#!/usr/bin/env bash
# Independent official NVIDIA open-model + cuVS service. This is not NIM.
set -euo pipefail
stage_root=${CIZHENG_RETRIEVER_ROOT:?Set the existing isolated candidate directory}
python_bin=${CIZHENG_RETRIEVER_PYTHON:?Set its existing isolated Python interpreter}
export CPATH="$stage_root/python-dev-headers/usr/include/python3.12:$stage_root/python-dev-headers/usr/include"
export PYTHONPATH="$stage_root:$stage_root/app-core-readonly${PYTHONPATH:+:$PYTHONPATH}"
action=${1:-health}
[[ -d "$stage_root" && -x "$python_bin" ]] || { echo 'candidate directory/interpreter missing' >&2; exit 2; }
case "$action" in
  probe)
    "$python_bin" "$stage_root/cuvs-no-model-probe.py"
    ;;
  health)
    "$python_bin" - <<'PY'
import httpx,json,os
from pathlib import Path
from runtime_contract import verify_runtime
_,_,binding=verify_runtime(Path(os.environ['CIZHENG_RETRIEVER_ROOT']))
with httpx.Client(trust_env=False,timeout=10) as c:
 r=c.get('http://127.0.0.1:8003/v1/health/ready');r.raise_for_status()
 body=r.json();assert body.get('ready') is True
 for k,v in binding.items():assert body.get(k)==v,(k,'endpoint runtime identity changed')
 print(json.dumps(body,ensure_ascii=False))
PY
    ;;
  start)
    [[ ${CIZHENG_RETRIEVER_LOAD_APPROVED:-0} == 1 ]] || { echo 'coordinate one-model loading slot before start' >&2; exit 2; }
    [[ -f "$stage_root/deployment-runtime-manifest.json" && -f "$stage_root/model-113abe4/weights-manifest.json" ]] || { echo 'verified deployment/weights manifests required' >&2; exit 2; }
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
    export PYTHONPATH="$stage_root:$stage_root/app-core-readonly${PYTHONPATH:+:$PYTHONPATH}"
    cd "$stage_root"
    bash "$stage_root/launch-candidate.sh"
    echo 'candidate started; verify actual readiness and API before claiming deployment'
    ;;
  *) echo 'usage: nvidia-serve-retriever-open.sh health|probe|start' >&2; exit 2 ;;
esac
