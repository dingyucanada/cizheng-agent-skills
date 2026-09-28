#!/usr/bin/env bash
# Candidate rc18 PyTorch multimodal backend; no legacy trtllm-build conversion.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_TRTLLM_IMAGE:?Set nvcr.io/nvidia/tensorrt-llm/release@sha256:... after ARM64 inspection}"
nvidia_check_image "$CIZHENG_TRTLLM_IMAGE" 'nvcr.io/nvidia/tensorrt-llm/release'
nvidia_check_model
nvidia_common_args
config_dir=$(cd "$(dirname "$0")" && pwd)
exec docker run --name cizheng-trtllm-candidate "${nvidia_args[@]}" \
  --mount "type=bind,source=$config_dir/nvidia-trtllm.yaml,target=/config/nvidia-trtllm.yaml,readonly" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  "$CIZHENG_TRTLLM_IMAGE" trtllm-serve serve /mnt/model \
  --host 0.0.0.0 --port 8000 --backend pytorch \
  --max_batch_size 1 --max_num_tokens 4096 \
  --max_seq_len "${CIZHENG_CANDIDATE_CONTEXT:-32768}" \
  --config /config/nvidia-trtllm.yaml "$@"
