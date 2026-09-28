#!/usr/bin/env bash
# Staged official 2.3 ARM64 embedding NIM. Not deployed or tested on Spark.
# Discovery image: nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2:2.3.
# Its NGC/China-distributor rules differ from current LLM keyless NIM.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_RETRIEVER_IMAGE:?Set the inspected official embedding image at immutable digest}"
nvidia_check_image "$CIZHENG_RETRIEVER_IMAGE" 'nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2'
: "${CIZHENG_RETRIEVER_WEIGHTS:?Set an existing absolute staged weights root}"
: "${CIZHENG_RETRIEVER_CACHE:?Set an existing isolated absolute runtime cache}"
for directory in "$CIZHENG_RETRIEVER_WEIGHTS" "$CIZHENG_RETRIEVER_CACHE"; do
  [[ "$directory" == /* && -d "$directory" ]] || { echo 'Existing absolute cache directories are required.' >&2; exit 2; }
done
if [[ "${1:-}" == prefetch ]]; then
  # Explicit opt-in download-only mode, never automatic during runtime startup.
  # Env-by-name passes credentials without echoing or placing values in argv.
  provider="${CIZHENG_RETRIEVER_PROVIDER:-hf}"
  if [[ "$provider" == ngc ]]; then
    [[ -n "${NGC_API_KEY:-}" ]] || { echo 'The NGC provider requires its existing credential.' >&2; exit 2; }
    provider_args=(-e NIM_ENGINE_MODEL_DOWNLOAD_PROVIDER=ngc -e NGC_API_KEY)
  elif [[ "$provider" == hf ]]; then
    [[ -n "${HF_TOKEN:-}" ]] || { echo 'The documented HF provider requires its existing credential.' >&2; exit 2; }
    provider_args=(-e HF_TOKEN)
  else
    echo 'Choose the documented hf or ngc download provider.' >&2; exit 2
  fi
  exec docker run --pull never --name cizheng-retriever-prefetch \
    -u "$(id -u)" -e NIM_ENGINE_MODEL_DOWNLOAD_ONLY=1 "${provider_args[@]}" \
    --mount "type=bind,source=$CIZHENG_RETRIEVER_WEIGHTS,target=/model" \
    "$CIZHENG_RETRIEVER_IMAGE"
fi
[[ -d "$CIZHENG_RETRIEVER_WEIGHTS/embed" ]] || { echo 'The staged default model requires the embed subdirectory.' >&2; exit 2; }
exec docker run --pull never --name cizheng-retriever-candidate \
  --gpus all --shm-size 8g -u "$(id -u)" \
  -p "127.0.0.1:${CIZHENG_RETRIEVER_PORT:-8003}:8000" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  --mount "type=bind,source=$CIZHENG_RETRIEVER_WEIGHTS,target=/model,readonly" \
  --mount "type=bind,source=$CIZHENG_RETRIEVER_CACHE,target=/opt/cache" \
  "$CIZHENG_RETRIEVER_IMAGE" "$@"
