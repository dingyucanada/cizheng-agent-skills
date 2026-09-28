"""Optional NVIDIA adapter's substantive privacy, integrity and budget boundaries."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/nvidia_nat/src"))

from cizheng.knowledge import KnowledgeStore
from cizheng.store import Store
from cizheng_nat.evidence import (Budget, EvidenceError, citation_for, fingerprint,
                                  retrieve_evidence, verify_evidence)


def original_document(title="本案软件协议资料", text="蟠螭甲标记仅用于引用版本核查，不是陶瓷归属答案。"):
    return {"title": title, "source_type": "original_protocol_fixture", "rights": "authorized_text",
            "rights_note": "项目原创协议验收文字，无外部全文。", "locator": "协议验收第1节",
            "scope": "软件协议验收", "text": text,
            "limitations": ["软件测试材料，不是实物研究依据。"]}


@pytest.fixture
def case_data(tmp_path):
    store, knowledge = Store(tmp_path), KnowledgeStore(tmp_path)
    case = store.create_case({"request_id": "nat-test-case-1", "title": "NVIDIA引用合同验收", "question": "核验引用版本和定位",
                              "target_attribution": "软件合同验收", "source_declaration": "项目原创协议测试"})
    source = knowledge.add_document(original_document())["source"]
    other = knowledge.add_document(original_document("另一案私有资料", "蟠螭甲另案秘密，不应出现在本案。"))["source"]
    case = store.link_document(case["id"], {"request_id": "nat-test-binding-1", "document_id": source["document_id"],
                                           "expected_case_revision": case["revision"]})
    request = {"case_id": case["id"], "expected_case_revision": case["revision"],
               "queries": ["蟠螭甲"], "limit": 2}
    return tmp_path, store, knowledge, case, source, other, request


def verify_packet(receipt, citations=None):
    return {"run_id": receipt["run_id"], "manifest_sha256": receipt["manifest_sha256"],
            "case_id": receipt["case_id"], "expected_case_revision": receipt["case_revision"],
            "citations": citations or []}


def test_case_scope_and_zero_network_with_original_read_receipts(case_data, monkeypatch):
    root, store, knowledge, case, source, other, request = case_data
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("No network is permitted in evidence mode"))
    before = store.read("case", case["id"])
    receipt = retrieve_evidence(root, request)
    result = verify_evidence(root, verify_packet(receipt))
    assert result["status"] == "references_verified"
    assert result["usage"]["model_calls"] == 0 and result["usage"]["tool_calls"] == 5
    assert result["inference_performed"] is False and result["expert_reviewed"] is False
    assert result["nvidia_verified_skill"] is False
    assert result["checks"][0]["claim_support_assessed"] is False
    assert other["document_id"] not in json.dumps(result)
    assert "另案秘密" not in json.dumps(result, ensure_ascii=False)
    assert store.read("case", case["id"]) == before
    assert store.listing("run") == []
    manifest = json.loads((root / "nat-audit" / (receipt["run_id"] + ".retrieval.json")).read_text())
    assert manifest["manifest_sha256"] == fingerprint(manifest["manifest"])
    assert all(event["event_sha256"] == fingerprint({k: v for k, v in event.items() if k != "event_sha256"})
               for event in result["events"])


def test_empty_binding_never_searches_the_entire_library(case_data):
    root, store, knowledge, case, source, other, request = case_data
    unbound = store.create_case({"request_id": "nat-empty-case-1", "title": "未关联资料案", "question": "查资料", "target_attribution": "",
                                "source_declaration": "无绑定"})
    receipt = retrieve_evidence(root, request | {"case_id": unbound["id"], "expected_case_revision": 1})
    assert receipt["read_evidence"] == []
    assert verify_evidence(root, verify_packet(receipt))["status"] == "no_read_evidence"


def test_historical_binding_remains_fixed_after_library_revision(case_data):
    root, store, knowledge, case, source, other, request = case_data
    revised = original_document(text="新版黼黻乙，仅应通过重新关联后使用。")
    knowledge.add_document(revised | {"document_id": source["document_id"], "expected_revision": 1})
    receipt = retrieve_evidence(root, request)
    assert receipt["read_evidence"][0]["document_revision"] == 1
    assert receipt["read_evidence"][0]["document_sha256"] == source["document_sha256"]


@pytest.mark.parametrize("field,value", [("document_sha256", "0" * 64), ("chunk_sha256", "0" * 64),
                                          ("locator", "伪造定位"), ("document_revision", 99)])
def test_tampered_citation_is_rejected(case_data, field, value):
    root, store, knowledge, case, source, other, request = case_data
    receipt = retrieve_evidence(root, request)
    citation = citation_for(receipt["read_evidence"][0]) | {field: value}
    result = verify_evidence(root, verify_packet(receipt, [citation]))
    assert result["status"] == "reference_mismatch"
    assert result["checks"][0]["mismatched_fields"] == [field]


def test_unread_other_case_citation_is_never_accepted(case_data):
    root, store, knowledge, case, source, other, request = case_data
    receipt = retrieve_evidence(root, request)
    chunk = knowledge.source(other["document_id"])["chunks"][0] | {"document_sha256": other["document_sha256"]}
    result = verify_evidence(root, verify_packet(receipt, [citation_for(chunk)]))
    assert result["checks"][0]["status"] == "not_read_in_this_run"


def test_receipt_tampering_and_cross_case_replay_are_rejected(case_data):
    root, store, knowledge, case, source, other, request = case_data
    receipt = retrieve_evidence(root, request)
    with pytest.raises(EvidenceError, match="receipt_case_boundary_mismatch"):
        verify_evidence(root, verify_packet(receipt) | {"case_id": "case_" + "0" * 32})
    path = root / "nat-audit" / (receipt["run_id"] + ".retrieval.json")
    record = json.loads(path.read_text()); record["manifest"]["read_evidence"][0]["locator"] = "tampered"
    path.write_text(json.dumps(record))
    with pytest.raises(EvidenceError, match="retrieval_receipt_hash_mismatch"):
        verify_evidence(root, verify_packet(receipt))


def test_stale_case_missing_bindings_and_budget_rejection_are_audited(case_data):
    root, store, knowledge, case, source, other, request = case_data
    with pytest.raises(EvidenceError, match="case_revision_changed"):
        retrieve_evidence(root, request | {"expected_case_revision": 1})
    with pytest.raises(EvidenceError, match="tool_budget_exhausted"):
        retrieve_evidence(root, request, max_tool_calls=3)
    assert len(list((root / "nat-audit").glob("*.rejected.json"))) == 2
    receipt = retrieve_evidence(root, request, max_tool_calls=4)
    with pytest.raises(EvidenceError, match="tool_budget_exhausted"):
        verify_evidence(root, verify_packet(receipt))
    with store.tx() as db:
        changed = store.get(db, "case", case["id"]); changed["knowledge_links"] = []; store.put(db, "case", changed)
    with pytest.raises(EvidenceError, match="explicit_case_version_bindings_required"):
        retrieve_evidence(root, request)


def test_time_budget_and_verification_replay(case_data):
    import time
    with pytest.raises(EvidenceError, match="time_budget_exhausted"):
        Budget(started_at=time.time() - 301).step("read_case", {})
    root, store, knowledge, case, source, other, request = case_data
    receipt = retrieve_evidence(root, request)
    packet = verify_packet(receipt)
    result = verify_evidence(root, packet)
    assert verify_evidence(root, packet) == result
    changed = citation_for(receipt["read_evidence"][0]) | {"locator": "修改"}
    with pytest.raises(EvidenceError, match="receipt_already_verified"):
        verify_evidence(root, verify_packet(receipt, [changed]))


def test_input_is_typed_bounded_and_cannot_accept_shell_commands(case_data):
    root, store, knowledge, case, source, other, request = case_data
    for bad in (request | {"command": "anything"}, request | {"queries": ["x" * 201]},
                request | {"case_id": "../../private"}, request | {"limit": 9}):
        with pytest.raises(EvidenceError, match="invalid_request_schema"):
            retrieve_evidence(root, bad)


def saved_run_fixture(store, knowledge, case, source):
    """Persist an explicit software fixture of the application's real record contract."""
    from cizheng.knowledge import read_snapshot, search_snapshot
    snapshot = knowledge.snapshot([source["document_id"]], case["knowledge_links"])
    match = search_snapshot(snapshot, "蟠螭甲", limit=1)["results"][0]
    chunk = read_snapshot(snapshot, match["document_id"], match["chunk_id"], limit=1)["chunks"][0]
    run = {"id": "run_" + "1" * 32, "case_id": case["id"], "case_revision": case["revision"],
           "state": "ready", "snapshot": {}, "knowledge_snapshot": snapshot,
           "versions": {"knowledge_snapshot_sha256": snapshot["snapshot_sha256"]},
           "read_knowledge": [chunk], "assessment": {"knowledge_citations": [citation_for(chunk)]}}
    with store.tx() as db:
        store.put(db, "run", run)
    return run


@pytest.mark.parametrize("completed_state", ["ready", "waiting_evidence"])
def test_saved_report_audit_uses_original_snapshot_after_case_rebinding(case_data, completed_state):
    root, store, knowledge, case, source, other, request = case_data
    run = saved_run_fixture(store, knowledge, case, source)
    with store.tx() as db:
        run["state"] = completed_state
        store.put(db, "run", run)
    new = knowledge.add_document(original_document(text="新版黼黻乙，旧报告不可自动改用新版。") |
                                 {"document_id": source["document_id"], "expected_revision": 1})["source"]
    case = store.link_document(case["id"], {"request_id": "nat-rebind-new-edition", "document_id": new["document_id"],
                                         "expected_case_revision": case["revision"], "document_revision": 2})
    receipt = retrieve_evidence(root, {"case_id": case["id"], "expected_case_revision": case["revision"],
                                       "assessment_run_id": run["id"]})
    result = verify_evidence(root, verify_packet(receipt))
    assert result["status"] == "references_verified"
    assert result["source_mode"] == "saved_assessment_run_snapshot"
    assert result["source_case_revision"] == run["case_revision"] < result["case_revision"]
    assert result["assessment_run_id"] == run["id"]
    assert result["read_evidence"][0]["document_revision"] == 1
    assert "黼黻乙" not in json.dumps(result, ensure_ascii=False)
    assert result["read_evidence"][0]["original_agent_read"] is True


def test_saved_run_mode_rejects_other_case_current_search_and_unread_citation(case_data):
    root, store, knowledge, case, source, other, request = case_data
    run = saved_run_fixture(store, knowledge, case, source)
    with store.tx() as db:
        store.put(db, "run", run | {"state": "running"})
    with pytest.raises(EvidenceError, match="completed_saved_assessment_required"):
        retrieve_evidence(root, request | {"assessment_run_id": run["id"], "queries": []})
    with store.tx() as db:
        store.put(db, "run", run)
    with pytest.raises(EvidenceError, match="saved_run_audit_does_not_search_current_library"):
        retrieve_evidence(root, request | {"assessment_run_id": run["id"]})
    foreign = store.create_case({"request_id": "nat-foreign-report-case", "title": "其他案件",
                                "question": "引用核查", "target_attribution": "", "source_declaration": "协议"})
    with pytest.raises(EvidenceError, match="assessment_run_case_boundary_mismatch"):
        retrieve_evidence(root, {"case_id": foreign["id"], "expected_case_revision": foreign["revision"],
                                 "assessment_run_id": run["id"]})
    chunk = knowledge.source(other["document_id"])["chunks"][0] | {"document_sha256": other["document_sha256"]}
    citation = citation_for(chunk)
    receipt = retrieve_evidence(root, request | {"assessment_run_id": run["id"], "queries": [], "citations": [citation]})
    result = verify_evidence(root, verify_packet(receipt, [citation]))
    assert result["status"] == "reference_mismatch" and result["read_evidence"] == []


def test_documentary_saved_report_reads_evidence_refs_not_attachment_refs(case_data):
    root, store, knowledge, case, source, _, request = case_data
    run = saved_run_fixture(store, knowledge, case, source)
    citation = run["assessment"]["knowledge_citations"][0]
    # Actual DocumentaryFinding uses evidence_refs, with a typed kind marker.
    # A TXT attachment has a separate receipt contract and is outside this audit.
    run["research_task"] = "documentary_audit"
    run["assessment"] = {"documentary_findings": [{"evidence_refs": [
        citation | {"kind": "knowledge"}, {"kind": "attachment", "document_id": "attachment-test"}]}]}
    with store.tx() as db:
        store.put(db, "run", run)
    receipt = retrieve_evidence(root, request | {"assessment_run_id": run["id"], "queries": []})
    result = verify_evidence(root, verify_packet(receipt))
    assert result["status"] == "references_verified"
    assert len(result["checks"]) == 1 and len(result["read_evidence"]) == 1
    assert result["read_evidence"][0]["original_agent_read"] is True
    assert result["checks"][0]["citation"] == citation
