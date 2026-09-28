"""Vision software-protocol checks with HTTP/model substitutes, never GPU accuracy."""
import asyncio
import hashlib
import json
import time

import httpx
import pytest

from cizheng import schemas as S
from cizheng.agent import Engine, LocalModel, SYSTEM, VISION_SYSTEM, vision_prompt
from cizheng.store import Store, digest, dump, uid
from test_closed_loop import ScriptedModel, add_photo, create_case, run_case


@pytest.fixture
def mock_local_model(monkeypatch):
    monkeypatch.setenv('CIZHENG_MODEL_KEY', '')
    monkeypatch.setenv('CIZHENG_DISABLE_THINKING', '0')
    monkeypatch.setenv('CIZHENG_MODEL_REVISION', 'SYNTHETIC-HTTP-FIXTURE')
    original_client = httpx.AsyncClient
    captured = []
    raw = '{"observations":['  # Deliberately truncated; no automatic JSON repair.

    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': raw},
            'finish_reason': 'length'}], 'usage': {'prompt_tokens': 7, 'completion_tokens': 800,
                                                 'total_tokens': 807}})

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr('cizheng.agent.httpx.AsyncClient', client)
    return LocalModel(base_url='http://127.0.0.1:9999/v1', model='SYNTHETIC-HTTP-FIXTURE'), captured, raw


@pytest.mark.parametrize('messages,cap', [
    ([{'role': 'system', 'content': VISION_SYSTEM}, {'role': 'user', 'content': 'observe'}], 800),
    ([{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': 'act'}], 2500),
    ([{'role': 'system', 'content': 'action'}, {'role': 'user', 'content': VISION_SYSTEM}], 2500),
    ([{'role': 'user', 'content': VISION_SYSTEM}], 2500),
    ([{'role': 'system', 'content': VISION_SYSTEM+' changed'}], 2500),
])
def test_http_phase_cap_uses_only_exact_first_system_and_preserves_finish_reason(mock_local_model, messages, cap):
    model, captured, raw = mock_local_model

    returned, usage = asyncio.run(model.complete(messages, timeout=5))

    assert captured[0]['max_tokens'] == cap
    assert captured[0]['messages'] == messages
    assert returned == raw
    assert usage['finish_reason'] == 'length'
    assert usage['completion_tokens'] == 800
    assert model.identity()['generation']['max_tokens_by_phase'] == {'action': 2500, 'vision': 800}


def test_dynamic_vision_schema_is_valid_json_and_has_no_observation_template():
    ids = ['media-software-one', 'media-software-two']
    prompt = vision_prompt(ids, '记录轮廓与颜色')
    schema = json.loads(prompt.rsplit('\n', 1)[1])
    observations = schema['properties']['observations']
    fields = observations['items']['properties']

    assert observations['minItems'] == observations['maxItems'] == 2
    assert fields['media_id']['enum'] == ids
    assert fields['region']['items'] == {'type': 'number', 'minimum': 0, 'maximum': 1}
    assert fields['region']['minItems'] == fields['region']['maxItems'] == 4
    assert {key: fields[key]['maxLength'] for key in ('visible', 'interpretation', 'limitation')} == {
        'visible': 48, 'interpretation': 24, 'limitation': 32}
    assert '直接可见现象' not in prompt
    assert '[x0' not in prompt and '...' not in prompt
    assert '每张只输出一条' in VISION_SYSTEM


def active(tmp_path, model):
    store = Store(tmp_path / 'data')
    case = add_photo(store, create_case(store))
    engine = Engine(store, model)
    start = store.start_run(case['id'], {'request_id': uid('req'),
        'expected_case_revision': case['revision'], 'mode': 'skills'}, engine.versions())
    store.update_run(start['run_id'], lambda run: run.update(state='running', started_at=time.time()))
    return store, case, engine, start['run_id']


class FixedVisionProtocolModel(ScriptedModel):
    def __init__(self, visible='合成测试蓝色色块', interpretation='', limitation='合成图无文物意义', repeat=1):
        self.visible, self.interpretation, self.limitation, self.repeat = visible, interpretation, limitation, repeat
        self.last_vision_messages = None

    async def complete(self, messages, timeout):
        if messages[0] == {'role': 'system', 'content': VISION_SYSTEM}:
            self.last_vision_messages = messages
            ids = [part['text'].split('=', 1)[1] for part in messages[1]['content']
                   if part['type'] == 'text' and part['text'].startswith('media_id=')]
            return dump({'observations': [{'media_id': media_id, 'region': [0, 0, 1, 1],
                'visible': self.visible, 'interpretation': self.interpretation, 'limitation': self.limitation}
                for media_id in ids for _ in range(self.repeat)]}), {'finish_reason': 'stop'}
        return await super().complete(messages, timeout)


@pytest.mark.parametrize('placeholder', ['直接可见现象', ' 直接可见现象 '])
def test_placeholder_cannot_become_stored_observation_or_failed_run_assessment(tmp_path, placeholder):
    # The old/global schema permits this text; the new guard is model-vision-only.
    assert S.Observation(media_id='software-id', region=[0, 0, 1, 1], visible=placeholder).visible == placeholder
    store = Store(tmp_path / 'data')
    run = run_case(store, add_photo(store, create_case(store)), FixedVisionProtocolModel(
        visible=placeholder, interpretation='', limitation=''))

    assert run['state'] == 'failed'
    assert run['observations'] == []
    assert run['assessment'] is None
    errors = [event for event in run['events'] if event['type'] == 'validation_error']
    assert len(errors) == 2
    assert all('模板占位' in error['detail'] for error in errors)
    assert [error['repair_allowed'] for error in errors] == [True, False]


@pytest.mark.parametrize('field,length', [('visible', 49), ('interpretation', 25), ('limitation', 33)])
def test_model_vision_short_sentence_limits_are_enforced_before_storage(tmp_path, field, length):
    model = FixedVisionProtocolModel(**{field: 'X'*length})
    store, case, engine, run_id = active(tmp_path, model)

    with pytest.raises(ValueError, match='短句长度上限'):
        asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
            media_ids=[case['media'][0]['id']], question='SYNTHETIC protocol check')))

    assert store.read('run', run_id)['observations'] == []
    assert store.read('run', run_id)['assessment'] is None


def test_one_observation_per_image_is_enforced_before_storage(tmp_path):
    store, case, engine, run_id = active(tmp_path, FixedVisionProtocolModel(repeat=2))

    with pytest.raises(ValueError, match='视觉输出结构无效'):
        asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
            media_ids=[case['media'][0]['id']], question='SYNTHETIC protocol check')))

    assert store.read('run', run_id)['observations'] == []


def test_real_tool_host_records_dynamic_prompt_hash_and_transport_finish_reason(tmp_path):
    model = FixedVisionProtocolModel()
    store, case, engine, run_id = active(tmp_path, model)
    media_id = case['media'][0]['id']
    result = asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
        media_ids=[media_id], question='SYNTHETIC protocol check')))
    run = store.read('run', run_id)
    call = next(event for event in run['events'] if event['type'] == 'model')
    prompt = model.last_vision_messages[1]['content'][0]['text']
    schema = json.loads(prompt.rsplit('\n', 1)[1])

    assert len(result['observations']) == len(run['observations']) == 1
    assert schema['properties']['observations']['items']['properties']['media_id']['enum'] == [media_id]
    assert call['input_hash'] == digest(model.last_vision_messages)
    assert call['usage']['finish_reason'] == 'stop'
    assert run['versions']['vision_prompt_hash'] == hashlib.sha256(VISION_SYSTEM.encode()).hexdigest()
    assert run['assessment'] is None  # Protocol acceptance alone creates no research opinion.


def test_http_truncation_reason_remains_in_run_record_without_creating_observations(tmp_path, mock_local_model):
    model, captured, raw = mock_local_model
    store, case, engine, run_id = active(tmp_path, model)

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(engine.tool(run_id, 'inspect_images', S.Inspect(
            media_ids=[case['media'][0]['id']], question='SYNTHETIC protocol check')))

    run = store.read('run', run_id)
    call = next(event for event in run['events'] if event['type'] == 'model')
    assert captured[0]['max_tokens'] == 800
    assert call['usage']['finish_reason'] == 'length'
    assert call['output_hash'] == hashlib.sha256(raw.encode()).hexdigest()
    assert run['observations'] == [] and run['assessment'] is None
