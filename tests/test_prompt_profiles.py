"""Frozen prompt/profile isolation contracts; synthetic tools, no model quality."""
import hashlib
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from cizheng.prompt_profiles import PROFILES, get_prompt_profile


ROOT = Path(__file__).resolve().parents[1]
# Actual source-r2/r4 frozen agent.py text, not rewritten model answers.
COMPONENT_HASHES = {
    'source-r2': {
        'system': '0a06b9e95a9a41e63054fa40f23276aa0cd067414fdb0d2ee2fd5b06850af8cc',
        'vision_system': '71ae803c5558e49c14e7c86fecf8ba154453e8839797315b433d007e79511005',
        'compact_instruction': '120f7415c0d20fab366e12d31f307af1bd83236fec59b35867973cbd2ad44322',
        'guided_source_notice_template': '596a819594c0d9b205228139a66f388320eec64f613ad388478d2305a3fe46d0',
        'guided_record_instruction_template': '97b72bee27091f19d80a7e7a38e40d2312795e91097c598ee9375cc513fa5bd1',
        'guided_first_image_question': 'f2eb5b10c6edbedd6a7f4580fb0b350c886f1906bf26d9c8598fe5183393b34a',
    },
    'r4': {
        'system': '4e07c3a6e280408810a544265104c082f5851e0c6e1fd7a37d2970792b790532',
        'vision_system': '30da00191788747f298887902c97f5cd50dd508f47b52644ac97c38adab18a47',
        'compact_instruction': '34df273d8a3ee3b68cdf03b6a62228379739196c9f1d07f104716ffeca2d3a0a',
        'guided_source_notice_template': '231578d3f0c6faf9ee8d5f24d36c7672e6ae6832fd97e035f02f3a128476e47a',
        'guided_record_instruction_template': 'a788983d163b4ff5f99d8d7feb24b7c033cb0b7a4301310e1c78b40848be7a79',
        'guided_first_image_question': '172715500a590b404614a9db9a9cd4d85e83fd1d6a92557c775787b9d9e56b0c',
    },
}
SAVED_PHASE_PROMPT_HASHES = {
    'source-r2': {
        'plain/build_opinion_available': '7e6b6d42b69f5dd18e2c2827e96cbe3009db672faa0a67d4b1d955e163496fea',
        'plain/record_assessment_required': '0aaa5307042c6e1efd6b0df46f48a49d2a90139a31f13e259750cf80d99625ac',
        'plain/respond_critic_required': '23dd19c424fcd452d499c79db0fb73936cb4cdae2cbdda020f26a4e426caf24a',
        'skills/build_opinion_available': '2c31c80a78edb63a7b7fd17d4966d31ead07306e105e865b01285ccc5aeaf951',
        'skills/record_assessment_required': 'ad0571add96b45bb8ee0092ff867468ddbfe00077db2984e5730f9819c384869',
        'skills/respond_critic_required': '146838805a093512dc4f90294444602aab18a68548ac0e33cfdca2dbeb667ab5',
    },
    'r4': {
        'plain/build_opinion_available': 'ce336249431dd00838279e243bd2f40ac7c2e2b7fbb542e2eb35910b7ea3bf6c',
        'plain/record_assessment_required': 'd3e47d8b2aacd7c912175d3fb5a14e29406dc2b0c9525424e4ac905704a5b37e',
        'plain/respond_critic_required': '921d6313bf768f3270a636a12e2a6ec6f06ae82a409c2e92ad7b6f2b5ace18c4',
        'skills/build_opinion_available': 'f6e44d5a995452ab9c1d4cc24647bf1724c1dace99e98a1f7ac81723a146a04a',
        'skills/record_assessment_required': 'e72df8e35b996da9ab804f340b0c966a3a0a415d52967da6a082d5b1ac30179b',
        'skills/respond_critic_required': '7878c34a7ff7f882e051b75e8d3032839c170363c63fc34e31891e7850bc658e',
    },
}


@pytest.mark.parametrize('name', ['source-r2', 'r4'])
def test_profile_text_is_bound_to_real_frozen_components(name):
    profile = get_prompt_profile(name)
    identity = profile.identity()
    assert identity['component_sha256'] == COMPONENT_HASHES[name]
    contents = {key: getattr(profile, key) for key in COMPONENT_HASHES[name]}
    canonical = json.dumps(contents, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode()
    assert identity['content_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert identity['quality_validation'] == 'not_established'
    assert identity['experimental'] is (name == 'r4')
    identity['component_sha256']['system'] = 'caller mutation'
    assert profile.identity()['component_sha256'] == COMPONENT_HASHES[name]


def test_default_and_profile_definitions_are_immutable():
    assert get_prompt_profile().name == 'source-r2'
    with pytest.raises(FrozenInstanceError):
        get_prompt_profile().system = 'silently replace production'
    with pytest.raises(TypeError):
        PROFILES['source-r2'] = get_prompt_profile('r4')


@pytest.mark.parametrize('invalid', ['', 'R4', ' r4', 'r4 ', 'unknown', False, 4, ['r4']])
def test_invalid_profile_names_are_rejected(invalid):
    with pytest.raises(ValueError, match='CIZHENG_PROMPT_PROFILE只允许source-r2或r4'):
        get_prompt_profile(invalid)


PROBE = r'''
import asyncio, hashlib, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from cizheng import agent, schemas as S
from cizheng.store import dump
from test_vision_output_contract import FixedVisionProtocolModel, active

with tempfile.TemporaryDirectory(prefix='cizheng-profile-test-') as directory:
    model = FixedVisionProtocolModel(visible='合成测试蓝色色块', limitation='合成图无专业意义')
    store, case, engine, run_id = active(Path(directory), model)
    messages = [{'role': 'system', 'content': agent.system_prompt('skills', 'visual_research', True)},
                {'role': 'user', 'content': 'SYNTHETIC startup profile test'}]
    asyncio.run(engine._prepare_guided(run_id, messages))
    run = store.read('run', run_id)
    context = engine.guided_delivery_context(run, True)
    schemas = {}
    for mode, task in agent.ACTION_VARIANTS:
        for compact in (False, True):
            phases = (None,) + (agent.GUIDED_ACTION_PHASES if compact and task == 'visual_research' else ())
            for phase in phases:
                key = '/'.join(map(str, (mode, task, compact, phase)))
                schemas[key] = agent.decoder_schema_sha256(agent.action_output_schema(mode, task, compact, phase))
    phases = {mode+'/'+phase: hashlib.sha256(agent.system_prompt(mode, 'visual_research', True, phase).encode()).hexdigest()
              for mode in ('plain', 'skills') for phase in agent.GUIDED_ACTION_PHASES}
    before = agent.PROMPT_PROFILE.identity()
    os.environ['CIZHENG_PROMPT_PROFILE'] = 'r4' if before['name'] == 'source-r2' else 'source-r2'
    after_engine = agent.Engine(store, model)
    print(json.dumps({
        'profile': run['versions']['prompt_profile'],
        'vision_system_sha256': hashlib.sha256(model.last_vision_messages[0]['content'].encode()).hexdigest(),
        'first_question': model.last_vision_messages[1]['content'][0]['text'].split('\n', 1)[0],
        'notice': context['instruction'],
        'default_action_prompt_sha256': hashlib.sha256(agent.system_prompt('skills', 'visual_research', True).encode()).hexdigest(),
        'phase_prompt_sha256': phases,
        'decoder_sha256': schemas,
        'vision_schema_sha256': agent.decoder_schema_sha256(agent.vision_output_schema(['synthetic-photo'])),
        'schema_file_sha256': hashlib.sha256(Path('cizheng/schemas.py').read_bytes()).hexdigest(),
        'profile_after_environment_change': after_engine.versions()['prompt_profile'],
        'observations': [{'visible': o['visible'], 'interpretation': o['interpretation']} for o in run['observations']],
        'assessment': run['assessment'],
        'model_calls': run['model_calls'],
        'tool_calls': run['tool_calls'],
    }, ensure_ascii=False))
'''


def startup_probe(name, code=PROBE):
    environment = dict(os.environ)
    environment.pop('CIZHENG_PROMPT_PROFILE', None)
    if name is not None:
        environment['CIZHENG_PROMPT_PROFILE'] = name
    environment.update(PYTHONDONTWRITEBYTECODE='1', CIZHENG_GUIDED_WORKFLOW='1',
                       CIZHENG_COMPACT_ACTIONS='1')
    return subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                          env=environment, text=True, capture_output=True, timeout=30)


@pytest.fixture(scope='module')
def startup_profiles():
    result = {}
    for name in (None, 'source-r2', 'r4'):
        process = startup_probe(name)
        assert process.returncode == 0, process.stderr
        result[name] = json.loads(process.stdout)
    return result


@pytest.mark.parametrize('name', [None, 'source-r2', 'r4'])
def test_selected_profile_reaches_real_tool_run_versions_and_delivery_notice(startup_profiles, name):
    result = startup_profiles[name]
    selected = 'source-r2' if name is None else name
    profile = get_prompt_profile(selected)
    assert result['profile'] == profile.identity()
    assert result['vision_system_sha256'] == COMPONENT_HASHES[selected]['vision_system']
    assert result['phase_prompt_sha256'] == SAVED_PHASE_PROMPT_HASHES[selected]
    assert profile.guided_first_image_question in result['first_question']
    presence = {'authorized_text_fragments_delivered_count': 0,
                'reference_images_observed_and_delivered_count': 0}
    assert profile.source_notice(presence) in result['notice']
    assert result['profile_after_environment_change'] == result['profile']
    assert result['observations'] == [{'visible': '合成测试蓝色色块', 'interpretation': ''}]
    assert result['assessment'] is None
    assert result['model_calls'] == 1 and 0 < result['tool_calls'] <= 20


def test_experimental_prompt_never_appears_in_default_and_cannot_change_decoder(startup_profiles):
    default, explicit, experimental = (startup_profiles[key] for key in (None, 'source-r2', 'r4'))
    assert default == explicit
    assert default['profile']['content_sha256'] != experimental['profile']['content_sha256']
    assert default['default_action_prompt_sha256'] == '0e29d5d0f0d792d17237081edfcddf7c542c6417b786a8d5fbd917410e8cf8c5'
    assert experimental['default_action_prompt_sha256'] == 'adcb2c9c2572344cfef88251747fabf47e38cba95902fa9048609ecc7ddd718c'
    assert '照片判断未能归属也应保留有用的来源背景' not in default['notice']
    assert '照片判断未能归属也应保留有用的来源背景' in experimental['notice']
    assert '实际可见色彩' not in default['first_question']
    assert '实际可见色彩' in experimental['first_question']
    for field in ('decoder_sha256', 'vision_schema_sha256', 'schema_file_sha256'):
        assert default[field] == experimental[field]
    assert default['phase_prompt_sha256'] != experimental['phase_prompt_sha256']


@pytest.mark.parametrize('invalid', ['', 'unknown', ' r4'])
def test_invalid_environment_profile_refuses_startup(invalid):
    process = startup_probe(invalid, 'from cizheng import agent')
    assert process.returncode != 0
    assert 'CIZHENG_PROMPT_PROFILE只允许source-r2或r4' in process.stderr


@pytest.mark.parametrize('changed', ['name', 'content_sha256', 'component_sha256'])
def test_queued_profile_drift_stops_before_any_model_or_tool(tmp_path, changed):
    from cizheng import agent
    from test_vision_output_contract import FixedVisionProtocolModel, active
    model = FixedVisionProtocolModel()
    store, _, engine, run_id = active(tmp_path, model)
    def drift(run):
        run.update(state='queued', started_at=None)
        profile = run['versions']['prompt_profile']
        if changed == 'name':
            profile['name'] = 'r4' if profile['name'] == 'source-r2' else 'source-r2'
        elif changed == 'content_sha256':
            profile['content_sha256'] = '0' * 64
        else:
            profile['component_sha256']['guided_source_notice_template'] = '0' * 64
    store.update_run(run_id, drift)
    recorded = store.read('run', run_id)['versions']['prompt_profile']
    assert recorded != agent.PROMPT_PROFILE.identity()
    asyncio.run(engine.execute(run_id))
    stopped = store.read('run', run_id)
    assert stopped['state'] == 'failed'
    assert '运行提示配置或内容已变化' in stopped['error']
    assert stopped['versions']['prompt_profile'] == recorded
    assert stopped['model_calls'] == stopped['tool_calls'] == 0
    assert stopped['assessment'] is None and model.last_vision_messages is None
