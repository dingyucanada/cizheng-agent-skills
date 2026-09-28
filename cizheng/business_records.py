"""Append-only operator business records; no document execution or inference.

Located evidence means a saved attachment or an exact knowledge paragraph can
be revisited. It does not establish an event, an object's identity, or authenticity.
Routes inherit the local host application's session and request-size middleware.
"""
import base64
import binascii
import hashlib
import re
import time
from pathlib import PurePath
from typing import Annotated, Literal, Union

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import Problem, uid


TXT_LIMIT = 2 * 1024 * 1024
PDF_LIMIT = 10 * 1024 * 1024
MAX_ATTACHMENTS = 20
MAX_PROVENANCE_EVENTS = 100
MAX_CONDITION_CHECKS = 100
UNVERIFIED_NOTICE = '本地操作人登记；文件与引用可回查，但未核验记载真实性、器物同一性或真伪，不是认证。'
SHA_PATTERN = r'^[a-f0-9]{64}$'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class CaseMutation(Strict):
    request_id: str = Field(min_length=8, max_length=100)
    expected_case_revision: int = Field(ge=1)


class EvidenceDocumentIn(CaseMutation):
    file_base64: str = Field(min_length=4, max_length=4 * ((PDF_LIMIT + 2) // 3))
    filename: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=2000)
    rights_note: str = Field(min_length=1, max_length=1500)
    permission: Literal['local_use_authorized']

    @model_validator(mode='after')
    def safe_filename(self):
        if (self.filename in ('.', '..') or '/' in self.filename or '\\' in self.filename
                or any(ord(char) < 32 for char in self.filename)
                or PurePath(self.filename).suffix.casefold() not in ('.txt', '.pdf')):
            raise ValueError('附件文件名须为无路径的TXT或PDF名称')
        return self


class AttachmentEvidence(Strict):
    kind: Literal['attachment']
    document_id: str = Field(pattern=r'^evidoc_[a-f0-9]{32}$')
    locator: str = Field(min_length=1, max_length=1000)
    sha256: str | None = Field(default=None, pattern=SHA_PATTERN)


class KnowledgeEvidence(Strict):
    kind: Literal['knowledge']
    document_id: str = Field(pattern=r'^ksrc_[a-f0-9]{24}$')
    revision: int = Field(ge=1)
    chunk_id: str = Field(min_length=1, max_length=200)
    document_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    chunk_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    locator: str = Field(default='', max_length=1000)


LocatedEvidence = Annotated[Union[AttachmentEvidence, KnowledgeEvidence], Field(discriminator='kind')]


class ProvenanceEventIn(CaseMutation):
    date_text: str = Field(min_length=1, max_length=200)
    event_type: Literal['acquired', 'auction', 'exhibition', 'publication', 'transfer', 'statement', 'gap']
    party: str = Field(default='', max_length=1000)
    place: str = Field(default='', max_length=1000)
    description: str = Field(min_length=1, max_length=4000)
    object_link_basis: str = Field(min_length=1, max_length=2000)
    evidence: list[LocatedEvidence] = Field(default_factory=list, max_length=20)
    status: Literal['declared', 'documented', 'disputed', 'gap']
    supersedes: str | None = Field(default=None, pattern=r'^provenance_[a-f0-9]{32}$')

    @model_validator(mode='after')
    def status_requires_location(self):
        if self.status == 'documented' and not self.evidence:
            raise ValueError('documented 事件至少需要一项已保存资料的明确定位')
        if self.event_type == 'gap' and self.status != 'gap':
            raise ValueError('来源缺口事件须标记 status=gap')
        return self


class ConditionCheckIn(CaseMutation):
    date_text: str = Field(min_length=1, max_length=200)
    method: Literal['image', 'in_person', 'document']
    observer: str = Field(min_length=1, max_length=300)
    area: str = Field(min_length=1, max_length=500)
    observation: str = Field(min_length=1, max_length=4000)
    limitations: list[str] = Field(min_length=1, max_length=10)
    media_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=30)
    record_origin: Literal['operator'] = 'operator'
    evidence: list[LocatedEvidence] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def manual_observer(self):
        if self.method == 'document' and 'evidence' in self.model_fields_set and not self.evidence:
            raise ValueError('资料核对方式至少需要一项本案附件或固定知识段落的明确定位')
        if any(not item.strip() or len(item) > 1500 for item in self.limitations):
            raise ValueError('每条观察限制须为1到1500字')
        if len(self.media_ids) != len(set(self.media_ids)):
            raise ValueError('状况检查的图片ID不可重复')
        if re.match(r'^(?:ai|人工智能|视觉模型|语言模型|模型)(?:\s|[：:·-]|$)', self.observer, re.I):
            raise ValueError('此接口只登记人工观察，observer 应填写操作人声明')
        return self


class PreparationReviewIn(CaseMutation):
    expected_preparation_review_revision: int = Field(ge=0)
    state: Literal['reviewed', 'request_evidence', 'needs_revision']
    note: str = Field(min_length=1, max_length=4000)
    basis: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(default='本地操作人（身份未认证）', min_length=1, max_length=300)


def preparation_review_state(case):
    """Derive validity without altering the immutable review history.

The host should call this after any case advance (or while adapting old cases).
All routes in this module also refresh the convenience current-state field.
"""
    history = case.get('preparation_reviews', [])
    if not history:
        return {'state': 'pending', 'recorded_state': 'pending', 'stale': False,
                'case_revision': case['revision'], 'review_revision': case.get('preparation_review_revision', 0),
                'identity_verified': False, 'review_required': True,
                'review_kind': 'research_preparation', 'notice': UNVERIFIED_NOTICE}
    latest = history[-1]
    stale = latest['case_revision'] != case['revision']
    return dict(latest, recorded_state=latest['state'], state='stale' if stale else latest['state'],
                stale=stale, review_required=stale or latest['state'] != 'reviewed')


def refresh_preparation_review(case):
    for field in ('evidence_documents', 'provenance_events', 'condition_checks', 'preparation_reviews'):
        case.setdefault(field, [])
    case.setdefault('preparation_review_revision', 0)
    case['preparation_review'] = preparation_review_state(case)
    return case


def decode_attachment(body):
    try:
        raw = base64.b64decode(body.file_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise Problem(422, '附件必须为有效的标准base64内容') from exc
    if not raw:
        raise Problem(422, '附件内容不能为空')
    suffix = PurePath(body.filename).suffix.casefold()
    limit = TXT_LIMIT if suffix == '.txt' else PDF_LIMIT
    if len(raw) > limit:
        raise Problem(413, 'TXT最多2MB，PDF最多10MB')
    if suffix == '.txt':
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise Problem(422, 'TXT附件必须为UTF-8文本') from exc
        if any(ord(char) < 32 and char not in '\r\n\t' for char in text):
            raise Problem(422, 'TXT附件含二进制控制字符')
        mime = 'text/plain'
    else:
        # Validate only a PDF envelope. Do not open, execute, extract, OCR, or
        # claim the file is safe or its content has been read.
        if not re.match(br'^%PDF-(?:1\.[0-9]|2\.0)(?:\r|\n|\s)', raw[:16]) or b'%%EOF' not in raw[-1024:]:
            raise Problem(422, 'PDF附件缺少可识别的PDF文件头或结束标记')
        mime = 'application/pdf'
    return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'mime': mime, 'size': len(raw)}


class BusinessRecords:
    def __init__(self, store, knowledge):
        self.store, self.knowledge = store, knowledge

    def _advance(self, db, case, action, detail):
        self.store.advance(db, case, action, detail)
        refresh_preparation_review(case)
        self.store.put(db, 'case', case)
        return case

    def add_document(self, identifier, value):
        body = EvidenceDocumentIn.model_validate(value)
        raw, metadata = decode_attachment(body)

        def add(db):
            case = self.store.checked_case(db, identifier, body.expected_case_revision)
            refresh_preparation_review(case)
            duplicate = next((document for document in case['evidence_documents']
                              if document['sha256'] == metadata['sha256']), None)
            if duplicate:
                return {'case': case, 'document': duplicate, 'deduplicated': True}
            if len(case['evidence_documents']) >= MAX_ATTACHMENTS:
                raise Problem(413, '本案最多保存20份证据附件')
            asset = self.store.save_blob(db, raw, metadata)
            document = {field: getattr(body, field) for field in ('filename', 'source', 'rights_note', 'permission')}
            document.update(metadata, id=uid('evidoc'), artifact_id=asset['id'],
                            case_id=identifier, case_revision=case['revision'] + 1, created_at=time.time(),
                            download_url='/api/artifacts/' + asset['id'] + '?download=1',
                            verification_status='not_verified', authenticity_verified=False,
                            content_read=False, ocr_performed=False, execution_performed=False,
                            notice=UNVERIFIED_NOTICE)
            case['evidence_documents'].append(document)
            self._advance(db, case, 'evidence_document', '保存本地证据附件；未读取、执行或认证其内容')
            return {'case': case, 'document': document, 'deduplicated': False}

        return self.store.mutate('evidence-document:' + identifier, body.model_dump(), add)

    def _located_evidence(self, db, case, references):
        result = []
        for reference in references:
            if reference.kind == 'attachment':
                document = next((document for document in case['evidence_documents']
                                 if document['id'] == reference.document_id), None)
                if not document:
                    raise Problem(422, '来源事件引用的附件必须属于本案')
                row = db.execute('SELECT bytes FROM blobs WHERE id=?', (document['artifact_id'],)).fetchone()
                if not row or hashlib.sha256(row[0]).hexdigest() != document['sha256']:
                    raise Problem(409, '已保存附件的原始内容与哈希不一致')
                if reference.sha256 and reference.sha256 != document['sha256']:
                    raise Problem(422, '附件引用哈希与原始文件不一致')
                result.append({'kind': 'attachment', 'document_id': document['id'],
                               'artifact_id': document['artifact_id'], 'locator': reference.locator,
                               'sha256': document['sha256'],
                               'locator_status': 'operator_declared_not_content_verified'})
            else:
                if reference.document_id not in case.get('knowledge_document_ids', []):
                    raise Problem(422, '来源事件的知识资料必须已关联本案')
                binding = next((b for b in case.get('knowledge_links', [])
                                if b['document_id'] == reference.document_id), None)
                if not binding or binding['document_revision'] != reference.revision:
                    raise Problem(422, '来源事件须引用本案明确关联的资料版本；请先关联所选版本')
                try:
                    detail = self.knowledge.source(reference.document_id, reference.revision)
                except Problem as exc:
                    raise Problem(422, '知识资料或所引用的版本不存在') from exc
                source = detail['source']
                if source['document_sha256'] != binding['document_sha256']:
                    raise Problem(409, '本案关联的资料文档哈希不一致')
                if source['rights'] != 'authorized_text':
                    raise Problem(422, '知识引用仅接受该版本已许可的真实正文段落')
                chunk = next((chunk for chunk in detail['chunks'] if chunk['chunk_id'] == reference.chunk_id), None)
                if not chunk:
                    raise Problem(422, '知识引用的段落不属于所指定资料版本')
                if ((reference.document_sha256 and reference.document_sha256 != source['document_sha256'])
                        or (reference.chunk_sha256 and reference.chunk_sha256 != chunk['chunk_sha256'])
                        or (reference.locator and reference.locator != chunk['locator'])):
                    raise Problem(422, '知识引用的定位或内容哈希与原始版本不一致')
                result.append({'kind': 'knowledge', 'document_id': source['document_id'],
                               'revision': source['revision'], 'document_revision': source['revision'],
                               'document_sha256': source['document_sha256'], 'chunk_id': chunk['chunk_id'],
                               'chunk_sha256': chunk['chunk_sha256'], 'locator': chunk['locator'],
                               'source_url': source['source_url'], 'title': source['title'],
                               'locator_status': 'saved_paragraph_present_not_authenticity_verified'})
        return result

    def add_provenance_event(self, identifier, value):
        body = ProvenanceEventIn.model_validate(value)

        def add(db):
            case = self.store.checked_case(db, identifier, body.expected_case_revision)
            refresh_preparation_review(case)
            if len(case['provenance_events']) >= MAX_PROVENANCE_EVENTS:
                raise Problem(413, '本案最多登记100条来源事件')
            if body.supersedes and body.supersedes not in {event['id'] for event in case['provenance_events']}:
                raise Problem(422, 'supersedes 必须引用本案已保存的来源事件')
            evidence = self._located_evidence(db, case, body.evidence)
            event = {field: getattr(body, field) for field in ('date_text', 'event_type', 'party', 'place',
                     'description', 'object_link_basis', 'status', 'supersedes')}
            event.update(id=uid('provenance'), case_id=identifier, case_revision=case['revision'] + 1,
                         created_at=time.time(), evidence=evidence, identity_verified=False,
                         verification_status='not_verified', authenticity_verified=False,
                         event_truth_verified=False, object_identity_verified=False, notice=UNVERIFIED_NOTICE)
            case['provenance_events'].append(event)
            self._advance(db, case, 'provenance_event', '追加来源事件及定位资料；记载内容与器物同一性待核')
            return {'case': case, 'event': event}

        return self.store.mutate('provenance-event:' + identifier, body.model_dump(), add)

    def add_condition_check(self, identifier, value):
        body = ConditionCheckIn.model_validate(value)
        located_contract = 'evidence' in body.model_fields_set

        def add(db):
            case = self.store.checked_case(db, identifier, body.expected_case_revision)
            refresh_preparation_review(case)
            if len(case['condition_checks']) >= MAX_CONDITION_CHECKS:
                raise Problem(413, '本案最多登记100条人工状况检查')
            if not set(body.media_ids) <= {media['id'] for media in case['media']}:
                raise Problem(422, '状况检查只可引用本案已保存的图片')
            evidence = self._located_evidence(db, case, body.evidence)
            check = {field: getattr(body, field) for field in ('date_text', 'method', 'observer', 'area',
                     'observation', 'limitations', 'media_ids', 'record_origin')}
            check.update(id=uid('condition'), case_id=identifier, case_revision=case['revision'] + 1,
                         created_at=time.time(), kind='operator_condition_check', identity_verified=False,
                         authenticity_verified=False, image_inference_performed=False,
                         evidence=evidence, evidence_read_or_verified=False,
                         record_contract='condition-located-v1' if located_contract else 'operator-declaration-v0',
                         located_evidence_status=('located_not_authenticity_verified' if evidence else
                                                  'legacy_unlocated_operator_declaration' if body.method == 'document' and not located_contract else
                                                  'missing_operator_declaration_only'),
                         notice=UNVERIFIED_NOTICE)
            if body.method == 'document' and not evidence:
                check['notice'] += ' 旧请求仅保留资料核对方式的人工声明；缺少定位材料，系统未进行资料核对。'
            case['condition_checks'].append(check)
            self._advance(db, case, 'condition_check', '追加人工状况记录；未进行AI图像观察或真实性认证')
            return {'case': case, 'check': check}

        mutation_body = body.model_dump(exclude=set() if located_contract else {'evidence'})
        return self.store.mutate('condition-check:' + identifier, mutation_body, add)

    def add_preparation_review(self, identifier, value):
        body = PreparationReviewIn.model_validate(value)

        def add(db):
            case = self.store.checked_case(db, identifier, body.expected_case_revision, editable=False)
            refresh_preparation_review(case)
            if case['preparation_review_revision'] != body.expected_preparation_review_revision:
                raise Problem(409, '研究准备复核记录已更新，请刷新后操作')
            review = {field: getattr(body, field) for field in ('state', 'note', 'basis', 'reviewer')}
            review.update(id=uid('prepreview'), case_id=identifier, case_revision=case['revision'],
                          created_at=time.time(), review_revision=case['preparation_review_revision'] + 1,
                          review_kind='research_preparation', identity_verified=False,
                          authenticity_verified=False, notice=UNVERIFIED_NOTICE)
            case['preparation_reviews'].append(review)
            case['preparation_review_revision'] += 1
            refresh_preparation_review(case)
            self.store.put(db, 'case', case)
            return {'case': case, 'review': review}

        return self.store.mutate('preparation-review:' + identifier, body.model_dump(), add)


def create_business_router(store, knowledge):
    records = BusinessRecords(store, knowledge)
    router = APIRouter(prefix='/api/cases', tags=['business-records'])

    @router.post('/{identifier}/evidence-documents', status_code=201)
    def evidence_document(identifier: str, body: EvidenceDocumentIn):
        return records.add_document(identifier, body.model_dump())

    @router.post('/{identifier}/provenance-events', status_code=201)
    def provenance_event(identifier: str, body: ProvenanceEventIn):
        return records.add_provenance_event(identifier, body.model_dump())

    @router.post('/{identifier}/condition-checks', status_code=201)
    def condition_check(identifier: str, body: ConditionCheckIn):
        # Preserve omitted-vs-explicit evidence for legacy clients. New clients
        # always submit evidence (even []); document then requires a true locator.
        return records.add_condition_check(identifier, body.model_dump(exclude_unset=True))

    @router.post('/{identifier}/preparation-reviews', status_code=201)
    def preparation_review(identifier: str, body: PreparationReviewIn):
        return records.add_preparation_review(identifier, body.model_dump())

    return router
