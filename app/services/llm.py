from __future__ import annotations

import json
from typing import Any

import requests

from ..config import settings


class LLMError(Exception):
    pass


class LLMService:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        errors: list[str] = []
        try:
            return self._call_lm_studio(system_prompt, user_prompt), "lm_studio"
        except Exception as exc:
            errors.append(f"lm_studio: {exc}")

        try:
            return self._call_openrouter(system_prompt, user_prompt), "openrouter"
        except Exception as exc:
            errors.append(f"openrouter: {exc}")

        raise LLMError("All providers failed: " + " | ".join(errors))

    def _chat_payload(self, system_prompt: str, user_prompt: str, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
        }

    def _extract(self, response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices") or []
        if not choices:
            raise LLMError("No choices returned")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        return str(content or "").strip()

    def _call_lm_studio(self, system_prompt: str, user_prompt: str) -> str:
        url = settings.lm_studio_base_url.rstrip("/") + "/chat/completions"
        payload = self._chat_payload(system_prompt, user_prompt, settings.lm_studio_model)
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return self._extract(response.json())

    def _call_openrouter(self, system_prompt: str, user_prompt: str) -> str:
        if not settings.openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY missing")
        url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        payload = self._chat_payload(system_prompt, user_prompt, settings.openrouter_model)
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openclaw.local/book-factory",
            "X-Title": settings.app_name,
        }
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
        response.raise_for_status()
        return self._extract(response.json())


llm_service = LLMService()
