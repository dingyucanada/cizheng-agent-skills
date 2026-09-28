"""Offline software contracts only: no GPU, external model, or ceramic accuracy.

The actual store, registered tools, immutable knowledge and image derivatives run;
the planner and vision replies are conspicuously synthetic protocol fixtures.
"""
import asyncio
import hashlib
import json
import time
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from cizheng import schemas as S
from cizheng.agent import (Engine, LocalModel, LocalModelFailure, VISION_SYSTEM,
                           _ToolResultMessage, action_output_schema,
                           bounded_messages, decoder_schema_sha256, system_prompt)
from cizheng.agent import OBSERVED_METHOD_RULE
from cizheng.api import create_app
from cizheng.knowledge import KnowledgeStore, validate_snapshot
from cizheng.review_client import StepFunClient
from cizheng.store import Problem, Store, digest, dump, uid
from test_closed_loop import ScriptedModel, add_photo
from test_critic_revision import SyntheticTextCritic, revised_protocol_case
from test_knowledge import document

QUERY = '协议定位'


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Offline protocol test cannot invoke a real model or HTTP provider')
    monkeypatch.setattr(LocalModel, 'complete', forbidden)
    monkeypatch.setattr(StepFunClient, 'review', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.delenv('CIZHENG_GUIDED_WORKFLOW', raising=False)


def new_case(store, count=1, task='visual_research', question=QUERY):
    case = store.create_case(S.NewCase(request_id=uid('req'),
        title='SYNTHETIC guided workflow test', question=question, research_task=task,
        source_declaration='Offline generated fixtures; no ceramic identification').model_dump())
    for index in range(count):
        case = add_photo(store, case, '#%06x' % (index+1))
    return case


def bind(store, case, source):
    return store.link_document(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'document_id': source['document_id'],
        'document_revision': source['revision'], 'document_sha256': source['document_sha256']})


def add_pinned_text(store, case, paragraphs=3, rights='authorized_text'):
    source = KnowledgeStore(store.root).add_document(document(
        title='SYNTHETIC '+QUERY, rights=rights,
        text='\n\n'.join(QUERY+f' 合成固定版本段落{i}，只验证软件协议。' for i in range(paragraphs))
             if rights == 'authorized_text' else ''))['source']
    return bind(store, case, source), source


def tool_results(messages, name):
    records = [json.loads(message['content'].split('：', 1)[1]) for message in messages
               if isinstance(message['content'], str) and message['content'].startswith('工具结果（数据）：')]
    return [record['result'] for record in records if record['tool'] == name]


def main_media_ids(messages):
    values = []
    for message in messages:
        if isinstance(message['content'], list):
            for part in message['content']:
                text = part.get('text', '')
                if text.startswith('{'):
                    value = json.loads(text)
                    if 'media_id' in value:
                        values.append(value['media_id'])
    return values


def notice_budget(messages):
    content = messages[1]['content']
    text = content[0]['text'] if isinstance(content, list) else content
    return json.loads(text.split('预算与证据快照（请求前）：', 1)[1])


def assessment(run, cite=True):
    citations = []
    if cite and run.get('read_knowledge'):
        read = run['read_knowledge'][0]
        citations = [{key: read[key] for key in ('document_id', 'document_revision',
            'document_sha256', 'chunk_id', 'chunk_sha256', 'locator')} |
            {'use': 'source_context', 'relevance': '合成文字只验证固定引用，不是器物答案'}]
    return {'basic_info': 'SYNTHETIC protocol only', 'scope': 'ceramic_research',
        'claims': [{'dimension': dimension, 'candidate': '未知', 'status': 'insufficient',
            'support': [run['observations'][0]['id']], 'conflict': [],
            'reasoning_summary': '合成测试不能识别文物'} for dimension in ('period', 'kiln', 'style')],
        'alternatives': ['未核验'], 'condition_hypotheses': [], 'reference_ids': [],
        'reference_comparison': '合成测试没有实物或图像参照',
        'limitations': ['软件协议测试，没有真实模型或文物结论'],
        'revision_explanation': '本轮重新处理测试输入', 'knowledge_citations': citations}


class GuidedProtocolModel(ScriptedModel):
    def __init__(self, store, finish=False, cite=True, plans=(), vision_failure=None):
        self.store, self.finish, self.cite = store, finish, cite
        self.plans, self.vision_failure = list(plans), vision_failure
        self.run_id = None
        self.main_messages, self.main_states, self.vision_ids = [], [], []

    async def complete(self, messages, timeout):
        if messages[0]['content'] == VISION_SYSTEM:
            ids = [part['text'].split('=', 1)[1] for part in messages[-1]['content']
                   if part.get('text', '').startswith('media_id=')]
            self.vision_ids.append(ids)
            if self.vision_failure:
                raise self.vision_failure
            return await super().complete(messages, timeout)
        run = self.store.read('run', self.run_id)
        self.main_messages.append(deepcopy(messages))
        self.main_states.append(deepcopy(run))
        if self.plans:
            return dump({'actions': self.plans.pop(0)}), {}
        if not self.finish:
            raise LocalModelFailure('SYNTHETIC main request stopped; no provider call')
        seen = {observation['media_id'] for observation in run['observations']}
        missing = [media['id'] for media in run['snapshot']['media'] if media['id'] not in seen]
        if missing:
            return dump({'actions': [{'tool': 'inspect_images', 'arguments': {
                'media_ids': missing[:4], 'question': 'SYNTHETIC additional image protocol'}}]}), {}
        actions = []
        if run.get('text_review_snapshot') and 'critic_dispositions' not in run:
            actions.append({'tool': 'respond_critic', 'arguments': {'dispositions': [
                {'issue_index': index, 'decision': 'unresolved', 'reason': 'SYNTHETIC response only'}
                for index, _ in enumerate(run['text_review_snapshot']['result']['issues'])]}})
        if not run['evidence_request']:
            actions.append({'tool': 'request_evidence', 'arguments': {
                'view': 'SYNTHETIC missing evidence', 'reason': 'No ceramic identification',
                'distinguishes': 'Protocol state transition only', 'capture_instructions': 'No real capture required'}})
        actions.extend([{'tool': 'record_assessment', 'arguments': assessment(run, self.cite)},
                        {'tool': 'build_opinion', 'arguments': {}}])
        return dump({'actions': actions}), {}


def start(store, case, model=None, mode='skills', engine_type=Engine, active=False):
    model = model or GuidedProtocolModel(store)
    engine = engine_type(store, model)
    run_id = store.start_run(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'mode': mode},
        engine.versions(mode, case['research_task']))['run_id']
    model.run_id = run_id
    if active:
        store.update_run(run_id, lambda run: run.update(state='running', started_at=time.time()))
    return engine, run_id, model


def execute(engine, run_id):
    asyncio.run(engine.execute(run_id))
    return engine.store.read('run', run_id)


@pytest.mark.parametrize('flag', [None, '0', 'true', '1 '])
def test_guidance_is_explicit_and_default_has_no_preparation(tmp_path, monkeypatch, flag):
    if flag is not None:
        monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', flag)
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    run = execute(engine, run_id)
    assert run['versions']['harness']['guided_workflow'] is False
    assert run['versions']['harness']['strategy'] == 'model-planned-v1'
    assert run['versions']['harness']['compact_actions'] is False
    assert not any(event['type'].startswith('harness_') for event in run['events'])
    assert not model.vision_ids and run['tool_calls'] == 0 and run['model_calls'] == 1
    assert model.main_messages[0][0]['content'] == system_prompt()
    assert main_media_ids(model.main_messages[0]) == []


def test_default_preserves_three_argument_tool_overrides(tmp_path):
    class ExistingEngine(Engine):
        async def tool(self, run_id, name, args):
            return await super().tool(run_id, name, args)
    store = Store(tmp_path)
    model = GuidedProtocolModel(store, plans=[[{'tool': 'read_case', 'arguments': {}}]])
    engine, run_id, _ = start(store, new_case(store), model, engine_type=ExistingEngine)
    run = execute(engine, run_id)
    assert run['tool_calls'] == 1 and tool_results(model.main_messages[-1], 'read_case')
    assert not any(event['type'].startswith('harness_') for event in run['events'])


@pytest.mark.parametrize('cite', [False, True])
def test_guided_real_preparation_delivers_methods_images_and_optional_citation(tmp_path, monkeypatch, cite):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case, source = add_pinned_text(store, new_case(store, count=2))
    model = GuidedProtocolModel(store, finish=True, cite=cite)
    engine, run_id, _ = start(store, case, model)
    run = execute(engine, run_id)
    assert run['state'] == 'waiting_evidence', run['error']
    preparation = [event['tool'] for event in run['events']
                   if event['type'] == 'harness_prepare' and event['outcome'] == 'succeeded']
    assert preparation == ['read_case', 'discover_skills', 'load_skill', 'load_skill',
                           'search_knowledge', 'read_knowledge', 'read_knowledge', 'inspect_images']
    assert set(run['loaded_skills']) == {'ceramic-route', 'ceramic-research-record'}
    first = model.main_messages[0]
    assert first[0]['content'] == system_prompt()
    assert model.main_states[0]['model_calls'] == 2 and model.main_states[0]['tool_calls'] == 8
    assert run['model_calls'] == 2 and run['tool_calls'] == 11
    assert model.vision_ids == [[media['id'] for media in case['media']]]
    assert set(main_media_ids(first)) == set(model.vision_ids[0])
    assert model.main_states[0]['assessment'] is None
    for message in first:
        if isinstance(message, _ToolResultMessage) and message.method_key:
            value = json.loads(message['content'].split('：', 1)[1])
            assert value['tool'] == 'load_skill'
            assert value['result']['text'] and digest(value['result']) == value['result_sha256']
    assert len(tool_results(first, 'load_skill')) == 2
    assert {read['document_id'] for read in run['read_knowledge']} == {source['document_id']}
    assert len(run['assessment']['knowledge_citations']) == int(cite)
    budget = notice_budget(first)
    assert budget['remaining_model_calls_including_this_request'] == 11
    assert budget['remaining_tool_calls'] == 12 and budget['remaining_active_seconds'] <= 300
    assert not budget['selected_unobserved_media_ids']
    assert not budget['selected_requires_future_main_image_delivery']
    assert run['versions']['harness']['natural_skill_discovery'] is False


def test_plain_and_skills_share_non_skill_preparation_without_claiming_ablation(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    runs = []
    for mode in ('plain', 'skills'):
        case, _ = add_pinned_text(store, new_case(store))
        engine, run_id, model = start(store, case, mode=mode)
        run = execute(engine, run_id)
        names = [event['tool'] for event in run['events'] if
                 event['type'] == 'harness_prepare' and event['outcome'] == 'succeeded']
        runs.append((run, names, model))
        assert names[0] == 'read_case' and names[-1] == 'inspect_images'
        assert len(run['read_knowledge']) == 2 and len(model.vision_ids) == 1
        assert model.main_messages[0][0]['content'] == system_prompt(mode)
    plain, skills = runs
    assert [name for name in skills[1] if name not in ('discover_skills', 'load_skill')] == plain[1]
    assert plain[0]['loaded_skills'] == {}
    assert plain[0]['model_calls'] == skills[0]['model_calls'] == 2
    assert skills[0]['tool_calls'] == plain[0]['tool_calls'] + 3


def test_coordinator_search_uses_historical_pin_subset_not_global_top_hits(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case, pinned = add_pinned_text(store, new_case(store))
    knowledge = KnowledgeStore(store.root)
    knowledge.add_document(document(document_id=pinned['document_id'], expected_revision=1,
        title='SYNTHETIC later revision', text='Later revision has different content.'))
    unrelated = knowledge.add_document(document(title='UNRELATED '+QUERY,
        source_url='https://example.org/unrelated', text=(QUERY+' ')*40))['source']
    engine, run_id, model = start(store, case, active=True)
    original = deepcopy(store.read('run', run_id)['knowledge_snapshot'])
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'begin'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    run = store.read('run', run_id)
    query = run['knowledge_queries'][0]
    assert query['query'] == QUERY and query['filters'] == {'document_id': [pinned['document_id']]}
    assert query['selection_actor'] == 'coordinator' and query['scope'] == 'case-pinned-fixed-versions-only'
    assert query['run_snapshot_sha256'] == original['snapshot_sha256']
    assert query['snapshot_sha256'] != original['snapshot_sha256']
    assert len(query['result_chunk_ids']) == len(run['read_knowledge']) == 2
    assert {read['document_revision'] for read in run['read_knowledge']} == {1}
    assert {read['document_sha256'] for read in run['read_knowledge']} == {pinned['document_sha256']}
    assert store.read('run', run_id)['knowledge_snapshot'] == original
    scoped = engine._coordinator_knowledge_snapshot(run)
    assert validate_snapshot(scoped) and len(scoped['sources']) == 1
    normal = asyncio.run(engine.tool(run_id, 'search_knowledge', S.SearchKnowledge(query=QUERY)))
    assert unrelated['document_id'] in {hit['document_id'] for hit in normal['results']}
    chunk = next(entry['chunks'][0] for entry in original['sources']
                 if entry['source']['document_id'] == unrelated['document_id'])
    with pytest.raises(ValueError, match='本案已绑定'):
        asyncio.run(engine.tool(run_id, 'read_knowledge', S.ReadKnowledge(
            document_id=unrelated['document_id'], chunk_id=chunk['chunk_id']), coordinator=True))
    assert len(store.read('run', run_id)['read_knowledge']) == 2


@pytest.mark.parametrize('condition', ['no_pin', 'no_match', 'unknown', 'public_metadata'])
def test_no_pin_no_match_or_metadata_does_not_manufacture_text_reads(tmp_path, monkeypatch, condition):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store)
    if condition == 'no_pin':
        KnowledgeStore(store.root).add_document(document(title=QUERY, text=QUERY))
    elif condition == 'no_match':
        source = KnowledgeStore(store.root).add_document(document(
            title='English protocol only', institution='Synthetic', scope='Synthetic',
            author='Synthetic author', rights_note='Original offline fixture permission',
            limitations=['Offline fixture only'], locator='Section A',
            text='Completely unrelated latin text.'))['source']
        case = bind(store, case, source)
    else:
        case, _ = add_pinned_text(store, case, rights=condition)
    engine, run_id, model = start(store, case)
    run = execute(engine, run_id)
    search = tool_results(model.main_messages[0], 'search_knowledge')[0]
    assert run.get('read_knowledge', []) == [] and search['selection_actor'] == 'coordinator'
    if condition in ('no_pin', 'no_match'):
        assert search['results'] == []
    else:
        assert search['results'] and all(hit['content_kind'] == 'metadata' for hit in search['results'])
    assert run['assessment'] is None


def test_question_prefix_is_real_query_and_pin_hash_mismatch_stops_preparation(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case, _ = add_pinned_text(store, new_case(store, question=QUERY+'字'*220))
    engine, run_id, model = start(store, case)
    run = execute(engine, run_id)
    assert run['knowledge_queries'][0]['query'] == case['question'][:200]
    store2 = Store(tmp_path / 'other')
    case2, _ = add_pinned_text(store2, new_case(store2))
    engine2, rid2, model2 = start(store2, case2)
    store2.update_run(rid2, lambda run: run['snapshot']['knowledge_links'][0].update(document_sha256='0'*64))
    failed = execute(engine2, rid2)
    assert failed['state'] == 'failed' and '固定版本与哈希' in failed['error']
    event = next(event for event in failed['events'] if event['type'] == 'harness_prepare' and event['outcome'] == 'failed')
    assert event['tool'] == 'search_knowledge' and event['error_type'] == 'Problem'
    assert not model2.vision_ids and failed['tool_calls'] == 5 and failed['model_calls'] == 0


@pytest.mark.parametrize('count', [5, 8])
def test_only_first_four_prepared_then_all_selected_images_need_later_main_delivery(tmp_path, monkeypatch, count):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store, count=count+1)
    selected = case['analysis_media_ids'][:count]
    case = store.select_analysis_media(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'media_ids': selected})
    model = GuidedProtocolModel(store, finish=True)
    engine, run_id, _ = start(store, case, model)
    run = execute(engine, run_id)
    assert run['state'] == 'waiting_evidence', run['error']
    assert model.vision_ids == [selected[:4], selected[4:]]
    assert set(main_media_ids(model.main_messages[0])) == set(selected[:4])
    assert set(model.main_states[1]['main_seen_media_ids']) == set(selected[:4])
    assert set(run['main_seen_media_ids']) == set(selected)
    assert {observation['media_id'] for observation in run['observations']} == set(selected)
    assert notice_budget(model.main_messages[0])['selected_unobserved_media_ids'] == sorted(selected[4:])
    assert notice_budget(model.main_messages[0])['selected_requires_future_main_image_delivery'] == sorted(selected[4:])
    assert set(run['snapshot']['analysis_scope']['omitted_media_ids']).isdisjoint(run['main_seen_media_ids'])


def test_preparation_does_not_bypass_specialty_or_new_image_assessment_guard(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    engine, run_id, _ = start(store, new_case(store, count=5), active=True)
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'begin'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    run = store.read('run', run_id)
    bad = assessment(run, False)
    bad['scope'] = 'bluewhite_gu'
    with pytest.raises(ValueError, match='归属比较技能'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(bad)))
    with pytest.raises(ValueError, match='所有器物照片'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(assessment(run, False))))
    asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
        media_ids=[run['snapshot']['media'][-1]['id']], question='SYNTHETIC extra image')))
    with pytest.raises(ValueError, match='新动作轮'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(assessment(store.read('run', run_id), False))))
    assert store.read('run', run_id)['assessment'] is None


def test_parent_preparation_rereads_pixels_and_critic_still_needs_successful_main(tmp_path, monkeypatch):
    store = Store(tmp_path)
    case, previous, review = revised_protocol_case(store)
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    model = GuidedProtocolModel(store, finish=True)
    engine, run_id, _ = start(store, case, model, active=True)
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'begin'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    prepared = store.read('run', run_id)
    assert prepared['parent_run_id'] == previous['id'] and prepared['text_review_snapshot']['id'] == review['id']
    assert set(prepared['loaded_skills']) == {'ceramic-route', 'ceramic-research-record', 'evidence-revise'}
    assert prepared['dependencies_reviewed'] and not prepared.get('main_seen_media_ids')
    assert {obs['id'] for obs in prepared['observations']}.isdisjoint(obs['id'] for obs in previous['observations'])
    dispositions = S.RespondCritic(dispositions=[{'issue_index': index, 'decision': 'unresolved',
        'reason': 'SYNTHETIC response only'} for index in range(2)])
    with pytest.raises(ValueError, match='主 Agent'):
        asyncio.run(engine.tool(run_id, 'respond_critic', dispositions))
    engine.visual_context(run_id, messages)
    engine._guided_budget_context(run_id, messages)
    assert notice_budget(messages)['text_critic_requires_response'] is True
    asyncio.run(engine.call(run_id, messages, 'action'))
    with pytest.raises(ValueError, match='每项'):
        asyncio.run(engine.tool(run_id, 'respond_critic', S.RespondCritic(dispositions=dispositions.dispositions[:1])))
    assert asyncio.run(engine.tool(run_id, 'respond_critic', dispositions))['recorded']
    assert store.read('run', previous['id'])['assessment'] == previous['assessment']


def set_counts(store, run_id, models, tools, total_models, total_tools):
    store.update_run(run_id, lambda run: run.update(model_calls=models, tool_calls=tools))
    episode_id = store.read('run', run_id)['episode_id']
    with store.tx() as db:
        episode = store.get(db, 'episode', episode_id)
        episode.update(model_calls=total_models, tool_calls=total_tools)
        store.put(db, 'episode', episode)


@pytest.mark.parametrize('boundary', ['run', 'episode'])
def test_preparation_vision_cannot_bypass_model_budget(tmp_path, monkeypatch, boundary):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    set_counts(store, run_id, 11 if boundary == 'run' else 0, 0, 35, 0)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '预算耗尽' in run['error']
    assert run['model_calls'] == (12 if boundary == 'run' else 1)
    assert store.read('episode', run['episode_id'])['model_calls'] == 36
    assert len(model.vision_ids) == 1 and model.main_messages == [] and run['assessment'] is None
    assert [event['remaining_model_calls_including_this_request'] for event in run['events']
            if event['type'] == 'harness_budget'] == [0]


@pytest.mark.parametrize('boundary', ['run', 'episode'])
def test_every_preparation_tool_is_charged_and_original_limit_stops_dependencies(tmp_path, monkeypatch, boundary):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    set_counts(store, run_id, 0, 18 if boundary == 'run' else 0, 0, 58)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '预算耗尽' in run['error']
    assert run['tool_calls'] == (20 if boundary == 'run' else 2)
    assert store.read('episode', run['episode_id'])['tool_calls'] == 60
    failed = [event for event in run['events'] if event['type'] == 'harness_prepare' and event['outcome'] == 'failed']
    assert len(failed) == 1 and failed[0]['tool'] == 'load_skill' and failed[0]['error_type'] == 'Problem'
    assert run['loaded_skills'] == {} and not model.vision_ids and not model.main_messages


def test_failed_preparation_vision_preserves_charges_and_failure_reason(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    model = GuidedProtocolModel(store, vision_failure=TimeoutError('SYNTHETIC vision timeout'))
    engine, run_id, _ = start(store, new_case(store), model)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and run['model_calls'] == 1 and run['tool_calls'] == 6
    assert run['assessment'] is None and run['observations'] == [] and model.main_messages == []
    failed = [event for event in run['events'] if event['type'] == 'harness_prepare' and event['outcome'] == 'failed']
    assert failed[-1]['error_type'] == 'TimeoutError' and 'SYNTHETIC vision timeout' in failed[-1]['detail']
    assert any(event['type'] == 'model' and event['outcome'] == 'failed' for event in run['events'])


def test_budget_anchor_does_not_displace_latest_repair_or_method_body(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    engine, run_id, _ = start(store, new_case(store), active=True)
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'begin'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    methods = [message for message in messages if isinstance(message, _ToolResultMessage) and message.method_key]
    messages.extend([{'role': 'assistant', 'content': dump({'actions': [{'tool': 'read_case', 'arguments': {}}]})},
        _ToolResultMessage('read_case', {'padding': 'X'*29000})])
    repair = {'role': 'user', 'content': dump({'error': 'SYNTHETIC invalid action',
        'instruction': '仅允许再修正一次；不要忽略证据检查。'})}
    messages.append(repair)
    engine.visual_context(run_id, messages)
    engine._guided_budget_context(run_id, messages)
    bounded = bounded_messages(messages)
    assert bounded[-1] is repair
    assert all(any(message is method for message in bounded) for method in methods)
    assert notice_budget(bounded)['remaining_model_calls_including_this_request'] == 11
    assert sum(len(message['content']) if isinstance(message['content'], str) else
        sum(len(part.get('text', '')) for part in message['content']) for message in bounded) <= 32000


@pytest.mark.parametrize('recorded', ['missing', 'default'])
def test_guided_flag_cannot_change_a_frozen_or_legacy_queued_run(tmp_path, monkeypatch, recorded):
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    if recorded == 'missing':
        store.update_run(run_id, lambda run: run['versions'].pop('harness'))
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    guided = Engine(store, model)
    run = execute(guided, run_id)
    assert run['state'] == 'failed' and '协调策略已变化' in run['error']
    assert run['model_calls'] == run['tool_calls'] == 0 and not model.main_messages


def test_default_legacy_run_compatibility_and_hashes_stay_trusted(tmp_path, monkeypatch):
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    versions = deepcopy(store.read('run', run_id)['versions'])
    schema_hash = decoder_schema_sha256(action_output_schema())
    store.update_run(run_id, lambda run: run['versions'].pop('harness'))
    run = execute(engine, run_id)
    assert run['model_calls'] == 1 and model.main_messages[0][0]['content'] == system_prompt()
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    guided_versions = Engine(store, model).versions()
    for key in ('prompt_hash', 'vision_prompt_hash', 'tool_schema_hash'):
        assert guided_versions[key] == versions[key]
    assert guided_versions['prompt_hash'] == hashlib.sha256(system_prompt().encode()).hexdigest()
    assert decoder_schema_sha256(action_output_schema()) == schema_hash


def test_guided_status_identity_matches_run_versions_and_documentary_only_reads_case(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    app = create_app(tmp_path, model=GuidedProtocolModel(Store(tmp_path)), review_client=SyntheticTextCritic())
    with TestClient(app) as client:
        status = client.get('/api/status').json()
        assert status['harness'] == app.state.engine.versions()['harness']
        assert status['harness']['strategy'] == 'coordinator-observed-method-v2'
        assert 'harness' not in status['model']
    store = Store(tmp_path / 'documentary')
    case, _ = add_pinned_text(store, new_case(store, count=0, task='documentary_audit'))
    engine, run_id, model = start(store, case)
    run = execute(engine, run_id)
    assert [event['tool'] for event in run['events'] if event['type'] == 'harness_prepare'
            and event['outcome'] == 'succeeded'] == ['read_case']
    assert run['loaded_skills'] == {} and run['tool_calls'] == 1 and not model.vision_ids
    assert model.main_messages[0][0]['content'] == system_prompt('skills', 'documentary_audit')


class ObservedMethodProtocolModel(GuidedProtocolModel):
    """Synthetic vision text; actual registered observation/store path still runs."""
    def __init__(self, store, descriptions):
        super().__init__(store)
        self.descriptions = descriptions

    async def complete(self, messages, timeout):
        raw, usage = await super().complete(messages, timeout)
        if messages[0]['content'] == VISION_SYSTEM:
            value = json.loads(raw)
            for observation in value['observations']:
                observation['visible'] = self.descriptions.get(observation['media_id'], 'SYNTHETIC field')
                observation['interpretation'] = '青花只是合成解释，不能触发方法'
            raw = dump(value)
        return raw, usage


@pytest.mark.parametrize('mode', ['plain', 'skills'])
@pytest.mark.parametrize('visible,match', [('青花纹饰合成色块', True),
    ('Blue-and-white synthetic field', True), ('blue-and-whiteness fixture', False),
    ('SYNTHETIC field', False), ('青白瓷合成色块', False)])
def test_observed_method_only_uses_real_first_batch_visible_and_original_charges(tmp_path, monkeypatch, mode, visible, match):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store, count=2, question='青花 blue-and-white 用户文字不得触发')
    model = ObservedMethodProtocolModel(store, {media['id']: visible for media in case['media']})
    engine, run_id, _ = start(store, case, model, mode=mode, active=True)
    messages = [{'role': 'system', 'content': system_prompt(mode)}, {'role': 'user', 'content': 'SYNTHETIC'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    run = store.read('run', run_id)
    expected = match and mode == 'skills'
    assert ('bluewhite-attribution-test' in run['loaded_skills']) is expected
    assert 'condition-hypothesis-test' not in run['loaded_skills']
    successes = [event for event in run['events'] if event['type'] == 'harness_prepare' and event['outcome'] == 'succeeded']
    assert run['tool_calls'] == len(successes) == (6+int(expected) if mode == 'skills' else 3)
    assert run['model_calls'] == 1 and run['assessment'] is None and run['evidence_request'] is None
    assert run['versions']['harness']['strategy'] == 'coordinator-observed-method-v2'
    assert run['versions']['harness']['observed_method_rule'] == OBSERVED_METHOD_RULE
    decisions = [event for event in run['events'] if event['type'] == 'harness_observed_method']
    if mode == 'skills':
        assert len(decisions) == 1 and decisions[0]['actor'] == 'coordinator'
        assert decisions[0]['natural_skill_discovery'] is False and decisions[0]['classification_verified'] is False
        assert (decisions[0]['selected_method'] is not None) is expected
        assert {item['observation_id'] for item in decisions[0]['matched_observations']} == (
            {item['id'] for item in run['observations']} if match else set())
        assert len(tool_results(messages, 'load_skill')) == 2+int(expected)
    else:
        assert decisions == [] and tool_results(messages, 'load_skill') == []


def test_observed_method_does_not_inspect_fifth_image_or_restore_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store, count=5)
    model = ObservedMethodProtocolModel(store, {case['media'][4]['id']: '青花合成色块'})
    engine, run_id, _ = start(store, case, model, active=True)
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'SYNTHETIC'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    run = store.read('run', run_id)
    assert 'bluewhite-attribution-test' not in run['loaded_skills']
    assert model.vision_ids == [[media['id'] for media in case['media'][:4]]]
    assert run['model_calls'] == 1 and run['tool_calls'] == 6


def test_observed_method_failure_preserves_original_tool_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    case = new_case(store)
    model = ObservedMethodProtocolModel(store, {case['media'][0]['id']: '青花合成色块'})
    engine, run_id, _ = start(store, case, model)
    set_counts(store, run_id, 0, 14, 0, 14)
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '预算耗尽' in run['error']
    assert run['tool_calls'] == 20 and run['model_calls'] == 1 and run['assessment'] is None
    assert 'bluewhite-attribution-test' not in run['loaded_skills']
    failures = [event for event in run['events'] if event['type'] == 'harness_prepare' and event['outcome'] == 'failed']
    assert failures[-1]['tool'] == 'load_skill' and failures[-1]['error_type'] == 'Problem'


def test_old_guided_method_policy_queue_is_rejected_before_preparation(tmp_path, monkeypatch):
    monkeypatch.setenv('CIZHENG_GUIDED_WORKFLOW', '1')
    store = Store(tmp_path)
    engine, run_id, model = start(store, new_case(store))
    store.update_run(run_id, lambda run: run['versions']['harness'].update(strategy='coordinator-preparation-v1'))
    run = execute(engine, run_id)
    assert run['state'] == 'failed' and '协调策略已变化' in run['error']
    assert run['tool_calls'] == run['model_calls'] == 0 and not model.vision_ids


@pytest.mark.parametrize('kind', ['visual', 'documentary'])
@pytest.mark.parametrize('boundary', ['run_time', 'episode_time', 'cancelled'])
def test_post_response_budget_failure_never_records_successful_main_delivery(tmp_path, kind, boundary):
    store = Store(tmp_path)
    if kind == 'visual':
        case = new_case(store)
    else:
        case, source = add_pinned_text(store, new_case(store, count=0, task='documentary_audit'))
    engine, run_id, model = start(store, case, mode='plain', active=True)
    messages = [{'role': 'system', 'content': system_prompt('plain', case['research_task'])},
                {'role': 'user', 'content': 'SYNTHETIC boundary test'}]
    store.charge(run_id, 'tool_calls')
    if kind == 'visual':
        asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
            media_ids=[media['id'] for media in case['media']], question='SYNTHETIC real derivative')))
        engine.visual_context(run_id, messages)
    else:
        chunk = KnowledgeStore(store.root).source(source['document_id'], 1)['chunks'][0]
        result = asyncio.run(engine.tool(run_id, 'read_knowledge', S.ReadKnowledge(
            document_id=source['document_id'], chunk_id=chunk['chunk_id'])))
        messages.append(_ToolResultMessage('read_knowledge', result))
        assert result['chunks'][0]['read_id']
    before = store.read('run', run_id)['model_calls']

    class ReturningBoundaryModel(ScriptedModel):
        async def complete(self, messages, timeout):
            if boundary == 'run_time':
                store.update_run(run_id, lambda run: run.update(started_at=time.time()-301))
            elif boundary == 'episode_time':
                episode_id = store.read('run', run_id)['episode_id']
                with store.tx() as db:
                    episode = store.get(db, 'episode', episode_id)
                    episode['seconds'] = 901
                    store.put(db, 'episode', episode)
            else:
                store.finish(run_id, 'cancelled', 'SYNTHETIC cancellation after response')
            return dump({'actions': [{'tool': 'read_case', 'arguments': {}}]}), {}

    engine.model = ReturningBoundaryModel()
    with pytest.raises(Problem) as failed:
        asyncio.run(engine.call(run_id, messages, 'action'))
    assert failed.value.status == 409
    run = store.read('run', run_id)
    assert run['model_calls'] == before+1
    assert not run.get('main_seen_media_ids') and not run.get('main_seen_text_read_ids')
    event = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'failed' and event['failure_type'] == 'Problem'
    assert event['successful_text_read_ids'] == [] and event['output_hash']
    assert run['assessment'] is None
