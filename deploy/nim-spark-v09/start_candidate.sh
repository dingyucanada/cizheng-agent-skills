#!/usr/bin/env bash
# Start only the isolated, pinned official NIM candidate; never stop existing services.
set -euo pipefail
umask 077
if [ "$#" -ne 3 ]; then
  printf '%s\n' 'usage: start_candidate.sh PUBLIC_MODEL_DIR VERIFIED_MODEL_RECEIPT EVIDENCE_DIR' >&2
  exit 2
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
model_dir="$(cd -- "$1" && pwd)"
model_receipt="$2"
evidence_dir="$3"
container_name="${NIM_CANDIDATE_NAME:-cizheng-nim-qwen4b-v09}"
case "$container_name" in
  cizheng-nim-qwen4b-v09|cizheng-nim-qwen4b-v09-attempt-[0-9][0-9]) ;;
  *) printf '%s\n' 'unowned candidate name rejected' >&2; exit 2 ;;
esac
image='tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9'
if docker inspect "$container_name" >/dev/null 2>&1; then
  printf '%s\n' 'candidate already exists; preserve it and its evidence' >&2
  exit 1
fi
python3 -S - <<'PORT_GUARD'
import socket
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 8007))
PORT_GUARD
mkdir -p "$evidence_dir/cache/tmp" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
evidence_dir="$(cd -- "$evidence_dir" && pwd)"
chmod 700 "$evidence_dir" "$evidence_dir/cache" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
python3 -S "$script_dir/preflight.py" --model-directory "$model_dir" \
  --model-receipt "$model_receipt" --output "$evidence_dir/preflight.json"
# Copy only the pinned image's vendor configuration into this candidate's private
# directory. The SDK writes etc/default; the host owner cannot write the image's
# UID-1000 directory. Keep the original templates without granting capabilities.
template_container="${container_name}-templates"
if docker inspect "$template_container" >/dev/null 2>&1; then
  printf '%s\n' 'owned template container already exists; preserve it' >&2; exit 1
fi
docker create --name "$template_container" "$image" >/dev/null
docker cp "$template_container:/opt/nim/etc/." "$evidence_dir/nim-etc/"
docker cp "$template_container:/etc/passwd" "$evidence_dir/container-passwd"
docker cp "$template_container:/etc/group" "$evidence_dir/container-group"
docker rm "$template_container" >/dev/null
chmod -R u+rwX "$evidence_dir/nim-etc"
# PyTorch's cache code uses getpwuid, independently of HOME. Add only a synthetic
# identity to copies from the fixed image, never read the host's account files.
python3 -S - "$evidence_dir" <<'CONTAINER_IDENTITY'
import os,sys
from pathlib import Path
root=Path(sys.argv[1]);uid=os.getuid();gid=os.getgid()
for name,number,line in [('container-passwd',uid,f'cizheng-nim-host:x:{uid}:{gid}:NIM candidate:/opt/nim/.cache:/usr/sbin/nologin'),
                         ('container-group',gid,f'cizheng-nim-host:x:{gid}:')]:
    path=root/name;text=path.read_text()
    if not any(len(p:=entry.split(':'))>2 and p[2]==str(number) for entry in text.splitlines()):
        path.write_text(text.rstrip('\n')+'\n'+line+'\n')
    path.chmod(0o600)
CONTAINER_IDENTITY
# Keep the image's NVIDIA NIM entrypoint. The host owner UID can read its 0600
# public weights and own the independent cache; no permission changes to weights.
docker run -d --name "$container_name" \
  --device nvidia.com/gpu=all \
  --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 24g --memory-swap 24g --pids-limit 512 --shm-size 1g \
  --restart no -p 127.0.0.1:8007:8000 \
  --mount "type=bind,source=$model_dir,target=/models/qwen3-4b,readonly" \
  --mount "type=bind,source=$evidence_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$evidence_dir/nginx,target=/opt/nim/nginx" \
  --mount "type=bind,source=$evidence_dir/nim-etc,target=/opt/nim/etc" \
  --mount "type=bind,source=$evidence_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$evidence_dir/container-group,target=/etc/group,readonly" \
  --mount "type=bind,source=$evidence_dir/profiles,target=/evidence" \
  -e NIM_SERVER_PORT=8000 -e NIM_BACKEND_PORT=8001 \
  -e NIM_MODEL_PATH=/models/qwen3-4b \
  -e NIM_SERVED_MODEL_NAME=Qwen3-4B-Instruct-2507 \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -e NIM_RUNTIME_CACHE_PATH=/opt/nim/.cache/runtime \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e SGLANG_TORCH_PROFILER_DIR=/evidence \
  -e OMP_NUM_THREADS=4 -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  "$image" \
  --dtype bfloat16 --tp-size 1 --context-length 4096 --max-total-tokens 4096 \
  --max-running-requests 1 --chunked-prefill-size 512 \
  --mem-fraction-static 0.25 --disable-cuda-graph \
  > "$evidence_dir/container-id.txt"
printf '%s\n' '{"candidate_started":true,"port":8007,"production_modified":false,"original_nim_entrypoint_preserved":true}'
