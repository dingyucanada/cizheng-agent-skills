import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=20000)


class Mutation(Strict):
    request_id: str = Field(min_length=8, max_length=100)


class Revised(Mutation):
    expected_case_revision: int = Field(ge=1)


class Catalogue(Strict):
    inventory_number: str = Field(default="", max_length=200)
    object_name: str = Field(default="", max_length=300)
    object_type: str = Field(default="", max_length=200)
    material: str = Field(default="", max_length=300)
    decoration: str = Field(default="", max_length=1000)
    dimensions: str = Field(default="", max_length=1000)
    inscription: str = Field(default="", max_length=2000)
    provenance: str = Field(default="", max_length=4000)
    condition_note: str = Field(default="", max_length=3000)
    requested_output: str = Field(default="", max_length=1000)


class NewCase(Mutation):
    research_task: Literal["visual_research", "documentary_audit"] = "visual_research"
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    target_attribution: str = Field(default="未指定", max_length=200)
    source_declaration: str = Field(default="来源、尺寸和制作时期未知", max_length=2000)
    workflow: Literal["museum", "collection", "auction"] = "museum"
    catalogue: Catalogue = Field(default_factory=Catalogue)


class ResearchTaskIn(Revised):
    research_task: Literal["visual_research", "documentary_audit"]


class CatalogueIn(Revised):
    workflow: Literal["museum", "collection", "auction"]
    catalogue: Catalogue


class AnalysisSelection(Revised):
    media_ids: list[str] = Field(max_length=8)


class CaseDocumentIn(Revised):
    document_id: str = Field(min_length=1, max_length=200)
    document_revision: int | None = Field(default=None, ge=1)
    document_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AnnotationIn(Revised):
    media_id: str = Field(min_length=1, max_length=200)
    region: list[float] = Field(min_length=4, max_length=4)
    feature: Literal["foot", "glaze", "decoration", "inscription", "body", "damage", "other"]
    observation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_region(self):
        Observation(media_id=self.media_id, region=self.region, visible=self.observation)
        return self


class EvidenceIn(Revised):
    filename: str = Field(min_length=1, max_length=200)
    image_base64: str = Field(max_length=28_000_000)
    view: str = Field(min_length=1, max_length=100)
    edit_declaration: str = Field(default="未知", max_length=1000)
    source: str = Field(default="用户提供，来源待核", max_length=1000)


class ReferenceIn(Mutation):
    title: str = Field(min_length=1, max_length=300)
    locator: str = Field(min_length=1, max_length=1000)
    source_url: str = Field(default="", max_length=2000)
    attribution: str = Field(min_length=1, max_length=1000)
    authority: str = Field(min_length=1, max_length=1000)
    permission: Literal["local_use_authorized", "unknown"] = "unknown"
    notes: str = ""
    filename: str = Field(min_length=1, max_length=200)
    image_base64: str = Field(max_length=28_000_000)


class RunIn(Revised):
    mode: Literal["skills", "plain"] = "skills"


class CorrectionIn(Revised):
    assessment_run_id: str
    review_method: Literal["image", "in_person", "document"]
    correction: str = Field(min_length=1, max_length=5000)
    basis: str = Field(min_length=1, max_length=5000)


class ReviewIn(Revised):
    assessment_run_id: str
    expected_review_revision: int = Field(ge=0)
    status: Literal["reviewed", "request_evidence"]
    review_method: Literal["image", "in_person", "document"]
    note: str = Field(min_length=1, max_length=5000)
    basis: str = Field(min_length=1, max_length=5000)


class Observation(Strict):
    media_id: str
    region: list[float] = Field(min_length=4, max_length=4)
    visible: str = Field(min_length=1, max_length=2000)
    interpretation: str = Field(default="", max_length=2000)
    limitation: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_region(self):
        x0, y0, x1, y1 = self.region
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("region 必须为原图归一化坐标 [x0,y0,x1,y1]")
        return self


class Claim(Strict):
    dimension: Literal["period", "kiln", "style"]
    candidate: str = Field(min_length=1, max_length=300)
    status: Literal["supported", "conflicting", "insufficient", "out_of_scope"]
    support: list[str] = Field(max_length=20)
    conflict: list[str] = Field(max_length=20)
    reasoning_summary: str = Field(min_length=1, max_length=2000)


class KnowledgeCitation(Strict):
    document_id: str = Field(min_length=1, max_length=200)
    document_revision: int = Field(ge=1)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunk_id: str = Field(min_length=1, max_length=200)
    chunk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=1000)
    use: Literal["method", "comparison_context", "source_context"]
    relevance: str = Field(min_length=1, max_length=1500)


class Assessment(Strict):
    basic_info: str = Field(min_length=1, max_length=3000)
    scope: Literal["bluewhite_gu", "ceramic_research", "out_of_scope"]
    claims: list[Claim] = Field(min_length=1, max_length=9)
    alternatives: list[str] = Field(min_length=1, max_length=5)
    condition_hypotheses: list[str] = Field(max_length=10)
    reference_ids: list[str] = Field(max_length=10)
    reference_comparison: str = Field(min_length=1, max_length=3000)
    limitations: list[str] = Field(min_length=1, max_length=10)
    revision_explanation: str = Field(min_length=1, max_length=2000)
    knowledge_citations: list[KnowledgeCitation] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def no_uncalibrated_authenticity_probability(self):
        # Descriptive pixel fractions are outside Assessment. Prevent presenting an
        # uncalibrated authenticity / AI-origin likelihood as a numerical finding.
        content = self.model_dump_json()
        subject = r"(?:真品|赝品|真伪|真假|真实性|AI.{0,3}生成|人工智能生成|authenticity|authentic|fake|ai.generated)"
        probability = r"(?:概率|置信|可能性|probability|confidence|likelihood)"
        number = r"(?:\d+(?:\.\d+)?\s*[%％]|0\.\d+|[一二三四五六七八九十]成)"
        patterns = [subject + r"[^，。;；\n]{0,16}" + probability + r"[^，。;；\n]{0,8}" + number,
                    number + r"[^，。;；\n]{0,16}" + subject,
                    subject + r"[^，。;；\n]{0,8}\d+(?:\.\d+)?\s*[%％]"]
        if any(re.search(p, content, flags=re.IGNORECASE) for p in patterns):
            raise ValueError("未经校准，不得输出真伪或AI生成的数值概率")
        return self


class DocumentaryCitation(Strict):
    kind: Literal["attachment", "knowledge"]
    document_id: str = Field(min_length=1, max_length=200)
    document_revision: int | None = Field(default=None, ge=1)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunk_id: str = Field(min_length=1, max_length=200)
    chunk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=1000)
    read_id: str = Field(min_length=1, max_length=200)
    relevance: str = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def revision_matches_kind(self):
        if (self.kind == "knowledge") != (self.document_revision is not None):
            raise ValueError("固定知识须注明版本，本案附件不使用知识版本号")
        return self


class DocumentaryFinding(Strict):
    question: str = Field(min_length=1, max_length=1000)
    status: Literal["consistent", "conflicting", "missing", "needs_review"]
    finding: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[DocumentaryCitation] = Field(min_length=1, max_length=8)
    next_evidence: str = Field(min_length=1, max_length=1500)
    limitations: list[str] = Field(min_length=1, max_length=5)


class DocumentaryAssessment(Strict):
    research_task: Literal["documentary_audit"] = "documentary_audit"
    summary: str = Field(min_length=1, max_length=3000)
    documentary_findings: list[DocumentaryFinding] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=10)
    revision_explanation: str = Field(min_length=1, max_length=2000)
    authenticity_verified: Literal[False] = False
    statement_truth_verified: Literal[False] = False

    @model_validator(mode="after")
    def documentary_scope(self):
        # This structural/text guard is not an authenticity or semantic verifier.
        conclusions = self.summary + "\n" + "\n".join(f.finding for f in self.documentary_findings)
        patterns = (r"(?:^|[。；;\n])\s*(?:(?:本件|此件|本器物|器物)[^。；;\n]{0,5})?(?:年代|时期|窑口|风格|制作时期|制作年代)(?:判定|断定|确定|认定|归属)?(?:为|是|属于|确定为)",
                    r"(?:^|[。；;\n])\s*(?:(?:本件|此件|本器物|器物)[^。；;\n]{0,5})?(?:断代为|出自.{0,20}窑|制作于.{0,20}(?:朝|代|年)|确认为真品|来源真实可靠|传承有序)",
                    r"(?:^|[.;\n])\s*(?:(?:the object|this object)\s+)?(?:period|kiln|style)\s+(?:is|attributed to|confirmed as)")
        # Explicitly marked quotations remain source statements. Plain direct
        # assertions, including a leading "结论：", are still forbidden.
        unquoted = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', '[来源引述]', conclusions)
        direct_assertions = (r"(?:年代|时期|窑口|风格|制作时期|制作年代)(?:判定|断定|确定|认定|归属)?(?:为|是|属于|确定为)",
                             r"(?:本件|此件|本器物|器物)(?:是|属于|出自)[^。；;\n]{0,30}(?:代|朝|窑|真品)",
                             r"(?:已核验|已证实|已认证|确认为|证实为)[^。；;\n]{0,30}(?:合法|真实|属实|真品)")
        if any(re.search(pattern, unquoted, re.I) for pattern in patterns + direct_assertions):
            raise ValueError("文字凭据核查不得作年代、窑口、风格或真实性归属结论；只核查已读材料的陈述关系")
        Assessment.no_uncalibrated_authenticity_probability(self)
        return self


class ReadEvidenceDocument(Strict):
    document_id: str = Field(min_length=1, max_length=200)
    offset: int = Field(default=0, ge=0, le=2000000)
    limit: int = Field(default=2, ge=1, le=3)


class ReadCaseRecords(Strict):
    collection: Literal["annotations", "provenance_events", "condition_checks", "evidence_documents", "catalogue", "corrections", "knowledge_links"]
    offset: int = Field(default=0, ge=0, le=20000)
    limit: int = Field(default=5, ge=1, le=8)
    text_offset: int = Field(default=0, ge=0, le=200000)


class Empty(Strict):
    pass


class LoadSkill(Strict):
    name: str


class ReadSkillResource(Strict):
    name: str
    path: str = Field(min_length=1, max_length=300)


class InspectRegion(Strict):
    media_id: str
    region: list[float] = Field(min_length=4, max_length=4)
    question: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_region(self):
        Observation(media_id=self.media_id, region=self.region, visible='坐标验证')
        return self


class ReviewIssue(Strict):
    claim_dimension: Literal['period', 'kiln', 'style', 'general']
    concern: str = Field(min_length=1, max_length=1500)
    reference_ids: list[str] = Field(max_length=10)


class CriticResponse(Strict):
    issues: list[ReviewIssue] = Field(max_length=8)
    suggested_evidence: str = Field(max_length=1500)
    limitations: list[str] = Field(min_length=1, max_length=5)


class CriticDisposition(Strict):
    issue_index: int = Field(ge=0, le=7)
    decision: Literal['accept', 'reject', 'unresolved']
    reason: str = Field(min_length=1, max_length=1500)


class RespondCritic(Strict):
    dispositions: list[CriticDisposition] = Field(max_length=8)


class TextObservation(Observation):
    id: str = Field(min_length=1, max_length=150)


class ReviewPacketIn(Revised):
    assessment_run_id: str
    permission: Literal['public', 'approved_redacted']
    approval_basis: str = Field(min_length=1, max_length=1500)
    claims: list[Claim] = Field(min_length=1, max_length=9)
    observations: list[TextObservation] = Field(max_length=20)
    references: list['TextReference'] = Field(max_length=10)
    question: str = Field(min_length=1, max_length=1000)


class TextReference(Strict):
    reference_id: str
    title: str = Field(min_length=1, max_length=300)
    locator: str = Field(min_length=1, max_length=1000)
    excerpt: str = Field(min_length=1, max_length=4000)


class ReviewCallIn(Mutation):
    packet_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class RegionIn(Revised):
    media_id: str
    region: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_region(self):
        Observation(media_id=self.media_id, region=self.region, visible='坐标验证')
        return self


class Inspect(Strict):
    media_ids: list[str] = Field(min_length=1, max_length=4)
    question: str = Field(min_length=1, max_length=1000)


class Retrieve(Strict):
    query: str = Field(min_length=1, max_length=200)


class ReadReference(Strict):
    reference_id: str


class SearchKnowledge(Strict):
    query: str = Field(min_length=1, max_length=200)


class ReadKnowledge(Strict):
    document_id: str = Field(min_length=1, max_length=200)
    chunk_id: str = Field(min_length=1, max_length=200)


class EvidenceRequest(Strict):
    view: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    distinguishes: str = Field(min_length=1, max_length=1000)
    capture_instructions: str = Field(min_length=1, max_length=1000)


class Action(Strict):
    tool: str
    arguments: dict


class Plan(Strict):
    actions: list[Action] = Field(min_length=1, max_length=6)
