"""Reuse Cizheng's frozen retrieval contract without broadening case access.

This module verifies reference identity, never the truth of a ceramic claim.
It performs no HTTP request, image read, inference, shell command, or crawling.
"""
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class EvidenceError(ValueError):
    """A bounded error that does not include submitted text or private paths."""


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern=r"^ksrc_[a-f0-9]{24}$")
    document_revision: int = Field(ge=1)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunk_id: str = Field(min_length=1, max_length=160)
    chunk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=1000)


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^case_[a-f0-9]{32}$")
    expected_case_revision: int = Field(ge=1)
    assessment_run_id: str | None = Field(default=None, pattern=r"^run_[a-f0-9]{32}$")
    queries: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=8)
    limit: int = Field(default=2, ge=1, le=8)
    citations: list[Citation] = Field(default_factory=list, max_length=12)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^nat_[a-f0-9]{32}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_id: str = Field(pattern=r"^case_[a-f0-9]{32}$")
    expected_case_revision: int = Field(ge=1)
    citations: list[Citation] = Field(default_factory=list, max_length=12)


def parse_request(value, schema=EvidenceRequest):
    try:
        if isinstance(value, str):
            if len(value.encode()) > 24_000:
                raise EvidenceError("request_too_large")
            return schema.model_validate_json(value)
        return schema.model_validate(value)
    except (ValidationError, TypeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid_request_schema") from exc


class Budget:
    def __init__(self, max_tool_calls=20, max_seconds=300, *, started_at=None, events=None):
        if type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 20:
            raise EvidenceError("invalid_tool_budget")
        if not 0 < max_seconds <= 300:
            raise EvidenceError("invalid_time_budget")
        self.max_tool_calls, self.max_seconds = max_tool_calls, max_seconds
        self.started_at = time.time() if started_at is None else started_at
        self.events = list(events or [])

    def step(self, tool, payload):
        if len(self.events) >= self.max_tool_calls:
            raise EvidenceError("tool_budget_exhausted")
        if time.time() - self.started_at > self.max_seconds:
            raise EvidenceError("time_budget_exhausted")
        event = {"sequence": len(self.events) + 1, "tool": tool,
                 "input_sha256": fingerprint(payload),
                 "previous_event_sha256": self.events[-1]["event_sha256"] if self.events else None}
        event["event_sha256"] = fingerprint(event)
        self.events.append(event)

    def usage(self):
        return {"model_calls": 0, "tool_calls": len(self.events),
                "max_model_calls": 0, "max_tool_calls": self.max_tool_calls,
                "max_seconds": self.max_seconds,
                "elapsed_seconds": round(time.time() - self.started_at, 6)}


def _paths(data_dir):
    root = Path(data_dir).resolve()
    if not (root / "cizheng.sqlite3").is_file() or not (root / "knowledge.sqlite3").is_file():
        raise EvidenceError("existing_case_and_knowledge_store_required")
    receipts = root / "nat-audit"
    receipts.mkdir(mode=0o700, exist_ok=True)
    if receipts.is_symlink():
        raise EvidenceError("audit_symlink_refused")
    return root, receipts


def _write_once(path, value):
    # Exclusive creation keeps each receipt immutable in the application.
    with path.open("x", encoding="utf-8") as target:
        target.write(encoded(value) + "\n")
    path.chmod(0o600)


def citation_for(chunk):
    return {name: chunk[name] for name in Citation.model_fields}


def _saved_run_sources(store, request, budget):
    from cizheng.knowledge import read_snapshot, validate_snapshot
    budget.step("read_saved_assessment_run", {"run_id": request.assessment_run_id})
    run = store.read("run", request.assessment_run_id)
    if run["case_id"] != request.case_id:
        raise EvidenceError("assessment_run_case_boundary_mismatch")
    if run["state"] not in ("ready", "waiting_evidence") or not isinstance(run.get("assessment"), dict):
        raise EvidenceError("completed_saved_assessment_required")
    if request.queries:
        raise EvidenceError("saved_run_audit_does_not_search_current_library")
    snapshot = validate_snapshot(run.get("knowledge_snapshot"))
    if snapshot["snapshot_sha256"] != run.get("versions", {}).get("knowledge_snapshot_sha256"):
        raise EvidenceError("assessment_snapshot_hash_mismatch")
    declared = list((run.get("assessment") or {}).get("knowledge_citations", []))
    for finding in (run.get("assessment") or {}).get("documentary_findings", []):
        declared.extend(c for c in finding.get("evidence_refs", []) if c.get("kind") == "knowledge")
    chosen = [citation.model_dump() for citation in request.citations] or [citation_for(c) for c in declared]
    unique = {(c["document_id"], c["chunk_id"]): c for c in chosen}
    if len(unique) > 12:
        raise EvidenceError("too_many_saved_report_citations")
    reads = {(c["document_id"], c["chunk_id"]): c for c in run.get("read_knowledge", [])}
    selected = []
    for key in unique:
        original = reads.get(key)
        if original is None:
            continue
        budget.step("reread_saved_snapshot_chunk", {"document_id": key[0], "chunk_id": key[1]})
        actual = read_snapshot(snapshot, key[0], key[1], limit=1, max_chars=800)["chunks"][0]
        if citation_for(original) != citation_for(actual):
            raise EvidenceError("original_read_receipt_snapshot_mismatch")
        actual["original_agent_read"] = True
        selected.append(actual)
    return snapshot, selected, chosen, run["case_revision"]


def retrieve_evidence(data_dir, value, max_tool_calls=20, max_seconds=300):
    from cizheng.knowledge import KnowledgeStore, read_snapshot, search_snapshot
    from cizheng.store import Problem, Store

    request = parse_request(value)
    root, receipts = _paths(data_dir)
    budget = Budget(max_tool_calls, max_seconds)
    run_id = "nat_" + uuid.uuid4().hex
    try:
        budget.step("read_case", {"case_id": request.case_id})
        case = Store(root).read("case", request.case_id)
        if case["revision"] != request.expected_case_revision:
            raise EvidenceError("case_revision_changed")
        searches, read = [], {}
        if request.assessment_run_id:
            snapshot, chunks, default_citations, source_case_revision = _saved_run_sources(Store(root), request, budget)
            read = {(chunk["document_id"], chunk["chunk_id"]): chunk for chunk in chunks}
            ids = list({chunk["document_id"] for chunk in chunks})
            source_mode = "saved_assessment_run_snapshot"
        else:
            ids = list(case.get("knowledge_document_ids", []))
            bindings = list(case.get("knowledge_links", []))
            if set(ids) != {entry["document_id"] for entry in bindings}:
                raise EvidenceError("explicit_case_version_bindings_required")
            budget.step("freeze_case_sources", {"bindings": bindings})
            # Passing [] is intentional: an unbound case gets no library access.
            snapshot = KnowledgeStore(root).snapshot(document_ids=ids, bindings=bindings)
            for query in request.queries:
                budget.step("search_knowledge", {"query": query, "limit": request.limit})
                matches = search_snapshot(snapshot, query, limit=request.limit)
                searches.append(matches)
                for match in matches["results"]:
                    key = (match["document_id"], match["chunk_id"])
                    if key in read or len(read) >= 8:
                        continue
                    budget.step("read_knowledge", {"document_id": key[0], "chunk_id": key[1]})
                    detail = read_snapshot(snapshot, key[0], key[1], limit=1, max_chars=800)
                    read[key] = detail["chunks"][0]
            default_citations = [citation_for(chunk) for chunk in read.values()]
            source_case_revision, source_mode = case["revision"], "current_case_pinned_versions"
        if Store(root).read("case", request.case_id)["revision"] != request.expected_case_revision:
            raise EvidenceError("case_revision_changed")
        manifest = {"schema_version": 1, "run_id": run_id,
                    "integration": "NVIDIA NeMo Agent Toolkit / cizheng-nvidia-nat",
                    "mode": "deterministic_reference_integrity", "inference_performed": False,
                    "case_id": request.case_id, "case_revision": case["revision"],
                    "assessment_run_id": request.assessment_run_id, "source_case_revision": source_case_revision,
                    "source_mode": source_mode, "default_citations": default_citations,
                    "request_sha256": fingerprint(request.model_dump()),
                    "snapshot_sha256": snapshot["snapshot_sha256"],
                    "bound_source_ids": ids, "read_evidence": list(read.values()),
                    "searches": searches, "events": budget.events,
                    "started_at": budget.started_at, "usage": budget.usage(),
                    "limitations": ["Current-case searches use explicit version bindings; saved-report audits use only the original run snapshot and read receipts.",
                                    "This audit checks knowledge citations, not visual reference_ids or document authenticity.",
                                    "Reference integrity does not establish authenticity, ownership, date, or claim support.",
                                    "Ranking scores are text matches, not credibility or confidence."]}
        manifest_sha256 = fingerprint(manifest)
        _write_once(receipts / (run_id + ".retrieval.json"),
                    {"manifest": manifest, "manifest_sha256": manifest_sha256})
        return {"run_id": run_id, "manifest_sha256": manifest_sha256,
                "case_id": request.case_id, "case_revision": case["revision"],
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "source_mode": source_mode, "assessment_run_id": request.assessment_run_id,
                "source_case_revision": source_case_revision, "default_citations": default_citations,
                "read_evidence": list(read.values()), "usage": budget.usage(),
                "inference_performed": False, "review_required": True}
    except Exception as exc:
        code = (str(exc) if isinstance(exc, EvidenceError) else
                "case_or_reference_store_rejected" if isinstance(exc, Problem) else "evidence_operation_failed")
        _write_once(receipts / (run_id + ".rejected.json"),
                    {"run_id": run_id, "case_id": request.case_id,
                     "request_sha256": fingerprint(request.model_dump()), "reason": code,
                     "events": budget.events, "usage": budget.usage()})
        raise EvidenceError(code) from exc


def verify_evidence(data_dir, value):
    from cizheng.store import Store

    request = parse_request(value, VerifyRequest)
    root, receipts = _paths(data_dir)
    path = receipts / (request.run_id + ".retrieval.json")
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("retrieval_receipt_missing")
    record = json.loads(path.read_text())
    manifest = record["manifest"]
    if fingerprint(manifest) != record["manifest_sha256"] or record["manifest_sha256"] != request.manifest_sha256:
        raise EvidenceError("retrieval_receipt_hash_mismatch")
    if manifest["case_id"] != request.case_id or manifest["case_revision"] != request.expected_case_revision:
        raise EvidenceError("receipt_case_boundary_mismatch")
    if Store(root).read("case", request.case_id)["revision"] != request.expected_case_revision:
        raise EvidenceError("case_revision_changed")
    verify_hash = fingerprint(request.model_dump())
    result_path = receipts / (request.run_id + ".verification.json")
    if result_path.is_symlink():
        raise EvidenceError("audit_symlink_refused")
    if result_path.is_file():
        prior = json.loads(result_path.read_text())
        if prior.get("verify_request_sha256") != verify_hash:
            raise EvidenceError("receipt_already_verified_with_different_request")
        if fingerprint({k: v for k, v in prior.items() if k != "result_sha256"}) != prior["result_sha256"]:
            raise EvidenceError("verification_receipt_hash_mismatch")
        return prior
    budget = Budget(manifest["usage"]["max_tool_calls"], manifest["usage"]["max_seconds"],
                    started_at=manifest["started_at"], events=manifest["events"])
    budget.step("verify_read_citations", {"citations": [item.model_dump() for item in request.citations]})
    read = {(item["document_id"], item["chunk_id"]): item for item in manifest["read_evidence"]}
    citations = request.citations or [Citation(**item) for item in manifest["default_citations"]]
    checks = []
    for citation in citations:
        item = citation.model_dump()
        actual = read.get((citation.document_id, citation.chunk_id))
        if actual is None:
            status, changed = "not_read_in_this_run", []
        else:
            changed = [field for field in Citation.model_fields if item[field] != actual[field]]
            status = "reference_mismatch" if changed else (
                "metadata_only" if actual["content_kind"] != "authorized_text" else "valid_reference")
        checks.append({"citation": item, "status": status, "mismatched_fields": changed,
                       "claim_support_assessed": False})
    status = ("no_read_evidence" if not checks else "reference_mismatch" if any(
              check["status"] in ("reference_mismatch", "not_read_in_this_run") for check in checks)
              else "references_verified")
    result = {"schema_version": 1, "run_id": request.run_id, "case_id": request.case_id,
              "case_revision": request.expected_case_revision, "status": status,
              "assessment_run_id": manifest["assessment_run_id"],
              "source_case_revision": manifest["source_case_revision"], "source_mode": manifest["source_mode"],
              "mode": "deterministic_reference_integrity", "inference_performed": False,
              "nvidia_verified_skill": False, "expert_reviewed": False, "review_required": True,
              "snapshot_sha256": manifest["snapshot_sha256"], "manifest_sha256": request.manifest_sha256,
              "verify_request_sha256": verify_hash,
              "checks": checks, "read_evidence": manifest["read_evidence"],
              "usage": budget.usage(), "events": budget.events, "limitations": manifest["limitations"]}
    result["result_sha256"] = fingerprint(result)
    _write_once(result_path, result)
    return result
