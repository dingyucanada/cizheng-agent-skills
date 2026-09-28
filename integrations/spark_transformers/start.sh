#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
: "${CIZHENG_SPARK_MODEL_DIR:?Set an existing local model directory with a verified manifest}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
if [[ -n "${CIZHENG_SPARK_HEADERS_DIR:-}" ]]; then
  headers="$CIZHENG_SPARK_HEADERS_DIR"
  if [[ ! -f "$headers/usr/include/python3.12/Python.h" ]]; then
    printf 'Python 3.12 headers are missing from the configured directory\n' >&2
    exit 2
  fi
  export C_INCLUDE_PATH="$headers/usr/include/python3.12:$headers/usr/include:$headers/usr/include/aarch64-linux-gnu/python3.12${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
fi
if [[ -n "${CIZHENG_SPARK_CACHE_DIR:-}" ]]; then
  mkdir -p "$CIZHENG_SPARK_CACHE_DIR/triton"
  export TRITON_CACHE_DIR="$CIZHENG_SPARK_CACHE_DIR/triton"
fi
port="${CIZHENG_SPARK_PORT:-8000}"
if ! [[ "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  printf 'Invalid local service port\n' >&2
  exit 2
fi
exec python -m uvicorn integrations.spark_transformers.adapter:app \
  --host 127.0.0.1 --port "$port" --workers 1 --no-access-log
