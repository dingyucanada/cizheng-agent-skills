"""Error-only feedback and real Store/tool fail-stop contracts.

The planner below is explicitly synthetic. These tests do not establish model
quality, semantic support, image interpretation, or expert validation.
"""
import asyncio
import base64
import json
import time
from copy import deepcopy

import pytest

from cizheng import agent, schemas as S
from cizheng.agent import _ToolResultMessage
from cizheng.store import dump, uid
from test_source_attribution_gate import OfflineDelivery, deliver, opinion, reader


def source_assertion():
    value = opinion()
    value['reference_comparison'] = '馆方记载仅适用原编目对象，不适用本件'
    return value


def action(tool, arguments):
    return {'actions': [{'tool': tool, 'arguments': deepcopy(arguments)}]}


class SyntheticRepairPlanner(OfflineDelivery):
    def __init__(self, store, run_id, plans):
        self.store, self.run_id = store, run_id
        self.plans = deepcopy(plans)
        self.messages, self.raw_outputs, self.saved_before_calls = [], [], []

    async def complete(self, messages, timeout):
        assert self.plans, 'The host must not request an extra repair'
        self.messages.append(deepcopy(messages))
        self.saved_before_calls.append(deepcopy(self.store.read('run', self.run_id)['assessment']))
        raw = dump(self.plans.pop(0))
        self.raw_outputs.append(raw)
        return raw, {'finish_reason': 'stop'}


def execute(reader, plans):
    store, engine, run_id, _ = reader
    model = SyntheticRepairPlanner(store, run_id, plans)
    engine.model = model
    store.update_run(run_id, lambda run: run.update(state='queued', started_at=time.time()))
    asyncio.run(engine.execute(run_id))
    return store.read('run', run_id), model


def feedback(model):
    return json.loads(model.messages[1][-1]['content'])


def model_selected_citation(reader):
    store, engine, run_id, _ = reader
    receipt = store.read('run', run_id)['read_knowledge'][0]
    selected = ({'read_index': receipt['read_index']} if engine.compact_actions else
                {key: receipt[key] for key in agent.COMPACT_METADATA_FIELDS})
    return selected | {'use': 'source_context', 'relevance': '合成来源上下文，由测试模型选择'}


def assert_fail_stop(run, model):
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert run['state'] == 'failed' and run['assessment'] is None
    assert [event['repair_allowed'] for event in errors] == [True, False]
    assert len(model.messages) == 2
    assert model.saved_before_calls == [None, None]
    assert model.messages[1][-2] == {'role': 'assistant', 'content': model.raw_outputs[0]}


@pytest.mark.parametrize('text', ['尚需查阅馆方记载', '不能依据馆方资料判断',
                                 '没有文献记载', '图像资料显示蓝色色块'])
def test_feedback_does_not_expand_existing_finite_wording_guard(text):
    value = source_assertion()
    value['reference_comparison'] = text
    assert agent.explicit_knowledge_attributions(S.Assessment.model_validate(value)) == []


@pytest.mark.parametrize('suffix', ['', '，未采用资料陈述'])
def test_real_failure_shape_gets_precise_feedback_and_second_failure_stops(reader, suffix):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    first, second = source_assertion(), source_assertion()
    second['reference_comparison'] += suffix
    run, model = execute(reader, [action('record_assessment', first),
                                  action('record_assessment', second)])
    assert_fail_stop(run, model)
    diagnostic = feedback(model)
    assert diagnostic['policy'] == agent.SOURCE_ATTRIBUTION_POLICY
    assert diagnostic['violating_field'] == 'reference_comparison'
    assert diagnostic['violating_fields'] == ['reference_comparison']
    assert diagnostic['received_knowledge_citations'] == {'is_empty': True, 'count': 0}
    assert '追加“未采用”不能取消前述归因' in diagnostic['instruction']
    assert '不代表语义支持' in diagnostic['instruction']
    assert 'knowledge_citations' not in diagnostic  # No host-created replacement array.
    assert result['chunks'][0]['text'] not in dump(diagnostic)
    for key in agent.COMPACT_METADATA_FIELDS:
        if isinstance(result['chunks'][0][key], str):
            assert result['chunks'][0][key] not in dump(diagnostic)
    assert diagnostic['read_index_transport'] is engine.compact_actions
    assert diagnostic['eligible_knowledge_read_indexes'] == ([1] if engine.compact_actions else [])
    citation_fields = diagnostic['knowledge_citation_fields']
    assert citation_fields['use']['enum'] == ['method', 'comparison_context', 'source_context']
    assert citation_fields['relevance']['type'] == 'string'
    if engine.compact_actions:
        assert citation_fields['read_index'] == {'minimum': 1, 'type': 'integer'}
        assert citation_fields['relevance'] == {'minLength': 1, 'maxLength': 48, 'type': 'string'}
        assert diagnostic['knowledge_citation_required_fields'] == ['read_index', 'use', 'relevance']
    else:
        assert 'read_index' not in citation_fields
        assert citation_fields['document_revision']['type'] == 'integer'
        assert citation_fields['relevance']['maxLength'] == 120


def test_multiple_actual_fields_are_listed_without_inventing_a_single_location(reader):
    value = source_assertion()
    value['claims'][1]['reasoning_summary'] = '根据资料说明登记来源背景'
    run, model = execute(reader, [action('record_assessment', value)] * 2)
    assert_fail_stop(run, model)
    diagnostic = feedback(model)
    assert diagnostic['violating_field'] is None
    assert diagnostic['violating_fields'] == ['claims.1.reasoning_summary', 'reference_comparison']


@pytest.mark.parametrize('reader', [False], indirect=True, ids=['original-transport'])
def test_unreceived_nonempty_citation_is_reported_without_exporting_or_replacing_it(reader):
    value = source_assertion()
    value['knowledge_citations'] = [model_selected_citation(reader)]
    run, model = execute(reader, [action('record_assessment', value)] * 2)
    assert_fail_stop(run, model)
    diagnostic = feedback(model)
    assert diagnostic['violating_field'] == 'reference_comparison'
    assert diagnostic['received_knowledge_citations'] == {'is_empty': False, 'count': 1}
    assert diagnostic['eligible_knowledge_read_indexes'] == []
    assert value['knowledge_citations'][0]['document_id'] not in dump(diagnostic)


@pytest.mark.parametrize('surface', ['unread', 'read_not_delivered', 'foreign_case',
                                    'metadata_listing', 'copied_tool_json', 'changed_body'])
def test_ineligible_read_or_metadata_cannot_be_offered_or_used_in_a_repair(reader, surface):
    store, engine, run_id, result = reader
    chosen = model_selected_citation(reader)
    if surface == 'unread':
        store.update_run(run_id, lambda run: run.update(read_knowledge=[]))
    elif surface == 'foreign_case':
        foreign = store.create_case(S.NewCase(request_id=uid('req'), title='外案合成测试',
            question='仅检验隔离', source_declaration='合成协议').model_dump())
        media = store.read('run', run_id)['snapshot']['media'][0]
        _, image = store.blob(media['id'])
        foreign = store.add_evidence(foreign['id'], {'request_id': uid('req'),
            'expected_case_revision': foreign['revision'], 'filename': 'foreign-synthetic.png',
            'image_base64': base64.b64encode(image).decode(), 'view': '合成视角',
            'edit_declaration': '合成纯色', 'source': 'SYNTHETIC-TEST-ONLY'})['case']
        pin = store.read('run', run_id)['snapshot']['knowledge_links'][0]
        foreign = store.link_document(foreign['id'], {'request_id': uid('req'),
            'expected_case_revision': foreign['revision'], **pin})
        foreign_id = store.start_run(foreign['id'], {'request_id': uid('req'),
            'expected_case_revision': foreign['revision'], 'mode': 'plain'}, engine.versions('plain'))['run_id']
        store.update_run(foreign_id, lambda run: run.update(state='running', started_at=time.time()))
        foreign_result = asyncio.run(engine.tool(foreign_id, 'read_knowledge', S.ReadKnowledge(
            document_id=pin['document_id'], chunk_id=result['chunks'][0]['chunk_id'])))
        # The paragraph may exist in both snapshots; another case's actual tool result
        # still cannot substitute for this run's successful body delivery.
        for chunk in foreign_result['chunks']:
            chunk['run_id'] = foreign_id
        deliver(reader, _ToolResultMessage('read_knowledge', foreign_result))
    elif surface in ('metadata_listing', 'copied_tool_json', 'changed_body'):
        changed = deepcopy(result)
        if surface == 'metadata_listing':
            changed['chunks'][0].update(text='来源元数据列举', content_kind='metadata')
        elif surface == 'changed_body':
            changed['chunks'][0]['text'] += '未送达的追加正文'
        message = _ToolResultMessage('read_knowledge', changed)
        deliver(reader, dict(message) if surface == 'copied_tool_json' else message)
    first, second = source_assertion(), source_assertion()
    second['knowledge_citations'] = [chosen]
    run, model = execute(reader, [action('record_assessment', first),
                                  action('record_assessment', second)])
    assert_fail_stop(run, model)
    assert feedback(model)['eligible_knowledge_read_indexes'] == []
    assert feedback(model)['eligible_knowledge_read_indexes_total'] == 0
    assert run.get('main_seen_knowledge_receipt_sha256', []) == []


@pytest.mark.parametrize('reader', [True], indirect=True, ids=['compact-transport'])
@pytest.mark.parametrize('malformation', ['index_in_reasoning', 'string_index', 'wrong_field',
                                       'invalid_use', 'empty_relevance', 'array_as_text'])
def test_ambiguous_or_wrong_citation_fields_still_fail_without_second_feedback(reader, malformation):
    _, _, _, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    first, second = source_assertion(), source_assertion()
    second['knowledge_citations'] = [model_selected_citation(reader)]
    if malformation == 'index_in_reasoning':
        second['knowledge_citations'] = []
        second['reference_comparison'] += '，使用read_index=1'
    elif malformation == 'string_index':
        second['knowledge_citations'][0]['read_index'] = '1'
    elif malformation == 'wrong_field':
        second['knowledge_citations'][0]['index'] = second['knowledge_citations'][0].pop('read_index')
    elif malformation == 'invalid_use':
        second['knowledge_citations'][0]['use'] = '来源上下文'
    elif malformation == 'empty_relevance':
        second['knowledge_citations'][0]['relevance'] = ''
    else:
        second['knowledge_citations'] = 'read_index=1'
    run, model = execute(reader, [action('record_assessment', first),
                                  action('record_assessment', second)])
    assert_fail_stop(run, model)
    assert feedback(model)['eligible_knowledge_read_indexes'] == [1]


@pytest.mark.parametrize('repair', ['model_selected_citation', 'actually_remove_assertion'])
def test_one_legal_model_authored_repair_can_then_form_a_limited_opinion(reader, repair):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    first, second = source_assertion(), source_assertion()
    if repair == 'model_selected_citation':
        second['knowledge_citations'] = [model_selected_citation(reader)]
    else:
        second['reference_comparison'] = '没有可用的实物参照'
    run, model = execute(reader, [action('record_assessment', first),
                                  action('record_assessment', second), action('build_opinion', {})])
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert [event['repair_allowed'] for event in errors] == [True]
    assert run['state'] == 'waiting_evidence' and len(model.messages) == 3
    assert model.saved_before_calls[:2] == [None, None]
    expected = deepcopy(second)
    if engine.compact_actions and second['knowledge_citations']:
        receipt = run['read_knowledge'][0]
        expected['knowledge_citations'][0] = {key: receipt[key] for key in agent.COMPACT_METADATA_FIELDS} | {
            key: second['knowledge_citations'][0][key] for key in ('use', 'relevance')}
    assert run['assessment'] == expected
    assert model.saved_before_calls[2] == expected
    assert all(claim['status'] == 'insufficient' for claim in run['assessment']['claims'])
    assert first['knowledge_citations'] == [] and model.raw_outputs[0] == dump(action('record_assessment', first))


def test_unrelated_validation_keeps_existing_generic_feedback(reader):
    bad = source_assertion()
    bad['scope'] = 'ambiguous-scope'
    run, model = execute(reader, [action('record_assessment', bad)] * 2)
    assert_fail_stop(run, model)
    assert set(feedback(model)) == {'error', 'instruction'}


@pytest.mark.parametrize('reader', [True], indirect=True, ids=['compact-transport'])
@pytest.mark.parametrize('damage', ['duplicate_index', 'foreign_receipt', 'mutated_body',
                                  'invalid_range', 'snapshot_commitment', 'chunk_owner'])
def test_index_diagnostics_require_unique_canonical_delivered_frozen_body(reader, damage):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    def mutate(run):
        receipt = run['read_knowledge'][0]
        if damage == 'duplicate_index':
            run['read_knowledge'].append(deepcopy(receipt))
        elif damage == 'foreign_receipt':
            receipt['run_id'] = 'SYNTHETIC-foreign-run'
        elif damage == 'mutated_body':
            receipt['text'] += '变更文本'
            receipt['snippet_end'] += len('变更文本')
        elif damage == 'invalid_range':
            receipt['snippet_end'] += 1
        elif damage == 'snapshot_commitment':
            run['knowledge_snapshot']['snapshot_sha256'] = '0' * 64
        else:
            snapshot = run['knowledge_snapshot']
            snapshot['sources'][0]['chunks'][0]['document_revision'] += 1
            snapshot['snapshot_sha256'] = agent.digest({key: value for key, value in snapshot.items()
                                                       if key != 'snapshot_sha256'})
    store.update_run(run_id, mutate)
    if damage == 'chunk_owner':
        agent.validate_snapshot(store.read('run', run_id)['knowledge_snapshot'])
    diagnostic = engine.source_attribution_repair_feedback(run_id, S.Assessment.model_validate(source_assertion()))
    assert diagnostic['eligible_knowledge_read_indexes'] == []
    assert diagnostic['eligible_knowledge_read_indexes_total'] == 0
    assert result['chunks'][0]['text'] not in dump(diagnostic)
