"""Optional isolated, offline NVIDIA NAT workflow invoked from the workbench."""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from .store import Problem, uid


def validate_result(result, case_id, body, run):
    """Fail closed on truncated, mismatched or internally inconsistent output.

    A completed workflow may report missing/mismatched references. Success means
    the audit ran; only its explicit status describes the reference result.
    """
    if (not isinstance(result, dict) or type(result.get('schema_version')) is not int
            or result['schema_version'] != 1
            or result.get('case_id') != case_id
            or result.get('case_revision') != body['expected_case_revision']
            or result.get('assessment_run_id') != run['id']
            or result.get('source_case_revision') != run['case_revision']
            or result.get('source_mode') != 'saved_assessment_run_snapshot'
            or result.get('mode') != 'deterministic_reference_integrity'
            or result.get('inference_performed') is not False
            or result.get('nvidia_verified_skill') is not False
            or result.get('expert_reviewed') is not False
            or result.get('review_required') is not True
            or result.get('snapshot_sha256') != run.get('versions', {}).get('knowledge_snapshot_sha256')):
        raise ValueError('result_boundary_mismatch')
    for field in ('snapshot_sha256', 'manifest_sha256', 'verify_request_sha256', 'result_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', str(result.get(field, ''))):
            raise ValueError('invalid_result_hash')
    unsigned = {k: v for k, v in result.items() if k != 'result_sha256'}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != result['result_sha256']:
        raise ValueError('result_hash_mismatch')
    usage = result.get('usage', {})
    events, checks = result.get('events'), result.get('checks')
    if (not isinstance(usage, dict) or usage.get('model_calls') != 0
            or usage.get('max_model_calls') != 0
            or type(usage.get('tool_calls')) is not int
            or not 1 <= usage['tool_calls'] <= 20
            or not isinstance(events, list) or len(events) != usage['tool_calls']
            or not isinstance(checks, list) or len(checks) > 64
            or not isinstance(result.get('read_evidence'), list)
            or not isinstance(result.get('limitations'), list)):
        raise ValueError('invalid_result_contract')
    statuses = []
    for check in checks:
        if (not isinstance(check, dict) or check.get('claim_support_assessed') is not False
                or check.get('status') not in ('valid_reference', 'metadata_only', 'reference_mismatch', 'not_read_in_this_run')
                or not isinstance(check.get('citation'), dict)
                or not isinstance(check.get('mismatched_fields'), list)):
            raise ValueError('invalid_reference_check')
        statuses.append(check['status'])
    expected_status = ('no_read_evidence' if not checks else 'reference_mismatch'
                       if any(s in ('reference_mismatch', 'not_read_in_this_run') for s in statuses)
                       else 'references_verified')
    if result.get('status') != expected_status:
        raise ValueError('result_status_mismatch')


class NvidiaAudit:
    def __init__(self, store, python=None):
        self.store = store
        self.python = python or os.getenv('CIZHENG_NAT_PYTHON', '')
        self.script = Path(__file__).resolve().parents[1] / 'scripts/nvidia-nat-call.py'

    @property
    def configured(self):
        return bool(self.python and Path(self.python).is_absolute()
                    and Path(self.python).is_file() and os.access(self.python, os.X_OK)
                    and self.script.is_file())

    async def execute(self, case_id, body):
        if not self.configured:
            raise Problem(503, 'NVIDIA NAT独立运行环境未配置；没有执行资料核查')
        def prepare(db):
            case = self.store.checked_case(db, case_id, body['expected_case_revision'])
            run = self.store.get(db, 'run', body['assessment_run_id'])
            if run['case_id'] != case_id or run['state'] not in ('ready', 'waiting_evidence') or not run.get('assessment'):
                raise Problem(422, 'NVIDIA报告核查只接受本案已完成意见的固定运行')
            record = {'id': uid('nvaudit'), 'case_id': case_id, 'case_revision': case['revision'],
                      'assessment_run_id': run['id'], 'source_case_revision': run['case_revision'],
                      'state': 'prepared', 'result': None,
                      'notice': '只核对已读知识引用的版本、哈希和定位，不验证结论或真伪。'}
            self.store.put(db, 'nvidia_audit', record)
            return record
        record = self.store.mutate('nvidia-audit:'+case_id, body, prepare)
        with self.store.tx() as db:
            current = self.store.get(db, 'nvidia_audit', record['id'])
            if current['state'] != 'prepared':
                return current
            run = self.store.get(db, 'run', current['assessment_run_id'])
            current['state'] = 'running'
            self.store.put(db, 'nvidia_audit', current)
        payload = {'case_id': case_id, 'expected_case_revision': body['expected_case_revision'],
                   'assessment_run_id': body['assessment_run_id'], 'queries': [], 'limit': 2}
        env = os.environ.copy()
        # The subprocess uses a separate interpreter. It never needs the visual
        # service, StepFun credential, session token, or a cloud telemetry key.
        for key in list(env):
            if any(word in key.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                env.pop(key)
        env.update(PYTHONDONTWRITEBYTECODE='1', NAT_TELEMETRY_ENABLED='false',
                   OTEL_SDK_DISABLED='true', LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                self.python, str(self.script), '--data-dir', str(self.store.root.resolve()),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env)
            stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=45)
            if process.returncode or len(stdout) > 1_000_000:
                raise ValueError('workflow_failed')
            result = json.loads(stdout)
            validate_result(result, case_id, body, run)
            with self.store.tx() as db:
                self.store.checked_case(db, case_id, body['expected_case_revision'])
                record = self.store.get(db, 'nvidia_audit', record['id'])
                record.update(state='succeeded', result=result)
                self.store.put(db, 'nvidia_audit', record)
            return record
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
                await process.communicate()
            self._fail(record['id'], 'interrupted')
            raise
        except Exception:
            if process and process.returncode is None:
                process.kill()
                await process.communicate()
            return self._fail(record['id'], 'failed')

    def _fail(self, identifier, state):
        with self.store.tx() as db:
            record = self.store.get(db, 'nvidia_audit', identifier)
            record.update(state=state, result=None,
                          error='NVIDIA资料核查未完成，请检查独立环境或资料版本；未修改研究意见。')
            self.store.put(db, 'nvidia_audit', record)
            return record
