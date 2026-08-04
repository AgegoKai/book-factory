#!/usr/bin/env bash
set -euo pipefail

workflow_dir=/workspace/ComfyUI/user/default/workflows
mkdir -p "${workflow_dir}" /workspace/ComfyUI/input /workspace/ComfyUI/output /workspace/ComfyUI/temp
model_file=/workspace/ComfyUI/models/sam2/sam2.1_hiera_large.pt
echo "${NJS_SAM2_MODEL_SHA256}  ${model_file}" | sha256sum --check --status || {
  echo "Missing or invalid SAM2 model. Run Initialize-NjsAiRuntime.ps1 before starting the worker." >&2
  exit 1
}

versioned_workflow="${workflow_dir}/RemoveBg by SAM2 v1.0.0.json"
[[ -f "${versioned_workflow}" ]] || cp "/opt/default-workflows/RemoveBg by SAM2.json" "${versioned_workflow}"
[[ -f "${workflow_dir}/RemoveBg by SAM2.json" ]] || cp "${versioned_workflow}" "${workflow_dir}/RemoveBg by SAM2.json"
cp "/opt/default-workflows/sam2-point-segmentation.manifest.json" "${workflow_dir}/sam2-point-segmentation.manifest.json"
if [[ ! -f "/workspace/ComfyUI/input/SAM2_bear_edge_test.png" ]]; then
  cp "/opt/default-input/SAM2_bear_edge_test.png" "/workspace/ComfyUI/input/SAM2_bear_edge_test.png"
fi

exec "$@"
