"""Actual independent endpoint integration; preserve returned ranks, no quality claim."""
from pathlib import Path
import hashlib,json,time,copy,math
import httpx
from cizheng.knowledge import validate_snapshot,read_snapshot,sha
from integrations.nvidia_retriever.client import RetrieverClient,RetrieverError
from runtime_contract import verify_runtime,MODEL,REVISION,WEIGHT_SHA
BASE=Path('/tmp/cizheng-retriever-v07')
def file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
start=time.perf_counter();manifest,snapshot,local_binding=verify_runtime(BASE)
bindings=[{k:e['source'][k] for k in ('document_id','document_revision','document_sha256')} for e in snapshot['sources']]
runtime=local_binding['runtime_identity']
http=httpx.Client(base_url='http://127.0.0.1:8003',timeout=60,trust_env=False)
health_records=[]
def check_health(stage):
 response=http.get('/v1/health/ready');response.raise_for_status();h=response.json()
 expected={'ready':True,'message':'ready','model':MODEL,'weights_revision':REVISION,'weights_sha256':WEIGHT_SHA,'precision':'torch.bfloat16','embedding_dimensions':2048,'corpus_sources':25,'corpus_chunks':25,'snapshot_sha256':snapshot['snapshot_sha256'],'index':'cuvs.neighbors.brute_force/cosine/CUDA','capability':[12,1],'matrix_cuda_array_interface':True,'matrix_dtype':'float32','model_parameter_device':'cuda:0','model_parameter_dtype':'torch.bfloat16','index_class':'cuvs.neighbors.brute_force.brute_force.Index','SDK_pipeline_used':False,'default_production_backend_changed':False,'professional_accuracy_measured':False,'hard_memory_limit_enforced':False}
 expected.update(local_binding)
 checks={k:h.get(k)==v for k,v in expected.items()}
 checks['GB10_device']='GB10' in h.get('device','')
 checks['actual_embedding_matrix_bytes']=h.get('embedding_matrix_sha256')==file_sha(BASE/'corpus-embeddings.npy')
 assert all(checks.values()),{k:False for k,v in checks.items() if not v}
 health_records.append({'stage':stage,'actual_HTTP_status':response.status_code,'response_sha256':hashlib.sha256(response.content).hexdigest(),'response_bytes':len(response.content),'checks':checks,'health':h,'binding_scope':'Actual loopback endpoint response matched separately verified deployed bytes and runtime versions; operational identity binding, not cryptographic remote attestation'})
 return h
health=check_health('before_original_client_requests')
trace=[]
def audit(response):
 response.read();request=response.request
 sent=json.loads(request.content)
 out=response.json()
 trace.append({'method':request.method,'path':request.url.path,'status':response.status_code,
  'input_type':sent.get('input_type'),'input_count':len(sent.get('input',[])),
  'input_sha256':[hashlib.sha256(t.encode()).hexdigest() for t in sent.get('input',[])],
  'model':out.get('model'),'usage':out.get('usage'),
  'embedding_dimensions':[len(r['embedding']) for r in out.get('data',[])],
  'response_bytes':len(response.content),'response_sha256':hashlib.sha256(response.content).hexdigest(),
  'server_elapsed_seconds':out.get('elapsed_seconds')})
client=RetrieverClient('http://127.0.0.1:8003',manifest['model'],runtime,timeout=60)
client.http.event_hooks={'response':[audit]}
index=client.build_index(snapshot,snapshot['snapshot_sha256'],bindings)
assert len(index.vectors)==25 and {len(v) for v in index.vectors}=={2048}
queries=['看到青花蓝色能否证明钴料、年代和窑口？',
 '旧胶发黄、补色和紫外荧光能判断修复年代吗？',
 '仿年款与本朝归属怎样区分？',
 'Met 18.61.4 花觚的山水、花篮、福字与康熙记录是什么？',
 '白色沉积和剥釉能证明出土或海水环境吗？']
results=[]
for query in queries:
 t=time.perf_counter()
 ranked=client.search(index,query,expected_snapshot_sha256=snapshot['snapshot_sha256'],limit=5)
 gpu=http.post('/v1/retrieval',json={'query':query,'expected_snapshot_sha256':snapshot['snapshot_sha256'],'allowed_bindings':bindings,'limit':5});gpu.raise_for_status();gpu=gpu.json()
 assert gpu['gpu_cpu_crosscheck']['distance_matches_cpu_dot'] is True
 assert gpu['gpu_cpu_crosscheck']['selected_scores_within_topk_tolerance'] is True
 assert gpu['model']==MODEL and gpu['weights_revision']==REVISION and gpu['snapshot_sha256']==snapshot['snapshot_sha256']
 assert gpu['body_read_performed'] is False and gpu['citation_permission_issued'] is False
 ids=lambda rows:[(x['document_id'],x['chunk_id']) for x in rows]
 exact_order=ids(ranked['results'])==ids(gpu['results'])
 client_scores={tuple((x['document_id'],x['chunk_id'])):x['semantic_score'] for x in ranked['results']}
 gpu_scores={tuple((x['document_id'],x['chunk_id'])):x['semantic_score'] for x in gpu['results']}
 common=set(client_scores)&set(gpu_scores)
 score_error=max([abs(client_scores[k]-gpu_scores[k]) for k in common] or [0])
 cutoff_client=min(client_scores.values());cutoff_gpu=min(gpu_scores.values());tolerance=2e-5
 allowed_ties=all(gpu_scores[k]>=cutoff_client-tolerance for k in set(gpu_scores)-set(client_scores)) and all(client_scores[k]>=cutoff_gpu-tolerance for k in set(client_scores)-set(gpu_scores))
 assert score_error<=tolerance and allowed_ties
 ranking_check={'ordered_ids_exactly_match':exact_order,'shared_score_error':score_error,'tolerance':tolerance,'topk_membership_within_tolerance':allowed_ties,'tied_order_may_differ':True,'expert_relevance_judgment':None}
 reads=[]
 for match in ranked['results'][:2]:
  original=read_snapshot(snapshot,match['document_id'],match['chunk_id'],limit=1,max_chars=800)
  chunk=original['chunks'][0]
  assert chunk['chunk_sha256']==match['chunk_sha256'] and chunk['document_sha256']==match['document_sha256']
  assert sha({'text':chunk['text'],'locator':chunk['locator']})==chunk['chunk_sha256']
  endpoint=http.post('/v1/read',json={'expected_snapshot_sha256':snapshot['snapshot_sha256'],'document_id':match['document_id'],'chunk_id':match['chunk_id']});endpoint.raise_for_status();endpoint=endpoint.json()
  assert endpoint['chunks']==original['chunks']
  assert endpoint['citation_permission_issued'] is False and endpoint['production_read_receipt_issued'] is False
  reads.append({'source_title':original['source']['title'],'source_url':original['source']['source_url'],'rights':original['source']['rights'],'review_status':original['source']['review_status'],'chunk':chunk,'candidate_body_view_matches_original_read_snapshot':True,'production_read_receipt_created':False})
 results.append({'query':query,'existing_client_results':ranked,'actual_gpu_results':gpu,'original_read_snapshot':reads,'elapsed_seconds':time.perf_counter()-t,'expert_relevance_judgment':None,'client_gpu_crosscheck':ranking_check})
negative=[]
for label,payload in [('snapshot_changed',{'query':queries[0],'expected_snapshot_sha256':'0'*64,'allowed_bindings':bindings,'limit':5}),('binding_changed',{'query':queries[0],'expected_snapshot_sha256':snapshot['snapshot_sha256'],'allowed_bindings':[dict(bindings[0],document_sha256='0'*64)],'limit':5})]:
 r=http.post('/v1/retrieval',json=payload);assert r.status_code==409
 negative.append({'test':label,'actual_status':r.status_code,'detail':r.json()['detail']})
r=http.post('/v1/embeddings',json={'model':manifest['model'],'input':['not an authorized frozen passage'],'input_type':'passage'});assert r.status_code==403
negative.append({'test':'unauthorized_passage','actual_status':r.status_code,'detail':r.json()['detail']})
final_health=check_health('after_original_client_and_negative_requests')
assert final_health['runtime_identity']==health['runtime_identity']
client.close();http.close()
receipt={'scope':'Independent NVIDIA open embedding + cuVS actual service integration, not NIM or production replacement',
 'runtime_identity':runtime,'runtime_identity_kind':'Canonical SHA256 of actual locally verified deployment manifest; actual HTTP health binding also checked. Not a container digest or hardware attestation',
 'client_code_sha256':file_sha(BASE/'app-core-readonly/integrations/nvidia_retriever/client.py'),
 'corpus_snapshot_sha256':snapshot['snapshot_sha256'],'source_count':25,'chunk_count':25,
 'health_binding_checks':health_records,'independent_local_runtime_binding':local_binding,
 'health':health,'embedding_requests':trace,'queries':results,'negative_requests':negative,
 'actual_existing_client_http_requests':len(trace),'all_candidate_ids_and_body_hashes_valid':True,
 'gpu_numpy_and_client_numeric_crosschecks_passed':True,'all_ordered_topk_ids_exactly_match':all(x['client_gpu_crosscheck']['ordered_ids_exactly_match'] and x['actual_gpu_results']['cosine_numpy_topk_parity'] for x in results),'default_production_backend_changed':False,
 'production_read_receipt_created':False,'expert_validation':False,'professional_accuracy_measured':False,
 'total_seconds':time.perf_counter()-start}
(BASE/'real-client-acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'acceptance_complete':True,'actual_existing_client_embedding_requests':len(trace),'queries':len(results),'negative_requests':negative,'gpu_numpy_and_client_numeric_crosschecks_passed':True,'all_ordered_topk_ids_exactly_match':all(x['client_gpu_crosscheck']['ordered_ids_exactly_match'] and x['actual_gpu_results']['cosine_numpy_topk_parity'] for x in results),'elapsed_seconds':receipt['total_seconds'],'professional_accuracy_measured':False},ensure_ascii=False))
