"""Native rejection protocol and bounded model self-repair; no real inference."""
import asyncio
import json
import time
from copy import deepcopy

import httpx
import pytest

from cizheng import agent
from cizheng.agent import (LocalModel, LocalModelFailure, LocalModelSchemaFailure,
                           _ToolResultMessage)
from cizheng.store import Problem, dump
from test_source_attribution_gate import reader, deliver, opinion, OfflineDelivery


FAILURE_USAGE = {'prompt_tokens': 100, 'completion_tokens': 189, 'total_tokens': 289}


def rejection():
    return LocalModelSchemaFailure(schema_sha256='a' * 64,
                                  response_sha256='b' * 64, usage=FAILURE_USAGE)


def native_detail(payload):
    return {'type': 'structured_output_validation',
            'schema_sha256': agent.decoder_schema_sha256(
                payload['response_format']['json_schema']['schema']),
            'response_sha256': 'b' * 64, 'usage': deepcopy(FAILURE_USAGE)}


@pytest.mark.parametrize('compact', [False, True])
def test_matching_original_schema_rejection_is_typed_and_usage_preserved(monkeypatch, compact):
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '1')
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1' if compact else '0')
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(422, json={'detail': native_detail(payload)})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    model = LocalModel('http://127.0.0.1:8000/v1', 'test')
    with pytest.raises(LocalModelSchemaFailure) as failed:
        asyncio.run(model.complete([{'role': 'system', 'content':
            agent.system_prompt('plain', 'visual_research', compact)}], 3))
    assert len(requests) == 1
    assert failed.value.usage == FAILURE_USAGE and failed.value.status == 422
    assert failed.value.schema_sha256 == native_detail(requests[0])['schema_sha256']
    assert failed.value.response_sha256 == 'b' * 64


@pytest.mark.parametrize('mutation', ['marker', 'schema_sha', 'response_sha', 'uppercase_hash',
    'extra_detail', 'extra_envelope', 'missing_usage', 'negative_usage', 'bool_usage',
    'float_usage', 'inconsistent_total', 'excess_completion', 'extra_usage',
    'wrong_status_500', 'wrong_status_401', 'plain_detail', 'invalid_json',
    'duplicate_marker', 'projected_schema_sha'])
def test_untrusted_or_malformed_rejections_are_fatal_not_repairable(monkeypatch, mutation):
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '1')
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    original = httpx.AsyncClient
    calls = []
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        detail = native_detail(payload)
        body, status = {'detail': detail}, 422
        if mutation == 'marker': detail['type'] = 'gpu_error'
        elif mutation == 'schema_sha': detail['schema_sha256'] = '0' * 64
        elif mutation == 'response_sha': detail['response_sha256'] = 'provider secret'
        elif mutation == 'uppercase_hash': detail['response_sha256'] = 'B' * 64
        elif mutation == 'extra_detail': detail['message'] = 'provider secret'
        elif mutation == 'extra_envelope': body['content'] = 'provider secret'
        elif mutation == 'missing_usage': detail.pop('usage')
        elif mutation == 'negative_usage': detail['usage']['prompt_tokens'] = -1
        elif mutation == 'bool_usage': detail['usage']['prompt_tokens'] = True
        elif mutation == 'float_usage': detail['usage']['prompt_tokens'] = 100.0
        elif mutation == 'inconsistent_total': detail['usage']['total_tokens'] = 1
        elif mutation == 'excess_completion': detail['usage'].update(completion_tokens=2501, total_tokens=2601)
        elif mutation == 'extra_usage': detail['usage']['secret'] = 'provider secret'
        elif mutation.startswith('wrong_status_'): status = int(mutation.rsplit('_', 1)[1])
        elif mutation == 'plain_detail': body['detail'] = 'structured_output_validation provider secret'
        elif mutation == 'invalid_json': return httpx.Response(status, text='provider secret')
        elif mutation == 'duplicate_marker':
            encoded = json.dumps(body).replace('"type": "structured_output_validation"',
                '"type": "gpu_error", "type": "structured_output_validation"')
            return httpx.Response(status, text=encoded)
        elif mutation == 'projected_schema_sha':
            from integrations.spark_transformers.structured_generation import bounded_parser_schema
            projected = bounded_parser_schema(payload['response_format']['json_schema']['schema'])
            detail['schema_sha256'] = agent.decoder_schema_sha256(projected)
            assert detail['schema_sha256'] != native_detail(payload)['schema_sha256']
        return httpx.Response(status, json=body)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    model = LocalModel('http://127.0.0.1:8000/v1', 'test')
    with pytest.raises(LocalModelFailure) as failed:
        asyncio.run(model.complete([{'role': 'system', 'content':
            agent.system_prompt('plain', 'visual_research', True)}], 3))
    assert len(calls) == 1 and failed.value.status == 503
    assert 'provider secret' not in str(failed.value)


@pytest.mark.parametrize('error', [httpx.ConnectError('provider secret'),
    httpx.ReadTimeout('provider secret')])
def test_network_errors_are_never_retried_or_reclassified(monkeypatch, error):
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '1')
    original = httpx.AsyncClient
    calls = []
    def respond(request):
        calls.append(request)
        raise error
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    model = LocalModel('http://127.0.0.1:8000/v1', 'test')
    with pytest.raises(LocalModelFailure) as failed:
        asyncio.run(model.complete([{'role': 'system', 'content': agent.system_prompt('plain')}], 3))
    assert len(calls) == 1
    assert 'provider secret' not in str(failed.value)


@pytest.mark.parametrize('request_kind', ['disabled', 'vision', 'unknown_prompt'])
def test_no_expected_action_response_format_never_classifies_schema_failure(monkeypatch, request_kind):
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '0' if request_kind == 'disabled' else '1')
    original = httpx.AsyncClient
    def respond(request):
        assert 'response_format' not in json.loads(request.content)
        return httpx.Response(422, json={'detail': {'type': 'structured_output_validation',
            'schema_sha256': 'a' * 64, 'response_sha256': 'b' * 64, 'usage': FAILURE_USAGE}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    prompt = (agent.VISION_SYSTEM if request_kind == 'vision' else
              'unknown' if request_kind == 'unknown_prompt' else agent.system_prompt('plain'))
    model = LocalModel('http://127.0.0.1:8000/v1', 'test')
    with pytest.raises(LocalModelFailure):
        asyncio.run(model.complete([{'role': 'system', 'content': prompt}], 3))


class RepairScript(OfflineDelivery):
    def __init__(self, steps):
        self.steps = list(steps)
        self.messages = []

    async def complete(self, messages, timeout):
        self.messages.append(deepcopy(messages))
        if not self.steps:
            pytest.fail('Unexpected additional model call')
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step, {'total_tokens': 11}


def action(tool):
    return dump({'actions': [{'tool': tool, 'arguments': {}}]})


def execute_script(reader, steps, model_calls=0):
    store, engine, run_id, _ = reader
    script = RepairScript(steps)
    engine.model = script
    # Existing original/compact fixture has actual Store lifecycle, case image
    # and a recorded supplement request. Only its synthetic assessment is seeded.
    store.update_run(run_id, lambda run: run.update(
        state='queued', assessment=opinion(), model_calls=model_calls))
    asyncio.run(engine.execute(run_id))
    return store.read('run', run_id), script


def model_events(run):
    return [event for event in run['events'] if event['type'] == 'model']


def test_schema_rejection_gets_one_model_self_repair_and_retains_cost(reader):
    run, model = execute_script(reader, [rejection(), action('build_opinion')])
    assert run['state'] == 'waiting_evidence' and run['model_calls'] == 2
    events = model_events(run)
    assert [event['outcome'] for event in events] == ['failed', 'succeeded']
    assert events[0]['usage'] == FAILURE_USAGE
    assert sum(event['usage']['total_tokens'] for event in events) == 300
    assert events[0]['structured_failure']['response_sha256'] == 'b' * 64
    assert events[0]['successful_knowledge_body_sha256'] == []
    corrections = [message for message in model.messages[1]
                   if message['role'] == 'user' and isinstance(message['content'], str)
                   and 'structured_output_validation' in message['content']]
    assert len(corrections) == 1 and '仅允许再修正一次' in corrections[0]['content']
    assert all(message['role'] != 'assistant' for message in model.messages[1])


def test_second_consecutive_schema_rejection_stops_without_third_call(reader):
    run, model = execute_script(reader, [rejection(), rejection()])
    assert run['state'] == 'failed' and len(model.messages) == run['model_calls'] == 2
    assert '连续' in run['error']
    events = model_events(run)
    assert sum(event['usage']['total_tokens'] for event in events) == 578
    assert not run.get('main_seen_knowledge_body_sha256')
    validations = [event for event in run['events'] if event['type'] == 'validation_error']
    assert [event['repair_allowed'] for event in validations] == [True, False]


@pytest.mark.parametrize('native_first', [True, False])
def test_native_and_host_contract_failures_share_the_consecutive_repair_limit(reader, native_first):
    steps = [rejection(), action('unregistered')]
    if not native_first: steps.reverse()
    run, model = execute_script(reader, steps)
    assert run['state'] == 'failed' and len(model.messages) == 2
    validations = [event for event in run['events'] if event['type'] == 'validation_error']
    assert [event['repair_allowed'] for event in validations] == [True, False]


def test_successful_complete_plan_resets_only_the_consecutive_repair_allowance(reader):
    run, model = execute_script(reader, [rejection(), action('read_case'),
                                         rejection(), action('build_opinion')])
    assert run['state'] == 'waiting_evidence' and len(model.messages) == run['model_calls'] == 4
    assert [event['outcome'] for event in model_events(run)] == ['failed', 'succeeded', 'failed', 'succeeded']


@pytest.mark.parametrize('error', [LocalModelFailure('generic HTTP error'),
    TimeoutError('synthetic timeout'), RuntimeError('synthetic GPU error'),
    Problem(503, 'synthetic auth error')])
def test_generic_failures_remain_fatal_without_repair(reader, error):
    run, model = execute_script(reader, [error])
    assert run['state'] == 'failed' and len(model.messages) == run['model_calls'] == 1
    assert not [event for event in run['events'] if event['type'] == 'validation_error']


def test_self_repair_does_not_extend_real_model_call_budget(reader):
    run, model = execute_script(reader, [rejection()], model_calls=11)
    assert run['state'] == 'failed' and run['model_calls'] == 12
    assert len(model.messages) == 1 and '预算' in run['error']
    assert model_events(run)[0]['usage'] == FAILURE_USAGE


def test_self_repair_does_not_extend_real_elapsed_budget(reader):
    store, engine, run_id, _ = reader
    class Expired(RepairScript):
        async def complete(self, messages, timeout):
            store.update_run(run_id, lambda run: run.update(started_at=time.time() - 301))
            return await super().complete(messages, timeout)
    model = Expired([rejection()])
    engine.model = model
    store.update_run(run_id, lambda run: run.update(state='queued'))
    asyncio.run(engine.execute(run_id))
    run = store.read('run', run_id)
    assert run['state'] == 'failed' and len(model.messages) == run['model_calls'] == 1
    assert '预算' in run['error'] and model_events(run)[0]['usage'] == FAILURE_USAGE
    assert not run.get('main_seen_knowledge_body_sha256')


def test_typed_failure_never_grants_knowledge_body_or_compact_delivery_proof(reader):
    store, _, run_id, result = reader
    failed = RepairScript([rejection()])
    with pytest.raises(LocalModelSchemaFailure):
        deliver(reader, _ToolResultMessage('read_knowledge', result), failed)
    run = store.read('run', run_id)
    assert run['model_calls'] == 1
    for field in ('main_seen_knowledge_receipt_sha256', 'main_seen_knowledge_body_sha256',
                  'compact_seen_read_indexes'):
        assert not run.get(field)
    event = model_events(run)[-1]
    assert event['usage'] == FAILURE_USAGE and event['outcome'] == 'failed'
    assert event['successful_knowledge_receipt_sha256'] == event['successful_knowledge_body_sha256'] == []
    if 'successful_compact_read_indexes' in event:
        assert event['successful_compact_read_indexes'] == []
