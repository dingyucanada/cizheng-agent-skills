#!/usr/bin/env bash
# Candidate only; exact Qwen3-VL + GB10 + image digest still needs live validation.
# Official Spark discovery tag: lmsysorg/sglang:latest-cu130; resolve it once to a digest.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_SGLANG_IMAGE:?Set lmsysorg/sglang@sha256:... after CUDA13 ARM64 inspection}"
nvidia_check_image "$CIZHENG_SGLANG_IMAGE" 'lmsysorg/sglang'
nvidia_check_model
nvidia_common_args
exec docker run --name cizheng-sglang-candidate "${nvidia_args[@]}" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  "$CIZHENG_SGLANG_IMAGE" python3 -m sglang.launch_server \
  --model-path /mnt/model --served-model-name "$CIZHENG_MODEL_NAME" \
  --host 0.0.0.0 --port 8000 --dtype bfloat16 --tp 1 \
  --context-length "${CIZHENG_CANDIDATE_CONTEXT:-32768}" \
  --mem-fraction-static "${CIZHENG_CANDIDATE_MEMORY_FRACTION:-0.65}" \
  --max-running-requests 1 --chunked-prefill-size 4096 \
  --grammar-backend xgrammar "$@"
