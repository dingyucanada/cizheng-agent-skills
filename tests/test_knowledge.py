"""Synthetic protocol text is not a ceramic corpus or an accuracy benchmark."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from cizheng.api import create_app
from cizheng.knowledge import (CHUNK_CHARS, INDEXER_VERSION, KnowledgeStore,
                               read_snapshot, search_snapshot, sha)
from cizheng.knowledge_api import create_knowledge_router
from cizheng.store import Problem


def document(**changes):
    value = {'title': '测试协议资料：青花觚', 'institution': '合成测试机构',
             'source_url': 'https://example.org/protocol-only', 'locator': '测试页第2节',
             'author': '本地协议测试', 'year': '2026', 'rights': 'authorized_text',
             'rights_note': '本测试原创文本，无真实陶瓷研究内容。', 'scope': '仅测试中文检索协议',
             'source_type': 'test_fixture', 'text': '青花觚的口沿测试段落。此处只有协议测试内容。\n\n胎釉观察测试段落。不能作为真伪结论。',
             'limitations': ['合成测试文本，不是文物资料。']}
    value.update(changes)
    return value


def test_persisted_stable_ids_dedup_and_restart(tmp_path):
    first = KnowledgeStore(tmp_path)
    empty_version = first.index_version
    added = first.add_document(document())
    source = added['source']
    assert added['index_version'] != empty_version
    assert first.path.name == 'knowledge.sqlite3'
    assert first.path.stat().st_mode & 0o777 == 0o600
    restarted = KnowledgeStore(tmp_path)
    assert restarted.index_version == added['index_version']
    duplicate = restarted.add_document(document())
    assert duplicate['deduplicated'] is True
    assert duplicate['source']['document_id'] == source['document_id']
    assert duplicate['source']['revision'] == 1
    assert duplicate['index_version'] == added['index_version']
    detail = restarted.source(source['document_id'])
    assert len(detail['chunks']) == 2
    assert restarted.list_sources()['total'] == 1
    assert detail['source']['review_status'] == 'pending'
    assert detail['source']['expert_reviewed'] is False


def test_revision_and_immutable_paragraph_citations(tmp_path):
    store = KnowledgeStore(tmp_path)
    first = store.add_document(document())
    identifier = first['source']['document_id']
    old = store.source(identifier)
    updated = store.add_document(document(document_id=identifier, expected_revision=1,
                                          title='修改后的测试标题', text='口沿新的授权测试段落。'))
    assert updated['source']['document_id'] == identifier
    assert updated['source']['revision'] == 2
    assert updated['source']['document_sha256'] != first['source']['document_sha256']
    assert updated['index_version'] != first['index_version']
    assert store.source(identifier, 1)['chunks'] == old['chunks']
    current = store.source(identifier)
    assert current['revisions'] == [1, 2]
    assert current['chunks'][0]['chunk_id'] != old['chunks'][0]['chunk_id']
    for chunk in old['chunks'] + current['chunks']:
        assert chunk['chunk_sha256'] == sha({'text': chunk['text'], 'locator': chunk['locator']})
        assert chunk['document_id'] == identifier
        assert chunk['locator'].startswith('测试页第2节')
    assert not store.search('胎釉')['results']
    with pytest.raises(Problem, match='版本已更新'):
        store.add_document(document(document_id=identifier, expected_revision=1))
    with pytest.raises(Problem, match='修订需'):
        store.add_document(document(text='改变正文但未明确修订'))


def test_chinese_rank_filters_locator_and_snapshot_same_algorithm(tmp_path):
    store = KnowledgeStore(tmp_path)
    added = store.add_document(document())
    store.add_document(document(title='无关英文测试', institution='别的机构',
                                source_url='https://example.org/other', text='word-only paragraph'))
    snapshot = store.snapshot()
    live = store.search('胎釉')
    frozen = search_snapshot(snapshot, '胎釉')
    assert live['results']
    result = live['results'][0]
    assert result['text'].startswith('胎釉')
    assert result['document_id'] == added['source']['document_id']
    assert result['chunk_id'] in [chunk['chunk_id'] for chunk in store.source(result['document_id'])['chunks']]
    assert result['document_sha256'] == added['source']['document_sha256']
    assert result['index_version'] == added['index_version'] or result['index_version'] == store.index_version
    assert result['rank_score'] > 0 and 'confidence' not in result
    assert '不是可靠性' in live['rank_notice']
    assert frozen['results'][0]['rank_score'] == result['rank_score']
    assert frozen['results'][0]['snapshot_sha256'] == snapshot['snapshot_sha256']
    assert store.search('胎釉', {'institution': '别的机构'})['results'] == []
    assert store.search('青花觚', {'institution': '合成测试机构'})['results']
    assert store.search('胎釉', {'scope': '测试中文'})['results']
    assert store.search('word', {'source_type': 'test_fixture'})['results']
    assert store.list_sources({'institution': '别的机构'})['total'] == 1
    with pytest.raises(Problem, match='未知资料筛选'):
        store.search('胎釉', {'probability': 'verified'})


@pytest.mark.parametrize('rights', ['unknown', 'public_metadata'])
def test_unknown_or_public_permission_never_accepts_body(tmp_path, rights):
    store = KnowledgeStore(tmp_path)
    with pytest.raises(Problem, match='仅允许来源卡'):
        store.add_document(document(rights=rights, text='秘密正文关键词'))
    assert store.list_sources()['sources'] == []
    added = store.add_document(document(rights=rights, text='', title='公开元数据青花觚'))
    identifier = added['source']['document_id']
    assert store.source(identifier)['chunks'] == []
    assert store.snapshot()['sources'][0]['chunks'] == []
    assert not store.search('秘密正文关键词')['results']
    result = store.search('青花觚')['results'][0]
    assert result['content_kind'] == 'metadata'
    assert result['text'].startswith('来源卡元数据（未引用正文）')
    assert read_snapshot(store.snapshot(), identifier)['chunks'][0]['content_kind'] == 'metadata'
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT count(*) FROM knowledge_chunks').fetchone()[0] == 0
        assert not any('秘密正文关键词' in row[0] for row in db.execute('SELECT data FROM knowledge_sources'))


@pytest.mark.parametrize('changes', [
    {'rights_note': ''}, {'review_status': 'verified'}, {'expert_reviewed': True},
    {'source_url': 'javascript:alert(1)'}, {'source_url': 'file:///etc/passwd'},
    {'source_url': 'https://user:password@example.org/private'},
    {'title': ' '}, {'text': '字' * 100001},
    {'chunks': [{'text': '字' * (CHUNK_CHARS + 1)}], 'text': ''},
    {'chunks': [{'text': '短句'}] * 201, 'text': ''},
    {'chunks': [{'text': ' '}] , 'text': ''},
    {'text': '正文', 'chunks': [{'text': '另一正文'}]},
    {'limitations': ['字' * 1501]},
])
def test_permission_metadata_and_size_validation(tmp_path, changes):
    store = KnowledgeStore(tmp_path)
    with pytest.raises(Problem):
        store.add_document(document(**changes))
    assert store.list_sources()['total'] == 0


def test_fixed_snapshot_reads_old_content_and_detects_tampering(tmp_path):
    store = KnowledgeStore(tmp_path)
    added = store.add_document(document(text='冻结快照原始正文。'))
    identifier = added['source']['document_id']
    frozen = store.snapshot([identifier])
    chunk_id = frozen['sources'][0]['chunks'][0]['chunk_id']
    store.add_document(document(document_id=identifier, expected_revision=1, text='后来修改的正文。'))
    assert not store.search('原始')['results']
    assert search_snapshot(frozen, '原始')['results'][0]['document_revision'] == 1
    citation = read_snapshot(frozen, identifier, chunk_id)['chunks'][0]
    assert citation['text'] == '冻结快照原始正文。'
    assert citation['document_sha256'] == added['source']['document_sha256']
    assert store.snapshot([])['sources'] == []
    with pytest.raises(Problem, match='不存在'):
        store.snapshot(['ksrc_' + 'a' * 24])
    with pytest.raises(Problem, match='段落不在'):
        read_snapshot(frozen, identifier, 'not-existing')
    with pytest.raises(Problem, match='固定知识快照'):
        read_snapshot(frozen, 'ksrc_' + 'a' * 24)
    tampered = json.loads(json.dumps(frozen))
    tampered['sources'][0]['chunks'][0]['text'] = '悄悄篡改'
    with pytest.raises(Problem, match='不一致'):
        search_snapshot(tampered, '篡改')


def test_read_search_summary_are_bounded(tmp_path):
    store = KnowledgeStore(tmp_path)
    for index in range(10):
        store.add_document(document(title=f'测试资料{index}', source_url=f'https://example.org/{index}',
                                    text=('青花测试' + '长' * 1196) + '\n\n' + '短的另一段。'))
    snapshot = store.snapshot()
    identifier = snapshot['sources'][0]['source']['document_id']
    read = read_snapshot(snapshot, identifier, limit=1, max_chars=80)
    assert len(read['chunks']) == 1 and len(read['chunks'][0]['text']) == 80
    assert read['chunks'][0]['truncated'] is True
    assert read['total_chunks'] == 2
    results = store.search('青花', limit=3)['results']
    assert len(results) == 3 and all(len(result['text']) <= 800 for result in results)
    summary = store.summary(snapshot)
    assert len(summary['sources']) == 8 and summary['truncated'] is True
    assert all('text' not in source and 'chunks' not in source for source in summary['sources'])
    for q, limit in [('', 8), ('字' * 201, 8), ('!!!', 8), ('青花', 21)]:
        with pytest.raises(Problem):
            store.search(q, limit=limit)
    with pytest.raises(Problem):
        read_snapshot(snapshot, identifier, limit=9)


def test_request_id_replay_and_conflict(tmp_path):
    store = KnowledgeStore(tmp_path)
    body = document(request_id='test-request-id')
    first = store.add_document(body)
    assert store.add_document(body) == first
    with pytest.raises(Problem, match='request_id'):
        store.add_document(dict(body, text='request id不同正文'))


def test_explicit_paragraph_locator_and_normalized_keyword(tmp_path):
    store = KnowledgeStore(tmp_path)
    result = store.add_document(document(text='', chunks=[
        {'text': 'ＡＢＣ Test 全角字符与青花。', 'locator': '本地摘要，原文页码未知'},
        {'text': '第二段胎釉测试', 'locator': '来源条目备注第2项'}]))
    detail = store.source(result['source']['document_id'])
    assert detail['chunks'][0]['locator'] == '本地摘要，原文页码未知'
    assert store.search('abc')['results'][0]['chunk_id'] == detail['chunks'][0]['chunk_id']
    assert store.search('TEST')['results']
    aliased = document(title='URL别名测试')
    aliased.pop('source_url')
    aliased['url'] = 'https://example.org/alias'
    assert store.add_document(aliased)['source']['source_url'] == aliased['url']
    with pytest.raises(Problem, match='不能冲突'):
        store.add_document(dict(document(), url='https://example.org/contradiction'))


def test_api_inherits_session_limits_and_browses_without_model(tmp_path, monkeypatch):
    # Every network client construction is forbidden in these protocol tests.
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('No URL fetching'))
    monkeypatch.delenv('CIZHENG_MODEL_URL', raising=False)
    monkeypatch.delenv('CIZHENG_MODEL', raising=False)
    app = create_app(tmp_path)
    knowledge = app.state.knowledge
    with TestClient(app) as client:
        baseline = client.get('/api/knowledge/sources').json()['total']
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        assert client.post('/api/knowledge/documents', json=document()).status_code == 403
        assert client.post('/api/knowledge/sources', headers=dict(headers, Origin='https://other.example'),
                           json=document()).status_code == 403
        added = client.post('/api/knowledge/documents', headers=headers, json=document())
        assert added.status_code == 201, added.text
        identifier = added.json()['source']['document_id']
        assert client.get('/api/knowledge/sources').json()['total'] == baseline + 1
        assert client.get('/api/knowledge/sources/' + identifier).json()['chunks']
        search = client.get('/api/knowledge/search', params={'q': '胎釉', 'rights': 'authorized_text'})
        assert search.status_code == 200 and search.json()['results']
        assert search.headers['x-content-type-options'] == 'nosniff'
        assert client.get('/api/knowledge/search', params={'q': '胎釉', 'limit': 50}).status_code == 422
        assert client.get('/api/knowledge/sources/no-such').status_code == 404
        assert client.post('/api/knowledge/import', headers=headers, json=document()).json()['deduplicated']
        bad = client.post('/api/knowledge/sources', headers=headers, json=document(rights='unknown'))
        assert bad.status_code == 422
        assert not app.state.engine.model.configured


def test_xss_is_inert_json_data_and_url_scheme_cannot_execute(tmp_path):
    app = create_app(tmp_path)
    knowledge = app.state.knowledge
    payload = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    with TestClient(app) as client:
        headers = {'X-Cizheng-Token': client.get('/api/status').json()['session_token']}
        result = client.post('/api/knowledge/sources', headers=headers,
                             json=document(title=payload, text='正文：' + payload))
        assert result.status_code == 201
        response = client.get('/api/knowledge/sources/' + result.json()['source']['document_id'])
        assert response.headers['content-type'].startswith('application/json')
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.json()['source']['title'] == payload
        assert response.json()['chunks'][0]['text'] == '正文：' + payload
        assert "script-src 'self'" in response.headers['content-security-policy']
        bad = client.post('/api/knowledge/sources', headers=headers,
                          json=document(source_url='javascript:alert(1)'))
        assert bad.status_code == 422


def test_sql_punctuation_and_latest_permission_do_not_expand_search(tmp_path):
    store = KnowledgeStore(tmp_path)
    added = store.add_document(document(text='检索边界正文关键词。'))
    assert not store.search("' UNION DROPTABLE --")['results']
    identifier = added['source']['document_id']
    store.add_document(document(document_id=identifier, expected_revision=1, rights='unknown', text=''))
    assert not store.search('边界正文关键词')['results']
    assert store.source(identifier)['chunks'] == []
    assert store.search('青花觚')['results'][0]['content_kind'] == 'metadata'


def test_index_version_names_algorithm_and_subset_cannot_grow_live(tmp_path):
    store = KnowledgeStore(tmp_path)
    one = store.add_document(document())['source']['document_id']
    two = store.add_document(document(title='另一份协议', source_url='https://example.org/two',
                                      text='只在第二份资料里的关键词。'))['source']['document_id']
    selected = store.snapshot([one])
    assert selected['indexer_version'] == INDEXER_VERSION
    assert search_snapshot(selected, '第二份')['results'] == []
    with pytest.raises(Problem):
        read_snapshot(selected, two)


def test_single_han_query_and_invalid_snapshot(tmp_path):
    store = KnowledgeStore(tmp_path)
    store.add_document(document(text='孤立字检索：觚。口沿段落。'))
    assert store.search('觚')['results']
    assert search_snapshot(store.snapshot(), '觚')['results']
    for broken in [None, {}, {'schema_version': 1, 'indexer_version': INDEXER_VERSION},
                   {'schema_version': 1, 'indexer_version': INDEXER_VERSION, 'sources': [],
                    'index_version': 'x', 'snapshot_sha256': 'bad'}]:
        with pytest.raises(Problem, match='不一致'):
            search_snapshot(broken, '觚')


def test_concurrent_revision_checks_and_atomic_index(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store = KnowledgeStore(tmp_path)
    identifier = store.add_document(document())['source']['document_id']
    barrier = Barrier(2)

    def update(text):
        barrier.wait()
        try:
            return store.add_document(document(document_id=identifier, expected_revision=1, text=text))
        except Problem as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, text) for text in ['并发甲的测试段落。', '并发乙的测试段落。']]
        results = [future.result() for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    assert store.source(identifier)['source']['revision'] == 2
    assert store.source(identifier)['revisions'] == [1, 2]
    snapshot = store.snapshot()
    assert store.search('并发')['results'][0]['document_revision'] == 2
    assert search_snapshot(snapshot, '并发')['results'][0]['document_revision'] == 2


def test_library_count_and_total_text_quotas_are_transactional(tmp_path, monkeypatch):
    import cizheng.knowledge as module
    store = KnowledgeStore(tmp_path)
    monkeypatch.setattr(module, 'MAX_SOURCES', 1)
    store.add_document(document(text='原始正文。'))
    before = store.index_version
    with pytest.raises(Problem, match='500份上限'):
        store.add_document(document(title='第二份测试', source_url='https://example.org/two'))
    assert store.index_version == before
    monkeypatch.setattr(module, 'MAX_LIBRARY_BYTES', 8)
    identifier = store.list_sources()['sources'][0]['document_id']
    with pytest.raises(Problem, match='10MB上限'):
        store.add_document(document(document_id=identifier, expected_revision=1, text='资料超过此测试缩小的字节上限。'))
    assert store.source(identifier)['revisions'] == [1]
    assert store.index_version == before


def test_generated_paragraph_locator_keeps_source_and_fits_citation(tmp_path):
    from cizheng.schemas import KnowledgeCitation
    store = KnowledgeStore(tmp_path)
    locator = '原始长定位' * 200
    assert len(locator) == 1000
    source = store.add_document(document(locator=locator, text='协议测试段落。'))['source']
    detail = store.source(source['document_id'])
    chunk = detail['chunks'][0]
    assert detail['source']['locator'] == locator
    assert len(chunk['locator']) == 1000
    assert chunk['locator'].endswith(' · 手动录入第1段')
    result = store.search('协议测试段落')['results'][0]
    assert result['locator'] == chunk['locator']
    citation = KnowledgeCitation(**{key: result[key] for key in (
        'document_id', 'document_revision', 'document_sha256', 'chunk_id', 'chunk_sha256', 'locator')},
        use='method', relevance='仅验证协议字段，不是真实研究意见。')
    assert citation.locator == chunk['locator']
