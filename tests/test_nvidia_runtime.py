"""Application boundaries; subprocess doubles are not NVIDIA execution evidence."""
import asyncio
import hashlib
import json
import sys
import pytest
from cizheng.nvidia_runtime import NvidiaAudit
from cizheng.store import Store, uid, Problem
from test_closed_loop import create_case, add_photo, run_case


def setup(tmp_path):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    run = run_case(store, case)
    body = {'request_id': uid('req'), 'expected_case_revision': case['revision'],
            'assessment_run_id': run['id']}
    return store, case, run, body


def complete_result(case, run):
    """Synthetic complete no-citations result; not execution evidence."""
    result = {'schema_version': 1, 'run_id': 'nat_'+'a'*32,
              'case_id': case['id'], 'case_revision': case['revision'],
              'assessment_run_id': run['id'], 'source_case_revision': run['case_revision'],
              'source_mode': 'saved_assessment_run_snapshot',
              'mode': 'deterministic_reference_integrity', 'inference_performed': False,
              'nvidia_verified_skill': False, 'expert_reviewed': False, 'review_required': True,
              'snapshot_sha256': run['versions']['knowledge_snapshot_sha256'],
              'manifest_sha256': 'b'*64, 'verify_request_sha256': 'c'*64,
              'checks': [], 'status': 'no_read_evidence', 'read_evidence': [],
              'limitations': ['Synthetic software test only'],
              'usage': {'model_calls': 0, 'max_model_calls': 0, 'tool_calls': 1},
              'events': [{'tool': 'fixture'}]}
    return sign_result(result)


def sign_result(result):
    unsigned = {k: v for k, v in result.items() if k != 'result_sha256'}
    result['result_sha256'] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


def test_unconfigured_nat_does_not_execute(tmp_path, monkeypatch):
    store, case, _, body = setup(tmp_path)
    monkeypatch.delenv('CIZHENG_NAT_PYTHON', raising=False)
    with pytest.raises(Problem, match='未配置'):
        asyncio.run(NvidiaAudit(store).execute(case['id'], body))
    assert store.listing('nvidia_audit') == []


def test_cross_case_saved_report_is_rejected_before_subprocess(tmp_path):
    store, case, _, body = setup(tmp_path)
    other = add_photo(store, create_case(store), 'red')
    other_run = run_case(store, other)
    with pytest.raises(Problem, match='本案'):
        asyncio.run(NvidiaAudit(store, sys.executable).execute(case['id'], dict(body, assessment_run_id=other_run['id'])))
    assert store.listing('nvidia_audit') == []


def test_real_command_arguments_credentials_and_idempotence_boundary(tmp_path, monkeypatch):
    store, case, run, body = setup(tmp_path)
    calls = []
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY', 'SYNTHETIC-SENTINEL-KEY')
    class Process:
        returncode = 0
        async def communicate(self, data):
            value = json.loads(data)
            assert value['assessment_run_id'] == run['id'] and value['queries'] == []
            result = complete_result(case, run)
            return json.dumps(result).encode(), b'fixture-only'
    async def spawn(*args, **kwargs):
        calls.append(args)
        assert args[0] == sys.executable and args[1].endswith('/scripts/nvidia-nat-call.py')
        assert 'SYNTHETIC-SENTINEL-KEY' not in json.dumps(kwargs['env'])
        assert kwargs['env']['NAT_TELEMETRY_ENABLED'] == 'false'
        return Process()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    service = NvidiaAudit(store, sys.executable)
    first = asyncio.run(service.execute(case['id'], body))
    repeated = asyncio.run(service.execute(case['id'], body))
    assert first['state'] == 'succeeded' and repeated == first
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['incomplete', 'source_revision', 'source_mode',
                                   'snapshot', 'hash', 'status', 'model_calls'])
def test_semantic_and_hash_mismatches_are_not_success(tmp_path, monkeypatch, change):
    store, case, run, body = setup(tmp_path)
    result = complete_result(case, run)
    if change == 'incomplete':
        result = {k: result[k] for k in ('case_id', 'case_revision', 'assessment_run_id', 'inference_performed')}
    elif change == 'source_revision':
        result['source_case_revision'] += 1
    elif change == 'source_mode':
        result['source_mode'] = 'current_case_pinned_versions'
    elif change == 'snapshot':
        result['snapshot_sha256'] = 'd'*64
    elif change == 'status':
        result['status'] = 'references_verified'
    elif change == 'model_calls':
        result['usage']['model_calls'] = 1
    if change != 'hash':
        sign_result(result)
    else:
        result['result_sha256'] = '0'*64
    class Process:
        returncode = 0
        async def communicate(self, _):
            return json.dumps(result).encode(), b'not-for-export'
    async def spawn(*_, **__):
        return Process()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    record = asyncio.run(NvidiaAudit(store, sys.executable).execute(case['id'], body))
    assert record['state'] == 'failed' and record['result'] is None


@pytest.mark.parametrize('result', [b'not-json', b'{"inference_performed":true}',
                                  b'{"case_id":"other","case_revision":1,"inference_performed":false}'])
def test_invalid_subprocess_output_never_becomes_verified_report(tmp_path, monkeypatch, result):
    store, case, _, body = setup(tmp_path)
    class Process:
        returncode = 0
        async def communicate(self, _):
            return result, b'private stderr must not leak'
    async def spawn(*_, **__):
        return Process()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    record = asyncio.run(NvidiaAudit(store, sys.executable).execute(case['id'], body))
    assert record['state'] == 'failed' and record['result'] is None
    assert 'private stderr' not in json.dumps(record)


def test_restart_interrupts_only_pending_audits_without_changing_opinion(tmp_path):
    store, case, run, _ = setup(tmp_path)
    records = []
    with store.tx() as db:
        for state in ('prepared', 'running', 'succeeded', 'failed'):
            record = {'id': uid('nvaudit'), 'case_id': case['id'],
                      'assessment_run_id': run['id'], 'state': state, 'result': None}
            store.put(db, 'nvidia_audit', record)
            records.append(record)
    store.recover()
    assert [store.read('nvidia_audit', r['id'])['state'] for r in records] == [
        'interrupted', 'interrupted', 'succeeded', 'failed']
    assert store.read('run', run['id'])['assessment'] == run['assessment']


def test_case_reload_returns_only_its_saved_audit_records(tmp_path):
    from fastapi.testclient import TestClient
    from cizheng.api import create_app
    store, case, run, _ = setup(tmp_path)
    other = create_case(store)
    with store.tx() as db:
        for selected in (case, other):
            store.put(db, 'nvidia_audit', {'id': uid('nvaudit'), 'case_id': selected['id'],
                      'assessment_run_id': run['id'], 'state': 'failed', 'result': None})
    with TestClient(create_app(store.root)) as client:
        data = client.get('/api/cases/'+case['id']).json()
        assert len(data['nvidia_audits']) == 1
        assert data['nvidia_audits'][0]['case_id'] == case['id']
