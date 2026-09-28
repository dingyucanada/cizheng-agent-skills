"""SYNTHETIC PROTOCOL ONLY: critic revision contracts, never ceramic accuracy.

No credential-bearing clients or network calls are constructed by these tests.
"""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from cizheng import schemas as S
from cizheng.agent import Engine, VISION_SYSTEM, system_prompt
from cizheng.api import create_app
from cizheng.review_client import ReviewService, prepare_review, suggested_packet
from cizheng.store import Store, uid
from test_closed_loop import ScriptedModel, add_photo, create_case, run_case


class SyntheticTextCritic:
    configured = True

    def identity(self):
        return {'provider': 'SYNTHETIC-PROTOCOL-ONLY', 'model': 'offline-critic-revision'}

    async def review(self, payload, timeout):
        return {'issues': [{'claim_dimension': d, 'concern': '合成协议疑点', 'reference_ids': []}
                           for d in ('period', 'style')],
                'suggested_evidence': '需要真实原图', 'limitations': ['未查看原图；合成协议测试']}, {'total_tokens': 11}


class SyntheticRevisionPlanner(ScriptedModel):
    def __init__(self, order='good'):
        self.order = order
        self.response_image_counts = []

    def identity(self):
        return {'provider': 'SYNTHETIC-PROTOCOL-ONLY', 'model': 'offline-critic-revision-planner'}

    async def complete(self, messages, timeout):
        if messages[0]['content'] == VISION_SYSTEM:
            return await super().complete(messages, timeout)
        results = [json.loads(m['content'].split('：', 1)[1]) for m in messages
                   if isinstance(m['content'], str) and m['content'].startswith('工具结果（数据）：')]

        def got(name):
            return [r['result'] for r in results if r['tool'] == name]

        if got('review_dependencies') and not got('respond_critic'):
            critic = got('review_dependencies')[-1]['text_critic']
            if critic:
                media_ids = [m['id'] for m in got('read_case')[0]['case']['media']]
                observations = [o for result in got('inspect_images') for o in result['observations']]
                seen = {o['media_id'] for o in observations}
                actions = []
                if self.order == 'early' and not seen:
                    actions = [{'tool': 'respond_critic', 'arguments': {}}]
                elif self.order in ('batch', 'repair') and not seen:
                    actions = [{'tool': 'inspect_images', 'arguments': {
                        'media_ids': media_ids, 'question': 'SYNTHETIC PROTOCOL ONLY'}},
                        {'tool': 'respond_critic', 'arguments': {}}]
                elif self.order in ('good', 'repair') and set(media_ids) <= seen:
                    actions = [{'tool': 'respond_critic', 'arguments': {}}]
                if actions:
                    self.response_image_counts.append(sum(p.get('type') == 'image_url'
                        for m in messages if isinstance(m['content'], list) for p in m['content']))
                    actions[-1]['arguments']['dispositions'] = [
                        {'issue_index': n, 'decision': decision,
                         'reason': '合成协议回应；不代表专业研判'}
                        for n, decision in enumerate(('accept', 'unresolved'))]
                    return json.dumps({'actions': actions}, ensure_ascii=False), {}
        return await super().complete(messages, timeout)


class SyntheticFailureModel(SyntheticRevisionPlanner):
    async def complete(self, messages, timeout):
        raise RuntimeError('SYNTHETIC PROTOCOL failure; no network')


def completed_protocol_case(store, extra_colors=()):
    case = add_photo(store, create_case(store))
    for color in extra_colors:
        case = add_photo(store, case, color)
    run = run_case(store, case, SyntheticRevisionPlanner())
    assert run['state'] == 'waiting_evidence'
    return store.read('case', case['id']), run


def approved_packet(store, case):
    body = suggested_packet(store, case['id'])
    body.pop('notice')
    body.update(request_id=uid('req'), expected_case_revision=case['revision'],
                permission='public', approval_basis='SYNTHETIC PROTOCOL ONLY text authorization')
    return prepare_review(store, case['id'], S.ReviewPacketIn.model_validate(body).model_dump())


def revised_protocol_case(store, extra_colors=()):
    case, first = completed_protocol_case(store, extra_colors)
    packet = approved_packet(store, case)
    critic = SyntheticTextCritic()
    review = asyncio.run(ReviewService(store, critic).execute(packet['id'],
        {'request_id': uid('req'), 'packet_hash': packet['packet_hash']}))
    assert review['state'] == 'succeeded'
    app = create_app(store.root, model=SyntheticRevisionPlanner(), review_client=critic)
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        response = client.post('/api/text-reviews/' + review['id'] + '/revise', headers=headers,
            json={'request_id': uid('req'), 'expected_case_revision': case['revision']})
        assert response.status_code == 200, response.text
    return response.json(), first, review


@pytest.mark.parametrize('order,state', [('good', 'waiting_evidence'), ('early', 'failed'),
                                        ('batch', 'failed'), ('skip', 'failed'), ('repair', 'waiting_evidence')])
def test_critic_response_requires_main_agent_image_round(tmp_path, order, state):
    store = Store(tmp_path)
    case, first, review = revised_protocol_case(store)
    planner = SyntheticRevisionPlanner(order)
    run = run_case(store, case, planner)
    assert run['state'] == state, run.get('error')
    assert run['text_review_snapshot']['id'] == review['id']
    assert run['text_review_snapshot']['packet_hash'] == review['packet_hash']
    assert store.read('run', first['id'])['assessment'] == first['assessment']
    if state == 'waiting_evidence':
        assert {m['id'] for m in case['media']} <= set(run['main_seen_media_ids'])
        assert len(run['critic_dispositions']) == 2
        assert planner.response_image_counts[-1] > 0
        assert {o['id'] for o in run['observations']}.isdisjoint(o['id'] for o in first['observations'])
    if order in ('batch', 'repair'):
        assert planner.response_image_counts[0] == 0
        assert any('同批预先决定' in e.get('detail', '') for e in run['events'])
    if order == 'repair':
        assert len(planner.response_image_counts) == 2


def test_failed_main_request_does_not_count_as_main_agent_image_review(tmp_path):
    store = Store(tmp_path)
    case, _, _ = revised_protocol_case(store)
    engine = Engine(store, SyntheticRevisionPlanner())
    rid = store.start_run(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'mode': 'skills'}, engine.versions())['run_id']
    store.update_run(rid, lambda r: r.update(state='running', started_at=time.time()))
    asyncio.run(engine.tool(rid, 'review_dependencies', S.Empty()))
    asyncio.run(engine.tool(rid, 'inspect_images', S.Inspect(
        media_ids=[m['id'] for m in case['media']], question='SYNTHETIC PROTOCOL ONLY')))
    messages = [{'role': 'system', 'content': system_prompt()}, {'role': 'user', 'content': 'SYNTHETIC PROTOCOL ONLY'}]
    engine.visual_context(rid, messages)
    engine.model = SyntheticFailureModel()
    with pytest.raises(RuntimeError):
        asyncio.run(engine.call(rid, messages, 'action'))
    assert not store.read('run', rid).get('main_seen_media_ids')
    dispositions = S.RespondCritic(dispositions=[{'issue_index': n, 'decision': 'unresolved',
        'reason': '合成协议测试'} for n in range(2)])
    with pytest.raises(ValueError, match='主 Agent'):
        asyncio.run(engine.tool(rid, 'respond_critic', dispositions))
    engine.model = SyntheticRevisionPlanner()
    asyncio.run(engine.call(rid, messages, 'action'))
    assert asyncio.run(engine.tool(rid, 'respond_critic', dispositions))['recorded']


def test_run_input_hash_includes_late_critic_snapshot(tmp_path):
    store = Store(tmp_path)
    case, first = completed_protocol_case(store)
    packet = approved_packet(store, case)

    class GatedCritic(SyntheticTextCritic):
        def __init__(self):
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def review(self, payload, timeout):
            self.started.set()
            await self.release.wait()
            return await super().review(payload, timeout)

    async def compare_interleaving():
        critic = GatedCritic()
        pending = asyncio.create_task(ReviewService(store, critic).execute(packet['id'],
            {'request_id': uid('req'), 'packet_hash': packet['packet_hash']}))
        await critic.started.wait()
        revised = store.add_correction(case['id'], {'request_id': uid('req'),
            'expected_case_revision': case['revision'], 'assessment_run_id': first['id'],
            'review_method': 'image', 'correction': 'SYNTHETIC PROTOCOL correction',
            'basis': 'SYNTHETIC PROTOCOL ONLY'}, 'SYNTHETIC reviewer')
        engine = Engine(store, SyntheticFailureModel())
        versions = engine.versions()
        body = {'request_id': uid('req'), 'expected_case_revision': revised['revision'], 'mode': 'skills'}
        rid1 = store.start_run(case['id'], body, versions)['run_id']
        await engine.execute(rid1)
        assert store.read('run', rid1)['state'] == 'failed'
        critic.release.set()
        review = await pending
        assert review['state'] == 'succeeded'
        rid2 = store.start_run(case['id'], dict(body, request_id=uid('req')), versions)['run_id']
        before, after = store.read('run', rid1), store.read('run', rid2)
        assert before['text_review_snapshot'] is None
        assert after['text_review_snapshot']['id'] == review['id']
        assert before['input_hash'] != after['input_hash']

    asyncio.run(compare_interleaving())


def test_main_agent_review_accumulates_only_images_it_actually_receives(tmp_path):
    store = Store(tmp_path)
    case, _, _ = revised_protocol_case(store, extra_colors=('red', 'white', 'green', 'yellow'))
    media_ids = [m['id'] for m in case['media']]
    assert len(media_ids) == 5
    engine = Engine(store, SyntheticRevisionPlanner())
    rid = store.start_run(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
        'mode': 'skills'}, engine.versions())['run_id']
    store.update_run(rid, lambda r: r.update(state='running', started_at=time.time()))
    asyncio.run(engine.tool(rid, 'review_dependencies', S.Empty()))
    for batch in (media_ids[:4], media_ids[4:]):
        asyncio.run(engine.tool(rid, 'inspect_images', S.Inspect(
            media_ids=batch, question='SYNTHETIC PROTOCOL ONLY five-image coverage')))
    messages = [{'role': 'system', 'content': system_prompt()},
                {'role': 'user', 'content': 'SYNTHETIC images'}, {'role': 'user', 'content': 'SYNTHETIC action'}]
    engine.visual_context(rid, messages)
    asyncio.run(engine.call(rid, messages, 'action'))
    assert set(store.read('run', rid)['main_seen_media_ids']) == set(media_ids[1:])
    dispositions = S.RespondCritic(dispositions=[{'issue_index': n, 'decision': 'unresolved',
        'reason': 'SYNTHETIC PROTOCOL ONLY'} for n in range(2)])
    with pytest.raises(ValueError, match='主 Agent'):
        asyncio.run(engine.tool(rid, 'respond_critic', dispositions))
    asyncio.run(engine.tool(rid, 'inspect_images', S.Inspect(
        media_ids=media_ids[:1], question='SYNTHETIC PROTOCOL ONLY missing main frame')))
    engine.visual_context(rid, messages)
    asyncio.run(engine.call(rid, messages, 'action'))
    assert set(store.read('run', rid)['main_seen_media_ids']) == set(media_ids)
    assert asyncio.run(engine.tool(rid, 'respond_critic', dispositions))['recorded']
