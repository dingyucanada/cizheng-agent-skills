"""Synthetic software-protocol regressions; no GPU, network, or ceramic accuracy."""
import asyncio
import json

import pytest

from cizheng.agent import Engine
from cizheng.store import Problem, Store, uid
from test_closed_loop import ScriptedModel, add_photo, create_case, run_case


def plan(*actions):
    return json.dumps({'actions': list(actions)}), {}


def read_case():
    return {'tool': 'read_case', 'arguments': {}}


def validation_errors(run):
    return [event for event in run['events'] if event['type'] == 'validation_error']


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'data')


def test_successful_complete_plan_allows_later_independent_repair(store):
    class SeparatedErrors(ScriptedModel):
        calls = 0

        async def complete(self, messages, timeout):
            self.calls += 1
            if self.calls == 1:
                return '{"actions":[', {}
            if self.calls == 3:
                return plan({'tool': 'read_case', 'arguments': {'unexpected': 'PRIVATE-INPUT'}})
            return await super().complete(messages, timeout)

    case = add_photo(store, create_case(store))
    run = run_case(store, case, SeparatedErrors())

    assert run['state'] == 'waiting_evidence', run['error']
    errors = validation_errors(run)
    assert [error['error_type'] for error in errors] == ['JSONDecodeError', 'ValidationError']
    assert [error['repair_allowed'] for error in errors] == [True, True]
    assert 'unexpected' in errors[1]['detail']
    assert 'PRIVATE-INPUT' not in json.dumps(errors)
    assert run['assessment'] is not None


def test_consecutive_errors_stop_and_preserve_both_actual_causes(store):
    class ConsecutiveErrors(ScriptedModel):
        calls = 0

        async def complete(self, messages, timeout):
            self.calls += 1
            if self.calls == 1:
                return '{"actions":[', {}
            return plan({'tool': 'not_registered', 'arguments': {}})

    run = run_case(store, add_photo(store, create_case(store)), ConsecutiveErrors())

    assert run['state'] == 'failed'
    assert run['model_calls'] == 2
    assert run['tool_calls'] == 0
    assert run['assessment'] is None
    errors = validation_errors(run)
    assert [error['error_type'] for error in errors] == ['JSONDecodeError', 'ValueError']
    assert [error['repair_allowed'] for error in errors] == [True, False]
    assert 'Expecting' in errors[0]['detail']
    assert errors[1]['detail'] == '工具不在注册表内'


def test_partially_successful_plan_does_not_reset_repair_guard(store):
    class PartialRepair(ScriptedModel):
        calls = 0

        async def complete(self, messages, timeout):
            self.calls += 1
            if self.calls == 1:
                return '{"actions":[', {}
            return plan(read_case(), {'tool': 'not_registered', 'arguments': {}})

    run = run_case(store, add_photo(store, create_case(store)), PartialRepair())

    assert run['state'] == 'failed'
    assert run['model_calls'] == 2
    assert run['tool_calls'] == 1
    assert [error['repair_allowed'] for error in validation_errors(run)] == [True, False]
    assert run['assessment'] is None


def test_separated_repairs_still_exhaust_original_model_budget(store):
    class AlternatingErrors(ScriptedModel):
        calls = 0

        async def complete(self, messages, timeout):
            self.calls += 1
            if self.calls % 2:
                return '{"actions":[', {}
            return plan(read_case())

    case = add_photo(store, create_case(store))
    model = AlternatingErrors()
    run = run_case(store, case, model)
    episode = store.read('episode', case['episode_id'])

    assert run['state'] == 'failed'
    assert run['error'] == '模型或工具调用预算耗尽'
    assert model.calls == run['model_calls'] == episode['model_calls'] == 12
    assert run['tool_calls'] == episode['tool_calls'] == 6
    assert len(validation_errors(run)) == 6
    assert all(error['repair_allowed'] for error in validation_errors(run))
    assert run['assessment'] is None


@pytest.mark.parametrize('status', [409, 503])
def test_nonrepairable_tool_failure_stops_without_retry(store, status):
    class ValidPlan(ScriptedModel):
        async def complete(self, messages, timeout):
            return plan(read_case())

    class FatalToolEngine(Engine):
        async def tool(self, run_id, name, args):
            raise Problem(status, 'SYNTHETIC fatal tool failure')

    case = add_photo(store, create_case(store))
    engine = FatalToolEngine(store, ValidPlan())
    start = store.start_run(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'mode': 'skills'}, engine.versions())
    asyncio.run(engine.execute(start['run_id']))
    run = store.read('run', start['run_id'])

    assert run['state'] == 'failed'
    assert run['error'] == 'SYNTHETIC fatal tool failure'
    assert run['model_calls'] == run['tool_calls'] == 1
    errors = validation_errors(run)
    assert len(errors) == 1
    assert errors[0]['error_type'] == 'Problem'
    assert errors[0]['repair_allowed'] is False
    assert errors[0]['detail'] == 'SYNTHETIC fatal tool failure'
    assert run['assessment'] is None
