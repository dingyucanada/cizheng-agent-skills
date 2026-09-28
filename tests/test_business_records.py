"""Synthetic business protocol tests; no authentication of objects or records."""
import base64
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cizheng.agent import LocalModel
from cizheng.api import create_app
from cizheng.business_records import (BusinessRecords, ConditionCheckIn, EvidenceDocumentIn,
    PreparationReviewIn, ProvenanceEventIn, create_business_router, preparation_review_state)
from cizheng.knowledge import KnowledgeStore
from cizheng.review_client import StepFunClient
from cizheng.store import Problem, Store, uid


def new_case(store):
    return store.create_case({'request_id': uid('req'), 'title': '合成业务协议测试案',
                             'question': '仅验证本地登记与版本', 'source_declaration': '协议测试'})


def mutation(case):
    return {'request_id': uid('req'), 'expected_case_revision': case['revision']}


def attachment(case, raw=b'Protocol text, not evidence of an object.', **changes):
    body = mutation(case) | {'file_base64': base64.b64encode(raw).decode(), 'filename': 'protocol.txt',
        'source': '本测试原创文本', 'rights_note': '仅本地软件协议测试', 'permission': 'local_use_authorized'}
    body.update(changes)
    return body


def event(case, **changes):
    body = mutation(case) | {'date_text': '日期不明（测试）', 'event_type': 'statement',
        'party': '测试声明人', 'place': '测试地点', 'description': '未核实的来源声明，仅为协议测试。',
        'object_link_basis': '本测试不确认器物同一性。', 'evidence': [], 'status': 'declared'}
    body.update(changes)
    return body


def check(case, **changes):
    body = mutation(case) | {'date_text': '2026-09-28（测试）', 'method': 'document',
        'observer': '本地测试操作人', 'area': '测试部位', 'observation': '本记录是人工协议测试。',
        'limitations': ['未作实物检查或模型推断。'], 'media_ids': [], 'record_origin': 'operator'}
    body.update(changes)
    return body


def review(case, **changes):
    body = mutation(case) | {'expected_preparation_review_revision': case.get('preparation_review_revision', 0),
        'state': 'reviewed', 'note': '检查准备资料的测试记录', 'basis': '仅审查字段与附件定位',
        'reviewer': '本地协议测试操作人'}
    body.update(changes)
    return body


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path)
    return store, KnowledgeStore(tmp_path), BusinessRecords(store, KnowledgeStore(tmp_path))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import socket
    import urllib.request
    async def forbidden_async(*args, **kwargs):
        pytest.fail('Business records must not call model or remote HTTP')
    def forbidden_sync(*args, **kwargs):
        pytest.fail('Business records must not open network connections')
    monkeypatch.delenv('CIZHENG_MODEL_URL', raising=False)
    monkeypatch.delenv('CIZHENG_MODEL', raising=False)
    monkeypatch.setattr(LocalModel, 'complete', forbidden_async)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_async)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_async)
    monkeypatch.setattr(socket, 'create_connection', forbidden_sync)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden_sync)
    app = create_app(tmp_path)
    if not any(getattr(route, 'path', '') == '/api/cases/{identifier}/evidence-documents' for route in app.routes):
        app.include_router(create_business_router(app.state.store, app.state.knowledge))
    with TestClient(app) as api:
        headers = {'X-Cizheng-Token': api.get('/api/status').json()['session_token']}
        yield app, api, headers


def test_attachments_preserve_bytes_deduplicate_and_restart(service, tmp_path):
    store, knowledge, records = service
    case = new_case(store)
    raw = '原创测试中文TXT，不代表文物资料。\n'.encode('utf-8')
    body = attachment(case, raw)
    original = records.add_document(case['id'], body)
    document = original['document']
    assert original['case']['revision'] == case['revision'] + 1
    assert document['sha256'] == hashlib.sha256(raw).hexdigest()
    assert document['mime'] == 'text/plain' and document['size'] == len(raw)
    assert store.blob(document['artifact_id']) == ('text/plain', raw)
    assert document['verification_status'] == 'not_verified'
    assert document['content_read'] is document['ocr_performed'] is document['execution_performed'] is False
    assert records.add_document(case['id'], body) == original
    duplicate = records.add_document(case['id'], attachment(original['case'], raw, filename='another.txt'))
    assert duplicate['deduplicated'] is True
    assert duplicate['document'] == document
    assert duplicate['case']['revision'] == original['case']['revision']
    assert len(duplicate['case']['evidence_documents']) == 1
    restarted = Store(tmp_path)
    assert restarted.read('case', case['id'])['evidence_documents'][0] == document
    assert restarted.blob(document['artifact_id'])[1] == raw
    with pytest.raises(Problem, match='request_id'):
        records.add_document(case['id'], body | {'source': '改写旧附件信息'})


@pytest.mark.parametrize('changes,raw', [
    ({'filename': '../secret.txt'}, b'text'), ({'filename': '/private/secret.txt'}, b'text'),
    ({'filename': 'folder\\secret.txt'}, b'text'), ({'filename': 'bad\x00.txt'}, b'text'),
    ({'filename': 'script.py'}, b'text'), ({'permission': 'unknown'}, b'text'),
    ({'rights_note': ' '}, b'text'), ({'source': ' '}, b'text'),
    ({}, b'\xff\xff'), ({}, b'hello\x00binary'), ({'filename': 'fake.pdf'}, b'plain text'),
    ({'filename': 'incomplete.pdf'}, b'%PDF-1.4\nno-end-marker'), ({}, b''),
])
def test_bad_attachment_cannot_create_blob_or_case_revision(service, changes, raw):
    store, knowledge, records = service
    case = new_case(store)
    with pytest.raises((Problem, ValidationError)):
        records.add_document(case['id'], attachment(case, raw, **changes))
    assert store.read('case', case['id'])['revision'] == 1
    with store.tx() as db:
        assert db.execute('SELECT count(*) FROM blobs').fetchone()[0] == 0


def test_attachment_size_limits(service):
    store, knowledge, records = service
    case = new_case(store)
    for raw, name in [(b'x' * (2 * 1024 * 1024 + 1), 'too-large.txt'),
                      (b'%PDF-1.4\n' + b'x' * (10 * 1024 * 1024) + b'\n%%EOF', 'too-large.pdf')]:
        with pytest.raises((Problem, ValidationError)):
            records.add_document(case['id'], attachment(case, raw, filename=name))
    assert store.read('case', case['id'])['revision'] == 1


def test_pdf_download_is_attachment_and_never_read_or_executed(client):
    app, api, headers = client
    case = new_case(app.state.store)
    raw = b'%PDF-1.4\n1 0 obj << /Type /Catalog /OpenAction /JavaScript >> endobj\n%%EOF\n'
    response = api.post('/api/cases/' + case['id'] + '/evidence-documents', headers=headers,
                        json=attachment(case, raw, filename='protocol.pdf'))
    assert response.status_code == 201, response.text
    document = response.json()['document']
    assert document['mime'] == 'application/pdf' and document['content_read'] is False
    download = api.get(document['download_url'])
    assert download.content == raw
    assert download.headers['content-type'].startswith('application/pdf')
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['x-content-type-options'] == 'nosniff'
    assert app.state.store.read('case', case['id'])['revision'] == 2


def test_provenance_attachment_location_status_and_supersedes(service):
    store, knowledge, records = service
    case = new_case(store)
    saved = records.add_document(case['id'], attachment(case))
    case, document = saved['case'], saved['document']
    located = {'kind': 'attachment', 'document_id': document['id'], 'locator': 'TXT第1行', 'sha256': document['sha256']}
    original = records.add_provenance_event(case['id'], event(case, status='documented', evidence=[located]))
    record = original['event']
    assert original['case']['revision'] == 3
    assert record['evidence'][0]['artifact_id'] == document['artifact_id']
    assert record['event_truth_verified'] is record['object_identity_verified'] is False
    assert record['verification_status'] == 'not_verified'
    replacement = records.add_provenance_event(case['id'], event(original['case'], status='disputed',
        description='追加争议说明，不覆盖旧事件。', supersedes=record['id'], evidence=[located]))
    assert replacement['case']['provenance_events'][0] == record
    assert replacement['event']['supersedes'] == record['id']
    assert len(replacement['case']['provenance_events']) == 2
    with pytest.raises(ValidationError, match='至少需要'):
        records.add_provenance_event(case['id'], event(replacement['case'], status='documented'))
    with pytest.raises(Problem, match='本案已保存'):
        records.add_provenance_event(case['id'], event(replacement['case'], supersedes=uid('provenance')))
    with pytest.raises(Problem, match='哈希'):
        records.add_provenance_event(case['id'], event(replacement['case'], evidence=[located | {'sha256': '0' * 64}]))


def add_knowledge(knowledge):
    return knowledge.add_document({'title': '原创知识协议测试', 'institution': '测试机构',
        'source_url': 'https://example.invalid/no-fetch', 'rights': 'authorized_text',
        'rights_note': '本测试原创内容', 'scope': '协议测试', 'text': '原始知识协议段落。'})['source']


def test_knowledge_exact_revision_chunk_hash_and_case_membership(service):
    store, knowledge, records = service
    case = new_case(store)
    source = add_knowledge(knowledge)
    chunk = knowledge.source(source['document_id'])['chunks'][0]
    citation = {'kind': 'knowledge', 'document_id': source['document_id'], 'revision': source['revision'],
                'chunk_id': chunk['chunk_id'], 'document_sha256': source['document_sha256'],
                'chunk_sha256': chunk['chunk_sha256']}
    with pytest.raises(Problem, match='已关联本案'):
        records.add_provenance_event(case['id'], event(case, status='documented', evidence=[citation]))
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id']})
    original = records.add_provenance_event(case['id'], event(case, status='documented', evidence=[citation]))
    located = original['event']['evidence'][0]
    assert located['locator'] == chunk['locator']
    assert located['document_sha256'] == source['document_sha256']
    # Historical knowledge references still identify the immutable original
    # paragraph after a new live library revision has been added.
    knowledge.add_document({'document_id': source['document_id'], 'expected_revision': 1,
        'title': '原创知识协议测试', 'institution': '测试机构', 'source_url': source['source_url'],
        'rights': 'authorized_text', 'rights_note': '本测试原创内容', 'scope': '协议测试', 'text': '后来修订的段落。'})
    later = records.add_provenance_event(case['id'], event(original['case'], evidence=[citation]))
    assert later['event']['evidence'][0] == located
    for changes in ({'revision': 2}, {'chunk_sha256': '0' * 64}, {'document_sha256': '0' * 64}, {'locator': '伪造定位'}):
        with pytest.raises(Problem):
            records.add_provenance_event(case['id'], event(later['case'], evidence=[citation | changes]))


def test_unlicensed_metadata_cannot_supply_documented_knowledge_paragraph(service):
    store, knowledge, records = service
    case = new_case(store)
    source = knowledge.add_document({'title': '元数据协议测试', 'rights': 'unknown', 'scope': '仅元数据'})['source']
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id']})
    reference = {'kind': 'knowledge', 'document_id': source['document_id'], 'revision': 1,
                 'chunk_id': source['document_id'] + '_r1_metadata'}
    with pytest.raises(Problem, match='已许可的真实正文段落'):
        records.add_provenance_event(case['id'], event(case, status='documented', evidence=[reference]))
    assert store.read('case', case['id'])['revision'] == case['revision']


def test_invalid_base64_and_gap_event_have_explicit_semantics(service):
    store, knowledge, records = service
    case = new_case(store)
    with pytest.raises(Problem, match='base64'):
        records.add_document(case['id'], attachment(case) | {'file_base64': 'not!base64!'})
    gap = records.add_provenance_event(case['id'], event(case, event_type='gap', status='gap'))
    assert gap['event']['evidence'] == []
    assert gap['event']['event_truth_verified'] is False
    assert gap['case']['revision'] == 2


def test_cross_case_attachments_and_corrupted_bytes_are_rejected(service):
    store, knowledge, records = service
    first, second = new_case(store), new_case(store)
    saved = records.add_document(first['id'], attachment(first))
    reference = {'kind': 'attachment', 'document_id': saved['document']['id'], 'locator': '第1行'}
    with pytest.raises(Problem, match='必须属于本案'):
        records.add_provenance_event(second['id'], event(second, status='documented', evidence=[reference]))
    with store.tx() as db:
        db.execute('UPDATE blobs SET bytes=? WHERE id=?', (b'corrupt', saved['document']['artifact_id']))
    with pytest.raises(Problem, match='原始内容与哈希不一致'):
        records.add_provenance_event(first['id'], event(saved['case'], status='documented', evidence=[reference]))
    assert store.read('case', first['id'])['revision'] == saved['case']['revision']


def test_conditions_only_accept_manual_own_media_and_keep_history(service):
    store, knowledge, records = service
    case = new_case(store)
    with store.tx() as db:
        case['media'] = [{'id': uid('media')}]
        store.put(db, 'case', case)
    own_id = case['media'][0]['id']
    original = records.add_condition_check(case['id'], check(case, method='image', media_ids=[own_id]))
    record = original['check']
    assert record['kind'] == 'operator_condition_check'
    assert record['record_origin'] == 'operator'
    assert record['image_inference_performed'] is record['identity_verified'] is False
    assert record['media_ids'] == [own_id]
    next_record = records.add_condition_check(case['id'], check(original['case'], method='in_person'))
    assert next_record['case']['condition_checks'][0] == record
    with pytest.raises(Problem, match='本案已保存'):
        records.add_condition_check(case['id'], check(next_record['case'], media_ids=[uid('media')]))
    for changes in ({'record_origin': 'ai'}, {'observer': 'AI'}, {'limitations': []},
                    {'media_ids': [own_id, own_id]}, {'image_inference_performed': True}):
        with pytest.raises(ValidationError):
            records.add_condition_check(case['id'], check(next_record['case'], **changes))


def test_preparation_review_separate_cas_version_and_expiry(service):
    store, knowledge, records = service
    case = new_case(store)
    original_ai_review = copy.deepcopy(case['review'])
    original_ai_review_revision = case['review_revision']
    body = review(case)
    result = records.add_preparation_review(case['id'], body)
    assert result['case']['revision'] == case['revision']
    assert result['case']['preparation_review_revision'] == 1
    assert result['case']['preparation_review']['state'] == 'reviewed'
    assert result['review']['identity_verified'] is False
    assert result['case']['review'] == original_ai_review
    assert result['case']['review_revision'] == original_ai_review_revision
    assert result['case']['review_required'] is True
    assert records.add_preparation_review(case['id'], body) == result
    with pytest.raises(Problem, match='准备复核记录已更新'):
        records.add_preparation_review(case['id'], review(case))
    revised = records.add_preparation_review(case['id'], review(result['case'], state='needs_revision'))
    assert revised['case']['preparation_review_revision'] == 2
    assert revised['case']['preparation_reviews'][0] == result['review']
    assert revised['case']['revision'] == case['revision']
    advanced = records.add_condition_check(case['id'], check(revised['case']))['case']
    assert advanced['preparation_review']['state'] == 'stale'
    assert advanced['preparation_review']['recorded_state'] == 'needs_revision'
    assert advanced['preparation_review']['review_required'] is True
    assert advanced['preparation_reviews'][0] == result['review']
    # The exported helper also recognizes advances originating outside this module.
    other = store.select_analysis_media(case['id'], mutation(advanced) | {'media_ids': []})
    assert preparation_review_state(other)['stale'] is True
    with pytest.raises(Problem, match='案件已更新'):
        records.add_preparation_review(case['id'], review(revised['case']))


def test_actual_attachment_event_and_condition_count_limits(service):
    store, knowledge, records = service
    case = new_case(store)
    for index in range(20):
        case = records.add_document(case['id'], attachment(case, str(index).encode()))['case']
    at_capacity = case['revision']
    with pytest.raises(Problem, match='20份'):
        records.add_document(case['id'], attachment(case, b'one-over-limit'))
    dedup = records.add_document(case['id'], attachment(case, b'0'))
    assert dedup['deduplicated'] and dedup['case']['revision'] == at_capacity
    for index in range(100):
        case = records.add_provenance_event(case['id'], event(case, description=f'来源测试事件{index}'))['case']
    at_capacity = case['revision']
    with pytest.raises(Problem, match='100条来源'):
        records.add_provenance_event(case['id'], event(case))
    assert store.read('case', case['id'])['revision'] == at_capacity
    for index in range(100):
        case = records.add_condition_check(case['id'], check(case, observation=f'人工测试记录{index}'))['case']
    at_capacity = case['revision']
    with pytest.raises(Problem, match='100条人工'):
        records.add_condition_check(case['id'], check(case))
    assert store.read('case', case['id'])['revision'] == at_capacity


def test_real_api_session_and_all_record_routes(client):
    app, api, headers = client
    case = new_case(app.state.store)
    route = '/api/cases/' + case['id']
    body = attachment(case)
    assert api.post(route + '/evidence-documents', json=body).status_code == 403
    assert api.post(route + '/evidence-documents', headers=headers | {'Origin': 'https://other.invalid'}, json=body).status_code == 403
    added = api.post(route + '/evidence-documents', headers=headers, json=body)
    assert added.status_code == 201, added.text
    case = added.json()['case']
    record = added.json()['document']
    provenance = api.post(route + '/provenance-events', headers=headers, json=event(case, status='documented',
        evidence=[{'kind': 'attachment', 'document_id': record['id'], 'locator': 'TXT第1行'}]))
    assert provenance.status_code == 201, provenance.text
    case = provenance.json()['case']
    condition = api.post(route + '/condition-checks', headers=headers, json=check(case))
    assert condition.status_code == 201, condition.text
    case = condition.json()['case']
    prepared = api.post(route + '/preparation-reviews', headers=headers, json=review(case))
    assert prepared.status_code == 201, prepared.text
    assert prepared.json()['case']['revision'] == case['revision']
    assert api.get('/api/cases/' + case['id']).json()['case']['preparation_review_revision'] == 1
    bad = api.post(route + '/condition-checks', headers=headers, json=check(case, record_origin='ai'))
    assert bad.status_code == 422


@pytest.mark.parametrize('kind', ['attachment', 'event', 'check', 'review'])
def test_concurrent_mutation_cas_has_one_winner(service, kind):
    store, knowledge, records = service
    case = new_case(store)
    barrier = Barrier(2)

    def mutate(index):
        barrier.wait()
        try:
            if kind == 'attachment':
                return records.add_document(case['id'], attachment(case, f'file{index}'.encode()))
            if kind == 'event':
                return records.add_provenance_event(case['id'], event(case, description=f'event{index}'))
            if kind == 'check':
                return records.add_condition_check(case['id'], check(case, observation=f'check{index}'))
            return records.add_preparation_review(case['id'], review(case, note=f'review{index}'))
        except Problem as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mutate, index) for index in range(2)]
        results = [future.result() for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    saved = store.read('case', case['id'])
    assert saved['revision'] == (1 if kind == 'review' else 2)
    assert saved.get('preparation_review_revision', 0) == (1 if kind == 'review' else 0)


def test_schema_never_accepts_external_path_certification_or_bogus_evidence(service):
    store, knowledge, records = service
    case = new_case(store)
    for model, body in [
        (EvidenceDocumentIn, attachment(case) | {'file_path': '/private/secret'}),
        (ProvenanceEventIn, event(case) | {'authenticity_verified': True}),
        (ConditionCheckIn, check(case) | {'record_origin': 'ai'}),
        (PreparationReviewIn, review(case) | {'identity_verified': True}),
        (ProvenanceEventIn, event(case, event_type='gap', status='declared')),
        (ProvenanceEventIn, event(case, evidence=[{'kind': 'url', 'url': 'https://example.invalid'}])),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(body)
    assert store.read('case', case['id'])['revision'] == 1
