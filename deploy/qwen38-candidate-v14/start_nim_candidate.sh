#!/usr/bin/env bash
# Start only fixed v14 27B after coordinator-owned 4B/TRT rotation.
set -euo pipefail
umask 077
if [ "$#" -ne 4 ]; then
  printf '%s\n' 'usage: start_nim_candidate.sh FIXED_MODEL_DIR DOWNLOAD_RECEIPT ORIGINAL_CPU_AUDIT_DIR FRESH_EVIDENCE_DIR' >&2
  exit 2
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
model_dir="$(cd -- "$1" && pwd)"
model_receipt="$2"
original_cpu_dir="$(cd -- "$3" && pwd)"
evidence_dir="$4"
container_name='cizheng-nim-qwen38-v14-attempt-04'
template_container="${container_name}-templates"
cpu_container="${container_name}-cpu-preflight"
image='tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9'
for owned_name in "$container_name" "$template_container" "$cpu_container"; do
  if docker container inspect "$owned_name" >/dev/null 2>&1; then
    printf '%s\n' 'owned candidate or audit already exists; preserve it and its evidence' >&2; exit 1
  fi
done
python3 -S - "$model_dir" "$model_receipt" "$original_cpu_dir" "$evidence_dir" "$script_dir" <<'PATH_GUARD'
import sys
from pathlib import Path
for value in sys.argv[1:]:
    if any(char in value for char in ',\n\r\0'):
        raise ValueError('unsafe Docker bind path')
root=Path(sys.argv[4])
if not root.is_absolute() or root.exists() or root.is_symlink():
    raise ValueError('fresh absolute evidence directory required')
sys.path.insert(0,sys.argv[5])
from preflight import require_model_path_isolation
require_model_path_isolation(sys.argv[1],{
    'evidence directory':root,'candidate cache directory':root/'cache',
    'candidate profiles directory':root/'profiles','source directory':sys.argv[5],
    'original CPU directory':sys.argv[3],'download receipt':sys.argv[2]})
root.mkdir(mode=0o700,parents=True)
PATH_GUARD
evidence_dir="$(cd -- "$evidence_dir" && pwd)"
preflight_args=(--model-directory "$model_dir" --model-receipt "$model_receipt"
  --cpu-compatibility-report "$original_cpu_dir/cpu-compatibility.json"
  --cpu-host-report "$original_cpu_dir/host-before.json"
  --cpu-container-report "$original_cpu_dir/container-inspect.json")
# A model view with extra entries/symlinks, nested paths, less than 60 GiB,
# still-running historical 4B/TRT, occupied 8006/8009, changed Retriever
# guard or any unhealthy business service rejects before
# a template, CPU probe or GPU candidate is created. All 19 files are hashed.
python3 -S "$script_dir/preflight.py" "${preflight_args[@]}" --output "$evidence_dir/preflight.json"
mkdir -p "$evidence_dir/cache/tmp" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
chmod 700 "$evidence_dir/cache" "$evidence_dir/cache/tmp" "$evidence_dir/profiles" "$evidence_dir/nginx" "$evidence_dir/nim-etc"
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
# Only the root coordinator executes this audit after timing work is finished.
# A failed audit remains stopped and prevents the later GPU start.
docker run --pull=never --name "$cpu_container" --network none \
  --entrypoint python3 --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --memory-swap 4g --pids-limit 512 --shm-size 64m --cpus 4 \
  --mount "type=bind,source=$script_dir,target=/candidate,readonly" \
  --mount "type=bind,source=$model_dir,target=/models/qwen38,readonly" \
  --mount "type=bind,source=$original_cpu_dir,target=/original-cpu,readonly" \
  --mount "type=bind,source=$evidence_dir,target=/audit" \
  --mount "type=bind,source=$evidence_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$evidence_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$evidence_dir/container-group,target=/etc/group,readonly" \
  -e CUDA_VISIBLE_DEVICES= -e NVIDIA_VISIBLE_DEVICES=void \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e OMP_NUM_THREADS=4 \
  "$image" -u /candidate/cpu_profile_preflight.py \
  > "$evidence_dir/cpu-preflight.stdout" 2> "$evidence_dir/cpu-preflight.stderr"
docker container inspect "$cpu_container" > "$evidence_dir/cpu-profile-container-inspect.json"
# Keep all CPU evidence. Recheck live resources and checkpoint file identities
# after the CPU audit, before any GPU device is requested.
python3 -S "$script_dir/preflight.py" "${preflight_args[@]}" --guard-only \
  --verified-report "$evidence_dir/preflight.json" --cpu-profile-report "$evidence_dir/cpu-preflight.json" \
  --output "$evidence_dir/immediate-prestart.json"
candidate_args=()
while IFS= read -r argument; do candidate_args+=("$argument"); done < <(python3 -S - "$script_dir/launch_profile.json" <<'PROFILE_ARGS'
import hashlib,json,sys
raw=open(sys.argv[1],'rb').read()
if hashlib.sha256(raw).hexdigest()!='70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04':
    raise ValueError('launch profile changed')
for value in json.loads(raw)['arguments']:
    if '\n' in value or '\r' in value:raise ValueError('invalid argument')
    print(value)
PROFILE_ARGS
)
if [ "${#candidate_args[@]}" -ne 43 ]; then
  printf '%s\n' 'complete fixed launch profile required' >&2; exit 1
fi
# Preserve the pinned image's original NVIDIA NIM entrypoint.
docker create --pull=never --name "$container_name" \
  --device nvidia.com/gpu=all --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 40g --memory-swap 40g --pids-limit 512 --shm-size 1g \
  --restart no -p 127.0.0.1:8009:8000 \
  --mount "type=bind,source=$model_dir,target=/models/qwen38,readonly" \
  --mount "type=bind,source=$evidence_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$evidence_dir/nginx,target=/opt/nim/nginx" \
  --mount "type=bind,source=$evidence_dir/nim-etc,target=/opt/nim/etc" \
  --mount "type=bind,source=$evidence_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$evidence_dir/container-group,target=/etc/group,readonly" \
  --mount "type=bind,source=$evidence_dir/profiles,target=/evidence" \
  -e NIM_SERVER_PORT=8000 -e NIM_BACKEND_PORT=8001 \
  -e NIM_MODEL_PATH=/models/qwen38 -e NIM_SERVED_MODEL_NAME=Qwen3.8-27B-NVFP4 \
  -e NIM_CACHE_PATH=/opt/nim/.cache -e NIM_RUNTIME_CACHE_PATH=/opt/nim/.cache/runtime \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e SGLANG_IMAGE_MAX_PIXELS=262144 -e SGLANG_TORCH_PROFILER_DIR=/evidence \
  -e OMP_NUM_THREADS=4 -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  "$image" "${candidate_args[@]}" \
  > "$evidence_dir/container-id.txt" 2> "$evidence_dir/start.stderr"
# The created container has not run. Arm the sampled, exact-ID candidate guard
# before starting the NVIDIA entrypoint. It never restores historical services.
nohup python3 -S "$script_dir/memory_guard.py" \
  --container-id-file "$evidence_dir/container-id.txt" \
  --output-directory "$evidence_dir/memory-guard" \
  </dev/null > "$evidence_dir/memory-guard.stdout" 2> "$evidence_dir/memory-guard.stderr" &
guard_pid=$!
printf '%s\n' "$guard_pid" > "$evidence_dir/memory-guard.pid"
python3 -S - "$evidence_dir" "$guard_pid" <<'GUARD_HANDSHAKE'
import json,os,sys,time
from pathlib import Path
root=Path(sys.argv[1]);pid=int(sys.argv[2]);deadline=time.monotonic()+10
while time.monotonic()<deadline:
    if (root/'memory-guard/error.json').exists() or (root/'memory-guard/stop-receipt.json').exists():
        raise ValueError('candidate memory guard refused before GPU start')
    os.kill(pid,0)
    path=root/'memory-guard/ready.json'
    if path.exists():
        ready=json.loads(path.read_bytes())
        assert ready['memory_guard']=='armed'
        assert ready['interval_seconds']==0.5
        assert ready['minimum_system_buffer_bytes']==34*1024**3
        assert ready['resource_policy_sha256']=='92c2bc09a19bc56ca528d57b3e649ae43f8f9e574c9c516df4aa335ad662f217'
        assert ready['container_id']==(root/'container-id.txt').read_text().strip()
        break
    time.sleep(0.1)
else:raise TimeoutError('candidate memory guard did not arm')
GUARD_HANDSHAKE
# Recheck the three business services, fixed stopped 4B/TRT and 60 GiB admission
# after creating/arming the candidate and before any model process executes.
python3 -S "$script_dir/preflight.py" "${preflight_args[@]}" --guard-only \
  --verified-report "$evidence_dir/preflight.json" --cpu-profile-report "$evidence_dir/cpu-preflight.json" \
  --output "$evidence_dir/final-prestart.json"
if [ -f "$evidence_dir/memory-guard/error.json" ] || [ -f "$evidence_dir/memory-guard/stop-receipt.json" ]; then
  printf '%s\n' 'candidate memory guard failed; created container preserved without starting' >&2; exit 1
fi
kill -0 "$guard_pid"
docker start "$container_name" > "$evidence_dir/start.stdout" 2> "$evidence_dir/start.stderr"
printf '%s\n' '{"candidate_started":true,"candidate_ready":false,"port":8009,"static_fraction":0.58,"requested_context_length":24576,"requested_max_total_tokens":24576,"kv_cache_argument":"auto","kv_cache_expected_dtype":"bfloat16","production_modified":false,"original_nim_entrypoint_preserved":true,"resource_policy_sha256":"92c2bc09a19bc56ca528d57b3e649ae43f8f9e574c9c516df4aa335ad662f217","minimum_available_bytes":64424509440,"minimum_system_buffer_bytes":36507222016,"gpu_peak_and_remaining_floor_verified":false,"coordinator_rotated_owned_4b":true,"coordinator_rotated_owned_trt":true,"business_preserved_ports":[8005,8780,8003],"trt_restore_and_warm_cache_proven":false}' \
  | tee "$evidence_dir/start-receipt.json"
