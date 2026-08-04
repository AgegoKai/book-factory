#!/usr/bin/env python3
"""Sweep LaMa resolution using Crop + margin without storing artifacts in production."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

import benchmark_workers as bench


def resize(source: Path, destination: Path, long_edge: int, *, mask: bool = False) -> None:
    with Image.open(source) as opened:
        image = opened.convert("L" if mask else "RGB")
    scale = long_edge / max(image.size)
    size = (round(image.width * scale), round(image.height * scale))
    image.resize(size, Image.Resampling.NEAREST if mask else Image.Resampling.LANCZOS).save(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lama-url", default="http://127.0.0.1:8090")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--long-edges", type=int, nargs="+", default=(2048, 3072, 4096))
    args = parser.parse_args()
    manifest = json.loads(bench.FIXTURES.read_text(encoding="utf-8"))
    source = next(case for case in manifest["cases"] if case["id"] == "white-ceramic-cup-retouch-thick")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for edge in args.long_edges:
        image_path = args.work_dir / f"input-{edge}.png"
        mask_path = args.work_dir / f"mask-{edge}.png"
        expected_path = args.work_dir / f"expected-{edge}.png"
        resize(bench.ROOT / source["input"], image_path, edge)
        resize(bench.ROOT / source["mask"], mask_path, edge, mask=True)
        resize(bench.ROOT / source["expected"], expected_path, edge)
        case = {**source, "hdStrategy": "Crop", "roiMargin": 128}
        with bench.VramSampler() as vram:
            result = bench.run_lama(args.lama_url, image_path, mask_path, case)
        peak = max(vram.values) if vram.values else None
        record = {
            "longEdgePx": edge, "width": Image.open(image_path).width, "height": Image.open(image_path).height,
            "latencySeconds": round(result["latencySeconds"], 4), "vramBaselineMiB": vram.baseline,
            "vramPeakMiB": peak, "vramDeltaMiB": peak - vram.baseline if peak is not None and vram.baseline is not None else None,
            **bench.retouch_metrics(result["outputs"]["image"], image_path, mask_path, expected_path),
        }
        records.append(record); print(json.dumps(record))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schemaVersion": 1, "records": records}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
