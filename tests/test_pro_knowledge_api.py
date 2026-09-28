"""Integrated local knowledge routes; synthetic text is not a ceramic benchmark."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from cizheng.agent import LocalModel
from cizheng.api import create_app
from cizheng.knowledge import search_snapshot, sha
from cizheng.review_client import StepFunClient


def api_document(**changes):
    body = {'title': 'API协议测试资料', 'institution': '本地API协议测试机构',
            'source_url': 'https://example.invalid/no-fetch/protocol', 'author': '协议测试作者',
            'year': '2026', 'locator': '仅测试来源定位', 'source_type': 'api_protocol_fixture',
            'rights': 'authorized_text', 'rights_note': '本测试原创文本，仅验证软件合同。',
            'scope': '仅测试API权限与版本', 'limitations': ['不是陶瓷参考资料或研究意见。'],
            'text': '蟠螭甲标记，仅用于检查旧版中文检索。\n\n不构成任何真伪结论。'}
    body.update(changes)
    return body


@pytest.fixture
def local_client(tmp_path, monkeypatch):
    """Fail immediately if a knowledge route attempts a model or network call."""
    import socket
    import urllib.request

    async def forbidden_async(*args, **kwargs):
        pytest.fail('Knowledge routes must not call models or remote HTTP services')

    def forbidden_sync(*args, **kwargs):
        pytest.fail('Knowledge routes must not open network connections')

    monkeypatch.delenv('CIZHENG_MODEL_URL', raising=False)
    monkeypatch.delenv('CIZHENG_MODEL', raising=False)
    monkeypatch.setattr(LocalModel, 'complete', forbidden_async)
    monkeypatch.setattr(StepFunClient, 'review', forbidden_async)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_async)
    monkeypatch.setattr(socket, 'create_connection', forbidden_sync)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden_sync)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        status = client.get('/api/status').json()
        assert not status['model_configured']
        headers = {'X-Cizheng-Token': status['session_token']}
        yield app, client, headers


def test_aliases_pagination_filters_and_versioned_search(local_client):
    app, client, headers = local_client
    versions = []
    identifiers = []
    for index, route in enumerate(('sources', 'documents', 'import')):
        response = client.post('/api/knowledge/' + route, headers=headers,
                               json=api_document(title=f'API协议资料{index}',
                                                 source_url=f'https://example.invalid/no-fetch/{index}'))
        assert response.status_code == 201, response.text
        payload = response.json()
        versions.append(payload['index_version'])
        identifiers.append(payload['source']['document_id'])
        assert payload['source']['review_status'] == 'pending'
        assert payload['source']['expert_reviewed'] is False
    assert len(set(versions)) == 3
    first = client.get('/api/knowledge/sources', params={
        'institution': '本地API协议测试机构', 'limit': 1, 'offset': 0}).json()
    second = client.get('/api/knowledge/sources', params={
        'institution': '本地API协议测试机构', 'limit': 1, 'offset': 1}).json()
    assert first['total'] == second['total'] == 3
    assert first['sources'][0]['document_id'] != second['sources'][0]['document_id']
    assert first['index_version'] == app.state.knowledge.index_version
    search = client.get('/api/knowledge/search', params={
        'q': '蟠螭甲', 'document_id': identifiers[0], 'rights': 'authorized_text',
        'source_type': 'api_protocol_fixture', 'institution': '本地API协议测试机构',
        'scope': 'API权限', 'review_status': 'pending', 'limit': 1})
    assert search.status_code == 200
    result = search.json()['results'][0]
    assert result['document_id'] == identifiers[0]
    assert result['document_revision'] == 1
    assert result['index_version'] == versions[-1]
    assert result['rank_score'] > 0
    assert result['rank_components']['exact_phrase'] is True
    assert len(result['text']) <= 800 and result['locator']
    detail = client.get('/api/knowledge/sources/' + identifiers[0]).json()
    chunk = next(chunk for chunk in detail['chunks'] if chunk['chunk_id'] == result['chunk_id'])
    assert result['chunk_sha256'] == chunk['chunk_sha256'] == sha({'text': chunk['text'], 'locator': chunk['locator']})
    assert result['document_sha256'] == detail['source']['document_sha256']
    assert client.get('/api/knowledge/search', params={'q': '蟠螭甲', 'rights': 'unknown'}).json()['results'] == []


@pytest.mark.parametrize('route', ['sources', 'documents', 'import'])
def test_mutations_use_session_and_rejections_do_not_change_index(local_client, route):
    app, client, headers = local_client
    before = app.state.knowledge.index_version
    path = '/api/knowledge/' + route
    assert client.post(path, json=api_document()).status_code == 403
    assert client.post(path, headers={'X-Cizheng-Token': 'incorrect'}, json=api_document()).status_code == 403
    assert client.post(path, headers=headers | {'Origin': 'https://cross-site.invalid'},
                       json=api_document()).status_code == 403
    assert app.state.knowledge.index_version == before
    invalid = api_document(rights='unknown', text='樗栎秘密拒绝正文。')
    assert client.post(path, headers=headers, json=invalid).status_code == 422
    assert client.post(path, headers=headers, json=api_document(rights_note='')).status_code == 422
    assert client.post(path, headers=headers, json=api_document(review_status='verified')).status_code == 422
    assert client.post(path, headers=headers, json=api_document(source_url='javascript:alert(1)')).status_code == 422
    assert client.post(path, headers=headers, json=api_document(text='字' * 100001)).status_code == 422
    assert app.state.knowledge.index_version == before
    assert client.get('/api/knowledge/search', params={'q': '樗栎'}).json()['results'] == []
    assert client.get('/api/knowledge/sources', params={'institution': '本地API协议测试机构'}).json()['total'] == 0


def test_api_cas_history_snapshot_and_restart(local_client, tmp_path):
    app, client, headers = local_client
    body = api_document(request_id='api-original-request')
    original = client.post('/api/knowledge/import', headers=headers, json=body).json()
    identifier = original['source']['document_id']
    frozen = app.state.knowledge.snapshot([identifier])
    assert client.post('/api/knowledge/documents', headers=headers, json=body).json() == original
    conflicting = client.post('/api/knowledge/import', headers=headers,
                              json=body | {'text': '同request不同正文'})
    assert conflicting.status_code == 409
    revised_body = api_document(document_id=identifier, expected_revision=1,
                                request_id='api-revision-request', text='黼黻乙标记，仅用于检查新版中文检索。')
    revised = client.post('/api/knowledge/sources', headers=headers, json=revised_body)
    assert revised.status_code == 201, revised.text
    second = revised.json()
    assert second['source']['revision'] == 2
    assert second['source']['document_sha256'] != original['source']['document_sha256']
    assert second['index_version'] != original['index_version']
    stale = client.post('/api/knowledge/documents', headers=headers,
                        json=revised_body | {'request_id': 'api-stale-request', 'text': '过期修改'})
    assert stale.status_code == 409
    old = client.get('/api/knowledge/sources/' + identifier, params={'revision': 1}).json()
    current = client.get('/api/knowledge/sources/' + identifier).json()
    assert current['revisions'] == [1, 2]
    assert old['source']['document_sha256'] == original['source']['document_sha256']
    assert old['chunks'] == frozen['sources'][0]['chunks']
    assert current['source']['document_sha256'] == second['source']['document_sha256']
    assert old['index_version'] == current['index_version'] == second['index_version']
    assert client.get('/api/knowledge/sources/' + identifier, params={'revision': 0}).status_code == 422
    assert client.get('/api/knowledge/sources/' + identifier, params={'revision': 999}).status_code == 404
    assert client.get('/api/knowledge/search', params={'q': '蟠螭甲'}).json()['results'] == []
    assert client.get('/api/knowledge/search', params={'q': '黼黻乙'}).json()['results'][0]['document_revision'] == 2
    assert search_snapshot(frozen, '蟠螭甲')['results'][0]['document_revision'] == 1
    # A second constructed app reads the same persisted DB without relying on
    # the first KnowledgeStore object. It does not run a second server lifespan.
    restarted = create_app(tmp_path)
    assert restarted.state.knowledge.source(identifier)['source'] == current['source']
    assert restarted.state.knowledge.index_version == second['index_version']


@pytest.mark.parametrize('rights', ['unknown', 'public_metadata'])
def test_api_metadata_body_isolation_and_explicit_history(local_client, rights):
    app, client, headers = local_client
    card_body = api_document(title='榑桑公开元数据卡', rights=rights, text='')
    added = client.post('/api/knowledge/sources', headers=headers, json=card_body)
    assert added.status_code == 201
    identifier = added.json()['source']['document_id']
    detail = client.get('/api/knowledge/sources/' + identifier).json()
    assert detail['chunks'] == [] and detail['source']['text_bytes'] == 0
    metadata = client.get('/api/knowledge/search', params={'q': '榑桑', 'document_id': identifier}).json()['results'][0]
    assert metadata['content_kind'] == 'metadata'
    assert metadata['text'].startswith('来源卡元数据（未引用正文）')
    invalid = card_body | {'text': '樗栎不应持久化的正文秘密'}
    assert client.post('/api/knowledge/import', headers=headers, json=invalid).status_code == 422
    assert not client.get('/api/knowledge/search', params={'q': '樗栎'}).json()['results']
    with sqlite3.connect(app.state.knowledge.path) as db:
        assert db.execute('SELECT count(*) FROM knowledge_chunks WHERE document_id=?', (identifier,)).fetchone()[0] == 0
        assert not db.execute('SELECT count(*) FROM knowledge_sources WHERE data LIKE ?', ('%樗栎%',)).fetchone()[0]
    # Admit explicitly licensed manual text in a new revision, then change the
    # current card back to metadata. Live body search excludes the old revision.
    permitted = client.post('/api/knowledge/documents', headers=headers, json=card_body | {
        'document_id': identifier, 'expected_revision': 1, 'rights': 'authorized_text',
        'text': '樗栎授权文字协议标记'}).json()
    assert permitted['source']['revision'] == 2
    assert client.get('/api/knowledge/search', params={'q': '樗栎'}).json()['results']
    reset = client.post('/api/knowledge/sources', headers=headers, json=card_body | {
        'document_id': identifier, 'expected_revision': 2})
    assert reset.status_code == 201
    assert client.get('/api/knowledge/search', params={'q': '樗栎'}).json()['results'] == []
    assert client.get('/api/knowledge/sources/' + identifier).json()['chunks'] == []
    historical = client.get('/api/knowledge/sources/' + identifier, params={'revision': 2}).json()
    assert historical['source']['rights'] == 'authorized_text'
    assert historical['chunks'][0]['text'] == '樗栎授权文字协议标记'


def test_real_api_concurrent_cas_has_single_winner(local_client):
    app, client, headers = local_client
    added = client.post('/api/knowledge/sources', headers=headers, json=api_document()).json()
    identifier = added['source']['document_id']
    barrier = Barrier(2)

    def revise(text):
        barrier.wait()
        return client.post('/api/knowledge/documents', headers=headers,
                           json=api_document(document_id=identifier, expected_revision=1, text=text))

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(revise, text) for text in ['黼黻甲并发正文', '黼黻乙并发正文']]
        responses = [request.result() for request in requests]
    assert sorted(response.status_code for response in responses) == [201, 409]
    winning = next(response.json() for response in responses if response.status_code == 201)
    detail = client.get('/api/knowledge/sources/' + identifier).json()
    assert detail['revisions'] == [1, 2]
    assert detail['source']['document_sha256'] == winning['source']['document_sha256']
    assert detail['index_version'] == winning['index_version'] == app.state.knowledge.index_version


def test_api_maximum_locator_is_valid_citation_and_inputs_are_bounded(local_client):
    from cizheng.schemas import KnowledgeCitation
    app, client, headers = local_client
    locator = '定位' * 500
    added = client.post('/api/knowledge/import', headers=headers, json=api_document(locator=locator))
    assert added.status_code == 201
    identifier = added.json()['source']['document_id']
    detail = client.get('/api/knowledge/sources/' + identifier).json()
    assert detail['source']['locator'] == locator
    result = client.get('/api/knowledge/search', params={'q': '蟠螭甲', 'document_id': identifier}).json()['results'][0]
    assert len(result['locator']) == 1000
    KnowledgeCitation(**{key: result[key] for key in (
        'document_id', 'document_revision', 'document_sha256', 'chunk_id', 'chunk_sha256', 'locator')},
        use='source_context', relevance='合成测试，仅验证引用字段。')
    for params in ({'q': ''}, {'q': ' '}, {'q': '!!!'}, {'q': '字' * 201}, {'q': '字', 'limit': 21}):
        assert client.get('/api/knowledge/search', params=params).status_code == 422
    assert client.get('/api/knowledge/sources', params={'limit': 501}).status_code == 422
