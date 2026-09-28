#!/usr/bin/env bash
# Shared checks. No pull, credentials, service stop, or host configuration changes.
set -euo pipefail
nvidia_check_image() {
  local image="$1" prefix="$2"
  if [[ "${image%@*}" != "$prefix" || ! "${image#*@}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo 'Set the official image repository plus the inspected immutable sha256 digest.' >&2
    return 2
  fi
  local architecture
  architecture=$(docker image inspect "$image" --format '{{.Architecture}}')
  [[ "$architecture" == arm64 ]] || { echo 'The locally staged image must be ARM64.' >&2; return 2; }
}
nvidia_check_model() {
  : "${CIZHENG_MODEL_DIR:?Set the absolute directory of locally verified model weights}"
  : "${CIZHENG_MODEL_NAME:?Set the exact model ID from its verified manifest}"
  [[ "$CIZHENG_MODEL_DIR" == /* && -d "$CIZHENG_MODEL_DIR" && -f "$CIZHENG_MODEL_DIR/config.json" ]] || {
    echo 'A local absolute model directory with config.json is required.' >&2; return 2;
  }
  [[ -f "$CIZHENG_MODEL_DIR/_file_manifest.json" ]] || {
    echo 'Stage and verify the project model manifest before starting a candidate runtime.' >&2; return 2;
  }
}
nvidia_common_args() {
  : "${CIZHENG_CANDIDATE_CACHE:?Set an isolated absolute writable candidate cache directory}"
  [[ "$CIZHENG_CANDIDATE_CACHE" == /* && -d "$CIZHENG_CANDIDATE_CACHE" ]] || {
    echo 'Create the isolated candidate cache before serving.' >&2; return 2;
  }
  nvidia_args=(--pull never --gpus all --shm-size 8g --ulimit memlock=-1 --ulimit stack=67108864
    -p "127.0.0.1:${CIZHENG_CANDIDATE_PORT:-8002}:8000"
    --mount "type=bind,source=$CIZHENG_MODEL_DIR,target=/mnt/model,readonly"
    --mount "type=bind,source=$CIZHENG_CANDIDATE_CACHE,target=/root/.cache")
}
