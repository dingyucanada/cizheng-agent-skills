#!/usr/bin/env bash
# A model-free probe; never starts or modifies another container or service.
set -euo pipefail
readonly TRT_IMAGE='nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965'
mkdir -p integration-evidence/trt-deploy
python3 -S - <<'IMAGE_IDENTITY'
import json,subprocess
image='nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965'
result=subprocess.run(['docker','image','inspect',image],capture_output=True,text=True)
if result.returncode:raise SystemExit('fixed official image not locally complete; no pull or GPU probe attempted')
item=json.loads(result.stdout)[0]
assert item['Architecture']=='arm64' and item['Os']=='linux'
assert image in item['RepoDigests']
identity={key:item[key] for key in ('Id','Architecture','Os','Size','RepoDigests')}
from pathlib import Path
receipt=Path('integration-evidence/trt-deploy/local-image-identity.json')
if receipt.exists():assert json.loads(receipt.read_bytes())==identity, 'prior image identity differs'
else:
 with receipt.open('x') as stream:json.dump(identity,stream,sort_keys=True)
print(json.dumps(identity,sort_keys=True))
IMAGE_IDENTITY
docker run --rm --pull=never --name cizheng-trt-cuda-probe-smi \
  --device nvidia.com/gpu=all --network none --memory 4g \
  --security-opt no-new-privileges --cap-drop ALL \
  "$TRT_IMAGE" nvidia-smi \
  --query-gpu=name,driver_version,compute_cap --format=csv,noheader
# Only a 256x256 BF16 matmul, not a model load or text generation.
docker run --rm --pull=never --name cizheng-trt-cuda-probe-torch \
  --device nvidia.com/gpu=all --network none --memory 4g \
  --security-opt no-new-privileges --cap-drop ALL \
  "$TRT_IMAGE" python -c '
import json,torch,tensorrt_llm
assert torch.cuda.is_available()
a=torch.ones((256,256),device="cuda",dtype=torch.bfloat16)
b=a@a
torch.cuda.synchronize()
assert b.device.type=="cuda" and bool(torch.all(b==256).item())
print(json.dumps({"torch_version":torch.__version__,"cuda_version":torch.version.cuda,"tensorrt_llm_version":tensorrt_llm.__version__,"device_name":torch.cuda.get_device_name(),"compute_capability":list(torch.cuda.get_device_capability()),"operation":"256x256_bfloat16_cuda_matmul","expected_all_elements":256,"verified":True,"allocated_bytes":torch.cuda.memory_allocated(),"peak_allocated_bytes":torch.cuda.max_memory_allocated(),"model_loaded":False}))
' | tee integration-evidence/trt-deploy/cuda-probe.stdout
