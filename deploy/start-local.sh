#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo '先按 README 创建 .venv 并安装依赖。' >&2
  exit 2
fi
exec .venv/bin/python -m uvicorn cizheng.api:create_app --factory --host 127.0.0.1 --port "${CIZHENG_PORT:-8780}" --workers 1
