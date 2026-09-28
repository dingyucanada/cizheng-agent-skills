from pathlib import Path
import json,time,importlib.metadata as md
import torch  # Read-only native CUDA library initialization, no checkpoint or model.
import numpy as np,cupy as cp
from cuvs.neighbors import brute_force
before=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))
start=time.perf_counter()
# Small fixed numeric matrix only; this does not load an embedding model.
x=np.arange(256,dtype=np.float32).reshape(32,8)/256
x=x/np.linalg.norm(x,axis=1,keepdims=True)
gpu=cp.asarray(x);index=brute_force.build(gpu,metric='cosine')
q=cp.asarray(x[[7,19]])
d,n=brute_force.search(index,q,4);cp.cuda.runtime.deviceSynchronize()
d,n=cp.asnumpy(cp.asarray(d)),cp.asnumpy(cp.asarray(n))
reference=np.argsort(-(x[[7,19]]@x.T),axis=1,kind='stable')[:,:4]
# Near-collinear rows may tie within rounding; compare similarity, not assumed ID order.
error=max(abs(float(d[i,j])-(1-float(x[[7,19]][i]@x[n[i,j]]))) for i in range(2) for j in range(4))
after=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))
p=cp.cuda.runtime.getDeviceProperties(0)
r={'no_model_loaded':True,'gpu_index_built':True,'cuvs_class':type(index).__module__+'.'+type(index).__name__,'array_cuda_interface':hasattr(gpu,'__cuda_array_interface__'),'device':p['name'].decode() if isinstance(p['name'],bytes) else p['name'],'compute_capability':[p['major'],p['minor']],'cuda_driver_version':cp.cuda.runtime.driverGetVersion(),'cuda_runtime_version':cp.cuda.runtime.runtimeGetVersion(),'matrix_shape':list(gpu.shape),'gpu_pool_used_bytes':cp.get_default_memory_pool().used_bytes(),'gpu_pool_total_bytes':cp.get_default_memory_pool().total_bytes(),'memory_available_before_kib':before,'memory_available_after_kib':after,'elapsed_seconds':time.perf_counter()-start,'gpu_neighbor_ids':n.tolist(),'numpy_reference_ids':reference.tolist(),'max_distance_math_error':error,'distance_math_passed':error<1e-4,'versions':{k:md.version(k) for k in ['cuvs-cu13','libcuvs-cu13','pylibraft-cu13','cupy-cuda13x']},'scope':'Actual small numeric GPU library validation, not Chinese retrieval or model deployment'}
assert r['gpu_pool_total_bytes']<1024**3 and error<1e-4
Path('/tmp/cizheng-retriever-v07/cuvs-no-model-probe.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r,ensure_ascii=False))
