"""Independent NVIDIA NeMo Retriever open-model + cuVS candidate, not NIM.

Loopback only. Corpus is the user's fixed public seed snapshot. Retrieval never
issues production read receipts or assessment citations. No web fetch at runtime.
"""
from pathlib import Path
from contextlib import asynccontextmanager
import os, json, hashlib, time, math, threading, signal, importlib.metadata as md
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

MODEL = 'nvidia/llama-nemotron-embed-1b-v2'
REVISION = '113abe4acafa848e77ead9c0623205e511932348'
WEIGHT_SHA = '45f8440682a89ac577cc8d53b1bb345804772adb7b34e0573562e2fca4e62b0d'
BASE=Path(os.environ.get('CIZHENG_RETRIEVER_ROOT','/tmp/cizheng-retriever-v07'))
LOCK=threading.Lock(); STATE={}

def file_sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def available_kib():
 for line in Path('/proc/meminfo').read_text().splitlines():
  if line.startswith('MemAvailable:'):return int(line.split()[1])
 raise RuntimeError('MemAvailable required')

class Exact(BaseModel):model_config=ConfigDict(extra='forbid')
class Embeddings(Exact):
 model:Literal[MODEL]
 input:list[str]=Field(min_length=1,max_length=8)
 input_type:Literal['query','passage']
 modality:Literal['text']='text'
 embedding_type:Literal['float']='float'
 encoding_format:Literal['float']='float'
class Binding(Exact):
 document_id:str
 document_revision:int=Field(ge=1)
 document_sha256:str=Field(pattern='^[a-f0-9]{64}$')
class Retrieval(Exact):
 query:str=Field(min_length=1,max_length=200)
 expected_snapshot_sha256:str=Field(pattern='^[a-f0-9]{64}$')
 allowed_bindings:list[Binding]=Field(min_length=1,max_length=25)
 limit:int=Field(default=5,ge=1,le=8)
class Read(Exact):
 expected_snapshot_sha256:str=Field(pattern='^[a-f0-9]{64}$')
 document_id:str=Field(min_length=1,max_length=200)
 chunk_id:str=Field(min_length=1,max_length=200)


def encode(texts,kind):
 import torch
 if not texts or len(texts)>25 or any(not isinstance(t,str) or not 1<=len(t)<=2000 for t in texts):raise HTTPException(422,'input_budget_exceeded')
 if kind=='query' and any(len(t)>200 for t in texts):raise HTTPException(422,'query_budget_exceeded')
 vectors=[];tokens=0
 for start in range(0,len(texts),2):
  batch=STATE['tokenizer']([kind+': '+t for t in texts[start:start+2]],padding=True,truncation=False,return_tensors='pt')
  if batch['input_ids'].shape[1]>1024:raise HTTPException(413,'candidate_token_limit_1024_no_truncation')
  tokens+=int(batch['attention_mask'].sum());batch={k:v.to('cuda') for k,v in batch.items()}
  with torch.inference_mode():
   out=STATE['model'](**batch,use_cache=False).last_hidden_state.float()
   mask=batch['attention_mask'].bool().unsqueeze(-1)
   out=out.masked_fill(~mask,0).sum(dim=1)/mask.sum(dim=1)
   out=torch.nn.functional.normalize(out,p=2,dim=-1)
   assert out.shape[1]==2048 and torch.isfinite(out).all()
   vectors.append(out)
 return torch.cat(vectors,dim=0).contiguous(),tokens

@asynccontextmanager
async def lifespan(app):
 from cizheng.knowledge import sha,read_snapshot
 from runtime_contract import verify_runtime
 runtime_manifest,snapshot,runtime_binding=verify_runtime(BASE)
 import torch,cupy as cp
 from cuvs.neighbors import brute_force
 from transformers import AutoModel,AutoTokenizer
 before=available_kib()
 if before<45*1024*1024:raise RuntimeError('GPU loading denied by 45GiB startup reserve; coordinate resource allocation')
 model_dir=BASE/'model-113abe4'
 chunks=[];bindings={};sources={}
 for entry in snapshot['sources']:
  source=entry['source'];assert source['rights']=='authorized_text'
  bindings[source['document_id']]={'document_id':source['document_id'],'document_revision':source['document_revision'],'document_sha256':source['document_sha256']}
  sources[source['document_id']]=source
  for c in entry['chunks']:
   assert sha({'text':c['text'],'locator':c['locator']})==c['chunk_sha256']
   chunks.append({**c,'document_sha256':source['document_sha256'],'title':source['title']})
 assert len(chunks)==25 and len(bindings)==25
 torch.set_num_threads(4);torch.cuda.reset_peak_memory_stats()
 start=time.perf_counter()
 stop_watch=threading.Event()
 def watch_memory():
  while not stop_watch.wait(2):
   remaining=available_kib()
   if remaining<32*1024*1024:
    (BASE/'resource-stop-receipt.json').write_text(json.dumps({'candidate_only_stopped':True,'mem_available_kib':remaining,'minimum_kib':32*1024*1024,'production_services_touched':False})+'\n')
    os.kill(os.getpid(),signal.SIGTERM)
    return
 threading.Thread(target=watch_memory,daemon=True).start()
 STATE.update(snapshot=snapshot,chunks=chunks,bindings=bindings,read_snapshot=read_snapshot,brute_force=brute_force,cp=cp)
 STATE['tokenizer']=AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
 STATE['model']=AutoModel.from_pretrained(model_dir,local_files_only=True,trust_remote_code=True,torch_dtype=torch.bfloat16,attn_implementation='sdpa').eval().to('cuda')
 encoded,tokens=encode([c['text'] for c in chunks],'passage')
 # DLPack keeps the corpus vectors in GPU memory; cuVS builds/searches on CUDA.
 matrix=cp.from_dlpack(encoded)
 STATE['matrix']=matrix;STATE['index']=brute_force.build(matrix,metric='cosine')
 cp.cuda.runtime.deviceSynchronize()
 cpu=encoded.detach().cpu().numpy();np.save(BASE/'corpus-embeddings.npy',cpu)
 STATE['cpu_vectors']=cpu
 warmup,_=encode(['釉下装饰和钴蓝色料之间有什么限定关系？'],'query')
 d,n=brute_force.search(STATE['index'],cp.from_dlpack(warmup),3)
 cp.cuda.runtime.deviceSynchronize();assert cp.asarray(n).shape==(1,3)
 after=available_kib()
 if after<32*1024*1024:raise RuntimeError('Remaining system memory below 32GiB; candidate must not serve')
 health={
  **runtime_binding,
  'object':'health.response','message':'ready','ready':True,'runtime_kind':'NVIDIA NeMo Retriever open-model + cuVS GPU candidate; not Embedding NIM',
  'model':MODEL,'weights_revision':REVISION,'weights_sha256':WEIGHT_SHA,'precision':'torch.bfloat16','device':torch.cuda.get_device_name(),'capability':list(torch.cuda.get_device_capability()),
  'embedding_dimensions':2048,'corpus_sources':25,'corpus_chunks':25,'snapshot_sha256':snapshot['snapshot_sha256'],
  'embedding_matrix_sha256':file_sha(BASE/'corpus-embeddings.npy'),'matrix_cuda_array_interface':hasattr(matrix,'__cuda_array_interface__'),'matrix_dtype':str(matrix.dtype),'model_parameter_device':str(next(STATE['model'].parameters()).device),'model_parameter_dtype':str(next(STATE['model'].parameters()).dtype),'index_class':type(STATE['index']).__module__+'.'+type(STATE['index']).__name__,'index':'cuvs.neighbors.brute_force/cosine/CUDA',
  'startup_seconds':time.perf_counter()-start,'corpus_prompt_tokens':tokens,'mem_available_before_kib':before,'mem_available_after_kib':after,
  'torch_peak_allocated_bytes':torch.cuda.max_memory_allocated(),'torch_peak_reserved_bytes':torch.cuda.max_memory_reserved(),
  'versions':{p:(md.version(p) if list(md.distributions(name=p)) else None) for p in ['torch','transformers','cuvs-cu13','libcuvs-cu13','pylibraft-cu13','cupy-cuda13x','nemo-retriever']},
  'memory_guard_kind':'soft 2-second MemAvailable polling; not a hard memory limit','hard_memory_limit_enforced':False,
  'remaining_memory_watchdog_seconds':2,'minimum_remaining_memory_kib':32*1024*1024,
  'SDK_installed':bool(list(md.distributions(name='nemo-retriever'))),'SDK_pipeline_used':False,'default_production_backend_changed':False,'expert_validation':False,'professional_accuracy_measured':False}
 STATE['health']=health;(BASE/'startup-receipt.json').write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n')
 yield
 stop_watch.set()
 STATE.clear()

app=FastAPI(title='瓷证 · NVIDIA开放Retriever独立候选',lifespan=lifespan)
@app.get('/v1/health/ready')
def health():
 if 'health' not in STATE:raise HTTPException(503,'not_ready')
 return STATE['health']
@app.post('/v1/embeddings')
def embeddings(body:Embeddings):
 if body.input_type=='passage' and any(t not in {c['text'] for c in STATE['chunks']} for t in body.input):raise HTTPException(403,'only_frozen_authorized_passages')
 with LOCK:
  start=time.perf_counter();v,tokens=encode(body.input,body.input_type);values=v.cpu().tolist()
 return {'object':'list','data':[{'object':'embedding','index':i,'embedding':x} for i,x in enumerate(values)],'model':MODEL,'usage':{'prompt_tokens':tokens,'total_tokens':tokens},'elapsed_seconds':time.perf_counter()-start}
@app.post('/v1/retrieval')
def retrieval(body:Retrieval):
 if body.expected_snapshot_sha256!=STATE['snapshot']['snapshot_sha256']:raise HTTPException(409,'frozen_snapshot_changed')
 allowed=[];seen=set()
 for b in body.allowed_bindings:
  data=b.model_dump()
  if data!=STATE['bindings'].get(b.document_id) or b.document_id in seen:raise HTTPException(409,'case_source_boundary_mismatch')
  seen.add(b.document_id);allowed.append(b.document_id)
 positions=[i for i,c in enumerate(STATE['chunks']) if c['document_id'] in allowed]
 if not positions:raise HTTPException(422,'empty_allowed_corpus')
 with LOCK:
  start=time.perf_counter();q,tokens=encode([body.query],'query');cp=STATE['cp'];bf=STATE['brute_force']
  index=STATE['index'] if len(positions)==25 else bf.build(STATE['matrix'][cp.asarray(positions)],metric='cosine')
  retrieval_start=time.perf_counter();dist,neighbors=bf.search(index,cp.from_dlpack(q),min(body.limit,len(positions)));cp.cuda.runtime.deviceSynchronize()
  ids=cp.asnumpy(cp.asarray(neighbors))[0].tolist();ds=cp.asnumpy(cp.asarray(dist))[0].tolist();search_seconds=time.perf_counter()-retrieval_start
  qc=q.detach().cpu().numpy()[0];scores=STATE['cpu_vectors'][positions]@qc
  expected=np.argsort(-scores,kind='stable')[:min(body.limit,len(positions))].tolist()
  parity=(ids==expected)
  tolerance=2e-5
  score_errors=[abs(float(1-d)-float(scores[int(i)])) for i,d in zip(ids,ds)]
  cpu_cutoff=float(scores[expected[-1]])
  topk_within_tolerance=all(float(scores[int(i)])>=cpu_cutoff-tolerance for i in ids)
  crosscheck={'distance_tolerance':tolerance,'maximum_score_error':max(score_errors),'distance_matches_cpu_dot':max(score_errors)<=tolerance,'selected_scores_within_topk_tolerance':topk_within_tolerance,'ordered_ids_exactly_match':parity,'gpu_local_ids':ids,'numpy_local_ids':expected,'numpy_selected_scores':[float(scores[int(i)]) for i in ids],'tie_order_not_accuracy_claim':True}
  result=[]
  for localid,distance in zip(ids,ds):
   c=STATE['chunks'][positions[int(localid)]]
   result.append({k:c[k] for k in ['document_id','document_revision','document_sha256','chunk_id','chunk_sha256','locator','title']} | {'semantic_score':float(1-distance)})
 return {'query':body.query,'snapshot_sha256':body.expected_snapshot_sha256,'model':MODEL,'weights_revision':REVISION,'results':result,'gpu_search_seconds':search_seconds,'total_seconds':time.perf_counter()-start,'cosine_numpy_topk_parity':parity,'gpu_cpu_crosscheck':crosscheck,'body_read_performed':False,'citation_permission_issued':False,'notice':'相似性不是可靠性或真伪概率；须经原read_snapshot阅读与生产证据门禁，候选服务不授予引用权限。'}
@app.post('/v1/read')
def read(body:Read):
 if body.expected_snapshot_sha256!=STATE['snapshot']['snapshot_sha256']:raise HTTPException(409,'frozen_snapshot_changed')
 try:result=STATE['read_snapshot'](STATE['snapshot'],body.document_id,body.chunk_id,limit=1,max_chars=800)
 except Exception:raise HTTPException(404,'chunk_not_in_frozen_public_snapshot') from None
 return {**result,'production_read_receipt_issued':False,'citation_permission_issued':False,'candidate_only':True}
