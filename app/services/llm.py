from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

from ..config import settings


class LLMError(Exception):
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


class LLMService:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout_seconds

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        cfg: LLMConfig | None = None,
    ) -> tuple[str, str]:
        cfg = cfg or LLMConfig()
        errors: list[str] = []
        providers = [
            ("lm_studio", lambda s, u: self._call_lm_studio(s, u, cfg)),
            ("google_gemini", lambda s, u: self._call_google_gemini(s, u, cfg)),
            ("openrouter", lambda s, u: self._call_openrouter(s, u, cfg)),
        ]
        for name, handler in providers:
            try:
                return handler(system_prompt, user_prompt), name
            except Exception as exc:
                errors.append(f"{name}: {exc}")

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
            "max_tokens": 4096,
        }

    def _extract(self, response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices") or []
        if not choices:
            raise LLMError("No choices returned")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            ).strip()
        return str(content or "").strip()

    # --------------------------------------------------------------- providers

    def _call_lm_studio(self, system_prompt: str, user_prompt: str, cfg: LLMConfig) -> str:
        url = cfg.resolve_lm_url() + "/chat/completions"
        model = cfg.resolve_lm_model()
        api_key = cfg.resolve_lm_key()
        payload = self._chat_payload(system_prompt, user_prompt, model)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return self._extract(response.json())

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
            "generationConfig": {"temperature": 0.75, "maxOutputTokens": 4096},
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
        url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        payload = self._chat_payload(system_prompt, user_prompt, model)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://book-factory.local",
            "X-Title": settings.app_name,
        }
        response = requests.post(
            url, headers=headers, data=json.dumps(payload), timeout=self.timeout
        )
        response.raise_for_status()
        return self._extract(response.json())


llm_service = LLMService()
