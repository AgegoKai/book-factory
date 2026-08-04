#!/usr/bin/env bash
set -euo pipefail

workflow_dir=/workspace/ComfyUI/user/default/workflows
mkdir -p "${workflow_dir}" /workspace/ComfyUI/input /workspace/ComfyUI/output /workspace/ComfyUI/temp /workspace/ComfyUI/models/RMBG
model_dir=/workspace/ComfyUI/models/RMBG/RMBG-2.0
{
  echo "${NJS_RMBG2_MODEL_SHA256}  ${model_dir}/model.safetensors"
  echo "${NJS_RMBG2_CONFIG_SHA256}  ${model_dir}/config.json"
  echo "${NJS_RMBG2_CODE_SHA256}  ${model_dir}/birefnet.py"
  echo "${NJS_RMBG2_CONFIG_CODE_SHA256}  ${model_dir}/BiRefNet_config.py"
} | sha256sum --check --status || {
  echo "Missing or invalid RMBG-2.0 artifacts. Run Initialize-NjsAiRuntime.ps1 before starting the worker." >&2
  exit 1
}

versioned_gui="${workflow_dir}/RemoveBg by RMBG-2.0 v1.0.0.json"
versioned_api="${workflow_dir}/RemoveBg by RMBG-2.0 API v1.0.0.json"
[[ -f "${versioned_gui}" ]] || cp "/opt/default-workflows/RemoveBg by RMBG-2.0.json" "${versioned_gui}"
[[ -f "${versioned_api}" ]] || cp "/opt/default-workflows/RemoveBg by RMBG-2.0 API.json" "${versioned_api}"
[[ -f "${workflow_dir}/RemoveBg by RMBG-2.0.json" ]] || cp "${versioned_gui}" "${workflow_dir}/RemoveBg by RMBG-2.0.json"
[[ -f "${workflow_dir}/RemoveBg by RMBG-2.0 API.json" ]] || cp "${versioned_api}" "${workflow_dir}/RemoveBg by RMBG-2.0 API.json"
cp "/opt/default-workflows/rmbg2-remove-background.manifest.json" "${workflow_dir}/rmbg2-remove-background.manifest.json"
if [[ ! -f "/workspace/ComfyUI/input/RMBG2_bear_edge_test.png" ]]; then
  cp "/opt/default-input/RMBG2_bear_edge_test.png" "/workspace/ComfyUI/input/RMBG2_bear_edge_test.png"
fi

exec "$@"
