from pathlib import Path
import hashlib,json,importlib.metadata as md,datetime
from runtime_contract import CODE_FILES,file_sha,verify_runtime
BASE=Path('/tmp/cizheng-retriever-v07')
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(8*1024*1024),b''):h.update(x)
 return h.hexdigest()
m=json.loads((BASE/'model-113abe4/weights-manifest.json').read_text())
for x in m['files']:
 p=BASE/'model-113abe4'/x['filename']
 assert p.is_file() and p.stat().st_size==x['bytes'] and digest(p)==x['sha256']
assert next(x['sha256'] for x in m['files'] if x['filename']=='model.safetensors')=='45f8440682a89ac577cc8d53b1bb345804772adb7b34e0573562e2fca4e62b0d'
packages=[]
reports=['gpu-package-install-report.json','model-compat-install-report.json']
installs=[x for name in reports for x in json.loads((BASE/name).read_text())['install']]
for x in installs:
 packages.append({'name':x['metadata']['name'],'version':x['metadata']['version'],'download_sha256':x['download_info']['archive_info']['hashes']['sha256']})
manifest={'runtime_kind':'NVIDIA open embedding + cuVS service, not Embedding NIM','model':m['repo'],'weights_revision':m['revision'],'model_files':m['files'],
 'code_files':{n:digest(BASE/n) for n in CODE_FILES},
 'candidate_python_headers':json.loads((BASE/'isolated-python-headers-proof.json').read_text()),
 'gpu_packages':packages,'resolved_runtime_versions':{p:md.version(p) for p in ['torch','transformers','fastapi','uvicorn','pydantic','numpy']},
 'service_contract':{'embedding_dimensions':2048,'corpus_sources':25,'corpus_chunks':25,'precision':'torch.bfloat16','index':'cuvs.neighbors.brute_force/cosine/CUDA','SDK_pipeline_used':False,'default_production_backend_changed':False},
 'snapshot_file_sha256':file_sha(BASE/'public-seed-snapshot-v07.json'),
 'snapshot_sha256':json.loads((BASE/'public-seed-snapshot-v07.json').read_text())['snapshot_sha256'],
 'production_torch_read_only':True,'isolated_transformers_override':True,'container_digest':None,'default_production_backend_changed':False}
(BASE/'deployment-runtime-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
canonical=json.dumps(manifest,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
print(json.dumps({'remote_model_files_verified':len(m['files']),'weights_bytes':sum(x['bytes'] for x in m['files']),'runtime_identity':'sha256:'+hashlib.sha256(canonical).hexdigest(),'container_digest':None,'GPU_model_loaded':False}))

_,_,binding=verify_runtime(BASE)
(BASE/'runtime-contract-cpu-verification.json').write_text(json.dumps({'GPU_model_loaded':False,**binding},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'runtime_contract_verified_before_loading':True,**binding}))
