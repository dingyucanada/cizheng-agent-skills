#!/usr/bin/env bash
# Operator must coordinate this load with other Spark deployments beforehand.
set -euo pipefail
if [[ "${TRT_LOAD_COORDINATED:-}" != 'yes' ]]; then
  echo 'Load not coordinated; no container or model started.' >&2
  exit 2
fi
readonly TRT_IMAGE='nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965'
readonly TRT_CONTAINER='cizheng-trt-qwen4b'
mkdir -p integration-evidence/trt-deploy/profiles
readonly TRT_PROFILE_DIR="$(realpath -- integration-evidence/trt-deploy/profiles)"
if [[ -e "$TRT_PROFILE_DIR/first-text.trace.json" ]]; then
  echo 'Prior candidate trace exists; inspect instead of overwriting.' >&2
  exit 2
fi
readonly TRT_CONFIG_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TRT_MODEL_DIR="$(realpath -- models/trt-qwen3-4b-instruct-2507)"
python3 -S - <<'PRELOAD_CHECK'
import hashlib,json,socket,subprocess
from pathlib import Path
model=Path('models/trt-qwen3-4b-instruct-2507')
receipt=json.loads(Path('integration-evidence/trt-deploy/qwen4b-verified-model.json').read_bytes())
assert receipt['all_files_verified'] is True
assert receipt['model']=='Qwen/Qwen3-4B-Instruct-2507'
assert receipt['file_count']==14 and receipt['total_file_bytes']==8060918292
for item in receipt['files']:
 path=model/item['name']
 assert path.is_file() and not path.is_symlink() and path.stat().st_size==item['bytes']
 digest=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
 assert digest.hexdigest()==item['sha256']
mem={line.split(':',1)[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
assert mem['MemAvailable']>=32*1024**3, 'insufficient free unified memory margin'
with socket.socket() as probe:probe.bind(('127.0.0.1',8006))
result=subprocess.run(['docker','container','inspect','cizheng-trt-qwen4b'],capture_output=True)
assert result.returncode!=0, 'owned container already exists; inspect instead of replacing'
print(json.dumps({'checkpoint_reverified':True,'mem_available_before_load_bytes':mem['MemAvailable'],'container_memory_limit_bytes':24*1024**3,'port':8006,'production_services_modified':False}))
PRELOAD_CHECK
docker run -d --pull=never --name "$TRT_CONTAINER" \
  --device nvidia.com/gpu=all --network host --ipc private --shm-size 1g \
  --memory 24g --memory-swap 24g --ulimit memlock=-1 --ulimit stack=67108864 \
  --security-opt no-new-privileges --cap-drop ALL --cap-add DAC_OVERRIDE \
  --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 \
  --env TLLM_PROFILE_START_STOP=0-8 \
  --env TLLM_TORCH_PROFILE_TRACE=/evidence/first-text.trace.json \
  --mount "type=bind,src=$TRT_PROFILE_DIR,dst=/evidence" \
  --mount "type=bind,src=$TRT_MODEL_DIR,dst=/model,readonly" \
  --mount "type=bind,src=$TRT_CONFIG_DIR/serve-config.yaml,dst=/config/serve.yaml,readonly" \
  "$TRT_IMAGE" trtllm-serve serve /model \
  --backend pytorch --host 127.0.0.1 --port 8006 \
  --served_model_name Qwen3-4B-Instruct-2507 \
  --max_batch_size 1 --max_seq_len 4096 --max_num_tokens 2048 \
  --extra_llm_api_options /config/serve.yaml --no-telemetry
