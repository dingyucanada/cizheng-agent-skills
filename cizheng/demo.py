"""Import an attributed public teaching example; no network or model calls."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from .agent import ROOT
from .store import Store
from .schemas import NewCase, CatalogueIn
from .knowledge import KnowledgeStore
from .knowledge_seed import seed_knowledge
from .business_records import BusinessRecords


def import_demo(directory):
    source=ROOT/'examples/public-demo';meta=json.loads((source/'sources.json').read_text())
    store=Store(directory)
    case=store.create_case({'request_id':'public-demo-met-48607-v1',
        'title':'公开教学案 · Met山水纹花觚 18.61.4',
        'question':'只据照片，记录器形、纹饰与可见部位；哪些证据仍不能支持独立制作时期核验？',
        'target_attribution':'馆藏记载是公开资料，不是本项目独立鉴定结果',
        'source_declaration':'公开教学样例，非盲测。Met馆藏18.61.4；来源见 examples/public-demo/sources.json；未取得实物或原始拍摄记录。'})
    case=store.read('case',case['id'])
    for item in meta['images']:
        raw=(source/item['file']).read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha!=item['sha256']:raise ValueError('公开教学图与来源清单不一致')
        if any(m['sha256']==sha for m in case['media']):continue
        case=store.add_evidence(case['id'],{'request_id':'demo-photo-'+sha,
            'expected_case_revision':case['revision'],'filename':item['file'],'image_base64':base64.b64encode(raw).decode(),
            'view':item['view'],'edit_declaration':'下载馆方公开JPEG，未改像素；不是相机原文件，拍摄处理历史未知',
            'source':meta['object_url']+'；公开教学，CC0'})['case']
    return {'case_id':case['id'],'media_count':len(case['media']),'model_calls':0,'assessment':None,'scope':'public teaching; NOT blind benchmark'}


def import_professional_demos(directory):
    """Three attributed objects, no synthetic findings or implicit expert review."""
    source = ROOT / 'examples/public-demo'
    metadata = json.loads((source / 'professional-cases.json').read_text())
    store = Store(directory); knowledge = KnowledgeStore(directory); seed_knowledge(knowledge)
    sources = knowledge.list_sources(limit=500)['sources']
    result = []
    for item in metadata['objects']:
        body = NewCase(request_id='professional-demo-'+item['object_id'],
                       title='公开教学 · '+item['catalogue']['object_name'],
                       workflow=item['workflow'], catalogue=item['catalogue'],
                       question='整理公开图像与馆藏资料，明确观察范围、资料限制及下一项必要补证。',
                       target_attribution='已知馆藏资料，仅作教学；不是独立鉴定结论',
                       source_declaration='公开教学样例，非盲测、非真实委托。'+item['object_url']+
                                          '；原机构资料与本项目记录分别呈现，未取得实物。').model_dump()
        # Reuse the identity of an earlier teaching import across schema upgrades.
        # Do not replay a changed request or overwrite later operator edits.
        with store.tx() as db:
            prior = db.execute('SELECT response FROM requests WHERE key=?',
                               ('case:'+body['request_id'],)).fetchone()
        case = (store.read('case', json.loads(prior[0])['id']) if prior
                else store.create_case(body))
        case = store.read('case', case['id'])
        for image in item['images']:
            raw = (source / image['file']).read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if sha != image['sha256']: raise ValueError('公开教学照片来源哈希不一致')
            if any(m['sha256'] == sha for m in case['media']): continue
            case = store.add_evidence(case['id'], {'request_id':'pro-demo-photo-'+sha,
                'expected_case_revision':case['revision'], 'filename':image['file'],
                'image_base64':base64.b64encode(raw).decode(), 'view':image['view'],
                'edit_declaration':'馆方公开JPEG，原下载字节未修改；拍摄与处理历史未知',
                'source':item['object_url']+'；Public Domain / CC0，公开教学'})['case']
        matching = [d for d in sources if d['source_url'] == item['object_url']]
        for document in matching:
            if any(b['document_id'] == document['id'] for b in case.get('knowledge_links', [])): continue
            case = store.link_document(case['id'], {'request_id':'pro-demo-pin-'+document['id']+'-c'+str(case['revision']),
                'expected_case_revision':case['revision'], 'document_id':document['id']})
        result.append({'case_id':case['id'], 'object_id':item['object_id'], 'workflow':case['workflow'],
                       'media_count':len(case['media']), 'model_calls':0, 'assessment':None})
    return {'scope':metadata['scope'], 'cases':result}


def import_guided_demos(directory):
    """Prepare complete public records without inventing a run or assessment.

    Stable per-step request IDs permit recovery after an interrupted import.
    Once an import completes, repeat calls read its current case and never
    overwrite, restore, or append to a later operator's edits or review history.
    Human-authored comparison findings remain in the static teaching pack; the
    backend stores only photos, documents, located operator notes and reviews.
    """
    source = ROOT / 'examples/public-demo'
    pack = json.loads((source / 'guided-cases.json').read_text())
    if pack.get('mode') != 'guided_teaching' or pack.get('ai_inference_performed') is not False:
        raise ValueError('教学包须明确未进行模型推理')
    # Validate all bytes before a partial case is written. Case documents are
    # project-original TXT, not scraped museum pages or simulated legal records.
    for item in pack['cases']:
        for image in item['images']:
            filename = Path(image['file']).name
            if image['file'] != 'assets/' + filename:
                raise ValueError('教学照片路径不符合公开包约定')
            if hashlib.sha256((source / filename).read_bytes()).hexdigest() != image['sha256']:
                raise ValueError('公开教学照片来源哈希不一致')
        for document in item['documents']:
            if (document.get('origin') != 'project_curated_teaching'
                    or hashlib.sha256(document['text'].encode('utf-8')).hexdigest() != document['sha256']):
                raise ValueError('教学原创文字与清单不一致')
    store = Store(directory)
    knowledge = KnowledgeStore(directory)
    seed_knowledge(knowledge)
    records = BusinessRecords(store, knowledge)
    sources = knowledge.list_sources(limit=500)['sources']

    def prior(key):
        with store.tx() as db:
            row = db.execute('SELECT response FROM requests WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    result = []
    for item in pack['cases']:
        prefix = 'guided-public-' + item['id'] + '-v1'
        body = NewCase(request_id=prefix,
            title='完整教学案 · ' + item['title'], workflow=item['role'], catalogue=item['catalogue'],
            question='完成公开资料编目、定位观察、来源与状况缺项整理、准备复核和交接；不形成独立鉴定结论。',
            target_attribution='馆方资料标签与人工记录分开；本项目未独立鉴定',
            source_declaration=pack['notice'] + ' ' + item['object_url']).model_dump()
        existing = prior('case:' + prefix)
        case = (store.read('case', existing['id']) if existing else store.create_case(body))
        identifier = case['id']
        if not prior('guided-demo-complete:' + prefix):
            # Test each durable step's request record rather than replaying its
            # old optimistic revision against a case already edited by a user.
            for image in item['images']:
                step = prefix + '-image-' + image['id']
                if prior('evidence:' + identifier + ':' + step):
                    continue
                case = store.read('case', identifier)
                raw = (source / Path(image['file']).name).read_bytes()
                store.add_evidence(identifier, {
                    'request_id': step, 'expected_case_revision': case['revision'],
                    'filename': Path(image['file']).name, 'image_base64': base64.b64encode(raw).decode(),
                    'view': image['view'], 'edit_declaration': image['edit_declaration'],
                    'source': item['object_url'] + '；Public Domain / CC0，已知对象公开教学'})
            for document in item['documents']:
                step = prefix + '-doc-' + document['id']
                if prior('evidence-document:' + identifier + ':' + step):
                    continue
                case = store.read('case', identifier)
                records.add_document(identifier, {
                    'request_id': step, 'expected_case_revision': case['revision'],
                    'filename': document['filename'],
                    'file_base64': base64.b64encode(document['text'].encode('utf-8')).decode(),
                    'source': '项目原创公开教学摘记；来源：' + document['source_url'],
                    'rights_note': document['rights_note'], 'permission': 'local_use_authorized'})
            for document in [s for s in sources if s['source_url'] in {card['url'] for card in item['sources']}]:
                step = prefix + '-pin-' + document['id']
                if prior('document-link:' + identifier + ':' + step):
                    continue
                case = store.read('case', identifier)
                store.link_document(identifier, {'request_id': step,
                    'expected_case_revision': case['revision'], 'document_id': document['id'],
                    'document_revision': document['revision'], 'document_sha256': document['document_sha256']})
            case = store.read('case', identifier)
            media = {m['filename']: m['id'] for m in case['media']}
            photo_by_id = {i['id']: media[Path(i['file']).name] for i in item['images']}
            for observation in item['observations']:
                step = prefix + '-annotation-' + observation['id']
                if prior('annotation:' + identifier + ':' + step):
                    continue
                case = store.read('case', identifier)
                region = observation['region']
                store.annotate(identifier, {'request_id': step, 'expected_case_revision': case['revision'],
                    'media_id': photo_by_id[observation['image_id']],
                    'region': [region['x'], region['y'], region['x'] + region['width'], region['y'] + region['height']],
                    'feature': observation['feature'],
                    'observation': '项目人工编写的公开教学记录；非模型输出、非专家意见。' + observation['text']})
            for event in item['provenance']:
                step = prefix + '-event-' + event['id']
                if prior('provenance-event:' + identifier + ':' + step):
                    continue
                case = store.read('case', identifier)
                document = next(d for d in case['evidence_documents'] if d['filename'] == event['document_id'] + '.txt')
                records.add_provenance_event(identifier, {'request_id': step,
                    'expected_case_revision': case['revision'],
                    **{k: event[k] for k in ('date_text', 'event_type', 'status', 'party', 'place', 'description', 'object_link_basis')},
                    'evidence': [{'kind': 'attachment', 'document_id': document['id'],
                                  'locator': event['locator'], 'sha256': document['sha256']}]})
            step = prefix + '-condition'
            if not prior('condition-check:' + identifier + ':' + step):
                case = store.read('case', identifier)
                records.add_condition_check(identifier, {'request_id': step,
                    'expected_case_revision': case['revision'], 'date_text': '公开教学记录；非现场检查日期',
                    'method': 'image', 'observer': '瓷证项目人工教学编写者（非专家身份认证）',
                    'area': '公开整体照片呈现范围',
                    'observation': '已预置可定位的图像描述和待补证事项；照片没有展示的部位不作状况结论，不写无修复或真品保证。',
                    'limitations': item['limits'], 'media_ids': list(photo_by_id.values()), 'evidence': []})
            step = prefix + '-preparation-review'
            if not prior('preparation-review:' + identifier + ':' + step):
                case = store.read('case', identifier)
                records.add_preparation_review(identifier, {'request_id': step,
                    'expected_case_revision': case['revision'],
                    'expected_preparation_review_revision': case['preparation_review_revision'],
                    'state': 'request_evidence', 'reviewer': '瓷证项目教学编写者（未认证，非真实专家复核）',
                    'note': '资料与定位观察已预置；真实研判仍需缺项材料，且未进行模型推理或实物检查。',
                    'basis': '公开JPEG、项目原创TXT、关联来源摘要与明确未核验事项。教学编写仅检查资料准备范围。'})
            store.mutate('guided-demo-complete', {'request_id': prefix, 'case_id': identifier},
                         lambda db: {'case_id': identifier, 'teaching_import_completed': True})
        current = store.read('case', identifier)
        result.append({'case_id': identifier, 'object_id': item['id'], 'workflow': current['workflow'],
                       'media_count': len(current['media']), 'document_count': len(current['evidence_documents']),
                       'observation_count': len(current['annotations']), 'case_revision': current['revision'],
                       'model_calls': 0, 'assessment': None, 'ai_inference_performed': False})
    return {'scope': pack['notice'], 'cases': result, 'model_calls': 0, 'ai_inference_performed': False,
            'teaching_findings_origin': 'project_curated_teaching', 'assessment': None}


def main():
    p=argparse.ArgumentParser(description='本地导入公开教学案，不调用模型、不形成鉴定结果')
    p.add_argument('--data-dir',type=Path,default=ROOT/'data')
    kind = p.add_mutually_exclusive_group()
    kind.add_argument('--professional',action='store_true',help='导入三个公开教学档案与项目原创来源摘要')
    kind.add_argument('--guided',action='store_true',help='导入完整三案：图片、原创TXT、定位观察、来源与人工准备复核；不调用模型')
    a=p.parse_args()
    importer = import_guided_demos if a.guided else import_professional_demos if a.professional else import_demo
    print(json.dumps(importer(a.data_dir),ensure_ascii=False))


if __name__=='__main__':main()
