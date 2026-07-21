#!/usr/bin/env bash
set -euo pipefail

workflow_dir=/workspace/ComfyUI/user/default/workflows
mkdir -p "${workflow_dir}" /workspace/ComfyUI/input /workspace/ComfyUI/output /workspace/ComfyUI/temp
cp "/opt/default-workflows/RemoveBg by SAM2.json" "${workflow_dir}/RemoveBg by SAM2.json"
if [[ ! -f "/workspace/ComfyUI/input/SAM2_bear_edge_test.png" ]]; then
  cp "/opt/default-input/SAM2_bear_edge_test.png" "/workspace/ComfyUI/input/SAM2_bear_edge_test.png"
fi

exec "$@"
