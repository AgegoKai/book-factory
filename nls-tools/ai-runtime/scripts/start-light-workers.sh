#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime_root=$(cd -- "${script_dir}/.." && pwd)
repo_root=$(cd -- "${runtime_root}/../.." && pwd)
env_file=${1:-${runtime_root}/.env}

# Source the initializer so variables loaded from .env remain available for
# Compose interpolation and custom smoke-test ports.
source "${script_dir}/initialize-njs-ai-runtime.sh" all "${env_file}"

compose_files=(
  "${repo_root}/docker-sam2/compose.yaml"
  "${repo_root}/nls-tools/comfyui/rmbg2/docker/compose.yaml"
  "${repo_root}/nls-tools/image-cleanup/lama/docker/compose.yaml"
)

for compose_file in "${compose_files[@]}"; do
  docker compose --env-file "${env_file}" -f "${compose_file}" --profile light config --quiet
done
for compose_file in "${compose_files[@]}"; do
  docker compose --env-file "${env_file}" -f "${compose_file}" --profile light \
    up -d --build --wait --wait-timeout 300
done

python3 "${script_dir}/smoke_light_workers.py" sam2 \
  --base-url "http://127.0.0.1:${NJS_SAM2_PORT:-8188}"
python3 "${script_dir}/smoke_light_workers.py" rmbg2 \
  --base-url "http://127.0.0.1:${NJS_RMBG2_PORT:-8189}"
python3 "${script_dir}/smoke_light_workers.py" lama \
  --base-url "http://127.0.0.1:${NJS_LAMA_PORT:-8090}"
