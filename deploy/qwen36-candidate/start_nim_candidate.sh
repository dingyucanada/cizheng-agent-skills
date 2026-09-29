#!/usr/bin/env bash
# Start one isolated candidate. Existing services are only read through health URLs.
set -euo pipefail
umask 077
if [ "$#" -ne 3 ]; then
  printf '%s\n' 'usage: start_nim_candidate.sh FIXED_MODEL_DIR VERIFIED_RECEIPT FRESH_EVIDENCE_DIR' >&2
  exit 2
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
model_dir="$(cd -- "$1" && pwd)"
model_receipt="$2"
evidence_dir="$3"
container_name="${NIM_CANDIDATE_NAME:-cizheng-nim-qwen36-v10-attempt-01}"
case "$container_name" in
  cizheng-nim-qwen36-v10-attempt-[0-9][0-9]) ;;
  *) printf '%s\n' 'unowned candidate name rejected' >&2; exit 2 ;;
esac
template_container="${container_name}-templates"
cpu_container="${container_name}-cpu-preflight"
image='tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9'
for owned_name in "$container_name" "$template_container" "$cpu_container"; do
  if docker container inspect "$owned_name" >/dev/null 2>&1; then
    printf '%s\n' 'an owned candidate/audit container already exists; preserve it and its evidence' >&2
    exit 1
  fi
done
# Require a new directory; every attempt has separate evidence and cache.
python3 -S - "$model_dir" "$model_receipt" "$evidence_dir" "$script_dir" <<'PATH_GUARD'
import sys
from pathlib import Path
for value in sys.argv[1:]:
    if any(char in value for char in ',\n\r\0'):
        raise ValueError('unsafe Docker bind path')
root=Path(sys.argv[3])
if not root.is_absolute() or root.exists() or root.is_symlink():
    raise ValueError('fresh absolute evidence directory required')
root.mkdir(mode=0o700, parents=True)
PATH_GUARD
evidence_dir="$(cd -- "$evidence_dir" && pwd)"
# Preserve the original 0.24 rejection as an audit record without loading weights.
if python3 -S "$script_dir/preflight.py" --guard-only --static-fraction 0.24 \
     --model-directory "$model_dir" --model-receipt "$model_receipt" \
     --output "$evidence_dir/legacy-024-preflight.json"; then
  printf '%s\n' 'legacy 0.24 budget happened to pass; startup still uses the fixed 0.58 experimental profile'
fi
python3 -S "$script_dir/preflight.py" --model-directory "$model_dir" \
  --model-receipt "$model_receipt" --output "$evidence_dir/preflight.json"
mkdir -p "$evidence_dir/cache/tmp" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
chmod 700 "$evidence_dir/cache" "$evidence_dir/cache/tmp" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
# Copy vendor configuration and account files from this exact installed image.
# No GPU is attached to the stopped template, and no image is pulled.
docker create --pull=never --name "$template_container" "$image" > "$evidence_dir/template-id.txt"
docker cp "$template_container:/opt/nim/etc/." "$evidence_dir/nim-etc/"
docker cp "$template_container:/etc/passwd" "$evidence_dir/container-passwd"
docker cp "$template_container:/etc/group" "$evidence_dir/container-group"
docker rm "$template_container" >/dev/null
chmod -R u+rwX "$evidence_dir/nim-etc"
python3 -S - "$evidence_dir" <<'CONTAINER_IDENTITY'
import os,sys
from pathlib import Path
root=Path(sys.argv[1]);uid=os.getuid();gid=os.getgid()
for name,number,line in [('container-passwd',uid,f'cizheng-nim-host:x:{uid}:{gid}:NIM candidate:/opt/nim/.cache:/usr/sbin/nologin'),
                         ('container-group',gid,f'cizheng-nim-host:x:{gid}:')]:
    path=root/name;text=path.read_text()
    if not any(len(parts:=entry.split(':'))>2 and parts[2]==str(number) for entry in text.splitlines()):
        path.write_text(text.rstrip('\n')+'\n'+line+'\n')
    path.chmod(0o600)
CONTAINER_IDENTITY
# CPU audit deliberately overrides the entrypoint and has no GPU or network.
# A failure preserves this owned stopped audit container and prevents GPU startup.
docker run --pull=never --name "$cpu_container" --network none \
  --entrypoint python3 --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --memory-swap 4g --pids-limit 512 --shm-size 64m --cpus 4 \
  --mount "type=bind,source=$script_dir,target=/candidate,readonly" \
  --mount "type=bind,source=$model_dir,target=/models/qwen36,readonly" \
  --mount "type=bind,source=$evidence_dir,target=/audit" \
  --mount "type=bind,source=$evidence_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$evidence_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$evidence_dir/container-group,target=/etc/group,readonly" \
  -e CUDA_VISIBLE_DEVICES= -e NVIDIA_VISIBLE_DEVICES=void \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e OMP_NUM_THREADS=4 \
  "$image" -u /candidate/cpu_preflight.py \
  > "$evidence_dir/cpu-preflight.stdout" 2> "$evidence_dir/cpu-preflight.stderr"
docker rm "$cpu_container" >/dev/null
# Recheck resources, port, five old services and exact image after the CPU audit.
python3 -S "$script_dir/preflight.py" --guard-only --model-directory "$model_dir" \
  --model-receipt "$model_receipt" --cpu-report "$evidence_dir/cpu-preflight.json" \
  --output "$evidence_dir/immediate-prestart.json"
# Obtain arguments from a hash-pinned profile; do not use eval or caller flags.
candidate_args=()
while IFS= read -r argument; do
  candidate_args+=("$argument")
done < <(python3 -S - "$script_dir/launch_profile.json" <<'PROFILE_ARGS'
import hashlib,json,sys
raw=open(sys.argv[1],'rb').read()
if hashlib.sha256(raw).hexdigest()!='2e4f0d0b02e4769be5b92487cbba4a9bb4d2f346e18602de31e8fa108ece571e':
    raise ValueError('launch profile changed')
for value in json.loads(raw)['arguments']:
    if '\n' in value or '\r' in value: raise ValueError('invalid argument')
    print(value)
PROFILE_ARGS
)
if [ "${#candidate_args[@]}" -ne 43 ]; then
  printf '%s\n' 'complete fixed launch profile required' >&2; exit 1
fi
# Keep the pinned image's original NVIDIA NIM entrypoint for the actual server.
docker run -d --pull=never --name "$container_name" \
  --device nvidia.com/gpu=all --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 40g --memory-swap 40g --pids-limit 512 --shm-size 1g \
  --restart no -p 127.0.0.1:8008:8000 \
  --mount "type=bind,source=$model_dir,target=/models/qwen36,readonly" \
  --mount "type=bind,source=$evidence_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$evidence_dir/nginx,target=/opt/nim/nginx" \
  --mount "type=bind,source=$evidence_dir/nim-etc,target=/opt/nim/etc" \
  --mount "type=bind,source=$evidence_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$evidence_dir/container-group,target=/etc/group,readonly" \
  --mount "type=bind,source=$evidence_dir/profiles,target=/evidence" \
  -e NIM_SERVER_PORT=8000 -e NIM_BACKEND_PORT=8001 \
  -e NIM_MODEL_PATH=/models/qwen36 -e NIM_SERVED_MODEL_NAME=Qwen3.6-35B-A3B-NVFP4 \
  -e NIM_CACHE_PATH=/opt/nim/.cache -e NIM_RUNTIME_CACHE_PATH=/opt/nim/.cache/runtime \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e SGLANG_IMAGE_MAX_PIXELS=262144 -e SGLANG_TORCH_PROFILER_DIR=/evidence \
  -e OMP_NUM_THREADS=4 -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  "$image" "${candidate_args[@]}" \
  > "$evidence_dir/container-id.txt" 2> "$evidence_dir/start.stderr"
printf '%s\n' '{"candidate_started":true,"candidate_ready":false,"port":8008,"static_fraction":0.58,"requested_context_length":24576,"requested_max_total_tokens":24576,"production_modified":false,"original_nim_entrypoint_preserved":true}' \
  | tee "$evidence_dir/start-receipt.json"
