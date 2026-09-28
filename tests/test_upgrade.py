"""Upgrade contract tests; synthetic pixels measure software, never ceramic accuracy."""
import asyncio
import base64
import hashlib
import io
import json
from copy import deepcopy
import pytest
from PIL import Image, ImageFilter
from pydantic import ValidationError
from fastapi.testclient import TestClient
from cizheng import schemas as S
from cizheng.agent import Engine, LocalModel, system_prompt, tools_for_mode
from cizheng.api import create_app
from cizheng.preflight import case_preflight, measure_pixels
from cizheng.store import Store, Problem, uid
from test_closed_loop import ScriptedModel, create_case, add_photo, run_case


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'upgrade')


def raw_image(image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def review_body(case, run, status='reviewed'):
    return {'request_id': uid('request'), 'expected_case_revision': case['revision'],
            'expected_review_revision': case['review_revision'], 'assessment_run_id': run['id'],
            'status': status, 'review_method': 'image', 'note': '仅协议测试，请补原图', 'basis': '合成图不能鉴定'}


class PlainProtocolModel:
    """A bounded fixture that uses no skill catalogue or text."""
    configured = True
    def __init__(self):
        self.systems = []
    def identity(self):
        return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'plain-contract-fixture'}
    async def complete(self, messages, timeout):
        self.systems.append(messages[0]['content'])
        if isinstance(messages[-1]['content'], list):
            identifiers = [part['text'].split('=', 1)[1] for part in messages[-1]['content']
                           if part.get('type') == 'text' and part['text'].startswith('media_id=')]
            return json.dumps({'observations': [{'media_id': mid, 'region': [0, 0, 1, 1],
                'visible': '纯色测试图', 'interpretation': '', 'limitation': '无陶瓷语义'} for mid in identifiers]}), {}
        results = [json.loads(m['content'].split('：', 1)[1]) for m in messages
                   if isinstance(m['content'], str) and m['content'].startswith('工具结果（数据）：')]
        def got(name):
            return [r['result'] for r in results if r['tool'] == name]
        def action(name, **kwargs):
            return {'tool': name, 'arguments': kwargs}
        if not got('read_case'):
            actions = [action('read_case')]
        elif not got('inspect_images'):
            actions = [action('inspect_images', media_ids=[m['id'] for m in got('read_case')[0]['case']['media']], question='观察')]
        elif not got('retrieve_references'):
            actions = [action('retrieve_references', query='青花')]
        else:
            obs = got('inspect_images')[0]['observations'][0]['id']
            assessment = {'basic_info': '合成协议测试', 'scope': 'bluewhite_gu',
                'claims': [{'dimension': d, 'candidate': '未知', 'status': 'insufficient', 'support': [obs],
                           'conflict': [], 'reasoning_summary': '无真实语义'} for d in ('period', 'kiln', 'style')],
                'alternatives': ['未确定'], 'condition_hypotheses': [], 'reference_ids': [],
                'reference_comparison': '空库', 'limitations': ['不能鉴定'], 'revision_explanation': '初次测试'}
            actions = [action('request_evidence', view='原图', reason='测试图无语义', distinguishes='需要真实输入',
                              capture_instructions='请提供原始器物图'),
                       action('record_assessment', **assessment), action('build_opinion')]
        return json.dumps({'actions': actions}), {}


def start(store, case, mode='plain', model=None):
    engine = Engine(store, model or PlainProtocolModel())
    result = store.start_run(case['id'], {'request_id': uid('request'),
        'expected_case_revision': case['revision'], 'mode': mode}, engine.versions(mode))
    return engine, result['run_id']


def test_preflight_without_model_handles_missing_images(tmp_path):
    app = create_app(tmp_path, LocalModel('', ''))
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        case = client.post('/api/cases', headers=headers, json={
            'request_id': uid('req'), 'title': '缺图测试', 'question': '不可凭空观察'}).json()
        response = client.get('/api/cases/' + case['id'] + '/preflight')
        assert response.status_code == 200
        preflight = response.json()
        assert preflight['next_step'] == 'ask_user' and preflight['review_required']
        assert preflight['images'] == [] and preflight['verified_views'] == []
        assert app.state.store.listing('run') == []
        assert not client.get('/api/status').json()['model_configured']


def test_pixel_statistics_are_measured_not_inferred_from_declaration(store):
    case = add_photo(store, create_case(store), 'white')
    preflight = case_preflight(store, case)
    metrics = preflight['images'][0]['metrics']
    assert (metrics['width'], metrics['height']) == (48, 64)
    assert metrics['bright_pixel_ratio_gte_250'] == 1
    assert metrics['dark_pixel_ratio_lte_5'] == 0
    assert metrics['contrast_stddev_0_255'] == 0
    assert metrics['edge_response_variance'] == 0
    assert metrics['calibrated'] is False and metrics['quality_verdict'] == 'not_assessed'
    assert preflight['declared_views'] == ['合成视角'] and preflight['verified_views'] == []
    assert preflight['next_step'] == 'ready_for_analysis' and preflight['review_required']
    # The user explicitly called these synthetic; the pixel preflight does not infer AI origin.
    assert 'ai_probability' not in json.dumps(preflight)
    assert not preflight['images'][0]['view_verified']


def test_texture_and_blur_change_descriptive_metrics():
    im = Image.new('L', (64, 64))
    im.putdata([255 if (x // 4 + y // 4) % 2 else 0 for y in range(64) for x in range(64)])
    texture = measure_pixels(raw_image(im))
    blur = measure_pixels(raw_image(im.filter(ImageFilter.GaussianBlur(3))))
    assert texture['contrast_stddev_0_255'] > blur['contrast_stddev_0_255']
    assert texture['edge_response_variance'] > blur['edge_response_variance']
    assert measure_pixels(raw_image(Image.new('RGB', (1, 1))))['edge_response_variance'] is None


def test_historical_corrupt_blob_is_explicit_not_fake_metrics(store):
    case = add_photo(store, create_case(store))
    with store.tx() as db:
        db.execute('UPDATE blobs SET bytes=? WHERE id=?', (b'broken', case['media'][0]['id']))
    preflight = case_preflight(store, case)
    assert preflight['images'] == [] and len(preflight['errors']) == 1
    assert preflight['next_step'] == 'ask_user' and preflight['review_required']


def test_plain_does_not_read_catalogue_and_hashes_actual_prompt(store, monkeypatch):
    import cizheng.agent as module
    def forbidden():
        raise AssertionError('plain must never read skills')
    monkeypatch.setattr(module, 'skill_catalog', forbidden)
    case = add_photo(store, create_case(store))
    model = PlainProtocolModel()
    engine, rid = start(store, case, model=model)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assert run['state'] == 'waiting_evidence', run.get('error')
    assert run['mode'] == 'plain' and run['loaded_skills'] == {} and run['versions']['skills'] == {}
    assert run['versions']['prompt_hash'] == hashlib.sha256(model.systems[0].encode()).hexdigest()
    assert 'discover_skills' not in model.systems[0] and 'ceramic-route' not in model.systems[0]
    assert run['next_step'] == 'ask_user' and run['review_required']
    with pytest.raises(ValueError, match='不可使用'):
        asyncio.run(engine.tool(rid, 'load_skill', S.LoadSkill(name='ceramic-route')))
    with pytest.raises(ValueError, match='不可使用'):
        asyncio.run(engine.tool(rid, 'discover_skills', S.Empty()))


def test_modes_share_all_non_skill_tools_and_evidence_contract(store):
    skills, plain = tools_for_mode('skills'), tools_for_mode('plain')
    assert set(skills) - set(plain) == {'discover_skills', 'load_skill', 'read_skill_resource'}
    assert all(skills[name] is plain[name] for name in plain)
    assert Engine(store).versions('skills')['prompt_hash'] != Engine(store).versions('plain')['prompt_hash']
    case = add_photo(store, create_case(store))
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    assessment = deepcopy(run['assessment'])
    assessment['claims'][0]['support'] = ['fabricated-observation']
    with pytest.raises(ValueError, match='非本轮'):
        Engine.validate_assessment(run, S.Assessment.model_validate(assessment), {})
    assert run['model_calls'] <= 12 and run['tool_calls'] <= 20


def test_mode_switch_and_version_mismatch_rejected(store):
    case = add_photo(store, create_case(store))
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    case = add_photo(store, store.read('case', case['id']), 'red')
    body = {'request_id': uid('req'), 'expected_case_revision': case['revision'], 'mode': 'skills'}
    with pytest.raises(Problem, match='不可切换模式'):
        store.start_run(case['id'], body, engine.versions('skills'))
    body['mode'] = 'plain'
    with pytest.raises(Problem, match='模式与提示版本'):
        store.start_run(case['id'], body, engine.versions('skills'))
    assert S.RunIn(request_id='request-123', expected_case_revision=2, mode='plain').mode == 'plain'
    with pytest.raises(ValidationError):
        S.RunIn(request_id='request-123', expected_case_revision=2, mode='test')


def test_review_persists_without_erasing_next_evidence_and_exports(store):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    case = store.read('case', case['id'])
    old_assessment = deepcopy(run['assessment'])
    old_request = deepcopy(run['evidence_request'])
    body = review_body(case, run)
    case = store.add_review(case['id'], body, '本地操作人')
    assert case == store.add_review(case['id'], body, '本地操作人')
    persisted = Store(store.root).read('case', case['id'])
    assert persisted['review']['status'] == 'reviewed' and not persisted['review_required']
    assert not persisted['review']['identity_verified'] and len(persisted['reviews']) == 1
    updated = store.read('run', run['id'])
    assert updated['assessment'] == old_assessment and updated['evidence_request'] == old_request
    assert updated['next_step'] == 'ask_user' and not updated['review_required']
    app = create_app(store.root, LocalModel('', ''))
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        response = client.post('/api/cases/' + case['id'] + '/exports', headers=headers, json={
            'request_id': uid('req'), 'expected_case_revision': case['revision']})
        assert response.status_code == 200
        export = client.get(response.json()['artifacts'][0]['url']).json()
        assert export['review']['status'] == 'reviewed'
        assert not export['expert_reviewed'] and export['preflight']['next_step'] == 'ask_user'


def test_new_evidence_reopens_review_and_stale_run_cannot_clear_it(store):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    case = store.read('case', case['id'])
    case = store.add_review(case['id'], review_body(case, run), '本地操作人')
    reviewed_revision = case['review_revision']
    same = add_photo(store, case)  # identical pixels are idempotent; no new evidence
    assert same['review']['status'] == 'reviewed'
    case = add_photo(store, same, 'red')
    assert case['review']['status'] == 'pending' and case['review_required']
    assert case['review_revision'] > reviewed_revision
    with pytest.raises(Problem, match='旧意见不能放行'):
        store.add_review(case['id'], review_body(case, run), '本地操作人')
    assert case['reviews'][0]['status'] == 'reviewed'


def test_review_request_evidence_is_append_only_and_has_own_revision(store):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    case = store.read('case', case['id'])
    body = review_body(case, run, 'request_evidence')
    case = store.add_review(case['id'], body, '本地操作人')
    assert case['review_required'] and case['review']['status'] == 'request_evidence'
    preflight = case_preflight(store, case, store.read('run', run['id']))
    assert preflight['next_step'] == 'ask_user' and preflight['review_required']
    stale = dict(body, request_id=uid('req'))
    with pytest.raises(Problem, match='状态已更新'):
        store.add_review(case['id'], stale, '本地操作人')
    first = deepcopy(case['reviews'][0])
    case = store.add_review(case['id'], review_body(case, run), '本地操作人')
    assert case['reviews'][0] == first and len(case['reviews']) == 2
    assert case['revision'] == run['case_revision']


def test_legacy_records_default_to_pending_review(store):
    case = create_case(store)
    with store.tx() as db:
        for key in ('review', 'review_required', 'review_revision', 'reviews', 'mode'):
            case.pop(key, None)
        Store.put(db, 'case', case)
    recovered = Store(store.root).read('case', case['id'])
    assert recovered['review']['status'] == 'pending'
    assert recovered['reviews'] == [] and recovered['review_required']
    assert recovered['mode'] is None


def test_failed_model_call_records_cost_purpose_without_response_leak(store):
    class FailureModel(PlainProtocolModel):
        async def complete(self, messages, timeout):
            raise RuntimeError('SECRET provider response must not be stored')
    case = add_photo(store, create_case(store))
    engine, rid = start(store, case, model=FailureModel())
    asyncio.run(engine.execute(rid))
    run = store.read('run', rid)
    events = [e for e in run['events'] if e['type'] == 'model']
    assert run['state'] == 'failed' and run['model_calls'] == 1
    assert len(events) == 1 and events[0]['purpose'] == 'action'
    assert events[0]['outcome'] == 'failed' and events[0]['failure_type'] == 'RuntimeError'
    assert events[0]['elapsed'] >= 0 and events[0]['output_hash'] is None
    assert 'SECRET' not in json.dumps(run)


@pytest.mark.parametrize('claim', ['真品概率91%', 'AI生成置信度0.92', '90%可能是真品', '真伪概率九成'])
def test_uncalibrated_probability_rejected_in_assessment(store, claim):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    assessment = deepcopy(run['assessment'])
    assessment['claims'][0]['reasoning_summary'] = claim
    with pytest.raises(ValidationError, match='数值概率'):
        S.Assessment.model_validate(assessment)


def test_current_review_api_binds_run_and_records_identity_unverified(store):
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    case = store.read('case', case['id'])
    app = create_app(store.root, LocalModel('', ''))
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        response = client.post('/api/cases/' + case['id'] + '/reviews', headers=headers,
                               json=review_body(case, run))
        assert response.status_code == 200, response.text
        assert not response.json()['review']['identity_verified']
        assert response.json()['review']['assessment_run_id'] == run['id']


def test_snapshot_input_hash_matches_persisted_mode(store):
    from cizheng.store import digest
    case = add_photo(store, create_case(store))
    _, rid = start(store, case)
    run = store.read('run', rid)
    assert run['snapshot']['mode'] == run['mode'] == 'plain'
    assert run['input_hash'] == digest({'case': run['snapshot'], 'refs': run['reference_snapshot'],
                                        'versions': run['versions'], 'mode': run['mode'], 'text_review': run['text_review_snapshot'],
                                        'analysis_scope': run['snapshot']['analysis_scope'],
                                        'knowledge_snapshot_sha256': run['knowledge_snapshot']['snapshot_sha256']})


def test_plain_revision_still_requires_dependency_review(store):
    case = add_photo(store, create_case(store))
    engine, rid = start(store, case)
    asyncio.run(engine.execute(rid))
    first = store.read('run', rid)
    case = add_photo(store, store.read('case', case['id']), 'red')
    engine, rid = start(store, case)
    # The fixture intentionally skips dependency review. Shared checks must stop it.
    asyncio.run(engine.execute(rid))
    revised = store.read('run', rid)
    assert revised['parent_run_id'] == first['id']
    assert revised['state'] == 'failed'
    errors = [e['detail'] for e in revised['events'] if e['type'] == 'validation_error']
    assert any('读取上一版' in detail for detail in errors)
    assert not revised['loaded_skills']


def test_explicit_reference_refresh_unblocks_research_preserves_parent_and_review(store):
    from test_closed_loop import add_ref
    case = add_photo(store, create_case(store))
    first = run_case(store, case)
    assert first['assessment']['reference_ids'] == []
    case = store.read('case', case['id'])
    case = store.add_review(case['id'], review_body(case, first), '本地操作人')
    original_media = deepcopy(case['media'])
    original_assessment = deepcopy(first['assessment'])
    reference = add_ref(store)
    engine = Engine(store, ScriptedModel())
    # Saving a library item alone neither changes the case nor authorizes another round.
    with pytest.raises(Problem, match='本版本已有意见'):
        store.start_run(case['id'], {'request_id': uid('request'),
                        'expected_case_revision': case['revision'], 'mode': 'skills'}, engine.versions())
    episode_before = store.read('episode', case['episode_id'])
    app = create_app(store.root, LocalModel('', ''))
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        body = {'request_id': uid('request'), 'expected_case_revision': case['revision']}
        response = client.post('/api/cases/' + case['id'] + '/refresh-references', headers=headers, json=body)
        assert response.status_code == 200, response.text
        refreshed = response.json()
        assert refreshed['changed']
        case = refreshed['case']
        assert case['revision'] == first['case_revision'] + 1
        assert case['media'] == original_media  # No fabricated photo is used to trigger revision.
        assert case['review']['status'] == 'pending' and case['review_required']
        assert case['current_run_id'] == first['id']
        assert case['reference_refreshes'][-1]['authorized_reference_ids'] == [reference['id']]
        assert client.post('/api/cases/' + case['id'] + '/refresh-references', headers=headers, json=body).json() == refreshed
        stale = client.post('/api/cases/' + case['id'] + '/exports', headers=headers, json={
            'request_id': uid('request'), 'expected_case_revision': case['revision']})
        assert stale.status_code == 409
    assert store.read('episode', case['episode_id']) == episode_before
    second = run_case(store, case)
    assert second['state'] == 'waiting_evidence', second.get('error')
    assert second['parent_run_id'] == first['id'] and 'evidence-revise' in second['loaded_skills']
    assert second['dependencies_reviewed']
    assert second['assessment']['reference_ids'] == [reference['id']]
    dependency = next(event['result'] for event in second['events']
                      if event['type'] == 'tool_result' and event.get('tool') == 'review_dependencies')
    assert dependency['new_media_ids'] == []
    assert dependency['reference_changes']['added_reference_ids'] == [reference['id']]
    assert store.read('run', first['id'])['assessment'] == original_assessment


def test_reference_refresh_no_change_does_not_spend_revision_or_budget(store):
    from test_closed_loop import add_ref
    case = add_photo(store, create_case(store))
    first = run_case(store, case)
    case = store.read('case', case['id'])
    add_ref(store, permission='unknown')
    before = store.read('episode', case['episode_id'])
    result = store.refresh_references(case['id'], {'request_id': uid('request'),
                                      'expected_case_revision': case['revision']})
    assert not result['changed'] and result['case']['revision'] == case['revision']
    assert result['case']['reference_refreshes'] == []
    add_ref(store)
    result = store.refresh_references(case['id'], {'request_id': uid('request'),
                                      'expected_case_revision': case['revision']})
    assert result['changed']
    refreshed = result['case']
    result = store.refresh_references(case['id'], {'request_id': uid('request'),
                                      'expected_case_revision': refreshed['revision']})
    assert not result['changed'] and result['case'] == refreshed
    assert len(result['case']['reference_refreshes']) == 1
    assert store.read('episode', case['episode_id']) == before
    assert len(store.listing('run')) == 1 and store.read('run', first['id'])['state'] == 'waiting_evidence'


def test_reference_refresh_rejects_active_case_and_stale_revision(store):
    from test_closed_loop import add_ref
    case = add_photo(store, create_case(store))
    run_case(store, case)
    case = add_photo(store, store.read('case', case['id']), 'red')
    add_ref(store)
    engine, run_id = start(store, case, mode='skills', model=ScriptedModel())
    with pytest.raises(Problem, match='仍在分析'):
        store.refresh_references(case['id'], {'request_id': uid('request'),
                                 'expected_case_revision': case['revision']})
    assert store.read('case', case['id'])['revision'] == case['revision']
    assert store.read('run', run_id)['state'] == 'queued'
    store.finish(run_id, 'cancelled')
    with pytest.raises(Problem, match='案件已更新'):
        store.refresh_references(case['id'], {'request_id': uid('request'),
                                 'expected_case_revision': case['revision'] - 1})


def test_reference_refresh_reports_removed_or_changed_authorized_records(store):
    from test_closed_loop import add_ref
    case = add_photo(store, create_case(store))
    reference = add_ref(store)
    first = run_case(store, case)
    case = store.read('case', case['id'])
    # Simulate an independently corrected source record; no UI mutation endpoint is introduced.
    with store.tx() as db:
        updated = store.get(db, 'reference', reference['id'])
        updated['permission'] = 'unknown'
        store.put(db, 'reference', updated)
    refreshed = store.refresh_references(case['id'], {'request_id': uid('request'),
                                           'expected_case_revision': case['revision']})
    assert refreshed['changed']
    second = run_case(store, refreshed['case'])
    assert second['state'] == 'waiting_evidence'
    assert second['assessment']['reference_ids'] == []
    dependency = next(event['result'] for event in second['events']
                      if event['type'] == 'tool_result' and event.get('tool') == 'review_dependencies')
    assert dependency['reference_changes']['removed_reference_ids'] == [reference['id']]
    assert store.read('run', first['id'])['assessment']['reference_ids'] == [reference['id']]
