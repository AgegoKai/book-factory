from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import requests

from ..config import settings


class HumanCheckError(Exception):
    pass


@dataclass
class HumanCheckConfig:
    email: str = ""
    api_key: str = ""
    sandbox: bool | None = None

    def resolve_email(self) -> str:
        return (self.email or settings.copyleaks_email).strip()

    def resolve_api_key(self) -> str:
        return (self.api_key or settings.copyleaks_api_key).strip()

    def resolve_sandbox(self) -> bool:
        if self.sandbox is None:
            return bool(settings.copyleaks_sandbox)
        return bool(self.sandbox)


class HumanCheckService:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout_seconds
        self._token_cache: dict[str, tuple[str, float]] = {}

    def analyze_text(self, text: str, *, language: str = "", cfg: HumanCheckConfig | None = None) -> dict:
        cfg = cfg or HumanCheckConfig()
        normalized = (text or "").strip()
        if len(normalized) < 255:
            raise HumanCheckError("Human check needs at least 255 characters of text.")
        if len(normalized) > 25000:
            raise HumanCheckError("Human check supports up to 25,000 characters per scan.")

        token = self._get_token(cfg)
        submission = {
            "text": normalized,
            "sandbox": cfg.resolve_sandbox(),
            "explain": True,
            "sensitivity": 2,
        }
        lang = (language or "").strip().lower()
        if lang:
            submission["language"] = lang.split("-")[0]

        scan_id = str(uuid.uuid4())
        url = settings.copyleaks_api_base_url.rstrip("/") + f"/writer-detector/{scan_id}/check"
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=submission,
            timeout=self.timeout,
        )
        if not response.ok:
            raise HumanCheckError(f"Copyleaks HTTP {response.status_code}: {response.text[:400]}")
        data = response.json()
        summary = data.get("summary") or {}
        scanned = data.get("scannedDocument") or {}
        return {
            "provider": "copyleaks",
            "human_score": float(summary.get("human") or 0.0),
            "ai_score": float(summary.get("ai") or 0.0),
            "total_words": int(scanned.get("totalWords") or 0),
            "checked_at": scanned.get("creationTime") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model_version": data.get("modelVersion") or "",
            "scan_id": scanned.get("scanId") or scan_id,
            "summary": summary,
            "results": data.get("results") or [],
            "explain": data.get("explain") or {},
            "raw": data,
        }

    def _get_token(self, cfg: HumanCheckConfig) -> str:
        email = cfg.resolve_email()
        api_key = cfg.resolve_api_key()
        if not email or not api_key:
            raise HumanCheckError("Copyleaks email and API key are required.")

        cache_key = f"{email}:{api_key}"
        cached = self._token_cache.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]

        url = settings.copyleaks_identity_base_url.rstrip("/") + "/account/login/api"
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"email": email, "key": api_key},
            timeout=self.timeout,
        )
        if not response.ok:
            raise HumanCheckError(f"Copyleaks auth failed: HTTP {response.status_code}: {response.text[:300]}")

        data = response.json()
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise HumanCheckError("Copyleaks auth returned an empty token.")

        self._token_cache[cache_key] = (token, time.time() + 60 * 60 * 48)
        return token


human_check_service = HumanCheckService()
