#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


MODEL = Path("/workspace/ComfyUI/models/RMBG/RMBG-2.0/model.safetensors")
EXPECTED = os.environ["NJS_RMBG2_MODEL_SHA256"]


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:8189{path}", timeout=5) as response:
        return json.load(response)


if not MODEL.is_file() or MODEL.stat().st_size != 884878856:
    raise SystemExit(f"missing or truncated model: {MODEL}")
if len(EXPECTED) != 64:
    raise SystemExit("invalid expected checksum configuration")
stats = get_json("/system_stats")
if not any("nvidia" in str(device).lower() or "cuda" in str(device).lower() for device in stats.get("devices", [])):
    raise SystemExit("CUDA/NVIDIA device is not visible")
nodes = get_json("/object_info")
if "RMBG" not in nodes:
    raise SystemExit("RMBG custom node is unavailable")
