"""Software and supplied-label contracts, never ceramic expert benchmarks."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from cizheng.knowledge import INDEXER_VERSION, validate_snapshot
from cizheng.store import Problem

from cizheng.claim_support_audit import (
    BODY_FIELDS, IDENTITY_FIELDS, audit_claim_support, build_audit_packet,
    main, region_iou, review_template,
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


@pytest.fixture
def run():
    """Original synthetic text; image metadata is synthetic and no image is read."""
    identity = {"document_id": "synthetic-source", "document_revision": 1,
                "document_sha256": "b" * 64, "chunk_id": "synthetic-paragraph",
                "chunk_sha256": "c" * 64, "locator": "合成段落1"}
    text = "资料甲讨论修复痕迹；该方法不能单独断代。"
    identity["chunk_sha256"] = fingerprint({"text": text, "locator": identity["locator"]})
    read = {**identity, "run_id": "synthetic-run", "content_kind": "authorized_text",
            "text": text, "snippet_start": 0, "snippet_end": len(text)}
    observation = {"id": "synthetic-observation", "run_id": "synthetic-run", "media_id": "synthetic-image",
                   "region": [0.1, 0.1, 0.6, 0.6], "coordinate_space": "exif-corrected-original-normalized",
                   "visible": "表面有圆圈装饰", "interpretation": "登记解释称为甲期，尚未验证", "limitation": "合成协议测试"}
    frozen = {"schema_version": 1, "indexer_version": INDEXER_VERSION, "index_version": "synthetic-index",
              "sources": [{"source": {"document_id": identity["document_id"], "revision": 1,
                  "document_sha256": identity["document_sha256"], "rights": "authorized_text"},
                  "chunks": [{**identity, "text": text, "content_kind": "authorized_text"}]}]}
    frozen["snapshot_sha256"] = fingerprint(frozen)
    return {"id": "synthetic-run", "case_id": "synthetic-case", "state": "waiting_evidence",
            "research_task": "visual_research", "snapshot": {
                "media": [{"id": "synthetic-image", "sha256": "a" * 64,
                           "width": 100, "height": 100, "view": "整体声明", "capture_role": "overall"}],
                "knowledge_links": [{key: identity[key] for key in ("document_id", "document_revision", "document_sha256")}],
                "catalogue": {"period": "EXPERT_SECRET_DO_NOT_USE_AS_PIXELS"},
                "expert_labels": {"kiln": "EXPERT_SECRET_SECOND_LABEL"}},
            "observations": [observation], "main_seen_media_ids": ["synthetic-image"],
            "read_knowledge": [read],
            "knowledge_snapshot": frozen,
            "versions": {"knowledge_snapshot_sha256": frozen["snapshot_sha256"]},
            "main_seen_knowledge_receipt_sha256": [fingerprint(identity)],
            "main_seen_knowledge_body_sha256": [fingerprint({key: read[key] for key in BODY_FIELDS})],
            "evidence_request": {"view": "合成底足", "reason": "补核缺失部位", "distinguishes": "尚缺鉴别依据"},
            "assessment": {"basic_info": "合成软件测试", "scope": "ceramic_research",
                "claims": [
                    {"dimension": "period", "candidate": "甲期", "status": "insufficient",
                     "support": [observation["id"]], "conflict": [], "reasoning_summary": "圆圈装饰符合甲期"},
                    {"dimension": "kiln", "candidate": "待核", "status": "insufficient",
                     "support": [], "conflict": [], "reasoning_summary": "无胎体证据，需补底足"},
                    {"dimension": "style", "candidate": "无圆圈装饰", "status": "conflicting",
                     "support": [], "conflict": [observation["id"]], "reasoning_summary": "可见圆圈装饰，与候选不符"}],
                "alternatives": ["后期添加装饰"], "condition_hypotheses": [], "reference_ids": ["synthetic-reference"],
                "reference_comparison": "资料只讨论方法，无法据此断代", "limitations": ["合成软件输入，无专业结论"],
                "revision_explanation": "测试原文保留", "knowledge_citations": [
                    {**identity, "use": "method", "relevance": "方法提醒不能仅凭纹饰断代"}]}}


def labels_for(run):
    labels = review_template(build_audit_packet(run))
    labels.update(reviewer="SYNTHETIC SOFTWARE TEST", reviewer_role="synthetic_test", independent_of_model=True)
    return labels


def source_label(packet, *, kind="object_inference", relation="does_not_support"):
    citation = packet["citations"][0]
    field = "claims.0.reasoning_summary" if kind == "object_inference" else "knowledge_citations.0.relevance"
    return {"citation_id": citation["citation_id"], "target_field": field, "target_kind": kind,
            "relation": relation, "target_excerpt": packet["report_fields"][field],
            "receipt_body_sha256": citation["delivered_excerpts"][0]["receipt_body_sha256"],
            "source_excerpt": "该方法不能单独断代", "basis": "合成标签测试：方法提醒没有提供甲期特征。"}


def test_identity_delivery_does_not_assign_semantic_support_or_read_images(run, monkeypatch):
    import httpx
    from PIL import Image

    def forbidden(*args, **kwargs):
        pytest.fail("This offline audit must not call HTTP, a model, or image decoding")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    before = deepcopy(run)
    result = audit_claim_support(run)
    packet = result["packet"]
    assert run == before
    citation = packet["citations"][0]
    assert citation["matches_saved_current_run_receipt"] and citation["eligible_for_text_review"]
    assert citation["semantic_support"] == "unreviewed"
    assert result["metrics"]["declared_observation_link_appropriateness"]["fully_positive_fraction"] is None
    assert result["metrics"]["reasoning"]["inference_bridge"]["assessed_denominator"] == 0
    assert result["metrics"]["reasoning"]["inference_bridge"]["pending_items"] == 3
    assert result["metrics"]["citation_mapping_coverage"]["unmapped_citations"] == 1
    assert result["semantic_status"] == "awaiting_review"
    assert not result["expert_validation_established"] and result["ceramic_accuracy"] == "not_measured"
    assert not packet["images"][0]["image_bytes_verified_by_this_tool"]
    assert "EXPERT_SECRET" not in json.dumps(packet, ensure_ascii=False)
    assert packet["observations"][0]["model_interpretation"] == run["observations"][0]["interpretation"]


def test_packet_hash_matches_existing_host_identity_algorithms(run):
    from cizheng.agent import knowledge_body_identity, knowledge_receipt_identity
    read = run["read_knowledge"][0]
    assert fingerprint({key: read[key] for key in IDENTITY_FIELDS}) == knowledge_receipt_identity(read)
    assert fingerprint({key: read[key] for key in BODY_FIELDS}) == knowledge_body_identity(read)
    packet = build_audit_packet(run)
    assert fingerprint({key: value for key, value in packet.items() if key != "packet_sha256"}) == packet["packet_sha256"]


@pytest.mark.parametrize("failure", ["old_run", "changed_locator", "changed_body", "not_sent", "pin_changed", "metadata"])
def test_ineligible_read_cannot_be_counted_as_semantic_evidence(run, failure):
    if failure == "old_run":
        run["read_knowledge"][0]["run_id"] = "previous-run"
    elif failure == "changed_locator":
        run["assessment"]["knowledge_citations"][0]["locator"] = "未读定位"
    elif failure == "changed_body":
        run["read_knowledge"][0]["text"] = "伪造文本长度改动"
    elif failure == "not_sent":
        run["main_seen_knowledge_body_sha256"] = []
    elif failure == "pin_changed":
        run["snapshot"]["knowledge_links"][0]["document_revision"] = 2
    else:
        run["read_knowledge"][0]["content_kind"] = "metadata"
    packet = build_audit_packet(run)
    assert not packet["citations"][0]["eligible_for_text_review"]
    labels = labels_for(run)
    labels["citations"] = [{"citation_id": "citation-0", "target_field": "claims.0.candidate",
                            "target_kind": "object_inference", "relation": "supports", "target_excerpt": "甲期",
                            "source_excerpt": "资料甲", "receipt_body_sha256": "a" * 64, "basis": "合成拒绝测试"}]
    with pytest.raises(ValueError, match="without_saved_exact_delivery"):
        audit_claim_support(run, labels)


def test_repeated_reads_select_only_exact_successfully_delivered_fragment(run):
    receipt = deepcopy(run["read_knowledge"][0])
    receipt.update(text="没有送达的另一片段", snippet_start=5, snippet_end=15)
    run["read_knowledge"].insert(0, receipt)
    excerpts = build_audit_packet(run)["citations"][0]["delivered_excerpts"]
    assert len(excerpts) == 1 and excerpts[0]["text"] != receipt["text"]


def test_source_statement_and_object_inference_are_scored_separately(run):
    packet = build_audit_packet(run)
    labels = labels_for(run)
    labels["citations"] = [source_label(packet), source_label(packet, kind="source_statement", relation="supports")]
    labels["reasoning"] = [{"claim_id": "claim-0-period", "criterion": "inference_bridge",
                            "verdict": "inadequate", "basis": "合成阅评：没有说明圆圈如何排除其它时期。"}]
    result = audit_claim_support(run, labels)
    metrics = result["metrics"]["citation_relations_by_target_kind"]
    assert metrics["object_inference"]["assessed_denominator"] == 1
    assert metrics["object_inference"]["fully_positive_fraction"] == 0
    assert metrics["source_statement"]["fully_positive_fraction"] == 1
    assert result["metrics"]["citation_mapping_coverage"] == {
        "mapped_citations": 1, "declared_citation_denominator": 1, "unmapped_citations": 0}
    assert result["metrics"]["reasoning"]["inference_bridge"]["fully_positive_fraction"] == 0
    assert not result["expert_validation_established"]
    assert result["packet"]["citations"][0]["semantic_support"] == "unreviewed"


@pytest.mark.parametrize("change,error", [
    ("source_excerpt", "citation_source_excerpt_not_in_delivered_text"),
    ("target_excerpt", "citation_target_excerpt_not_in_report"),
    ("body", "matching_delivered_excerpt_identity"),
    ("target_field", "unknown_citation_or_report_target"),
])
def test_semantic_label_requires_exact_report_and_delivered_text_anchors(run, change, error):
    packet = build_audit_packet(run)
    labels = labels_for(run)
    labels["citations"] = [source_label(packet)]
    key = "receipt_body_sha256" if change == "body" else change
    labels["citations"][0][key] = "d" * 64 if change == "body" else "未出现的内容"
    with pytest.raises(ValueError, match=error):
        audit_claim_support(run, labels)


def test_reading_full_paragraph_identity_does_not_allow_unseen_source_quote(run):
    read = run["read_knowledge"][0]
    read.update(text="资料甲讨论修复痕迹", snippet_end=len("资料甲讨论修复痕迹"))
    run["main_seen_knowledge_body_sha256"] = [fingerprint({key: read[key] for key in BODY_FIELDS})]
    packet = build_audit_packet(run)
    assert packet["citations"][0]["eligible_for_text_review"]
    labels = labels_for(run)
    labels["citations"] = [source_label(packet)]
    with pytest.raises(ValueError, match="source_excerpt_not_in_delivered_text"):
        audit_claim_support(run, labels)


def test_not_assessable_and_pending_are_visible_and_excluded_only_from_conditional_denominator(run):
    labels = labels_for(run)
    labels["reasoning"] = [
        {"claim_id": "claim-0-period", "criterion": "observed_basis", "verdict": "partial",
         "report_field": "claims.0.reasoning_summary", "report_excerpt": "圆圈装饰", "basis": "合成标签：有特征但不充分。"},
        {"claim_id": "claim-1-kiln", "criterion": "observed_basis", "verdict": "adequate",
         "report_field": "claims.1.reasoning_summary", "report_excerpt": "无胎体证据", "basis": "合成标签：对不足说明有根据。"},
        {"claim_id": "claim-2-style", "criterion": "observed_basis", "verdict": "not_assessable",
         "basis": "合成标签：尚无独立图像阅评。"}]
    result = audit_claim_support(run, labels)
    metric = result["metrics"]["reasoning"]["observed_basis"]
    assert metric["total_items"] == metric["labels_received"] == 3
    assert metric["not_assessable"] == 1 and metric["assessed_denominator"] == 2
    assert metric["fully_positive_count"] == 1 and metric["fully_positive_fraction"] == 0.5
    assert result["metrics"]["reasoning"]["missing_evidence"]["pending_items"] == 3
    assert result["metrics"]["reasoning"]["missing_evidence"]["fully_positive_fraction"] is None


def observation_label(**changes):
    value = {"observation_id": "synthetic-observation", "image_access": "original_pixels",
             "reviewed_media_sha256": "a" * 64, "visible_verdict": "correct", "region_verdict": "appropriate",
             "reviewer_region": [0.1, 0.1, 0.6, 0.6], "basis": "合成软件标签，未作真实图像或专业测试。"}
    return value | changes


def test_image_review_is_hash_bound_and_iou_is_descriptive_only(run):
    labels = labels_for(run)
    labels["observations"] = [observation_label()]
    result = audit_claim_support(run, labels)
    assert result["region_overlaps"][0]["iou"] == 1
    assert result["metrics"]["observation_visible_correctness"]["fully_positive_fraction"] == 1
    assert result["reviewer_identity_authenticated"] is False
    assert result["expert_validation_established"] is False
    assert region_iou([0, 0, 0.5, 0.5], [0.5, 0.5, 1, 1]) == 0
    labels["observations"][0]["reviewed_media_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="original_image_hash_mismatch"):
        audit_claim_support(run, labels)


@pytest.mark.parametrize("changes,error", [
    ({"image_access": "report_text_only"}, "requires_declared_original_pixel_access"),
    ({"reviewed_media_sha256": None}, "requires_declared_original_pixel_access"),
    ({"reviewer_region": [0.8, 0, 0.2, 1]}, "invalid_reviewer_region"),
    ({"reviewer_region": None}, "requires_reviewer_region"),
])
def test_source_labels_or_report_text_cannot_count_as_image_correctness(run, changes, error):
    labels = labels_for(run)
    labels["observations"] = [observation_label(**changes)]
    with pytest.raises(ValidationError, match=error):
        audit_claim_support(run, labels)


def test_text_reviewer_cannot_claim_image_access_and_expert_title_cannot_create_expert_validation(run):
    labels = labels_for(run)
    labels.update(reviewer_role="automated_text_reviewer")
    labels["observations"] = [observation_label()]
    with pytest.raises(ValueError, match="text_reviewer_cannot_claim_pixel_access"):
        audit_claim_support(run, labels)
    labels.update(reviewer_role="declared_domain_expert")
    result = audit_claim_support(run, labels)
    assert not result["expert_validation_established"]


def test_automated_multimodal_review_keeps_shared_context_and_expert_boundaries(run):
    labels = labels_for(run)
    labels.update(reviewer_role="automated_multimodal_reviewer", independent_of_model=False)
    labels["observations"] = [observation_label()]
    result = audit_claim_support(run, labels)
    assert result["review_labels"]["reviewer_role"] == "automated_multimodal_reviewer"
    assert not result["review_labels"]["independent_of_model"]
    assert result["metrics"]["observation_visible_correctness"]["assessed_denominator"] == 1
    assert not result["reviewer_identity_authenticated"] and not result["expert_validation_established"]
    assert result["ceramic_accuracy"] == "not_measured"
    labels["observations"][0]["reviewed_media_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="original_image_hash_mismatch"):
        audit_claim_support(run, labels)


def test_observation_link_review_uses_visible_description_and_declared_role(run):
    packet = build_audit_packet(run)
    link = next(item for item in packet["observation_links"] if item["declared_role"] == "conflict")
    labels = labels_for(run)
    labels["observation_links"] = [{"link_id": link["link_id"], "relation": "contradicts",
                                    "claim_excerpt": "无圆圈装饰", "visible_excerpt": "圆圈装饰",
                                    "basis": "合成标签：文本描述与候选冲突；尚不说明像素事实。"}]
    result = audit_claim_support(run, labels)
    metric = result["metrics"]["declared_observation_link_appropriateness"]
    assert metric["total_items"] == 2 and metric["pending_items"] == 1
    assert metric["assessed_denominator"] == 1 and metric["fully_positive_fraction"] == 1
    labels["observation_links"][0]["visible_excerpt"] = "登记解释称为甲期"
    with pytest.raises(ValueError, match="visible_excerpt_not_in_observation_description"):
        audit_claim_support(run, labels)


def test_unavailable_observation_link_and_duplicate_links_remain_visible(run):
    run["assessment"]["claims"][0]["support"] += ["synthetic-observation", "unknown-observation"]
    packet = build_audit_packet(run)
    assert len(packet["observation_links"]) == 3  # Duplicate role is not counted twice.
    assert {item["code"] for item in packet["findings"]} >= {
        "duplicate_declared_observation_link", "claim_links_unavailable_observation"}
    unavailable = next(item for item in packet["observation_links"] if not item["eligible_observation_link"])
    labels = labels_for(run)
    labels["observation_links"] = [{"link_id": unavailable["link_id"], "relation": "supports",
                                    "claim_excerpt": "甲期", "visible_excerpt": "圆圈", "basis": "合成拒绝测试。"}]
    with pytest.raises(ValueError, match="unavailable_observation_cannot_receive_support"):
        audit_claim_support(run, labels)


@pytest.mark.parametrize("collection", ["observations", "observation_links", "citations", "reasoning"])
def test_repeated_labels_cannot_inflate_denominators(run, collection):
    packet = build_audit_packet(run)
    labels = labels_for(run)
    sample = {"observations": observation_label(), "citations": source_label(packet),
              "reasoning": {"claim_id": "claim-0-period", "criterion": "inference_bridge", "verdict": "inadequate", "basis": "合成测试"},
              "observation_links": {"link_id": packet["observation_links"][0]["link_id"], "relation": "not_assessable", "basis": "合成测试"}}[collection]
    labels[collection] = [sample, deepcopy(sample)]
    with pytest.raises(ValueError, match="duplicate_"):
        audit_claim_support(run, labels)


def test_stale_labels_and_hidden_answer_fields_are_rejected(run):
    labels = labels_for(run)
    run["assessment"]["claims"][0]["reasoning_summary"] = "修订后未评理由"
    with pytest.raises(ValueError, match="do_not_match_frozen_run"):
        audit_claim_support(run, labels)
    labels = labels_for(run)
    labels["expected_period"] = "不得当作图像事实的答案"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        audit_claim_support(run, labels)


def test_reasoning_excerpt_cannot_be_borrowed_from_another_claim(run):
    labels = labels_for(run)
    labels["reasoning"] = [{"claim_id": "claim-0-period", "criterion": "observed_basis", "verdict": "adequate",
                            "report_field": "claims.1.reasoning_summary", "report_excerpt": "无胎体证据", "basis": "合成拒绝测试"}]
    with pytest.raises(ValueError, match="belongs_to_another_claim"):
        audit_claim_support(run, labels)


def test_failed_run_is_retained_as_no_result_without_correctness_denominator(run):
    run.update(state="failed", assessment=None)
    result = audit_claim_support(run)
    assert result["packet"]["run_state"] == "failed"
    assert not result["packet"]["assessment_present"]
    assert result["packet"]["findings"][0]["code"] == "no_saved_visual_assessment"
    assert result["metrics"]["reasoning"]["inference_bridge"]["total_items"] == 0
    assert result["metrics"]["reasoning"]["inference_bridge"]["fully_positive_fraction"] is None


@pytest.mark.parametrize("phase,observation_count,link_count", [("initial", 2, 0), ("revision", 3, 2)])
def test_actual_round12_published_commitment_mismatch_never_exports_body_or_semantic_results(phase, observation_count, link_count):
    root = Path(__file__).resolve().parents[1]
    run = json.loads((root / "verification/nvidia/v07-workflows/round-12" / phase / "final-run.json").read_text())
    before = deepcopy(run)
    result = audit_claim_support(run)
    packet = result["packet"]
    assert len(packet["claims"]) == 3 and len(packet["observations"]) == observation_count
    assert len(packet["observation_links"]) == link_count
    # The historical public projection already has an invalid snapshot
    # commitment. Preserve it; do not repair a real record to make it pass.
    with pytest.raises(Problem):
        validate_snapshot(run["knowledge_snapshot"])
    assert not packet["citations"][0]["eligible_for_text_review"]
    assert packet["citations"][0]["delivered_excerpts"] == []
    assert "knowledge_snapshot_invalid_commitment" in {item["code"] for item in packet["findings"]}
    assert result["metrics"]["reasoning"]["inference_bridge"]["pending_items"] == 3
    assert result["semantic_status"] == "awaiting_review"
    assert result["metrics"]["citation_mapping_coverage"]["unmapped_citations"] == 1
    assert run == before and not result["expert_validation_established"]
    if phase == "revision":
        assert packet["claims"][2]["reasoning_summary"] == "装饰布局对称，符合清代风格"
        assert packet["claims"][2]["support_semantics"] == "unreviewed"


def _recommit_in_memory_fixture(value, *, bind_run=True):
    """For adversarial test construction only; never saves or repairs a run."""
    snapshot = value["knowledge_snapshot"]
    snapshot["snapshot_sha256"] = fingerprint({key: snapshot[key] for key in (
        "schema_version", "indexer_version", "index_version", "sources")})
    if bind_run:
        value["versions"]["knowledge_snapshot_sha256"] = snapshot["snapshot_sha256"]


@pytest.mark.parametrize("mutation,diagnostic", [
    ("hash", "knowledge_snapshot_invalid_commitment"),
    ("run_commitment", "knowledge_snapshot_run_commitment_mismatch"),
    ("foreign_document", "citation_snapshot_paragraph_owner_mismatch"),
    ("foreign_revision", "citation_snapshot_paragraph_owner_mismatch"),
    ("duplicate_source", "knowledge_snapshot_duplicate_source_id"),
    ("conflicting_source", "knowledge_snapshot_duplicate_source_id"),
    ("duplicate_paragraph", "citation_snapshot_paragraph_not_unique"),
])
def test_hash_matching_receipts_cannot_bypass_frozen_commitment_and_paragraph_owner(run, mutation, diagnostic):
    snapshot = run["knowledge_snapshot"]
    entry = snapshot["sources"][0]
    if mutation == "hash":
        snapshot["snapshot_sha256"] = "0" * 64
    elif mutation == "run_commitment":
        run["versions"]["knowledge_snapshot_sha256"] = "0" * 64
    elif mutation in ("foreign_document", "foreign_revision"):
        field = "document_id" if mutation == "foreign_document" else "document_revision"
        entry["chunks"][0][field] = "foreign-source" if mutation == "foreign_document" else 2
        _recommit_in_memory_fixture(run)
    elif mutation in ("duplicate_source", "conflicting_source"):
        duplicate = deepcopy(entry)
        if mutation == "conflicting_source":
            duplicate["source"]["rights"] = "unknown"
        snapshot["sources"].append(duplicate)
        _recommit_in_memory_fixture(run)
    else:
        entry["chunks"].append(deepcopy(entry["chunks"][0]))
        _recommit_in_memory_fixture(run)
    if mutation != "hash":
        # Even a self-consistent snapshot cannot erase run binding, ownership,
        # or ambiguous-source failures. A hash match is not enough.
        validate_snapshot(snapshot)
    before = deepcopy(run)
    result = audit_claim_support(run)
    citation = result["packet"]["citations"][0]
    assert citation["matches_saved_current_run_receipt"] and citation["recorded_identity_delivery"]
    assert not citation["authorized_saved_source"] and not citation["eligible_for_text_review"]
    assert citation["delivered_excerpts"] == []
    assert diagnostic in {item["code"] for item in result["packet"]["findings"]}
    assert run == before and result["semantic_status"] == "awaiting_review"


@pytest.fixture
def original_real_saved_run():
    """Optional original artifact; caller supplies its path, never an answer key.

    Local validation uses the original main8b-r2 final-run.json. Public/CI runs
    without that artifact still execute every portable corruption contract.
    """
    configured = os.environ.get("CIZHENG_AUDIT_SAVED_RUN")
    if not configured or not Path(configured).is_file():
        pytest.skip("Original real run artifact not provided via CIZHENG_AUDIT_SAVED_RUN")
    value = json.loads(Path(configured).read_text(encoding="utf-8"))
    validate_snapshot(value["knowledge_snapshot"])
    assert value["versions"]["knowledge_snapshot_sha256"] == value["knowledge_snapshot"]["snapshot_sha256"]
    return value


def test_original_real_saved_run_keeps_only_original_delivered_excerpt_and_no_accuracy_score(original_real_saved_run):
    run = original_real_saved_run
    before = deepcopy(run)
    packet = build_audit_packet(run)
    assert packet["citations"]
    for citation in packet["citations"]:
        assert citation["authorized_saved_source"] and citation["eligible_for_text_review"]
        reads = [read for read in run["read_knowledge"] if read["document_id"] == citation["document_id"]
                 and read["chunk_id"] == citation["chunk_id"] and read["run_id"] == run["id"]]
        assert all(excerpt["text"] in [read["text"] for read in reads] for excerpt in citation["delivered_excerpts"])
        assert citation["semantic_support"] == "unreviewed"
    result = audit_claim_support(run)
    assert run == before and result["semantic_status"] == "awaiting_review"
    assert not result["expert_validation_established"] and result["ceramic_accuracy"] == "not_measured"
    assert all(item["assessed_denominator"] == 0 for item in result["metrics"]["reasoning"].values())


@pytest.mark.parametrize("mutation,diagnostic", [
    ("snapshot_sha256", "knowledge_snapshot_invalid_commitment"),
    ("rights_note", "knowledge_snapshot_invalid_commitment"),
    ("paragraph_document", "knowledge_snapshot_invalid_commitment"),
    ("paragraph_revision", "knowledge_snapshot_invalid_commitment"),
    ("recommitted_paragraph_document", "citation_snapshot_paragraph_owner_mismatch"),
    ("recommitted_paragraph_revision", "citation_snapshot_paragraph_owner_mismatch"),
    ("recommitted_conflicting_source", "knowledge_snapshot_duplicate_source_id"),
    ("snapshot_recommit_without_run", "knowledge_snapshot_run_commitment_mismatch"),
])
def test_original_real_run_tampering_retains_diagnostic_without_export(original_real_saved_run, mutation, diagnostic):
    run = deepcopy(original_real_saved_run)
    cited = run["assessment"]["knowledge_citations"][0]
    entry = next(item for item in run["knowledge_snapshot"]["sources"]
                 if item["source"]["document_id"] == cited["document_id"])
    paragraph = next(item for item in entry["chunks"] if item["chunk_id"] == cited["chunk_id"])
    if mutation == "snapshot_sha256":
        run["knowledge_snapshot"]["snapshot_sha256"] = "0" * 64
    elif mutation in ("rights_note", "snapshot_recommit_without_run"):
        entry["source"]["rights_note"] += " · changed for offline counterexample"
        if mutation == "snapshot_recommit_without_run":
            _recommit_in_memory_fixture(run, bind_run=False)
    elif mutation == "recommitted_conflicting_source":
        duplicate = deepcopy(entry)
        duplicate["source"]["rights"] = "unknown"
        run["knowledge_snapshot"]["sources"].append(duplicate)
        _recommit_in_memory_fixture(run)
    else:
        field = "document_id" if mutation.endswith("document") else "document_revision"
        paragraph[field] = "foreign-source" if field == "document_id" else cited["document_revision"] + 1
        if mutation.startswith("recommitted_"):
            _recommit_in_memory_fixture(run)
    if diagnostic == "knowledge_snapshot_invalid_commitment":
        with pytest.raises(Problem):
            validate_snapshot(run["knowledge_snapshot"])
    else:
        validate_snapshot(run["knowledge_snapshot"])
    packet = build_audit_packet(run)
    citation = packet["citations"][0]
    assert citation["matches_saved_current_run_receipt"]
    assert citation["delivered_excerpts"] == [] and not citation["eligible_for_text_review"]
    assert diagnostic in {item["code"] for item in packet["findings"]}
    assert not packet["expert_validation_established"]


def test_cli_keeps_audit_and_labels_separate_and_refuses_overwrite(run, tmp_path):
    saved = tmp_path / "saved-run.json"
    output, template = tmp_path / "audit.json", tmp_path / "review-template.json"
    saved.write_text(json.dumps(run, ensure_ascii=False))
    args = ["--run", str(saved), "--output", str(output), "--review-template", str(template)]
    main(args)
    result = json.loads(output.read_text())
    assert result["semantic_status"] == "awaiting_review" and result["review_labels"] is None
    assert json.loads(template.read_text())["citations"] == []
    original = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2 and output.read_bytes() == original
    labels = labels_for(run)
    labels["packet_sha256"] = "f" * 64
    label_file = tmp_path / "stale-labels.json"
    label_file.write_text(json.dumps(labels))
    bad_output = tmp_path / "must-not-exist.json"
    with pytest.raises(ValueError, match="do_not_match_frozen_run"):
        main(["--run", str(saved), "--labels", str(label_file), "--output", str(bad_output)])
    assert not bad_output.exists()
