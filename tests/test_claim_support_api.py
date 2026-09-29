"""Read-only case-bound audit API tests; synthetic records are not expertise."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from cizheng.agent import Engine, LocalModel, knowledge_body_identity, knowledge_receipt_identity
from cizheng.api import create_app
from cizheng.knowledge import read_snapshot
from cizheng.review_client import StepFunClient
from cizheng.store import uid
from test_closed_loop import add_photo, create_case
from test_source_attribution_gate import opinion


def source_body(title, text):
    return {"title": title, "institution": "SYNTHETIC API TEST", "author": "软件协议测试",
            "source_url": "https://example.invalid/software-only/" + title, "locator": "合成段落",
            "year": "2026", "rights": "authorized_text", "rights_note": "本测试原创文字",
            "scope": "仅软件协议", "source_type": "test_fixture", "text": text,
            "limitations": ["不是陶瓷判断或专家样本"]}


@pytest.fixture
def audit_client(tmp_path, monkeypatch):
    app = create_app(tmp_path / "data")
    store, knowledge = app.state.store, app.state.knowledge
    case = add_photo(store, create_case(store))
    other_case = add_photo(store, create_case(store), "red")
    chosen = knowledge.add_document(source_body("case-bound", "本轮许可片段只讨论核查步骤，不提供年代结论。"))["source"]
    unbound = knowledge.add_document(source_body("PRIVATE_UNRELATED_TITLE", "PRIVATE_UNRELATED_BODY"))["source"]
    case = store.link_document(case["id"], {"request_id": uid("req"), "expected_case_revision": case["revision"],
        "document_id": chosen["document_id"], "document_revision": chosen["revision"], "document_sha256": chosen["document_sha256"]})
    rid = store.start_run(case["id"], {"request_id": uid("req"), "expected_case_revision": case["revision"], "mode": "plain"},
                          app.state.engine.versions("plain"))["run_id"]
    run = store.read("run", rid)
    chunk = read_snapshot(run["knowledge_snapshot"], chosen["document_id"])["chunks"][0]
    chunk["run_id"] = rid
    oid = uid("obs")
    observation = {"id": oid, "run_id": rid, "media_id": case["media"][0]["id"],
                   "region": [0.1, 0.1, 0.8, 0.8], "coordinate_space": "exif-corrected-original-normalized",
                   "visible": "合成色块，仅测试API", "interpretation": "不能据此鉴定", "limitation": "合成图片"}
    assessment = opinion()
    assessment["claims"][0]["support"] = [oid]
    assessment["claims"][2]["conflict"] = [oid]
    assessment["knowledge_citations"] = [{key: chunk[key] for key in (
        "document_id", "document_revision", "document_sha256", "chunk_id", "chunk_sha256", "locator")} |
        {"use": "method", "relevance": "只作核查方法记录"}]
    store.update_run(rid, lambda r: r.update(state="waiting_evidence", observations=[observation], assessment=assessment,
        main_seen_media_ids=[case["media"][0]["id"]], read_knowledge=[chunk],
        main_seen_knowledge_receipt_sha256=[knowledge_receipt_identity(chunk)],
        main_seen_knowledge_body_sha256=[knowledge_body_identity(chunk)]))

    def forbidden(*args, **kwargs):
        pytest.fail("Audit API must not read pixels, consult live sources, call a model, or make remote requests")
    async def forbidden_async(*args, **kwargs):
        forbidden()
    import socket
    import urllib.request
    from PIL import Image
    monkeypatch.setattr(Image, "open", forbidden)
    monkeypatch.setattr(store, "blob", forbidden)
    monkeypatch.setattr(knowledge, "source", forbidden)
    monkeypatch.setattr(Engine, "call", forbidden_async)
    monkeypatch.setattr(LocalModel, "complete", forbidden_async)
    monkeypatch.setattr(StepFunClient, "review", forbidden_async)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with TestClient(app) as client:
        yield app, client, case, rid, other_case, unbound


def test_api_download_is_one_frozen_run_without_pixels_library_or_semantic_scores(audit_client):
    app, client, case, rid, other_case, unbound = audit_client
    before = deepcopy(app.state.store.read("run", rid))
    response = client.get("/api/runs/" + rid + "/claim-support")
    assert response.status_code == 200, response.text
    result = response.json()
    packet = result["packet"]
    assert packet["run_id"] == rid and packet["case_id"] == case["id"]
    assert len(packet["claims"]) == 3 and len(packet["observation_links"]) == 2
    assert packet["citations"][0]["eligible_for_text_review"]
    assert packet["citations"][0]["authorized_saved_source"]
    assert packet["citations"][0]["delivered_excerpts"][0]["text"].startswith("本轮许可片段")
    assert result["semantic_status"] == "awaiting_review" and result["review_labels"] is None
    assert result["review_template"]["packet_sha256"] == packet["packet_sha256"]
    assert result["review_template"]["observations"] == result["review_template"]["citations"] == []
    assert not result["expert_validation_established"] and result["ceramic_accuracy"] == "not_measured"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "PRIVATE_UNRELATED" not in serialized and unbound["document_id"] not in serialized
    assert other_case["id"] not in serialized and other_case["media"][0]["id"] not in serialized
    assert "knowledge_snapshot" not in serialized and "image_base64" not in serialized and "data:image/" not in serialized
    assert all(m["assessed_denominator"] == 0 and m["fully_positive_fraction"] is None
               for m in result["metrics"]["reasoning"].values())
    download = client.get("/api/runs/" + rid + "/claim-support?download=true")
    assert download.status_code == 200 and download.json() == result
    assert download.headers["content-disposition"] == 'attachment; filename="claim-support-audit.json"'
    assert download.headers["cache-control"] == "no-store"
    assert app.state.store.read("run", rid) == before


@pytest.mark.parametrize("change", ["rights_unknown", "unbound", "forged_read_body", "missing_snapshot"])
def test_audit_never_exports_unlicensed_unbound_or_forged_excerpt(audit_client, change):
    app, client, _, rid, _, unbound = audit_client
    def invalidate(run):
        if change == "rights_unknown":
            document = run["assessment"]["knowledge_citations"][0]["document_id"]
            entry = next(e for e in run["knowledge_snapshot"]["sources"] if e["source"]["document_id"] == document)
            entry["source"]["rights"] = "unknown"
        elif change == "unbound":
            run["snapshot"]["knowledge_links"] = []
        elif change == "forged_read_body":
            read = run["read_knowledge"][0]
            read.update(text="UNAUTHORIZED_FORGED_BODY", snippet_start=0, snippet_end=len("UNAUTHORIZED_FORGED_BODY"))
            run["main_seen_knowledge_body_sha256"] = [knowledge_body_identity(read)]
        else:
            run.pop("knowledge_snapshot")
    app.state.store.update_run(rid, invalidate)
    result = client.get("/api/runs/" + rid + "/claim-support").json()
    citation = result["packet"]["citations"][0]
    assert citation["delivered_excerpts"] == [] and not citation["eligible_for_text_review"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "UNAUTHORIZED_FORGED_BODY" not in serialized and "本轮许可片段" not in serialized
    assert unbound["document_id"] not in serialized


def test_api_rejects_missing_documentary_and_invalid_saved_opinions_without_echo(audit_client):
    app, client, _, rid, _, _ = audit_client
    assert client.get("/api/runs/run_missing/claim-support").status_code == 404
    app.state.store.update_run(rid, lambda r: r.update(research_task="documentary_audit"))
    text = client.get("/api/runs/" + rid + "/claim-support")
    assert text.status_code == 422 and "文字凭据核查" in text.json()["detail"]
    app.state.store.update_run(rid, lambda r: r.update(research_task="visual_research", assessment={"private": "DO_NOT_ECHO_BAD_REPORT"}))
    bad = client.get("/api/runs/" + rid + "/claim-support")
    assert bad.status_code == 409 and "DO_NOT_ECHO_BAD_REPORT" not in bad.text
    assert client.get("/api/runs/" + rid + "/claim-support?download=invalid").status_code == 422


def test_api_cannot_accept_grading_and_does_not_change_history(audit_client):
    app, client, _, rid, _, _ = audit_client
    before = app.state.store.read("run", rid)
    path = "/api/runs/" + rid + "/claim-support"
    result = client.request("GET", path, json={"expert_validation_established": True, "labels": {"supports": True}})
    assert result.status_code == 200 and result.json()["review_labels"] is None
    assert not result.json()["expert_validation_established"]
    token = client.get("/api/status").json()["session_token"]
    assert client.post(path, json={"labels": "model grading"}, headers={"X-Cizheng-Token": token}).status_code == 405
    assert app.state.store.read("run", rid) == before


def test_frozen_audit_does_not_follow_current_case_relabeling_or_omit_failed_runs(audit_client):
    app, client, case, rid, _, _ = audit_client
    path = "/api/runs/" + rid + "/claim-support"
    original = client.get(path).json()
    app.state.store.label_capture(case["id"], case["media"][0]["id"], {"request_id": uid("req"),
        "expected_case_revision": case["revision"], "capture_role": "base", "view": "后来修改的视角声明"})
    assert client.get(path).json() == original
    app.state.store.update_run(rid, lambda r: r.update(state="failed", assessment=None))
    failed = client.get(path)
    assert failed.status_code == 200 and failed.json()["packet"]["run_state"] == "failed"
    assert not failed.json()["packet"]["assessment_present"]
    assert failed.json()["metrics"]["reasoning"]["inference_bridge"]["total_items"] == 0


def test_frontend_relations_are_text_safe_and_download_tracks_selected_saved_run():
    """Execute the real component functions with a bounded DOM stand-in."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional; API privacy contracts are tested independently")
    app_js = Path(__file__).resolve().parents[1] / "static/app.js"
    script = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const {Blob} = require('node:buffer');
const source = fs.readFileSync(process.argv[2], 'utf8'), downloads = [], requests = [];
const objectUrls = new Map(), revokedUrls = [], timers = [], locatedObservations = [], sourceReads = [];
let servedAudit, afterRead = () => {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  set innerHTML(_) { throw Error('HTML interpretation is forbidden for report text'); }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  prepend(...children) { for (const child of children) child.parent = this; this.children.unshift(...children); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  querySelector(tag) { for (const child of this.children) { if (child.tag === tag) return child; const found = child.querySelector(tag); if (found) return found; } return null; }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  click() {
    if (this.tag === 'a') {
      assert.ok(objectUrls.has(this.href), 'downloads must use an unreleased local Blob URL');
      downloads.push({href: this.href, filename: this.download, blob: objectUrls.get(this.href)});
    }
    return this.onclick?.();
  }
}
const observationId = 'obs_75629327069045bb81a3e0026fbf952f';
const run = {id: 'run-<script>?', case_id: 'synthetic-case', observations: [
  {id: observationId, visible: '<img src=x onerror=alert(1)> synthetic visible text'}]};
const opinionRoot = new Element('section');
const firstAudit = {schema_version: 'claim-support-audit-v1', packet: {run_id: run.id,
  packet_sha256: 'a'.repeat(64), claims: [{reasoning_summary: '首次保存的理由'},{},{}],
  observation_links: [{}], citations: [{}]}, semantic_status: 'awaiting_review',
  review_template: {packet_sha256: 'a'.repeat(64), observations: [], citations: []},
  metrics: {reasoning: {inference_bridge: {fully_positive_fraction: null}}},
  expert_validation_established: false};
servedAudit = firstAudit;
const context = {document: {createElement: tag => new Element(tag)}, selectedRun: run, Blob,
  $: selector => { assert.equal(selector, '#opinionContent'); return opinionRoot; },
  dimensions: {period: '制作时期', kiln: '窑口归属', style: '装饰风格'},
  statuses: {supported: '当前资料支持', insufficient: '依据不足'},
  showEvidence: id => { locatedObservations.push(id); },
  isDocumentary: record => record?.research_task === 'documentary_audit',
  tab: () => {}, showDocument: async (...args) => { sourceReads.push(args); },
  URL: {
    createObjectURL: blob => { const url = 'blob:synthetic-' + objectUrls.size; objectUrls.set(url, blob); return url; },
    revokeObjectURL: url => { revokedUrls.push(url); objectUrls.delete(url); }
  },
  setTimeout: (callback, delay) => { timers.push({callback, delay}); },
  current: {id: run.case_id}, guarded: fn => fn(), notice: () => {},
  api: async url => { requests.push(url); const result = JSON.parse(JSON.stringify(servedAudit)); afterRead(); return result; }};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function el('), source.indexOf('function notice(')), context);
vm.runInContext(source.slice(source.indexOf('function evidenceButtons('), source.indexOf('function renderProfessional(')), context);
const citationStart = source.indexOf('function renderKnowledgeCitations(');
vm.runInContext(source.slice(citationStart, source.indexOf("document.querySelectorAll('[data-tab]')", citationStart)), context);
const text = element => [element.textContent, ...element.children.map(text)].join(' ');
const absent = context.claimObservationRelations({support: [], conflict: []}, run);
assert.match(text(absent), /尚未关联观察/);
const linked = context.claimObservationRelations({support: [observationId, observationId], conflict: ['missing']}, run);
assert.match(text(linked), /<img src=x onerror=alert\(1\)>/);
assert.match(text(linked), /冲突观察： 观察记录不可用/);
assert.doesNotMatch(text(linked), /obs_[a-f0-9]+|missing|以上为模型声明/);
assert.equal(text(linked).split('<img src=x onerror=alert(1)>').length - 1, 1);
assert.equal(linked.querySelector('img'), null);
assert.equal(linked.querySelector('button').title, '查看对应原图区域');
linked.querySelector('button').click();
assert.deepEqual(locatedObservations, [observationId]);
assert.equal(linked.children[1].querySelector('button').disabled, true);
const claim = {dimension: 'period', candidate: '清代康熙早期', status: 'insufficient',
  support: [observationId], conflict: [], reasoning_summary: '纹饰风格与馆藏相似，但依据不足'};
const savedClaim = JSON.stringify(claim);
const claimCard = context.claimOpinionCard(claim, run);
assert.equal(claimCard.querySelector('h3').textContent, '制作时期 · 待核查线索：清代康熙早期');
assert.equal(claimCard.querySelector('p').textContent, '判断理由：' + claim.reasoning_summary);
assert.equal(text(claimCard).split('<img src=x onerror=alert(1)>').length - 1, 1);
assert.doesNotMatch(text(claimCard), /obs_[a-f0-9]+|引用资料/);
assert.equal(JSON.stringify(claim), savedClaim, 'presentation must preserve model fields');
assert.doesNotMatch(context.claimOpinionCard({...claim, status: 'supported'}, run).querySelector('h3').textContent, /待核查线索/);
(async () => {
  const citation = {document_id: 'source-1', chunk_id: 'chunk-1', document_revision: 3,
    locator: '来源段落', relevance: '馆方原始记载'};
  context.selectedRun = {...run, assessment: {reference_ids: [], knowledge_citations: [citation]}};
  const savedAssessment = JSON.stringify(context.selectedRun.assessment);
  context.renderKnowledgeCitations();
  assert.match(text(opinionRoot), /本轮未查看参照图片，资料记载不能直接证明本件归属/);
  assert.match(text(opinionRoot), /本轮全局资料引用，未自动对应各条判断/);
  assert.equal(opinionRoot.children.filter(child => child.tag === 'article').length, 1);
  assert.equal(JSON.stringify(context.selectedRun.assessment), savedAssessment);
  await opinionRoot.querySelector('button').click();
  assert.deepEqual(sourceReads, [['source-1', 'chunk-1', 3]]);
  opinionRoot.replaceChildren();
  context.selectedRun.assessment.reference_ids = ['actually-read-reference'];
  context.renderKnowledgeCitations();
  assert.doesNotMatch(text(opinionRoot), /本轮未查看参照图片/);
  assert.match(text(opinionRoot), /本轮全局资料引用/);
  opinionRoot.replaceChildren();
  context.selectedRun = {...run, assessment: {reference_ids: [], knowledge_citations: []}};
  context.renderKnowledgeCitations();
  assert.match(text(opinionRoot), /本轮未查看参照图片/);
  opinionRoot.replaceChildren();
  context.selectedRun = {...run, research_task: 'documentary_audit', assessment: {knowledge_citations: []}};
  context.renderKnowledgeCitations();
  assert.equal(opinionRoot.children.length, 0);
  context.selectedRun = run;
  // The same run can change before the download. Its ID alone is not a content pin.
  afterRead = () => {
    servedAudit = JSON.parse(JSON.stringify(firstAudit));
    servedAudit.packet.packet_sha256 = 'b'.repeat(64);
    servedAudit.packet.claims[0].reasoning_summary = '同一运行后来更新的理由';
    servedAudit.review_template.packet_sha256 = 'b'.repeat(64);
    context.selectedRun = {...run, assessment: {revision: 'later'}};
  };
  const control = context.claimSupportAuditControls(run);
  await control.querySelector('button').click();
  afterRead = () => {};
  const encoded = encodeURIComponent(run.id);
  assert.deepEqual(requests, ['/api/runs/' + encoded + '/claim-support']);
  assert.equal(context.selectedRun.id, run.id);
  assert.equal(downloads[0].filename, 'claim-support-audit.json');
  assert.equal(downloads[0].blob.type, 'application/json');
  assert.deepEqual(JSON.parse(await downloads[0].blob.text()), firstAudit);
  assert.notEqual(servedAudit.packet.packet_sha256, firstAudit.packet.packet_sha256);
  assert.match(text(control), /3 条意见、1 条观察关系、1 条资料引用/);
  assert.equal(control.querySelector('a'), null);
  assert.equal(timers.length, 1);
  assert.equal(revokedUrls.length, 0);
  timers.shift().callback();
  assert.deepEqual(revokedUrls, [downloads[0].href]);
  assert.equal(objectUrls.size, 0);
  const staleControl = context.claimSupportAuditControls(run);
  const pending = staleControl.querySelector('button').click();
  context.selectedRun = {id: 'different-run'};
  await assert.rejects(pending, /已切换报告/);
  assert.equal(staleControl.querySelector('a'), null);
  assert.equal(downloads.length, 1);
  assert.equal(objectUrls.size, 0);
  context.selectedRun = run;
  const differentCaseControl = context.claimSupportAuditControls(run);
  const changingCase = differentCaseControl.querySelector('button').click();
  context.current = {id: 'different-case'};
  await assert.rejects(changingCase, /已切换报告/);
  assert.equal(downloads.length, 1);
  assert.equal(objectUrls.size, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([node, "-", str(app_js)], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
