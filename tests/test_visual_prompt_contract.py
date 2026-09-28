"""Prompt logic contracts only; no model behavior or ceramic conclusion evidence."""
import pytest

from cizheng import agent


VISUAL_PROMPT_VARIANTS = [(mode, compact) for mode in ('plain', 'skills')
                          for compact in (False, True)]


@pytest.mark.parametrize('mode,compact', VISUAL_PROMPT_VARIANTS)
def test_source_statement_requires_delivered_body_citation_but_irrelevant_read_does_not(mode, compact):
    prompt = agent.system_prompt(mode, 'visual_research', compact)
    for clause in (
        '转述资料的年代、窑口或方法陈述时，必须在knowledge_citations引用支持该陈述的正文段落',
        '正文须已在本轮成功的主动作中实际送达',
        '检索摘要、来源卡和上一轮阅读不具引用资格',
        '未采用资料陈述时引用可为空，无关资料不强行引用',
        'use=source_context只表示该来源的陈述，不能充当已看图的器物参照',
        '不能据来源年代推出本器物年代',
    ):
        assert clause in prompt


@pytest.mark.parametrize('mode,compact', VISUAL_PROMPT_VARIANTS)
def test_critic_dispositions_address_individual_evidence_gaps_without_preselected_decisions(mode, compact):
    prompt = agent.system_prompt(mode, 'visual_research', compact)
    for clause in (
        '审查未看图只限制其图像断言的效力',
        '不能作为忽略来源不足、参照缺失或逻辑缺口的通用理由',
        '各疑点分别依据本轮实际图像、已读资料与证据缺口回应',
        'accept说明承认的缺口及相应修订',
        'reject给出可核验反证',
        'unresolved说明尚缺的具体证据及下一补证',
        '不得给不同疑点复制同一概括理由',
        '裁决由你依据证据选择，不预设结果',
        '不能把未看图的审查意见当真值',
    ):
        assert clause in prompt


@pytest.mark.parametrize('mode', ['plain', 'skills'])
def test_compact_source_selection_stays_model_authored_and_within_single_citation_limit(mode):
    prompt = agent.system_prompt(mode, 'visual_research', True)
    assert agent.COMPACT_INSTRUCTION in prompt
    for clause in (
        '最多一项；转述资料的年代、窑口或方法陈述时，必须选择支持该陈述的read_index',
        '只采用该项引用能支持的资料陈述',
        '尚未送达或被上下文省去的正文不能凭猜编号引用',
        '宿主只从该回执补齐固定来源编号、版本、哈希和定位，不补任何意见或理由',
        '主上下文的编号清单只列请求前本轮已取得资格的编号，不提供意见，也不替你选择引用',
        'reference_ids只能引用实际读参照记录、看其图像且已送达成功主动作的参照',
        '不以审查未看图统一搁置全部疑点；不预设裁决结果',
    ):
        assert clause in prompt


@pytest.mark.parametrize('mode', ['plain', 'skills'])
def test_visual_prompt_rules_do_not_change_documentary_prompt_route(mode):
    prompt = agent.system_prompt(mode, 'documentary_audit')
    assert agent.DOCUMENTARY_SYSTEM in prompt
    assert agent.SYSTEM not in prompt
    assert agent.COMPACT_INSTRUCTION not in prompt
    assert agent.system_prompt(mode, 'documentary_audit', True) == prompt


@pytest.mark.parametrize('mode,compact', VISUAL_PROMPT_VARIANTS)
def test_source_attribution_gate_has_finite_scope_and_keeps_source_context_separate(mode, compact):
    prompt = agent.system_prompt(mode, 'visual_research', compact)
    for clause in (
        '问题要求馆方记载与照片判断时须分列',
        'reference_comparison可陈述有引用的馆方来源上下文',
        'claims依本件图像与参照独立写候选和不足',
        '不能把馆方记录的器物归属直接迁移成本件结论',
        '明确采用资料记载却没有合格正文引用的record_assessment',
        '宿主不补引用或意见',
        '只识别有限的明示归因措辞，不验证引用语义或陈述真实性',
        '没有采用资料陈述时仍可空引',
    ):
        assert clause in prompt
