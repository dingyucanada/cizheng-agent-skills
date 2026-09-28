"""Synthetic documentary protocol tests; no ceramic claims or real model outputs.

The scripted fixture identifies itself as synthetic and only exercises software
contracts. External networking, the production model and StepFun are forbidden.
"""
import asyncio
import base64
import hashlib
import json
import time
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cizheng import schemas as S
from cizheng.agent import Engine, LocalModel, bounded_messages, case_projection, system_prompt, tools_for_mode
from cizheng.api import create_app, export_bundle
from cizheng.knowledge import KnowledgeDocumentIn, KnowledgeStore
from cizheng.reporting import html_report, markdown_report
from cizheng.review_client import ReviewService, StepFunClient, prepare_review, suggested_packet
from cizheng.store import Problem, Store, digest, uid


@pytest.fixture(autouse=True)
def forbid_production_calls(monkeypatch):
    import socket
    import urllib.request
    async def forbidden_async(*args, **kwargs):
        pytest.fail('No production model, OCR or external HTTP allowed in documentary protocol tests')
    def forbidden_sync(*args, **kwargs):
        pytest.fail('No external socket or downloader allowed')
    monkeypatch.setattr(LocalModel, 'complete', forbidden_async)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_async)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_async)
    monkeypatch.setattr(socket, 'create_connection', forbidden_sync)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden_sync)


def mutation(case):
    return {'request_id': uid('req'), 'expected_case_revision': case['revision']}


def new_case(store, task='documentary_audit'):
    return store.create_case(S.NewCase(request_id=uid('req'), title='SYNTHETIC documentary test',
        question='测试文书陈述是否涵盖移交编号，不是真实文物鉴定',
        source_declaration='完全合成的软件协议材料；不是馆藏或专家判断', research_task=task).model_dump())


def attach(store, case, text='合成甲方声明：测试编号 SYN-001。\n\n合成乙方声明：尚未登记移交日期。', suffix='txt'):
    # Exercise the real registered FastAPI route and attachment validators.
    app = create_app(store.root, model=SyntheticDocumentaryModel())
    app.state.engine.schedule = lambda identifier: None
    with TestClient(app) as client:
        token = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        raw = text.encode('utf-8') if suffix == 'txt' else b'%PDF-1.7\nSYNTHETIC NOT PARSED\n%%EOF\n'
        response = client.post('/api/cases/'+case['id']+'/evidence-documents', headers=token,
            json=mutation(case) | {'file_base64': base64.b64encode(raw).decode(), 'filename': 'synthetic.'+suffix,
                'source': '合成本地测试材料', 'rights_note': '测试原创文字许可本地使用，非机构资料。',
                'permission': 'local_use_authorized'})
        assert response.status_code == 201, response.text
        return response.json()['case'], response.json()['document']


def start(store, case, model=None, mode='skills'):
    engine = Engine(store, model or SyntheticDocumentaryModel())
    identifier = store.start_run(case['id'], mutation(case) | {'mode': mode},
        engine.versions(mode, case['research_task']))['run_id']
    return engine, identifier


def active(store, case, mode='plain'):
    engine, rid = start(store, case, mode=mode)
    store.update_run(rid, lambda run: run.update(state='running', started_at=time.time()))
    return engine, rid


def citation(read):
    value = {key: read[key] for key in ('kind', 'document_id', 'document_sha256', 'chunk_id',
                                      'chunk_sha256', 'locator', 'read_id')}
    if read['kind'] == 'knowledge':
        value['document_revision'] = read['document_revision']
    value['relevance'] = '合成片段仅用来验证实际已读引用与问题的对应'
    return value


def findings(read):
    return S.DocumentaryAssessment(summary='合成测试材料对编号有声明，未核验其真实经历。',
        documentary_findings=[S.DocumentaryFinding(question='已读材料是否涵盖移交时间？',
            status='missing', finding='本次已读片段未登记可回查的移交时间；不推断其它材料不存在。',
            evidence_refs=[S.DocumentaryCitation(**citation(read))],
            next_evidence='请操作人补充带日期及编号的移交原件并人工核对。',
            limitations=['合成软件测试；陈述并非历史真实性证明。'])],
        limitations=['文书内容、来源及器物同一性均未核验。'],
        revision_explanation='此为合成协议初次核查，无真实结论。')


class SyntheticDocumentaryModel:
    configured = True

    def __init__(self, wrong_hash=False):
        self.calls = []
        self.wrong_hash = wrong_hash

    def identity(self):
        return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'scripted-documentary-protocol-fixture'}

    async def complete(self, messages, timeout):
        self.calls.append(deepcopy(messages))
        results = []
        for message in messages:
            content = message['content']
            assert not isinstance(content, list), 'Documentary fixture must never receive image content'
            if content.startswith('工具结果（数据）：'):
                results.append(json.loads(content.split('：', 1)[1]))
        def got(name):
            return [item['result'] for item in results if item['tool'] == name]
        def action(tool, **arguments):
            return {'tool': tool, 'arguments': arguments}
        def send(*actions):
            return json.dumps({'actions': list(actions)}, ensure_ascii=False), {'synthetic_fixture': True}
        if not got('read_case'):
            return send(action('read_case'), action('discover_skills'), action('load_skill', name='documentary-evidence-audit'))
        if not got('read_evidence_document'):
            return send(action('read_evidence_document', document_id=got('read_case')[0]['case']['evidence_documents'][0]['id']))
        read = got('read_evidence_document')[0]['chunks'][0]
        value = findings(read).model_dump()
        if self.wrong_hash:
            value['documentary_findings'][0]['evidence_refs'][0]['document_sha256'] = '0'*64
        return send(action('record_documentary_findings', **value), action('build_opinion'))


async def expose(engine, rid, result):
    # One real software model-protocol success carrying the exact tool result.
    return await engine.call(rid, [{'role': 'system', 'content': 'SYNTHETIC fixture only'},
        {'role': 'user', 'content': '工具结果（数据）：'+json.dumps({'tool': 'read_evidence_document', 'result': result}, ensure_ascii=False)}], 'action')


class AckOnlySyntheticModel(SyntheticDocumentaryModel):
    async def complete(self, messages, timeout):
        self.calls.append(deepcopy(messages))
        return '{"actions":[{"tool":"read_case","arguments":{}}]}', {'synthetic_fixture': True}


def test_documentary_md_and_html_include_only_this_saved_report_nvidia_audit(tmp_path):
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store))
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    audit = {'id': uid('nvaudit'), 'case_id': case['id'], 'case_revision': case['revision'],
             'assessment_run_id': rid, 'source_case_revision': run['case_revision'],
             'state': 'succeeded', 'result': {'status': 'no_read_evidence',
                                             'snapshot_sha256': run['versions']['knowledge_snapshot_sha256']}}
    with store.tx() as db:
        store.put(db, 'nvidia_audit', audit)
        store.put(db, 'nvidia_audit', dict(audit, id=uid('nvaudit'), assessment_run_id='run-other'))
    bundle = export_bundle(store, store.read('case', case['id']), run)
    assert [a['id'] for a in bundle['nvidia_audits']] == [audit['id']]
    markdown = markdown_report(bundle)
    rendered = html_report(bundle, lambda _: pytest.fail('Documentary report must not load images'))
    assert audit['id'] in markdown and audit['id'] in rendered
    assert 'NVIDIA 引用身份核查' in markdown and 'no_read_evidence' in rendered
    assert 'run-other' not in markdown and 'run-other' not in rendered


def test_real_documentary_zero_photo_loop_and_report(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    model = SyntheticDocumentaryModel()
    engine, rid = start(store, case, model)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assert run['state'] == 'ready', run.get('error')
    assert run['research_task'] == 'documentary_audit'
    assert run['snapshot']['media'] == [] and run['observations'] == []
    assert run['assessment']['documentary_findings'][0]['status'] == 'missing'
    assert 'claims' not in run['assessment']
    assert run['assessment']['authenticity_verified'] is False
    assert run['assessment']['statement_truth_verified'] is False
    read = run['read_evidence_documents'][0]
    assert read['document_sha256'] == document['sha256']
    assert read['read_id'] in run['main_seen_text_read_ids']
    assert len(model.calls) == 3 and all(len(json.dumps(m, ensure_ascii=False)) < 34000 for m in model.calls)
    events = [event for event in run['events'] if event['type'] == 'tool_result']
    assert all(event['result_sha256'] == digest(event['result']) for event in events)
    bundle = export_bundle(store, store.read('case', case['id']), run)
    markdown = markdown_report(bundle)
    rendered = html_report(bundle, lambda _: pytest.fail('Documentary HTML must not load photos'))
    assert '文字凭据核查' in markdown and read['text'] in markdown
    assert read['chunk_sha256'] in markdown and document['sha256'] in rendered
    assert '## 归属意见' not in markdown and '<img ' not in rendered
    assert '未核验' in rendered


def test_wrong_citation_model_failure_has_no_fake_current_result(tmp_path):
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store))
    engine, rid = start(store, case, SyntheticDocumentaryModel(wrong_hash=True))
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assert run['state'] == 'failed' and run['assessment'] is None
    assert store.read('case', case['id'])['current_run_id'] is None
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert len(errors) == 2
    assert [event['repair_allowed'] for event in errors] == [True, False]
    assert all(event['error_type'] == 'ValueError' and '本轮实际阅读' in event['detail']
               for event in errors)
    assert run['model_calls'] == 4


@pytest.mark.parametrize('field,value', [('document_sha256', '0'*64), ('chunk_sha256', '0'*64),
    ('document_id', 'evidoc_'+'0'*32), ('chunk_id', 'not-read'), ('locator', '虚构第99页'), ('read_id', 'read_not_actual')])
def test_each_attachment_citation_identity_must_match_actual_read(tmp_path, field, value):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    engine.model = AckOnlySyntheticModel()
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    asyncio.run(expose(engine, rid, result))
    payload = findings(result['chunks'][0]).model_dump()
    payload['documentary_findings'][0]['evidence_refs'][0][field] = value
    with pytest.raises(ValueError, match='实际阅读'):
        Engine.validate_documentary_assessment(store.read('run', rid), S.DocumentaryAssessment.model_validate(payload))


def test_reading_same_action_batch_does_not_mean_main_agent_received_text(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    with pytest.raises(ValueError, match='成功的新动作轮'):
        asyncio.run(engine.tool(rid, 'record_documentary_findings', findings(result['chunks'][0])))
    assert store.read('run', rid)['assessment'] is None


def test_pdf_only_metadata_no_ocr_no_text_read_receipt(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store), suffix='pdf')
    case, _ = attach(store, case, text='合成许可TXT仅使任务可启动，PDF仍不得读取正文。')
    engine, rid = active(store, case)
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    assert result['content_read'] is False and result['ocr_performed'] is False and result['chunks'] == []
    assert '未OCR' in result['notice']
    run = store.read('run', rid)
    assert run.get('read_evidence_documents', []) == []
    fake = {'kind': 'attachment', 'document_id': document['id'], 'document_sha256': document['sha256'],
            'chunk_id': 'fake_pdf_text', 'chunk_sha256': '0'*64, 'locator': '虚构第1页', 'read_id': 'fake_pdf_read'}
    with pytest.raises(ValueError, match='实际阅读'):
        Engine.validate_documentary_assessment(run, findings(fake))


def test_foreign_and_unknown_permission_documents_rejected(tmp_path):
    store = Store(tmp_path)
    own, own_doc = attach(store, new_case(store))
    foreign, foreign_doc = attach(store, new_case(store), text='另一案完全合成私有文字')
    engine, rid = active(store, own)
    with pytest.raises(ValueError, match='本案'):
        asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=foreign_doc['id'])))
    store.update_run(rid, lambda run: run['snapshot']['evidence_documents'][0].update(permission='unknown'))
    with pytest.raises(ValueError, match='许可'):
        asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=own_doc['id'])))


def test_document_bytes_hash_mismatch_is_rejected(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    store.update_run(rid, lambda run: run['snapshot']['evidence_documents'][0].update(sha256='0'*64))
    with pytest.raises(Problem, match='') as failure:
        asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    assert failure.value.status == 409


def test_stable_paragraph_hashes_paging_and_actual_text_limit(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store), text='首段合成测试。\n\n'+'字'*2300+'\n\n末段测试。')
    engine, rid = active(store, case)
    first = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'], limit=3)))
    again = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'], limit=3)))
    last = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'], offset=3, limit=3)))
    assert first['total_chunks'] == 5 and first['next_offset'] == 3 and last['next_offset'] is None
    assert all(len(chunk['text']) <= 1000 for chunk in first['chunks']+last['chunks'])
    assert first['chunks'][1]['locator'] == '段落 2 / 字符 1–1000'
    assert first['chunks'][1]['chunk_id'] == again['chunks'][1]['chunk_id']
    assert first['chunks'][1]['read_id'] != again['chunks'][1]['read_id']
    assert first['chunks'][1]['chunk_sha256'] == digest({'text': '字'*1000, 'locator': '段落 2 / 字符 1–1000'})
    assert all(chunk['document_sha256'] == document['sha256'] for chunk in last['chunks'])
    with pytest.raises(ValidationError):
        S.ReadEvidenceDocument(document_id=document['id'], limit=4)


def kb(store, title, text):
    knowledge = KnowledgeStore(store.root)
    result = knowledge.add_document(KnowledgeDocumentIn(title=title, institution='SYNTHETIC fixture',
        source_url='https://example.invalid/not-fetched', author='test', locator='合成章节',
        source_type='synthetic_protocol', rights='authorized_text', rights_note='原创测试许可',
        scope='协议测试，非真实知识', text=text))
    return knowledge, result['source']


def test_pinned_knowledge_actual_read_and_unlinked_source_is_unavailable(tmp_path):
    store = Store(tmp_path)
    case = new_case(store)
    knowledge, source = kb(store, '测试本案固定资料', '合成时间登记方法，本测试仅验证版本定位。')
    _, other = kb(store, '其它案资料', '合成秘密资料，不应进入本案搜索。')
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id'],
        'document_revision': source['revision'], 'document_sha256': source['document_sha256']})
    revised = knowledge.add_document(KnowledgeDocumentIn(title=source['title'], institution=source['institution'],
        source_url=source['source_url'], author=source['author'], locator='合成章节', source_type='synthetic_protocol',
        document_id=source['document_id'], expected_revision=1, rights='authorized_text', rights_note='原创测试许可',
        scope='协议测试，非真实知识', text='第二版新正文，不应替换旧案关联。'))['source']
    engine, rid = active(store, case)
    engine.model = AckOnlySyntheticModel()
    search = asyncio.run(engine.tool(rid, 'search_knowledge', S.SearchKnowledge(query='合成')))
    assert {hit['document_id'] for hit in search['results']} == {source['document_id']}
    result = asyncio.run(engine.tool(rid, 'read_knowledge', S.ReadKnowledge(document_id=source['document_id'],
        chunk_id=search['results'][0]['chunk_id'])))
    assert result['source']['revision'] == 1 and revised['revision'] == 2
    assert '时间登记方法' in result['chunks'][0]['text']
    assert result['chunks'][0]['kind'] == 'knowledge'
    asyncio.run(expose(engine, rid, result))
    Engine.validate_documentary_assessment(store.read('run', rid), findings(result['chunks'][0]))
    unrelated = knowledge.source(other['document_id'])['chunks'][0]
    with pytest.raises(ValueError, match='本案已绑定'):
        asyncio.run(engine.tool(rid, 'read_knowledge', S.ReadKnowledge(document_id=other['document_id'], chunk_id=unrelated['chunk_id'])))
    bad = findings(result['chunks'][0]).model_dump()
    bad['documentary_findings'][0]['evidence_refs'][0]['document_revision'] = 2
    with pytest.raises(ValueError, match='固定关联版本'):
        Engine.validate_documentary_assessment(store.read('run', rid), S.DocumentaryAssessment.model_validate(bad))


def test_search_results_are_not_text_read_receipts(tmp_path):
    store = Store(tmp_path)
    case = new_case(store)
    _, source = kb(store, '合成测试来源', '合成正文。')
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id'],
        'document_revision': 1, 'document_sha256': source['document_sha256']})
    engine, rid = active(store, case)
    result = asyncio.run(engine.tool(rid, 'search_knowledge', S.SearchKnowledge(query='合成')))['results'][0]
    fake = result | {'kind': 'knowledge', 'read_id': 'not-read'}
    with pytest.raises(ValueError, match='实际阅读'):
        Engine.validate_documentary_assessment(store.read('run', rid), findings(fake))


def test_doc_context_registration_is_bounded_and_records_are_paged(tmp_path):
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store))
    # Stress only local run data; these are synthetic capacity fixtures, not API evidence.
    with store.tx() as db:
        case = store.get(db, 'case', case['id'])
        case['catalogue']['provenance'] = '测试长登记'*600
        case['annotations'] = [{'id': uid('annotation'), 'observation': '私有长注释'*500} for _ in range(100)]
        case['provenance_events'] = [{'id': uid('event'), 'description': '长事件'*2000} for _ in range(100)]
        case['condition_checks'] = [{'id': uid('check'), 'observation': '长状况'*2000} for _ in range(100)]
        store.put(db, 'case', case)
    engine, rid = active(store, case)
    read = asyncio.run(engine.tool(rid, 'read_case', S.Empty()))
    assert len(json.dumps(read, ensure_ascii=False)) < 14000
    assert read['case']['record_collections']['annotations']['total'] == 100
    assert 'annotations' not in read['case']
    assert 'catalogue.provenance' in read['case']['truncated_fields']
    page = asyncio.run(engine.tool(rid, 'read_case_records', S.ReadCaseRecords(collection='provenance_events', offset=90, limit=8)))
    assert len(page['records']) == 8 and page['next_offset'] == 98 and page['total'] == 100
    assert all(len(record['text']) == 1000 and record['truncated'] for record in page['records'])
    continuation = asyncio.run(engine.tool(rid, 'read_case_records', S.ReadCaseRecords(collection='provenance_events', offset=90, limit=1, text_offset=1000)))
    assert continuation['records'][0]['record_sha256'] == page['records'][0]['record_sha256']
    assert continuation['records'][0]['text_start'] == 1000
    messages = [{'role': 'system', 'content': system_prompt('skills', 'documentary_audit')}, {'role': 'user', 'content': 'begin'}]
    messages.extend({'role': 'user', 'content': 'X'*8000} for _ in range(10))
    bounded = bounded_messages(messages)
    assert sum(len(message['content']) for message in bounded) <= 32000
    assert '省去' in bounded[2]['content']


def test_private_txt_is_never_in_stepfun_preview_or_send(tmp_path):
    store = Store(tmp_path)
    private = 'SYNTHETIC-PRIVATE-TXT-NEVER-EXTERNAL'
    case, _ = attach(store, new_case(store), text=private)
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    current = store.read('case', case['id'])
    with pytest.raises(Problem) as preview:
        suggested_packet(store, case['id'])
    assert preview.value.status == 409 and private not in preview.value.message
    with pytest.raises(Problem) as prepare:
        prepare_review(store, case['id'], mutation(current) | {'assessment_run_id': rid})
    assert prepare.value.status == 409 and not store.listing('text_review')
    # Even a legacy/tampered prepared packet cannot reach the client.
    packet = {'id': uid('textreview'), 'case_id': case['id'], 'case_revision': current['revision'],
              'assessment_run_id': rid, 'episode_id': current['episode_id'], 'state': 'prepared',
              'payload': {'private': private}, 'packet_hash': digest({'private': private})}
    with store.tx() as db:
        store.put(db, 'text_review', packet)
    class NoSend:
        configured = True
        async def review(self, *args):
            pytest.fail('Private TXT must not be sent')
    with pytest.raises(Problem) as sent:
        asyncio.run(ReviewService(store, NoSend()).execute(packet['id'], {'packet_hash': packet['packet_hash'], 'request_id': uid('req')}))
    assert sent.value.status == 409
    assert store.read('episode', current['episode_id'])['model_calls'] == 3


def test_documentary_task_forbids_visual_tools_and_attribution_fields(tmp_path):
    assert 'record_assessment' not in tools_for_mode('skills', 'documentary_audit')
    assert 'inspect_images' not in tools_for_mode('plain', 'documentary_audit')
    assert 'record_documentary_findings' not in tools_for_mode('skills', 'visual_research')
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store))
    engine, rid = active(store, case)
    with pytest.raises(ValueError, match='模式不可'):
        asyncio.run(engine.tool(rid, 'inspect_images', S.Inspect(media_ids=['fake'], question='fake')))
    read = {'kind': 'attachment', 'document_id': 'test', 'document_sha256': '0'*64,
            'chunk_id': 'test', 'chunk_sha256': '0'*64, 'locator': 'test', 'read_id': 'test'}
    value = findings(read).model_dump()
    value['claims'] = []
    with pytest.raises(ValidationError):
        S.DocumentaryAssessment.model_validate(value)
    value.pop('claims')
    value['summary'] = '年代确定为明代，窑口归属为景德镇。'
    with pytest.raises(ValidationError, match='不得作年代'):
        S.DocumentaryAssessment.model_validate(value)


def test_research_task_switch_is_cas_and_forbidden_after_any_run(tmp_path):
    store = Store(tmp_path)
    case = new_case(store, 'visual_research')
    body = mutation(case) | {'research_task': 'documentary_audit'}
    changed = store.update_research_task(case['id'], body)
    assert changed['revision'] == case['revision']+1
    assert store.update_research_task(case['id'], body) == changed
    with pytest.raises(Problem) as stale:
        store.update_research_task(case['id'], mutation(case) | {'research_task': 'visual_research'})
    assert stale.value.status == 409
    changed, _ = attach(store, changed)
    engine, rid = start(store, changed)
    store.finish(rid, 'failed', 'SYNTHETIC interrupted test run')
    with pytest.raises(Problem) as mixed:
        store.update_research_task(changed['id'], mutation(changed) | {'research_task': 'visual_research'})
    assert mixed.value.status == 409 and '另建案卷' in mixed.value.message


def test_empty_documentary_case_needs_material_and_visual_case_still_needs_photo(tmp_path):
    store = Store(tmp_path)
    documentary = new_case(store)
    with pytest.raises(Problem) as missing:
        start(store, documentary)
    assert missing.value.status == 422 and '附件' in missing.value.message
    visual, _ = attach(store, new_case(store, 'visual_research'))
    with pytest.raises(Problem) as no_photo:
        start(store, visual)
    assert no_photo.value.status == 422 and '照片' in no_photo.value.message
    assert S.NewCase(request_id=uid('req'), title='default', question='default').research_task == 'visual_research'


def test_prior_read_receipt_cannot_be_reused_in_revision(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    previous = store.read('run', rid)
    updated, _ = attach(store, store.read('case', case['id']), text='合成第二轮补证文本')
    engine2, rid2 = active(store, updated, mode='skills')
    asyncio.run(engine2.tool(rid2, 'load_skill', S.LoadSkill(name='documentary-evidence-audit')))
    old_read = previous['read_evidence_documents'][0]
    run = store.read('run', rid2)
    with pytest.raises(ValueError, match='上一版依赖'):
        Engine.validate_documentary_assessment(run, findings(old_read))
    dependency = asyncio.run(engine2.tool(rid2, 'review_dependencies', S.Empty()))
    assert dependency['strategy'] == 'full-documentary-reread-no-cache'
    with pytest.raises(ValueError, match='实际阅读'):
        Engine.validate_documentary_assessment(store.read('run', rid2), findings(old_read))


def test_documentary_report_escapes_untrusted_text(tmp_path):
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store), text='<script>alert("synthetic")</script> 合成测试正文')
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assert run['state'] == 'ready'
    bundle = export_bundle(store, store.read('case', case['id']), run)
    rendered = html_report(bundle, lambda _: pytest.fail('No images'))
    assert '<script>alert' not in rendered and '&lt;script&gt;alert' in rendered


def test_failed_model_does_not_register_read_receipt_as_delivered(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    class FailedSyntheticModel(AckOnlySyntheticModel):
        async def complete(self, *args):
            raise TimeoutError('SYNTHETIC fixture failure; no real model')
    engine.model = FailedSyntheticModel()
    with pytest.raises(TimeoutError):
        asyncio.run(expose(engine, rid, result))
    run = store.read('run', rid)
    assert not run.get('main_seen_text_read_ids')
    last = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert last['outcome'] == 'failed' and last['successful_text_read_ids'] == []
    with pytest.raises(ValueError, match='成功的新动作轮'):
        Engine.validate_documentary_assessment(run, findings(result['chunks'][0]))


def test_compacted_unreceived_text_is_not_counted_as_read_by_main_agent(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    engine.model = AckOnlySyntheticModel()
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    messages = [{'role': 'system', 'content': system_prompt('plain', 'documentary_audit')},
                {'role': 'user', 'content': 'SYNTHETIC begin'},
                {'role': 'user', 'content': json.dumps(result, ensure_ascii=False)}]
    messages.extend({'role': 'user', 'content': 'Later synthetic record '*600} for _ in range(3))
    bounded = bounded_messages(messages)
    assert result['chunks'][0]['read_id'] not in json.dumps(bounded)
    asyncio.run(engine.call(rid, bounded, 'action'))
    assert not store.read('run', rid).get('main_seen_text_read_ids')


def test_aborted_documentary_draft_does_not_remain_as_completed_assessment(tmp_path):
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    engine, rid = active(store, case)
    engine.model = AckOnlySyntheticModel()
    result = asyncio.run(engine.tool(rid, 'read_evidence_document', S.ReadEvidenceDocument(document_id=document['id'])))
    asyncio.run(expose(engine, rid, result))
    draft = findings(result['chunks'][0])
    asyncio.run(engine.tool(rid, 'record_documentary_findings', draft))
    store.finish(rid, 'failed', 'SYNTHETIC later action failure')
    run = store.read('run', rid)
    assert run['assessment'] is None and run['discarded_assessment_sha256'] == digest(draft.model_dump())
    assert store.read('case', case['id'])['current_run_id'] is None


@pytest.mark.parametrize('summary', ['真伪概率90%', '95%真品', 'AI生成置信概率0.9'])
def test_documentary_authenticity_probability_is_also_forbidden(summary):
    read = {'kind': 'attachment', 'document_id': 'test', 'document_sha256': '0'*64,
            'chunk_id': 'test', 'chunk_sha256': '0'*64, 'locator': 'test', 'read_id': 'test'}
    value = findings(read).model_dump() | {'summary': summary}
    with pytest.raises(ValidationError, match='数值概率'):
        S.DocumentaryAssessment.model_validate(value)


def test_knowledge_excerpt_hash_commits_only_returned_text(tmp_path):
    store = Store(tmp_path)
    case = new_case(store)
    _, source = kb(store, '合成长段文字', '前'*800+'末尾尚未读取'*100)
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id'],
        'document_revision': 1, 'document_sha256': source['document_sha256']})
    engine, rid = active(store, case)
    search = asyncio.run(engine.tool(rid, 'search_knowledge', S.SearchKnowledge(query='前')))['results'][0]
    result = asyncio.run(engine.tool(rid, 'read_knowledge', S.ReadKnowledge(document_id=source['document_id'], chunk_id=search['chunk_id'])))
    chunk = result['chunks'][0]
    assert len(chunk['text']) == 800 and chunk['truncated'] is True and chunk['snippet_end'] == 800
    assert chunk['read_text_sha256'] == hashlib.sha256(chunk['text'].encode()).hexdigest()
    assert '末尾尚未读取' not in chunk['text']
    receipt = store.read('run', rid)['read_knowledge'][0]
    assert receipt['read_text_sha256'] == chunk['read_text_sha256']


def test_archived_photos_do_not_enter_documentary_model_or_report(tmp_path):
    from test_closed_loop import add_photo
    store = Store(tmp_path)
    case, document = attach(store, new_case(store))
    case = add_photo(store, case)
    model = SyntheticDocumentaryModel()
    engine, rid = start(store, case, model)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assert run['state'] == 'ready'
    assert run['snapshot']['media'] == [] and run['snapshot']['analysis_scope']['archive_media_count'] == 1
    assert run['snapshot']['analysis_scope']['omitted_media_ids'] == [case['media'][0]['id']]
    case_result = next(event['result'] for event in run['events'] if event['type']=='tool_result' and event['tool']=='read_case')
    assert case_result['preflight']['image_observation'] == 'not_performed'
    assert 'images' not in case_result['preflight']
    assert all(not isinstance(message['content'], list) for messages in model.calls for message in messages)
    bundle = export_bundle(store, store.read('case', case['id']), run)
    assert '<img ' not in html_report(bundle, lambda _: pytest.fail('Archive photos must not be read for documentary HTML'))


def test_documentary_can_describe_a_source_statement_without_adopting_attribution():
    read = {'kind': 'attachment', 'document_id': 'test', 'document_sha256': '0'*64,
            'chunk_id': 'test', 'chunk_sha256': '0'*64, 'locator': 'test', 'read_id': 'test'}
    value = findings(read).model_dump()
    value['summary'] = '来源材料写道“年代是明代”，本核查仅记录其陈述，未作归属判定。'
    assert S.DocumentaryAssessment.model_validate(value).statement_truth_verified is False


@pytest.fixture
def documentary_api(tmp_path, monkeypatch):
    app = create_app(tmp_path, model=SyntheticDocumentaryModel())
    scheduled = []
    monkeypatch.setattr(app.state.engine, 'schedule', scheduled.append)
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token':client.get('/api/status').json()['session_token']}
        yield app, client, headers, scheduled


def api_documentary_case(client, headers, task='documentary_audit'):
    result = client.post('/api/cases', headers=headers, json={
        'request_id':uid('req'), 'title':'SYNTHETIC API documentary case',
        'question':'API协议夹具，不是真实文书核查', 'research_task':task})
    assert result.status_code == 200, result.text
    return result.json()


def api_attachment(client, headers, case):
    result = client.post('/api/cases/'+case['id']+'/evidence-documents', headers=headers,
        json=mutation(case) | {'file_base64':base64.b64encode('仅本地合成私有文字'.encode()).decode(),
                              'filename':'fixture.txt', 'source':'合成测试', 'rights_note':'测试原创本地许可',
                              'permission':'local_use_authorized'})
    assert result.status_code == 201, result.text
    return result.json()['case']


def test_real_api_documentary_run_202_zero_photos_and_stepfun_409(documentary_api):
    app, client, headers, scheduled = documentary_api
    case = api_attachment(client, headers, api_documentary_case(client, headers))
    preflight = client.get('/api/cases/'+case['id']+'/preflight').json()
    assert preflight['research_task'] == 'documentary_audit'
    assert preflight['images'] == [] and preflight['evidence_request'] is None
    response = client.post('/api/cases/'+case['id']+'/runs', headers=headers, json=mutation(case) | {'mode':'skills'})
    assert response.status_code == 202, response.text
    rid = response.json()['run_id']
    assert scheduled == [rid]
    run = client.get('/api/runs/'+rid).json()
    assert run['research_task'] == run['versions']['research_task'] == 'documentary_audit'
    assert run['snapshot']['media'] == []
    asyncio.run(app.state.engine.execute(rid))
    finished = client.get('/api/runs/'+rid).json()
    assert finished['state'] == 'ready'
    ready = client.get('/api/cases/'+case['id']+'/preflight').json()
    assert ready['next_step'] == 'complete' and ready['evidence_request'] is None
    assert client.get('/api/cases/'+case['id']+'/text-review-preview').status_code == 409
    current = app.state.store.read('case', case['id'])
    packet = mutation(current) | {'assessment_run_id':rid, 'permission':'approved_redacted',
        'approval_basis':'合成软件测试，无外传授权', 'question':'测试不能发',
        'claims':[{'dimension':'style','candidate':'禁止转成视觉判断','status':'insufficient',
                   'support':[],'conflict':[],'reasoning_summary':'合成夹具，仅验证拒绝'}],
        'observations':[], 'references':[]}
    prepared = client.post('/api/cases/'+case['id']+'/text-reviews', headers=headers, json=packet)
    assert prepared.status_code == 409, prepared.text
    assert app.state.store.listing('text_review') == []


def test_real_api_task_cas_and_no_switch_after_run(documentary_api):
    app, client, headers, scheduled = documentary_api
    case = api_documentary_case(client, headers, task='visual_research')
    route = '/api/cases/'+case['id']+'/research-task'
    assert client.patch(route, json=mutation(case) | {'research_task':'documentary_audit'}).status_code == 403
    body = mutation(case) | {'research_task':'documentary_audit'}
    changed = client.patch(route, headers=headers, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == case['revision']+1
    assert client.patch(route, headers=headers, json=body).json() == changed.json()
    assert client.patch(route, headers=headers, json=mutation(case) | {'research_task':'visual_research'}).status_code == 409
    material = api_attachment(client, headers, changed.json())
    result = client.post('/api/cases/'+case['id']+'/runs', headers=headers, json=mutation(material) | {'mode':'skills'})
    assert result.status_code == 202
    app.state.store.finish(result.json()['run_id'], 'failed', 'SYNTHETIC stopped run')
    no_switch = client.patch(route, headers=headers, json=mutation(material) | {'research_task':'visual_research'})
    assert no_switch.status_code == 409 and '另建案卷' in no_switch.text


def test_real_api_unconfigured_documentary_model_has_no_fake_run(documentary_api):
    app, client, headers, scheduled = documentary_api
    case = api_attachment(client, headers, api_documentary_case(client, headers))
    class UnconfiguredSyntheticModel(SyntheticDocumentaryModel):
        configured = False
    app.state.engine.model = UnconfiguredSyntheticModel()
    result = client.post('/api/cases/'+case['id']+'/runs', headers=headers, json=mutation(case) | {'mode':'skills'})
    assert result.status_code == 503 and '文字' in result.text
    assert '仅本地合成私有文字' not in result.text
    assert not scheduled and app.state.store.listing('run') == []
    assert app.state.store.read('case', case['id'])['current_run_id'] is None


@pytest.mark.parametrize('summary', ['结论：年代确定为明代，窑口归属为景德镇。',
    '本件是明代景德镇官窑真品。', '已核验产权合法且文书是真实的。'])
def test_plain_attribution_or_certification_prefix_is_not_a_guard_bypass(summary):
    read = {'kind':'attachment','document_id':'test','document_sha256':'0'*64,'chunk_id':'test',
            'chunk_sha256':'0'*64,'locator':'test','read_id':'test'}
    value = findings(read).model_dump() | {'summary':summary}
    with pytest.raises(ValidationError, match='不得作年代'):
        S.DocumentaryAssessment.model_validate(value)


def test_documentary_human_review_and_correction_use_document_method(documentary_api):
    app, client, headers, scheduled = documentary_api
    case = api_attachment(client, headers, api_documentary_case(client, headers))
    run = client.post('/api/cases/'+case['id']+'/runs', headers=headers,
        json=mutation(case) | {'mode':'skills'})
    assert run.status_code == 202
    rid = run.json()['run_id']
    asyncio.run(app.state.engine.execute(rid))
    current = app.state.store.read('case', case['id'])
    review = mutation(current) | {'assessment_run_id':rid, 'expected_review_revision':current['review_revision'],
        'status':'reviewed','review_method':'image','note':'合成资料核对测试','basis':'仅软件协议夹具'}
    route = '/api/cases/'+case['id']
    assert client.post(route+'/reviews', headers=headers, json=review).status_code == 422
    review['review_method'] = 'document'
    saved = client.post(route+'/reviews', headers=headers, json=review)
    assert saved.status_code == 200, saved.text
    assert saved.json()['review']['review_method'] == 'document' and saved.json()['review']['identity_verified'] is False
    body = mutation(saved.json()) | {'assessment_run_id':rid,'review_method':'image',
        'correction':'合成资料订正，没有真实结论','basis':'仅协议验证'}
    assert client.post(route+'/corrections', headers=headers, json=body).status_code == 422
    body['review_method'] = 'document'
    corrected = client.post(route+'/corrections', headers=headers, json=body)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()['corrections'][-1]['review_method'] == 'document'
    bundle = export_bundle(app.state.store, corrected.json(), app.state.store.read('run', rid))
    assert '资料核对方式：document' in markdown_report(bundle)
    assert '订正方式：document' in html_report(bundle, lambda _: pytest.fail('No images'))


def test_large_valid_source_metadata_is_bounded_without_altering_snapshot_or_read_hash(tmp_path):
    store = Store(tmp_path)
    case = new_case(store)
    knowledge = KnowledgeStore(store.root)
    source = knowledge.add_document({'title':'题'*300,'institution':'机'*300,
        'source_url':'https://example.invalid/'+('x'*(2000-len('https://example.invalid/'))),
        'locator':'定'*1000, 'author':'著'*300, 'year':'2'*100, 'source_type':'X'*100,
        'rights':'authorized_text','rights_note':'权'*1500,'scope':'范'*1500,
        'limitations':['合成限制'*375 for _ in range(10)],'text':'实际合成短正文'+('字'*800)})['source']
    case = store.link_document(case['id'], mutation(case) | {'document_id':source['document_id'],
        'document_revision':1, 'document_sha256':source['document_sha256']})
    engine, rid = active(store, case)
    chunk = knowledge.source(source['document_id'])['chunks'][0]
    result = asyncio.run(engine.tool(rid,'read_knowledge',S.ReadKnowledge(document_id=source['document_id'],chunk_id=chunk['chunk_id'])))
    assert 'limitations' in result['source_metadata_truncated_fields']
    assert len(result['source']['limitations']) == 3 and all(len(item)==300 for item in result['source']['limitations'])
    assert result['source']['document_sha256'] == source['document_sha256']
    assert result['chunks'][0]['chunk_sha256'] == chunk['chunk_sha256']
    assert '实际合成短正文' in result['chunks'][0]['text']
    assert len(json.dumps(result,ensure_ascii=False)) < 10000
    frozen = store.read('run',rid)['knowledge_snapshot']
    original = next(item['source'] for item in frozen['sources'] if item['source']['document_id']==source['document_id'])
    assert len(original['limitations']) == 10 and len(original['limitations'][0]) == 1500
    assert result['source_metadata_sha256'] == digest(original)
