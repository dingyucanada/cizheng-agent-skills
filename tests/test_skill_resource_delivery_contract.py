"""Real tool replay of the r3 resource-name error; no GPU or accuracy claims."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from cizheng import agent, schemas as S
from cizheng.agent import Engine, LocalModel
from cizheng.store import Problem, Store
from test_guided_workflow import new_case, start
from test_source_attribution_gate import opinion


@pytest.fixture(params=[False, True], ids=['original', 'compact'])
def skill_run(tmp_path, monkeypatch, request):
    def forbidden(*args, **kwargs):
        pytest.fail('Resource tests cannot call a provider or real model')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setattr(LocalModel, 'complete', forbidden)
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1' if request.param else '0')
    monkeypatch.delenv('CIZHENG_GUIDED_WORKFLOW', raising=False)
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store), active=True)
    return store, engine, run_id, model


def load(engine, run_id, name='bluewhite-attribution-test'):
    return asyncio.run(engine.tool(run_id, 'load_skill', S.LoadSkill(name=name)))


def resource_option(result):
    # The caller selects one of the original paths; the host has not selected it.
    path = next(path for path in result['resources'] if path == 'references/comparison-method.md')
    return {'tool': result['resource_reader']['tool'], 'arguments': {
        'name': result['resource_reader']['name'], 'path': path}}


def test_load_returns_exact_owner_and_path_without_selecting_or_reading(skill_run):
    store, engine, run_id, model = skill_run
    result = load(engine, run_id)
    assert result['resource_reader'] == {'tool': 'read_skill_resource', 'name': result['name']}
    assert result['resources'] == [path for path in agent.skill_catalog()[result['name']]['files'] if path != 'SKILL.md']
    assert resource_option(result)['arguments']['name'] == 'bluewhite-attribution-test'
    assert 'path按需从resources原样选，须由模型调用，不自动读取' in result['resource_call_notice']
    run = store.read('run', run_id)
    assert run.get('read_skill_resources', []) == [] and run['assessment'] is None
    assert run['model_calls'] == run['tool_calls'] == 0
    assert not model.main_messages and not model.vision_ids


def test_r3_wrong_basename_is_rejected_then_model_selected_owner_can_read(skill_run):
    store, engine, run_id, _ = skill_run
    result = load(engine, run_id)
    before = deepcopy(store.read('run', run_id)['loaded_skills'])
    wrong = S.ReadSkillResource(name='comparison-method', path='references/comparison-method.md')
    for _ in range(2):
        with pytest.raises(ValueError) as rejected:
            asyncio.run(engine.tool(run_id, 'read_skill_resource', wrong))
        message = str(rejected.value)
        assert 'name是所属Skill目录名，不是资源文件名或basename' in message
        assert '当前已加载可选name：["bluewhite-attribution-test"]' in message
        assert store.read('run', run_id).get('read_skill_resources', []) == []
        assert store.read('run', run_id)['loaded_skills'] == before
    # The host never rewrites the rejected parameters. The caller chooses the hint.
    chosen = resource_option(result)
    read = asyncio.run(engine.tool(run_id, chosen['tool'], S.ReadSkillResource.model_validate(chosen['arguments'])))
    run = store.read('run', run_id)
    assert read['skill'] == chosen['arguments']['name']
    assert read['path'] == chosen['arguments']['path'] and read['text']
    assert run['read_skill_resources'] == [{key: read[key] for key in ('skill', 'path', 'sha256')}]
    assert run['assessment'] is None and run['model_calls'] == 0


@pytest.mark.parametrize('path', ['../ceramic-route/SKILL.md', 'references/unregistered.md'])
def test_resource_hints_do_not_bypass_the_existing_manifest_boundary(skill_run, path):
    store, engine, run_id, _ = skill_run
    load(engine, run_id)
    with pytest.raises(Problem, match='当前技能包清单内'):
        asyncio.run(engine.tool(run_id, 'read_skill_resource', S.ReadSkillResource(
            name='bluewhite-attribution-test', path=path)))
    assert store.read('run', run_id).get('read_skill_resources', []) == []


def test_resource_hint_keeps_frozen_version_check(skill_run):
    store, engine, run_id, _ = skill_run
    result = load(engine, run_id)
    chosen = resource_option(result)
    store.update_run(run_id, lambda run: run['loaded_skills'].update({'bluewhite-attribution-test': '0' * 64}))
    with pytest.raises(Problem, match='技能版本不一致'):
        asyncio.run(engine.tool(run_id, chosen['tool'], S.ReadSkillResource.model_validate(chosen['arguments'])))
    assert store.read('run', run_id).get('read_skill_resources', []) == []


@pytest.mark.parametrize('scope,required', [
    ('bluewhite_gu', 'bluewhite-attribution-test'), ('ceramic_research', 'ceramic-research-record')])
def test_scope_error_names_existing_prerequisite_without_loading_or_authoring(skill_run, scope, required):
    store, engine, run_id, _ = skill_run
    load(engine, run_id, 'ceramic-route')
    run = store.read('run', run_id)
    before = deepcopy(run)
    value = opinion()
    value['scope'] = scope
    with pytest.raises(ValueError) as rejected:
        Engine.validate_assessment(run, S.Assessment.model_validate(value), {})
    assert '须先调用load_skill，name=' + required in str(rejected.value)
    assert run == before == store.read('run', run_id)
    assert required not in run['loaded_skills'] and run['assessment'] is None


# Actual decoder commitments from the saved main8b-r3 run. Preserving these is
# required for the already registered native server, not evidence of better output.
R3_SCHEMA_HASHES = {
    ('plain', 'documentary_audit', None): 'f066947a82e7e9c0b2f78e13032f8d2ae9d4201f7767f31e894e0724866a9821',
    ('skills', 'documentary_audit', None): '9a74cbe462a679176f1a2cdb4eb947494c858342916a264c6cd13cc7c57a5aa2',
    ('plain', 'visual_research', None): 'c0c080104f56bb914e244e6f0b4b55aba601f728418098861871a852fbba0991',
    ('skills', 'visual_research', None): 'e94ee9b4289315f7d1cab0155ce8c4186644755707f588bd9c992c0413429e73',
    ('plain', 'visual_research', 'respond_critic_required'): '2b1d49e9604008ebba734d3849bfa47ae259129bae4434552f3ee31c78b5661b',
    ('plain', 'visual_research', 'record_assessment_required'): '9f787e56ac0fe2e9322b27f4128b4a534f9248635f8701fb8497bbe2a5021d66',
    ('plain', 'visual_research', 'build_opinion_available'): 'c0c080104f56bb914e244e6f0b4b55aba601f728418098861871a852fbba0991',
    ('skills', 'visual_research', 'respond_critic_required'): '05caae15c48cd580db2b05b1fa4de41b192991b7162982022463926fe75dc89c',
    ('skills', 'visual_research', 'record_assessment_required'): '73de254a26813c1e4f142b005b9d0968ea1c0ec2a78bab0dc82200856df97ef7',
    ('skills', 'visual_research', 'build_opinion_available'): 'e94ee9b4289315f7d1cab0155ce8c4186644755707f588bd9c992c0413429e73',
}


@pytest.mark.parametrize('mode,task,phase', R3_SCHEMA_HASHES)
def test_r4_keeps_the_registered_r3_decoder_bytes(mode, task, phase):
    assert agent.decoder_schema_sha256(agent.action_output_schema(mode, task, True, phase)) == R3_SCHEMA_HASHES[(mode, task, phase)]


def test_resource_argument_schema_and_limits_are_not_changed_by_hints():
    expected = S.ReadSkillResource.model_json_schema()
    for compact in (False, True):
        assert agent.model_argument_schema('read_skill_resource', S.ReadSkillResource, compact) == expected
    assert agent.model_argument_schema('record_assessment', S.Assessment, True)['properties']['reference_comparison']['maxLength'] == 48
    assert agent.OBSERVED_METHOD_RULE['source'] == 'first-batch-current-run-vision-visible-only'
    assert agent.OBSERVED_METHOD_RULE['triggers'] == ['青花', 'blue-and-white']
