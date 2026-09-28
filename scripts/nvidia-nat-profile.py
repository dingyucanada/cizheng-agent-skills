#!/usr/bin/env python3
"""Profile the actual offline NVIDIA NAT reference workflow with public fixtures.

Run with the Python from the installed NAT 1.9 environment. This measures CPU
wall-clock spans of retrieve/verify/workflow, not the Qwen visual agent, CUDA,
model tokens, ceramic accuracy, or a NVIDIA Verified Skill. A new output directory
is required; previous integration receipts are never changed.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "integrations/nvidia_nat/src"))
DOCS = "https://docs.nvidia.com/nemo/agent-toolkit/latest/improve-workflows/profiler.html"
PACKAGES = ("nvidia-nat", "nvidia-nat-core", "nvidia-nat-eval", "nvidia-nat-profiler")

# Execute the installed CLI entry point, with outbound sockets denied before imports.
# This guard does not replace any NAT functions or profiler implementation.
NETWORK_GUARD = '''
import atexit, json, runpy, sys
from pathlib import Path
audit_path, cli_path, *cli_args = sys.argv[1:]
audit = {"network_requests_allowed": False, "blocked_attempts": 0}
atexit.register(lambda: Path(audit_path).write_text(json.dumps(audit, indent=2) + "\\n"))
def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
        audit["blocked_attempts"] += 1
        raise RuntimeError("Outbound network is forbidden in this offline profiler run")
sys.addaudithook(deny_network)
sys.argv = [cli_path, *cli_args]
runpy.run_path(cli_path, run_name="__main__")
'''


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def claim_output_directory(output):
    output.mkdir(parents=True, exist_ok=False)
    return output


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_eval_config(output, data_dir):
    import yaml
    config = yaml.safe_load((SOURCE / "integrations/nvidia_nat/configs/evidence.yml").read_text())
    for function in config["functions"].values():
        function["data_dir"] = str(data_dir)
    if config["llms"]:
        raise ValueError("The offline profiler must not configure an LLM")
    config["eval"] = {
        "general": {
            "max_concurrency": 1,
            "dataset": {"_type": "json", "file_path": str(output / "dataset.json")},
            "output": {"dir": str(output / "nat-eval"), "cleanup": False,
                       "workflow_output_step_filter": [], "write_atif_workflow_output": True},
            "profiler": {"base_metrics": True, "compute_llm_metrics": False,
                         "csv_exclude_io_text": True,
                         "bottleneck_analysis": {"enable_nested_stack": True}},
        },
        "evaluators": {"reference_contract": {"_type": "cizheng_reference_contract"},
                       "workflow_runtime": {"_type": "avg_workflow_runtime"},
                       "llm_calls": {"_type": "avg_num_llm_calls"}},
    }
    return config


def offline_environment(output, data_dir, inherited=None):
    inherited = os.environ if inherited is None else inherited
    provider_exporter_prefixes = ("OPENAI_", "ANTHROPIC_", "STEPFUN_", "AZURE_OPENAI_", "NVIDIA_API_",
                                 "NIM_", "HF_", "HUGGINGFACE_", "LANGCHAIN_", "LANGSMITH_", "LANGGRAPH_",
                                 "OTEL_", "PHOENIX_", "WEAVE_", "WANDB_", "NAT_")
    env = {key: value for key, value in inherited.items()
           if not any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
           and not key.upper().startswith(provider_exporter_prefixes)}
    env.update(NAT_TELEMETRY_ENABLED="false", NAT_CONFIG_DIR=str(output / "nat-config"),
               CIZHENG_DATA_DIR=str(data_dir), PYTHONPATH=os.pathsep.join((str(SOURCE), str(SOURCE / "integrations/nvidia_nat/src"))),
               LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", OTEL_SDK_DISABLED="true",
               PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR=str(output / "matplotlib"), MPLBACKEND="Agg",
               CUDA_VISIBLE_DEVICES="", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return env


def summarize_trace(requests):
    """Pair real raw events by request, family and UUID; never sum nested timings."""
    counts, spans, native = Counter(), [], []
    for request in requests:
        pending = {}
        request_spans = []
        for step in request["intermediate_steps"]:
            payload = step["payload"]
            event = payload["event_type"]
            counts[event] += 1
            if event.startswith("LLM_"):
                raise ValueError("Unexpected LLM event in the offline workflow")
            if not event.startswith(("SPAN_", "FUNCTION_")):
                continue
            family, phase = event.split("_", 1)
            key = (family, payload["UUID"])
            if phase == "START":
                if key in pending:
                    raise ValueError("Duplicate span start")
                pending[key] = step
            elif phase == "END":
                start = pending.pop(key, None)
                if start is None:
                    raise ValueError("Span end has no matching start")
                first, last = start["payload"]["event_timestamp"], payload["event_timestamp"]
                if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (first, last)) or last < first:
                    raise ValueError("Invalid span timing")
                if start["payload"]["name"] != payload["name"]:
                    raise ValueError("Span name changed between start and end")
                span = {"request_number": request["request_number"], "uuid": key[1],
                        "name": payload["name"], "event_family": family,
                        "nat_function_name": start["function_ancestry"]["function_name"],
                        "parent_id": start["parent_id"],
                        "started_at": first, "ended_at": last, "seconds": last - first}
                (spans if family == "SPAN" else native).append(span)
                if family == "SPAN":
                    request_spans.append(span)
        if pending:
            raise ValueError("Unfinished function/span event")
        if Counter(span["name"] for span in request_spans) != Counter({"workflow": 1, "retrieve": 1, "verify": 1}):
            raise ValueError("Missing actual tracked retrieve/verify/workflow spans")
        outer = next(span for span in request_spans if span["name"] == "workflow")
        for child in request_spans:
            if child["started_at"] < outer["started_at"] or child["ended_at"] > outer["ended_at"]:
                raise ValueError("Tracked action lies outside the workflow span")
    if not requests:
        raise ValueError("No actual profiler requests")
    return {"trace_requests": len(requests), "event_counts": dict(sorted(counts.items())),
            "tracked_function_span_count": len(spans), "nat_function_invocation_count": len(native),
            "tracked_function_spans": spans, "nat_function_invocations": native,
            "timing_unit": "seconds", "nested_timings_are_not_additive": True,
            "llm_event_count": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nat", type=Path, default=Path(sys.executable).parent / "nat")
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        claim_output_directory(output)
    except FileExistsError:
        parser.error("The output directory already exists; choose a fresh directory to preserve receipts.")
    status_path = output / "profiler-status.json"
    result = {"status": "running", "scope": "actual local NAT CPU reference-integrity workflow spans",
              "profiled_qwen_visual_agent": False, "gpu_requested": False, "model_inference_performed": False,
              "model_token_performance_measured": False, "ceramic_accuracy_measured": False,
              "nvidia_verified_skill": False, "telemetry_enabled": False,
              "remote_exporters_configured": False, "official_profiler_documentation": DOCS,
              "host": {"system": platform.system(), "machine": platform.machine()}, "commands": []}
    write_json(status_path, result)
    started = time.monotonic()
    try:
        result["dependencies"] = {name: version(name) for name in (*PACKAGES, "cizheng-nvidia-nat")}
        if any(result["dependencies"][name] != "1.9.0" for name in PACKAGES):
            raise ValueError("This reproducible profiler requires installed official NAT 1.9.0 packages")
        nat = args.nat.resolve()
        if not nat.is_file() or nat.parent != Path(sys.executable).absolute().parent:
            raise ValueError("Use the NAT executable in the same Python environment")
        import cizheng_nat.register as registered
        expected_register = SOURCE / "integrations/nvidia_nat/src/cizheng_nat/register.py"
        if Path(registered.__file__).resolve() != expected_register.resolve():
            raise ValueError("The installed entry point is bound to a different plugin source")
        source_paths = [expected_register, SOURCE / "integrations/nvidia_nat/src/cizheng_nat/evidence.py",
                        SOURCE / "integrations/nvidia_nat/src/cizheng_nat/evaluators.py",
                        SOURCE / "integrations/nvidia_nat/configs/evidence.yml",
                        SOURCE / "scripts/nvidia-nat-verify.py", Path(__file__).resolve()]
        result["source_sha256"] = {str(path.relative_to(SOURCE)): sha256(path) for path in source_paths}
        from nat.plugins.profiler.decorators import function_tracking
        result["official_decorator_sha256"] = sha256(Path(function_tracking.__file__))
        spec = importlib.util.spec_from_file_location("cizheng_nat_public_fixture", SOURCE / "scripts/nvidia-nat-verify.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        data_dir, _ = fixture.prepare(output)
        import yaml
        eval_path = output / "eval.yml"
        eval_path.write_text(yaml.safe_dump(build_eval_config(output, data_dir), sort_keys=False))
        env = offline_environment(output, data_dir)
        result["inherited_credentials_and_provider_exporter_environment_stripped"] = True
        for name, arguments in (("validate", ["validate", "--config_file", str(eval_path)]),
                                ("eval", ["eval", "--config_file", str(eval_path), "--reps", "1"])):
            audit_path = output / (name + "-network-audit.json")
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            command_started = time.monotonic()
            command = {"name": name, "nat_arguments": arguments, "network_guard": "Python socket audit hook"}
            result["commands"].append(command)
            try:
                completed = subprocess.run([sys.executable, "-c", NETWORK_GUARD, str(audit_path), str(nat), *arguments],
                                           cwd=SOURCE, env=env, text=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, timeout=180)
                (output / (name + ".log")).write_text(completed.stdout)
                command["exit_code"] = completed.returncode
            except subprocess.TimeoutExpired as exc:
                saved = exc.stdout or b""
                (output / (name + ".log")).write_text(saved.decode(errors="replace") if isinstance(saved, bytes) else saved)
                command["timed_out"] = True
                raise
            finally:
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                command.update(wall_seconds=time.monotonic() - command_started,
                               child_cpu_user_seconds=after.ru_utime - before.ru_utime,
                               child_cpu_system_seconds=after.ru_stime - before.ru_stime)
                write_json(status_path, result)
            command["network_audit"] = json.loads(audit_path.read_text())
            if completed.returncode or command["network_audit"]["blocked_attempts"]:
                raise RuntimeError(name + " failed; see its preserved log and network audit")
        eval_dir = output / "nat-eval"
        result.update(summarize_trace(json.loads((eval_dir / "all_requests_profiler_traces.json").read_text())))
        workflow = json.loads((eval_dir / "workflow_output.json").read_text())
        if len(workflow) != 3 or result["trace_requests"] != 3:
            raise ValueError("Expected all three actual software fixture results")
        statuses = []
        for item in workflow:
            actual = json.loads(item["generated_answer"])
            if actual["usage"]["model_calls"] != 0 or actual["inference_performed"] is not False:
                raise ValueError("Zero-inference workflow boundary changed")
            statuses.append({"id": item["id"], "status": actual["status"],
                             "model_calls": actual["usage"]["model_calls"],
                             "tool_calls": actual["usage"]["tool_calls"]})
        result["software_fixture_results"] = statuses
        contract = json.loads((eval_dir / "reference_contract_output.json").read_text())
        calls = json.loads((eval_dir / "llm_calls_output.json").read_text())
        if contract["average_score"] != 1.0 or calls["average_score"] != 0:
            raise ValueError("Reference contract or zero-LLM evaluator failed")
        result["reference_contract_average"] = contract["average_score"]
        result["llm_calls_average"] = calls["average_score"]
        atif = json.loads((eval_dir / "workflow_output_atif.json").read_text())
        result["atif_trajectory_step_count"] = sum(len(item["trajectory"].get("steps", [])) for item in atif)
        with (eval_dir / "standardized_data_all.csv").open() as stream:
            result["standardized_csv_event_rows"] = sum(1 for _ in csv.DictReader(stream))
        artifacts = ("all_requests_profiler_traces.json", "standardized_data_all.csv", "gantt_chart.png",
                     "workflow_profiling_metrics.json", "workflow_profiling_report.txt", "workflow_output_atif.json")
        if any(not (eval_dir / name).is_file() or not (eval_dir / name).stat().st_size for name in artifacts):
            raise ValueError("Actual profiler output is incomplete")
        result["artifact_sha256"] = {"nat-eval/" + name: sha256(eval_dir / name) for name in artifacts}
        if any(sha256(SOURCE / name) != digest for name, digest in result["source_sha256"].items()):
            raise ValueError("Profiled source changed during execution")
        result["status"] = "passed"
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
    result["total_wall_seconds"] = time.monotonic() - started
    write_json(status_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
