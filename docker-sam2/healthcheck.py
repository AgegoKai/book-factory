#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


MODEL = Path("/workspace/ComfyUI/models/sam2/sam2.1_hiera_large.pt")
EXPECTED = os.environ["NJS_SAM2_MODEL_SHA256"]
EXPECTED_SIZE = 898083611
REQUIRED_NODES = {
    "SAM2ModelLoader (segment anything2)",
    "SAM2PointSegment (segment anything2)",
}


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:8188{path}", timeout=5) as response:
        return json.load(response)


if not MODEL.is_file() or MODEL.stat().st_size != EXPECTED_SIZE:
    raise SystemExit(f"missing model: {MODEL}")
# The entrypoint verifies the full SHA-256 once. The recurring healthcheck only
# checks the immutable read-only mount and the live API to avoid hashing 898 MB
# every few seconds.
if len(EXPECTED) != 64:
    raise SystemExit("invalid expected checksum configuration")
stats = get_json("/system_stats")
if not any("nvidia" in str(device).lower() or "cuda" in str(device).lower() for device in stats.get("devices", [])):
    raise SystemExit("CUDA/NVIDIA device is not visible")
nodes = get_json("/object_info")
missing = REQUIRED_NODES.difference(nodes)
if missing:
    raise SystemExit(f"missing nodes: {sorted(missing)}")
