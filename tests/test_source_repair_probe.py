"""One-shot CLI contracts with original LocalModel and explicit HTTP mocks.

No GPU, real provider, expert label, or semantic accuracy is exercised.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from cizheng import agent, schemas as S
from cizheng.agent import _ToolResultMessage
from cizheng.store import dump
from evals import run_source_repair_probe as probe
from test_source_attribution_gate import reader, deliver, opinion

HTTP_CLIENT = httpx.AsyncClient
pytestmark = pytest.mark.parametrize("reader", [True], indirect=True, ids=["compact"])


@pytest.fixture
def bundle(reader, tmp_path, monkeypatch):
    store, engine, run_id, result = reader
    deliver(reader, _ToolResultMessage("read_knowledge", result))
    short = opinion()
    short["reference_comparison"] = "馆方记载仅用于合成来源上下文"
    short["knowledge_citations"] = [{"read_index": 1, "use": "source_context",
                                     "relevance": "合成测试模型选择的来源背景"}]
    expanded, _ = engine.expand_compact_assessment(run_id, agent.CompactAssessment.model_validate(short))
    asyncio.run(engine.tool(run_id, "record_assessment", S.Assessment.model_validate(expanded)))
    run_path, request_path = tmp_path / "run.json", tmp_path / "request.json"
    run_path.write_text(dump(store.read("run", run_id)))
    raw = dump({"actions": [{"tool": "record_assessment", "arguments": short}]})
    request_path.write_text(dump({"response_text": raw}))
    prepared = tmp_path / "prepared"
    process = subprocess.run(probe.helper_command(run_path, request_path, prepared),
                             cwd=probe.ROOT, text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    monkeypatch.setenv("CIZHENG_STRUCTURED_OUTPUTS", "1")
    monkeypatch.setenv("CIZHENG_COMPACT_ACTIONS", "1")
    monkeypatch.setenv("CIZHENG_MODEL_KEY", "")
    monkeypatch.setenv("CIZHENG_DISABLE_THINKING", "0")
    return prepared, run_path, request_path, raw


def run(bundle, output, **kwargs):
    prepared, run_path, request_path, _ = bundle
    return asyncio.run(probe.run_probe(prepared=prepared, run=run_path,
        record_request=request_path, output=output, model_url="http://127.0.0.1:9999/v1",
        model_name="SYNTHETIC-ONLY", **kwargs))


@pytest.mark.parametrize("reply", ["selected_citation", "remove_assertion", "still_empty",
                                  "string_index", "native_rejection", "deadline", "network_timeout"])
def test_exact_native_request_once_and_model_result_preserved(bundle, tmp_path, monkeypatch, reply):
    prepared, _, _, original_raw = bundle
    requests = []
    response_raw = original_raw
    payload = json.loads(original_raw)
    if reply in ("still_empty", "remove_assertion"):
        payload = json.loads((prepared / "counterexample.json").read_text())
        if reply == "remove_assertion":
            payload["actions"][0]["arguments"]["reference_comparison"] = "没有实物参照图"
        response_raw = dump(payload)
    elif reply == "string_index":
        payload["actions"][0]["arguments"]["knowledge_citations"][0]["read_index"] = "1"
        response_raw = dump(payload)
    usage = {"prompt_tokens": 100, "completion_tokens": 70, "total_tokens": 170}
    def respond(request):
        actual = json.loads(request.content)
        requests.append(actual)
        if reply == "network_timeout":
            raise httpx.ReadTimeout("SYNTHETIC private provider error")
        if reply == "native_rejection":
            return httpx.Response(422, json={"detail": {
                "type": "structured_output_validation",
                "schema_sha256": agent.decoder_schema_sha256(actual["response_format"]["json_schema"]["schema"]),
                "response_sha256": "b" * 64, "usage": usage}})
        return httpx.Response(200, json={"choices": [{"message": {"content": response_raw},
            "finish_reason": "length" if reply == "deadline" else "stop"}], "usage": usage,
            "cizheng_runtime": {"termination": "deadline" if reply == "deadline" else "eos",
                                "identity": "SYNTHETIC native observation"}})
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kwargs: HTTP_CLIENT(
        transport=httpx.MockTransport(respond), **kwargs))
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(dump({"identity": "SYNTHETIC supplied file"}))
    output = tmp_path / "result"
    result = run(bundle, output, server_identity=identity_path)
    assert len(requests) == result["http_requests_observed"] == result["model_calls_attempted"] == 1
    actual = requests[0]
    assert actual["max_tokens"] == 2500 and actual["temperature"] == 0.1
    assert actual["response_format"]["json_schema"]["strict"] is True
    assert actual["response_format"]["json_schema"]["schema"] == json.loads(
        (prepared / "registered-action-schema.json").read_text())
    assert actual["messages"] == json.loads((output / "messages.json").read_text())
    assert actual["messages"][0]["content"] == agent.system_prompt("plain", "visual_research", True,
                                                               "record_assessment_required")
    assert not any(isinstance(item["content"], list) for item in actual["messages"])
    assert result["original_artifacts_unchanged"] and not result["opinion_built"]
    assert not result["host_filled_citations_or_conclusions"] and not result["original_request_replay"]
    assert result["operator_server_identity_provenance"] == "supplied_local_file_not_authenticated_by_probe"
    if reply in ("selected_citation", "remove_assertion"):
        assert result["state"] == "contract_repair_accepted" and result["frozen_validation_exit"] == 0
    elif reply in ("still_empty", "string_index"):
        assert result["state"] == "contract_repair_rejected" and result["frozen_validation_exit"] == 1
    else:
        assert result["state"] == "model_failed" and "frozen_validation_exit" not in result
    if reply not in ("native_rejection", "network_timeout"):
        assert (output / "response.txt").read_text() == response_raw
        assert result["same_response_native_runtime"]["identity"] == "SYNTHETIC native observation"
    if reply == "deadline":
        assert result["finish_reason"] == "length" and not result["local_model_returned_text"]
        assert json.loads((output / "response-record.json").read_text())["succeeded"] is False
    if reply == "native_rejection":
        assert result["native_schema_failure"]["response_sha256"] == "b" * 64
        assert result["usage"] == usage and (output / "http-response.raw.json").exists()
    if reply == "network_timeout":
        assert not (output / "http-response.raw.json").exists()
        assert "private provider error" not in (output / "summary.json").read_text()


@pytest.mark.parametrize("mutation", ["messages", "schema", "mother_sha", "disabled_native"])
def test_tampered_or_unconfigured_preflight_never_calls_model(bundle, tmp_path, monkeypatch, mutation):
    prepared, _, _, _ = bundle
    if mutation == "disabled_native":
        monkeypatch.setenv("CIZHENG_STRUCTURED_OUTPUTS", "0")
    else:
        filename = {"messages": "prepared-text-request.json", "schema": "registered-action-schema.json",
                    "mother_sha": "probe-meta.json"}[mutation]
        path = prepared / filename
        value = json.loads(path.read_text())
        if mutation == "messages":
            value["messages"][0]["content"] += " changed"
        elif mutation == "schema":
            value["properties"]["actions"]["minItems"] = 0
        else:
            value["original_run_file_sha256"] = "0" * 64
        path.write_text(dump(value))
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must not construct a real or mocked provider client")
    monkeypatch.setattr(agent.httpx, "AsyncClient", forbidden)
    result = run(bundle, tmp_path / "rejected")
    assert result["state"] == "preflight_failed"
    assert result["model_calls_attempted"] == result["http_requests_observed"] == 0
    assert result["original_artifacts_unchanged"]


def test_existing_output_cannot_be_overwritten_or_issue_request(bundle, tmp_path, monkeypatch):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        run(bundle, output)
    assert (output / "keep.txt").read_text() == "keep"
