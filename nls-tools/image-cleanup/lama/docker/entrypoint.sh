#!/usr/bin/env bash
set -euo pipefail

model_url="https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"
model_sha256="344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9"
model_file="/data/models/torch/hub/checkpoints/big-lama.pt"
model_download="${model_file}.download"

checksum_ok() {
    [[ -s "$1" ]] && echo "${model_sha256}  $1" | sha256sum --check --status
}

if ! checksum_ok "$model_file"; then
    mkdir -p "$(dirname "$model_file")"
    if ! checksum_ok "$model_download"; then
        echo "Pobieranie modelu LaMa (około 196 MB)..."
        curl --location --fail --retry 5 --retry-delay 2 \
            --continue-at - --output "$model_download" "$model_url"
    fi
    checksum_ok "$model_download"
    mv -f "$model_download" "$model_file"
    echo "Model LaMa pobrany i zweryfikowany."
fi

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
