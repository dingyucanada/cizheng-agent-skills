"""Registered app phase schemas under the real native parser; no GPU or weights."""
import json
from copy import deepcopy

import pytest

from cizheng.agent import GUIDED_ACTION_PHASES, action_output_schema, decoder_schema_sha256
from integrations.spark_transformers import structured_generation as structured


@pytest.fixture
def real_parser():
    pytest.importorskip('lmformatenforcer', reason='Released optional native decoder environment required')
    return structured.make_parser


def consumes(parser, text):
    for character in text:
        if character not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(character)
    return parser.can_end()


def raw(tool, arguments=None):
    return json.dumps({'actions': [{'tool': tool, 'arguments': arguments or {}}]}, ensure_ascii=False)


@pytest.mark.parametrize('mode', ['plain', 'skills'])
@pytest.mark.parametrize('phase', GUIDED_ACTION_PHASES)
def test_real_parser_excludes_premature_build_preserves_read_and_original_schema(real_parser, mode, phase):
    schema = action_output_schema(mode, 'visual_research', True, phase)
    before = deepcopy(schema)
    envelope = {'type': 'json_schema', 'json_schema': {'name': 'cizheng_actions', 'strict': True, 'schema': schema}}
    validated = structured.validate_response_format(envelope)
    decoder = structured.bounded_parser_schema(validated['json_schema']['schema'])
    assert consumes(real_parser(decoder), raw('read_case'))
    assert consumes(real_parser(decoder), raw('review_dependencies'))
    assert not consumes(real_parser(decoder), raw('read_case', {'unexpected': 'data'}))
    build_allowed = phase == 'build_opinion_available'
    assert consumes(real_parser(decoder), raw('build_opinion')) is build_allowed
    assert structured.output_matches_schema(raw('build_opinion'), schema) is build_allowed
    assert schema == before == validated['json_schema']['schema']
    assert decoder_schema_sha256(schema) == decoder_schema_sha256(before)


@pytest.mark.parametrize('mode', ['plain', 'skills'])
def test_real_parser_cannot_emit_record_before_respond_and_keeps_decision_model_authored(real_parser, mode):
    schema = action_output_schema(mode, 'visual_research', True, 'respond_critic_required')
    decoder = structured.bounded_parser_schema(schema)
    # Tool selection is already rejected before reading any assessment arguments.
    prefix = '{"actions":[{"tool":"record_assessment"'
    parser = real_parser(decoder)
    for character in prefix:
        if character not in parser.get_allowed_characters():
            break
        parser = parser.add_character(character)
    else:
        pytest.fail('Premature record tool prefix was accepted')
    for decision in ('accept', 'reject', 'unresolved'):
        text = raw('respond_critic', {'dispositions': [{'issue_index': 0, 'decision': decision, 'reason': '软件测试理由'}]})
        assert consumes(real_parser(decoder), text)
        assert structured.output_matches_schema(text, schema)
    bad = raw('respond_critic', {'dispositions': [{'issue_index': 0, 'decision': 'host-decided', 'reason': '软件测试理由'}]})
    assert not consumes(real_parser(decoder), bad)
    assert not structured.output_matches_schema(bad, schema)
