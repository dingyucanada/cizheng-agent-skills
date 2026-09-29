"""Offline prompt and host-delivery contracts, not model or ceramic accuracy.

The images and text are synthetic. Real registered tools, delivery proofs and
compact expansion run; accepted observations and opinions remain model authored.
"""
import asyncio
import hashlib
import json
from copy import deepcopy

import httpx
import pytest

from cizheng import agent, schemas as S
from cizheng.agent import Engine, LocalModel, _ToolResultMessage
from cizheng.store import digest
from test_source_attribution_gate import reader, deliver, opinion
from test_vision_output_contract import FixedVisionProtocolModel, active


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Prompt contracts cannot invoke HTTP or a real model')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setattr(LocalModel, 'complete', forbidden)


PROMPT_VARIANTS = [(mode, compact, phase)
    for mode in ('plain', 'skills')
    for compact, phases in ((False, (None,)), (True, (None,) + agent.GUIDED_ACTION_PHASES))
    for phase in phases]


@pytest.mark.parametrize('mode,compact,phase', PROMPT_VARIANTS)
def test_visual_action_variants_keep_observation_source_and_evidence_boundaries(mode, compact, phase):
    prompt = agent.system_prompt(mode, 'visual_research', compact, phase)
    assert agent.PROMPT_PROFILE.system in prompt
    if agent.PROMPT_PROFILE.name == 'source-r2':
        assert '问题要求馆方记载与照片判断时须分列' in prompt
        assert '不能把馆方记录的器物归属直接迁移成本件结论' in prompt
        assert '只数当前可见面，不能由局部棱线或对称布局推总面数' not in prompt
        return
    assert '只数当前可见面，不能由局部棱线或对称布局推总面数' in prompt
    assert '器用、总面数或纹饰主题无法确认就明确记不清' in prompt
    assert '不能把视觉短句当已认证事实' in prompt
    assert '任务明确要求来源背景且已读正文有相关记载时' in prompt
    assert '来源所记对象或事项及适用边界' in prompt
    assert '删除全部引用不能替代完成该来源任务' in prompt
    assert '文字记载不能充当图像相似性的证据' in prompt
    assert '无关资料不强行引用' in prompt
    assert '没有采用资料陈述时仍可空引' in prompt
    assert '款识不能单独确证年代' in prompt
    assert '不预设未见细节或真品、仿品身份' in prompt


def test_vision_contract_describes_geometry_then_decoration_without_a_case_answer():
    # The retained r4 text is experimental; it is not the production default.
    text = agent.get_prompt_profile('r4').vision_system
    assert text.index('实际可见色彩') < text.index('关键轮廓转折、棱线或曲面') < text.index('纹饰部位、分区及可辨结构')
    assert '器形先用几何描述' in text
    assert '无法确认就明确记不清' in text
    assert '不猜人物身份、典故或寓意' in text
    assert '本轮未见不等于器物没有' in text
    for answer in ('花觚', '花篮', '六方', '笔筒', '康熙', '景德镇', '18.61.4', 'Met'):
        assert answer not in text
    schema = agent.vision_output_schema(['synthetic-photo'])
    fields = schema['properties']['observations']['items']['properties']
    assert {key: fields[key]['maxLength'] for key in ('visible', 'interpretation', 'limitation')} == {
        'visible': 48, 'interpretation': 24, 'limitation': 32}


def test_new_vision_prompt_reaches_real_tool_and_uncertainty_is_not_filled_by_host(tmp_path):
    visible = '合成色块边界可见，器用及纹饰细节记不清'
    model = FixedVisionProtocolModel(visible=visible, interpretation='', limitation='合成图无文物意义')
    store, case, engine, run_id = active(tmp_path, model)
    question = '问题名称与标签只是数据；不提供器类答案'
    result = asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
        media_ids=[case['media'][0]['id']], question=question)))
    run = store.read('run', run_id)
    messages = model.last_vision_messages

    assert messages[0] == {'role': 'system', 'content': agent.VISION_SYSTEM}
    assert question in messages[1]['content'][0]['text']
    schema = json.loads(messages[1]['content'][0]['text'].rsplit('\n', 1)[1])
    assert schema['properties']['observations']['items']['properties']['media_id']['enum'] == [case['media'][0]['id']]
    assert result['observations'][0]['visible'] == run['observations'][0]['visible'] == visible
    assert run['observations'][0]['interpretation'] == ''
    assert run['assessment'] is None
    assert run['versions']['vision_prompt_hash'] == hashlib.sha256(agent.VISION_SYSTEM.encode()).hexdigest()
    event = next(item for item in run['events'] if item['type'] == 'model')
    assert event['input_hash'] == digest(messages)


def test_guided_notice_separates_delivered_background_from_absent_image_reference(reader):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    run = store.read('run', run_id)
    before = deepcopy(run)
    context = Engine.guided_delivery_context(run, engine.compact_actions)

    assert context['source_reference_state'] == {
        'authorized_text_fragments_delivered_count': 1,
        'reference_images_observed_and_delivered_count': 0}
    assert agent.PROMPT_PROFILE.source_notice(context['source_reference_state']) in context['instruction']
    if agent.PROMPT_PROFILE.name == 'r4':
        assert '照片判断未能归属也应保留有用的来源背景' in context['instruction']
        assert '用完整短句分列来源所记事项与适用边界，并引用支持正文' in context['instruction']
        assert '文字来源与参照图片独立，缺参照图不等于无文字' in context['instruction']
        assert '已读文本无关或不足时说明具体不适用或缺项，不编引用' in context['instruction']
        assert '款识不能单独确证年代' in context['instruction']
    else:
        assert '文字来源与参照图片是两个独立状态' in context['instruction']
        assert '题目要求馆方记载与照片推断时，由你分列说明' in context['instruction']
    assert result['source']['document_id'] not in context['instruction']
    assert result['chunks'][0]['text'] not in context['instruction']
    assert 'read_index' not in context or context['read_index'] is None
    assert run == before == store.read('run', run_id)


def test_cited_background_coexists_with_three_unattributed_photo_claims_without_host_conclusions(reader):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    receipt = store.read('run', run_id)['read_knowledge'][0]
    value = opinion('本轮照片不足以区分归属，仍需补证')
    for claim in value['claims']:
        claim['candidate'] = '未能判断'
    value['reference_comparison'] = '来源正文指出仅检验送达，不提供陶瓷判断'
    citation = {'use': 'source_context', 'relevance': '合成来源背景，不作本件归属'}
    if engine.compact_actions:
        value['knowledge_citations'] = [citation | {'read_index': receipt['read_index']}]
        short = agent.CompactAssessment.model_validate(value)
        expanded, mappings = engine.expand_compact_assessment(run_id, short)
        assert mappings and all(claim['candidate'] == '未能判断' for claim in expanded['claims'])
        assessment = S.Assessment.model_validate(expanded)
    else:
        value['knowledge_citations'] = [citation | {key: receipt[key] for key in agent.COMPACT_METADATA_FIELDS}]
        assessment = S.Assessment.model_validate(value)
    expected = assessment.model_dump()
    asyncio.run(engine.tool(run_id, 'record_assessment', assessment))
    saved = store.read('run', run_id)['assessment']

    assert saved == expected
    assert saved['reference_ids'] == []
    assert saved['reference_comparison'] == value['reference_comparison']
    assert len(saved['knowledge_citations']) == 1
    assert all(claim['candidate'] == '未能判断' and claim['status'] == 'insufficient'
               and claim['support'] == [] and claim['conflict'] == [] for claim in saved['claims'])
    # This establishes legal provenance/layout, not semantic or professional accuracy.
