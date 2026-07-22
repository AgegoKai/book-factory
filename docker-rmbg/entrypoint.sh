#!/usr/bin/env bash
set -euo pipefail

workflow_dir=/workspace/ComfyUI/user/default/workflows
mkdir -p "${workflow_dir}" /workspace/ComfyUI/input /workspace/ComfyUI/output /workspace/ComfyUI/temp /workspace/ComfyUI/models/RMBG
cp "/opt/default-workflows/RemoveBg by RMBG-2.0.json" "${workflow_dir}/RemoveBg by RMBG-2.0.json"
cp "/opt/default-workflows/RemoveBg by RMBG-2.0 API.json" "${workflow_dir}/RemoveBg by RMBG-2.0 API.json"
if [[ ! -f "/workspace/ComfyUI/input/RMBG2_bear_edge_test.png" ]]; then
  cp "/opt/default-input/RMBG2_bear_edge_test.png" "/workspace/ComfyUI/input/RMBG2_bear_edge_test.png"
fi

exec "$@"
