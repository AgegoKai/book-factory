#!/usr/bin/env python3
"""Read-only readiness smoke test for light GPU workers."""

from __future__ import annotations

import argparse
import json
import urllib.request


WORKERS = {
    "sam2": {
        "url": "http://127.0.0.1:8188",
        "nodes": [
            "SAM2ModelLoader (segment anything2)",
            "SAM2PointSegment (segment anything2)",
        ],
    },
    "rmbg2": {"url": "http://127.0.0.1:8189", "nodes": ["RMBG"]},
    "lama": {"url": "http://127.0.0.1:8090", "path": "/api/v1/server-config"},
}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.load(response)


def check_worker(name: str, base_url: str | None) -> dict:
    config = WORKERS[name]
    url = (base_url or config["url"]).rstrip("/")
    if name in {"sam2", "rmbg2"}:
        stats = get_json(f"{url}/system_stats")
        nodes = get_json(f"{url}/object_info")
        missing = [node for node in config["nodes"] if node not in nodes]
        if missing:
            raise RuntimeError(f"{name}: missing nodes: {', '.join(missing)}")
        devices = stats.get("devices") or []
        if not any("nvidia" in str(device).lower() or "cuda" in str(device).lower() for device in devices):
            raise RuntimeError(f"{name}: ComfyUI does not report a CUDA/NVIDIA device")
        return {"worker": name, "status": "ready", "nodes": config["nodes"]}

    server_config = get_json(f"{url}{config['path']}")
    models = {item.get("name") for item in server_config.get("modelInfos", [])}
    if "lama" not in models:
        raise RuntimeError("lama: server does not report the LaMa model")
    return {"worker": name, "status": "ready", "model": "lama"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", choices=[*WORKERS, "all"])
    parser.add_argument("--base-url")
    args = parser.parse_args()
    names = list(WORKERS) if args.worker == "all" else [args.worker]
    for name in names:
        print(json.dumps(check_worker(name, args.base_url), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
