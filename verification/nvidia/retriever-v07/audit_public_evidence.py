"""Offline audit of published actual Retriever records, no HTTP or GPU requests."""
from pathlib import Path
import json,hashlib

def sha(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
def text_sha(text):return hashlib.sha256(text.encode()).hexdigest()
b=Path(__file__).resolve().parent
snapshot=json.loads((b/'public-seed-snapshot-v07.json').read_text())
receipt=json.loads((b/'real-client-acceptance.json').read_text())
manifest=json.loads((b/'deployment-runtime-manifest.json').read_text())
assert receipt['runtime_identity']=='sha256:'+sha(manifest)
assert len(snapshot['sources'])==25 and receipt['corpus_snapshot_sha256']==snapshot['snapshot_sha256']
chunks={};ordered=[]
for entry in snapshot['sources']:
 source=entry['source'];assert source['rights']=='authorized_text'
 for chunk in entry['chunks']:
  assert sha({'text':chunk['text'],'locator':chunk['locator']})==chunk['chunk_sha256']
  chunks[(chunk['document_id'],chunk['chunk_id'])]={**chunk,'document_sha256':source['document_sha256']}
  ordered.append(text_sha(chunk['text']))
assert len(chunks)==25
identities=0;reads=0
for q in receipt['queries']:
 for kind in ['existing_client_results','actual_gpu_results']:
  rows=q[kind]['results'];assert len(rows)==5
  for row in rows:
   original=chunks[(row['document_id'],row['chunk_id'])]
   for field in ['document_id','document_revision','document_sha256','chunk_id','chunk_sha256','locator']:
    assert row[field]==original[field]
   identities+=1
 for row in q['original_read_identity_checks']:
  original=chunks[(row['document_id'],row['chunk_id'])]
  for field in ['document_id','document_revision','document_sha256','chunk_id','chunk_sha256','locator']:
   assert row[field]==original[field]
  assert row['body_text_sha256']==text_sha(original['text'])
  assert row['candidate_body_view_matches_original_read_snapshot'] is True
  assert row['production_read_receipt_created'] is False
  reads+=1
 assert q['actual_gpu_results']['gpu_cpu_crosscheck']['distance_matches_cpu_dot'] is True
 assert q['client_gpu_crosscheck']['topk_membership_within_tolerance'] is True
trace=receipt['embedding_requests'];assert len(trace)==9
assert [x for r in trace if r['input_type']=='passage' for x in r['input_sha256']]==ordered
assert [r['input_sha256'][0] for r in trace if r['input_type']=='query']==[text_sha(q['query']) for q in receipt['queries']]
assert all(r['status']==200 and r['model']==manifest['model'] and set(r['embedding_dimensions'])=={2048} for r in trace)
assert all(all(h['checks'].values()) and h['health']['runtime_identity']==receipt['runtime_identity'] for h in receipt['health_binding_checks'])
assert receipt['professional_accuracy_measured'] is False and receipt['production_read_receipt_created'] is False
result={'scope':'Offline independent public-record audit; no network/model requests. Confirms recorded identities/numeric execution, not expert relevance or accuracy','runtime_identity':receipt['runtime_identity'],'frozen_sources':25,'frozen_chunks':25,'actual_request_records':9,'queries':5,'returned_identity_rows_verified':identities,'original_body_text_SHA_views_verified':reads,'health_checks_per_observation':[len(x['checks']) for x in receipt['health_binding_checks']],'public_client_sha256':hashlib.sha256((b/'real-client-acceptance.json').read_bytes()).hexdigest(),'source_client_sha256':receipt['public_normalization']['source_receipt_sha256'],'all_checks_passed':True,'GPU_or_HTTP_requests_in_this_audit':False,'expert_validation':False,'professional_accuracy_measured':False}
(b/'independent-public-record-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
