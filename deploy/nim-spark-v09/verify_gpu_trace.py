"""Bind a private SGLang profiler slice to the original NIM process and one public request."""
import argparse
import gzip
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path

from preflight import CONFIG_ID, IMAGE
from accept_text_once import REQUEST

CONTAINER = "cizheng-nim-qwen4b-v09"
MODEL = "Qwen3-4B-Instruct-2507"


def capture_identity(container=CONTAINER):
    if not re.fullmatch(r"cizheng-nim-qwen4b-v09(?:-attempt-[0-9]{2})?", container):
        raise ValueError("unowned candidate name rejected")
    item = json.loads(subprocess.run(["docker", "inspect", container],
                                    capture_output=True, check=True).stdout)[0]
    if (item["Config"]["Image"] != IMAGE or item["Image"] != CONFIG_ID
            or item["State"]["Running"] is not True
            or item["Config"]["Entrypoint"] != ["/opt/nim/start_server.sh"]):
        raise ValueError("pinned NIM candidate identity required")
    bindings = item["HostConfig"].get("PortBindings", {}).get("8000/tcp")
    if bindings != [{"HostIp": "127.0.0.1", "HostPort": "8007"}]:
        raise ValueError("only the isolated loopback endpoint is allowed")
    top = subprocess.run(["docker", "top", container, "-o", "pid"],
                         capture_output=True, text=True, check=True).stdout
    host_pids = [int(line.strip()) for line in top.splitlines() if line.strip().isdigit()]
    namespace_pids = []
    for pid in host_pids:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("NSpid:"):
                namespace_pids.append(int(line.split()[-1]))
    if not host_pids or not namespace_pids:
        raise ValueError("candidate process identity unavailable")
    return {"container_id": item["Id"], "image": IMAGE, "image_id": item["Image"],
            "entrypoint": item["Config"]["Entrypoint"], "started_at": item["State"]["StartedAt"],
            "host_init_pid": item["State"]["Pid"], "restart_count": item["RestartCount"],
            "running": True, "host_pids": host_pids, "namespace_pids": namespace_pids,
            "captured_at_unix_ns": time.time_ns()}


def summarize(trace):
    if not isinstance(trace, dict) or not isinstance(trace.get("traceEvents"), list):
        raise ValueError("invalid trace envelope")
    kernel_events, runtime_events, names = 0, 0, set()
    for event in trace["traceEvents"]:
        if not isinstance(event, dict) or event.get("ph") != "X":
            continue
        duration = event.get("dur")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            continue
        if event.get("cat") == "kernel":
            kernel_events += 1
            names.add(event.get("name") if isinstance(event.get("name"), str) else "unnamed")
        elif event.get("cat") == "cuda_runtime":
            runtime_events += 1
    if kernel_events == 0 or runtime_events == 0:
        raise ValueError("CUDA kernel and runtime events both required")
    return {"cuda_kernel_event_count": kernel_events,
            "distinct_cuda_kernel_names": len(names), "cuda_runtime_event_count": runtime_events,
            "cuda_execution_verified": True, "gpu_utilization_measured": False,
            "end_to_end_acceleration_proven": False, "semantic_quality_proven": False}


def verify_binding(trace, receipt, before, after, arm, trace_mtime_ns):
    keys = ("container_id", "image", "image_id", "entrypoint", "started_at", "host_init_pid", "restart_count")
    if (any(before.get(key) != after.get(key) for key in keys)
            or before.get("image") != IMAGE or before.get("image_id") != CONFIG_ID
            or before.get("entrypoint") != ["/opt/nim/start_server.sh"]
            or before.get("restart_count") != 0
            or before.get("running") is not True or after.get("running") is not True
            or type(before.get("host_init_pid")) is not int or before["host_init_pid"] <= 0
            or not re.fullmatch(r"[a-f0-9]{64}", before.get("container_id", ""))):
        raise ValueError("NIM process identity not bound")
    if (arm.get("http_status") != 200 or arm.get("trace_files_before") != []
            or arm.get("request") != {"output_dir": "/evidence", "num_steps": 8,
                                      "start_step": 0, "activities": ["CPU", "GPU"]}):
        raise ValueError("fresh bounded profiler arm receipt required")
    if (receipt.get("accepted_interface") is not True or receipt.get("model") != MODEL
            or receipt.get("inference_requests_sent") != 1 or receipt.get("automatic_retries") != 0
            or receipt.get("finish_reason") != "stop"):
        raise ValueError("one completed original public request required")
    if any(not re.fullmatch(r"[a-f0-9]{64}", receipt.get(key, ""))
           for key in ("request_sha256", "response_sha256")):
        raise ValueError("original request and response hashes required")
    times = (before.get("captured_at_unix_ns"), arm.get("finished_at_unix_ns"),
             receipt.get("request_started_at_unix_ns"), receipt.get("request_finished_at_unix_ns"),
             after.get("captured_at_unix_ns"))
    if (any(type(value) is not int for value in times) or list(times) != sorted(times)
            or type(trace_mtime_ns) is not int or not times[2] <= trace_mtime_ns <= times[3]):
        raise ValueError("profiler and request time window not bound")
    process_ids = set(before.get("host_pids", []) + before.get("namespace_pids", []))
    process_ids &= set(after.get("host_pids", []) + after.get("namespace_pids", []))
    trace_ids = {event.get("pid") for event in trace["traceEvents"]
                 if isinstance(event, dict) and event.get("cat") == "cpu_op"}
    if not process_ids.intersection(trace_ids):
        raise ValueError("trace CPU process does not match the candidate")
    return {"container_id": before["container_id"], "image": IMAGE, "image_id": CONFIG_ID,
            "entrypoint": before["entrypoint"], "started_at": before["started_at"],
            "candidate_process_bound": True, "request_time_window_bound": True,
            "trace_mtime_unix_ns": trace_mtime_ns, "request_sha256": receipt["request_sha256"],
            "response_sha256": receipt["response_sha256"], "profile_step_limit": 8,
            "full_request_covered": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-runtime", action="store_true")
    parser.add_argument("--container", default=CONTAINER)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--acceptance-receipt", type=Path)
    parser.add_argument("--container-before", type=Path)
    parser.add_argument("--container-after", type=Path)
    parser.add_argument("--profile-arm", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.capture_runtime:
        data = capture_identity(args.container)
    else:
        if any(value is None for value in (args.trace, args.acceptance_receipt, args.container_before,
                                          args.container_after, args.profile_arm)):
            parser.error("trace, original request receipt, both identities and profiler arm are required")
        receipt = json.loads(args.acceptance_receipt.read_bytes())
        claim = json.loads((args.acceptance_receipt.parent / "claimed.json").read_bytes())
        if claim.get("request") != REQUEST:
            raise ValueError("approved bounded public request required")
        raw_request = json.dumps(claim["request"], ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode()
        raw_response = (args.acceptance_receipt.parent / "response.raw.json").read_bytes()
        if (hashlib.sha256(raw_request).hexdigest() != receipt.get("request_sha256")
                or hashlib.sha256(raw_response).hexdigest() != receipt.get("response_sha256")):
            raise ValueError("original request or response hash mismatch")
        raw = args.trace.read_bytes()
        trace = json.loads(gzip.decompress(raw) if args.trace.suffix == ".gz" else raw)
        data = summarize(trace)
        data.update(verify_binding(trace, receipt, json.loads(args.container_before.read_bytes()),
                                   json.loads(args.container_after.read_bytes()),
                                   json.loads(args.profile_arm.read_bytes()), args.trace.stat().st_mtime_ns))
        data.update({"trace_bytes": len(raw), "trace_sha256": hashlib.sha256(raw).hexdigest(),
                     "capture_kind": "nim-sglang-bounded-8-executor-steps", "raw_trace_private": True,
                     "acceptance_receipt_sha256": hashlib.sha256(args.acceptance_receipt.read_bytes()).hexdigest()})
    data["verifier_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    serialized = json.dumps(data, sort_keys=True, allow_nan=False).encode() + b"\n"
    with args.output.open("xb") as stream: stream.write(serialized)
    print(json.dumps({"evidence_written": True, "sha256": hashlib.sha256(serialized).hexdigest(),
                      "cuda_execution_verified": data.get("cuda_execution_verified", False)}))


if __name__ == "__main__": main()
