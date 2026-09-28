#!/usr/bin/env bash
# Candidate only. Prefer inspected NVIDIA 25.11 CUDA13.0.2/vLLM0.11 image.
# Discovery: nvcr.io/nvidia/vllm:25.11-py3; ARM64/GB10/Qwen3-VL need live tests.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_VLLM_IMAGE:?Set the inspected official CUDA13 ARM64 vLLM image at sha256 digest}"
case "${CIZHENG_VLLM_IMAGE%@*}" in
  nvcr.io/nvidia/vllm)
    image_repository=nvcr.io/nvidia/vllm
    ;;
  vllm/vllm-openai)
    image_repository=vllm/vllm-openai
    ;;
  *) echo 'Only inspected NVIDIA or upstream vLLM repositories are accepted.' >&2; exit 2 ;;
esac
nvidia_check_image "$CIZHENG_VLLM_IMAGE" "$image_repository"
nvidia_check_model
nvidia_common_args
# Preserve NVIDIA's CUDA/driver entrypoint; upstream's API entrypoint would
# otherwise prepend its own server command to our explicit vllm serve command.
if [[ "$image_repository" == vllm/vllm-openai ]]; then
  nvidia_args+=(--entrypoint '')
fi
exec docker run --name cizheng-vllm-candidate "${nvidia_args[@]}" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  "$CIZHENG_VLLM_IMAGE" vllm serve /mnt/model \
  --served-model-name "$CIZHENG_MODEL_NAME" --host 0.0.0.0 --port 8000 \
  --dtype bfloat16 --tensor-parallel-size 1 \
  --max-model-len "${CIZHENG_CANDIDATE_CONTEXT:-32768}" \
  --gpu-memory-utilization "${CIZHENG_CANDIDATE_MEMORY_FRACTION:-0.65}" \
  --max-num-seqs 1 --max-num-batched-tokens 4096 \
  --limit-mm-per-prompt '{"image":4,"video":0}' \
  --structured-outputs-config '{"backend":"xgrammar"}' "$@"
