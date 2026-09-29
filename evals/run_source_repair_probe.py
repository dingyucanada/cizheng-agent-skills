"""One recorded native-schema request for an AI-edited text counterexample.

Never replay missing r5 messages, send images, fill citations, build an opinion,
or retry. The production LocalModel.complete owns generation and native_schema.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cizheng import agent
from cizheng.store import dump

HELPER = ROOT / "evals/source_repair_probe/prepare_and_validate.py"


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def helper_command(run, record_request, output, response=None):
    command = [sys.executable, "-B", str(HELPER), "--repo", str(ROOT),
               "--run", str(run), "--record-request", str(record_request),
               "--output", str(output)]
    if response is not None:
        command += ["--model-output", str(response)]
    return command


@contextmanager
def record_single_http(evidence, schema):
    """Observe the existing client's one request; do not replace generation.

    This scope is used only by this isolated one-shot CLI. Headers are never
    saved. Unrecognized HTTP error bodies remain private, as in LocalModel.
    """
    original_factory = agent.httpx.AsyncClient

    async def request_hook(request):
        evidence["http_requests"] += 1
        if evidence["http_requests"] != 1:
            raise ValueError("probe_allows_one_http_request")
        payload = json.loads(request.content)
        if (payload.get("max_tokens") != 2500 or
                payload.get("response_format", {}).get("json_schema", {}).get("schema") != schema or
                payload["response_format"]["json_schema"].get("strict") is not True):
            raise ValueError("probe_requires_unchanged_registered_native_schema")
        evidence["http_request_payload"] = payload

    async def response_hook(response):
        await response.aread()
        evidence["http_status"] = response.status_code
        evidence["http_response_sha256"] = hashlib.sha256(response.content).hexdigest()
        safe = 200 <= response.status_code < 300
        if not safe:
            safe = agent._local_schema_failure(response, evidence["http_request_payload"]) is not None
        if safe:
            evidence["http_response_bytes"] = response.content
            try:
                body = response.json()
                evidence["same_response_native_runtime"] = body.get("cizheng_runtime")
                choices = body.get("choices", [])
                if choices and isinstance(choices[0].get("message", {}).get("content"), str):
                    evidence["same_response_choice_text"] = choices[0]["message"]["content"]
            except (ValueError, AttributeError):
                pass

    def client_factory(*args, **kwargs):
        hooks = {key: list(value) for key, value in kwargs.pop("event_hooks", {}).items()}
        hooks.setdefault("request", []).append(request_hook)
        hooks.setdefault("response", []).append(response_hook)
        return original_factory(*args, event_hooks=hooks, **kwargs)

    agent.httpx.AsyncClient = client_factory
    try:
        yield
    finally:
        agent.httpx.AsyncClient = original_factory


async def run_probe(*, prepared, run, record_request, output, model_url, model_name,
                    server_identity=None):
    prepared, run, record_request, output = map(Path, (prepared, run, record_request, output))
    output.mkdir(parents=True, exist_ok=False)
    result = {"experiment": "AI_EDITED_TEXT_COUNTEREXAMPLE_NOT_R5_REPLAY", "author": "AI",
              "original_request_replay": False, "image_access": "report_text_only",
              "expert_validation_established": False, "professional_quality_assessed": False,
              "opinion_built": False, "host_filled_citations_or_conclusions": False,
              "model_calls_attempted": 0, "model_call_limit": 1, "max_tokens": 2500,
              "timeout_seconds": 90, "state": "preflight", "usage": {}, "finish_reason": None}
    evidence = {"http_requests": 0}
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (run, record_request)}
    raw = None
    began = time.monotonic()
    try:
        # Recreate the edited counterexample/actual guard feedback from the
        # supplied mother record. Arbitrary prepared context is not accepted.
        with tempfile.TemporaryDirectory(prefix="probe-preflight-", dir=output) as temporary:
            generated = Path(temporary) / "verified"
            check = subprocess.run(helper_command(run.resolve(), record_request.resolve(), generated),
                                   cwd=ROOT, capture_output=True, text=True, timeout=30)
            if check.returncode:
                raise ValueError("frozen_counterexample_preparation_failed")
            names = ("counterexample.json", "guard-feedback.json", "prepared-text-request.json",
                     "registered-action-schema.json", "probe-meta.json")
            values = {name: json.loads((prepared / name).read_text()) for name in names}
            if any(value != json.loads((generated / name).read_text()) for name, value in values.items()):
                raise ValueError("prepared_package_does_not_match_frozen_counterexample")
        messages = values["prepared-text-request.json"]["messages"]
        schema = values["registered-action-schema.json"]
        meta = values["probe-meta.json"]
        if any(not isinstance(message.get("content"), str) for message in messages):
            raise ValueError("probe_must_be_text_only")
        variant = agent._action_prompt_variant(messages, True)
        if variant != (json.loads(run.read_text())["mode"], "visual_research", True,
                       "record_assessment_required"):
            raise ValueError("exact_registered_record_phase_required")
        if schema != agent.action_output_schema(*variant):
            raise ValueError("registered_schema_changed")
        if agent.bounded_messages(messages) != messages:
            raise ValueError("prepared_context_exceeds_original_context_budget")
        model = agent.LocalModel(model_url, model_name)
        if not model.structured_outputs or not model.compact_actions:
            raise ValueError("set_CIZHENG_STRUCTURED_OUTPUTS_and_CIZHENG_COMPACT_ACTIONS_to_1")
        result.update(model_identity=model.identity(), mother_run_sha256=meta["original_run_file_sha256"],
                      mother_request_sha256=meta["original_request_file_sha256"],
                      frozen_run_input_sha256=meta["run_input_sha256"],
                      registered_phase=meta["registered_phase"],
                      system_prompt_sha256=meta["system_prompt_sha256"],
                      decoder_schema_sha256=agent.decoder_schema_sha256(schema),
                      prepared_messages_sha256=hashlib.sha256(dump(messages).encode()).hexdigest())
        write_new(output / "messages.json", messages)
        write_new(output / "registered-action-schema.json", schema)
        write_new(output / "counterexample.json", values["counterexample.json"])
        write_new(output / "guard-feedback.json", values["guard-feedback.json"])
        if server_identity is not None:
            identity_path = Path(server_identity)
            identity_bytes = identity_path.read_bytes()
            write_new(output / "operator-server-identity.json", json.loads(identity_bytes))
            result["operator_server_identity_sha256"] = hashlib.sha256(identity_bytes).hexdigest()
            result["operator_server_identity_provenance"] = "supplied_local_file_not_authenticated_by_probe"
        result["model_calls_attempted"] = 1
        call_started = time.monotonic()
        try:
            with record_single_http(evidence, schema):
                raw, usage = await asyncio.wait_for(model.complete(messages, 90), timeout=90)
            result.update(usage=usage, finish_reason=usage.get("finish_reason"), state="response_received")
        except Exception as error:
            result.update(state="model_failed", error_type=type(error).__name__,
                          usage=dict(getattr(error, "usage", {}) or {}))
            result["finish_reason"] = result["usage"].get("finish_reason")
            if isinstance(error, agent.LocalModelSchemaFailure):
                result["native_schema_failure"] = error.safe_detail()
        finally:
            result["model_seconds"] = time.monotonic() - call_started
        # A truncated or otherwise rejected native response is still saved,
        # but only text actually returned by LocalModel can enter validation.
        recorded_raw = raw if raw is not None else evidence.get("same_response_choice_text")
        result["local_model_returned_text"] = raw is not None
        if recorded_raw is not None:
            with (output / "response.txt").open("x", encoding="utf-8") as stream:
                stream.write(recorded_raw)
            result["response_sha256"] = hashlib.sha256(recorded_raw.encode()).hexdigest()
            write_new(output / "response-record.json", {"response_text": recorded_raw, "usage": result["usage"],
                      "seconds": result["model_seconds"], "messages_sha256": result["prepared_messages_sha256"],
                      "response_sha256": result["response_sha256"], "succeeded": raw is not None})
        if raw is not None:
            validation = subprocess.run(helper_command(run.resolve(), record_request.resolve(), output.resolve() / "frozen-validation",
                                        output.resolve() / "response-record.json"),
                                        cwd=ROOT, capture_output=True, text=True, timeout=30)
            result["frozen_validation_exit"] = validation.returncode
            with (output / "validation.stdout.txt").open("x", encoding="utf-8") as stream:
                stream.write(validation.stdout)
            with (output / "validation.stderr.txt").open("x", encoding="utf-8") as stream:
                stream.write(validation.stderr)
            result["state"] = "contract_repair_accepted" if validation.returncode == 0 else "contract_repair_rejected"
    except Exception as error:
        result.update(state="preflight_failed" if result["model_calls_attempted"] == 0 else "probe_failed",
                      error_type=type(error).__name__)
    finally:
        result["seconds"] = time.monotonic() - began
        result["http_requests_observed"] = evidence["http_requests"]
        result["http_status"] = evidence.get("http_status")
        result["http_response_sha256"] = evidence.get("http_response_sha256")
        result["same_response_native_runtime"] = evidence.get("same_response_native_runtime")
        result["original_artifacts_unchanged"] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
                                                     for path, sha in before.items())
        if "http_request_payload" in evidence:
            write_new(output / "http-request.json", evidence["http_request_payload"])
        if "http_response_bytes" in evidence:
            with (output / "http-response.raw.json").open("xb") as stream:
                stream.write(evidence["http_response_bytes"])
        write_new(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--record-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-url", required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--server-identity", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_probe(prepared=args.prepared, run=args.run, record_request=args.record_request,
                                  output=args.output, model_url=args.model_url, model_name=args.model,
                                  server_identity=args.server_identity))
    print(dump(result))
    raise SystemExit(0 if result["state"] == "contract_repair_accepted" and result["original_artifacts_unchanged"] else 1)


if __name__ == "__main__":
    main()
