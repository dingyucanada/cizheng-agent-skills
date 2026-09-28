#!/usr/bin/env bash
# Prepared candidate checks only. Never pulls or starts a model/API/GPU process.
set -euo pipefail
source "$(dirname "$0")/nvidia-container-common.sh"
: "${CIZHENG_VLLM_IMAGE:?Set an already local NVIDIA vLLM image at its inspected digest}"
nvidia_check_image "$CIZHENG_VLLM_IMAGE" nvcr.io/nvidia/vllm
mode="${1:-image}"
case "$mode" in
  image)
    docker image inspect --format '{"architecture":{{json .Architecture}},"os":{{json .Os}},"image_id":{{json .Id}},"repo_digests":{{json .RepoDigests}},"size_bytes":{{json .Size}}}' "$CIZHENG_VLLM_IMAGE"
    ;;
  cpu-cli)
    # Executor opt-in after image completion. No GPU/device/port/model mounts.
    # Capture stdout/stderr in a new evidence log; a CLI pass is not GPU proof.
    docker run --rm --name cizheng-vllm-preflight --pull never --network none \
      --entrypoint /bin/bash -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
      "$CIZHENG_VLLM_IMAGE" -c '
set -euo pipefail
python - <<"PY"
import importlib.metadata as metadata
import json
import torch
print(json.dumps({"package_versions": {name: metadata.version(name) for name in
                 ("torch", "vllm", "transformers", "xgrammar")},
                  "torch_build_cuda": torch.version.cuda,
                  "scope": "CPU package import only; no GPU, model, or server"}))
PY
vllm serve --help
'
    ;;
  *) echo 'Usage: nvidia-preflight-vllm.sh [image|cpu-cli]' >&2; exit 2 ;;
esac
