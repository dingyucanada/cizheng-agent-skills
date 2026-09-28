set -eu
cd /tmp/cizheng-retriever-v07
export CPATH=/tmp/cizheng-retriever-v07/python-dev-headers/usr/include/python3.12:/tmp/cizheng-retriever-v07/python-dev-headers/usr/include
PYTHONPATH=/tmp/cizheng-retriever-v07/app-core-readonly .gpu-venv/bin/python - <<'PY'
from pathlib import Path
import tempfile,json,copy
from runtime_contract import verify_runtime,CODE_FILES
b=Path('/tmp/cizheng-retriever-v07');original=json.loads((b/'deployment-runtime-manifest.json').read_text());cases=[]
for label in ['wrong_model_revision','wrong_snapshot_identity','wrong_dimensions','changed_service_code_sha','changed_runtime_version']:
 m=copy.deepcopy(original)
 if label=='wrong_model_revision':m['weights_revision']='0'*40
 elif label=='wrong_snapshot_identity':m['snapshot_sha256']='0'*64
 elif label=='wrong_dimensions':m['service_contract']['embedding_dimensions']=1024
 elif label=='changed_service_code_sha':m['code_files']['gpu_service.py']='0'*64
 elif label=='changed_runtime_version':m['resolved_runtime_versions']['transformers']='0.0.0'
 with tempfile.TemporaryDirectory(prefix='cizheng-candidate-cpu-identity-') as td:
  p=Path(td)
  for n in CODE_FILES:
   dest=p/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(b/n)
  (p/'model-113abe4').symlink_to(b/'model-113abe4',target_is_directory=True)
  (p/'public-seed-snapshot-v07.json').symlink_to(b/'public-seed-snapshot-v07.json')
  (p/'deployment-runtime-manifest.json').write_text(json.dumps(m))
  try:verify_runtime(p)
  except AssertionError as e:cases.append({'case':label,'actual_rejected':True,'reason':str(e) or 'fixed expected identity assertion'})
  else:raise AssertionError(label+' unexpectedly accepted')
receipt={'scope':'Actual CPU negative identity checks against deployed verification code; no model loading or production mutation','cases':cases,'GPU_model_loaded':False,'production_changed':False,'service_deployment_proven':False,'current_runtime_identity':__import__('cizheng.knowledge',fromlist=['sha']).sha(original)}
(b/'cpu-negative-bindings.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))
PY
