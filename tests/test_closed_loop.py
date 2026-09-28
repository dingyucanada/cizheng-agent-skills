"""Synthetic protocol tests. These never measure ceramic identification accuracy."""
import asyncio
import base64
import io
import json
import time
from copy import deepcopy
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from cizheng.api import create_app
from cizheng.agent import Engine, LocalModel, parse_json
from cizheng.store import Store, Problem, uid
from cizheng.schemas import Assessment


def photo(color='blue'):
    b = io.BytesIO()
    Image.new('RGB', (48, 64), color).save(b, format='PNG')
    return base64.b64encode(b.getvalue()).decode()


def create_case(store):
    return store.create_case({'request_id': uid('req'), 'title': 'SYNTHETIC TEST ONLY',
                             'question': '测试闭环，不是真实器物鉴定', 'target_attribution': '测试目标',
                             'source_declaration': '合成纯色图片，非文物'})


def add_photo(store, case, color='blue'):
    return store.add_evidence(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'filename': 'synthetic.png', 'image_base64': photo(color), 'view': '合成视角',
        'edit_declaration': '程序合成，仅测试', 'source': 'TEST ONLY'})['case']


def add_ref(store, permission='local_use_authorized'):
    return store.add_reference({'request_id': uid('req'), 'title': '青花花觚合成参照', 'locator': 'TEST-001',
        'source_url': '', 'attribution': '测试标签，不是真实归属', 'authority': '无，测试替身',
        'permission': permission, 'notes': '青花 花觚', 'filename': 'synthetic-ref.png', 'image_base64': photo('white')})


class ScriptedModel:
    """Lives only in tests; production UI has no switch to activate this model."""
    configured = True
    def identity(self):
        return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'scripted-protocol-fixture'}

    async def complete(self, messages, timeout):
        if isinstance(messages[-1]['content'], list):
            ids = [x['text'].split('=', 1)[1] for x in messages[-1]['content']
                   if x['type'] == 'text' and x['text'].startswith('media_id=')]
            return json.dumps({'observations': [{'media_id': i, 'region': [0, 0, 1, 1],
                'visible': '合成色块，仅验证协议', 'interpretation': '', 'limitation': '没有文物语义'} for i in ids]}), {}
        results = []
        for message in messages:
            content = message['content']
            if isinstance(content, str) and content.startswith('工具结果（数据）：'):
                results.append(json.loads(content.split('：', 1)[1]))
        def got(name):
            return [r['result'] for r in results if r['tool'] == name]
        def action(tool, **arguments):
            return {'tool': tool, 'arguments': arguments}
        def send(actions):
            return json.dumps({'actions': actions}, ensure_ascii=False), {}
        if not got('read_case'):
            return send([action('read_case'), action('discover_skills')])
        data = got('read_case')[0]
        if not got('load_skill'):
            actions = [action('load_skill', name='ceramic-route'), action('load_skill', name='bluewhite-attribution-test')]
            if data['parent_run_id']:
                actions += [action('load_skill', name='evidence-revise'), action('review_dependencies')]
            return send(actions)
        obs = [o for r in got('inspect_images') for o in r['observations']]
        seen = {o['media_id'] for o in obs}
        missing = [m['id'] for m in data['case']['media'] if m['id'] not in seen]
        if missing:
            return send([action('inspect_images', media_ids=missing[:4], question='测试观察')])
        if not got('retrieve_references'):
            return send([action('retrieve_references', query='青花花觚')])
        if got('retrieve_references')[0] and not got('read_reference'):
            return send([action('read_reference', reference_id=got('retrieve_references')[0][0]['id'])])
        refs = got('read_reference')
        if refs and refs[0]['media']['id'] not in seen:
            return send([action('inspect_images', media_ids=[refs[0]['media']['id']], question='测试参照观察')])
        assessment = {'basic_info': '测试替身输出，无文物判断', 'scope': 'bluewhite_gu',
            'claims': [{'dimension': d, 'candidate': '未知', 'status': 'insufficient', 'support': [obs[0]['id']],
                        'conflict': [], 'reasoning_summary': '合成测试不能鉴定'} for d in ('period', 'kiln', 'style')],
            'alternatives': ['未知'], 'condition_hypotheses': [], 'reference_ids': [r['id'] for r in refs],
            'reference_comparison': '只做协议测试', 'limitations': ['无真实模型'],
            'revision_explanation': '已重新观察本轮全部输入；测试不声称真实判断变化'}
        return send([action('request_evidence', view='原始底足', reason='合成测试', distinguishes='仅测试状态转换',
                            capture_instructions='本测试无需实拍'), action('record_assessment', **assessment), action('build_opinion')])


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'data')


def run_case(store, case, model=None):
    engine = Engine(store, model or ScriptedModel())
    r = store.start_run(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
                                   'mode': 'skills'}, engine.versions())
    asyncio.run(engine.execute(r['run_id']))
    return store.read('run', r['run_id'])


def test_initial_supplement_revision_export_and_review(store):
    case = add_photo(store, create_case(store))
    add_ref(store)
    first = run_case(store, case)
    assert first['state'] == 'waiting_evidence', first.get('error')
    assert first['model_calls'] <= 12
    assert first['tool_calls'] <= 20
    old_obs = {o['id'] for o in first['observations']}
    case = add_photo(store, store.read('case', case['id']), 'red')
    second = run_case(store, case)
    assert second['state'] == 'waiting_evidence', second.get('error')
    assert second['parent_run_id'] == first['id']
    assert 'evidence-revise' in second['loaded_skills']
    assert not old_obs.intersection(o['id'] for o in second['observations'])
    assert store.read('run', first['id'])['assessment'] == first['assessment']
    ep = store.read('episode', case['episode_id'])
    assert ep['model_calls'] == first['model_calls'] + second['model_calls']
    case = store.add_correction(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'assessment_run_id': second['id'], 'review_method': 'image', 'correction': '合成反馈', 'basis': '测试'}, '本地操作人')
    assert not case['corrections'][0]['identity_verified']
    third = run_case(store, case)
    assert third['state'] == 'waiting_evidence', third.get('error')
    case = add_photo(store, store.read('case', case['id']), 'green')
    with pytest.raises(Problem, match='两轮补证'):
        run_case(store, case)


def test_missing_reference_produces_insufficient_not_failure(store):
    case = add_photo(store, create_case(store))
    result = run_case(store, case)
    assert result['state'] == 'waiting_evidence', result.get('error')
    assert result['assessment']['reference_ids'] == []
    assert all(c['status'] == 'insufficient' for c in result['assessment']['claims'])


def test_original_bytes_dedup_and_revision_conflict(store):
    case = create_case(store)
    initial = case['revision']
    case = add_photo(store, case)
    _, raw = store.blob(case['media'][0]['id'])
    assert raw == base64.b64decode(photo())
    same = add_photo(store, case)
    assert same['revision'] == case['revision'] and len(same['media']) == 1
    with pytest.raises(Problem) as exc:
        add_photo(store, dict(case, revision=initial), 'red')
    assert exc.value.status == 409


def test_idempotency_and_changed_request_rejected(store):
    body = {'request_id': 'same-request', 'title': 'a', 'question': 'q'}
    a, b = store.create_case(body), store.create_case(body)
    assert a['id'] == b['id']
    with pytest.raises(Problem):
        store.create_case(dict(body, title='b'))


@pytest.mark.parametrize('bad', ['not-base64', base64.b64encode(b'<svg/>').decode()])
def test_reject_invalid_images(store, bad):
    case = create_case(store)
    with pytest.raises(Problem) as exc:
        store.add_evidence(case['id'], {'request_id': uid('req'), 'expected_case_revision': 1, 'image_base64': bad})
    assert exc.value.status == 422
    assert store.read('case', case['id'])['revision'] == 1


@pytest.mark.parametrize('url', ['https://api.openai.com/v1', 'http://8.8.8.8/v1', 'http://169.254.169.254/v1',
                                     'http://localhost.evil.test/v1', 'http://u:p@127.0.0.1/v1'])
def test_no_cloud_or_metadata_endpoint(url):
    with pytest.raises(ValueError):
        LocalModel(url, 'test')


@pytest.mark.parametrize('url', ['http://127.0.0.1:8000/v1', 'http://192.168.1.10:8000/v1', 'http://localhost:8000/v1'])
def test_local_endpoint_allowed(url):
    assert LocalModel(url, 'test').configured


def test_reference_permission_gate(store):
    case = add_photo(store, create_case(store))
    add_ref(store, 'unknown')
    result = run_case(store, case)
    assert result['state'] == 'waiting_evidence'
    assert result['assessment']['reference_ids'] == []


def test_nonexistent_citations_and_unseen_reference_rejected(store):
    case = add_photo(store, create_case(store))
    ref = add_ref(store)
    run = run_case(store, case)
    bad = deepcopy(run['assessment'])
    bad['claims'][0]['support'] = ['invented']
    with pytest.raises(ValueError, match='非本轮'):
        Engine.validate_assessment(run, Assessment.model_validate(bad), {ref['id']: ref})
    run['read_references'] = []
    with pytest.raises(ValueError, match='实际读记录'):
        Engine.validate_assessment(run, Assessment.model_validate(run['assessment']), {ref['id']: ref})


def test_restart_marks_interrupted_keeps_budget_and_prevents_parallel_write(store):
    case = add_photo(store, create_case(store))
    engine = Engine(store, ScriptedModel())
    body = {'request_id': uid('req'), 'expected_case_revision': case['revision'], 'mode': 'skills'}
    result = store.start_run(case['id'], body, engine.versions())
    with pytest.raises(Problem, match='仍在分析'):
        add_photo(store, case, 'red')
    store.update_run(result['run_id'], lambda r: r.update(state='running', started_at=time.time()))
    store.charge(result['run_id'], 'model_calls')
    Store(store.root).recover()
    assert store.read('run', result['run_id'])['state'] == 'interrupted'
    assert store.read('episode', case['episode_id'])['model_calls'] == 1


def test_unconfigured_api_and_csrf(tmp_path):
    app = create_app(tmp_path, LocalModel('', ''))
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        token = client.get('/api/status').json()['session_token']
        body = {'request_id': 'test-creation', 'title': '待鉴定', 'question': '研究'}
        assert client.post('/api/cases', json=body).status_code == 403
        headers = {'X-Cizheng-Token': token}
        response = client.post('/api/cases', json=body, headers=headers)
        assert response.status_code == 200
        case = response.json()
        result = client.post('/api/cases/'+case['id']+'/runs', headers=headers,
                             json={'request_id': 'test-start', 'expected_case_revision': 1, 'mode': 'skills'})
        assert result.status_code == 503
        assert app.state.store.listing('run') == []
        assert client.get('/static/no-file').status_code == 404
        assert client.get('/api/artifacts/not-real').status_code == 404
        assert client.post('/api/cases', json=body, headers=dict(headers, Origin='https://evil.test')).status_code == 403


def test_export_blocks_stale_revision_and_escapes_html(store):
    case = add_photo(store, create_case(store))
    run_case(store, case)
    app = create_app(store.root, ScriptedModel())
    with TestClient(app) as client:
        token = client.get('/api/status').json()['session_token']
        headers = {'X-Cizheng-Token': token}
        result = client.post('/api/cases/'+case['id']+'/exports', headers=headers,
                             json={'request_id': 'export-one', 'expected_case_revision': case['revision']})
        assert result.status_code == 200, result.text
        assert len(result.json()['artifacts']) == 3
        raw = client.get(result.json()['artifacts'][0]['url'])
        assert raw.json()['run']['versions']['model']['provider'] == 'SYNTHETIC-TEST-ONLY'
        case = add_photo(store, store.read('case', case['id']), 'red')
        stale = client.post('/api/cases/'+case['id']+'/exports', headers=headers,
                            json={'request_id': 'export-two', 'expected_case_revision': case['revision']})
        assert stale.status_code == 409


def test_duplicate_json_key():
    with pytest.raises(ValueError):
        parse_json('{"a":1,"a":2}')


def test_malformed_model_fails_after_one_repair(store):
    class BadModel(ScriptedModel):
        async def complete(self, messages, timeout):
            return '{"actions":[{"tool":"shell","arguments":{}}]}', {}
    case = add_photo(store, create_case(store))
    result = run_case(store, case, BadModel())
    assert result['state'] == 'failed'
    assert result['model_calls'] == 2
    assert not result['assessment']


def test_budget_enforced_across_failed_runs(store):
    class LoopModel(ScriptedModel):
        async def complete(self, messages, timeout):
            return '{"actions":[{"tool":"read_case","arguments":{}}]}', {}
    case = add_photo(store, create_case(store))
    for _ in range(3):
        r = run_case(store, case, LoopModel())
        assert r['state'] == 'failed'
        assert r['model_calls'] == 12
    assert store.read('episode', case['episode_id'])['model_calls'] == 36
    with pytest.raises(Problem, match='预算耗尽'):
        run_case(store, case, LoopModel())


def test_cancel_during_model_preserves_counts(store):
    class SlowModel(ScriptedModel):
        async def complete(self, messages, timeout):
            await asyncio.sleep(100)
    async def scenario():
        case = add_photo(store, create_case(store))
        engine = Engine(store, SlowModel())
        r = store.start_run(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'], 'mode': 'skills'}, engine.versions())
        engine.schedule(r['run_id'])
        await asyncio.sleep(0.02)
        task = engine.tasks[r['run_id']]
        task.cancel()
        await task
        return store.read('run', r['run_id'])
    result = asyncio.run(scenario())
    assert result['state'] == 'cancelled' and result['model_calls'] == 1
    assert not result['assessment']


def test_api_upload_schedule_complete_and_idempotent_retry(tmp_path):
    app = create_app(tmp_path, ScriptedModel())
    with TestClient(app) as client:
        token = client.get('/api/status').json()['session_token']
        headers = {'X-Cizheng-Token': token}
        c = client.post('/api/cases', headers=headers, json={'request_id': 'api-create',
            'title': 'SYNTHETIC API TEST', 'question': '协议测试'}).json()
        body = {'request_id': 'api-photo', 'expected_case_revision': 1, 'filename': 'fake.png',
                'image_base64': photo(), 'view': 'synthetic'}
        upload = client.post('/api/cases/'+c['id']+'/evidence', headers=headers, json=body)
        assert upload.status_code == 200, upload.text
        assert client.post('/api/cases/'+c['id']+'/evidence', headers=headers, json=body).json() == upload.json()
        rbody = {'request_id': 'api-start', 'expected_case_revision': 2, 'mode': 'skills'}
        result = client.post('/api/cases/'+c['id']+'/runs', headers=headers, json=rbody)
        assert result.status_code == 202, result.text
        rid = result.json()['run_id']
        for _ in range(100):
            run = client.get('/api/runs/'+rid).json()
            if run['state'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert run['state'] == 'waiting_evidence', run.get('error')
        assert client.post('/api/cases/'+c['id']+'/runs', headers=headers, json=rbody).json()['run_id'] == rid
        assert len(app.state.store.listing('run')) == 1


def test_condition_skill_required_and_out_of_scope_consistency(store):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    assessment = deepcopy(run['assessment'])
    assessment['condition_hypotheses'] = ['合成疑点：可能反光，也可能附着物']
    with pytest.raises(ValueError, match='状况假说'):
        Engine.validate_assessment(run, Assessment.model_validate(assessment), {})
    engine = Engine(store, ScriptedModel())
    from cizheng.schemas import LoadSkill
    asyncio.run(engine.tool(run['id'], 'load_skill', LoadSkill(name='condition-hypothesis-test')))
    run = store.read('run', run['id'])
    Engine.validate_assessment(run, Assessment.model_validate(assessment), {})
    assessment['scope'] = 'out_of_scope'
    with pytest.raises(ValueError, match='范围外'):
        Engine.validate_assessment(run, Assessment.model_validate(assessment), {})


def test_local_adapter_sends_actual_multimodal_request(monkeypatch):
    import httpx
    original_client = httpx.AsyncClient
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"observations":[]}'}}],
                                        'usage': {'total_tokens': 5}})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=transport, **kw))
    model = LocalModel('http://127.0.0.1:8000/v1', 'TEST-VLM')
    data_url = 'data:image/png;base64,' + photo()
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': '协议测试'},
        {'type': 'image_url', 'image_url': {'url': data_url}}]}]
    content, usage = asyncio.run(model.complete(messages, 2))
    assert captured[0]['messages'][0]['content'][1]['image_url']['url'] == data_url
    assert captured[0]['model'] == 'TEST-VLM'
    assert usage['total_tokens'] == 5


def test_no_two_servers_on_same_database(tmp_path):
    with TestClient(create_app(tmp_path, ScriptedModel())):
        with pytest.raises(RuntimeError, match='只允许一个服务进程'):
            with TestClient(create_app(tmp_path, ScriptedModel())):
                pass
