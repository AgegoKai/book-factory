from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from ..config import settings


class LLMError(Exception):
    pass


class LLMProviderUnavailable(LLMError):
    """Raised when a provider is not configured (missing key/token).

    In auto-routing mode this is treated as a silent skip, not a hard error,
    so the error message is NOT included in the final "All providers failed" summary.
    """
    pass


@dataclass
class LLMConfig:
    """Runtime config that overrides global settings — built from UserSettings."""
    lm_studio_base_url: str = ""
    lm_studio_api_key: str = ""
    lm_studio_model: str = ""
    google_api_key: str = ""
    google_model: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""
    # OpenClaw OAuth — ChatGPT subscription gateway (no sk- API key required)
    openclaw_oauth_token: str = ""
    openclaw_base_url: str = ""
    openclaw_model: str = ""
    # auto = LM→Gemini→OpenRouter→OpenAI→OpenClaw; inne = tylko ten provider
    preferred_llm_provider: str = ""

    def resolve_preferred_provider(self) -> str:
        raw = (self.preferred_llm_provider or settings.preferred_llm_provider or "auto").strip().lower()
        allowed = {"auto", "lm_studio", "google_gemini", "openrouter", "openai", "openclaw"}
        return raw if raw in allowed else "auto"

    def resolve_lm_url(self) -> str:
        return (self.lm_studio_base_url or settings.lm_studio_base_url).rstrip("/")

    def resolve_lm_key(self) -> str:
        return self.lm_studio_api_key or settings.lm_studio_api_key

    def resolve_lm_model(self) -> str:
        return self.lm_studio_model or settings.lm_studio_model

    def resolve_google_key(self) -> str:
        return self.google_api_key or settings.google_api_key

    def resolve_google_model(self) -> str:
        return self.google_model or settings.google_model

    def resolve_openrouter_key(self) -> str:
        return self.openrouter_api_key or settings.openrouter_api_key

    def resolve_openrouter_model(self) -> str:
        return self.openrouter_model or settings.openrouter_model

    def resolve_openai_key(self) -> str:
        return self.openai_api_key or settings.openai_api_key

    def resolve_openai_base_url(self) -> str:
        return (self.openai_base_url or settings.openai_base_url).rstrip("/")

    def resolve_openai_model(self) -> str:
        return self.openai_model or settings.openai_model

    def resolve_openclaw_token(self) -> str:
        """Return only the access_token portion.

        Tokens are stored as ``access|refresh|expiry_epoch`` by the OAuth
        exchange endpoint.  Legacy plain tokens (no pipe) are returned as-is.
        """
        raw = self.openclaw_oauth_token or settings.openclaw_oauth_token
        if "|" in raw:
            return raw.split("|", 1)[0]
        return raw

    def resolve_openclaw_base_url(self) -> str:
        return (self.openclaw_base_url or settings.openclaw_base_url).rstrip("/")

    def resolve_openclaw_model(self) -> str:
        return self.openclaw_model or settings.openclaw_model



class LLMService:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout_seconds
        self._max_out = settings.llm_max_output_tokens

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        cfg: LLMConfig | None = None,
    ) -> tuple[str, str]:
        cfg = cfg or LLMConfig()
        errors: list[str] = []
        handlers: dict[str, Callable[[str, str], str]] = {
            "lm_studio": lambda s, u: self._call_lm_studio(s, u, cfg),
            "google_gemini": lambda s, u: self._call_google_gemini(s, u, cfg),
            "openrouter": lambda s, u: self._call_openrouter(s, u, cfg),
            "openai": lambda s, u: self._call_openai(s, u, cfg),
            "openclaw": lambda s, u: self._call_openclaw(s, u, cfg),
        }
        pref = cfg.resolve_preferred_provider()
        order = (
            ["openclaw", "lm_studio", "google_gemini", "openrouter", "openai"]
            if pref == "auto"
            else [pref]
        )
        for name in order:
            try:
                return handlers[name](system_prompt, user_prompt), name
            except LLMProviderUnavailable:
                # Provider not configured — skip silently in auto mode
                continue
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        if not errors:
            raise LLMError("No providers configured. Add an API key or OAuth token in Settings.")
        raise LLMError("All providers failed: " + " | ".join(errors))

    # ------------------------------------------------------------------ helpers

    def _chat_payload(self, system_prompt: str, user_prompt: str, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.75,
            # Not sent globally — OpenRouter and LM Studio each receive a model-appropriate limit
            # via _openrouter_payload() and _call_lm_studio() overrides below.
        }

    @staticmethod
    def _openrouter_heuristic_merge_system(model_slug: str) -> bool:
        """Known backends (e.g. Gemma via Google AI Studio) reject OpenAI-style system messages."""
        return "gemma" in (model_slug or "").lower()

    def _openrouter_messages_split(self, system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
        """Standard chat: system + user (preferred whenever the upstream supports it)."""
        sys_t = (system_prompt or "").strip()
        usr_t = (user_prompt or "").strip()
        if sys_t:
            return [
                {"role": "system", "content": sys_t},
                {"role": "user", "content": usr_t},
            ]
        return [{"role": "user", "content": usr_t}]

    def _openrouter_messages_merged(self, system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
        """Fallback: one user turn — for APIs that do not support developer/system channel."""
        sys_t = (system_prompt or "").strip()
        usr_t = (user_prompt or "").strip()
        if not sys_t:
            return [{"role": "user", "content": usr_t}]
        combined = (
            "[Instrukcje systemowe — stosuj bezwzględnie]\n"
            f"{sys_t}\n\n"
            "[Zadanie]\n"
            f"{usr_t}"
        )
        return [{"role": "user", "content": combined}]

    @staticmethod
    def _openrouter_error_needs_merged_user_only(status_code: int, data: dict[str, Any], response_text: str) -> bool:
        """HTTP 400 from upstream that indicates system/developer instruction is unsupported."""
        if status_code != 400:
            return False
        blob = json.dumps(data, ensure_ascii=False).lower()
        blob += " " + (response_text or "").lower()
        markers = (
            "developer instruction is not enabled",
            "system instruction is not enabled",
            "system role is not supported",
            "does not support system",
        )
        return any(m in blob for m in markers)

    def _openrouter_max_tokens(self) -> int:
        """
        Safe output-token cap for OpenRouter.
        Free models typically have 8 192 total context (input+output combined).
        A long system+user prompt can use 4 000+ tokens, leaving < 4 096 for output.
        We cap at 4 096 so `prompt + max_tokens` stays within typical model limits.
        If the user raised LLM_MAX_OUTPUT_TOKENS explicitly, honour it (they know their model).
        """
        return min(self._max_out, 4096)

    def _extract_openai_style_message(self, message: dict[str, Any]) -> str:
        """Normalize assistant message content from OpenAI-compatible APIs (incl. OpenRouter)."""
        content = message.get("content")
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and "text" in part:
                    parts.append(str(part.get("text") or ""))
                elif "text" in part:
                    parts.append(str(part.get("text") or ""))
            return "\n".join(parts).strip()
        return str(content).strip()

    def _extract_chat_response(self, response_json: dict[str, Any], provider_label: str) -> str:
        if "error" in response_json and response_json["error"]:
            err = response_json["error"]
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code") or json.dumps(err)
            else:
                msg = str(err)
            raise LLMError(f"{provider_label} API error: {msg}")

        choices = response_json.get("choices") or []
        if not choices:
            raise LLMError(f"{provider_label}: empty choices in response")

        choice0 = choices[0]
        if isinstance(choice0, dict) and choice0.get("error"):
            err = choice0["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMError(f"{provider_label} choice error: {msg}")

        # Non-chat completion shape (rare)
        if isinstance(choice0, dict) and "text" in choice0 and choice0.get("text") is not None:
            return str(choice0["text"]).strip()

        message = choice0.get("message") if isinstance(choice0, dict) else None
        if not isinstance(message, dict):
            raise LLMError(f"{provider_label}: missing message in choice")

        text = self._extract_openai_style_message(message)
        if text:
            return text

        # Reasoning models: some providers put visible text in refusal or separate fields
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise LLMError(f"{provider_label}: model refused: {refusal[:500]}")

        finish = choice0.get("finish_reason") if isinstance(choice0, dict) else None
        raise LLMError(
            f"{provider_label}: empty assistant content (finish_reason={finish!r}). "
            "Sprawdź model, limity tokenów lub saldo OpenRouter."
        )

    def _extract(self, response_json: dict[str, Any]) -> str:
        return self._extract_chat_response(response_json, "Provider")

    def _openrouter_payload(
        self, system_prompt: str, user_prompt: str, model: str, *, merge_system: bool
    ) -> dict[str, Any]:
        """
        OpenRouter: suffix ':online' → plugins web. Prefer split system+user; merge only when
        heuristic or a 400 retry says the upstream rejects system messages (e.g. Gemma on Google).
        """
        resolved_model = model[: -len(":online")] if model.endswith(":online") else model
        messages = (
            self._openrouter_messages_merged(system_prompt, user_prompt)
            if merge_system
            else self._openrouter_messages_split(system_prompt, user_prompt)
        )
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": 0.75,
            "max_tokens": self._openrouter_max_tokens(),
        }
        if model.endswith(":online"):
            payload["plugins"] = [{"id": "web"}]
        return payload

    # --------------------------------------------------------------- providers

    def _call_lm_studio(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        url = cfg.resolve_lm_url() + "/chat/completions"
        model = cfg.resolve_lm_model()
        api_key = cfg.resolve_lm_key()
        payload = self._chat_payload(system_prompt, user_prompt, model)
        payload["max_tokens"] = self._max_out  # LM Studio: use full configured limit
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return self._extract_chat_response(response.json(), "LM Studio")

    def _call_google_gemini(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        api_key = cfg.resolve_google_key()
        if not api_key:
            raise LLMError("GOOGLE_API_KEY missing")
        model = cfg.resolve_google_model()
        url = (
            settings.google_base_url.rstrip("/")
            + f"/models/{model}:generateContent?key={api_key}"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.75,
                "maxOutputTokens": min(self._max_out, 8192),
            },
        }
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("No candidates returned")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "\n".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise LLMError("Empty Gemini response")
        return text

    def _call_openrouter(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        api_key = cfg.resolve_openrouter_key()
        if not api_key:
            raise LLMError("OPENROUTER_API_KEY missing")
        model = cfg.resolve_openrouter_model()
        if not model or not model.strip():
            raise LLMError("OPENROUTER_MODEL is empty — ustaw model w Ustawieniach lub .env")

        url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        model_raw = model.strip()
        merge = self._openrouter_heuristic_merge_system(model_raw)

        referer = (settings.openrouter_http_referer or "").strip() or "https://localhost"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-Title": settings.app_name,
        }

        def _post(payload: dict[str, Any]) -> tuple[requests.Response, dict[str, Any]]:
            r = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            try:
                d = r.json()
            except ValueError:
                d = {}
            return r, d

        payload = self._openrouter_payload(system_prompt, user_prompt, model_raw, merge_system=merge)
        response, data = _post(payload)

        if (
            not response.ok
            and not merge
            and self._openrouter_error_needs_merged_user_only(
                response.status_code, data, response.text or ""
            )
        ):
            merge = True
            payload = self._openrouter_payload(system_prompt, user_prompt, model_raw, merge_system=True)
            response, data = _post(payload)

        if not response.ok:
            msg = self._format_http_error_body(response, data)
            raise LLMError(f"OpenRouter HTTP {response.status_code}: {msg}")

        return self._extract_chat_response(data, "OpenRouter")

    @staticmethod
    def _format_http_error_body(response: requests.Response, data: dict[str, Any]) -> str:
        """
        Extract the most useful error message from an OpenRouter (or OpenAI-compatible) error.
        OpenRouter wraps provider errors as:
          {"error": {"code": 400, "message": "Provider returned error.",
                     "metadata": {"raw": "<actual upstream error>", "provider_name": "..."}}}
        We surface the raw upstream error when present.
        """
        err = data.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            metadata = err.get("metadata") or {}
            raw = metadata.get("raw", "") if isinstance(metadata, dict) else ""
            provider_name = metadata.get("provider_name", "") if isinstance(metadata, dict) else ""
            parts = [msg] if msg else []
            if provider_name:
                parts.append(f"[{provider_name}]")
            if raw:
                raw_str = raw if isinstance(raw, str) else json.dumps(raw)
                parts.append(f"raw: {raw_str[:400]}")
            return " ".join(parts) or json.dumps(err)[:300]
        if err:
            return str(err)[:300]
        text = (response.text or "").strip()
        return text[:800] if text else response.reason


    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        """Decode the middle segment of a JWT without verification."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return {}
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _extract_chatgpt_account_id(token: str) -> str | None:
        payload = LLMService._decode_jwt_payload(token)
        auth = payload.get("https://api.openai.com/auth") or {}
        return auth.get("chatgpt_account_id") or auth.get("chatgpt_account_user_id") or None

    def _call_openclaw(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        """Call ChatGPT directly using an OAuth access token.

        Uses the OpenAI Responses API at https://chatgpt.com/backend-api/codex/responses
        with SSE streaming (stream:true is required — the endpoint does not support
        stream:false).  Event types follow the Responses API spec:
          - response.output_text.delta  → incremental text
          - response.done / response.completed → final response with full output

        The access token comes from the OAuth PKCE flow in Settings → ChatGPT Plus / Pro.
        """
        token = cfg.resolve_openclaw_token()
        if not token:
            raise LLMProviderUnavailable(
                "ChatGPT OAuth token missing — podepnij konto w Ustawieniach → ChatGPT Plus / Pro"
            )

        # Strip "openai-codex/" prefix — the actual API uses plain model IDs
        raw_model = cfg.resolve_openclaw_model() or "gpt-5.4"
        model_id = raw_model.removeprefix("openai-codex/") if raw_model.startswith("openai-codex/") else raw_model

        account_id = self._extract_chatgpt_account_id(token)

        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "OpenAI-Beta": "responses=experimental",
            "originator": "book-factory",
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        payload: dict[str, Any] = {
            "model": model_id,
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": [{"role": "user", "content": user_prompt}],
            "text": {"verbosity": "low"},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "max_output_tokens": self._max_out,
        }

        url = "https://chatgpt.com/backend-api/codex/responses"

        with requests.post(
            url, headers=headers, json=payload,
            stream=True, timeout=self.timeout,
        ) as response:
            if response.status_code == 401:
                raise LLMError(
                    "ChatGPT token wygasł lub jest nieprawidłowy (HTTP 401). "
                    "Podepnij konto ponownie w Ustawieniach → ChatGPT Plus / Pro."
                )
            if response.status_code == 403:
                raise LLMError(
                    "ChatGPT odmówił dostępu (HTTP 403) — sprawdź czy konto ma aktywny plan Plus/Pro/Codex."
                )
            if not response.ok:
                body = response.text[:400]
                raise LLMError(f"ChatGPT zwrócił HTTP {response.status_code}: {body}")

            text_parts: list[str] = []
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str in ("[DONE]", ""):
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                # Incremental text delta
                if etype == "response.output_text.delta":
                    text_parts.append(event.get("delta", ""))

                # Final response object (response.done or response.completed)
                elif etype in ("response.done", "response.completed"):
                    resp_obj = event.get("response") or {}
                    if not text_parts:
                        # Extract from final output list as fallback
                        for item in (resp_obj.get("output") or []):
                            if item.get("type") == "message":
                                for part in (item.get("content") or []):
                                    if part.get("type") == "output_text":
                                        text_parts.append(part.get("text", ""))
                    break

                # Error event
                elif etype == "error":
                    msg = event.get("message") or event.get("error") or str(event)
                    raise LLMError(f"ChatGPT error: {msg[:300]}")

        result = "".join(text_parts).strip()
        if not result:
            raise LLMError("ChatGPT zwrócił pustą odpowiedź")
        return result

    def _call_openai(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        """Call the official OpenAI API (or any OpenAI-compatible endpoint).

        Uses the same OpenAI chat-completions wire format as LM Studio, but with
        the official base URL and enforces a model.  The API key is the standard
        "sk-..." Bearer token from platform.openai.com.
        """
        api_key = cfg.resolve_openai_key()
        if not api_key:
            raise LLMProviderUnavailable("OPENAI_API_KEY missing — add it in Settings → OpenAI")
        model = cfg.resolve_openai_model()
        if not model:
            raise LLMError("OPENAI_MODEL is empty — set a model in Settings → OpenAI")
        base_url = cfg.resolve_openai_base_url()
        url = base_url + "/chat/completions"
        payload = self._chat_payload(system_prompt, user_prompt, model)
        payload["max_tokens"] = self._max_out
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return self._extract_chat_response(response.json(), "OpenAI")


llm_service = LLMService()
