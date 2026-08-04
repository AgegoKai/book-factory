#!/usr/bin/env bash
set -euo pipefail

worker=${1:-}
env_file=${2:-}
case "${worker}" in
  sam2|rmbg2|lama|all) ;;
  *) echo "Usage: $0 {sam2|rmbg2|lama|all} [env-file]" >&2; exit 2 ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime_root=$(cd -- "${script_dir}/.." && pwd)
env_file=${env_file:-${runtime_root}/.env}

load_dotenv() {
  local file=$1 line name value
  [[ -f "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line=${line%$'\r'}
    [[ "${line}" =~ ^[[:space:]]*$ || "${line}" =~ ^[[:space:]]*# ]] && continue
    name=${line%%=*}
    value=${line#*=}
    name=${name//[[:space:]]/}
    [[ "${name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
      echo "Invalid variable name in ${file}: ${name}" >&2
      exit 2
    }
    if [[ -z ${!name+x} ]]; then
      value=${value#\"}; value=${value%\"}
      value=${value#\'}; value=${value%\'}
      export "${name}=${value}"
    fi
  done < "${file}"
}

load_dotenv "${env_file}"
: "${NJS_AI_MODELS_ROOT:?Set NJS_AI_MODELS_ROOT in ${env_file}}"
: "${NJS_AI_DATA_ROOT:?Set NJS_AI_DATA_ROOT in ${env_file}}"
: "${NJS_AI_CACHE_ROOT:?Set NJS_AI_CACHE_ROOT in ${env_file}}"
: "${NJS_AI_NETWORK:=njs-ai}"

workers=("${worker}")
[[ "${worker}" == all ]] && workers=(sam2 rmbg2 lama)
declare -A manifests=(
  [sam2]=sam2.1-hiera-large.json
  [rmbg2]=rmbg-2.0.json
  [lama]=big-lama.json
)

for name in "${workers[@]}"; do
  mkdir -p \
    "${NJS_AI_DATA_ROOT}/workers/${name}/input" \
    "${NJS_AI_DATA_ROOT}/workers/${name}/output" \
    "${NJS_AI_DATA_ROOT}/workers/${name}/user" \
    "${NJS_AI_DATA_ROOT}/workers/${name}/temp" \
    "${NJS_AI_CACHE_ROOT}/${name}/huggingface"
  prepare_args=(
    "${runtime_root}/models/${manifests[${name}]}"
    --models-root "${NJS_AI_MODELS_ROOT}"
    --cache-root "${NJS_AI_CACHE_ROOT}/model-downloads"
  )
  [[ -n ${NJS_AI_MODEL_MIRROR:-} ]] && prepare_args+=(--mirror "${NJS_AI_MODEL_MIRROR}")
  if [[ -n ${NJS_AI_MODEL_IMPORT_ROOTS:-} ]]; then
    IFS=: read -r -a import_roots <<< "${NJS_AI_MODEL_IMPORT_ROOTS}"
    for import_root in "${import_roots[@]}"; do
      [[ -n "${import_root}" ]] && prepare_args+=(--import-root "${import_root}")
    done
  fi
  python3 "${script_dir}/prepare_model_artifacts.py" "${prepare_args[@]}"
done

docker info >/dev/null
docker network inspect "${NJS_AI_NETWORK}" >/dev/null 2>&1 || \
  docker network create --driver bridge "${NJS_AI_NETWORK}" >/dev/null

echo "NJS AI runtime ready: models=${NJS_AI_MODELS_ROOT} data=${NJS_AI_DATA_ROOT} network=${NJS_AI_NETWORK}"
