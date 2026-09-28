"""Verify real CUDA events from a private candidate profiler trace; export counts only."""
import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path

IMAGE = "nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965"
CONTAINER = "cizheng-trt-qwen4b"
TRACE = Path("integration-evidence/trt-deploy/profiles/first-text.trace.json")


def capture_identity():
    item = json.loads(subprocess.run(["docker", "inspect", CONTAINER],
                                    capture_output=True, text=True, check=True).stdout)[0]
    assert item["Config"]["Image"] == IMAGE and item["State"]["Running"] is True
    top = subprocess.run(["docker", "top", CONTAINER, "-o", "pid"],
                         capture_output=True, text=True, check=True).stdout
    host_pids = [int(line.strip()) for line in top.splitlines() if line.strip().isdigit()]
    assert host_pids
    namespace_pids = []
    for pid in host_pids:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("NSpid:"):
                namespace_pids.append(int(line.split()[-1]))
    log = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, check=True)
    text = (log.stdout + log.stderr).decode(errors="replace")
    return {"container_id": item["Id"], "image": item["Config"]["Image"],
            "image_id": item["Image"], "started_at": item["State"]["StartedAt"],
            "host_init_pid": item["State"]["Pid"], "restart_count": item["RestartCount"],
            "running": item["State"]["Running"], "host_pids": host_pids,
            "namespace_pids": namespace_pids, "captured_at_unix_ns": time.time_ns(),
            "profile_started_zero": "Profiling started at iteration 0." in text,
            "profile_stopped_eight": "Profiling stopped at iteration 8," in text,
            "trace_exists": TRACE.exists()}


def verify_binding(trace, receipt, before, after, trace_mtime_ns):
    keys = ("container_id", "image", "image_id", "started_at", "host_init_pid", "restart_count")
    if (any(before.get(key) != after.get(key) for key in keys)
            or before.get("image") != IMAGE or before.get("restart_count") != 0
            or before.get("running") is not True or after.get("running") is not True
            or type(before.get("host_init_pid")) is not int or before["host_init_pid"] <= 0
            or not re.fullmatch(r"[a-f0-9]{64}", before.get("container_id", ""))
            or before.get("trace_exists") is not False
            or after.get("profile_started_zero") is not True
            or after.get("profile_stopped_eight") is not True):
        raise ValueError("candidate process or profiler identity not bound")
    if any(not re.fullmatch(r"[a-f0-9]{64}", receipt.get(key, ""))
           for key in ("request_sha256", "response_sha256")):
        raise ValueError("original request and response hashes required")
    times = (before.get("captured_at_unix_ns"), receipt.get("request_started_at_unix_ns"),
             receipt.get("request_finished_at_unix_ns"), after.get("captured_at_unix_ns"))
    if (any(type(value) is not int for value in times) or list(times) != sorted(times)
            or not times[1] <= trace_mtime_ns <= times[2]):
        raise ValueError("trace and single request time window not bound")
    process_ids = set(before.get("host_pids", []) + before.get("namespace_pids", []))
    process_ids &= set(after.get("host_pids", []) + after.get("namespace_pids", []))
    trace_ids = {event.get("pid") for event in trace["traceEvents"]
                 if isinstance(event, dict) and event.get("cat") == "cpu_op"}
    if not process_ids.intersection(trace_ids):
        raise ValueError("trace CPU process does not match candidate process")
    return {"container_id": before["container_id"], "image": IMAGE,
            "image_id": before["image_id"], "started_at": before["started_at"],
            "candidate_process_bound": True, "request_time_window_bound": True,
            "trace_mtime_unix_ns": trace_mtime_ns,
            "request_sha256": receipt["request_sha256"],
            "response_sha256": receipt["response_sha256"],
            "full_request_covered": False}


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
            "distinct_cuda_kernel_names": len(names),
            "cuda_runtime_event_count": runtime_events,
            "cuda_execution_verified": True,
            "gpu_utilization_measured": False,
            "end_to_end_acceleration_proven": False,
            "semantic_quality_proven": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-runtime", action="store_true")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--acceptance-receipt", type=Path)
    parser.add_argument("--container-before", type=Path)
    parser.add_argument("--container-after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.capture_runtime:
        identity = capture_identity()
        with args.output.open("x") as stream:json.dump(identity, stream, sort_keys=True)
        print(json.dumps({"runtime_identity_captured": True,
                          "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))
        return
    if any(value is None for value in (args.trace, args.acceptance_receipt, args.container_before, args.container_after)):
        parser.error("trace, request receipt, and both runtime identities are required")
    receipt = json.loads(args.acceptance_receipt.read_bytes())
    if (receipt.get("accepted_interface") is not True
            or receipt.get("model") != "Qwen3-4B-Instruct-2507"
            or receipt.get("inference_requests_sent") != 1
            or receipt.get("automatic_retries") != 0):
        raise ValueError("a successful original single candidate request is required")
    claim = json.loads((args.acceptance_receipt.parent / "claimed.json").read_bytes())
    original_request = json.dumps(claim["request"], ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode()
    original_response = (args.acceptance_receipt.parent / "response.raw.json").read_bytes()
    if (hashlib.sha256(original_request).hexdigest() != receipt.get("request_sha256")
            or hashlib.sha256(original_response).hexdigest() != receipt.get("response_sha256")):
        raise ValueError("request or response content hash mismatch")
    raw = args.trace.read_bytes()
    trace = json.loads(raw)
    summary = summarize(trace)
    summary.update(verify_binding(trace, receipt,
                                  json.loads(args.container_before.read_bytes()),
                                  json.loads(args.container_after.read_bytes()),
                                  args.trace.stat().st_mtime_ns))
    summary.update({"trace_bytes": len(raw), "trace_sha256": hashlib.sha256(raw).hexdigest(),
                    "verifier_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "acceptance_receipt_sha256": hashlib.sha256(args.acceptance_receipt.read_bytes()).hexdigest(),
                    "capture_kind": "pinned-rc13-first-0-through-8-executor-iterations",
                    "raw_trace_private": True})
    serialized = json.dumps(summary, sort_keys=True, allow_nan=False).encode() + b"\n"
    with args.output.open("xb") as stream:
        stream.write(serialized)
    print(serialized.decode().strip())


if __name__ == "__main__":
    main()
