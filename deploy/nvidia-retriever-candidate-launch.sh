set -eu
python3 - <<'PY'
import socket
s=socket.socket();s.bind(('127.0.0.1',8003));s.close()
print('{"candidate_port_free":true,"production_services_touched":false}')
PY
cd /tmp/cizheng-retriever-v07
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 PYTHONPATH=/tmp/cizheng-retriever-v07/app-core-readonly
export CPATH=/tmp/cizheng-retriever-v07/python-dev-headers/usr/include/python3.12:/tmp/cizheng-retriever-v07/python-dev-headers/usr/include
export CIZHENG_RETRIEVER_ROOT=/tmp/cizheng-retriever-v07
/tmp/cizheng-retriever-v07/.gpu-venv/bin/python - <<'PY'
from pathlib import Path
from runtime_contract import verify_runtime
import json
_,_,binding=verify_runtime(Path('/tmp/cizheng-retriever-v07'))
print(json.dumps({'pre_launch_runtime_contract_verified':True,**binding}))
PY
nohup /tmp/cizheng-retriever-v07/.gpu-venv/bin/python -m uvicorn gpu_service:app --host 127.0.0.1 --port 8003 --workers 1 > /tmp/cizheng-retriever-v07/service.log 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > /tmp/cizheng-retriever-v07/service.pid
printf '{"candidate_service_pid":%s,"production_services_touched":false}\n' "$pid"
