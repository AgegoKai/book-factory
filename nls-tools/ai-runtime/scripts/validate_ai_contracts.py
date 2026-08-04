#!/usr/bin/env python3
"""Validate versioned AI workflow/worker contracts without third-party packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMFY_MANIFESTS = (
    Path("docker-sam2/workflow-manifest.json"),
    Path("nls-tools/comfyui/rmbg2/workflows/workflow-manifest.json"),
)
LAMA_MANIFEST = Path("nls-tools/image-cleanup/lama/worker-manifest.json")
REQUIRED_SEMANTIC_OUTPUTS = {"transparent_image", "alpha_mask"}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_binding(path: Path, graph: dict, name: str, spec: dict, *, output: bool) -> list[str]:
    errors: list[str] = []
    binding = spec.get("binding", {})
    node_id = str(binding.get("nodeId", ""))
    if node_id not in graph:
        return [f"{path}: {name} binds missing node {node_id!r}"]
    node = graph[node_id]
    if output:
        if node.get("class_type") != "SaveImage":
            errors.append(f"{path}: output {name} must bind a SaveImage node")
        if binding.get("output") != "images":
            errors.append(f"{path}: output {name} must use semantic output 'images'")
    else:
        input_name = binding.get("input")
        if input_name not in node.get("inputs", {}):
            errors.append(f"{path}: input {name} binds missing {node_id}.{input_name}")
    return errors


def validate_comfy(root: Path, rel: Path) -> list[str]:
    path = root / rel
    data = read_json(path)
    errors: list[str] = []
    if data.get("schemaVersion") != 2:
        errors.append(f"{rel}: schemaVersion must be 2")
    if data.get("engine") != "comfyui":
        errors.append(f"{rel}: engine must be comfyui")
    if not SEMVER.fullmatch(str(data.get("version", ""))):
        errors.append(f"{rel}: version must be SemVer")

    workflow = data.get("workflow", {})
    api_rel = workflow.get("api")
    api_path = path.parent / str(api_rel or "")
    if not api_rel or not api_path.is_file():
        errors.append(f"{rel}: API workflow does not exist: {api_rel!r}")
        return errors
    ui_rel = workflow.get("ui")
    if ui_rel and not (path.parent / ui_rel).is_file():
        errors.append(f"{rel}: UI workflow does not exist: {ui_rel!r}")
    expected = workflow.get("sha256", "")
    if not SHA256.fullmatch(str(expected)):
        errors.append(f"{rel}: workflow.sha256 must contain 64 lowercase hex characters")
    elif digest(api_path) != expected:
        errors.append(f"{rel}: workflow sha256 does not match {api_rel}")

    graph = read_json(api_path)
    if not graph or not all(isinstance(value, dict) and "class_type" in value for value in graph.values()):
        errors.append(f"{rel}: workflow must use ComfyUI API format")
        return errors
    contract = data.get("contract", {})
    inputs = contract.get("inputs", {})
    outputs = contract.get("outputs", {})
    if "image" not in inputs:
        errors.append(f"{rel}: semantic input 'image' is required")
    if not REQUIRED_SEMANTIC_OUTPUTS.issubset(outputs):
        errors.append(f"{rel}: outputs must include transparent_image and alpha_mask")
    for name, spec in inputs.items():
        errors.extend(validate_binding(rel, graph, name, spec, output=False))
    for name, spec in outputs.items():
        errors.extend(validate_binding(rel, graph, name, spec, output=True))

    requirements = data.get("requirements", {})
    for model in requirements.get("models", []):
        if not SHA256.fullmatch(str(model.get("sha256", ""))):
            errors.append(f"{rel}: model {model.get('id')} has no pinned sha256")
    for node, revision in requirements.get("customNodes", {}).items():
        if not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
            errors.append(f"{rel}: custom node {node} is not pinned to a full commit")
    return errors


def validate_lama(root: Path) -> list[str]:
    data = read_json(root / LAMA_MANIFEST)
    errors: list[str] = []
    if data.get("schemaVersion") != 2 or not SEMVER.fullmatch(str(data.get("version", ""))):
        errors.append(f"{LAMA_MANIFEST}: schemaVersion 2 and SemVer are required")
    protocol = data.get("protocol", {})
    for key in ("readinessPath", "inpaintPath"):
        if not str(protocol.get(key, "")).startswith("/api/v1/"):
            errors.append(f"{LAMA_MANIFEST}: protocol.{key} must be a /api/v1 path")
    contract = data.get("contract", {})
    if not {"image", "mask"}.issubset(contract.get("inputs", {})):
        errors.append(f"{LAMA_MANIFEST}: stable image + mask input is required")
    image_out = contract.get("outputs", {}).get("image", {})
    if image_out.get("sameDimensionsAs") != "image":
        errors.append(f"{LAMA_MANIFEST}: output must preserve input dimensions")
    if contract.get("invariants", {}).get("modelsDownloadedAtRequestTime") is not False:
        errors.append(f"{LAMA_MANIFEST}: runtime model downloads must be disabled")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    for manifest in COMFY_MANIFESTS:
        try:
            errors.extend(validate_comfy(root, manifest))
        except ValueError as exc:
            errors.append(str(exc))
    try:
        errors.extend(validate_lama(root))
    except ValueError as exc:
        errors.append(str(exc))
    if errors:
        print("AI contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("AI contracts valid: 2 ComfyUI workflows and 1 LaMa worker")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
