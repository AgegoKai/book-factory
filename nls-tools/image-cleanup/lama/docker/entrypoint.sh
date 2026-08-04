#!/usr/bin/env bash
set -euo pipefail

model_file="/data/models/torch/hub/checkpoints/big-lama.pt"
echo "${NJS_BIG_LAMA_SHA256}  ${model_file}" | sha256sum --check --status || {
    echo "Missing or invalid Big-LaMa model. Run Initialize-NjsAiRuntime.ps1 before starting the worker." >&2
    exit 1
}

python - <<'PY'
import sys
import torch

if not torch.cuda.is_available():
    print("BŁĄD: PyTorch nie widzi karty NVIDIA/CUDA w kontenerze.", file=sys.stderr)
    print("Sprawdź Docker Desktop, WSL2 i NVIDIA Container Toolkit.", file=sys.stderr)
    raise SystemExit(1)

print(f"LaMa użyje GPU: {torch.cuda.get_device_name(0)}")
print(f"PyTorch: {torch.__version__}; CUDA: {torch.version.cuda}")
PY

exec iopaint start \
    --host=0.0.0.0 \
    --port=8080 \
    --model=lama \
    --device=cuda \
    --model-dir=/data/models \
    --input=/data/input \
    --output-dir=/data/output \
    --quality=100
