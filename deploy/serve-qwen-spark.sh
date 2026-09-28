#!/usr/bin/env bash
# Project adaptation of NVIDIA's official Spark recipe. Not hardware-validated yet.
# Require an operator-pinned official ARM64 image; never silently pull 'latest'.
set -euo pipefail
: "${CIZHENG_VLLM_IMAGE:?Set a tested vllm/vllm-openai image digest after ARM64 inspection}"
if [[ "$CIZHENG_VLLM_IMAGE" != vllm/vllm-openai@sha256:* ]]; then
  echo '需要官方镜像的固定 sha256 digest；先在节点核实架构与版本。' >&2; exit 2
fi
model_revision_args=()
if [[ -n "${CIZHENG_MODEL_REVISION:-}" && "$CIZHENG_MODEL_REVISION" != unverified ]]; then
  model_revision_args=(--revision "$CIZHENG_MODEL_REVISION")
fi
exec docker run --rm --name cizheng-vlm --gpus all --shm-size 8g \
  -p 127.0.0.1:8000:8000 -e HF_TOKEN \
  -v "${CIZHENG_HF_CACHE:-$HOME/.cache/huggingface}:/root/.cache/huggingface" \
  "$CIZHENG_VLLM_IMAGE" nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --host 0.0.0.0 --port 8000 --tensor-parallel-size 1 --trust-remote-code \
  --kv-cache-dtype fp8 --attention-backend flashinfer --moe-backend marlin \
  --gpu-memory-utilization "${CIZHENG_GPU_MEMORY_UTILIZATION:-0.4}" \
  --max-model-len "${CIZHENG_MAX_MODEL_LEN:-32768}" --max-num-seqs 1 \
  --max-num-batched-tokens 8192 --enable-chunked-prefill --enable-prefix-caching \
  --reasoning-parser qwen3 --limit-mm-per-prompt '{"image":4,"video":0}' \
  "${model_revision_args[@]}"
