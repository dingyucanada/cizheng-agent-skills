"""Photo-report invariants; synthetic fixtures do not measure ceramic accuracy."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from cizheng.api import create_app, export_bundle
from cizheng.photo_report import photo_report
from cizheng.reporting import markdown_report, html_report
from cizheng.schemas import Assessment
from cizheng.store import Store, Problem, uid
from test_closed_loop import create_case, add_photo, add_ref, run_case
from test_closed_loop import ScriptedModel
import json


def test_filenames_and_free_view_text_cannot_inflate_capture_index():
    run = {'snapshot': {'media': [{'id': 'one', 'filename': '真品_底足_釉面_100percent.jpg',
                                 'view': '全貌 底足 口沿 釉面 纹饰'}]}, 'observations': []}
    result = photo_report(run)
    assert result['capture_coverage']['value'] == 0
    assert result['capture_coverage']['view_verified'] is False
    assert result['authenticity_probability']['value'] is None
    assert result['photo_observation_coverage']['observed_count'] == 0


def test_references_and_repeat_views_cannot_raise_object_coverage():
    run = {'snapshot': {'media': [{'id': 'a', 'capture_role': 'base'},
                                 {'id': 'b', 'capture_role': 'base'}]},
           'observations': [{'id': 'ref-observation', 'media_id': 'reference', 'visible': '参照'}]}
    result = photo_report(run)
    assert result['capture_coverage']['value'] == 20
    assert result['photo_observation_coverage']['observed_count'] == 0
    assert len(result['photos']) == 2
    assert all(not item['observations'] for item in result['photos'])


def test_full_capture_guide_still_cannot_produce_authenticity_probability():
    roles = ['overall', 'base', 'mouth', 'glaze', 'decoration']
    run = {'snapshot': {'target_attribution': '某时期/窑口原作（仅测试）',
                       'media': [{'id': str(i), 'capture_role': r} for i, r in enumerate(roles)]},
           'state': 'failed', 'assessment': {'claims': []}}
    result = photo_report(run)
    assert result['capture_coverage']['value'] == 100
    assert result['status'] == 'incomplete_run'
    assert result['authenticity_probability']['status'] == 'not_calibrated'
    assert result['authenticity_probability']['value'] is None
    assert not result['authenticity_probability']['router_probabilities_used']


def test_label_revision_does_not_change_original_bytes_or_old_report(tmp_path):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    case = add_photo(store, case, 'red')
    run = run_case(store, case)
    before = photo_report(run)
    media = case['media'][0]
    raw = store.blob(media['id'])[1]
    case = store.label_capture(case['id'], media['id'], {
        'request_id': uid('request'), 'expected_case_revision': case['revision'],
        'capture_role': 'overall', 'view': '操作人视角声明'})
    assert case['revision'] == run['case_revision'] + 1
    assert case['media'][0]['sha256'] == media['sha256']
    assert store.blob(media['id'])[1] == raw
    assert photo_report(store.read('run', run['id'])) == before
    assert case['media'][0]['view_verified'] is False


def test_foreign_photo_cannot_be_labeled_and_stale_request_is_rejected(tmp_path):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    other = add_photo(store, create_case(store), 'red')
    body = {'request_id': uid('request'), 'expected_case_revision': case['revision'],
            'capture_role': 'base', 'view': '声明'}
    with pytest.raises(Problem, match='本案'):
        store.label_capture(case['id'], other['media'][0]['id'], body)
    store.label_capture(case['id'], case['media'][0]['id'], dict(body, request_id=uid('request')))
    with pytest.raises(Problem) as error:
        store.label_capture(case['id'], case['media'][0]['id'], dict(body, request_id=uid('request')))
    assert error.value.status == 409


def test_report_contains_photo_details_reasons_and_source_scope(tmp_path):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    case = add_photo(store, case, 'red')
    add_ref(store)
    run = run_case(store, case)
    bundle = export_bundle(store, store.read('case', case['id']), run)
    assert bundle['photo_report']['photo_observation_coverage']['observed_count'] == 2
    assert len(bundle['photo_report']['photos']) == 2
    assert all(claim['support_details'] for claim in bundle['photo_report']['claims'])
    text = markdown_report(bundle)
    assert '采集覆盖指数：0/100' in text
    assert '数值为null' in text and '判断理由与反证' in text
    assert '可见现象：合成色块' in text
    rendered = html_report(bundle, store.blob)
    assert 'report-indicators' in rendered
    assert rendered.count('data:image/jpeg;base64,') == 3  # Two object views + one actually used reference.
    assert all(m['sha256'] in rendered for m in case['media'])


def test_api_exposes_metrics_and_protects_label_mutations(tmp_path):
    app = create_app(tmp_path / 'data')
    store = app.state.store
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    with TestClient(app) as client:
        endpoint = '/api/cases/'+case['id']+'/evidence/'+case['media'][0]['id']+'/capture-label'
        body = {'request_id': uid('request'), 'expected_case_revision': case['revision'],
                'capture_role': 'base', 'view': '操作人底足声明'}
        assert client.patch(endpoint, json=body).status_code == 403
        token = client.get('/api/status').json()['session_token']
        assert client.patch(endpoint, json=body, headers={'X-Cizheng-Token': token}).status_code == 200
        result = client.get('/api/cases/'+case['id']).json()
        assert result['case']['media'][0]['capture_role'] == 'base'
        assert result['runs'][0]['photo_report']['capture_coverage']['value'] == 0
        assert result['runs'][0]['photo_report']['run_id'] == run['id']
        assert client.patch(endpoint, json=dict(body, request_id=uid('request'), capture_role='authentic'),
                            headers={'X-Cizheng-Token': token}).status_code == 422


def test_documentary_task_has_no_photo_or_authenticity_score():
    result = photo_report({'research_task': 'documentary_audit',
                          'snapshot': {'media': [{'id': 'unseen', 'capture_role': 'base'}]}})
    assert result['status'] == 'not_applicable'
    assert 'capture_coverage' not in result and 'authenticity_probability' not in result


@pytest.mark.parametrize('assertion', ['真品率95%', '真品概率0.95', 'authenticity probability 95%'])
def test_model_cannot_insert_uncalibrated_percentage_into_report(tmp_path, assertion):
    store = Store(tmp_path / 'data')
    run = run_case(store, add_photo(store, create_case(store)))
    assessment = deepcopy(run['assessment'])
    assessment['basic_info'] = assertion
    with pytest.raises(ValidationError, match='未经校准'):
        Assessment.model_validate(assessment)


@pytest.mark.parametrize('field', ['visible', 'interpretation', 'limitation'])
def test_vision_subcall_cannot_bypass_percentage_guard(tmp_path, field):
    class SelfReportedPercentage(ScriptedModel):
        async def complete(self, messages, timeout):
            content, usage = await super().complete(messages, timeout)
            if isinstance(messages[-1]['content'], list):
                value = json.loads(content)
                value['observations'][0][field] = '真品率95%'
                return json.dumps(value, ensure_ascii=False), usage
            return content, usage
    store = Store(tmp_path / 'data')
    run = run_case(store, add_photo(store, create_case(store)), SelfReportedPercentage())
    assert run['state'] == 'failed'
    assert run['observations'] == [] and run['assessment'] is None
    assert photo_report(run)['status'] == 'incomplete_run'


def test_percentage_guard_does_not_rewrite_original_operator_annotation(tmp_path):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    result = store.annotate(case['id'], {'request_id': uid('request'),
        'expected_case_revision': case['revision'], 'media_id': case['media'][0]['id'],
        'region': [0, 0, 1, 1], 'feature': 'other', 'observation': '送审者声称真品率95%，未经核验'})
    assert result['annotation']['observation'] == '送审者声称真品率95%，未经核验'
    assert result['annotation']['kind'] == 'operator_observation'
