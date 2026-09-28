"""Verify this independent candidate's pinned local bytes before any model load.

This is a local operational binding check, not hardware/remote attestation.
"""
from pathlib import Path
import hashlib, json, importlib.metadata as md, importlib.util, subprocess, os
from cizheng.knowledge import validate_snapshot, sha
MODEL='nvidia/llama-nemotron-embed-1b-v2'
REVISION='113abe4acafa848e77ead9c0623205e511932348'
WEIGHT_SHA='45f8440682a89ac577cc8d53b1bb345804772adb7b34e0573562e2fca4e62b0d'
SNAPSHOT_SHA='e3b1f9290e502d27d2ecae2b16fc8a611aed5367d693e4f678df7f2b0cc1be24'
SNAPSHOT_FILE_SHA='7da8b95f277e9e0185b0fc9688ba95a9d7d7b180dd58ae0ab48d5037b1248bf9'
CODE_FILES=('gpu_service.py','runtime_contract.py','verify-and-runtime-manifest.py','launch-candidate.sh','app-core-readonly/cizheng/knowledge.py','app-core-readonly/integrations/nvidia_retriever/client.py','real-client-acceptance.py')

def file_sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def verify_runtime(base):
 base=Path(base);mp=base/'deployment-runtime-manifest.json'
 manifest=json.loads(mp.read_text())
 assert manifest['model']==MODEL and manifest['weights_revision']==REVISION
 assert manifest['snapshot_sha256']==SNAPSHOT_SHA and manifest['snapshot_file_sha256']==SNAPSHOT_FILE_SHA
 assert manifest['service_contract']=={'embedding_dimensions':2048,'corpus_sources':25,'corpus_chunks':25,'precision':'torch.bfloat16','index':'cuvs.neighbors.brute_force/cosine/CUDA','SDK_pipeline_used':False,'default_production_backend_changed':False}
 assert manifest['container_digest'] is None
 assert set(manifest['code_files'])==set(CODE_FILES),'code file set differs from reviewed candidate'
 code={n:file_sha(base/n) for n in CODE_FILES}
 assert code==manifest['code_files'],'deployed code bytes do not match runtime manifest'
 versions={p:md.version(p) for p in manifest['resolved_runtime_versions']}
 assert versions==manifest['resolved_runtime_versions'],'runtime versions changed'
 packages={p['name']:md.version(p['name']) for p in manifest['gpu_packages']}
 assert all(packages[p['name']]==p['version'] for p in manifest['gpu_packages']),'pinned package version changed'
 headers=manifest['candidate_python_headers']
 assert headers==json.loads((base/'isolated-python-headers-proof.json').read_text())
 assert headers['official_InRelease_signature_verified'] is True and headers['system_packages_installed_or_upgraded'] is False
 deb=base/'python-dev-download'/f"{headers['package']}_{headers['package_version']}_arm64.deb"
 assert deb.stat().st_size==headers['download_bytes'] and file_sha(deb)==headers['official_apt_SHA256']
 for n,d in headers['header_files_sha256'].items():
  p=Path(n);assert not p.is_absolute() and '..' not in p.parts
  assert file_sha(base/'python-dev-headers'/p)==d,'extracted header file changed'
 assert subprocess.check_output(['/usr/bin/gcc','-dumpfullversion'],text=True).strip()==headers['compiler_version']
 assert file_sha('/usr/bin/gcc')==headers['compiler_binary_sha256']
 source=Path(importlib.util.find_spec('triton').origin).parent/'backends/nvidia/driver.c'
 assert file_sha(source)==headers['triton_driver_source_sha256']
 assert file_sha(base/'cpu-compiled-cuda-utils.so')==headers['CPU_compiled_output_sha256']
 expected_cpath=str(base/'python-dev-headers/usr/include/python3.12')+':'+str(base/'python-dev-headers/usr/include')
 assert os.environ.get('CPATH')==expected_cpath,'candidate-only header search path not set'
 weights=json.loads((base/'model-113abe4/weights-manifest.json').read_text())
 assert weights['repo']==MODEL and weights['revision']==REVISION and manifest['model_files']==weights['files']
 assert len(weights['files'])==13 and len({x['filename'] for x in weights['files']})==13
 for row in weights['files']:
  p=Path(row['filename']);assert not p.is_absolute() and '..' not in p.parts and '.' not in p.parts
  actual=base/'model-113abe4'/p
  assert actual.stat().st_size==row['bytes'] and file_sha(actual)==row['sha256'],'model file bytes changed'
 assert next(x['sha256'] for x in weights['files'] if x['filename']=='model.safetensors')==WEIGHT_SHA
 snapshot_path=base/'public-seed-snapshot-v07.json'
 assert file_sha(snapshot_path)==SNAPSHOT_FILE_SHA,'snapshot file bytes changed'
 snapshot=validate_snapshot(json.loads(snapshot_path.read_text()))
 assert snapshot['snapshot_sha256']==SNAPSHOT_SHA
 return manifest,snapshot,{'runtime_identity':'sha256:'+sha(manifest),'runtime_identity_kind':'canonical SHA256 of verified local manifest; not a container digest or remote attestation','runtime_manifest_file_sha256':file_sha(mp),'verified_code_sha256':code,'verified_package_versions':packages,'verified_runtime_versions':versions,'snapshot_file_sha256':SNAPSHOT_FILE_SHA,'local_bytes_verified_before_loading':True,'model_files_verified':13,'candidate_header_bytes_and_CPU_compile_verified':True,'candidate_header_CPATH_verified':True,'candidate_header_package':headers['package_version'],'candidate_header_package_sha256':headers['official_apt_SHA256'],'compiler_binary_sha256':headers['compiler_binary_sha256']}
