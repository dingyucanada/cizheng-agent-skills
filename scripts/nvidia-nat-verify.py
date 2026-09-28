#!/usr/bin/env python3
"""Reproduce real CLI discovery, validation, run and offline NAT evaluation.

Uses project-original summaries of public reference metadata. It does not run a
model, produce ceramic conclusions, upload photos or qualify a Verified Skill.
Run with the Python from the isolated NAT environment.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "integrations/nvidia_nat/src"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare(output):
    from cizheng.knowledge import KnowledgeStore, read_snapshot, search_snapshot
    from cizheng.knowledge_seed import seed_knowledge
    from cizheng.schemas import NewCase
    from cizheng.store import Store
    from cizheng_nat.evidence import citation_for

    directory = output / "public-reference-case"
    store, knowledge = Store(directory), KnowledgeStore(directory)
    seed_knowledge(knowledge)
    case = store.create_case(NewCase(
        request_id="nat-public-reference-integrity-v1", title="公开资料引用核验 · 山水纹花觚",
        research_task="documentary_audit", question="核验本案绑定资料的版本、段落哈希与引用定位。",
        target_attribution="只验证资料引用身份，不生成实物研究意见",
        source_declaration="公开软件验收。项目原创摘要引用 Met 48607 馆藏元数据；非盲测、无模型推理。"
    ).model_dump())
    case = store.read("case", case["id"])
    source = next(source for source in knowledge.list_sources(limit=500)["sources"]
                  if source["source_url"] == "https://www.metmuseum.org/art/collection/search/48607")
    if not any(binding["document_id"] == source["document_id"] and
               binding["document_revision"] == source["revision"] and
               binding["document_sha256"] == source["document_sha256"] for binding in case["knowledge_links"]):
        case = store.link_document(case["id"], {"request_id": "nat-public-source-bind-c" + str(case["revision"]),
                                   "expected_case_revision": case["revision"], "document_id": source["document_id"]})
    # Read current case after idempotent replay, preserving later revisions.
    case = store.read("case", case["id"])
    request = {"case_id": case["id"], "expected_case_revision": case["revision"],
               "queries": ["山水纹花觚"], "limit": 2}
    snap = knowledge.snapshot([source["document_id"]], case["knowledge_links"])
    match = search_snapshot(snap, "山水纹花觚", limit=1)["results"][0]
    actual = read_snapshot(snap, match["document_id"], match["chunk_id"], limit=1)["chunks"][0]
    tampered = citation_for(actual) | {"chunk_sha256": "0" * 64}
    dataset = [
        {"id": "reference-valid", "question": json.dumps(request, ensure_ascii=False),
         "answer": json.dumps({"status": "references_verified"})},
        {"id": "tampered-chunk-hash", "question": json.dumps(request | {"citations": [tampered]}, ensure_ascii=False),
         "answer": json.dumps({"status": "reference_mismatch"})},
        {"id": "no-retrieved-evidence", "question": json.dumps(request | {"queries": []}, ensure_ascii=False),
         "answer": json.dumps({"status": "no_read_evidence"})},
    ]
    write_json(output / "request.json", request)
    write_json(output / "dataset.json", dataset)
    return directory, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SOURCE / ".tmp/nvidia-integration-evidence")
    parser.add_argument("--nat", type=Path, default=Path(sys.executable).parent / "nat")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    nat = args.nat.resolve()
    if not nat.is_file():
        parser.error("Use the Python from an environment with the official nvidia-nat CLI installed.")
    data_dir, request = prepare(output)
    config = SOURCE / "integrations/nvidia_nat/configs/evidence.yml"
    env = os.environ.copy()
    env.update(NAT_TELEMETRY_ENABLED="false", NAT_CONFIG_DIR=str(output / "nat-config"),
               CIZHENG_DATA_DIR=str(data_dir), PYTHONPATH=str(SOURCE),
               LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", OTEL_SDK_DISABLED="true",
               PYTHONDONTWRITEBYTECODE="1",
               MPLCONFIGDIR=str(output / "matplotlib"))
    commands = []

    def run(name, *arguments):
        started = time.monotonic()
        completed = subprocess.run([str(nat), *arguments], cwd=SOURCE, env=env,
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (output / (name + ".log")).write_text(completed.stdout)
        commands.append({"name": name, "exit_code": completed.returncode,
                         "seconds": round(time.monotonic() - started, 3)})
        if completed.returncode:
            write_json(output / "verification-status.json", {"status": "failed", "commands": commands})
            raise RuntimeError(name + " failed; inspect its saved log")

    run("telemetry", "configure", "telemetry", "--status")
    run("discovery", "info", "components", "-t", "function", "-q", "cizheng",
        "--output_path", str(output / "components.json"))
    run("evaluator-discovery", "info", "components", "-t", "evaluator", "-q", "cizheng",
        "--output_path", str(output / "evaluators.json"))
    run("validate", "validate", "--config_file", str(config))
    before = set((data_dir / "nat-audit").glob("*.verification.json")) if (data_dir / "nat-audit").exists() else set()
    run("run", "run", "--config_file", str(config), "--input", json.dumps(request, ensure_ascii=False))
    after = set((data_dir / "nat-audit").glob("*.verification.json"))
    artifacts = list(after - before)
    if len(artifacts) != 1:
        raise RuntimeError("CLI run did not produce exactly one fresh verification receipt")
    run_result = json.loads(artifacts[0].read_text())
    if run_result["status"] != "references_verified" or run_result["usage"]["model_calls"] != 0:
        raise RuntimeError("Unexpected reference-integrity result")
    write_json(output / "run-result.json", run_result)
    import yaml
    eval_config = yaml.safe_load(config.read_text())
    eval_config["eval"] = {
        "general": {"max_concurrency": 1, "dataset": {"_type": "json", "file_path": str(output / "dataset.json")},
                    "output": {"dir": str(output / "nat-eval"), "cleanup": False,
                               "write_atif_workflow_output": True}},
        "evaluators": {"reference_contract": {"_type": "cizheng_reference_contract"},
                       "workflow_runtime": {"_type": "avg_workflow_runtime"},
                       "llm_calls": {"_type": "avg_num_llm_calls"}},
    }
    eval_path = output / "eval.yml"; eval_path.write_text(yaml.safe_dump(eval_config, sort_keys=False))
    run("validate-eval", "validate", "--config_file", str(eval_path))
    run("eval", "eval", "--config_file", str(eval_path))
    contract = json.loads((output / "nat-eval/reference_contract_output.json").read_text())
    calls = json.loads((output / "nat-eval/llm_calls_output.json").read_text())
    runtime = json.loads((output / "nat-eval/workflow_runtime_output.json").read_text())
    if contract["average_score"] != 1.0 or calls["average_score"] != 0:
        raise RuntimeError("NAT evaluation contract or zero-inference check failed")
    result = {"status": "passed", "scope": "real local NAT integration; deterministic software contract only",
              "nvidia_nat_version": version("nvidia-nat"), "plugin_version": version("cizheng-nvidia-nat"),
              "telemetry_enabled": False, "remote_exporters_configured": False,
              "dataset_items": 3, "reference_contract_average": contract["average_score"],
              "llm_calls_average": calls["average_score"], "workflow_runtime_average_seconds": runtime["average_score"],
              "commands": commands, "nvidia_verified_skill": False,
              "ai_efficacy_or_ceramic_accuracy_measured": False}
    write_json(output / "verification-status.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
