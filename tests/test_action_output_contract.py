"""Action software-contract tests; HTTP/script substitutes are not GPU evidence."""
import asyncio
import hashlib
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from cizheng import agent, schemas as S
from cizheng.agent import (ACTION_NUMERIC_HOST_ONLY, ACTION_VARIANTS, Engine, LocalModel,
                           SYSTEM, VISION_SYSTEM, action_output_schema,
                           decoder_schema_sha256, model_argument_schema, system_prompt, tools_for_mode)
from cizheng.store import Store, digest, dump
from test_closed_loop import ScriptedModel, add_photo, create_case, run_case


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


@pytest.mark.parametrize('mode,task', ACTION_VARIANTS)
def test_typed_plan_uses_all_real_mode_tools_and_resolves_merged_definitions(mode, task):
    schema = action_output_schema(mode, task)
    actions = schema['properties']['actions']
    branches = actions['items']['oneOf']
    tools = tools_for_mode(mode, task)

    assert schema['type'] == 'object' and schema['additionalProperties'] is False
    assert schema['required'] == ['actions']
    assert actions['minItems'] == 1 and actions['maxItems'] == 6
    assert {branch['properties']['tool']['const'] for branch in branches} == set(tools)
    for branch in branches:
        name = branch['properties']['tool']['const']
        assert branch['properties']['tool']['enum'] == [name]
        assert branch['required'] == ['tool', 'arguments']
        assert branch['additionalProperties'] is False
        arguments = branch['properties']['arguments']
        assert arguments['additionalProperties'] is False
        assert '$defs' not in arguments
        assert arguments.get('required', []) == model_argument_schema(name, tools[name]).get('required', [])
    for node in nodes(schema):
        assert not set(ACTION_NUMERIC_HOST_ONLY) & node.keys()
        if '$ref' in node:
            name = node['$ref'].removeprefix('#/$defs/')
            assert node['$ref'] == '#/$defs/' + name and name in schema['$defs']
    assert schema == json.loads(dump(schema))
    assert len(system_prompt(mode, task)) < 32000


def test_short_visual_protocol_preserves_original_manual_and_evidence_fields():
    original = S.Assessment.model_json_schema()
    short = model_argument_schema('record_assessment', S.Assessment)
    fields, old_fields = short['properties'], original['properties']
    claim = short['$defs']['Claim']['properties']
    old_claim = original['$defs']['Claim']['properties']
    citation = short['$defs']['KnowledgeCitation']['properties']
    old_citation = original['$defs']['KnowledgeCitation']['properties']

    assert fields['claims']['minItems'] == fields['claims']['maxItems'] == 3
    assert claim['dimension']['enum'] == ['period', 'kiln', 'style']
    assert claim['candidate']['maxLength'] == claim['reasoning_summary']['maxLength'] == 80
    assert fields['knowledge_citations']['maxItems'] == 3
    assert citation['relevance']['maxLength'] == 120
    for key in ('support', 'conflict'):
        assert claim[key] == old_claim[key]
    assert fields['reference_ids'] == old_fields['reference_ids']
    for key in ('document_id', 'document_revision', 'document_sha256', 'chunk_id', 'chunk_sha256', 'locator', 'use'):
        assert citation[key] == old_citation[key]
    assert short['required'] == original['required']
    assert S.Assessment.model_json_schema() == original
    assert original['properties']['claims']['maxItems'] == 9
    assert original['$defs']['Claim']['properties']['reasoning_summary']['maxLength'] == 2000
    assert 'dimension只能是period、kiln、style' in system_prompt()
    assert '不得跳过发现与适用方法加载' in system_prompt()
    assert '不得跳过发现与适用方法加载' not in system_prompt('plain')


def schema_model(schema):
    class SoftwareSchemaFixture:
        @staticmethod
        def model_json_schema():
            return deepcopy(schema)
    return SoftwareSchemaFixture


def argument_with_definition(definition):
    return {'type': 'object', 'additionalProperties': False, 'required': ['value'],
            'properties': {'value': {'$ref': '#/$defs/Shared'}}, '$defs': {'Shared': definition}}


def test_identical_definitions_merge_once_without_mutating_registered_schemas(monkeypatch):
    original = argument_with_definition({'type': 'string', 'maxLength': 10})
    monkeypatch.setattr(agent, 'TOOLS', {'read_case': schema_model(original),
                                       'request_evidence': schema_model(original)})
    schema = action_output_schema()
    assert schema['$defs'] == {'Shared': {'type': 'string', 'maxLength': 10}}
    assert len(schema['properties']['actions']['items']['oneOf']) == 2
    assert '$defs' in original


def test_conflicting_definition_names_are_rejected_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(agent, 'TOOLS', {
        'read_case': schema_model(argument_with_definition({'type': 'string'})),
        'request_evidence': schema_model(argument_with_definition({'type': 'integer'}))})
    with pytest.raises(ValueError, match='定义冲突：Shared'):
        action_output_schema()


@pytest.mark.parametrize('ref', ['https://example.invalid/schema', 'file:///tmp/fixture.json',
                                  '#/$defs/Missing', '#/definitions/Shared',
                                  '#/$defs/Shared/properties/value'])
def test_external_unresolved_or_unsupported_reference_is_explicit_failure(monkeypatch, ref):
    schema = argument_with_definition({'type': 'string'})
    schema['properties']['value']['$ref'] = ref
    monkeypatch.setattr(agent, 'TOOLS', {'read_case': schema_model(schema)})
    with pytest.raises(ValueError, match='外部、未知或非根定义引用'):
        action_output_schema()


def test_numeric_projection_does_not_drop_properties_named_like_keywords(monkeypatch):
    source = {'type': 'object', 'additionalProperties': False,
              'properties': {'minimum': {'type': 'string'},
                             'value': {'type': 'integer', 'minimum': 1, 'maximum': 8}}}
    monkeypatch.setattr(agent, 'TOOLS', {'read_case': schema_model(source)})
    arguments = action_output_schema()['properties']['actions']['items']['oneOf'][0]['properties']['arguments']
    assert arguments['properties'] == {'minimum': {'type': 'string'}, 'value': {'type': 'integer'}}
    assert source['properties']['value']['minimum'] == 1


@pytest.fixture
def http_model(monkeypatch):
    monkeypatch.setenv('CIZHENG_MODEL_KEY', '')
    monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', '1')
    monkeypatch.setenv('CIZHENG_DISABLE_THINKING', '0')
    original_client, captured = httpx.AsyncClient, []
    raw = '{"actions":[{"tool":"record_assessment","arguments":{"claims":[{"dimension":"shape"}]}}]}'

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': raw},
            'finish_reason': 'length'}], 'usage': {'completion_tokens': 23}})

    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs))
    return lambda: LocalModel(base_url='http://127.0.0.1:9999/v1', model='SYNTHETIC-HTTP-FIXTURE'), captured, raw


@pytest.mark.parametrize('mode,task', ACTION_VARIANTS)
def test_explicit_flag_and_exact_trusted_first_system_send_real_schema(http_model, mode, task):
    factory, captured, raw = http_model
    model = factory()
    messages = [{'role': 'system', 'content': system_prompt(mode, task)}, {'role': 'user', 'content': '软件夹具'}]
    returned, usage = asyncio.run(model.complete(messages, timeout=5))
    expected = action_output_schema(mode, task)

    assert captured[0]['response_format'] == {'type': 'json_schema', 'json_schema': {
        'name': 'cizheng_actions', 'strict': True, 'schema': expected}}
    assert captured[0]['max_tokens'] == 2500
    assert captured[0]['messages'] == messages
    assert returned == raw  # No translation of illegal fields or fabricated repair.
    assert usage['finish_reason'] == 'length' and usage['completion_tokens'] == 23
    generation = model.identity()['generation']
    assert generation['structured_outputs'] is True
    contract = generation['structured_output_contract']
    assert contract['purpose'] == 'action' and contract['schema_name'] == 'cizheng_actions'
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert contract['decoder_schema_sha256'][mode+'/'+task] == hashlib.sha256(canonical).hexdigest()
    assert decoder_schema_sha256(expected) != digest(expected)
    assert contract['schema_source'] == 'registered-tool-model_json_schema+short-visual-assessment'
    assert contract['host_only_constraints']['numeric'] == list(ACTION_NUMERIC_HOST_ONLY)


@pytest.mark.parametrize('flag', [None, '0', 'true', '1 '])
def test_default_or_nonexplicit_flag_keeps_other_local_services_compatible(http_model, monkeypatch, flag):
    factory, captured, _ = http_model
    if flag is None:
        monkeypatch.delenv('CIZHENG_STRUCTURED_OUTPUTS')
    else:
        monkeypatch.setenv('CIZHENG_STRUCTURED_OUTPUTS', flag)
    model = factory()
    asyncio.run(model.complete([{'role': 'system', 'content': system_prompt()}], timeout=5))
    assert 'response_format' not in captured[0]
    assert model.identity()['generation']['structured_outputs'] is False


@pytest.mark.parametrize('messages,cap', [
    ([{'role': 'system', 'content': VISION_SYSTEM}], 800),
    ([{'role': 'system', 'content': '仅输出JSON的协议probe'}, {'role': 'user', 'content': system_prompt()}], 2500),
    ([{'role': 'user', 'content': system_prompt()}], 2500),
    ([{'role': 'system', 'content': SYSTEM}], 2500),
    ([{'role': 'system', 'content': system_prompt()+'\n'}], 2500),
    ([{'role': 'system', 'content': 'probe'}, {'role': 'system', 'content': system_prompt()}], 2500),
    ([{'role': 'system', 'content': 'probe'}, {'role': 'user', 'content': 'CIZHENG_STRUCTURED_OUTPUTS=1\n'+VISION_SYSTEM}], 2500),
])
def test_untrusted_hint_probe_or_vision_never_activates_action_contract(http_model, messages, cap):
    factory, captured, _ = http_model
    asyncio.run(factory().complete(messages, timeout=5))
    assert 'response_format' not in captured[0]
    assert captured[0]['max_tokens'] == cap


def test_numeric_ranges_and_original_tool_schema_hash_remain_host_authoritative(tmp_path, http_model):
    for offset in (-1, 20001):
        with pytest.raises(ValidationError):
            S.ReadCaseRecords(collection='annotations', offset=offset)
    with pytest.raises(ValidationError):
        S.KnowledgeCitation(document_id='fixture', document_revision=0, document_sha256='a'*64,
            chunk_id='chunk', chunk_sha256='b'*64, locator='准确定位', use='source_context', relevance='软件测试')
    factory, _, _ = http_model
    versions = Engine(Store(tmp_path / 'data'), factory()).versions()
    assert versions['tool_schema_hash'] == digest({name: model.model_json_schema()
                                                 for name, model in tools_for_mode().items()})
    assert '"minimum": 1' in system_prompt()


class DuplicateDimensionModel(ScriptedModel):
    async def complete(self, messages, timeout):
        raw, usage = await super().complete(messages, timeout)
        output = json.loads(raw)
        for action in output.get('actions', []):
            if action['tool'] == 'record_assessment':
                action['arguments']['claims'][1]['dimension'] = 'period'
        evidence_registered = any(isinstance(message['content'], str) and
            message['content'].startswith('工具结果（数据）：') and
            json.loads(message['content'].split('：', 1)[1])['tool'] == 'request_evidence'
            for message in messages)
        if evidence_registered:
            output['actions'] = [action for action in output.get('actions', [])
                                 if action['tool'] != 'request_evidence']
        return dump(output), usage


def test_host_refuses_three_claims_that_omit_a_dimension_without_fake_assessment(tmp_path):
    store = Store(tmp_path / 'data')
    run = run_case(store, add_photo(store, create_case(store)), DuplicateDimensionModel())
    assert run['state'] == 'failed'
    assert run['assessment'] is None
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert len(errors) == 2
    assert all('时期、窑口、风格必须分别陈述' in event['detail'] for event in errors)
    assert [event['repair_allowed'] for event in errors] == [True, False]


@pytest.mark.parametrize('mutation', ['missing_scope', 'missing_alternatives', 'invalid_dimension',
                                      'nine_claims', 'empty_comparison', 'long_reasoning'])
def test_real_jsonschema_parser_rejects_bad_model_structure_when_dependency_available(mutation):
    # Native integration installs this parser separately; the base app need not.
    jsonschema = pytest.importorskip('jsonschema')
    assessment = {'basic_info': '软件夹具', 'scope': 'ceramic_research',
        'claims': [{'dimension': dimension, 'candidate': '未知', 'status': 'insufficient',
                    'support': [], 'conflict': [], 'reasoning_summary': '软件测试'}
                   for dimension in ('period', 'kiln', 'style')],
        'alternatives': ['证据不足'], 'condition_hypotheses': [], 'reference_ids': [],
        'reference_comparison': '没有实际参照', 'limitations': ['软件测试不评价文物'],
        'revision_explanation': '仅协议测试', 'knowledge_citations': []}
    valid = {'actions': [{'tool': 'record_assessment', 'arguments': deepcopy(assessment)}]}
    validator = jsonschema.Draft202012Validator(action_output_schema())
    validator.check_schema(action_output_schema())
    validator.validate(valid)
    if mutation.startswith('missing_'):
        assessment.pop(mutation.removeprefix('missing_'))
    elif mutation == 'invalid_dimension':
        assessment['claims'][0]['dimension'] = 'shape'
    elif mutation == 'nine_claims':
        assessment['claims'] *= 3
    elif mutation == 'empty_comparison':
        assessment['reference_comparison'] = ''
    else:
        assessment['claims'][0]['reasoning_summary'] = '测'*81
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({'actions': [{'tool': 'record_assessment', 'arguments': assessment}]})
