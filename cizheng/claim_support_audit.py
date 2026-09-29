"""Offline, label-conditional review of saved visual research opinions.

Receipt/version checks are software facts. They never assign semantic support,
image correctness, ceramic attribution, or expert authority. Reviewer judgments
are a separate sidecar bound to the frozen run and review packet. This module
does not read images, call a model, send evidence, or change a saved opinion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .knowledge import validate_snapshot
from .schemas import Assessment, Observation
from .store import Problem


SCHEMA_VERSION = "claim-support-audit-v1"
IDENTITY_FIELDS = ("document_id", "document_revision", "document_sha256",
                   "chunk_id", "chunk_sha256", "locator")
BODY_FIELDS = IDENTITY_FIELDS + ("text", "snippet_start", "snippet_end", "content_kind")
REASONING_CRITERIA = ("observed_basis", "inference_bridge", "alternative_explanations",
                      "missing_evidence")
NotBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Relation = Literal["supports", "partial", "does_not_support", "contradicts", "not_assessable"]
ReasoningVerdict = Literal["adequate", "partial", "inadequate", "not_assessable"]


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _region_valid(region):
    if not isinstance(region, list) or len(region) != 4:
        return False
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in region):
        return False
    x0, y0, x1, y1 = region
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def region_iou(first, second):
    """Descriptive overlap with a reviewer box; no correctness threshold."""
    if not _region_valid(first) or not _region_valid(second):
        raise ValueError("invalid_normalized_region")
    x0, y0 = max(first[0], second[0]), max(first[1], second[1])
    x1, y1 = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, x1 - x0) * max(0, y1 - y0)
    areas = [(box[2] - box[0]) * (box[3] - box[1]) for box in (first, second)]
    return overlap / (sum(areas) - overlap)


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ObservationJudgment(ReviewModel):
    observation_id: NotBlank
    image_access: Literal["original_pixels", "report_text_only"]
    reviewed_media_sha256: Sha256 | None = None
    visible_verdict: Literal["correct", "partial", "incorrect", "not_assessable"]
    region_verdict: Literal["appropriate", "partial", "incorrect", "not_assessable"]
    reviewer_region: list[float] | None = Field(default=None, min_length=4, max_length=4)
    basis: NotBlank

    @model_validator(mode="after")
    def pixels_needed(self):
        assessed = self.visible_verdict != "not_assessable" or self.region_verdict != "not_assessable"
        if (assessed or self.reviewer_region is not None) and (self.image_access != "original_pixels" or not self.reviewed_media_sha256):
            raise ValueError("image_judgment_requires_declared_original_pixel_access_and_hash")
        if self.region_verdict != "not_assessable" and self.reviewer_region is None:
            raise ValueError("region_judgment_requires_reviewer_region")
        if self.reviewer_region is not None and not _region_valid(self.reviewer_region):
            raise ValueError("invalid_reviewer_region")
        return self


class ObservationLinkJudgment(ReviewModel):
    link_id: NotBlank
    relation: Relation
    claim_excerpt: str = Field(default="", max_length=2000)
    visible_excerpt: str = Field(default="", max_length=2000)
    basis: NotBlank


class CitationJudgment(ReviewModel):
    citation_id: NotBlank
    target_field: NotBlank
    target_kind: Literal["source_statement", "object_inference", "method"]
    relation: Relation
    target_excerpt: str = Field(default="", max_length=3000)
    receipt_body_sha256: Sha256 | None = None
    source_excerpt: str = Field(default="", max_length=4000)
    basis: NotBlank


class ReasoningJudgment(ReviewModel):
    claim_id: NotBlank
    criterion: Literal["observed_basis", "inference_bridge", "alternative_explanations", "missing_evidence"]
    verdict: ReasoningVerdict
    report_field: str = Field(default="", max_length=200)
    report_excerpt: str = Field(default="", max_length=3000)
    basis: NotBlank


class ReviewLabels(ReviewModel):
    schema_version: Literal["claim-support-review-v1"]
    run_input_sha256: Sha256
    packet_sha256: Sha256
    reviewer: NotBlank
    reviewer_role: Literal["human_reviewer", "declared_domain_expert", "automated_text_reviewer",
                           "automated_multimodal_reviewer", "synthetic_test"]
    independent_of_model: bool
    observations: list[ObservationJudgment] = Field(default_factory=list, max_length=100)
    observation_links: list[ObservationLinkJudgment] = Field(default_factory=list, max_length=400)
    citations: list[CitationJudgment] = Field(default_factory=list, max_length=100)
    reasoning: list[ReasoningJudgment] = Field(default_factory=list, max_length=36)


def _unique(items, key, error):
    values = [key(item) for item in items]
    if len(set(values)) != len(values):
        raise ValueError(error)


def _report_fields(assessment, evidence_request):
    fields = {}
    for key in ("basic_info", "reference_comparison", "revision_explanation"):
        fields[key] = assessment[key]
    for key in ("alternatives", "condition_hypotheses", "limitations"):
        fields.update({f"{key}.{i}": text for i, text in enumerate(assessment[key])})
    for i, claim in enumerate(assessment["claims"]):
        for key in ("candidate", "reasoning_summary"):
            fields[f"claims.{i}.{key}"] = claim[key]
    for i, citation in enumerate(assessment["knowledge_citations"]):
        fields[f"knowledge_citations.{i}.relevance"] = citation["relevance"]
    for key, text in (evidence_request or {}).items():
        if isinstance(text, str):
            fields[f"evidence_request.{key}"] = text
    return fields


def _frozen_snapshot_for_audit(run):
    """Reuse the host commitment and reject ambiguous source ownership."""
    try:
        frozen = validate_snapshot(run.get("knowledge_snapshot"))
    except Problem:
        return None, "knowledge_snapshot_invalid_commitment"
    versions = run.get("versions")
    recorded_hash = versions.get("knowledge_snapshot_sha256") if isinstance(versions, dict) else None
    if recorded_hash != frozen["snapshot_sha256"]:
        return None, "knowledge_snapshot_run_commitment_mismatch"
    ids = []
    for entry in frozen["sources"]:
        source = entry.get("source") if isinstance(entry, dict) else None
        if (not isinstance(source, dict) or not isinstance(source.get("document_id"), str)
                or not source["document_id"] or type(source.get("revision")) is not int
                or source["revision"] < 1 or not isinstance(entry.get("chunks"), list)):
            return None, "knowledge_snapshot_source_schema_invalid"
        if (source.get("id", source["document_id"]) != source["document_id"]
                or source.get("document_revision", source["revision"]) != source["revision"]):
            return None, "knowledge_snapshot_source_identity_conflict"
        ids.append(source["document_id"])
    if len(set(ids)) != len(ids):
        return None, "knowledge_snapshot_duplicate_source_id"
    return frozen, None


def _authorized_snapshot_chunk(frozen, citation):
    """Only one case-bound paragraph owned by this frozen version can expose text."""
    for entry in frozen["sources"]:
        source = entry["source"]
        if (source["document_id"] != citation["document_id"]
                or source.get("rights") != "authorized_text"
                or source["revision"] != citation["document_revision"]
                or source.get("document_sha256") != citation["document_sha256"]):
            continue
        candidates = [chunk for chunk in entry["chunks"]
                      if isinstance(chunk, dict) and chunk.get("chunk_id") == citation["chunk_id"]]
        if len(candidates) > 1:
            return None, "citation_snapshot_paragraph_not_unique"
        for chunk in candidates:
            if (chunk.get("document_id") != source["document_id"]
                    or type(chunk.get("document_revision")) is not int
                    or chunk["document_revision"] != source["revision"]):
                return None, "citation_snapshot_paragraph_owner_mismatch"
            if (chunk.get("chunk_sha256") == citation["chunk_sha256"]
                    and chunk.get("locator") == citation["locator"]
                    and chunk.get("content_kind") == "authorized_text"
                    and isinstance(chunk.get("text"), str)
                    and _digest({"text": chunk["text"], "locator": chunk["locator"]}) == citation["chunk_sha256"]):
                return chunk, None
    return None, None


def build_audit_packet(run: dict) -> dict:
    """Project a saved visual run without promoting catalogue/labels to facts.

    All provenance booleans below mean only 'recorded in the submitted run'.
    Hashes bind that submission; they do not authenticate the submitting host.
    """
    if not isinstance(run, dict) or not isinstance(run.get("id"), str) or not run["id"]:
        raise ValueError("saved_run_id_required")
    if run.get("research_task", "visual_research") != "visual_research":
        raise ValueError("visual_research_run_required")
    raw_assessment = run.get("assessment")
    assessment = Assessment.model_validate(raw_assessment).model_dump() if raw_assessment is not None else None
    snapshot = run.get("snapshot") or {}
    media = snapshot.get("media", [])
    observations = run.get("observations", [])
    _unique(media, lambda item: item["id"], "duplicate_media_id")
    _unique(observations, lambda item: item["id"], "duplicate_observation_id")
    image_by_id = {item["id"]: item for item in media}
    main_seen = set(run.get("main_seen_media_ids", []))
    findings = []

    def note(code, subject):
        findings.append({"code": code, "subject": subject, "semantic_verdict": "not_assigned"})

    images = [{"media_id": item["id"], "declared_original_sha256": item.get("sha256"),
               "width": item.get("width"), "height": item.get("height"),
               "view_declaration": item.get("view", ""),
               "capture_role_declaration": item.get("capture_role", "unknown"),
               "recorded_main_delivery": item["id"] in main_seen,
               "image_bytes_verified_by_this_tool": False} for item in media]
    observed = []
    for item in observations:
        try:
            if not _region_valid(item.get("region")):
                raise ValueError("invalid_original_region")
            Observation.model_validate({key: item[key] for key in Observation.model_fields if key in item})
            schema_valid = True
        except ValueError:
            schema_valid = False
            note("invalid_observation_schema", item["id"])
        current = item.get("run_id") == run["id"]
        image = image_by_id.get(item.get("media_id"))
        eligible = schema_valid and current and image is not None and item.get("media_id") in main_seen
        if not eligible:
            note("observation_not_linkable_in_saved_run", item["id"])
        observed.append({"observation_id": item["id"], "media_id": item.get("media_id"),
                         "declared_original_sha256": image.get("sha256") if image else None,
                         "coordinate_space": item.get("coordinate_space", "unknown"),
                         "region": deepcopy(item.get("region")), "region_valid": _region_valid(item.get("region")),
                         "model_visible_description": item.get("visible", ""),
                         "model_interpretation": item.get("interpretation", ""),
                         "model_limitation": item.get("limitation", ""),
                         "recorded_current_run": current, "eligible_observation_link": eligible,
                         "image_correctness": "unreviewed"})
    observed_by_id = {item["observation_id"]: item for item in observed}
    claims, links, citations = [], [], []
    if assessment is None:
        note("no_saved_visual_assessment", run["id"])
    else:
        dimensions = Counter(claim["dimension"] for claim in assessment["claims"])
        if dimensions != Counter({"period": 1, "kiln": 1, "style": 1}):
            note("claim_dimensions_not_one_each", run["id"])
        for i, claim in enumerate(assessment["claims"]):
            claim_id = f"claim-{i}-{claim['dimension']}"
            claims.append({"claim_id": claim_id, "report_index": i, **deepcopy(claim),
                           "support_semantics": "unreviewed"})
            if not claim["support"] and not claim["conflict"]:
                note("claim_has_no_declared_observation_link", claim_id)
            if claim["status"] in ("supported", "conflicting") and not assessment["reference_ids"]:
                note("explicit_attribution_without_image_reference", claim_id)
            for role in ("support", "conflict"):
                if len(claim[role]) != len(set(claim[role])):
                    note("duplicate_declared_observation_link", claim_id + ":" + role)
                for observation_id in dict.fromkeys(claim[role]):
                    observation = observed_by_id.get(observation_id)
                    link_id = "link-" + _digest([claim_id, observation_id, role])[:20]
                    links.append({"link_id": link_id, "claim_id": claim_id,
                                  "observation_id": observation_id, "declared_role": role,
                                  "eligible_observation_link": bool(observation and observation["eligible_observation_link"]),
                                  "relation": "unreviewed"})
                    if not links[-1]["eligible_observation_link"]:
                        note("claim_links_unavailable_observation", link_id)
        pins = {item["document_id"]: item for item in snapshot.get("knowledge_links", [])}
        proofs = set(run.get("main_seen_knowledge_body_sha256", []))
        identity_proofs = set(run.get("main_seen_knowledge_receipt_sha256", []))
        frozen, snapshot_error = _frozen_snapshot_for_audit(run) if assessment["knowledge_citations"] else (None, None)
        if snapshot_error:
            note(snapshot_error, run["id"])
        for i, citation in enumerate(assessment["knowledge_citations"]):
            citation_id = f"citation-{i}"
            identity = {key: citation[key] for key in IDENTITY_FIELDS}
            reads = [item for item in run.get("read_knowledge", [])
                     if item.get("run_id") == run["id"] and all(item.get(key) == val for key, val in identity.items())]
            pin = pins.get(citation["document_id"])
            fixed = bool(pin and all(pin.get(key) == citation[key]
                                     for key in ("document_revision", "document_sha256")))
            authorized_chunk, chunk_error = _authorized_snapshot_chunk(frozen, citation) if fixed and frozen else (None, None)
            if chunk_error:
                note(chunk_error, citation_id)
            excerpts = []
            for read in reads:
                start, end, text = read.get("snippet_start"), read.get("snippet_end"), read.get("text")
                if (not all(key in read for key in BODY_FIELDS) or read.get("content_kind") != "authorized_text"
                        or not isinstance(text, str) or not text.strip() or type(start) is not int
                        or type(end) is not int or not 0 <= start < end or len(text) != end - start):
                    continue
                if authorized_chunk is None or text != authorized_chunk["text"][start:end]:
                    continue
                body_hash = _digest({key: read[key] for key in BODY_FIELDS})
                if body_hash in proofs and not any(item["receipt_body_sha256"] == body_hash for item in excerpts):
                    excerpts.append({"receipt_body_sha256": body_hash, "text": text,
                                     "snippet_start": start, "snippet_end": end})
            eligible = bool(reads and fixed and excerpts and _digest(identity) in identity_proofs)
            citations.append({"citation_id": citation_id, **deepcopy(citation),
                              "matches_saved_current_run_receipt": bool(reads), "matches_saved_case_version_pin": fixed,
                              "authorized_saved_source": authorized_chunk is not None,
                              "recorded_identity_delivery": _digest(identity) in identity_proofs,
                              "delivered_excerpts": excerpts, "eligible_for_text_review": eligible,
                              "semantic_support": "unreviewed"})
            if not reads:
                note("citation_identity_not_in_saved_current_run_reads", citation_id)
            if not fixed:
                note("citation_fixed_case_version_mismatch", citation_id)
            if authorized_chunk is None:
                note("citation_saved_source_authorization_not_established", citation_id)
            if not eligible:
                note("citation_exact_excerpt_delivery_not_established", citation_id)

    packet = {"schema_version": SCHEMA_VERSION, "run_id": run["id"], "case_id": run.get("case_id"),
              "run_state": run.get("state", "unknown"), "run_input_sha256": _digest(run),
              "assessment_sha256": _digest(raw_assessment), "assessment_present": assessment is not None,
              "images": images, "observations": observed, "claims": claims, "observation_links": links,
              "citations": citations, "report_fields": _report_fields(assessment, run.get("evidence_request")) if assessment else {},
              "findings": findings, "model_inference_performed": False, "expert_validation_established": False,
              "notice": "保存记录与哈希仅供回查；图像描述、引用支持和判断理由须另行阅评。登记标签不是图像事实。"}
    packet["packet_sha256"] = _digest(packet)
    return packet


def review_template(packet):
    return {"schema_version": "claim-support-review-v1", "run_input_sha256": packet["run_input_sha256"],
            "packet_sha256": packet["packet_sha256"], "reviewer": "填写阅评人或工具说明",
            "reviewer_role": "human_reviewer", "independent_of_model": False,
            "observations": [], "observation_links": [], "citations": [], "reasoning": []}


def _contains(container, excerpt, error):
    if not excerpt.strip() or excerpt not in container:
        raise ValueError(error)


def _metric(total, statuses, positive, unit):
    counts = Counter(statuses)
    assessed = len(statuses) - counts["not_assessable"]
    fully_positive = sum(counts[label] for label in positive)
    return {"unit": unit, "total_items": total, "labels_received": len(statuses),
            "pending_items": total - len(statuses), "not_assessable": counts["not_assessable"],
            "assessed_denominator": assessed, "fully_positive_count": fully_positive,
            "fully_positive_fraction": fully_positive / assessed if assessed else None,
            "label_coverage": len(statuses) / total if total else None,
            "verdict_counts": dict(counts)}


def audit_claim_support(run: dict, labels: dict | None = None) -> dict:
    """Scores only supplied, anchored labels; no aggregate ceramic accuracy."""
    packet = build_audit_packet(run)
    review = ReviewLabels.model_validate(labels) if labels is not None else None
    if review and (review.run_input_sha256 != packet["run_input_sha256"] or review.packet_sha256 != packet["packet_sha256"]):
        raise ValueError("review_labels_do_not_match_frozen_run_and_packet")
    observations = {item["observation_id"]: item for item in packet["observations"]}
    claims = {item["claim_id"]: item for item in packet["claims"]}
    links = {item["link_id"]: item for item in packet["observation_links"]}
    citations = {item["citation_id"]: item for item in packet["citations"]}
    obs_labels = review.observations if review else []
    link_labels = review.observation_links if review else []
    cite_labels = review.citations if review else []
    reason_labels = review.reasoning if review else []
    _unique(obs_labels, lambda item: item.observation_id, "duplicate_observation_judgment")
    _unique(link_labels, lambda item: item.link_id, "duplicate_observation_link_judgment")
    _unique(cite_labels, lambda item: (item.citation_id, item.target_field, item.target_kind), "duplicate_citation_target_judgment")
    _unique(reason_labels, lambda item: (item.claim_id, item.criterion), "duplicate_reasoning_judgment")
    overlaps = []
    for label in obs_labels:
        observed = observations.get(label.observation_id)
        if observed is None:
            raise ValueError("unknown_review_observation_id")
        if label.reviewed_media_sha256 is not None and label.reviewed_media_sha256 != observed["declared_original_sha256"]:
            raise ValueError("reviewed_original_image_hash_mismatch")
        if review.reviewer_role == "automated_text_reviewer" and label.image_access == "original_pixels":
            raise ValueError("text_reviewer_cannot_claim_pixel_access")
        if label.reviewer_region is not None:
            if observed["coordinate_space"] != "exif-corrected-original-normalized" or not observed["region_valid"]:
                raise ValueError("localization_overlap_requires_valid_original_coordinate_space")
            overlaps.append({"observation_id": label.observation_id,
                             "iou": region_iou(observed["region"], label.reviewer_region),
                             "meaning": "overlap_with_supplied_reviewer_box_only"})
    for label in link_labels:
        link = links.get(label.link_id)
        if link is None:
            raise ValueError("unknown_declared_observation_link")
        if label.relation != "not_assessable":
            if not link["eligible_observation_link"]:
                raise ValueError("unavailable_observation_cannot_receive_support_judgment")
            claim = claims[link["claim_id"]]
            _contains(claim["candidate"] + "\n" + claim["reasoning_summary"], label.claim_excerpt, "claim_excerpt_not_in_saved_claim")
            _contains(observations[link["observation_id"]]["model_visible_description"], label.visible_excerpt,
                      "visible_excerpt_not_in_observation_description")
    for label in cite_labels:
        citation = citations.get(label.citation_id)
        if citation is None or label.target_field not in packet["report_fields"]:
            raise ValueError("unknown_citation_or_report_target")
        if label.relation != "not_assessable":
            if not citation["eligible_for_text_review"]:
                raise ValueError("citation_without_saved_exact_delivery_cannot_receive_support_judgment")
            excerpt = next((item for item in citation["delivered_excerpts"]
                            if item["receipt_body_sha256"] == label.receipt_body_sha256), None)
            if excerpt is None:
                raise ValueError("citation_judgment_requires_matching_delivered_excerpt_identity")
            _contains(packet["report_fields"][label.target_field], label.target_excerpt, "citation_target_excerpt_not_in_report")
            _contains(excerpt["text"], label.source_excerpt, "citation_source_excerpt_not_in_delivered_text")
    for label in reason_labels:
        if label.claim_id not in claims:
            raise ValueError("unknown_reasoning_claim_id")
        if label.verdict in ("adequate", "partial") or label.report_excerpt:
            if label.report_field not in packet["report_fields"]:
                raise ValueError("unknown_reasoning_report_field")
            index = claims[label.claim_id]["report_index"]
            if label.report_field.startswith("claims.") and not label.report_field.startswith(f"claims.{index}."):
                raise ValueError("reasoning_excerpt_belongs_to_another_claim")
            _contains(packet["report_fields"][label.report_field], label.report_excerpt, "reasoning_excerpt_not_in_report")

    role_statuses = []
    for label in link_labels:
        expected = "supports" if links[label.link_id]["declared_role"] == "support" else "contradicts"
        role_statuses.append("appropriate" if label.relation == expected else label.relation)
    metrics = {
        "observation_visible_correctness": _metric(len(observations), [item.visible_verdict for item in obs_labels], {"correct"}, "model_observations"),
        "observation_region_appropriateness": _metric(len(observations), [item.region_verdict for item in obs_labels], {"appropriate"}, "model_observations"),
        "declared_observation_link_appropriateness": _metric(len(links), role_statuses, {"appropriate"}, "unique_declared_claim_observation_roles"),
        "reasoning": {criterion: _metric(len(claims), [item.verdict for item in reason_labels if item.criterion == criterion],
                                         {"adequate"}, "saved_claims") for criterion in REASONING_CRITERIA},
        "citation_relations_by_target_kind": {
            kind: _metric(len(items), [item.relation for item in items], {"supports"}, "supplied_citation_target_pairs")
            for kind in ("source_statement", "object_inference", "method")
            for items in [[item for item in cite_labels if item.target_kind == kind]]},
        "citation_mapping_coverage": {"mapped_citations": len({item.citation_id for item in cite_labels}),
                                      "declared_citation_denominator": len(citations),
                                      "unmapped_citations": len(citations) - len({item.citation_id for item in cite_labels})},
    }
    received = len(obs_labels) + len(link_labels) + len(cite_labels) + len(reason_labels)
    return {"schema_version": SCHEMA_VERSION, "packet": packet, "metrics": metrics,
            "region_overlaps": overlaps, "review_labels": review.model_dump() if review else None,
            "semantic_status": "supplied_labels_only" if received else "awaiting_review",
            "reviewer_identity_authenticated": False, "expert_validation_established": False,
            "ceramic_accuracy": "not_measured", "authenticity_probability": None,
            "denominator_policy": "未评项目保留在total_items；图像无法判断等not_assessable保留计数、排除条件分母。partial计入分母且不计为完全支持。引用按人工明确的目标类型分别计数，未映射引用另报覆盖。",
            "limitations": ["只核对提交的保存记录和阅评标签，未认证宿主记录或阅评者身份。",
                            "不会从来源、款识、器物名称或专家标签生成图像事实。",
                            "文字支持分数以已送达段落和所选目标为条件；不等于本器物归属已证实。",
                            "图像访问由阅评者声明；工具未读取图像或核验实际阅评行为。"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线审核保存意见；语义评分只来自单独阅评标签。")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--review-template", type=Path)
    args = parser.parse_args(argv)
    run = json.loads(args.run.read_text(encoding="utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels else None
    result = audit_claim_support(run, labels)
    targets = [args.output] + ([args.review_template] if args.review_template else [])
    if len({path.resolve() for path in targets}) != len(targets) or any(path.exists() for path in targets):
        parser.error("audit_output_must_be_new_and_distinct")
    for path, value in [(args.output, result)] + ([(args.review_template, review_template(result["packet"]))] if args.review_template else []):
        with path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"semantic_status": result["semantic_status"], "expert_validation_established": False,
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
