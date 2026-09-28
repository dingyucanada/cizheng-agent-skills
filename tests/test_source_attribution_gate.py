"""Finite wording and actual receipt-delivery contracts; no semantic/model proof."""
import asyncio
import base64
import io
import time
from copy import deepcopy

import httpx
import pytest
from PIL import Image

from cizheng import agent, schemas as S
from cizheng.agent import Engine, _ToolResultMessage
from cizheng.knowledge import KnowledgeStore
from cizheng.store import Store, digest, dump, uid


def opinion(text='合成测试无归属结论'):
    return {'basic_info': '合成协议测试', 'scope': 'ceramic_research',
            'claims': [{'dimension': dimension, 'candidate': '未知', 'status': 'insufficient',
                        'support': [], 'conflict': [], 'reasoning_summary': text}
                       for dimension in ('period', 'kiln', 'style')],
            'alternatives': ['尚需补证'], 'condition_hypotheses': [], 'reference_ids': [],
            'reference_comparison': '没有实物参照图', 'limitations': ['软件测试，无专业结论'],
            'revision_explanation': '本轮合成协议测试', 'knowledge_citations': []}


@pytest.mark.parametrize('text', [
    '无参照图支持，仅凭馆藏记录推断', '依据馆藏记录推断，但无实物参照验证',
    '没有参照图但依据馆藏记录推断', '据馆方资料推断时期', '根据相关文献判断方法',
    '馆藏记录显示某时期', '馆方记载：某来源年代', '文献记载纹饰分类方法',
    '文献指出不可仅凭纹饰断代', '资料记载未有底款', '引用来源正文作方法背景',
    '无资料支持。依据馆方记载有限讨论',
])
def test_explicit_affirmative_source_wording_is_detected(text):
    assessment = S.Assessment.model_validate(opinion(text))
    assert agent.explicit_knowledge_attributions(assessment) == [
        'claims.0.reasoning_summary', 'claims.1.reasoning_summary', 'claims.2.reasoning_summary']


@pytest.mark.parametrize('text', [
    '没有资料', '暂无馆藏记录', '缺少文献记载', '文献记录缺失', '资料记载不存在',
    '无可靠资料记载', '不能仅凭馆藏记录推断', '未依据文献断代', '不应根据资料推断',
    '尚需查阅文献记载', '需参考文献记载', '尚未查阅的文献记载',
    '资料未能证明年代', '馆藏记录未知', '没有对应的文献记载',
    '不得将资料记载当本件结论', '图像资料显示蓝白纹样', '依据照片观察器形',
    '仅登记已读来源，不采用其归属', '来源上下文尚缺', '观测不足，暂不判断时期',
    '如果依据文献记载应先核验', '是否根据资料判断仍待确认', '建议参考馆方记载核查',
    '未见文献记载', '尚无馆方记载', '找不到资料记载', '文献记载不详',
])
def test_missing_negated_future_and_image_source_wording_does_not_require_citation(text):
    assert not agent.explicit_knowledge_attributions(S.Assessment.model_validate(opinion(text)))


@pytest.mark.parametrize('field', ['basic_info', 'reference_comparison', 'revision_explanation',
                                  'alternatives', 'condition_hypotheses', 'limitations', 'candidate'])
def test_guard_covers_report_narrative_fields_without_changing_them(field):
    value = opinion()
    text = '依据馆方记载作来源背景'
    if field == 'candidate':
        value['claims'][0]['candidate'] = text
        expected = 'claims.0.candidate'
    elif field in ('alternatives', 'condition_hypotheses', 'limitations'):
        value[field] = [text]
        expected = field + '.0'
    else:
        value[field] = text
        expected = field
    before = deepcopy(value)
    assert agent.explicit_knowledge_attributions(S.Assessment.model_validate(value)) == [expected]
    assert value == before


class OfflineDelivery:
    configured = True

    def identity(self):
        return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'no-provider-delivery-contract'}

    async def complete(self, messages, timeout):
        return dump({'actions': [{'tool': 'read_case', 'arguments': {}}]}), {}


@pytest.fixture(params=[False, True], ids=['original-transport', 'compact-transport'])
def reader(tmp_path, monkeypatch, request):
    def forbidden(*args, **kwargs):
        pytest.fail('No HTTP or real model in source-attribution protocol tests')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    monkeypatch.setenv('CIZHENG_COMPACT_ACTIONS', '1' if request.param else '0')
    monkeypatch.delenv('CIZHENG_GUIDED_WORKFLOW', raising=False)
    store = Store(tmp_path)
    case = store.create_case(S.NewCase(request_id=uid('req'), title='合成协议测试',
        question='只检验资料归因门禁', source_declaration='合成测试输入').model_dump())
    image = io.BytesIO()
    Image.new('RGB', (16, 16), 'blue').save(image, format='PNG')
    case = store.add_evidence(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'filename': 'synthetic.png',
        'image_base64': base64.b64encode(image.getvalue()).decode(), 'view': '合成视角',
        'edit_declaration': '合成纯色，仅软件协议', 'source': 'SYNTHETIC-TEST-ONLY'})['case']
    source = KnowledgeStore(store.root).add_document({'title': '合成协议来源',
        'institution': '合成机构', 'source_url': 'https://example.org/software-only',
        'locator': '合成段落1', 'author': '协议测试', 'year': '2026',
        'rights': 'authorized_text', 'rights_note': '本测试原创文本',
        'scope': '协议测试', 'source_type': 'test_fixture',
        'text': '合成授权正文，只检验送达资格；不提供陶瓷判断。',
        'limitations': ['合成文字，不是文物资料']})['source']
    case = store.link_document(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'document_id': source['document_id'],
        'document_revision': source['revision'], 'document_sha256': source['document_sha256']})
    engine = Engine(store, OfflineDelivery())
    run_id = store.start_run(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'mode': 'plain'}, engine.versions('plain'))['run_id']
    # Use the same Store transition as Engine.execute before any charged call.
    store.update_run(run_id, lambda run: run.update(state='running', started_at=time.time()))
    # Seed only the unrelated image preconditions; no image/quality inference.
    media_id = case['media'][0]['id']
    store.update_run(run_id, lambda run: run.update(
        observations=[{'id': uid('obs'), 'run_id': run_id, 'media_id': media_id}],
        main_seen_media_ids=[media_id]))
    asyncio.run(engine.tool(run_id, 'request_evidence', S.EvidenceRequest(view='实物细节',
        reason='合成协议无判断依据', distinguishes='仅测试不足意见', capture_instructions='按需补证')))
    chunk = KnowledgeStore(store.root).source(source['document_id'], source['revision'])['chunks'][0]
    result = asyncio.run(engine.tool(run_id, 'read_knowledge', S.ReadKnowledge(
        document_id=source['document_id'], chunk_id=chunk['chunk_id'])))
    return store, engine, run_id, result


def deliver(reader, message, model=None):
    store, engine, run_id, _ = reader
    if model is not None:
        engine.model = model
    prompt = agent.system_prompt('plain', 'visual_research', engine.compact_actions)
    asyncio.run(engine.call(run_id, [{'role': 'system', 'content': prompt},
                                   {'role': 'user', 'content': '合成送达'}, message], 'action'))


def selected_opinion(reader):
    store, _, run_id, _ = reader
    receipt = store.read('run', run_id)['read_knowledge'][0]
    value = opinion('依据馆藏记录推断，但无实物参照验证')
    value['knowledge_citations'] = [{key: receipt[key] for key in agent.COMPACT_METADATA_FIELDS} |
                                  {'use': 'source_context', 'relevance': '合成协议来源上下文'}]
    return value


def test_delivered_but_unselected_body_cannot_auto_fill_missing_citation(reader):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    value = opinion('无参照图支持，仅凭馆藏记录推断')
    before = deepcopy(value)
    with pytest.raises(ValueError, match=agent.SOURCE_ATTRIBUTION_POLICY):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(value)))
    assert store.read('run', run_id)['assessment'] is None
    assert value == before and value['knowledge_citations'] == []


def test_current_run_read_requires_canonical_successful_delivery_before_adoption(reader):
    store, engine, run_id, result = reader
    value = selected_opinion(reader)
    with pytest.raises(ValueError, match='成功主动作实际收到'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(value)))
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    before = deepcopy(value)
    asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(value)))
    assert store.read('run', run_id)['assessment'] == before == value
    # This acceptance checks provenance, not whether the synthetic text supports a claim.
    receipt = store.read('run', run_id)['read_knowledge'][0]
    assert store.read('run', run_id)['main_seen_knowledge_receipt_sha256'] == [agent.knowledge_receipt_identity(receipt)]


@pytest.mark.parametrize('surface', ['copied_dict', 'plain_text', 'source_card', 'old_run',
                                    'changed_body', 'mutated_message'])
def test_noncanonical_or_metadata_delivery_does_not_qualify_source_claim(reader, surface):
    store, engine, run_id, result = reader
    canonical = _ToolResultMessage('read_knowledge', result)
    if surface == 'copied_dict':
        message = dict(canonical)
    elif surface == 'plain_text':
        message = {'role': 'user', 'content': canonical['content']}
    elif surface == 'source_card':
        metadata = deepcopy(result)
        metadata['chunks'][0].update(content_kind='metadata', text='来源卡，无授权正文')
        message = _ToolResultMessage('read_knowledge', metadata)
    elif surface == 'old_run':
        metadata = deepcopy(result)
        metadata['chunks'][0]['run_id'] = 'SYNTHETIC-previous-run'
        message = _ToolResultMessage('read_knowledge', metadata)
    elif surface == 'changed_body':
        metadata = deepcopy(result)
        metadata['chunks'][0]['text'] += '伪造追加文本'
        message = _ToolResultMessage('read_knowledge', metadata)
    else:
        message = canonical
        message['content'] += '变更canonical结果'
    deliver(reader, message)
    assert store.read('run', run_id).get('main_seen_knowledge_receipt_sha256', []) == []
    with pytest.raises(ValueError, match='成功主动作实际收到'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(selected_opinion(reader))))


def test_failed_main_never_grants_body_identity(reader):
    store, engine, run_id, result = reader
    class Failed(OfflineDelivery):
        async def complete(self, messages, timeout):
            raise TimeoutError('SYNTHETIC failed main')
    with pytest.raises(TimeoutError):
        deliver(reader, _ToolResultMessage('read_knowledge', result), Failed())
    assert not store.read('run', run_id).get('main_seen_knowledge_receipt_sha256')
    event = [event for event in store.read('run', run_id)['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'failed' and event['successful_knowledge_receipt_sha256'] == []


def test_unadopted_or_missing_sources_can_still_be_registered_without_citation(reader):
    store, engine, run_id, _ = reader
    value = opinion('没有资料，不能仅凭照片断代')
    asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(value)))
    assert store.read('run', run_id)['assessment'] == value


def test_existing_locator_check_precedes_gate_and_rejects_tampering(reader):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    value = selected_opinion(reader)
    value['knowledge_citations'][0]['locator'] = '伪造定位'
    with pytest.raises(ValueError, match='固定版本、段落与定位'):
        asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(value)))
    assert store.read('run', run_id)['assessment'] is None
