"""Synthetic receipt, approval and error contracts; no external model or truth proof."""
import asyncio
import hashlib
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from cizheng import schemas as S
from cizheng.agent import Engine, VISION_SYSTEM
from cizheng.knowledge import KnowledgeStore
from cizheng.review_client import ReviewService, StepFunClient, prepare_review, suggested_packet
from cizheng.store import Problem, Store, digest, dump, uid
from test_closed_loop import ScriptedModel, add_photo, add_ref, create_case, run_case
from test_runtime_v3 import CriticFixture, review_case

HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def no_external_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Only explicit MockTransport may construct a provider client')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    for name in ('CIZHENG_GUIDED_WORKFLOW', 'CIZHENG_COMPACT_ACTIONS'):
        monkeypatch.delenv(name, raising=False)


class KnowledgePlanner(ScriptedModel):
    def __init__(self, source, chunks):
        self.source, self.chunks = source, chunks

    async def complete(self, messages, timeout):
        if messages[0]['content'] == VISION_SYSTEM:
            return await super().complete(messages, timeout)
        results = [json.loads(message['content'].split('：', 1)[1]) for message in messages
                   if isinstance(message['content'], str)
                   and message['content'].startswith('工具结果（数据）：')]
        if any(result['tool'] == 'read_case' for result in results):
            reads = [result['result'] for result in results if result['tool'] == 'read_knowledge']
            if len(reads) < len(self.chunks):
                return dump({'actions': [{'tool': 'read_knowledge', 'arguments': {
                    'document_id': self.source['document_id'],
                    'chunk_id': self.chunks[len(reads)]['chunk_id']}}]}), {}
        else:
            reads = []
        raw, usage = await super().complete(messages, timeout)
        plan = json.loads(raw)
        for action in plan['actions']:
            if action['tool'] == 'record_assessment':
                chunk = reads[0]['chunks'][0]
                action['arguments']['knowledge_citations'] = [{key: chunk[key] for key in (
                    'document_id', 'document_revision', 'document_sha256', 'chunk_id',
                    'chunk_sha256', 'locator')} | {'use': 'source_context',
                        'relevance': '合成来源上下文；不支持文物归属'}]
                action['arguments']['reference_comparison'] = '依据资料作合成来源上下文，不作归属判断'
        return dump(plan), usage


@pytest.fixture
def knowledge_case(tmp_path):
    store = Store(tmp_path)
    case = add_photo(store, create_case(store))
    add_ref(store)
    source = KnowledgeStore(store.root).add_document({
        'title': '合成知识固定段落', 'institution': '合成机构', 'rights': 'authorized_text',
        'rights_note': '仅本测试原创，非默认外发授权', 'locator': '合成出处1',
        'chunks': [{'text': '合成已读正文：只验证阅读与批准合同，不提供文物判断。', 'locator': '第一段'},
                   {'text': '已读但未被意见引用的第二段，不得默认进入外发预览。', 'locator': '第二段'}]})['source']
    case = store.link_document(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'document_id': source['document_id'],
        'document_revision': source['revision'], 'document_sha256': source['document_sha256']})
    chunks = KnowledgeStore(store.root).source(source['document_id'], source['revision'])['chunks']
    run = run_case(store, case, KnowledgePlanner(source, chunks))
    assert run['state'] == 'waiting_evidence', run.get('error')
    assert len(run['read_knowledge']) == 2
    case = store.read('case', case['id'])
    packet = suggested_packet(store, case['id'])
    packet.pop('notice')
    packet.update(request_id=uid('req'), expected_case_revision=case['revision'],
                  permission='public', approval_basis='SYNTHETIC explicit approval of this exact text packet')
    return store, case, run, S.ReviewPacketIn.model_validate(packet).model_dump(), source


def knowledge_ref(fixture):
    _, _, run, body, _ = fixture
    identifier = run['assessment']['knowledge_citations'][0]['chunk_id']
    return next(reference for reference in body['references'] if reference['reference_id'] == identifier)


def test_preview_only_selects_delivered_cited_body_and_preserves_four_fields(knowledge_case):
    store, case, run, body, _ = knowledge_case
    selected = knowledge_ref(knowledge_case)
    assert selected['excerpt'] == run['read_knowledge'][0]['text']
    assert set(selected) == {'reference_id', 'title', 'locator', 'excerpt'}
    assert run['read_knowledge'][1]['chunk_id'] not in {item['reference_id'] for item in body['references']}
    assert len(body['references']) == 2  # one visual record and one selected text paragraph
    assert store.listing('text_review') == []  # local reading permission sends nothing
    record = prepare_review(store, case['id'], body)
    assert set(record['payload']) == {'question', 'claims', 'observations', 'references'}
    binding = record['knowledge_reference_bindings'][selected['reference_id']]
    assert binding['document_sha256'] == run['assessment']['knowledge_citations'][0]['document_sha256']
    assert binding['read_text_sha256'] == hashlib.sha256(selected['excerpt'].encode()).hexdigest()
    assert 'knowledge_reference_bindings' not in record['payload']
    assert 'image_url' not in dump(record['payload']) and 'image_base64' not in dump(record['payload'])


def test_approval_can_omit_knowledge_without_host_adding_it_back(knowledge_case):
    store, case, _, body, _ = knowledge_case
    identifier = knowledge_ref(knowledge_case)['reference_id']
    body['references'] = [item for item in body['references'] if item['reference_id'] != identifier]
    record = prepare_review(store, case['id'], body)
    assert record['payload']['references'] == body['references']
    assert record['knowledge_reference_bindings'] == {}


def test_explicit_redacted_approval_accepts_only_contiguous_read_text(knowledge_case):
    store, case, _, body, _ = knowledge_case
    reference = knowledge_ref(knowledge_case)
    original = reference['excerpt']
    reference['excerpt'] = original[2:16]
    body['permission'] = 'approved_redacted'
    record = prepare_review(store, case['id'], body)
    binding = record['knowledge_reference_bindings'][reference['reference_id']]
    assert record['payload']['references'] == body['references']
    assert binding['read_text_sha256'] == hashlib.sha256(original.encode()).hexdigest()
    assert binding['approved_excerpt_sha256'] == hashlib.sha256(original[2:16].encode()).hexdigest()


@pytest.mark.parametrize('change', ['title', 'locator', 'rewrite', 'public_partial', 'unselected', 'duplicate'])
def test_approval_rejects_changed_unselected_or_duplicate_knowledge(knowledge_case, change):
    store, case, run, body, _ = knowledge_case
    reference = knowledge_ref(knowledge_case)
    if change in ('title', 'locator'):
        reference[change] += '改写'
    elif change == 'rewrite':
        body['permission'] = 'approved_redacted'
        reference['excerpt'] = '并非原文的伪造陈述'
    elif change == 'public_partial':
        reference['excerpt'] = reference['excerpt'][2:16]
    elif change == 'unselected':
        reference['reference_id'] = run['read_knowledge'][1]['chunk_id']
    else:
        body['references'].append(deepcopy(reference))
    with pytest.raises(Problem, match='知识|唯一'):
        prepare_review(store, case['id'], body)
    assert store.listing('text_review') == []


@pytest.mark.parametrize('change', ['undelivered', 'old_run', 'wrong_hash', 'metadata', 'unbound', 'snapshot'])
def test_preview_fails_closed_for_invalid_read_version_permission_or_delivery(knowledge_case, change):
    store, case, run, _, _ = knowledge_case
    def mutate(value):
        if change == 'undelivered':
            value['main_seen_knowledge_receipt_sha256'] = []
        elif change == 'old_run':
            value['read_knowledge'][0]['run_id'] = 'SYNTHETIC-old-run'
        elif change == 'wrong_hash':
            value['assessment']['knowledge_citations'][0]['chunk_sha256'] = '0' * 64
        elif change == 'metadata':
            value['read_knowledge'][0]['content_kind'] = 'metadata'
        elif change == 'unbound':
            value['snapshot']['knowledge_links'] = []
        else:
            value['knowledge_snapshot']['sources'][0]['source']['title'] += '篡改'
    store.update_run(run['id'], mutate)
    with pytest.raises(Problem):
        suggested_packet(store, case['id'])
    assert store.listing('text_review') == []


def test_preview_keeps_frozen_body_after_library_revision(knowledge_case):
    store, case, _, body, source = knowledge_case
    original = knowledge_ref(knowledge_case)
    KnowledgeStore(store.root).add_document({'document_id': source['document_id'], 'expected_revision': source['revision'],
        'title': '合成新版本', 'rights': 'authorized_text', 'rights_note': '测试原创', 'text': '新版本不应替换已批准的旧正文'})
    packet = suggested_packet(store, case['id'])
    assert original in packet['references']
    assert all(reference['excerpt'] != '新版本不应替换已批准的旧正文' for reference in packet['references'])
    assert prepare_review(store, case['id'], body)['payload']['references'] == body['references']


def test_read_permission_is_not_default_outbound_approval(knowledge_case):
    store, case, _, body, _ = knowledge_case
    body.pop('permission')
    with pytest.raises(ValidationError):
        S.ReviewPacketIn.model_validate(body)
    assert store.listing('text_review') == []


@pytest.mark.parametrize('known', [True, False])
def test_critic_reference_guard_does_not_repair_unknown_ids_and_preserves_paid_cost(knowledge_case, known):
    store, case, run, body, _ = knowledge_case
    packet = prepare_review(store, case['id'], body)
    reference = knowledge_ref(knowledge_case)['reference_id']
    class Critic(CriticFixture):
        async def review(self, payload, timeout):
            result, usage = await super().review(payload, timeout)
            result['issues'][0]['reference_ids'] = [reference if known else 'SYNTHETIC-unknown-secret-identifier']
            return result, usage
    critic = Critic()
    request = {'request_id': uid('req'), 'packet_hash': packet['packet_hash']}
    result = asyncio.run(ReviewService(store, critic).execute(packet['id'], request))
    assert result['state'] == ('succeeded' if known else 'failed')
    assert result['usage']['total_tokens'] == 83
    assert store.read('episode', case['episode_id'])['model_calls'] == run['model_calls'] + 1
    if known:
        assert result['result']['issues'][0]['reference_ids'] == [reference]
        assert result['error_diagnostic'] is None
    else:
        assert result['result'] is None
        diagnostic = result['error_diagnostic']
        assert diagnostic == {'stage': 'allowed_reference_ids', 'category': 'unknown_reference_ids',
                              'error_type': 'ValueError', 'allowed_reference_count': 2,
                              'unknown_reference_count': 1, 'issue_indexes': [0]}
        assert 'SYNTHETIC-unknown-secret-identifier' not in dump(result)
    assert asyncio.run(ReviewService(store, critic).execute(packet['id'], request))['state'] == result['state']
    assert critic.calls == 1


@pytest.mark.parametrize('failure,category,stage', [
    ('schema', 'response_schema_invalid', 'critic_response_schema'),
    ('envelope', 'response_envelope_invalid', 'provider_response_envelope'),
    ('content', 'response_content_invalid', 'provider_content'),
    ('json', 'response_json_invalid', 'provider_response_json'),
    ('http', 'http_status_error', 'provider_request'),
])
def test_provider_failure_diagnostics_exclude_arbitrary_response_and_keep_usage(tmp_path, monkeypatch,
                                                                             failure, category, stage):
    store, case, _, body = review_case(tmp_path)
    packet = prepare_review(store, case['id'], body)
    secret = 'SYNTHETIC-do-not-retain-response-secret'
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY', 'synthetic-offline-key')
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', 'https://api.stepfun.com/v1')
    def respond(request):
        if failure == 'http':
            return httpx.Response(503, text=secret)
        if failure == 'json':
            return httpx.Response(200, text=secret)
        value = {'usage': {'total_tokens': 37}}
        if failure != 'envelope':
            content = [secret] if failure == 'content' else dump({'issues': secret})
            value['choices'] = [{'message': {'content': content}}]
        return httpx.Response(200, json=value)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(
        transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(ReviewService(store, StepFunClient()).execute(packet['id'],
        {'request_id': uid('req'), 'packet_hash': packet['packet_hash']}))
    assert result['state'] == 'failed' and result['result'] is None
    assert result['error_diagnostic']['category'] == category
    assert result['error_diagnostic']['stage'] == stage
    if failure in ('schema', 'envelope', 'content'):
        assert result['usage']['total_tokens'] == 37
    if failure == 'http':
        assert result['error_diagnostic']['http_status'] == 503
    assert secret not in dump(result) and 'synthetic-offline-key' not in dump(result)
