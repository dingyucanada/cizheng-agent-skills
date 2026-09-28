"""Evaluate the evaluation contract, not ceramic expertise."""
import asyncio
import base64
import json
from pathlib import Path
import pytest
from cizheng.paired_eval import read_manifest, prepare, evaluate
from cizheng.agent import LocalModel
from test_closed_loop import photo


def manifest(tmp_path):
    (tmp_path / 'image.png').write_bytes(base64.b64decode(photo()))
    value = {'cases': [{'id': 'blind-1', 'object_id': 'vessel-1', 'question': '比较归属',
        'target_attribution': '待检主张', 'source_declaration': '未知；合成协议测试',
        'images': [{'path': 'image.png', 'view': '底足声明', 'edit_declaration': '合成仅测试'}]}], 'references': []}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(value))
    return path, value


def test_prepare_makes_no_inference_and_never_fabricates_result(tmp_path):
    path, _ = manifest(tmp_path)
    value = prepare(read_manifest(path))
    assert value['model_calls'] == 0 and value['semantic_evaluation'] == 'not_run'
    assert not value['answer_key_passed_to_model']


def test_missing_model_cannot_produce_benchmark(tmp_path):
    path, _ = manifest(tmp_path)
    out = tmp_path / 'results'
    with pytest.raises(ValueError, match='No local model'):
        asyncio.run(evaluate(read_manifest(path), out, LocalModel('', '')))
    assert not out.exists()


def test_prepare_decodes_before_creating_any_trial(tmp_path):
    path, _ = manifest(tmp_path)
    (tmp_path / 'image.png').write_bytes(b'not a PNG')
    with pytest.raises(ValueError, match='Invalid image'):
        read_manifest(path)


def test_prepare_rejects_same_object_duplicate_bytes_with_conflicting_views(tmp_path):
    path, value = manifest(tmp_path)
    (tmp_path / 'renamed.png').write_bytes((tmp_path / 'image.png').read_bytes())
    value['cases'][0]['images'].append({'path': 'renamed.png', 'view': '整体声明', 'edit_declaration': '合成仅测试'})
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='case blind-1: duplicate image bytes'):
        prepare(read_manifest(path))


@pytest.mark.parametrize('count', [0, 9])
def test_prepare_rejects_photo_count_outside_first_round_capacity(tmp_path, count):
    path, value = manifest(tmp_path)
    images = []
    for index in range(count):
        filename = f'unique-{index}.png'
        (tmp_path / filename).write_bytes(base64.b64decode(photo((index * 10, 20, 30))))
        images.append({'path': filename, 'view': '合成同一视角', 'edit_declaration': '协议测试'})
    value['cases'][0]['images'] = images
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='case blind-1:.*1–8'):
        prepare(read_manifest(path))


def test_prepare_accepts_the_first_round_photo_capacity(tmp_path):
    path, value = manifest(tmp_path)
    images = []
    for index in range(8):
        filename = f'unique-{index}.png'
        (tmp_path / filename).write_bytes(base64.b64decode(photo((index * 10, 20, 30))))
        images.append({'path': filename, 'view': '合成同一视角', 'edit_declaration': '协议测试'})
    value['cases'][0]['images'] = images
    path.write_text(json.dumps(value))
    prepared = prepare(read_manifest(path))
    assert len(prepared['cases'][0]['image_sha256']) == 8
    assert prepared['model_calls'] == 0


def test_paired_packets_resolve_images_and_preserve_failed_trials(tmp_path):
    from test_closed_loop import ScriptedModel
    from test_upgrade import PlainProtocolModel
    class BothModes:
        configured = True
        def identity(self):
            return {'provider': 'SYNTHETIC-TEST-ONLY', 'model': 'paired-contract'}
        async def complete(self, messages, timeout):
            impl = ScriptedModel() if 'discover_skills' in messages[0]['content'] else PlainProtocolModel()
            return await impl.complete(messages, timeout)
    path, _ = manifest(tmp_path)
    out = tmp_path/'paired'
    result = asyncio.run(evaluate(read_manifest(path), out, BothModes()))
    assert result['planned_trials'] == result['completed_trials'] == result['protocol_completed'] == 2
    assert result['semantic_evaluation'] == 'requires_blind_expert_review'
    assert {t['mode'] for t in result['trials']} == {'plain','skills'}
    for packet_file in (out/'blind').glob('*.json'):
        packet = json.loads(packet_file.read_text())
        ids = {im['media_id'] for im in packet['images']}
        assert {o['media_id'] for o in packet['observations']} <= ids
        for im in packet['images']:
            assert (packet_file.parent/im['path']).is_file()
    class Broken(BothModes):
        async def complete(self, messages, timeout):
            raise TimeoutError('SYNTHETIC ONLY')
    failed = asyncio.run(evaluate(read_manifest(path), tmp_path/'failed', Broken()))
    assert failed['planned_trials'] == failed['completed_trials'] == 2
    assert failed['protocol_completed'] == 0 and failed['excluded_trials'] == 0
    assert all(t['error'] and t['state']=='failed' for t in failed['trials'])


def test_cli_marks_failed_runs_nonzero_and_retains_results(tmp_path, monkeypatch):
    from cizheng import paired_eval
    path, _ = manifest(tmp_path)
    async def failed_run(manifest_value, output):
        output.mkdir()
        result = {'planned_trials': 2, 'protocol_completed': 0, 'trials': [
            {'state': 'failed', 'error': 'SYNTHETIC-TEST-ONLY'}]}
        (output / 'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(paired_eval, 'evaluate', failed_run)
    out = tmp_path / 'cli-result'
    with pytest.raises(SystemExit) as exc:
        paired_eval.main(['--manifest', str(path), '--output', str(out), '--run'])
    assert exc.value.code == 1
    assert json.loads((out / 'summary.json').read_text())['protocol_completed'] == 0


@pytest.mark.parametrize('problem', ['answer_key', 'duplicate_object', 'duplicate_image', 'escape', 'same_reference'])
def test_reject_leakage_or_invalid_inputs(tmp_path, problem):
    path, value = manifest(tmp_path)
    first = value['cases'][0]
    if problem == 'answer_key':
        first['correct_period'] = '不能给模型的答案'
    elif problem in ('duplicate_object','duplicate_image'):
        second = json.loads(json.dumps(first)); second['id'] = 'blind-2'
        if problem == 'duplicate_image': second['object_id'] = 'vessel-2'
        value['cases'].append(second)
    elif problem == 'escape':
        first['images'][0]['path'] = '/etc/hosts'
    else:
        value['references'] = [{'object_id': 'vessel-1', 'title': '测试', 'locator': '测试',
            'source_url': '', 'attribution': '测试', 'authority': '测试', 'permission': 'local_use_authorized',
            'notes': '测试', 'path': 'image.png'}]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_manifest(path)
