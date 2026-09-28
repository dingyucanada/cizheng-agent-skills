"""Real offline teaching import checks, never model quality or authenticity tests."""
import hashlib
import importlib.util
import io
import json
import socket
import urllib.request
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from cizheng.agent import LocalModel, ROOT
from cizheng.api import create_app
from cizheng.business_records import BusinessRecords
from cizheng.demo import import_guided_demos
from cizheng.knowledge import KnowledgeStore
from cizheng.review_client import StepFunClient
from cizheng.store import Store, uid


@pytest.fixture
def forbid_inference_and_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Guided teaching import must not contact a model or network')
    async def forbidden_async(*args, **kwargs):
        forbidden()
    monkeypatch.delenv('CIZHENG_MODEL_URL', raising=False)
    monkeypatch.delenv('CIZHENG_MODEL', raising=False)
    monkeypatch.setattr(LocalModel, 'complete', forbidden_async)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_async)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_async)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)


def test_public_corpus_is_rebuildable_with_all_reference_targets_and_true_bytes():
    script = ROOT / 'scripts/build-public-cases.py'
    spec = importlib.util.spec_from_file_location('public_case_builder', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    raw = builder.build()
    assert (ROOT / 'site/data/demo-cases.json').read_bytes() == raw
    assert (ROOT / 'examples/public-demo/guided-cases.json').read_bytes() == raw
    pack = json.loads(raw)
    assert {c['role'] for c in pack['cases']} == {'museum', 'collection', 'auction'}
    assert sum(len(c['images']) for c in pack['cases']) == 4
    assert sum(len(c['documents']) for c in pack['cases']) == 9
    for case in pack['cases']:
        assert '非盲测' in case['scope'] and case['expert_reviewed'] is False
        for image in case['images']:
            original = (ROOT / 'examples/public-demo' / image['file'].split('/')[-1]).read_bytes()
            assert original == (ROOT / 'site' / image['file']).read_bytes()
            assert hashlib.sha256(original).hexdigest() == image['sha256']
        for supplement in case['supplements']:
            assert supplement['origin'] == 'project_curated_teaching'
            assert supplement['ai_inference_performed'] is False
            if case['id'] != 'met-48607':
                assert supplement['image_ids'] == []


def test_cold_import_is_complete_located_and_does_not_make_a_run(tmp_path, forbid_inference_and_network):
    result = import_guided_demos(tmp_path)
    store = Store(tmp_path)
    assert len(store.listing('case')) == 3 and store.listing('run') == []
    assert result['model_calls'] == 0 and result['assessment'] is None
    assert result['ai_inference_performed'] is False
    for item in result['cases']:
        case = store.read('case', item['case_id'])
        assert len(case['evidence_documents']) == 3 and len(case['annotations']) == 3
        assert len(case['provenance_events']) == 2 and len(case['condition_checks']) == 1
        assert len(case['knowledge_links']) >= 3
        assert case['preparation_review']['state'] == 'request_evidence'
        assert case['preparation_review']['identity_verified'] is False
        assert case['current_run_id'] is None
        assert store.read('episode', case['episode_id'])['model_calls'] == 0
        assert '已知对象身份' in case['source_declaration']
        for document in case['evidence_documents']:
            mime, raw = store.blob(document['artifact_id'])
            assert mime == 'text/plain' and len(raw.decode('utf-8')) > 250
            assert hashlib.sha256(raw).hexdigest() == document['sha256']
            assert document['content_read'] is document['authenticity_verified'] is False
        for event in case['provenance_events']:
            assert event['event_truth_verified'] is event['object_identity_verified'] is False
            assert event['evidence'][0]['kind'] == 'attachment'
        for note in case['annotations']:
            assert '非模型输出、非专家意见' in note['observation']


def test_repeat_import_retains_operator_catalogue_notes_and_new_review(tmp_path, forbid_inference_and_network):
    first = import_guided_demos(tmp_path)
    assert import_guided_demos(tmp_path) == first
    store = Store(tmp_path)
    identifier = first['cases'][0]['case_id']
    case = store.read('case', identifier)
    case = store.update_catalogue(identifier, {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'workflow': 'collection', 'catalogue': case['catalogue'] | {'dimensions': 'Visitor edit, retained by re-import'}})
    case = store.annotate(identifier, {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'media_id': case['media'][0]['id'], 'region': [.1, .1, .2, .2], 'feature': 'other',
        'observation': 'Visitor manual note, not expert authentication'})['case']
    records = BusinessRecords(store, KnowledgeStore(tmp_path))
    case = records.add_preparation_review(identifier, {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'expected_preparation_review_revision': case['preparation_review_revision'],
        'state': 'needs_revision', 'note': 'Visitor asks for revised wording.',
        'basis': 'Manual preparation review, no model or object inspection.'})['case']
    before = store.read('case', identifier)
    repeated = import_guided_demos(tmp_path)
    assert store.read('case', identifier) == before
    assert repeated['cases'][0]['workflow'] == 'collection'
    assert repeated['cases'][0]['observation_count'] == 4
    assert import_guided_demos(tmp_path) == repeated
    assert len(store.listing('case')) == 3 and store.listing('run') == []


def test_interrupted_import_resumes_without_duplicate_or_revision_conflict(tmp_path, monkeypatch, forbid_inference_and_network):
    original = BusinessRecords.add_condition_check
    interrupted = False
    def fail_once(self, identifier, body):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError('Synthetic power loss after persisted photo/doc/notes steps')
        return original(self, identifier, body)
    monkeypatch.setattr(BusinessRecords, 'add_condition_check', fail_once)
    with pytest.raises(RuntimeError, match='power loss'):
        import_guided_demos(tmp_path)
    store = Store(tmp_path)
    partial = store.listing('case')[0]
    assert len(partial['media']) == 2 and len(partial['evidence_documents']) == 3
    assert len(partial['annotations']) == 3 and len(partial['provenance_events']) == 2
    recovered = import_guided_demos(tmp_path)
    assert len(recovered['cases']) == 3 and len(store.listing('case')) == 3
    case = store.read('case', partial['id'])
    assert len(case['annotations']) == 3 and len(case['preparation_reviews']) == 1
    assert len(case['provenance_events']) == 2 and len(case['condition_checks']) == 1
    assert import_guided_demos(tmp_path) == recovered


def test_guided_endpoint_inherits_token_and_origin_and_dossier_is_exportable(tmp_path, forbid_inference_and_network):
    app = create_app(tmp_path)
    with TestClient(app) as api:
        assert api.post('/api/demo/guided').status_code == 403
        assert app.state.store.listing('case') == []
        token = api.get('/api/status').json()['session_token']
        headers = {'X-Cizheng-Token': token}
        assert api.post('/api/demo/guided', headers=headers | {'Origin': 'https://other.example'}).status_code == 403
        response = api.post('/api/demo/guided', headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['model_calls'] == 0 and result['assessment'] is None
        assert api.post('/api/demo/guided', headers=headers).json() == result
        item = result['cases'][0]
        case = app.state.store.read('case', item['case_id'])
        report = api.post('/api/cases/' + case['id'] + '/dossier', headers=headers,
            json={'request_id': uid('req'), 'expected_case_revision': case['revision']})
        assert report.status_code == 200, report.text
        assert len(report.json()['artifacts']) == 3
        for artifact in report.json()['artifacts']:
            exported = api.get('/api/artifacts/' + artifact['id'])
            assert exported.status_code == 200
            if artifact['filename'].endswith('.json'):
                assert json.loads(exported.content)['report_kind'] == 'research_preparation'
        handoff = api.post('/api/cases/' + case['id'] + '/handoff', headers=headers,
            json={'request_id': uid('req'), 'expected_case_revision': case['revision']})
        assert handoff.status_code == 200, handoff.text
        archive = api.get(handoff.json()['artifacts'][0]['url'])
        assert hashlib.sha256(archive.content).hexdigest() == handoff.json()['archive_sha256']
        with zipfile.ZipFile(io.BytesIO(archive.content)) as files:
            manifest = json.loads(files.read('manifest.json'))
            assert manifest['model_inference_included'] is manifest['expert_reviewed'] is False
            assert len([f for f in manifest['files'] if f['kind'] == 'original-images']) == 2
            assert len([f for f in manifest['files'] if f['kind'] == 'original-documents']) == 3
            for entry in manifest['files']:
                raw = files.read(entry['path'])
                assert hashlib.sha256(raw).hexdigest() == entry['sha256']
                assert len(raw) == entry['bytes']
            assert not any('51185' in path or '50839' in path or path.endswith('.sqlite3') for path in files.namelist())
        assert app.state.store.listing('run') == []
