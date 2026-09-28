"""Response-contract tests only; no Laya weights or ceramic predictions."""
from copy import deepcopy
import pytest
from cizheng.laya_shadow import run_shadow

STATE = {'facts': {'missing_view': 'base', 'origin': 'unverified declaration'},
         'incumbent_next_step': 'request_evidence', 'review_required': True}


class ContractDouble:
    def system_one(self, state, questions, **kwargs):
        return {'answers': {'next_step': {'type': 'choice', 'choice': 'continue_analysis',
            'probabilities': {'continue_analysis': .98, 'request_evidence': .01, 'out_of_scope': .01},
            'confidence': .89, 'answer_confidence': .98}}}


def test_confident_shadow_cannot_override_missing_evidence_or_review():
    original = deepcopy(STATE)
    record = run_shadow(STATE, ContractDouble(), 'SYNTHETIC-CONTRACT-DOUBLE')
    assert record['disagrees'] and record['prediction']['choice'] == 'continue_analysis'
    assert record['authoritative_next_step'] == 'request_evidence' and record['review_required']
    assert STATE == original and not record['calibrated_for_ceramics']


@pytest.mark.parametrize('kind', ['timeout', 'nan', 'missing', 'wrong_choice'])
def test_shadow_failure_has_no_operational_effect(kind):
    class Broken(ContractDouble):
        def system_one(self, *args, **kwargs):
            if kind == 'timeout':
                raise TimeoutError()
            raw = super().system_one(*args, **kwargs)
            answer = raw['answers']['next_step']
            if kind == 'nan':
                answer['confidence'] = float('nan')
            elif kind == 'missing':
                del answer['answer_confidence']
            else:
                answer['choice'] = 'request_evidence'
            return raw
    record = run_shadow(STATE, Broken(), 'SYNTHETIC-CONTRACT-DOUBLE')
    assert record['error'] and record['prediction'] is None
    assert record['authoritative_next_step'] == 'request_evidence' and record['review_required']
