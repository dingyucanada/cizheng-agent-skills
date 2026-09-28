"""Local, versioned text references. No crawler, model call, or credibility score.

Permission applies to manually entered text, not to the URL's remote content.
Sources and paragraphs are immutable per revision; the retrieval index contains
only current revisions. Fixed run snapshots use the same deterministic ranking.
"""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .store import Problem, dump


INDEXER_VERSION = 'cizheng-zh-bigram-v1'
MAX_TEXT_CHARS = 100_000
MAX_TEXT_BYTES = 400_000
MAX_CHUNKS = 200
CHUNK_CHARS = 1200
MAX_SOURCES = 500
MAX_LIBRARY_BYTES = 10_000_000
RANK_NOTICE = 'rank_score 是中文双字词与关键词的加权匹配排序分，不是可靠性、真伪或置信概率；来源与摘要均待专家复核。'
DEFAULT_LIMITATION = '资料仅供研究线索；出处存在不代表内容可靠，不能替代实物检查或专家复核。'
RIGHTS = ('unknown', 'public_metadata', 'authorized_text')
REVIEW_STATUSES = ('pending', 'unreviewed', 'needs_review')
FILTER_FIELDS = ('institution', 'source_type', 'rights', 'review_status', 'scope', 'document_id')
METADATA_FIELDS = ('title', 'institution', 'source_url', 'locator', 'author', 'year',
                   'rights', 'rights_note', 'scope', 'source_type', 'review_status', 'limitations')


def sha(value):
    return hashlib.sha256(dump(value).encode('utf-8')).hexdigest()


def normalize(value):
    return unicodedata.normalize('NFKC', value).casefold()


def terms(value):
    """Whitespace/Latin words and overlapping Han bigrams; a single Han is valid."""
    output = set()
    for item in re.findall(r'[\u3400-\u9fff]+|[a-z0-9]+', normalize(value)):
        if re.fullmatch(r'[\u3400-\u9fff]+', item) and len(item) > 1:
            output.update(item[index:index + 2] for index in range(len(item) - 1))
        else:
            output.add(item)
    return output


def _index_terms(value):
    # Single-character queries are supported without letting every long query
    # match merely because it shares a common Han character.
    return terms(value) | set(re.findall(r'[\u3400-\u9fff]', normalize(value)))


def _matching_terms(query_terms, value):
    present = terms(value)
    normalized = normalize(value)
    return {term for term in query_terms if term in present or
            (len(term) == 1 and re.fullmatch(r'[\u3400-\u9fff]', term) and term in normalized)}


class ParagraphIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=CHUNK_CHARS)
    locator: str = Field(default='', max_length=1000)


class KnowledgeDocumentIn(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    document_id: str | None = Field(default=None, pattern=r'^ksrc_[a-f0-9]{24}$')
    expected_revision: int | None = Field(default=None, ge=1)
    request_id: str | None = Field(default=None, min_length=8, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    institution: str = Field(default='', max_length=300)
    source_url: str = Field(default='', max_length=2000)
    locator: str = Field(default='', max_length=1000)
    author: str = Field(default='', max_length=300)
    year: str = Field(default='', max_length=100)
    rights: Literal['unknown', 'public_metadata', 'authorized_text'] = 'unknown'
    rights_note: str = Field(default='', max_length=1500)
    scope: str = Field(default='', max_length=1500)
    source_type: str = Field(default='manual_reference', min_length=1, max_length=100)
    review_status: Literal['pending', 'unreviewed', 'needs_review'] = 'pending'
    limitations: list[str] = Field(default_factory=lambda: [DEFAULT_LIMITATION], max_length=10)
    text: str = Field(default='', max_length=MAX_TEXT_CHARS)
    chunks: list[ParagraphIn] = Field(default_factory=list, max_length=MAX_CHUNKS)

    @model_validator(mode='before')
    @classmethod
    def url_alias(cls, value):
        if isinstance(value, dict) and 'url' in value:
            value = dict(value)
            url = value.pop('url')
            if 'source_url' in value and value['source_url'] != url:
                raise ValueError('url 与 source_url 内容不能冲突')
            value['source_url'] = url
        return value

    @model_validator(mode='after')
    def validate_source(self):
        for field in ('title', 'institution', 'source_url', 'locator', 'author', 'year',
                      'rights_note', 'scope', 'source_type'):
            setattr(self, field, getattr(self, field).strip())
        if not self.title or not self.source_type:
            raise ValueError('标题与来源类型不能为空')
        if self.source_url:
            parsed = urlsplit(self.source_url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                    or parsed.password or any(ord(c) < 32 for c in self.source_url)):
                raise ValueError('来源URL只接受不带登录凭据的HTTP(S)地址；不会访问此地址')
        if self.text.strip() and self.chunks:
            raise ValueError('text 与 chunks 只能填写一种')
        content = self.text.strip() or ''.join(chunk.text for chunk in self.chunks)
        if content and self.rights != 'authorized_text':
            raise ValueError('只有 authorized_text 可录入正文；unknown/public_metadata 仅允许来源卡')
        if content and not self.rights_note:
            raise ValueError('授权正文必须填写 rights_note 说明许可或原创依据')
        if len(content) > MAX_TEXT_CHARS or len(content.encode('utf-8')) > MAX_TEXT_BYTES:
            raise ValueError('单份正文最多100000字/400000字节')
        if self.document_id and self.expected_revision is None:
            raise ValueError('修改来源必须带 expected_revision')
        if not self.document_id and self.expected_revision is not None:
            raise ValueError('expected_revision 需要 document_id')
        if any(not str(item).strip() or len(str(item)) > 1500 for item in self.limitations):
            raise ValueError('每条适用限制须为1到1500字')
        if not self.limitations:
            self.limitations = [DEFAULT_LIMITATION]
        return self


def prepare_document(body):
    try:
        item = KnowledgeDocumentIn.model_validate(body)
    except ValidationError as exc:
        # Do not echo submitted text, credentials, or giant validation input.
        messages = '; '.join(error['msg'] for error in exc.errors(include_input=False))
        raise Problem(422, messages[:1500]) from exc
    metadata = {field: getattr(item, field) for field in METADATA_FIELDS}
    paragraphs = []
    if item.chunks:
        for index, chunk in enumerate(item.chunks, 1):
            text = chunk.text.strip()
            if not text:
                raise Problem(422, '段落不能只含空白')
            paragraphs.append({'text': text, 'locator': chunk.locator.strip() or
                               _paragraph_locator(item.locator, index)})
    elif item.text.strip():
        for paragraph in re.split(r'\n\s*\n', item.text.strip().replace('\r\n', '\n')):
            paragraph = paragraph.strip()
            for start in range(0, len(paragraph), CHUNK_CHARS):
                paragraphs.append({'text': paragraph[start:start + CHUNK_CHARS],
                                   'locator': _paragraph_locator(item.locator, len(paragraphs) + 1)})
    if len(paragraphs) > MAX_CHUNKS:
        raise Problem(413, '单份资料最多200段；请缩小文本或合并过短段落')
    return item, metadata, paragraphs


def _paragraph_locator(locator, index):
    suffix = '手动录入第' + str(index) + '段'
    if not locator:
        return suffix
    # Citation schemas admit at most 1000 characters. Keep the full input on
    # the source card, but reserve room in this paragraph locator for its index.
    return locator[:1000 - len(suffix) - 3] + ' · ' + suffix


def _source_identity(metadata):
    # These fields identify a manual source card. Explicit document_id is needed
    # when revising the title/URL/author; their old revision remains addressable.
    return 'ksrc_' + sha({field: metadata[field] for field in
                          ('title', 'institution', 'source_url', 'author')})[:24]


def _metadata_text(source):
    parts = [source['title']]
    for field, label in (('institution', '机构'), ('author', '作者'), ('year', '年份'),
                         ('locator', '定位'), ('scope', '适用范围')):
        if source[field]:
            parts.append(label + '：' + source[field])
    return '来源卡元数据（未引用正文）：' + '；'.join(parts)


def _metadata_chunk(source):
    text = _metadata_text(source)
    return {'chunk_id': source['document_id'] + '_r' + str(source['revision']) + '_metadata',
            'document_id': source['document_id'], 'document_revision': source['revision'],
            'ordinal': 0, 'text': text, 'locator': source['locator'] or '来源卡元数据',
            'chunk_sha256': sha({'text': text, 'locator': source['locator']}),
            'content_kind': 'metadata'}


def _allowed(source, filters):
    for field, value in filters.items():
        if value is None or value == '' or value == []:
            continue
        actual = str(source.get(field, ''))
        values = value if isinstance(value, (list, tuple, set)) else [value]
        if field == 'scope':
            if not any(normalize(str(part)) in normalize(actual) for part in values):
                return False
        elif actual not in [str(part) for part in values]:
            return False
    return True


def _filters(filters):
    filters = filters or {}
    if not isinstance(filters, dict) or set(filters) - set(FILTER_FIELDS):
        raise Problem(422, '未知资料筛选字段')
    return filters


def _query(q, limit):
    if not isinstance(q, str) or not q.strip() or len(q) > 200:
        raise Problem(422, '检索词须为1到200字')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise Problem(422, '检索结果数量须为1到20')
    query_terms = terms(q)
    if not query_terms:
        raise Problem(422, '检索词须含中文、字母或数字')
    return q.strip(), query_terms


def _snippet(text, query_terms, q, max_chars=800):
    normalized = normalize(text)
    match_at = normalized.find(normalize(q))
    if match_at < 0:
        positions = [normalized.find(term) for term in query_terms if term in normalized]
        match_at = min(positions) if positions else 0
    start = max(0, match_at - 100) if len(text) > max_chars else 0
    start = min(start, max(0, len(text) - max_chars))
    end = min(len(text), start + max_chars)
    return {'text': text[start:end], 'snippet_start': start, 'snippet_end': end,
            'truncated': start > 0 or end < len(text)}


def _result(source, chunk, query_terms, q):
    metadata = ' '.join(str(source[field]) for field in
                        ('title', 'institution', 'author', 'year', 'scope', 'source_type'))
    meta_matches = _matching_terms(query_terms, metadata)
    body_matches = _matching_terms(query_terms, chunk['text'])
    locator_matches = _matching_terms(query_terms, chunk['locator'])
    matches = meta_matches | body_matches | locator_matches
    if not matches:
        return None
    exact_phrase = normalize(q) in normalize(metadata + ' ' + chunk['text'] + ' ' + chunk['locator'])
    score = (3 * len(meta_matches) + 2 * len(body_matches) + len(locator_matches)) / len(query_terms)
    score += 4 if exact_phrase else 0
    result = {field: source[field] for field in METADATA_FIELDS}
    result.update(document_id=source['document_id'], document_revision=source['revision'],
                  revision=source['revision'], document_sha256=source['document_sha256'],
                  chunk_id=chunk['chunk_id'], chunk_sha256=chunk['chunk_sha256'],
                  locator=chunk['locator'], content_kind=chunk.get('content_kind', 'authorized_text'),
                  rank_score=round(score, 6), matched_terms=sorted(matches)[:30],
                  rank_components={'metadata_terms': len(meta_matches), 'body_terms': len(body_matches),
                                   'locator_terms': len(locator_matches), 'query_terms': len(query_terms),
                                   'exact_phrase': exact_phrase}, review_required=True)
    result.update(_snippet(chunk['text'], query_terms, q))
    return result


def _rank(entries, q, filters, limit, query_terms):
    results = []
    for entry in entries:
        source = entry['source']
        if not _allowed(source, filters):
            continue
        chunks = entry['chunks'] if source['rights'] == 'authorized_text' else []
        for chunk in chunks or [_metadata_chunk(source)]:
            result = _result(source, chunk, query_terms, q)
            if result:
                results.append(result)
    results.sort(key=lambda result: (-result['rank_score'], result['document_id'], result['chunk_id']))
    return results[:limit]


def _snapshot_hash(snapshot):
    return sha({key: snapshot[key] for key in
                ('schema_version', 'indexer_version', 'index_version', 'sources')})


def validate_snapshot(snapshot):
    try:
        valid = (isinstance(snapshot, dict) and snapshot.get('schema_version') == 1
                 and snapshot.get('indexer_version') == INDEXER_VERSION
                 and isinstance(snapshot.get('sources'), list)
                 and snapshot.get('snapshot_sha256') == _snapshot_hash(snapshot))
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise Problem(409, '知识资料快照内容或版本不一致')
    return snapshot


def search_snapshot(snapshot, q, filters=None, limit=8):
    """Search only frozen snapshot paragraphs; never consult a live database."""
    snapshot = validate_snapshot(snapshot)
    q, query_terms = _query(q, limit)
    filters = _filters(filters)
    results = _rank(snapshot['sources'], q, filters, limit, query_terms)
    for result in results:
        result['index_version'] = snapshot['index_version']
        result['snapshot_sha256'] = snapshot['snapshot_sha256']
    return {'query': q, 'filters': filters, 'results': results, 'index_version': snapshot['index_version'],
            'indexer_version': INDEXER_VERSION, 'snapshot_sha256': snapshot['snapshot_sha256'],
            'rank_notice': RANK_NOTICE}


def read_snapshot(snapshot, document_id, chunk_id=None, limit=8, max_chars=800):
    """Return bounded paragraph excerpts with exact version and locator hashes."""
    snapshot = validate_snapshot(snapshot)
    if not isinstance(limit, int) or not 1 <= limit <= 8 or not isinstance(max_chars, int) or not 1 <= max_chars <= 800:
        raise Problem(422, '资料阅读最多8段、每段800字')
    entry = next((entry for entry in snapshot['sources']
                  if entry['source']['document_id'] == document_id), None)
    if not entry:
        raise Problem(404, '资料不在本轮固定知识快照中')
    source = entry['source']
    available = entry['chunks'] if source['rights'] == 'authorized_text' else []
    available = available or [_metadata_chunk(source)]
    if chunk_id:
        available = [chunk for chunk in available if chunk['chunk_id'] == chunk_id]
        if not available:
            raise Problem(404, '段落不在该资料固定版本中')
    chunks = []
    for chunk in available[:limit]:
        excerpt = {key: chunk[key] for key in
                   ('chunk_id', 'document_id', 'document_revision', 'ordinal', 'locator', 'chunk_sha256')}
        excerpt.update(text=chunk['text'][:max_chars], snippet_start=0,
                       snippet_end=min(max_chars, len(chunk['text'])), truncated=len(chunk['text']) > max_chars,
                       content_kind=chunk.get('content_kind', 'authorized_text'),
                       document_sha256=source['document_sha256'])
        chunks.append(excerpt)
    return {'source': dict(source), 'chunks': chunks, 'total_chunks': len(available),
            'index_version': snapshot['index_version'], 'snapshot_sha256': snapshot['snapshot_sha256'],
            'notice': RANK_NOTICE}


class KnowledgeStore:
    def __init__(self, root):
        self.root = Path(root if isinstance(root, (str, Path)) else root.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'knowledge.sqlite3'
        with self.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                document_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(document_id, revision));
            CREATE TABLE IF NOT EXISTS knowledge_heads (
                document_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                FOREIGN KEY(document_id, revision) REFERENCES knowledge_sources(document_id, revision));
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, revision INTEGER NOT NULL,
                ordinal INTEGER NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(document_id, revision) REFERENCES knowledge_sources(document_id, revision));
            CREATE INDEX IF NOT EXISTS knowledge_chunk_source ON knowledge_chunks(document_id, revision);
            CREATE TABLE IF NOT EXISTS knowledge_terms (
                term TEXT NOT NULL, document_id TEXT NOT NULL, revision INTEGER NOT NULL,
                PRIMARY KEY(term, document_id, revision));
            CREATE TABLE IF NOT EXISTS knowledge_requests (
                request_id TEXT PRIMARY KEY, body_sha256 TEXT NOT NULL, response TEXT NOT NULL);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _heads(db):
        return [json.loads(row[0]) for row in db.execute('''SELECT s.data FROM knowledge_sources s
            JOIN knowledge_heads h ON h.document_id=s.document_id AND h.revision=s.revision
            ORDER BY s.document_id''')]

    @staticmethod
    def _index_version(db):
        return sha({'indexer_version': INDEXER_VERSION, 'documents': [
            [source['document_id'], source['revision'], source['document_sha256']]
            for source in KnowledgeStore._heads(db)]})

    @property
    def index_version(self):
        with self.tx() as db:
            return self._index_version(db)

    @staticmethod
    def _chunks(db, source):
        return [json.loads(row[0]) for row in db.execute('''SELECT data FROM knowledge_chunks
            WHERE document_id=? AND revision=? ORDER BY ordinal''',
            (source['document_id'], source['revision']))]

    def add_document(self, body):
        item, metadata, paragraphs = prepare_document(body)
        document_hash = sha({'source': metadata, 'paragraphs': paragraphs})
        identifier = item.document_id or _source_identity(metadata)
        request_hash = sha(item.model_dump())
        with self.tx() as db:
            if item.request_id:
                row = db.execute('SELECT body_sha256,response FROM knowledge_requests WHERE request_id=?',
                                 (item.request_id,)).fetchone()
                if row:
                    if row[0] != request_hash:
                        raise Problem(409, '同一request_id不可用于不同资料内容')
                    return json.loads(row[1])
            current_sources = self._heads(db)
            current = next((source for source in current_sources if source['document_id'] == identifier), None)
            if item.document_id and not current:
                raise Problem(404, '要修订的资料来源不存在')
            if current and item.document_id and current['revision'] != item.expected_revision:
                raise Problem(409, '知识资料版本已更新，请刷新后修订')
            duplicate = next((source for source in current_sources
                              if source['document_sha256'] == document_hash), None)
            if duplicate and (not item.document_id or duplicate['document_id'] == identifier):
                result = {'source': duplicate, 'index_version': self._index_version(db), 'deduplicated': True}
            else:
                if current and not item.document_id:
                    raise Problem(409, '同一来源卡已有不同内容；修订需 document_id 与 expected_revision')
                if not current and len(current_sources) >= MAX_SOURCES:
                    raise Problem(413, '本地资料来源达到500份上限')
                text_size = sum(len(paragraph['text'].encode('utf-8')) for paragraph in paragraphs)
                library_size = sum(source['text_bytes'] for source in current_sources)
                if library_size - (current['text_bytes'] if current else 0) + text_size > MAX_LIBRARY_BYTES:
                    raise Problem(413, '本地可检索正文总量达到10MB上限')
                revision = current['revision'] + 1 if current else 1
                source = dict(metadata, id=identifier, document_id=identifier, revision=revision,
                              document_revision=revision, document_sha256=document_hash,
                              text_sha256=sha(paragraphs), chunk_count=len(paragraphs), text_bytes=text_size,
                              created_at=current['created_at'] if current else time.time(), updated_at=time.time(),
                              review_required=True, expert_reviewed=False, imported_manually=True)
                db.execute('INSERT INTO knowledge_sources VALUES (?,?,?)', (identifier, revision, dump(source)))
                for index, paragraph in enumerate(paragraphs, 1):
                    chunk_hash = sha(paragraph)
                    chunk = dict(paragraph, chunk_id=identifier + '_r' + str(revision) + '_p' +
                                 str(index).zfill(4) + '_' + chunk_hash[:12], document_id=identifier,
                                 document_revision=revision, ordinal=index, chunk_sha256=chunk_hash,
                                 content_kind='authorized_text')
                    db.execute('INSERT INTO knowledge_chunks VALUES (?,?,?,?,?)',
                               (chunk['chunk_id'], identifier, revision, index, dump(chunk)))
                db.execute('INSERT INTO knowledge_heads VALUES (?,?) ON CONFLICT(document_id) '
                           'DO UPDATE SET revision=excluded.revision', (identifier, revision))
                searchable = ' '.join(str(source[field]) for field in
                                      ('title', 'institution', 'author', 'year', 'scope', 'source_type', 'locator'))
                if source['rights'] == 'authorized_text':
                    searchable += ' ' + ' '.join(paragraph['text'] + ' ' + paragraph['locator']
                                                 for paragraph in paragraphs)
                db.executemany('INSERT OR IGNORE INTO knowledge_terms VALUES (?,?,?)',
                               [(term, identifier, revision) for term in _index_terms(searchable)])
                result = {'source': source, 'index_version': self._index_version(db), 'deduplicated': False}
            if item.request_id:
                db.execute('INSERT INTO knowledge_requests VALUES (?,?,?)',
                           (item.request_id, request_hash, dump(result)))
            return result

    def list_sources(self, filters=None, limit=100, offset=0):
        filters = _filters(filters)
        if not isinstance(limit, int) or not 1 <= limit <= 500 or not isinstance(offset, int) or offset < 0:
            raise Problem(422, '来源分页参数无效')
        with self.tx() as db:
            sources = [source for source in self._heads(db) if _allowed(source, filters)]
            return {'sources': sources[offset:offset + limit], 'total': len(sources),
                    'index_version': self._index_version(db), 'indexer_version': INDEXER_VERSION}

    def source(self, document_id, revision=None):
        with self.tx() as db:
            if revision is None:
                head = db.execute('SELECT revision FROM knowledge_heads WHERE document_id=?',
                                  (document_id,)).fetchone()
                if not head:
                    raise Problem(404, '知识资料不存在')
                revision = head[0]
            row = db.execute('SELECT data FROM knowledge_sources WHERE document_id=? AND revision=?',
                             (document_id, revision)).fetchone()
            if not row:
                raise Problem(404, '知识资料版本不存在')
            source = json.loads(row[0])
            revisions = [row[0] for row in db.execute('SELECT revision FROM knowledge_sources '
                        'WHERE document_id=? ORDER BY revision', (document_id,))]
            return {'source': source, 'chunks': self._chunks(db, source), 'revisions': revisions,
                    'index_version': self._index_version(db), 'indexer_version': INDEXER_VERSION}

    def snapshot(self, document_ids=None, bindings=None):
        if document_ids is not None and (not isinstance(document_ids, list) or len(document_ids) > MAX_SOURCES
                                         or any(not isinstance(item, str) for item in document_ids)):
            raise Problem(422, '知识快照 document_ids 必须为最多500个来源ID')
        if bindings is not None and (not isinstance(bindings, list) or len(bindings) > MAX_SOURCES
                                     or any(not isinstance(b, dict) or not isinstance(b.get('document_id'), str)
                                            or type(b.get('document_revision')) is not int or b['document_revision'] < 1
                                            or not re.fullmatch(r'[a-f0-9]{64}', b.get('document_sha256', ''))
                                            for b in bindings)):
            raise Problem(422, '知识资料绑定必须包含来源ID、明确版本和文档哈希')
        with self.tx() as db:
            sources = self._heads(db)
            if document_ids is not None:
                unknown = set(document_ids) - {source['document_id'] for source in sources}
                if unknown:
                    raise Problem(404, '选中的知识资料来源不存在')
                sources = [source for source in sources if source['document_id'] in document_ids]
            pinned = {b['document_id']: b for b in (bindings or [])}
            if set(pinned) - {s['document_id'] for s in sources}:
                raise Problem(404, '本案固定版本的资料未包含于知识快照')
            for index, source in enumerate(sources):
                if source['document_id'] not in pinned: continue
                binding = pinned[source['document_id']]
                row = db.execute('SELECT data FROM knowledge_sources WHERE document_id=? AND revision=?',
                                 (binding['document_id'], binding['document_revision'])).fetchone()
                if not row:
                    raise Problem(409, '本案固定的来源资料版本不存在')
                historical = json.loads(row[0])
                if historical['document_sha256'] != binding['document_sha256']:
                    raise Problem(409, '本案固定的来源资料哈希不一致')
                sources[index] = historical
            snapshot = {'schema_version': 1, 'indexer_version': INDEXER_VERSION,
                        'index_version': self._index_version(db),
                        'sources': [{'source': source, 'chunks': self._chunks(db, source)
                                     if source['rights'] == 'authorized_text' else []} for source in sources]}
            snapshot['snapshot_sha256'] = _snapshot_hash(snapshot)
            return snapshot

    def search(self, q, filters=None, limit=8):
        q, query_terms = _query(q, limit)
        filters = _filters(filters)
        with self.tx() as db:
            placeholders = ','.join('?' for _ in query_terms)
            candidates = {row[0] for row in db.execute('''SELECT DISTINCT t.document_id FROM knowledge_terms t
                JOIN knowledge_heads h ON h.document_id=t.document_id AND h.revision=t.revision
                WHERE t.term IN (''' + placeholders + ')', tuple(sorted(query_terms)))}
            entries = [{'source': source, 'chunks': self._chunks(db, source)} for source in self._heads(db)
                       if source['document_id'] in candidates]
            results = _rank(entries, q, filters, limit, query_terms)
            version = self._index_version(db)
            for result in results:
                result['index_version'] = version
            return {'query': q, 'filters': filters, 'results': results, 'index_version': version,
                    'indexer_version': INDEXER_VERSION, 'rank_notice': RANK_NOTICE}

    @staticmethod
    def summary(snapshot, limit=8):
        """Metadata-only, bounded report context; never export the full library."""
        validate_snapshot(snapshot)
        if not isinstance(limit, int) or not 1 <= limit <= 8:
            raise Problem(422, '摘要最多8份来源')
        sources = []
        for entry in snapshot['sources'][:limit]:
            source = entry['source']
            sources.append({key: source[key] for key in ('document_id', 'revision', 'document_sha256',
                           'title', 'institution', 'source_url', 'rights', 'review_status')} |
                           {'scope': source['scope'][:300],
                            'limitations': [item[:300] for item in source['limitations'][:3]]})
        return {'sources': sources, 'total_sources': len(snapshot['sources']),
                'truncated': len(snapshot['sources']) > limit, 'index_version': snapshot['index_version'],
                'snapshot_sha256': snapshot['snapshot_sha256'], 'notice': RANK_NOTICE}

    search_snapshot = staticmethod(search_snapshot)
    read_snapshot = staticmethod(read_snapshot)
