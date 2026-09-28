"""One-shot JSON transport, paid failures and exact approved text; no provider calls."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from cizheng import review_client, schemas as S
from cizheng.review_client import CriticFailure, ReviewService, StepFunClient, prepare_review
from cizheng.store import Problem, dump, uid
from test_runtime_v3 import review_case

HTTP_CLIENT = httpx.AsyncClient
USAGE = {'prompt_tokens': 793, 'completion_tokens': 2500, 'total_tokens': 3293}
SECRET = 'SYNTHETIC-secret-response-not-for-diagnostics'
KEY = 'SYNTHETIC-offline-key-not-for-diagnostics'
MISSING = object()


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Only explicit MockTransport may construct a provider client')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY', KEY)
    monkeypatch.setenv('CIZHENG_STEPFUN_MODEL', 'SYNTHETIC-JSON-TRANSPORT')
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', 'https://api.stepfun.com/v1')
    monkeypatch.delenv('CIZHENG_GUIDED_WORKFLOW', raising=False)
    monkeypatch.delenv('CIZHENG_COMPACT_ACTIONS', raising=False)


def critic():
    return {'issues': [{'claim_dimension': 'general', 'concern': '合成依据不足', 'reference_ids': []}],
            'suggested_evidence': '合成补证', 'limitations': ['未查看原图，仅软件测试']}


def packet():
    return {'question': '合成文字审查', 'claims': [], 'observations': [],
            'references': [{'reference_id': 'SYNTHETIC-PUBLIC-REF', 'title': '合成来源',
                            'locator': '合成定位', 'excerpt': '合成已批准文字'}]}


def envelope(content=None, finish='stop'):
    choice = {'message': {'content': dump(critic()) if content is None else content}}
    if finish is not MISSING:
        choice['finish_reason'] = finish
    return {'choices': [choice], 'usage': deepcopy(USAGE)}


def mocked(monkeypatch, responder):
    calls, options = [], []
    def respond(request):
        calls.append(request)
        return responder(request)
    def client(**kwargs):
        options.append(deepcopy(kwargs))
        return HTTP_CLIENT(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    return StepFunClient(), calls, options


def run_review(client, payload=None):
    return asyncio.run(client.review(packet() if payload is None else payload, timeout=17))


def assert_safe_failure(failure, category, stage, usage=USAGE):
    assert failure.status == 503 and failure.usage == usage
    assert failure.diagnostic['category'] == category and failure.diagnostic['stage'] == stage
    saved = dump({'message': failure.message, 'usage': failure.usage, 'diagnostic': failure.diagnostic})
    assert SECRET not in saved and KEY not in saved and 'Authorization' not in saved


@pytest.mark.parametrize('endpoint', ['https://api.stepfun.com/v1', 'https://api.stepfun.ai/v1',
                                     'https://api.stepfun.com/step_plan/v1'])
def test_json_object_request_preserves_exact_packet_budget_and_existing_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', endpoint)
    value = packet()
    before = deepcopy(value)
    client, calls, options = mocked(monkeypatch, lambda request: httpx.Response(200, json=envelope()))
    result, usage = run_review(client, value)
    assert result == critic() and usage == USAGE and value == before
    assert len(calls) == 1 and str(calls[0].url) == endpoint + '/chat/completions'
    body = json.loads(calls[0].content)
    assert set(body) == {'model', 'temperature', 'max_tokens', 'response_format', 'messages'}
    assert body['response_format'] == {'type': 'json_object'}
    assert body['max_tokens'] == 2500 and body['temperature'] == 0.1
    assert body['messages'] == [{'role': 'system', 'content': review_client.SYSTEM},
                                {'role': 'user', 'content': dump(value)}]
    assert json.loads(body['messages'][1]['content']) == value
    assert set(value) == {'question', 'claims', 'observations', 'references'}
    assert 'json_schema' not in body and 'chat_template_kwargs' not in body and 'thinking' not in body
    assert options == [{'trust_env': False, 'follow_redirects': False, 'timeout': 17}]


@pytest.mark.parametrize('content', [dump(critic()), '{"issues":['])
def test_explicit_length_rejects_valid_json_and_eof_before_schema_parse(monkeypatch, content):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200,
        json=envelope(content, 'length'), headers={'X-Private-Response': SECRET}))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'response_truncated', 'provider_finish_reason')
    assert failed.value.diagnostic == {'stage': 'provider_finish_reason',
        'category': 'response_truncated', 'error_type': 'ValueError'}


@pytest.mark.parametrize('finish', ['content_filter', 'tool_calls', 'function_call', SECRET, '', False,
                                  {'untrusted': SECRET}])
def test_explicit_nonstop_is_safely_classified_without_retry_or_provider_prose(monkeypatch, finish):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, json=envelope(SECRET, finish)))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'response_finish_reason_invalid', 'provider_finish_reason')


@pytest.mark.parametrize('finish', [MISSING, None])
def test_missing_finish_remains_compatible_and_is_disclosed_as_not_verified(monkeypatch, finish):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, json=envelope(finish=finish)))
    result, usage = run_review(client)
    assert result == critic() and usage == USAGE and len(calls) == 1
    generation = client.identity()['generation']
    assert generation['finish_reason_policy'] == 'reject-explicit-nonstop-missing-not-verified'
    assert generation['automatic_retry'] is False
    assert generation['response_format'] == {'type': 'json_object'} and generation['max_tokens'] == 2500


@pytest.mark.parametrize('content', ['{"issues":[', SECRET])
def test_stop_with_invalid_json_is_schema_failure_not_inferred_token_truncation(monkeypatch, content):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, json=envelope(content, 'stop')))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'response_schema_invalid', 'critic_response_schema')
    assert 'json_invalid' in failed.value.diagnostic['validation_error_types']


@pytest.mark.parametrize('status', [401, 403, 429, 500, 307])
def test_http_failures_are_fatal_once_without_leaking_body_headers_or_inventing_usage(monkeypatch, status):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(status, text=SECRET,
        headers={'Location': 'https://example.invalid/unapproved', 'X-Private-Response': SECRET}))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'http_status_error', 'provider_request', usage={})
    assert failed.value.diagnostic['http_status'] == status


@pytest.mark.parametrize('failure', [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failures_do_not_retry_or_fabricate_token_usage(monkeypatch, failure):
    def respond(request):
        raise failure(SECRET, request=request)
    client, calls, _ = mocked(monkeypatch, respond)
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'transport_error', 'provider_request', usage={})


@pytest.mark.parametrize('shape', ['no_choices', 'empty_choices', 'missing_message'])
def test_bad_envelopes_keep_received_usage_and_do_not_expose_response_data(monkeypatch, shape):
    value = envelope()
    if shape == 'no_choices': value.pop('choices')
    elif shape == 'empty_choices': value['choices'] = []
    else: value['choices'][0].pop('message')
    value['private_extra'] = SECRET
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, json=value))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'response_envelope_invalid', 'provider_response_envelope')


def test_nonjson_outer_response_has_safe_classification_and_unknown_usage(monkeypatch):
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, text=SECRET))
    with pytest.raises(CriticFailure) as failed:
        run_review(client)
    assert len(calls) == 1
    assert_safe_failure(failed.value, 'response_json_invalid', 'provider_response_json', usage={})


def test_prompt_compactness_is_instruction_only_and_does_not_narrow_business_schema(monkeypatch):
    assert '一个完整JSON对象' in review_client.SYSTEM and '不输出思维链' in review_client.SYSTEM
    assert 'issues最多3项' in review_client.SYSTEM and 'concern最多100字' in review_client.SYSTEM
    assert 'suggested_evidence最多160字' in review_client.SYSTEM
    assert 'limitations最多3项，每项最多80字' in review_client.SYSTEM
    value = critic()
    value['issues'] *= 4
    value['issues'][0]['concern'] = '测' * 101
    value['suggested_evidence'] = '测' * 161
    value['limitations'] = ['测' * 81] * 4
    expected = S.CriticResponse.model_validate(value).model_dump()
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200, json=envelope(dump(value))))
    result, usage = run_review(client)
    assert len(calls) == 1 and result == expected and usage == USAGE
    assert client.identity()['generation']['prompt_limits'] == {
        'issues': 3, 'concern_chars': 100, 'suggested_evidence_chars': 160,
        'limitations': 3, 'limitation_chars': 80}


def test_real_service_keeps_exact_approval_packet_and_paid_truncation_cannot_be_reissued(tmp_path, monkeypatch):
    store, case, run, body = review_case(tmp_path)
    approved = prepare_review(store, case['id'], body)
    packet_before = deepcopy(approved['payload'])
    client, calls, _ = mocked(monkeypatch, lambda request: httpx.Response(200,
        json=envelope(dump(critic()), 'length')))
    service = ReviewService(store, client)
    request = {'request_id': uid('req'), 'packet_hash': approved['packet_hash']}
    result = asyncio.run(service.execute(approved['id'], request))
    assert result['state'] == 'failed' and result['result'] is None
    assert result['usage'] == USAGE and result['error_diagnostic']['category'] == 'response_truncated'
    assert result['packet_hash'] == approved['packet_hash'] and result['payload'] == packet_before
    provider_packet = json.loads(json.loads(calls[0].content)['messages'][1]['content'])
    assert provider_packet == packet_before
    assert set(provider_packet) == {'question', 'claims', 'observations', 'references'}
    assert all(key not in provider_packet for key in ('permission', 'approval_basis', 'request_id',
        'assessment_run_id', 'packet_hash', 'knowledge_reference_bindings', 'snapshot', 'case', 'image_url'))
    episode = store.read('episode', case['episode_id'])
    assert episode['model_calls'] == run['model_calls'] + 1 and episode['text_review_calls'] == 1
    assert episode['seconds'] >= result['elapsed'] >= 0
    assert KEY not in dump(result) and SECRET not in dump(result)
    # An idempotent read of the same execution returns its failure, not another provider call.
    assert asyncio.run(service.execute(approved['id'], request)) == result
    with pytest.raises(Problem, match='不重复'):
        asyncio.run(service.execute(approved['id'], {'request_id': uid('req'), 'packet_hash': approved['packet_hash']}))
    second = prepare_review(store, case['id'], dict(body, request_id=uid('req')))
    with pytest.raises(Problem, match='一次文字审查'):
        asyncio.run(service.execute(second['id'], {'request_id': uid('req'), 'packet_hash': second['packet_hash']}))
    assert len(calls) == 1 and store.read('episode', case['episode_id'])['text_review_calls'] == 1
