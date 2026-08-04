#!/usr/bin/env python3
"""Fast readiness check for the local LaMa worker."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import torch


MODEL_FILE = Path("/data/models/torch/hub/checkpoints/big-lama.pt")
MODEL_SIZE = 205669692


def main() -> int:
    expected_checksum = os.environ.get("NJS_BIG_LAMA_SHA256", "")
    if len(expected_checksum) != 64:
        raise RuntimeError("NJS_BIG_LAMA_SHA256 is missing or malformed")
    if not MODEL_FILE.is_file() or MODEL_FILE.stat().st_size != MODEL_SIZE:
        raise RuntimeError(f"missing or invalid-size model: {MODEL_FILE}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not visible")
    with urllib.request.urlopen(
        "http://127.0.0.1:8080/api/v1/server-config", timeout=5
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"server-config returned HTTP {response.status}")
        config = json.load(response)
    models = {item.get("name") for item in config.get("modelInfos", [])}
    if "lama" not in models:
        raise RuntimeError("IOPaint does not report the LaMa model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
