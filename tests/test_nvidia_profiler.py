"""Offline profiling evidence and the unchanged registered workflow boundary."""
import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "integrations/nvidia_nat/src"))
spec = importlib.util.spec_from_file_location("cizheng_nat_profiler_script", SOURCE / "scripts/nvidia-nat-profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def test_output_requires_fresh_directory_and_preserves_previous_receipts(tmp_path):
    output = profile.claim_output_directory(tmp_path / "profile")
    receipt = output / "previous.json"
    receipt.write_text('{"immutable":true}')
    with pytest.raises(FileExistsError):
        profile.claim_output_directory(output)
    assert receipt.read_text() == '{"immutable":true}'


def test_config_enables_actual_profiler_and_all_events_without_a_provider(tmp_path):
    config = profile.build_eval_config(tmp_path, tmp_path / "case")
    assert config["llms"] == {}
    assert not config.get("general", {}).get("telemetry", {}).get("tracing")
    general = config["eval"]["general"]
    assert general["max_concurrency"] == 1
    assert general["profiler"]["bottleneck_analysis"]["enable_nested_stack"] is True
    assert general["profiler"]["compute_llm_metrics"] is False
    assert general["output"]["workflow_output_step_filter"] == []
    assert general["output"]["cleanup"] is False
    assert config["functions"]["evidence_retrieve"]["max_tool_calls"] == 20
    assert config["functions"]["evidence_retrieve"]["max_seconds"] == 300


def test_empty_trace_cannot_be_declared_successful_profiling():
    with pytest.raises(ValueError, match="No actual profiler requests"):
        profile.summarize_trace([])


def test_offline_environment_strips_inherited_credentials_and_remote_exporters(tmp_path):
    env = profile.offline_environment(tmp_path, tmp_path / "case", {
        "PATH": "/usr/bin", "OPENAI_API_KEY": "test-credential", "STEPFUN_TOKEN": "test-token",
        "ANTHROPIC_BASE_URL": "https://example.invalid", "LANGSMITH_ENDPOINT": "https://example.invalid",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://example.invalid", "UNRELATED_SECRET": "test-secret",
        "NAT_TELEMETRY_ENABLED": "true", "NAT_CONFIG_DIR": "/inherited/private/config",
    })
    assert env["PATH"] == "/usr/bin"
    assert not any(key in env for key in ("OPENAI_API_KEY", "STEPFUN_TOKEN", "ANTHROPIC_BASE_URL",
                                          "LANGSMITH_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT", "UNRELATED_SECRET"))
    assert env["NAT_TELEMETRY_ENABLED"] == "false" and env["OTEL_SDK_DISABLED"] == "true"
    assert env["NAT_CONFIG_DIR"] == str(tmp_path / "nat-config")


def test_runtime_only_optional_profiler_absence_does_not_break_registration(tmp_path):
    pytest.importorskip("nat.builder.builder")
    code = '''
import importlib.metadata
original_version = importlib.metadata.version
def runtime_only_version(name):
    if name == "nvidia-nat-profiler":
        raise importlib.metadata.PackageNotFoundError(name)
    return original_version(name)
importlib.metadata.version = runtime_only_version
from cizheng_nat import register
async def sample(message: str) -> str:
    return message
assert register.track_function(sample) is sample
assert register.RetrieveConfig(data_dir="/unused").max_tool_calls == 20
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=SOURCE,
                               env=profile.offline_environment(tmp_path, tmp_path / "case"),
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    assert completed.returncode == 0, completed.stdout


def test_real_registered_workflow_has_paired_nested_spans_and_keeps_case_scope(tmp_path, monkeypatch):
    pytest.importorskip("nat.plugins.profiler.decorators.function_tracking")
    import socket
    from cizheng.knowledge import KnowledgeStore
    from cizheng.store import Store
    from cizheng_nat.register import RetrieveConfig, VerifyConfig, WorkflowConfig
    from nat.builder.runtime_event_subscriber import pull_intermediate
    from nat.builder.workflow_builder import WorkflowBuilder
    from nat.data_models.config import Config
    from nat.runtime.session import SessionManager

    monkeypatch.setenv("NAT_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("Network is forbidden"))
    store, knowledge = Store(tmp_path), KnowledgeStore(tmp_path)
    case = store.create_case({"request_id": "nat-profiler-case", "title": "引用协议分析",
                              "question": "只核验引用", "target_attribution": "软件测试",
                              "source_declaration": "项目原创协议文字"})
    document = {"title": "本案协议文字", "source_type": "original_protocol_fixture", "rights": "authorized_text",
                "rights_note": "项目原创软件测试材料", "locator": "第1节", "scope": "引用软件协议",
                "text": "蟠螭甲仅用于软件引用核验。", "limitations": ["不是陶瓷研究证据。"]}
    source = knowledge.add_document(document)["source"]
    other = knowledge.add_document(document | {"title": "另案文字", "text": "蟠螭甲另案不可读取标记"})["source"]
    case = store.link_document(case["id"], {"request_id": "nat-profiler-bind",
                                           "document_id": source["document_id"], "expected_case_revision": 1})
    request = {"case_id": case["id"], "expected_case_revision": case["revision"], "queries": ["蟠螭甲"], "limit": 2}
    config = Config(functions={"evidence_retrieve": RetrieveConfig(data_dir=str(tmp_path)),
                               "evidence_verify": VerifyConfig(data_dir=str(tmp_path))},
                    workflow=WorkflowConfig(retrieve="evidence_retrieve", verify="evidence_verify"), llms={})

    async def execute():
        async with WorkflowBuilder.from_config(config) as builder:
            manager = await SessionManager.create(config, builder, max_concurrency=1)
            try:
                async with manager.session(user_id="offline-profiler-test") as session:
                    async with session.run(json.dumps(request, ensure_ascii=False)) as runner:
                        events = pull_intermediate()
                        result = await runner.result()
                        return json.loads(result), await events
            finally:
                await manager.shutdown()

    result, events = asyncio.run(execute())
    assert result["status"] == "references_verified"
    assert result["usage"]["model_calls"] == 0 and result["usage"]["tool_calls"] == 5
    assert result["inference_performed"] is False
    assert other["document_id"] not in json.dumps(result)
    assert "另案不可读取标记" not in json.dumps(result, ensure_ascii=False)
    assert store.read("case", case["id"]) == case
    assert store.listing("run") == []
    summary = profile.summarize_trace([{"request_number": 0, "intermediate_steps": events}])
    assert summary["tracked_function_span_count"] == 3
    assert summary["nat_function_invocation_count"] == 3
    assert summary["llm_event_count"] == 0
    spans = {span["name"]: span for span in summary["tracked_function_spans"]}
    natives = {span["uuid"]: span for span in summary["nat_function_invocations"]}
    assert spans["workflow"]["parent_id"] in natives
    for action in ("retrieve", "verify"):
        parent = natives[spans[action]["parent_id"]]
        assert parent["name"] == "evidence_" + action
        assert parent["parent_id"] == spans["workflow"]["uuid"]
    missing_end = [step for step in events if not (step["payload"]["event_type"] == "SPAN_END"
                                                 and step["payload"]["name"] == "retrieve")]
    with pytest.raises(ValueError, match="Unfinished function/span"):
        profile.summarize_trace([{"request_number": 0, "intermediate_steps": missing_end}])
