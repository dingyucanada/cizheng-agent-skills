"""One real, bounded public-image workflow, isolated from the business store.

Run on the authorized Spark only. This is a technical/AI-review experiment,
not expert ceramic validation. Labels remain separate from model inputs.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import time

from cizheng import schemas as S
from cizheng.agent import Engine, LocalModel
from cizheng.claim_support_audit import audit_claim_support, review_template
from cizheng.knowledge import KnowledgeStore, METADATA_FIELDS
from cizheng.store import Store, uid


class RecordedModel(LocalModel):
    def __init__(self, *args, record_dir, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_dir = record_dir
        self.request_count = 0

    async def complete(self, messages, timeout):
        self.request_count += 1
        index = self.request_count
        encoded = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
        started = time.monotonic()
        record = {'request_index':index, 'messages_sha256':hashlib.sha256(encoded).hexdigest(),
                  'message_bytes':len(encoded), 'timeout_seconds':timeout}
        try:
            text, usage = await super().complete(messages, timeout)
            record.update(response_sha256=hashlib.sha256(text.encode()).hexdigest(),
                          response_text=text, usage=usage, succeeded=True)
            return text, usage
        except Exception as exc:
            record.update(succeeded=False, error_type=type(exc).__name__)
            raise
        finally:
            record['seconds'] = round(time.monotonic()-started, 3)
            (self.record_dir/f'request-{index:02d}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-record', required=True)
    parser.add_argument('--images', nargs='+', required=True)
    parser.add_argument('--model-url', default='http://127.0.0.1:8005/v1')
    parser.add_argument('--model', default='Qwen/Qwen3-VL-8B-Instruct')
    args = parser.parse_args()
    if not 1 <= len(args.images) <= 2:
        raise ValueError('This comparison uses one or two public images')
    out = Path(args.output).resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    (out/'requests').mkdir(mode=0o700)
    os.environ.update(CIZHENG_GUIDED_WORKFLOW='1', CIZHENG_COMPACT_ACTIONS='1',
                      CIZHENG_DISABLE_THINKING=('0' if args.model=='Qwen/Qwen3-VL-8B-Instruct' else '1'),
                      CIZHENG_STRUCTURED_OUTPUTS='1')
    store = Store(out/'case-data')
    model = RecordedModel(args.model_url, args.model, record_dir=out/'requests')
    engine = Engine(store, model)
    case = store.create_case(S.NewCase(request_id=uid('req'),
        title='公开图像理由核查；非专家验证',
        question='记录这组照片的具体可见细节，分别说明时期、窑口、装饰风格的依据和关键补证。馆方文字记载另列来源上下文；不能把普通纹样当断代证据。',
        target_attribution='照片可支持的有限研究；未指定制作时期和窑口',
        source_declaration='Met公开CC0图像，用于技术与AI阅评；没有独立专家标签。').model_dump())
    inputs=[]
    for index, name in enumerate(args.images):
        raw = Path(name).read_bytes()
        inputs.append({'input_id':f'photo-{index+1}', 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)})
        case = store.add_evidence(case['id'], S.EvidenceIn(request_id=uid('req'),
            expected_case_revision=case['revision'], filename=f'photo-{index+1}.jpg',
            image_base64=base64.b64encode(raw).decode(), view=f'公开拍摄视角{index+1}',
            edit_declaration='公开图像原始字节；模型工具将保存明确的显示派生',
            source='公开机构图像，来源清单独立于像素观察', capture_role='overall').model_dump())['case']
    source_record=json.loads(Path(args.source_record).read_text())
    metadata={k:v for k,v in source_record['source'].items() if k in METADATA_FIELDS}
    document=KnowledgeStore(store.root).add_document({**metadata,
        'chunks':[{'text':c['text'],'locator':c['locator']} for c in source_record['chunks']]})['source']
    case=store.link_document(case['id'], S.CaseDocumentIn(request_id=uid('req'),
        expected_case_revision=case['revision'], document_id=document['document_id'],
        document_revision=document['revision'],document_sha256=document['document_sha256']).model_dump())
    start=store.start_run(case['id'],S.RunIn(request_id=uid('req'),
        expected_case_revision=case['revision'],mode='skills').model_dump(),engine.versions('skills'))
    run_id=start['run_id'];began=time.monotonic()
    await engine.execute(run_id)
    run=store.read('run',run_id)
    (out/'final-run.json').write_text(json.dumps(run,ensure_ascii=False,indent=2))
    audit=audit_claim_support(run)
    (out/'claim-support-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    (out/'review-template.json').write_text(json.dumps(review_template(audit['packet']),ensure_ascii=False,indent=2))
    summary={'model':model.identity(),'state':run['state'],'seconds':round(time.monotonic()-began,3),
        'run_id':run_id,'input_images':inputs,'observation_count':len(run.get('observations',[])),
        'assessment_present':bool(run.get('assessment')),'error':run.get('error'),
        'scope':'public teaching images; isolated real Spark workflow',
        'expert_validation':False,'ceramic_accuracy':'not_measured','claim_support':'awaiting_separate_review'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='model'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    asyncio.run(main())
