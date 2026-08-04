#!/usr/bin/env python3
"""Repeatable GPU benchmark for RMBG-2.0, prompted SAM2.1 and Big-LaMa."""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
FIXTURES = ROOT / "fixtures/fixtures.json"


def request(url: str, *, data: bytes | None = None, content_type: str | None = None, timeout: float = 600) -> tuple[bytes, str]:
    headers = {"Accept": "application/json, image/png"}
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} {url}: {exc.read().decode(errors='replace')}") from exc


def request_json(url: str, payload: dict | None = None, timeout: float = 600) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    body, _ = request(url, data=data, content_type="application/json" if data else None, timeout=timeout)
    return json.loads(body)


def upload_comfy(server: str, path: Path) -> str:
    boundary = f"----NJS{uuid.uuid4().hex}"
    body = b"".join((
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode(),
        path.read_bytes(), b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode(),
    ))
    raw, _ = request(f"{server}/upload/image", data=body, content_type=f"multipart/form-data; boundary={boundary}")
    uploaded = json.loads(raw)
    return "/".join(filter(None, (uploaded.get("subfolder"), uploaded["name"])))


def download_comfy(server: str, item: dict) -> bytes:
    query = urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
    return request(f"{server}/view?{query}")[0]


def run_comfy(server: str, manifest_path: Path, image_path: Path, case: dict) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph_path = manifest_path.parent / manifest["workflow"]["api"]
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    uploaded = upload_comfy(server, image_path)
    for name, spec in manifest["contract"]["inputs"].items():
        binding = spec["binding"]
        if name == "image":
            value = uploaded
        elif name == "points":
            value = json.dumps(case.get("sam2Points", []))
        elif name == "negative_points":
            value = json.dumps(case.get("sam2NegativePoints", []))
        else:
            continue
        graph[binding["nodeId"]]["inputs"][binding["input"]] = value
    prefix = f"benchmark/{case['id']}/{uuid.uuid4().hex[:8]}"
    for spec in manifest["contract"]["outputs"].values():
        graph[spec["binding"]["nodeId"]]["inputs"]["filename_prefix"] = prefix
    started = time.perf_counter()
    prompt_id = request_json(f"{server}/prompt", {"prompt": graph})["prompt_id"]
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        history = request_json(f"{server}/history/{prompt_id}")
        if prompt_id in history:
            result = history[prompt_id]
            if result.get("status", {}).get("status_str") != "success":
                raise RuntimeError(json.dumps(result.get("status"), ensure_ascii=False))
            break
        time.sleep(0.25)
    else:
        raise TimeoutError(prompt_id)
    outputs = {}
    for name, spec in manifest["contract"]["outputs"].items():
        node_id = spec["binding"]["nodeId"]
        outputs[name] = download_comfy(server, result["outputs"][node_id]["images"][0])
    return {"latencySeconds": time.perf_counter() - started, "outputs": outputs}


def encode_image(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def run_lama(server: str, image_path: Path, mask_path: Path, case: dict) -> dict:
    payload = {
        "image": encode_image(image_path), "mask": encode_image(mask_path),
        "hd_strategy": case.get("hdStrategy", "Crop"),
        "hd_strategy_crop_margin": case.get("roiMargin", 128),
        "sd_keep_unmasked_area": True,
    }
    started = time.perf_counter()
    raw, content_type = request(f"{server}/api/v1/inpaint", data=json.dumps(payload).encode(), content_type="application/json")
    latency = time.perf_counter() - started
    if content_type == "application/json":
        response = json.loads(raw)
        encoded = response.get("image", response) if isinstance(response, dict) else response
        if isinstance(encoded, str):
            raw = base64.b64decode(encoded.split(",", 1)[-1])
    return {"latencySeconds": latency, "outputs": {"image": raw}}


class VramSampler:
    def __init__(self) -> None:
        self.values: list[int] = []
        self.baseline: int | None = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                value = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True)
                self.values.append(int(value.strip().splitlines()[0]))
            except (OSError, subprocess.SubprocessError, ValueError):
                return
            self.stop.wait(0.1)

    def __enter__(self) -> "VramSampler":
        try:
            value = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True)
            self.baseline = int(value.strip().splitlines()[0])
        except (OSError, subprocess.SubprocessError, ValueError):
            self.baseline = None
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set(); self.thread.join(timeout=2)


def mask_metrics(predicted: bytes, golden_path: Path) -> dict:
    pred = Image.open(io.BytesIO(predicted)).convert("L")
    gold = Image.open(golden_path).convert("L")
    if pred.size != gold.size:
        pred = pred.resize(gold.size, Image.Resampling.BILINEAR)
    p = pred.point(lambda value: 255 if value >= 128 else 0)
    g = gold.point(lambda value: 255 if value >= 128 else 0)
    tp = sum(v // 255 for v in ImageChops.multiply(p, g).getdata())
    fp = sum(v // 255 for v in ImageChops.subtract(p, g).getdata())
    fn = sum(v // 255 for v in ImageChops.subtract(g, p).getdata())
    union = tp + fp + fn
    return {"maskIoU": tp / union if union else 1.0, "maskF1": (2 * tp) / (2 * tp + fp + fn) if tp + fp + fn else 1.0}


def retouch_metrics(output: bytes, input_path: Path, mask_path: Path, expected_path: Path) -> dict:
    result = Image.open(io.BytesIO(output)).convert("RGB")
    source = Image.open(input_path).convert("RGB")
    expected = Image.open(expected_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    if result.size != source.size:
        return {"sameDimensions": False}
    difference = ImageChops.difference(result, source)
    outside = Image.composite(Image.new("RGB", result.size), difference, mask)
    extrema = outside.getextrema()
    max_delta = max(channel[1] for channel in extrema)
    inside_diff = ImageChops.difference(result, expected)
    mean = sum(ImageStat.Stat(inside_diff, mask=mask).mean) / 3
    return {"sameDimensions": True, "outsideMaskMaxDelta": max_delta, "insideMaskMeanError": mean}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", choices=("rmbg2", "sam2", "lama", "all"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rmbg-url", default="http://127.0.0.1:8189")
    parser.add_argument("--sam-url", default="http://127.0.0.1:8188")
    parser.add_argument("--lama-url", default="http://127.0.0.1:8090")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path)
    args = parser.parse_args()
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    workers = ("rmbg2", "sam2", "lama") if args.worker == "all" else (args.worker,)
    records = []
    for worker in workers:
        wanted = "retouch" if worker == "lama" else "remove-background"
        cases = [item for item in fixtures["cases"] if item["task"] == wanted]
        for case in cases:
            input_path = ROOT / case["input"]
            for index in range(args.repeats):
                with VramSampler() as vram:
                    if worker == "rmbg2":
                        result = run_comfy(args.rmbg_url, REPO / "nls-tools/comfyui/rmbg2/workflows/workflow-manifest.json", input_path, case)
                    elif worker == "sam2":
                        result = run_comfy(args.sam_url, REPO / "docker-sam2/workflow-manifest.json", input_path, case)
                    else:
                        result = run_lama(args.lama_url, input_path, ROOT / case["mask"], case)
                peak = max(vram.values) if vram.values else None
                record = {
                    "worker": worker, "fixture": case["id"], "run": index + 1,
                    "latencySeconds": round(result["latencySeconds"], 4),
                    "vramBaselineMiB": vram.baseline, "vramPeakMiB": peak,
                    "vramDeltaMiB": (peak - vram.baseline) if peak is not None and vram.baseline is not None else None,
                }
                if args.artifacts_dir:
                    artifact_dir = args.artifacts_dir / worker / case["id"] / f"run-{index + 1}"
                    artifact_dir.mkdir(parents=True, exist_ok=True)
                    for name, value in result["outputs"].items():
                        (artifact_dir / f"{name}.png").write_bytes(value)
                if worker == "lama":
                    record.update(retouch_metrics(result["outputs"]["image"], input_path, ROOT / case["mask"], ROOT / case["expected"]))
                elif case.get("goldenMask"):
                    record.update(mask_metrics(result["outputs"]["alpha_mask"], ROOT / case["goldenMask"]))
                records.append(record)
                print(json.dumps(record, ensure_ascii=False))
    report = {"schemaVersion": 1, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "repeats": args.repeats, "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
