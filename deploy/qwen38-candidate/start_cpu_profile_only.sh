#!/usr/bin/env bash
# Inspect metadata and image processing only; never request a GPU or network.
set -euo pipefail
umask 077
if [ "$#" -ne 3 ]; then
  printf '%s\n' 'usage: start_cpu_profile_only.sh MODEL_DIRECTORY ORIGINAL_CPU_DIRECTORY FRESH_AUDIT_DIRECTORY' >&2
  exit 2
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
model_dir="$(cd -- "$1" && pwd)"
original_cpu_dir="$(cd -- "$2" && pwd)"
audit_dir="$3"
image='tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9'
container_name="cizheng-nim-qwen38-$(basename -- "$audit_dir")"
case "$container_name" in
  cizheng-nim-qwen38-config-probe-[0-9][0-9]) ;;
  *) printf '%s\n' 'unowned CPU probe name rejected' >&2; exit 2 ;;
esac
template_container="${container_name}-templates"
for owned_name in "$container_name" "$template_container"; do
  if docker container inspect "$owned_name" >/dev/null 2>&1; then
    printf '%s\n' 'existing owned probe must be preserved' >&2; exit 1
  fi
done
python3 -S - "$image" "$script_dir" "$model_dir" "$audit_dir" "$original_cpu_dir" <<'GUARD'
import hashlib,json,subprocess,sys
from pathlib import Path
image,source,model,audit,original_cpu=sys.argv[1:]
for value in (source,model,audit,original_cpu):
    if any(char in value for char in ',\n\r\0'):
        raise ValueError('unsafe bind path')
info=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]
assert info['Id']=='sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef'
assert info['Architecture']=='arm64' and info['Os']=='linux'
assert image in info['RepoDigests']
import importlib.util
spec=importlib.util.spec_from_file_location('candidate_preflight',Path(source)/'preflight.py')
preflight=importlib.util.module_from_spec(spec);spec.loader.exec_module(preflight)
preflight.require_image(info)
preflight.read_pinned_json(Path(source)/'launch_profile.json',preflight.PROFILE_SHA256)
identity=preflight.read_pinned_json(Path(source)/'expected_identity.json',preflight.IDENTITY_SHA256)
original=Path(original_cpu)
preflight.require_cpu_compatibility(original/'cpu-compatibility.json',original/'host-before.json',original/'container-inspect.json',identity)
memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
available=int(memory['MemAvailable'].split()[0])*1024
assert available>=8*1024**3, 'CPU probe requires 8 GiB available'
root=Path(audit)
assert root.is_absolute() and not root.exists() and not root.is_symlink(), 'fresh audit directory required'
root.mkdir(mode=0o700)
record={'image':image,'image_id':info['Id'],'architecture':info['Architecture'],
        'mem_available_before_bytes':available,'gpu_requested':False,'network':'none',
        'memory_limit_bytes':4*1024**3,'source_sha256':{name:hashlib.sha256((Path(source)/name).read_bytes()).hexdigest()
              for name in ('cpu_profile_preflight.py','start_cpu_profile_only.sh','launch_profile.json','expected_identity.json')}}
(root/'host-before.json').write_text(json.dumps(record,indent=2)+'\n')
GUARD
audit_dir="$(cd -- "$audit_dir" && pwd)"
mkdir -p "$audit_dir/cache/tmp"
chmod 700 "$audit_dir/cache" "$audit_dir/cache/tmp"
docker create --pull=never --name "$template_container" "$image" > "$audit_dir/template-id.txt"
docker cp "$template_container:/etc/passwd" "$audit_dir/container-passwd"
docker cp "$template_container:/etc/group" "$audit_dir/container-group"
docker rm "$template_container" >/dev/null
python3 -S - "$audit_dir" <<'IDENTITY'
import os,sys
from pathlib import Path
root=Path(sys.argv[1]);uid=os.getuid();gid=os.getgid()
for name,number,line in [('container-passwd',uid,f'cizheng-nim-host:x:{uid}:{gid}:NIM CPU probe:/opt/nim/.cache:/usr/sbin/nologin'),
                         ('container-group',gid,f'cizheng-nim-host:x:{gid}:')]:
    path=root/name;content=path.read_text()
    if not any(len(parts:=entry.split(':'))>2 and parts[2]==str(number) for entry in content.splitlines()):
        path.write_text(content.rstrip('\n')+'\n'+line+'\n')
    path.chmod(0o600)
IDENTITY
set +e
docker run --pull=never --name "$container_name" --network none \
  --entrypoint python3 --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --memory-swap 4g --pids-limit 512 --shm-size 64m --cpus 4 \
  --mount "type=bind,source=$script_dir,target=/candidate,readonly" \
  --mount "type=bind,source=$model_dir,target=/models/qwen38,readonly" \
  --mount "type=bind,source=$audit_dir,target=/audit" \
  --mount "type=bind,source=$original_cpu_dir,target=/original-cpu,readonly" \
  --mount "type=bind,source=$audit_dir/cache,target=/opt/nim/.cache" \
  --mount "type=bind,source=$audit_dir/container-passwd,target=/etc/passwd,readonly" \
  --mount "type=bind,source=$audit_dir/container-group,target=/etc/group,readonly" \
  -e CUDA_VISIBLE_DEVICES= -e NVIDIA_VISIBLE_DEVICES=void \
  -e HOME=/opt/nim/.cache -e XDG_CACHE_HOME=/opt/nim/.cache/xdg \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e OMP_NUM_THREADS=4 \
  "$image" -u /candidate/cpu_profile_preflight.py \
  > "$audit_dir/cpu.stdout" 2> "$audit_dir/cpu.stderr"
probe_exit="$?"
set -e
docker container inspect "$container_name" > "$audit_dir/container-inspect.json"
python3 -S - "$audit_dir" "$probe_exit" <<'RECEIPT'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
record={'exit_code':int(sys.argv[2]),'mem_available_after_bytes':int(memory['MemAvailable'].split()[0])*1024,
        'gpu_requested':False,'model_weights_loaded':False,'original_services_modified':False,
        'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                 for name in ('cpu.stdout','cpu.stderr','container-inspect.json','host-before.json')}}
if (root/'cpu-preflight.json').exists():
    record['files']['cpu-preflight.json']=hashlib.sha256((root/'cpu-preflight.json').read_bytes()).hexdigest()
with (root/'host-after.json').open('x') as stream:
    stream.write(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
RECEIPT
# Preserve the stopped owned probe and all original diagnostics for review.
exit "$probe_exit"
