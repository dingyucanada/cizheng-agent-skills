#!/usr/bin/env bash
# Wrap an explicitly selected, newly launched process. No HTTP, downloads or stop.
set -euo pipefail

fail() { printf '%s\n' "$*" >&2; exit 2; }
[[ $# -gt 0 ]] || fail 'Usage: CIZHENG_NSYS_OUTPUT=/absolute/new-prefix bash nvidia-profile-native.sh command [args...]'
nsys_binary="${CIZHENG_NSYS_BINARY:-nsys}"
output="${CIZHENG_NSYS_OUTPUT:?Set an absolute, unused report prefix}"
[[ "$output" = /* && -d "$(dirname "$output")" ]] || fail 'Report prefix must be absolute with an existing parent directory'
for suffix in nsys-rep qdstrm sqlite; do
  [[ ! -e "$output.$suffix" ]] || fail 'Report prefix already has an artifact; choose a new prefix'
done
command -v "$nsys_binary" >/dev/null 2>&1 || fail 'An existing Nsight Systems CLI is required; this script installs nothing'

# torch.cuda.nvtx.range_push uses an ordinary string, not a registered string.
exec "$nsys_binary" profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --capture-range=nvtx --nvtx-capture=cizheng.model-generate \
  --capture-range-end=stop --kill=none \
  --env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0 --output="$output" "$@"
