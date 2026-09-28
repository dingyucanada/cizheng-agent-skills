#!/usr/bin/env bash
# Local weights, keyless-capable current public NIM candidate; inspect ARM64 first.
# Official documented discovery image: nvcr.io/nim/nvidia/model-free-nim:2.0.13.
# No assertion that this exact image supports GB10 or the project's Qwen3-VL.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_NIM_IMAGE:?Set nvcr.io/nim/nvidia/model-free-nim@sha256:... after ARM64 inspection}"
nvidia_check_image "$CIZHENG_NIM_IMAGE" 'nvcr.io/nim/nvidia/model-free-nim'
nvidia_check_model
nvidia_common_args
if [[ "${1:-}" == profiles ]]; then
  exec docker run --pull never --rm --gpus all --shm-size 8g \
    --mount "type=bind,source=$CIZHENG_MODEL_DIR,target=/mnt/model,readonly" \
    -e NIM_MODEL_PATH=/mnt/model -e NIM_SERVED_MODEL_NAME="$CIZHENG_MODEL_NAME" \
    "$CIZHENG_NIM_IMAGE" list-model-profiles
fi
exec docker run --name cizheng-nim-candidate "${nvidia_args[@]}" \
  --mount "type=bind,source=$CIZHENG_CANDIDATE_CACHE,target=/opt/nim/.cache" \
  -e NIM_MODEL_PATH=/mnt/model -e NIM_SERVED_MODEL_NAME="$CIZHENG_MODEL_NAME" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  "$CIZHENG_NIM_IMAGE" /mnt/model \
  --max-model-len "${CIZHENG_CANDIDATE_CONTEXT:-32768}" \
  --gpu-memory-utilization "${CIZHENG_CANDIDATE_MEMORY_FRACTION:-0.65}" \
  --max-num-seqs 1 "$@"
