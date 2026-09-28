"""Portable, case-scoped originals and fixed evidence; no external transfer."""
import hashlib
import io
import re
import zipfile
from .store import Problem, dump
from .pro_workflow import preparation_markdown, preparation_html

MAX_HANDOFF_BYTES = 64 * 1024 * 1024


def check_case_files(case, read_blob):
    """Check recorded originals before any image decoder or report renderer."""
    records = [(m['id'], m) for m in case.get('media', [])]
    records += [(d['artifact_id'], d) for d in case.get('evidence_documents', [])]
    for identifier, record in records:
        row = read_blob(identifier)
        if not row:
            raise Problem(409, '本案原文件缺失，请核对档案后重新导出')
        mime, raw = row
        if (hashlib.sha256(raw).hexdigest() != record['sha256']
                or record.get('mime', mime) != mime
                or record.get('size', len(raw)) != len(raw)):
            raise Problem(409, '本案原文件内容或格式与登记哈希不一致；未生成报告')


def case_documents(knowledge, case):
    """Include current bindings and historical paragraphs still cited by records."""
    bindings = {b['document_id']: b for b in case.get('knowledge_links', [])}
    if set(case.get('knowledge_document_ids', [])) - set(bindings):
        raise Problem(409, '旧案资料尚未绑定固定版本，请重新关联后导出')
    documents = {}
    for identifier in case.get('knowledge_document_ids', []):
        binding = bindings[identifier]
        detail = knowledge.source(identifier, binding['document_revision'])
        if detail['source']['document_sha256'] != binding['document_sha256']:
            raise Problem(409, '来源固定版本哈希不一致')
        documents[(identifier, binding['document_revision'])] = {
            'source': detail['source'], 'chunks': detail['chunks']}
    for record in case.get('provenance_events', []) + case.get('condition_checks', []):
        for evidence in record.get('evidence', []):
            if evidence['kind'] != 'knowledge':
                continue
            key = (evidence['document_id'], evidence['revision'])
            detail = knowledge.source(*key)
            if detail['source']['document_sha256'] != evidence['document_sha256']:
                raise Problem(409, '历史凭据资料版本哈希不一致')
            chunks = [c for c in detail['chunks'] if c['chunk_id'] == evidence['chunk_id']]
            if (len(chunks) != 1 or chunks[0]['chunk_sha256'] != evidence['chunk_sha256']
                    or chunks[0]['locator'] != evidence['locator']):
                raise Problem(409, '历史凭据定位段落不一致')
            if key not in documents:
                documents[key] = {'source': detail['source'], 'chunks': [],
                                  'history_scope': '仅保留本案历史记录实际引用段落'}
            if not any(c['chunk_id'] == chunks[0]['chunk_id'] for c in documents[key]['chunks']):
                documents[key]['chunks'].append(chunks[0])
    return [documents[key] for key in sorted(documents)]


def make_handoff(bundle, read_blob):
    """Deterministic ZIP with original bytes, no global DB or unrelated library."""
    case = bundle['case']
    check_case_files(case, read_blob)
    files, rows, total = {}, [], 0

    def add(path, raw, kind, metadata=None):
        nonlocal total
        if path in files or path.startswith('/') or '..' in path.split('/'):
            raise Problem(422, '交接文件路径冲突')
        total += len(raw)
        if total > MAX_HANDOFF_BYTES:
            raise Problem(413, '单案离线交接原文件与文书合计上限64MB；请分别下载较大的原文件')
        files[path] = raw
        rows.append({'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'kind': kind, **(metadata or {})})

    def original(identifier, expected_sha, kind, metadata):
        if not re.fullmatch(r'[a-z]+_[a-f0-9]{32}', identifier):
            raise Problem(422, '原文件标识不合法')
        entry = read_blob(identifier)
        if not entry:
            raise Problem(409, '交接原文件缺失，请核对本案档案')
        mime, raw = entry
        suffix = {'image/jpeg': 'jpg', 'image/png': 'png', 'text/plain': 'txt', 'application/pdf': 'pdf'}.get(mime)
        if not suffix or hashlib.sha256(raw).hexdigest() != expected_sha:
            raise Problem(409, '原文件格式或SHA256与本案记录不一致')
        add(kind + '/' + identifier + '.' + suffix, raw, kind, {'mime': mime, **metadata})

    add('preparation.json', dump(bundle).encode(), 'report')
    add('preparation.md', preparation_markdown(bundle).encode(), 'report')
    add('preparation.html', preparation_html(bundle, read_blob).encode(), 'report')
    for media in case.get('media', []):
        original(media['id'], media['sha256'], 'original-images',
                 {'filename': media['filename'], 'view': media.get('view'), 'source': media.get('source', '')})
    for document in case.get('evidence_documents', []):
        if document['permission'] != 'local_use_authorized':
            raise Problem(409, '本案附件尚无本地研究使用许可')
        original(document['artifact_id'], document['sha256'], 'original-documents',
                 {'document_id': document['id'], 'filename': document['filename'],
                  'rights_note': document['rights_note'], 'source': document['source']})
    for document in bundle['documents']:
        source = document['source']
        if not re.fullmatch(r'ksrc_[a-f0-9]{24}', source['id']):
            raise Problem(422, '资料标识不合法')
        add('knowledge/' + source['id'] + '-r' + str(source['revision']) + '.json',
            dump(document).encode(), 'fixed-knowledge')
    add('README.md', ('# 瓷证 · 离线证据交接包\n\n'
        '打开 preparation.html 查看研究准备档案。原图和附件保留原字节，文件路径与SHA256见manifest.json。\n'
        '包含本案资料、定位段落和人工材料复核，不含整个知识库、运行数据库或其他案件。\n'
        '这是资料交接，未包含模型推理；馆藏记载与操作人陈述不等于独立鉴定。\n'
        '本地许可与公开传播许可不同，接收方应按清单中的许可范围使用。\n'
        '哈希用于查验文件一致性，不是机构签名或专业认证。\n').encode(), 'readme')
    manifest = {'schema_version': 1, 'case_id': case['id'], 'case_revision': case['revision'],
                'preparation_review_revision': case.get('preparation_review_revision', 0),
                'bundle_sha256': bundle['bundle_sha256'], 'scope': 'single-case research preparation',
                'model_inference_included': False, 'expert_reviewed': False,
                'files': rows, 'manifest_self_hash_included': False}
    raw_manifest = dump(manifest).encode()
    if total + len(raw_manifest) > MAX_HANDOFF_BYTES:
        raise Problem(413, '交接文件总量超过64MB')
    files['manifest.json'] = raw_manifest
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[path])
    raw = output.getvalue()
    return raw, manifest
