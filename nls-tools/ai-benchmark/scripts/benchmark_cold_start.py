#!/usr/bin/env python3
"""Measure an isolated worker container start and its first GPU inference."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

import benchmark_workers as bench


CONFIG = {
    "sam2": {
        "image": "local/comfyui-sam2-click:0.13.0", "containerPort": 8188,
        "modelTarget": "/workspace/ComfyUI/models", "health": "/system_stats",
        "env": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "NJS_SAM2_MODEL_SHA256": "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318"},
    },
    "rmbg2": {
        "image": "local/comfyui-rmbg2:0.13.0", "containerPort": 8189,
        "modelTarget": "/workspace/ComfyUI/models/RMBG", "health": "/system_stats",
        "env": {
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "NJS_RMBG2_MODEL_SHA256": "566ed80c3d95f87ada6864d4cbe2290a1c5eb1c7bb0b123e984f60f76b02c3a7",
            "NJS_RMBG2_CONFIG_SHA256": "c97ea21569daf66b205491a4635147dd3bc42c7c168b89d7d75b53f67ef548ae",
            "NJS_RMBG2_CODE_SHA256": "8f498727f4bdb7dfaa4d66190f0ebf55392bda62c1b4f224be39f9b750a8915d",
            "NJS_RMBG2_CONFIG_CODE_SHA256": "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52",
        },
    },
    "lama": {
        "image": "local/lama-cleanup:1.1.0", "containerPort": 8080,
        "modelTarget": "/data/models", "health": "/api/v1/server-config",
        "env": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "NJS_BIG_LAMA_SHA256": "344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9"},
    },
}


def docker_run_args(worker: str, model_dir: Path, work_root: Path, port: int) -> tuple[str, list[str]]:
    cfg = CONFIG[worker]
    name = f"njs-bench-{worker}-{uuid.uuid4().hex[:8]}"
    dirs = {key: work_root / worker / key for key in ("input", "output", "user", "temp", "cache")}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    args = ["docker", "run", "-d", "--rm", "--name", name, "--gpus", "all", "--shm-size", "8g", "-p", f"127.0.0.1:{port}:{cfg['containerPort']}"]
    for key, value in cfg["env"].items():
        args.extend(("-e", f"{key}={value}"))
    args.extend(("-v", f"{model_dir.resolve()}:{cfg['modelTarget']}:ro"))
    if worker == "lama":
        args.extend(("-v", f"{dirs['input'].resolve()}:/data/input", "-v", f"{dirs['output'].resolve()}:/data/output", "-v", f"{dirs['cache'].resolve()}:/root/.cache"))
    else:
        args.extend(("-v", f"{dirs['input'].resolve()}:/workspace/ComfyUI/input", "-v", f"{dirs['output'].resolve()}:/workspace/ComfyUI/output", "-v", f"{dirs['user'].resolve()}:/workspace/ComfyUI/user", "-v", f"{dirs['temp'].resolve()}:/workspace/ComfyUI/temp", "-v", f"{dirs['cache'].resolve()}:/workspace/cache/huggingface"))
    args.append(cfg["image"])
    return name, args


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", choices=CONFIG)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    name, command = docker_run_args(args.worker, args.model_dir, args.work_root, args.port)
    base = f"http://127.0.0.1:{args.port}"
    fixtures = json.loads(bench.FIXTURES.read_text(encoding="utf-8"))
    task = "retouch" if args.worker == "lama" else "remove-background"
    case = next(item for item in fixtures["cases"] if item["task"] == task)
    started = time.perf_counter()
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 240
        while True:
            try:
                bench.request_json(base + CONFIG[args.worker]["health"], timeout=3)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{name} did not become ready")
                time.sleep(0.5)
        readiness = time.perf_counter() - started
        with bench.VramSampler() as vram:
            if args.worker == "sam2":
                result = bench.run_comfy(base, bench.REPO / "docker-sam2/workflow-manifest.json", bench.ROOT / case["input"], case)
            elif args.worker == "rmbg2":
                result = bench.run_comfy(base, bench.REPO / "nls-tools/comfyui/rmbg2/workflows/workflow-manifest.json", bench.ROOT / case["input"], case)
            else:
                result = bench.run_lama(base, bench.ROOT / case["input"], bench.ROOT / case["mask"], case)
        peak = max(vram.values) if vram.values else None
        record = {
            "worker": args.worker, "image": CONFIG[args.worker]["image"],
            "containerReadinessSeconds": round(readiness, 4),
            "firstInferenceSeconds": round(result["latencySeconds"], 4),
            "vramBaselineMiB": vram.baseline, "vramPeakMiB": peak,
            "vramDeltaMiB": peak - vram.baseline if peak is not None and vram.baseline is not None else None,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record))
        return 0
    finally:
        subprocess.run(["docker", "stop", "--timeout", "5", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
