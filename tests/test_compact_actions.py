"""Offline transport contracts only; no GPU, real model, or ceramic quality.

Real registered tools, store charges, immutable text, and image derivatives run.
HTTP replies and planner judgments below are explicit software test fixtures.
"""
import asyncio
import hashlib
import json
import time
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cizheng import agent, schemas as S
from cizheng.agent import (ACTION_VARIANTS, COMPACT_METADATA_FIELDS, CompactAssessment,
    CompactPlan, Engine, LocalModel, VISION_SYSTEM, action_output_schema,
    _ToolResultMessage, bounded_messages, decoder_schema_sha256, system_prompt, tools_for_mode)
from cizheng.api import create_app
from cizheng.knowledge import KnowledgeStore
from cizheng.review_client import StepFunClient
from cizheng.store import Problem, Store, digest, dump, uid
from test_closed_loop import ScriptedModel, add_ref
from test_critic_revision import SyntheticTextCritic, revised_protocol_case
from test_guided_workflow import (GuidedProtocolModel, add_pinned_text, assessment,
    execute, main_media_ids, new_case, set_counts, start)
from test_knowledge import document

HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch):
    def forbidden_client(*args, **kwargs):
        pytest.fail('Only the explicit HTTP MockTransport may construct a provider client')
    async def forbidden_review(*args, **kwargs):
        pytest.fail('No external text reviewer in transport tests')
    monkeypatch.setattr(agent.httpx, 'AsyncClient', forbidden_client)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_review)
    for key in ('CIZHENG_GUIDED_WORKFLOW', 'CIZHENG_COMPACT_ACTIONS', 'CIZHENG_STRUCTURED_OUTPUTS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('CIZHENG_MODEL_KEY', '')


def short_assessment(run=None, index=None):
    if run is None:
        value = {'basic_info': 'SYNTHETIC transport test', 'scope': 'ceramic_research',
            'claims': [{'dimension': dimension, 'candidate': '未知', 'status': 'insufficient',
                'support': [], 'conflict': [], 'reasoning_summary': '合成测试无文物结论'}
                for dimension in ('period', 'kiln', 'style')],
            'alternatives': ['未核验'], 'condition_hypotheses': [], 'reference_ids': [],
            'reference_comparison': '没有真实图像参照', 'limitations': ['软件协议，不代表模型质量'],
            'revision_explanation': '合成软件测试', 'knowledge_citations': []}
    else:
        value = assessment(run, False)
    if index is not None:
        value['knowledge_citations'] = [{'read_index': index, 'use': 'source_context',
                                         'relevance': '合成固定文本，只检验引用传输'}]
    return value


class CompactProtocolModel(GuidedProtocolModel):
    def __init__(self, store, plans=()):
        super().__init__(store, finish=True)
        self.raw_outputs = []
        self.plans = list(plans)

    async def complete(self, messages, timeout):
        if messages[0]['content'] == VISION_SYSTEM:
            return await super().complete(messages, timeout)
        run = self.store.read('run', self.run_id)
        self.main_messages.append(deepcopy(messages))
        self.main_states.append(deepcopy(run))
        if self.plans:
            result = self.plans.pop(0)
            raw = result if isinstance(result, str) else dump({'actions': result})
        else:
            seen = {observation['media_id'] for observation in run['observations']}
            missing = [media['id'] for media in run['snapshot']['media'] if media['id'] not in seen]
            if missing:
                action = {'tool': 'inspect_images', 'arguments': {
                    'media_ids': missing[:4], 'question': 'SYNTHETIC additional image protocol'}}
            elif run.get('text_review_snapshot') and 'critic_dispositions' not in run:
                action = {'tool': 'respond_critic', 'arguments': {'dispositions': [
                    {'issue_index': index, 'decision': 'unresolved', 'reason': '合成软件回应，不代表专业判断'}
                    for index, _ in enumerate(run['text_review_snapshot']['result']['issues'])]}}
            elif not run['evidence_request']:
                action = {'tool': 'request_evidence', 'arguments': {'view': 'SYNTHETIC missing evidence',
                    'reason': 'No ceramic identification', 'distinguishes': 'Protocol transition only',
                    'capture_instructions': 'No real capture required'}}
            elif not run['assessment']:
                reads = [read for read in run.get('read_knowledge', []) if 'read_index' in read]
                action = {'tool': 'record_assessment', 'arguments': short_assessment(
                    run, reads[0]['read_index'] if reads else None)}
            else:
                action = {'tool': 'build_opinion', 'arguments': {}}
            raw = dump({'actions': [action]})
        self.raw_outputs.append(raw)
        return raw, {'finish_reason': 'stop', 'completion_tokens': 1}


def mocked_local_model(monkeypatch, fixture, structured):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', str(int(structured)))
    captured = []

    async def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        raw, usage = await fixture.complete(payload['messages'], 5)
        return httpx.Response(200, json={'choices': [{'message': {'content': raw},
            'finish_reason': usage.get('finish_reason', 'stop')}], 'usage': usage})

    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: HTTP_CLIENT(
        transport=httpx.MockTransport(respond), **kwargs))
    return LocalModel('http://127.0.0.1:9999/v1', 'OFFLINE-MOCK-TRANSPORT'), captured


def active_reader(tmp_path, monkeypatch, mode='plain'):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    case, source = add_pinned_text(store, new_case(store))
    engine, run_id, _ = start(store, case, mode=mode, active=True)
    chunks = KnowledgeStore(store.root).source(source['document_id'], 1)['chunks']
    return store, engine, run_id, case, source, chunks


def read(engine, run_id, source, chunk):
    engine.store.charge(run_id, 'tool_calls')
    return asyncio.run(engine.tool(run_id, 'read_knowledge', S.ReadKnowledge(
        document_id=source['document_id'], chunk_id=chunk['chunk_id'])))


class DeliveryProtocolModel(ScriptedModel):
    async def complete(self, messages, timeout):
        return dump({'actions': [{'tool': 'read_case', 'arguments': {}}]}), {}


def deliver(engine, run_id, *messages):
    run = engine.store.read('run', run_id)
    engine.model = DeliveryProtocolModel()
    request = [{'role': 'system', 'content': system_prompt(run['mode'], run['research_task'], True)},
               {'role': 'user', 'content': 'SYNTHETIC canonical body delivery'}, *messages]
    asyncio.run(engine.call(run_id, request, 'action'))


def inventory_from_messages(messages):
    content = messages[1]['content']
    text = content[0]['text'] if isinstance(content, list) else content
    line = text.split('\n', 1)[0]
    assert line.startswith('本轮有资格编号（请求前；仅元数据，不替你选择证据）：')
    return json.loads(line.split('：', 1)[1])


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('mode', ['plain', 'skills'])
def test_real_guided_tools_http_transport_and_final_contract_preserve_all_opinions(tmp_path, monkeypatch, structured, mode):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case, _ = add_pinned_text(store, new_case(store, count=2))
    fixture = CompactProtocolModel(store)
    model, captured = mocked_local_model(monkeypatch, fixture, structured)
    engine, run_id, _ = start(store, case, model, mode=mode)
    fixture.run_id = run_id
    run = execute(engine, run_id)
    assert run['state'] == 'waiting_evidence', run['error']
    assert run['model_calls'] == 4  # one vision + three single action requests
    assert run['tool_calls'] == (11 if mode == 'skills' else 8)
    assert fixture.vision_ids == [[media['id'] for media in case['media']]]
    assert set(run['main_seen_media_ids']) == {media['id'] for media in case['media']}
    actions = [payload for payload in captured if payload['messages'][0]['content'] != VISION_SYSTEM]
    assert len(actions) == 3 and all(payload['max_tokens'] == 2500 for payload in actions)
    assert captured[0]['max_tokens'] == 800 and 'response_format' not in captured[0]
    for payload in actions:
        assert payload['messages'][0]['content'] == system_prompt(mode, 'visual_research', True)
        if structured:
            body_schema = payload['response_format']['json_schema']['schema']
            assert body_schema == action_output_schema(mode, 'visual_research', True)
            assert decoder_schema_sha256(body_schema) == run['versions']['harness']['action_transport']['decoder_schema_sha256'][mode+'/visual_research']
        else:
            assert 'response_format' not in payload
    inventories = [inventory_from_messages(payload['messages']) for payload in actions]
    assert inventories[0]['knowledge_read_indexes'] == []  # no prior successful body delivery
    actually_delivered = sorted(receipt['read_index'] for receipt in run['read_knowledge'])
    assert len(actually_delivered) == 2  # this fixture has two coordinator-prefetched paragraphs
    assert all(value['knowledge_read_indexes'] == actually_delivered for value in inventories[1:])
    assert all(value['reference_ids'] == [] for value in inventories)
    assert all(set(value['observation_ids']) == {obs['id'] for obs in run['observations']}
               for value in inventories)
    assert all('loaded_skills' not in value for value in inventories)
    record_raw = next(raw for raw in fixture.raw_outputs if 'record_assessment' in raw)
    raw_args = json.loads(record_raw)['actions'][0]['arguments']
    final = run['assessment']
    assert {key: value for key, value in final.items() if key != 'knowledge_citations'} == {
        key: value for key, value in raw_args.items() if key != 'knowledge_citations'}
    chosen = raw_args['knowledge_citations'][0]
    receipt = next(read for read in run['read_knowledge'] if read['read_index'] == chosen['read_index'])
    assert final['knowledge_citations'] == [{key: receipt[key] for key in COMPACT_METADATA_FIELDS} |
        {'use': chosen['use'], 'relevance': chosen['relevance']}]
    S.Assessment.model_validate(final)
    event = next(event for event in run['events'] if event['type'] == 'transport_expansion')
    assert event['metadata_only'] and event['raw_model_output_sha256'] == hashlib.sha256(record_raw.encode()).hexdigest()
    assert event['expanded_arguments_sha256'] == digest(final)
    assert any(e['type'] == 'model' and e['output_hash'] == event['raw_model_output_sha256'] for e in run['events'])
    assert 'read_index' not in final['knowledge_citations'][0]
    assert run['versions']['harness']['compact_actions'] is True


def test_read_indexes_are_atomic_append_only_and_duplicate_reading_is_charged(tmp_path, monkeypatch):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    results = [read(engine, run_id, source, chunks[index]) for index in (0, 0, 1)]
    deliver(engine, run_id, *[_ToolResultMessage('read_knowledge', result) for result in results])
    run = store.read('run', run_id)
    assert [result['chunks'][0]['read_index'] for result in results] == [1, 2, 3]
    assert [receipt['read_index'] for receipt in run['read_knowledge']] == [1, 2, 3]
    assert run['tool_calls'] == 3 and all(receipt['run_id'] == run_id for receipt in run['read_knowledge'])
    for index in (1, 2, 3):
        expanded, _ = engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=index)))
        assert expanded['knowledge_citations'][0]['chunk_id'] == run['read_knowledge'][index-1]['chunk_id']
    assert run['read_knowledge'][0]['chunk_id'] == run['read_knowledge'][1]['chunk_id']
    assert run['compact_seen_read_indexes'] == [1, 2, 3]


def test_compacted_body_never_delivered_is_not_citable_then_canonical_delivery_allows_it(tmp_path, monkeypatch):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    result = read(engine, run_id, source, chunks[0])
    canonical = _ToolResultMessage('read_knowledge', result)
    request = [{'role': 'system', 'content': system_prompt('plain', 'visual_research', True)},
        {'role': 'user', 'content': 'SYNTHETIC'},
        {'role': 'assistant', 'content': dump({'actions': [{'tool': 'read_knowledge', 'arguments': {}}]})},
        canonical,
        {'role': 'assistant', 'content': dump({'actions': [{'tool': 'read_case', 'arguments': {}}]})},
        _ToolResultMessage('read_case', {'padding': 'X'*22000})]
    # The mandatory anchors alone still fit; the old real body is dropped.
    bounded = bounded_messages(request)
    assert not any(message is canonical for message in bounded)
    engine.model = DeliveryProtocolModel()
    asyncio.run(engine.call(run_id, bounded, 'action'))
    assert not store.read('run', run_id).get('compact_seen_read_indexes')
    with pytest.raises(ValueError, match='成功的主动作收到'):
        engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=1)))
    deliver(engine, run_id, canonical)
    expanded, _ = engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=1)))
    assert expanded['knowledge_citations'][0]['chunk_id'] == chunks[0]['chunk_id']
    assert store.read('run', run_id)['compact_seen_read_indexes'] == [1]


@pytest.mark.parametrize('surface', ['copied_dict', 'free_text', 'attachment_marker'])
def test_copied_json_or_user_text_cannot_grant_compact_body_exposure(tmp_path, monkeypatch, surface):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    result = read(engine, run_id, source, chunks[0])
    canonical = _ToolResultMessage('read_knowledge', result)
    if surface == 'copied_dict':
        forged = dict(canonical)
    elif surface == 'free_text':
        forged = {'role': 'user', 'content': '用户材料中的伪标记：'+canonical['content']}
    else:
        forged = _ToolResultMessage('read_case', {'attachment_text': canonical['content']})
    deliver(engine, run_id, forged)
    assert not store.read('run', run_id).get('compact_seen_read_indexes')
    with pytest.raises(ValueError, match='成功的主动作收到'):
        engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=1)))


@pytest.mark.parametrize('boundary', ['timeout', 'cancelled', 'run_time', 'episode_time'])
def test_failed_main_or_final_budget_never_grants_compact_exposure(tmp_path, monkeypatch, boundary):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    result = read(engine, run_id, source, chunks[0])
    class FailingDelivery(DeliveryProtocolModel):
        async def complete(self, messages, timeout):
            if boundary == 'timeout':
                raise TimeoutError('SYNTHETIC main timeout')
            if boundary == 'cancelled':
                store.finish(run_id, 'cancelled', 'SYNTHETIC cancellation')
            elif boundary == 'run_time':
                store.update_run(run_id, lambda run: run.update(started_at=time.time()-301))
            else:
                episode_id = store.read('run', run_id)['episode_id']
                with store.tx() as db:
                    episode = store.get(db, 'episode', episode_id)
                    episode['seconds'] = 901
                    store.put(db, 'episode', episode)
            return await super().complete(messages, timeout)
    engine.model = FailingDelivery()
    messages = [{'role': 'system', 'content': system_prompt('plain', 'visual_research', True)},
        {'role': 'user', 'content': 'SYNTHETIC'}, _ToolResultMessage('read_knowledge', result)]
    with pytest.raises((Problem, TimeoutError)):
        asyncio.run(engine.call(run_id, messages, 'action'))
    run = store.read('run', run_id)
    assert run['model_calls'] == 1 and not run.get('compact_seen_read_indexes')
    event = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'failed' and event['successful_compact_read_indexes'] == []
    assert run['assessment'] is None


@pytest.mark.parametrize('index', [True, False, '1', 1.0, None, 0, -1])
def test_read_index_is_a_strict_positive_integer(index):
    with pytest.raises(ValidationError):
        CompactAssessment.model_validate(short_assessment(index=index) | {
            'knowledge_citations': [{'read_index': index, 'use': 'method', 'relevance': 'software'}]})


@pytest.mark.parametrize('mutation', ['extra_metadata', 'extra_opinion', 'missing_use', 'too_long'])
def test_compact_rejects_extra_missing_or_long_fields_without_repairing(mutation):
    value = short_assessment(index=1)
    if mutation == 'extra_metadata':
        value['knowledge_citations'][0]['document_id'] = 'untrusted'
    elif mutation == 'extra_opinion':
        value['invented_opinion'] = 'untrusted'
    elif mutation == 'missing_use':
        value['knowledge_citations'][0].pop('use')
    else:
        value['claims'][0]['reasoning_summary'] = '字'*33
    with pytest.raises(ValidationError):
        CompactAssessment.model_validate(value)


def test_unread_or_foreign_receipt_index_cannot_be_expanded(tmp_path, monkeypatch):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    read(engine, run_id, source, chunks[0])
    old = deepcopy(store.read('run', run_id)['read_knowledge'][0])
    with pytest.raises(ValueError, match='不存在'):
        engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=2)))
    other = new_case(store)
    child, child_id, _ = start(store, other, mode='plain', active=True)
    with pytest.raises(ValueError, match='不存在'):
        child.expand_compact_assessment(child_id, CompactAssessment.model_validate(short_assessment(index=1)))
    # A copied parent receipt is still foreign even if its small integer fits.
    store.update_run(child_id, lambda run: run.setdefault('read_knowledge', []).append(old))
    with pytest.raises(ValueError, match='本轮实际读取'):
        child.expand_compact_assessment(child_id, CompactAssessment.model_validate(short_assessment(index=1)))
    assert store.read('run', child_id)['assessment'] is None


@pytest.mark.parametrize('rights', ['unknown', 'public_metadata'])
def test_metadata_returns_no_eligible_index_and_cannot_become_body(tmp_path, monkeypatch, rights):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    # This source must enter the immutable snapshot before the run starts.
    source = KnowledgeStore(store.root).add_document(document(
        title='SYNTHETIC metadata '+rights, source_url='https://example.org/'+rights,
        rights=rights, text=''))['source']
    case = new_case(store)
    engine, run_id, _ = start(store, case, mode='plain', active=True)
    engine.store.charge(run_id, 'tool_calls')
    found = asyncio.run(engine.tool(run_id, 'search_knowledge', S.SearchKnowledge(query=source['title'])))
    chunk_id = next(hit['chunk_id'] for hit in found['results'] if hit['document_id'] == source['document_id'])
    engine.store.charge(run_id, 'tool_calls')
    result = asyncio.run(engine.tool(run_id, 'read_knowledge', S.ReadKnowledge(
        document_id=source['document_id'], chunk_id=chunk_id)))
    assert result['chunks'][0]['content_kind'] == 'metadata'
    assert 'read_index' not in result['chunks'][0]
    receipts = store.read('run', run_id)['read_knowledge']
    assert receipts[0]['content_kind'] == 'metadata' and 'read_index' not in receipts[0]
    with pytest.raises(ValueError, match='不存在'):
        engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=1)))


@pytest.mark.parametrize('corruption', ['empty', 'metadata', 'duplicate'])
def test_invalid_stored_receipts_fail_closed(tmp_path, monkeypatch, corruption):
    store, engine, run_id, _, source, chunks = active_reader(tmp_path, monkeypatch)
    read(engine, run_id, source, chunks[0])
    def change(run):
        receipt = run['read_knowledge'][0]
        if corruption == 'empty':
            receipt['text'] = ' '
        elif corruption == 'metadata':
            receipt['content_kind'] = 'metadata'
        else:
            run['read_knowledge'].append(deepcopy(receipt))
    store.update_run(run_id, change)
    with pytest.raises(ValueError):
        engine.expand_compact_assessment(run_id, CompactAssessment.model_validate(short_assessment(index=1)))


@pytest.mark.parametrize('structured', [False, True])
def test_host_enforces_one_action_even_if_provider_ignores_schema(tmp_path, monkeypatch, structured):
    store = Store(tmp_path)
    bad = [{'tool': 'read_case', 'arguments': {}}]*2
    fixture = CompactProtocolModel(store, plans=[bad, bad])
    model, _ = mocked_local_model(monkeypatch, fixture, structured)
    engine, run_id, _ = start(store, new_case(store), model)
    fixture.run_id = run_id
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and run['model_calls'] == 2 and run['tool_calls'] == 0
    assert run['assessment'] is None
    assert [event['repair_allowed'] for event in run['events'] if event['type'] == 'validation_error'] == [True, False]
    with pytest.raises(ValidationError):
        CompactPlan.model_validate({'actions': bad})


def test_compact_schema_has_real_refs_short_fields_and_unchanged_manual_contract():
    original = deepcopy(S.Assessment.model_json_schema())
    schema = action_output_schema('skills', 'visual_research', True)
    assert schema['properties']['actions']['minItems'] == schema['properties']['actions']['maxItems'] == 1
    branches = schema['properties']['actions']['items']['oneOf']
    assert {b['properties']['tool']['const'] for b in branches} == set(tools_for_mode())
    arguments = next(b['properties']['arguments'] for b in branches if b['properties']['tool']['const'] == 'record_assessment')
    assert arguments['properties']['claims']['minItems'] == arguments['properties']['claims']['maxItems'] == 3
    assert arguments['properties']['knowledge_citations']['maxItems'] == 1
    citation = schema['$defs']['CompactKnowledgeCitation']['properties']
    assert set(citation) == {'read_index', 'use', 'relevance'} and citation['read_index']['type'] == 'integer'
    claim = schema['$defs']['CompactClaim']['properties']
    for key in ('support', 'conflict'):
        assert claim[key] == original['$defs']['Claim']['properties'][key]
    assert arguments['properties']['reference_ids'] == original['properties']['reference_ids']
    assert claim['candidate']['maxLength'] == claim['reasoning_summary']['maxLength'] == 32
    assert schema['$defs']['CompactCriticDisposition']['properties']['reason']['maxLength'] == 32
    assert S.Assessment.model_json_schema() == original
    long_manual = short_assessment()
    long_manual['claims'][0]['reasoning_summary'] = '字'*100
    assert S.Assessment.model_validate(long_manual)
    with pytest.raises(ValidationError):
        CompactAssessment.model_validate(long_manual)


def test_exact_compact_prompt_only_and_legacy_prompt_compatibility(tmp_path, monkeypatch):
    store = Store(tmp_path)
    fixture = CompactProtocolModel(store, plans=[[{'tool': 'read_case', 'arguments': {}}]]*6)
    fixture.run_id = start(store, new_case(store), active=True)[1]
    model, captured = mocked_local_model(monkeypatch, fixture, True)
    compact_prompt = system_prompt('plain', 'visual_research', True)
    messages = [
        [{'role': 'system', 'content': compact_prompt}],
        [{'role': 'system', 'content': 'probe'}, {'role': 'user', 'content': compact_prompt}],
        [{'role': 'user', 'content': compact_prompt}],
        [{'role': 'system', 'content': compact_prompt+'\n'}],
        [{'role': 'system', 'content': system_prompt()}],
        [{'role': 'system', 'content': system_prompt('plain', 'documentary_audit', True)}]]
    for request in messages:
        asyncio.run(model.complete(request, 5))
    assert captured[0]['response_format']['json_schema']['schema'] == action_output_schema('plain', 'visual_research', True)
    assert all('response_format' not in payload for payload in captured[1:4])
    assert captured[4]['response_format']['json_schema']['schema'] == action_output_schema()
    assert captured[5]['response_format']['json_schema']['schema'] == action_output_schema('plain', 'documentary_audit')
    model.compact_actions = False
    asyncio.run(model.complete(messages[0], 5))
    assert 'response_format' not in captured[-1]


@pytest.mark.parametrize('count', [5, 8])
def test_compact_still_requires_all_selected_pixels_in_later_main_round(tmp_path, monkeypatch, count):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store, count=count)
    model = CompactProtocolModel(store)
    engine, run_id, _ = start(store, case, model)
    run = execute(engine, run_id)
    selected = [media['id'] for media in case['media']]
    assert run['state'] == 'waiting_evidence', run['error']
    assert model.vision_ids == [selected[:4], selected[4:]]
    assert set(main_media_ids(model.main_messages[0])) == set(selected[:4])
    assert set(model.main_states[1]['main_seen_media_ids']) == set(selected[:4])
    assert set(run['main_seen_media_ids']) == set(selected) and run['model_calls'] == 6


def test_parent_critic_is_once_complete_short_and_uses_new_observations(tmp_path, monkeypatch):
    store = Store(tmp_path)
    case, parent, review = revised_protocol_case(store)
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    model = CompactProtocolModel(store)
    engine, run_id, _ = start(store, case, model)
    run = execute(engine, run_id)
    assert run['state'] == 'waiting_evidence', run['error']
    assert run['parent_run_id'] == parent['id'] and run['text_review_snapshot']['id'] == review['id']
    assert 'evidence-revise' in run['loaded_skills'] and run['dependencies_reviewed']
    assert len(run['critic_dispositions']) == len(review['result']['issues'])
    assert all(len(value['reason']) <= 32 for value in run['critic_dispositions'])
    responses = [raw for raw in model.raw_outputs if 'respond_critic' in raw]
    assert len(responses) == 1
    assert json.loads(responses[0])['actions'][0]['arguments']['dispositions'] == run['critic_dispositions']
    assert {obs['id'] for obs in run['observations']}.isdisjoint(obs['id'] for obs in parent['observations'])
    assert main_media_ids(model.main_messages[0]) and run['model_calls'] == 5


def test_repairs_are_still_bounded_by_twelve_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    plans = [value for _ in range(6) for value in ('{"actions":[', [{'tool': 'read_case', 'arguments': {}}])]
    model = CompactProtocolModel(store, plans=plans)
    engine, run_id, _ = start(store, new_case(store), model)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '预算耗尽' in run['error']
    assert run['model_calls'] == 12 and run['tool_calls'] == 6
    assert store.read('episode', run['episode_id'])['model_calls'] == 12
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert len(errors) == 6 and all(event['repair_allowed'] for event in errors)
    assert run['assessment'] is None
    for index, messages in enumerate(model.main_messages):
        inventory_from_messages(messages)
        assert messages[1]['content'].count('本轮有资格编号（请求前；仅元数据，不替你选择证据）：') == 1
        if index % 2:
            assert json.loads(messages[-1]['content'])['instruction'] == '仅允许再修正一次；不要忽略证据检查。'


@pytest.mark.parametrize('counter,boundary', [('model_calls', 'run'), ('model_calls', 'episode'),
                                           ('tool_calls', 'run'), ('tool_calls', 'episode')])
def test_compact_preparation_does_not_restore_run_or_episode_budget(tmp_path, monkeypatch, counter, boundary):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    model = CompactProtocolModel(store)
    engine, run_id, _ = start(store, new_case(store), model)
    if counter == 'model_calls':
        set_counts(store, run_id, 11 if boundary == 'run' else 0, 0, 35, 0)
    else:
        set_counts(store, run_id, 0, 18 if boundary == 'run' else 0, 0, 58)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '预算耗尽' in run['error'] and run['assessment'] is None
    if boundary == 'run':
        assert run[counter] == (12 if counter == 'model_calls' else 20)
    else:
        assert run[counter] in (1, 2)
    episode = store.read('episode', run['episode_id'])
    assert episode[counter] == (36 if counter == 'model_calls' else 60)


def test_flag_is_captured_consistently_and_queued_identity_change_is_rejected(tmp_path, monkeypatch):
    store = Store(tmp_path)
    old_model = LocalModel('', '')
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    assert Engine(store, old_model).compact_actions is False
    engine, run_id, model = start(store, new_case(store))
    assert engine.compact_actions is True
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '0')
    assert engine.compact_actions is True
    changed = Engine(store, model)
    run = execute(changed, run_id)
    assert run['state'] == 'failed' and run['model_calls'] == run['tool_calls'] == 0
    assert '提示版本已变化' in run['error'] or '协调策略已变化' in run['error']


def test_harness_schema_hash_mutation_and_legacy_compact_missing_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    for missing in (False, True):
        engine, run_id, _ = start(store, new_case(store))
        def change(run):
            if missing:
                run['versions']['harness'].pop('compact_actions')
            else:
                run['versions']['harness']['action_transport']['decoder_schema_sha256']['skills/visual_research'] = '0'*64
        store.update_run(run_id, change)
        run = execute(engine, run_id)
        assert run['state'] == 'failed' and '协调策略已变化' in run['error'] and run['model_calls'] == 0


@pytest.mark.parametrize('policy', [None, 'legacy-read-receipt'])
def test_queued_compact_exposure_policy_change_stops_before_model(tmp_path, monkeypatch, policy):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    engine, run_id, _ = start(store, new_case(store))
    def change(run):
        transport = run['versions']['harness']['action_transport']
        if policy is None:
            transport.pop('citation_exposure')
        else:
            transport['citation_exposure'] = policy
    store.update_run(run_id, change)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '协调策略已变化' in run['error']
    assert run['model_calls'] == run['tool_calls'] == 0


@pytest.mark.parametrize('flag', [None, '0', 'true', '1 '])
def test_default_transport_keeps_original_prompt_schema_and_read_shape(tmp_path, monkeypatch, flag):
    if flag is not None:
        monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', flag)
    store = Store(tmp_path)
    case, source = add_pinned_text(store, new_case(store))
    engine, run_id, _ = start(store, case, mode='plain', active=True)
    assert engine.compact_actions is False
    chunk = KnowledgeStore(store.root).source(source['document_id'])['chunks'][0]
    result = read(engine, run_id, source, chunk)
    assert 'read_index' not in result['chunks'][0] and 'run_id' not in result['chunks'][0]
    assert 'read_index' not in store.read('run', run_id)['read_knowledge'][0]
    for mode, task in ACTION_VARIANTS:
        assert system_prompt(mode, task, False) == system_prompt(mode, task)
        assert action_output_schema(mode, task, False) == action_output_schema(mode, task)


def test_status_identity_matches_versions_and_documentary_contract_never_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    app = create_app(tmp_path, ScriptedModel(), SyntheticTextCritic())
    with TestClient(app) as client:
        status = client.get('/api/status').json()
    identity = status['harness']['action_transport']
    assert identity == status['action_transport'] == app.state.engine.versions()['harness']['action_transport']
    assert status['harness']['compact_actions'] is True
    assert identity['protocol'] == 'compact-visual-metadata-v1' and identity['scope'] == 'visual_research-only'
    assert identity['effective_by_task'] == {'visual_research': True, 'documentary_audit': False}
    assert identity['citation_exposure'] == 'successful-main-canonical-body-exposure'
    assert identity['semantic_affordance'] == 'current-run-eligible-evidence-inventory-v1'
    assert identity['inventory_limits'] == agent.COMPACT_INVENTORY_LIMITS
    assert identity['alternative_text_policy'] == 'single-line-ascii-alnum-or-cjk-first-1-40-model-authored'
    assert identity['explanation_pattern'] == agent.COMPACT_EXPLANATION_PATTERN
    for mode, task in ACTION_VARIANTS:
        assert identity['decoder_schema_sha256'][mode+'/'+task] == decoder_schema_sha256(action_output_schema(mode, task, True))
        if task == 'documentary_audit':
            assert system_prompt(mode, task, True) == system_prompt(mode, task)
            assert action_output_schema(mode, task, True) == action_output_schema(mode, task)


def test_compact_affordance_prompts_distinguish_namespaces_without_plain_skill_leak():
    plain = system_prompt('plain', 'visual_research', True)
    skills = system_prompt('skills', 'visual_research', True)
    for prompt in (plain, skills):
        assert agent.COMPACT_INSTRUCTION in prompt
        assert '图像参照和知识资料是不同编号域' in prompt
        assert '可用图像参照清单为空时填[]' in prompt
        assert 'knowledge_read_indexes只用于knowledge_citations的read_index' in prompt
        assert 'alternatives须写有实际含义的竞争解释' in prompt
        assert '如使用insufficient，须先由你request_evidence' in prompt
        assert '中日韩统一表意文字开头' in prompt
    assert agent.COMPACT_SKILLS_INSTRUCTION in skills
    assert 'condition-hypothesis-test' in skills and 'condition-hypothesis-test' not in plain
    assert 'bluewhite-attribution-test' not in plain
    for mode, task in ACTION_VARIANTS:
        assert agent.COMPACT_INSTRUCTION not in system_prompt(mode, task)
        if task == 'documentary_audit':
            assert system_prompt(mode, task, True) == system_prompt(mode, task)


@pytest.mark.parametrize('field', ['alternatives', 'condition_hypotheses'])
@pytest.mark.parametrize('placeholder', ['', ' \t ', ',，。!?', '—…（）'])
def test_only_compact_rejects_blank_or_punctuation_explanations(field, placeholder):
    value = short_assessment() | {field: [placeholder]}
    assert S.Assessment.model_validate(value).model_dump()[field] == [placeholder]
    with pytest.raises(ValidationError):
        CompactAssessment.model_validate(value)
    assert value[field] == [placeholder]  # no text repair, default, or deletion


@pytest.mark.parametrize('structured', [False, True])
def test_http_placeholder_plan_cannot_store_assessment_or_create_observations(tmp_path, monkeypatch, structured):
    store = Store(tmp_path)
    value = short_assessment() | {'alternatives': [',', '']}
    actions = [{'tool': 'record_assessment', 'arguments': value}]
    fixture = CompactProtocolModel(store, plans=[actions, actions])
    model, _ = mocked_local_model(monkeypatch, fixture, structured)
    engine, run_id, _ = start(store, new_case(store), model, mode='plain')
    fixture.run_id = run_id
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and run['assessment'] is None and run['observations'] == []
    assert run['model_calls'] == 2 and run['tool_calls'] == 0
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert [event['repair_allowed'] for event in errors] == [True, False]
    assert all('string_pattern_mismatch' in event['detail'] for event in errors)
    assert all(json.loads(raw)['actions'][0]['arguments'] == value for raw in fixture.raw_outputs)
    assert not any(event['type'] == 'transport_expansion' for event in run['events'])


@pytest.mark.parametrize('explanation', ['后世仿制；须检查材料', '原物受热变色，可用实物检查—'])
def test_meaningful_alternative_with_punctuation_survives_real_host_contract(tmp_path, monkeypatch, explanation):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    engine, run_id, _ = start(store, new_case(store), mode='plain', active=True)
    media_id = store.read('run', run_id)['snapshot']['media'][0]['id']
    store.charge(run_id, 'tool_calls')
    asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
        media_ids=[media_id], question='SYNTHETIC actual derivative protocol')))
    messages = [{'role': 'system', 'content': system_prompt('plain', 'visual_research', True)},
                {'role': 'user', 'content': 'SYNTHETIC actual image delivery'}]
    engine.visual_context(run_id, messages)
    engine.model = DeliveryProtocolModel()
    asyncio.run(engine.call(run_id, messages, 'action'))
    store.charge(run_id, 'tool_calls')
    asyncio.run(engine.tool(run_id, 'request_evidence', S.EvidenceRequest(
        view='SYNTHETIC view', reason='Protocol only', distinguishes='No identification',
        capture_instructions='No real capture')))
    authored = short_assessment(store.read('run', run_id)) | {
        'alternatives': [explanation], 'condition_hypotheses': [explanation]}
    parsed = CompactAssessment.model_validate(authored)
    expanded, mappings = engine.expand_compact_assessment(run_id, parsed)
    assert expanded == authored and mappings == []
    store.charge(run_id, 'tool_calls')
    asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(expanded)))
    assert store.read('run', run_id)['assessment'] == authored


def test_inventory_uses_actual_reference_read_pixels_main_and_body_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    eligible, unread, forbidden = add_ref(store), add_ref(store), add_ref(store, 'unknown')
    case, source = add_pinned_text(store, new_case(store))
    engine, run_id, _ = start(store, case, mode='plain', active=True)
    chunk = KnowledgeStore(store.root).source(source['document_id'])['chunks'][0]
    body = read(engine, run_id, source, chunk)
    store.charge(run_id, 'tool_calls')
    asyncio.run(engine.tool(run_id, 'read_reference', S.ReadReference(reference_id=eligible['id'])))
    assert engine.compact_metadata_inventory(store.read('run', run_id))['reference_ids'] == []
    store.charge(run_id, 'tool_calls')
    images = asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
        media_ids=[case['media'][0]['id'], eligible['media']['id']], question='SYNTHETIC pixels')))
    before = engine.compact_metadata_inventory(store.read('run', run_id))
    assert before['reference_ids'] == before['knowledge_read_indexes'] == []
    assert set(before['observation_ids']) == {obs['id'] for obs in images['observations']}
    messages = [{'role': 'system', 'content': system_prompt('plain', 'visual_research', True)},
        {'role': 'user', 'content': 'SYNTHETIC actual images'}, _ToolResultMessage('read_knowledge', body)]
    engine.visual_context(run_id, messages)
    engine.model = DeliveryProtocolModel()
    asyncio.run(engine.call(run_id, messages, 'action'))
    run = store.read('run', run_id)
    inventory = engine.compact_metadata_inventory(run)
    assert inventory['reference_ids'] == [eligible['id']]
    assert unread['id'] not in inventory['reference_ids'] and forbidden['id'] not in inventory['reference_ids']
    assert source['document_id'] not in inventory['reference_ids']
    assert inventory['knowledge_read_indexes'] == [1]
    assert set(inventory) == set(agent.COMPACT_INVENTORY_LIMITS) | {'totals', 'truncated'}
    same_receipts_skills = deepcopy(run) | {'mode': 'skills', 'loaded_skills': {'bluewhite-attribution-test': {}}}
    assert engine.compact_metadata_inventory(same_receipts_skills) == inventory
    second_body = read(engine, run_id, source, chunk)
    assert second_body['chunks'][0]['read_index'] == 2
    assert engine.compact_metadata_inventory(store.read('run', run_id))['knowledge_read_indexes'] == [1]
    deliver(engine, run_id, _ToolResultMessage('read_knowledge', second_body))
    assert engine.compact_metadata_inventory(store.read('run', run_id))['knowledge_read_indexes'] == [1, 2]
    # Even an injected copied parent observation/receipt is not this run's inventory.
    foreign = deepcopy(store.read('run', run_id))
    foreign['id'] = 'run_SYNTHETIC_other'
    assert engine.compact_metadata_inventory(foreign)['observation_ids'] == []
    assert engine.compact_metadata_inventory(foreign)['reference_ids'] == []
    assert engine.compact_metadata_inventory(foreign)['knowledge_read_indexes'] == []


def test_inventory_limits_are_bounded_and_disclose_truncation():
    # Deliberately oversized in-memory fixture; not evidence from actual tool calls.
    run = {'id': 'run_SYNTHETIC', 'observations': [], 'reference_snapshot': [],
           'read_references': [], 'main_seen_media_ids': [], 'read_knowledge': [],
           'compact_seen_read_indexes': list(range(1, 22))}
    for index in range(49):
        run['observations'].append({'id': f'obs_SYNTHETIC_{index:02}', 'media_id': f'media_{index}', 'run_id': run['id']})
        run['main_seen_media_ids'].append(f'media_{index}')
    for index in range(11):
        identifier = f'ref_SYNTHETIC_{index:02}'
        run['reference_snapshot'].append({'id': identifier, 'permission': 'local_use_authorized', 'media': {'id': f'media_{index}'}})
        run['read_references'].append(identifier)
    for index in range(1, 22):
        run['read_knowledge'].append({key: 'SYNTHETIC' for key in COMPACT_METADATA_FIELDS} |
            {'read_index': index, 'run_id': run['id'], 'content_kind': 'authorized_text', 'text': 'Synthetic body'})
    inventory = Engine.compact_metadata_inventory(run)
    for key, limit in agent.COMPACT_INVENTORY_LIMITS.items():
        assert len(inventory[key]) == limit
        assert inventory['totals'][key] == limit + 1 and inventory['truncated'][key]
    assert inventory['observation_ids'][0] == 'obs_SYNTHETIC_00'
    assert inventory['reference_ids'][0] == 'ref_SYNTHETIC_00'


@pytest.mark.parametrize('field', ['alternatives', 'condition_hypotheses'])
@pytest.mark.parametrize('explanation', ['；后世仿制', ' Greek α', '中文\n分行', '中文\r分行', 'a\n', 'a\r'])
def test_compact_single_line_start_guard_does_not_change_manual_contract(field, explanation):
    value = short_assessment() | {field: [explanation]}
    assert S.Assessment.model_validate(value).model_dump()[field] == [explanation]
    with pytest.raises(ValidationError):
        CompactAssessment.model_validate(value)


def test_actual_compact_schemas_have_only_the_exact_bounded_explanation_pattern():
    for mode in ('plain', 'skills'):
        schema = action_output_schema(mode, 'visual_research', True)
        branches = schema['properties']['actions']['items']['oneOf']
        arguments = next(branch['properties']['arguments'] for branch in branches
                         if branch['properties']['tool']['enum'] == ['record_assessment'])
        for field in ('alternatives', 'condition_hypotheses'):
            assert arguments['properties'][field]['items'] == {'type': 'string',
                'minLength': 1, 'maxLength': 40, 'pattern': agent.COMPACT_EXPLANATION_PATTERN}
    assert 'pattern' not in S.Assessment.model_json_schema()['properties']['alternatives']['items']


@pytest.mark.parametrize('mutation', ['old_prompt', 'missing_policy', 'old_policy'])
def test_queued_compact_affordance_change_stops_before_any_request(tmp_path, monkeypatch, mutation):
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1')
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    def change(run):
        if mutation == 'old_prompt':
            # Actual pre-affordance compact skills prompt hash from full03 source.
            run['versions']['prompt_hash'] = 'e6c0f4f620e2d5c2e1d6c441000d8a9b5d53424f68c27ff367707007107a981f'
        elif mutation == 'missing_policy':
            run['versions']['harness']['action_transport'].pop('semantic_affordance')
        else:
            run['versions']['harness']['action_transport']['semantic_affordance'] = 'legacy-no-inventory'
    store.update_run(run_id, change)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and run['model_calls'] == run['tool_calls'] == 0
    assert not model.main_messages and not model.vision_ids
    assert '版本已变化' in run['error'] or '协调策略已变化' in run['error']
