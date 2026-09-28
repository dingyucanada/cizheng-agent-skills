"""Integrated preparation contracts. All custom text/pixels are synthetic tests.

The model fixture identifies itself as synthetic and cannot generate a response.
Scheduling is captured so tests inspect real API-created frozen runs without
calling any model, OCR engine, crawler, or remote service.
"""
import base64
import html
import io
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cizheng.api import create_app
from cizheng.agent import LocalModel
from cizheng.knowledge import read_snapshot
from cizheng.review_client import StepFunClient
from cizheng.demo import import_professional_demos


class NoCallSyntheticModel:
    configured = True

    def identity(self):
        return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'no-call-frozen-run-protocol'}

    async def complete(self, *args, **kwargs):
        pytest.fail('No model call is permitted by these integrated preparation tests')


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    import socket
    import urllib.request
    async def forbidden_async(*args, **kwargs):
        pytest.fail('Preparation tests must not call models or external HTTP')
    def forbidden_sync(*args, **kwargs):
        pytest.fail('Preparation tests must not open network connections')
    monkeypatch.delenv('CIZHENG_MODEL_URL', raising=False)
    monkeypatch.delenv('CIZHENG_MODEL', raising=False)
    monkeypatch.setattr(LocalModel, 'complete', forbidden_async)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_async)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_async)
    monkeypatch.setattr(socket, 'create_connection', forbidden_sync)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden_sync)
    app = create_app(tmp_path, model=NoCallSyntheticModel())
    scheduled = []
    monkeypatch.setattr(app.state.engine, 'schedule', scheduled.append)
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        yield app, client, headers, scheduled


def mutation(case):
    return {'request_id': str(uuid.uuid4()), 'expected_case_revision': case['revision']}


def new_case(client, headers):
    response = client.post('/api/cases', headers=headers, json={
        'request_id': str(uuid.uuid4()), 'title': 'SYNTHETIC preparation contract case',
        'question': '仅测试版本与资料输出，不是真实文物研究', 'target_attribution': '无真实归属',
        'source_declaration': '合成测试文字与色块，不是真实文物', 'workflow': 'museum'})
    assert response.status_code == 200, response.text
    return response.json()


def source_body(**changes):
    value = {'title': '原创准备流程协议测试', 'institution': '合成测试机构', 'author': '本地协议测试作者',
        'source_url': 'https://example.invalid/not-fetched/preparation-protocol', 'locator': '协议测试章节',
        'year': '2026', 'rights': 'authorized_text', 'rights_note': '本测试原创段落，非机构认证。',
        'scope': '仅验证保存与绑定', 'limitations': ['不是陶瓷资料或真实性依据。'],
        'source_type': 'synthetic_protocol', 'text': '甲版蟠螭定位，仅为固定版本测试。'}
    value.update(changes)
    return value


def save_source(client, headers, body=None):
    response = client.post('/api/knowledge/sources', headers=headers, json=body or source_body())
    assert response.status_code == 201, response.text
    return response.json()['source']


def bind_source(client, headers, case, source):
    response = client.post('/api/cases/' + case['id'] + '/documents', headers=headers,
        json=mutation(case) | {'document_id': source['document_id'], 'document_revision': source['revision'],
                               'document_sha256': source['document_sha256']})
    assert response.status_code == 200, response.text
    return response.json()


def revise_source(client, headers, source, text='乙版黼黻定位，旧案不能自动读取。'):
    return save_source(client, headers, source_body(document_id=source['document_id'],
        expected_revision=source['revision'], text=text))


def dossier(client, headers, case):
    response = client.post('/api/cases/' + case['id'] + '/dossier', headers=headers, json=mutation(case))
    assert response.status_code == 200, response.text
    result = response.json()
    artifacts = {artifact['filename'].rsplit('.', 1)[1]: client.get(artifact['url'])
                 for artifact in result['artifacts']}
    assert set(artifacts) == {'json', 'md', 'html'}
    assert all(artifact.status_code == 200 for artifact in artifacts.values())
    bundle = artifacts['json'].json()
    assert bundle['bundle_sha256'] == result['bundle_sha256']
    return result, bundle, artifacts


def preparation_review(client, headers, case):
    response = client.post('/api/cases/' + case['id'] + '/preparation-reviews', headers=headers,
        json=mutation(case) | {'expected_preparation_review_revision': case['preparation_review_revision'],
            'state': 'reviewed', 'reviewer': '本地测试操作人', 'note': '已核对准备资料定位（协议测试）',
            'basis': '本记录不核验真伪或机构身份。'})
    assert response.status_code == 201, response.text
    return response.json()['case']


def synthetic_photo(client, headers, case, number=0):
    raw = io.BytesIO()
    Image.new('RGB', (24, 32), (number % 256, (number * 17) % 256, (number * 37) % 256)).save(raw, format='PNG')
    response = client.post('/api/cases/' + case['id'] + '/evidence', headers=headers,
        json=mutation(case) | {'filename': f'synthetic-{number}.png',
            'image_base64': base64.b64encode(raw.getvalue()).decode(), 'view': f'合成色块{number}',
            'edit_declaration': '程序生成，仅测试', 'source': 'SYNTHETIC PROTOCOL ONLY'})
    assert response.status_code == 200, response.text
    return response.json()['case']


def test_bound_source_revision_and_preparation_sha_do_not_follow_live_library(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers)
    case = bind_source(client, headers, case, first)
    binding = case['knowledge_links'][0]
    assert binding == {'document_id': first['document_id'], 'document_revision': 1,
        'document_sha256': first['document_sha256'], 'linked_case_revision': case['revision']}
    before, before_bundle, _ = dossier(client, headers, case)
    second = revise_source(client, headers, first)
    assert second['revision'] == 2
    current = client.get('/api/cases/' + case['id']).json()['case']
    assert current['revision'] == case['revision']
    assert current['knowledge_links'] == case['knowledge_links']
    after, after_bundle, _ = dossier(client, headers, current)
    assert after_bundle['documents'][0]['source']['revision'] == 1
    assert after_bundle['documents'][0]['source']['document_sha256'] == first['document_sha256']
    assert after['bundle_sha256'] == before['bundle_sha256'], 'Live index/history metadata must not change a pinned preparation bundle'
    assert after_bundle['documents'] == before_bundle['documents']
    assert not scheduled


def test_explicit_rebind_advances_case_and_stales_review(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers)
    case = bind_source(client, headers, case, first)
    case = preparation_review(client, headers, case)
    prior_history = json.loads(json.dumps(case['preparation_reviews']))
    second = revise_source(client, headers, first)
    relinked = bind_source(client, headers, case, second)
    assert relinked['revision'] == case['revision'] + 1
    assert relinked['knowledge_links'][0]['document_revision'] == 2
    assert relinked['knowledge_links'][0]['document_sha256'] == second['document_sha256']
    assert relinked['preparation_review']['stale'] is True
    assert relinked['preparation_review']['state'] == 'stale'
    assert relinked['preparation_review_revision'] == case['preparation_review_revision']
    assert relinked['preparation_reviews'] == prior_history
    assert relinked['review']['status'] == 'pending'
    result, bundle, _ = dossier(client, headers, relinked)
    assert bundle['documents'][0]['source']['revision'] == 2


def test_run_uses_pinned_r1_after_live_r2_and_reads_only_selected_images(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers)
    case = bind_source(client, headers, case, first)
    case = synthetic_photo(client, headers, case)
    second = revise_source(client, headers, first)
    response = client.post('/api/cases/' + case['id'] + '/runs', headers=headers,
                           json=mutation(case) | {'mode': 'skills'})
    assert response.status_code == 202, response.text
    run = client.get('/api/runs/' + response.json()['run_id']).json()
    assert scheduled == [run['id']]
    source = next(entry for entry in run['knowledge_snapshot']['sources']
                  if entry['source']['document_id'] == first['document_id'])
    assert source['source']['revision'] == 1
    assert source['source']['document_sha256'] == first['document_sha256']
    assert source['source']['document_sha256'] != second['document_sha256']
    assert read_snapshot(run['knowledge_snapshot'], first['document_id'])['chunks'][0]['text'].startswith('甲版蟠螭')
    assert run['versions']['knowledge_snapshot_sha256'] == run['knowledge_snapshot']['snapshot_sha256']
    assert run['snapshot']['knowledge_links'] == case['knowledge_links']
    assert run['model_calls'] == run['tool_calls'] == 0


@pytest.mark.parametrize('bad', ['hash', 'revision'])
def test_bad_explicit_binding_cannot_advance_case(workbench, bad):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    source = save_source(client, headers)
    body = mutation(case) | {'document_id': source['document_id'], 'document_revision': source['revision'],
                             'document_sha256': source['document_sha256']}
    body['document_sha256' if bad == 'hash' else 'document_revision'] = '0' * 64 if bad == 'hash' else 999
    response = client.post('/api/cases/' + case['id'] + '/documents', headers=headers, json=body)
    assert response.status_code in (404, 409), response.text
    saved = client.get('/api/cases/' + case['id']).json()['case']
    assert saved['revision'] == case['revision']
    assert saved['knowledge_links'] == []
    assert saved['knowledge_document_ids'] == []


def test_old_id_only_link_cannot_export_or_run_with_silent_latest(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    source = save_source(client, headers)
    case = synthetic_photo(client, headers, case)
    # Simulate a persisted pre-pin case. No request is allowed to infer latest
    # on its behalf; a human must explicitly bind the displayed version.
    with app.state.store.tx() as db:
        case['knowledge_document_ids'] = [source['document_id']]
        case['knowledge_links'] = []
        app.state.store.put(db, 'case', case)
    for route, extra in [('dossier', {}), ('runs', {'mode': 'skills'})]:
        response = client.post('/api/cases/' + case['id'] + '/' + route, headers=headers,
                               json=mutation(case) | extra)
        assert response.status_code == 409, response.text
        assert '绑定' in response.json()['detail']
    assert not scheduled
    assert client.get('/api/cases/' + case['id']).json()['runs'] == []


def test_preparation_artifacts_keep_fifth_paragraph_full_text_and_hashes(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    fifth = '第五段完整未截断标记：' + '长' * 1100 + '尾部应完整出现。'
    chunks = [{'text': f'前面第{index}段合成协议测试。', 'locator': f'协议第{index}段'} for index in range(1, 5)]
    chunks.append({'text': fifth, 'locator': '协议第5段（完整）'})
    source = save_source(client, headers, source_body(text='', chunks=chunks))
    case = bind_source(client, headers, case, source)
    result, bundle, artifacts = dossier(client, headers, case)
    saved = bundle['documents'][0]
    assert saved['source']['document_sha256'] == source['document_sha256']
    assert len(saved['chunks']) == 5
    final = saved['chunks'][4]
    assert final['text'] == fifth and len(final['text']) > 1000
    for extension in ('md', 'html'):
        text = artifacts[extension].text
        assert fifth in text or html.escape(fifth) in text
        assert final['chunk_id'] in text and final['chunk_sha256'] in text
        assert source['document_sha256'] in text
    assert bundle['model_inference_included'] is False
    assert bundle['expert_reviewed'] is False
    assert not scheduled


def test_manual_annotation_expires_preparation_review_after_knowledge_binding(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    source = save_source(client, headers)
    case = bind_source(client, headers, case, source)
    case = synthetic_photo(client, headers, case)
    case = preparation_review(client, headers, case)
    review_record = case['preparation_reviews'][0]
    response = client.post('/api/cases/' + case['id'] + '/annotations', headers=headers,
        json=mutation(case) | {'media_id': case['media'][0]['id'], 'region': [.1, .2, .4, .6],
                              'feature': 'glaze', 'observation': '合成人工记录，不是模型判断。'})
    assert response.status_code == 200, response.text
    revised = response.json()['case']
    assert revised['revision'] == case['revision'] + 1
    assert revised['knowledge_links'] == case['knowledge_links']
    assert revised['preparation_reviews'][0] == review_record
    assert revised['preparation_review']['state'] == 'stale'
    assert revised['preparation_review']['review_required'] is True
    assert not scheduled


def test_archive_thirty_and_run_selection_eight_are_independent(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    for index in range(30):
        case = synthetic_photo(client, headers, case, index)
    assert len(case['media']) == 30
    assert len(case['analysis_media_ids']) == 8
    twenty_first = case['media'][20]['id']
    selected = [media['id'] for media in case['media'][:7]] + [twenty_first]
    response = client.put('/api/cases/' + case['id'] + '/analysis-selection', headers=headers,
                          json=mutation(case) | {'media_ids': selected})
    assert response.status_code == 200, response.text
    case = response.json()
    too_many = client.put('/api/cases/' + case['id'] + '/analysis-selection', headers=headers,
                         json=mutation(case) | {'media_ids': [media['id'] for media in case['media'][:9]]})
    assert too_many.status_code == 422
    raw = io.BytesIO(); Image.new('RGB', (24, 32), (250, 200, 150)).save(raw, format='PNG')
    excess = client.post('/api/cases/' + case['id'] + '/evidence', headers=headers,
        json=mutation(case) | {'filename': 'synthetic-over-limit.png', 'image_base64': base64.b64encode(raw.getvalue()).decode(),
                              'view': '合成第31图', 'edit_declaration': '合成测试', 'source': 'SYNTHETIC ONLY'})
    assert excess.status_code == 413
    started = client.post('/api/cases/' + case['id'] + '/runs', headers=headers,
                          json=mutation(case) | {'mode': 'skills'})
    assert started.status_code == 202, started.text
    run = client.get('/api/runs/' + started.json()['run_id']).json()
    assert {media['id'] for media in run['snapshot']['media']} == set(selected)
    assert len(run['snapshot']['media']) == 8
    assert twenty_first in {media['id'] for media in run['snapshot']['media']}
    assert run['snapshot']['analysis_scope']['archive_media_count'] == 30
    assert len(run['snapshot']['analysis_scope']['omitted_media_ids']) == 22
    assert len(client.get('/api/cases/' + case['id']).json()['case']['media']) == 30
    assert run['model_calls'] == 0


def test_validation_errors_do_not_echo_base64_or_full_request_data(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    private = base64.b64encode(b'PRIVATE-PAYLOAD-MUST-NOT-APPEAR-IN-VALIDATION-RESPONSE').decode()
    response = client.post('/api/cases/' + case['id'] + '/evidence-documents', headers=headers,
        json=mutation(case) | {'file_base64': private, 'filename': '../private.txt',
                              'source': 'private source marker', 'rights_note': 'test only',
                              'permission': 'local_use_authorized'})
    assert response.status_code == 422
    assert private not in response.text and 'private source marker' not in response.text
    assert all(set(error) <= {'loc', 'msg', 'type'} for error in response.json()['detail'])
    assert len(response.content) < 3000
    assert not scheduled


def test_professional_teaching_import_is_idempotent_and_never_runs_models(workbench):
    app, client, headers, scheduled = workbench
    first = import_professional_demos(app.state.store.root)
    assert len(first['cases']) == 3
    assert {item['workflow'] for item in first['cases']} == {'museum', 'collection', 'auction'}
    assert '教学' in first['scope'] and '不是' in first['scope']
    assert all(item['media_count'] > 0 and item['model_calls'] == 0 and item['assessment'] is None
               for item in first['cases'])
    before = {item['case_id']: client.get('/api/cases/' + item['case_id']).json()['case']
              for item in first['cases']}
    second = import_professional_demos(app.state.store.root)
    assert second == first
    assert len(client.get('/api/cases').json()) == 3
    assert {item['object_id']: item['case_id'] for item in second['cases']} == {
           item['object_id']: item['case_id'] for item in first['cases']}
    for identifier, case in before.items():
        current = client.get('/api/cases/' + identifier).json()['case']
        assert current == case
        assert current['knowledge_links']
        assert current['current_run_id'] is None
        assert app.state.store.read('episode', current['episode_id'])['model_calls'] == 0
        assert client.get('/api/cases/' + identifier).json()['runs'] == []
    assert not scheduled


def test_professional_teaching_reimport_preserves_operator_catalogue_and_annotations(workbench):
    app, client, headers, scheduled = workbench
    imported = import_professional_demos(app.state.store.root)
    identifier = imported['cases'][0]['case_id']
    case = client.get('/api/cases/' + identifier).json()['case']
    modified_catalogue = dict(case['catalogue'], object_name='人工改名：请保留，不要覆盖教学模板',
                              condition_note='人工新增条件说明，不构成真实性认证。')
    response = client.patch('/api/cases/' + identifier + '/catalogue', headers=headers,
                           json=mutation(case) | {'workflow': case['workflow'], 'catalogue': modified_catalogue})
    assert response.status_code == 200, response.text
    case = response.json()
    response = client.post('/api/cases/' + identifier + '/annotations', headers=headers,
        json=mutation(case) | {'media_id': case['media'][0]['id'], 'region': [.1, .1, .4, .4],
                              'feature': 'other', 'observation': '仅测试保留本地人工观察，未认证。'})
    assert response.status_code == 200, response.text
    case = preparation_review(client, headers, response.json()['case'])
    before = json.loads(json.dumps(case))
    imported_again = import_professional_demos(app.state.store.root)
    assert len(imported_again['cases']) == 3
    after = client.get('/api/cases/' + identifier).json()['case']
    assert after == before
    assert after['catalogue'] == modified_catalogue
    assert after['annotations'][0]['observation'].startswith('仅测试保留本地人工观察')
    assert after['preparation_review']['state'] == 'reviewed'
    assert after['knowledge_links'] == before['knowledge_links']
    assert not scheduled


def test_business_knowledge_citation_must_match_case_pin(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers)
    case = bind_source(client, headers, case, first)
    second = revise_source(client, headers, first)
    chunk = client.get('/api/knowledge/sources/' + second['document_id'], params={'revision': 2}).json()['chunks'][0]
    citation = {'kind': 'knowledge', 'document_id': second['document_id'], 'revision': 2,
                'document_sha256': second['document_sha256'], 'chunk_id': chunk['chunk_id'],
                'chunk_sha256': chunk['chunk_sha256']}
    event_body = {'date_text': '时间未知（协议测试）', 'event_type': 'statement', 'party': '测试声明人',
                  'place': '', 'description': '仅测试知识凭据必须遵守本案固定绑定版本。',
                  'object_link_basis': '测试不确认器物同一性', 'status': 'documented', 'evidence': [citation]}
    rejected = client.post('/api/cases/' + case['id'] + '/provenance-events', headers=headers,
                           json=mutation(case) | event_body)
    assert rejected.status_code == 422, rejected.text
    assert client.get('/api/cases/' + case['id']).json()['case']['revision'] == case['revision']
    rebound = bind_source(client, headers, case, second)
    accepted = client.post('/api/cases/' + case['id'] + '/provenance-events', headers=headers,
                           json=mutation(rebound) | event_body)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()['event']['evidence'][0]['document_sha256'] == second['document_sha256']
    assert accepted.json()['event']['event_truth_verified'] is False
    assert not scheduled


def test_corrupt_persisted_pin_hash_blocks_dossier_and_run(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    source = save_source(client, headers)
    case = bind_source(client, headers, case, source)
    case = synthetic_photo(client, headers, case)
    with app.state.store.tx() as db:
        case['knowledge_links'][0]['document_sha256'] = '0' * 64
        app.state.store.put(db, 'case', case)
    for route, extra in [('dossier', {}), ('runs', {'mode': 'skills'})]:
        response = client.post('/api/cases/' + case['id'] + '/' + route, headers=headers,
                               json=mutation(case) | extra)
        assert response.status_code == 409, response.text
        assert '哈希' in response.json()['detail']
    assert not scheduled
    assert client.get('/api/cases/' + case['id']).json()['runs'] == []
