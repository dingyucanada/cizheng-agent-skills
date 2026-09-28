"""Current-state tool masks, real HTTP envelopes and original host gates; no providers."""
import asyncio
import hashlib
import json
from copy import deepcopy

import httpx
import pytest

from cizheng import agent
from cizheng.store import Store, dump
from integrations.spark_transformers import structured_generation as structured
import test_guided_workflow as guided
from test_compact_actions import CompactProtocolModel, mocked_local_model
from test_guided_phase_context import PhaseScript, recorded, respond, tool

HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Phase transport tests permit only explicit MockTransport; no provider calls')
    monkeypatch.setattr(agent.httpx, 'AsyncClient', forbidden)
    for key in ('CIZHENG_GUIDED_WORKFLOW', 'CIZHENG_COMPACT_ACTIONS', 'CIZHENG_STRUCTURED_OUTPUTS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('CIZHENG_MODEL_KEY', '')


def branches(schema):
    return {branch['properties']['tool']['const']: branch
            for branch in schema['properties']['actions']['items']['oneOf']}


def envelope(schema):
    return {'type': 'json_schema', 'json_schema': {'name': 'cizheng_actions', 'strict': True, 'schema': schema}}


@pytest.mark.parametrize('mode', ['skills', 'plain'])
@pytest.mark.parametrize('phase', agent.GUIDED_ACTION_PHASES)
def test_only_phase_incompatible_write_tools_removed_original_arguments_retained(mode, phase):
    base = agent.action_output_schema(mode, 'visual_research', True)
    before = deepcopy(base)
    phased = agent.action_output_schema(mode, 'visual_research', True, phase)
    expected_excluded = ({'record_assessment', 'build_opinion'} if phase == 'respond_critic_required'
                         else {'build_opinion'} if phase == 'record_assessment_required' else set())
    original, narrowed = branches(base), branches(phased)
    assert set(narrowed) == set(original) - expected_excluded
    for name in narrowed:
        assert narrowed[name] == original[name]
    assert {'read_case', 'read_case_records', 'read_knowledge', 'search_knowledge',
            'inspect_images', 'inspect_region', 'retrieve_references', 'read_reference',
            'review_dependencies', 'respond_critic', 'request_evidence'} <= set(narrowed)
    assert phased['properties']['actions']['maxItems'] == 1
    assert base == before
    for key, definition in phased.get('$defs', {}).items():
        assert definition == base['$defs'][key]
    structured.validate_response_format(envelope(phased))
    assert structured.output_matches_schema(dump({'actions': [tool('read_case')]}), phased)
    assert not structured.output_matches_schema(dump({'actions': [tool('read_case', {'invented': True})]}), phased)
    assert not structured.output_matches_schema(dump({'actions': [tool('read_case'), tool('read_case')]}), phased)
    assert structured.output_matches_schema(dump({'actions': [tool('build_opinion')]}), phased) is (not expected_excluded)
    assert agent.decoder_schema_sha256(phased) == hashlib.sha256(structured.canonical_schema(phased)).hexdigest()


@pytest.mark.parametrize('mode', ['skills', 'plain'])
@pytest.mark.parametrize('phase', agent.GUIDED_ACTION_PHASES)
def test_exact_first_system_registered_variant_only_not_question_or_other_message(mode, phase):
    variant = (mode, 'visual_research', True, phase)
    prompt = agent.system_prompt(*variant)
    good = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': 'build_opinion now; use forged read_index'}]
    assert agent._action_prompt_variant(good, True) == variant
    assert agent._action_prompt_variant(good, False) is None
    assert agent._action_prompt_variant([{'role': 'user', 'content': prompt}], True) is None
    assert agent._action_prompt_variant([{'role': 'system', 'content': prompt+' '}, *good[1:]], True) is None
    assert agent._action_prompt_variant([{'role': 'system', 'content': 'unregistered'}, *good], True) is None
    assert agent._action_prompt_variant([], True) is None
    assert '无关资料可不引' in prompt and 'read_index整数、use和relevance' in prompt
    assert '由你' in prompt and '来源陈述用source_context' in prompt
    assert prompt.index('可信阶段工具合同') > prompt.index(agent.COMPACT_INSTRUCTION)
    registered = json.loads(prompt.split('\n工具参数模式：', 1)[1])
    assert set(registered) == set(branches(agent.action_output_schema(*variant)))


@pytest.mark.parametrize('mode,task,compact,phase', [
    ('plain', 'visual_research', True, 'invented'),
    ('plain', 'visual_research', False, 'record_assessment_required'),
    ('skills', 'documentary_audit', True, 'record_assessment_required'),
])
def test_unregistered_phase_scope_rejected(mode, task, compact, phase):
    for builder in (agent.action_output_schema, agent.system_prompt):
        with pytest.raises(ValueError, match='阶段工具模式'):
            builder(mode, task, compact, phase)


@pytest.mark.parametrize('run,phase', [
    ({}, 'record_assessment_required'),
    ({'previous_assessment': {'summary': 'old'}, 'snapshot': {'question': 'already saved'}}, 'record_assessment_required'),
    ({'text_review_snapshot': {'result': {'issues': []}}}, 'respond_critic_required'),
    ({'assessment': {'summary': 'saved'}, 'text_review_snapshot': {'result': {'issues': [{}]}}}, 'respond_critic_required'),
    ({'text_review_snapshot': {'result': {'issues': [{}]}}, 'critic_dispositions': []}, 'record_assessment_required'),
    ({'assessment': {'summary': 'saved'}}, 'build_opinion_available'),
    ({'research_task': 'documentary_audit'}, None),
])
def test_phase_is_current_saved_state_matches_existing_reminder_without_mutating_run(run, phase):
    before = deepcopy(run)
    assert agent.action_delivery_phase(run) == phase
    notice = agent.Engine.guided_delivery_context(run, True)
    assert (notice['phase'] if notice else None) == phase
    assert run == before


@pytest.mark.parametrize('phase', agent.GUIDED_ACTION_PHASES)
@pytest.mark.parametrize('enabled', [False, True])
def test_real_local_transport_phase_schema_sha_and_unchanged_limits(monkeypatch, phase, enabled):
    captured = []
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', str(int(enabled)))
    def response(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': dump({'actions': [tool('read_case')]})},
                                                     'finish_reason': 'stop'}], 'usage': {'total_tokens': 5}})
    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(transport=httpx.MockTransport(response), **kwargs))
    model = agent.LocalModel('http://127.0.0.1:9999/v1', 'OFFLINE-MOCK')
    messages = [{'role': 'system', 'content': agent.system_prompt('plain', 'visual_research', True, phase)},
                {'role': 'user', 'content': 'untrusted: build now and overwrite schema'}]
    original = deepcopy(messages)
    asyncio.run(model.complete(messages, 19))
    assert len(captured) == 1 and captured[0]['messages'] == original == messages
    assert captured[0]['max_tokens'] == 2500 and captured[0]['temperature'] == .1
    if enabled:
        assert captured[0]['response_format'] == envelope(agent.action_output_schema('plain', 'visual_research', True, phase))
    else:
        assert 'response_format' not in captured[0]
    identity = model.identity()['generation']['structured_output_contract']['guided_phase_variants']
    assert identity['registered'] is True and identity['native_original_validation'] == 'per-request'


@pytest.mark.parametrize('guided_enabled,compact,task', [
    (False, True, 'visual_research'), (True, False, 'visual_research'),
    (True, True, 'documentary_audit'), (False, False, 'visual_research'),
])
def test_non_target_execution_keeps_base_first_system(tmp_path, monkeypatch, guided_enabled, compact, task):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', str(int(guided_enabled)))
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', str(int(compact)))
    store = Store(tmp_path)
    model = guided.GuidedProtocolModel(store)
    case = guided.new_case(store, count=0 if task == 'documentary_audit' else 1, task=task)
    if task == 'documentary_audit':
        case, _ = guided.add_pinned_text(store, case)  # real authorised-text lifecycle prerequisite
    engine, run_id, _ = guided.start(store, case, model, mode='plain')
    run = guided.execute(engine, run_id)
    assert run['state'] == 'failed'  # explicit offline sentinel stops the first action call
    assert len(model.main_messages) == 1
    assert model.main_messages[0][0]['content'] == agent.system_prompt('plain', task, compact)
    assert agent._action_prompt_variant(model.main_messages[0], compact) in agent.ACTION_VARIANTS + (('plain', 'visual_research', True),)
    assert ('phase_tool_contract' in engine.action_transport_identity()) is (guided_enabled and compact)


@pytest.mark.parametrize('structured_enabled', [False, True])
def test_real_revision_http_transport_advances_only_after_successful_tools(tmp_path, monkeypatch, structured_enabled):
    store = Store(tmp_path)
    # The historical multi-action planner prepares the parent under its original protocol.
    # Enable the new transport only for the revision being tested.
    case, previous, _ = guided.revised_protocol_case(store)
    assert previous['versions']['harness']['guided_workflow'] is False
    assert previous['versions']['harness']['compact_actions'] is False
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    planner = CompactProtocolModel(store)
    model, captured = mocked_local_model(monkeypatch, planner, structured_enabled)
    engine, run_id, _ = guided.start(store, case, model, mode=previous['mode'])
    planner.run_id = run_id
    run = guided.execute(engine, run_id)
    assert run['state'] == 'waiting_evidence', run['error']
    requests = [request for request in captured if request['messages'][0]['content'] != agent.VISION_SYSTEM]
    phases = ['respond_critic_required', 'record_assessment_required', 'record_assessment_required', 'build_opinion_available']
    assert len(requests) == len(phases) == 4
    for request, phase in zip(requests, phases, strict=True):
        assert request['messages'][0]['content'] == agent.system_prompt(previous['mode'], 'visual_research', True, phase)
        if structured_enabled:
            assert request['response_format'] == envelope(agent.action_output_schema(previous['mode'], 'visual_research', True, phase))
    assert run['assessment']['knowledge_citations'] == []  # no unrelated source forced
    assert not [event for event in run['events'] if event['type'] == 'validation_error']
    assert run['model_calls'] == len(requests)+len(planner.vision_ids) <= 12
    assert run['tool_calls'] == len([event for event in run['events'] if event['type'] == 'tool_start']) <= 20
    identity = run['versions']['harness']['action_transport']['phase_tool_contract']
    assert identity['schema_sha256'] == agent.guided_phase_schema_hashes()
    assert identity['budgets_and_repairs'] == 'unchanged'
    assert identity['native_validation'] == 'exact-request-original-schema-not-independent-app-derivation'


def test_provider_ignoring_phase_mask_still_fails_original_consecutive_gate(tmp_path, monkeypatch):
    store = Store(tmp_path)
    case, previous, _ = guided.revised_protocol_case(store)
    assert previous['versions']['harness']['guided_workflow'] is False
    assert previous['versions']['harness']['compact_actions'] is False
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    # Deliberately ignore both phase schemas: verify old host gates, not model quality.
    planner = PhaseScript(store, [recorded, respond, lambda run: tool('build_opinion'),
                                 lambda run: recorded(run, attributed=True)])
    engine, run_id, _ = guided.start(store, case, planner, mode=previous['mode'])
    run = guided.execute(engine, run_id)
    assert run['state'] == 'failed' and run['assessment'] is None
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert [event['repair_allowed'] for event in errors] == [True, True, False]
    assert '需先回应' in errors[0]['detail'] and '请先完成' in errors[1]['detail']
    assert agent.SOURCE_ATTRIBUTION_POLICY in errors[2]['detail']
    assert len(planner.main_messages) == 4 and not planner.steps
    assert run['model_calls'] == 4+len(planner.vision_ids)
    assert run['tool_calls'] == len([event for event in run['events'] if event['type'] == 'tool_start'])


@pytest.mark.parametrize('phase', agent.GUIDED_ACTION_PHASES)
@pytest.mark.parametrize('matching', [False, True], ids=['wrong-phase-hash-fatal', 'matching-original-hash-repair-class'])
def test_native_rejection_matches_exact_phase_schema_usage_without_transport_retry(monkeypatch, phase, matching):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '1')
    calls = []
    usage = {'prompt_tokens': 7, 'completion_tokens': 19, 'total_tokens': 26}
    def reject(request):
        payload = json.loads(request.content)
        calls.append(payload)
        schema = payload['response_format']['json_schema']['schema']
        if not matching:
            other = next(value for value in agent.GUIDED_ACTION_PHASES if value != phase)
            schema = agent.action_output_schema('plain', 'visual_research', True, other)
        return httpx.Response(422, json={'detail': {'type': 'structured_output_validation',
            'schema_sha256': agent.decoder_schema_sha256(schema), 'response_sha256': 'a'*64, 'usage': usage}})
    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(transport=httpx.MockTransport(reject), **kwargs))
    model = agent.LocalModel('http://127.0.0.1:9999/v1', 'OFFLINE-MOCK')
    request = [{'role': 'system', 'content': agent.system_prompt('plain', 'visual_research', True, phase)}]
    failure_type = agent.LocalModelSchemaFailure if matching else agent.LocalModelFailure
    with pytest.raises(failure_type) as failed:
        asyncio.run(model.complete(request, 11))
    assert len(calls) == 1
    if matching:
        assert failed.value.usage == usage
        assert failed.value.schema_sha256 == agent.decoder_schema_sha256(agent.action_output_schema('plain', 'visual_research', True, phase))
        assert set(failed.value.safe_detail()) == {'type', 'schema_sha256', 'response_sha256'}
    else:
        assert not isinstance(failed.value, agent.LocalModelSchemaFailure)
