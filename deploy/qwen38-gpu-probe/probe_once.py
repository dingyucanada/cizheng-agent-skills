"""One coordinator-authorized public-image request in the original NIM runtime.

Importing this module does no IO. The explicit operator flag is required before
any Docker/HTTP call. Raw request, response and profiler traces remain private.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

CONTAINER_NAME = "cizheng-nim-qwen38-v14-attempt-04"
CONTAINER_ID = "dccb16dfc75032a1742220a72a0eceef23c01a25e72ea4f64f7b8dcd0581556d"
STARTED_AT = "2026-09-29T10:01:38.393207957Z"
IMAGE = "tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9"
IMAGE_ID = "sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef"
MODEL = "Qwen3.8-27B-NVFP4"
REVISION = "482ca0f3832238542f8f5295dde86b5f22711d80"
PROFILE_SHA256 = "70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04"
NODE_ROOT = Path.home() / "cizheng-next-model27-20260929"
MODEL_VIEW = Path.home() / "cizheng-model-checkpoints/qwen38-rev482ca0f"
OUTPUT_NAME = "gpu-profile-image-01"
PROFILE_NAME = "probe-qwen38-image-01"
MAX_TOKENS = 384
MAX_HTTP_BYTES = 2 * 1024**2
MAX_TRACE_BYTES = 64 * 1024**2
MAX_DECOMPRESSED_TRACE_BYTES = 512 * 1024**2
MIN_BUFFER_BYTES = 34 * 1024**3
PUBLIC_SOURCE = "https://www.metmuseum.org/art/collection/search/48607"
INPUTS = (
    {"name": "photo-1.jpg", "input_id": "photo-1", "bytes": 107321,
     "sha256": "0cafb54b1f5edb156a96bd05a8c507bb500b76bb5f2a423778e306a27868febc"},
    {"name": "photo-2.jpg", "input_id": "photo-2", "bytes": 109880,
     "sha256": "383ae83bba805f8bc8e0b5a0eb7ec1e0fef705447a94e5e4fdb3bc3ca792964f"},
)
SCHEMA = {"type": "object", "properties": {
    "first_visible": {"type": "string", "minLength": 1, "maxLength": 80},
    "second_visible": {"type": "string", "minLength": 1, "maxLength": 80}},
    "required": ["first_visible", "second_visible"], "additionalProperties": False}
BASELINE_ENDPOINTS = ("http://127.0.0.1:8005/health", "http://127.0.0.1:8780/api/status",
                      "http://127.0.0.1:8003/v1/health/ready")


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def write_once(path, raw):
    with path.open("xb") as stream:stream.write(raw)
    return digest(raw)


def write_json(path, value):
    return write_once(path, serialized(value) + b"\n")


def strict_json(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(_):raise ValueError("non-finite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def require_runtime(item):
    config = item.get("Config", {}); state = item.get("State", {}); host = item.get("HostConfig", {})
    if (item.get("Id") != CONTAINER_ID or item.get("Name") != "/" + CONTAINER_NAME
            or item.get("Image") != IMAGE_ID or config.get("Image") != IMAGE
            or config.get("Entrypoint") != ["/opt/nim/start_server.sh"]
            or state.get("Running") is not True or state.get("StartedAt") != STARTED_AT
            or item.get("RestartCount") != 0 or type(state.get("Pid")) is not int or state["Pid"] <= 0
            or host.get("Memory") != 40 * 1024**3 or host.get("MemorySwap") != 40 * 1024**3
            or host.get("PortBindings") != {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8009"}]}
            or "NIM_MODEL_PATH=/models/qwen38" not in config.get("Env", [])
            or "NIM_SERVED_MODEL_NAME=" + MODEL not in config.get("Env", [])):
        raise ValueError("exact started original NIM candidate identity required")
    model = [m for m in item.get("Mounts", []) if m.get("Destination") == "/models/qwen38"]
    profiles = [m for m in item.get("Mounts", []) if m.get("Destination") == "/evidence"]
    if (len(model) != 1 or model[0].get("RW") is not False or model[0].get("Type") != "bind"
            or Path(model[0].get("Source", "")).resolve() != MODEL_VIEW.resolve()
            or len(profiles) != 1 or profiles[0].get("RW") is not True or profiles[0].get("Type") != "bind"):
        raise ValueError("original read-only flat checkpoint and evidence bind required")
    return Path(profiles[0]["Source"])


def capture_identity():
    raw = subprocess.run(["docker", "container", "inspect", CONTAINER_ID],
                         capture_output=True, check=True, timeout=10).stdout
    items = strict_json(raw)
    if not isinstance(items, list) or len(items) != 1:raise ValueError("one exact runtime required")
    item = items[0]; profile_root = require_runtime(item)
    top = subprocess.run(["docker", "top", CONTAINER_ID, "-o", "pid"],
                         capture_output=True, check=True, text=True, timeout=10).stdout
    records = []
    for pid in [int(s) for s in top.splitlines() if s.strip().isdigit()]:
        proc = Path("/proc") / str(pid)
        row = proc.joinpath("stat").read_text(); parts = row[row.rfind(")") + 2:].split()
        namespace = [r for r in proc.joinpath("status").read_text().splitlines() if r.startswith("NSpid:")]
        if len(namespace) != 1:raise ValueError("process namespace identity missing")
        records.append({"host_pid": pid, "start_ticks": int(parts[19]),
                        "namespace_pid": int(namespace[0].split()[-1])})
    if not records or not any(r["host_pid"] == item["State"]["Pid"] for r in records):
        raise ValueError("original init process missing")
    return {"container_id": item["Id"], "name": item["Name"], "image": IMAGE, "image_id": item["Image"],
            "entrypoint": item["Config"]["Entrypoint"], "started_at": item["State"]["StartedAt"],
            "running": True, "host_init_pid": item["State"]["Pid"], "restart_count": item["RestartCount"],
            "processes": records, "profile_root": str(profile_root),
            "captured_at_unix_ns": time.time_ns()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def http(url, data=None, timeout=8):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data is not None else {})
    with opener.open(request, timeout=timeout) as response:raw = response.read(MAX_HTTP_BYTES + 1); status = response.status
    if len(raw) > MAX_HTTP_BYTES:raise ValueError("HTTP metadata/response exceeds bound")
    return status, raw


def health():
    rows = []
    for url in BASELINE_ENDPOINTS:
        status, raw = http(url)
        if status != 200:raise ValueError("retained business service not healthy")
        if url.endswith("/v1/health/ready"):
            value = strict_json(raw)
            if (value.get("ready") is not True or value.get("minimum_remaining_memory_kib") != 33554432
                    or value.get("remaining_memory_watchdog_seconds") != 2):
                raise ValueError("original Retriever 32 GiB / 2-second guard required")
        rows.append({"url": url, "http_status": status, "body_sha256": digest(raw)})
    for url in ("http://127.0.0.1:8009/health", "http://127.0.0.1:8009/v1/models"):
        status, raw = http(url)
        if status != 200:raise ValueError("candidate not ready")
        if url.endswith("/v1/models"):
            if MODEL not in [r.get("id") for r in strict_json(raw).get("data", [])]:raise ValueError("candidate model identity missing")
        rows.append({"url": url, "http_status": status, "body_sha256": digest(raw)})
    memory = {r.split(":", 1)[0]: int(r.split()[1]) * 1024 for r in Path("/proc/meminfo").read_text().splitlines()
              if r.startswith(("MemAvailable:", "SwapTotal:"))}
    if memory.get("MemAvailable", 0) < MIN_BUFFER_BYTES or memory.get("SwapTotal") != 0:
        raise ValueError("unchanged 34 GiB system buffer and no-swap required")
    return {"endpoints": rows, "memory_bytes": memory}


def build_request(input_directory):
    content = [{"type": "text", "text": "分别描述两张照片直接可见的外轮廓、色彩和装饰分区，不判断年代、窑口或真伪。请用简短中文。"}]
    inputs = []
    for expected in INPUTS:
        path = input_directory / expected["name"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"]:
            raise ValueError("fixed regular public image required")
        raw = path.read_bytes()
        if digest(raw) != expected["sha256"]:raise ValueError("public image SHA mismatch")
        inputs.append({k: expected[k] for k in ("input_id", "bytes", "sha256")})
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode()}})
    payload = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": MAX_TOKENS,
               "temperature": 0.1, "chat_template_kwargs": {"enable_thinking": False},
               "response_format": {"type": "json_schema", "json_schema": {
                   "name": "profile_two_public_images", "strict": True, "schema": SCHEMA}}}
    raw = serialized(payload)
    return raw, {"model": MODEL, "input_images": inputs, "request_sha256": digest(raw), "request_bytes": len(raw),
                 "planned_inference_requests": 1, "automatic_retries": 0, "max_tokens": MAX_TOKENS,
                 "public_source": PUBLIC_SOURCE, "expert_validation": False}


def validate_request(raw):
    payload = strict_json(raw)
    if (set(payload) != {"model", "messages", "max_tokens", "temperature", "chat_template_kwargs", "response_format"}
            or payload["model"] != MODEL or payload["max_tokens"] != MAX_TOKENS
            or payload["temperature"] != 0.1 or payload["chat_template_kwargs"] != {"enable_thinking": False}
            or payload["response_format"] != {"type": "json_schema", "json_schema": {
                "name": "profile_two_public_images", "strict": True, "schema": SCHEMA}}
            or len(payload["messages"]) != 1 or payload["messages"][0].get("role") != "user"):
        raise ValueError("original fixed structured request required")
    content = payload["messages"][0].get("content", [])
    if (len(content) != 3 or content[0] != {"type": "text", "text": "分别描述两张照片直接可见的外轮廓、色彩和装饰分区，不判断年代、窑口或真伪。请用简短中文。"}):
        raise ValueError("fixed two public images and visible-only prompt required")
    for entry, expected in zip(content[1:], INPUTS):
        url = entry.get("image_url", {}).get("url", "")
        if entry.get("type") != "image_url" or not url.startswith("data:image/jpeg;base64,"):
            raise ValueError("original image data required")
        image = base64.b64decode(url.split(",", 1)[1], validate=True)
        if len(image) != expected["bytes"] or digest(image) != expected["sha256"]:
            raise ValueError("original public image SHA mismatch")


def profile_control(action):
    if action not in ("start", "stop"):raise ValueError("only original profiler start/stop allowed")
    payload = {"output_dir": "/evidence/" + PROFILE_NAME, "num_steps": 8, "start_step": 0, "activities": ["CPU", "GPU"]} if action == "start" else {}
    code = ('import sys,json,hashlib,urllib.request,urllib.error\n'
            'class NoRedirect(urllib.request.HTTPRedirectHandler):\n'
            ' def redirect_request(self,req,fp,code,msg,headers,newurl):\n'
            '  raise urllib.error.HTTPError(req.full_url,code,"redirect refused",headers,fp)\n'
            'opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())\n'
            f'req=urllib.request.Request("http://127.0.0.1:8001/{action}_profile",data=sys.stdin.buffer.read(),headers={{"Content-Type":"application/json"}})\n'
            'response=opener.open(req,timeout=15); raw=response.read(65537)\n'
            'assert len(raw)<=65536\n'
            'print(json.dumps({"http_status":response.status,"response_sha256":hashlib.sha256(raw).hexdigest()}))')
    result = subprocess.run(["docker", "exec", "-i", CONTAINER_ID, "python3", "-c", code],
                            input=serialized(payload), capture_output=True, check=True, timeout=25)
    value = strict_json(result.stdout)
    if value.get("http_status") != 200 or not is_sha256(value.get("response_sha256")):
        raise ValueError("original backend profiler control failed")
    return {**value, "request": payload, "action": action,
            "interface": "original NIM internal SGLang backend; no external exposure or source export"}


def validate_response(raw, status):
    data = strict_json(raw)
    if status != 200 or data.get("model") != MODEL or len(data.get("choices", [])) != 1:
        raise ValueError("one completed original-model response required")
    choice = data["choices"][0]
    if choice.get("finish_reason") != "stop" or choice.get("message", {}).get("tool_calls"):
        raise ValueError("finish_reason stop required without repair or retry")
    visible = strict_json(choice.get("message", {}).get("content", ""))
    if (not isinstance(visible, dict) or set(visible) != {"first_visible", "second_visible"}
            or any(not isinstance(value, str) or not 1 <= len(value) <= 80 for value in visible.values())):
        raise ValueError("original two-image JSON schema not satisfied")
    usage = data.get("usage", {})
    if (any(type(usage.get(k)) is not int or usage[k] <= 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
            or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
            or usage["completion_tokens"] > MAX_TOKENS):
        raise ValueError("original token usage invalid")
    image_tokens = usage.get("prompt_tokens_details", {}).get("image_tokens")
    if type(image_tokens) is not int or not 0 < image_tokens <= 512:raise ValueError("bounded real image token usage required")
    return {"model": MODEL, "http_status": status, "finish_reason": "stop", "usage": usage,
            "structured_image_output_valid": True, "original_output_repaired": False,
            "expert_validation": False, "semantic_quality_proven": False}


def stable_process_ids(before, after):
    keys = ("container_id", "name", "image", "image_id", "entrypoint", "started_at", "host_init_pid", "restart_count", "profile_root")
    if (any(before.get(k) != after.get(k) for k in keys) or before.get("container_id") != CONTAINER_ID
            or before.get("started_at") != STARTED_AT or before.get("running") is not True or after.get("running") is not True):
        raise ValueError("runtime changed across original request")
    def records(value):
        result = set()
        for row in value.get("processes", []):
            values = tuple(row.get(k) for k in ("host_pid", "start_ticks", "namespace_pid"))
            if any(type(v) is not int or v <= 0 for v in values):raise ValueError("positive process start identity required")
            result.add(values)
        return result
    shared = records(before) & records(after)
    if not any(r[0] == before["host_init_pid"] for r in shared):raise ValueError("original init PID start identity changed")
    return {pid for host, _, namespace in shared for pid in (host, namespace)}


def summarize(trace, process_ids):
    if not isinstance(trace, dict) or not isinstance(trace.get("traceEvents"), list):raise ValueError("invalid trace envelope")
    kernels = []; runtime = []; cpu_pids = set()
    for event in trace["traceEvents"]:
        if not isinstance(event, dict):continue
        if event.get("cat") == "cpu_op":cpu_pids.add(event.get("pid"))
        duration = event.get("dur")
        if event.get("ph") != "X" or type(duration) not in (float, int) or not math.isfinite(duration) or duration <= 0:continue
        if event.get("cat") == "kernel":kernels.append(event)
        if event.get("cat") == "cuda_runtime":runtime.append(event)
    if not kernels or not runtime or not cpu_pids & process_ids:raise ValueError("real CUDA events and candidate CPU process required")
    owned_cpu = cpu_pids & process_ids
    correlations = {e.get("args", {}).get("correlation") for e in runtime if e.get("pid") in owned_cpu}
    correlations = {v for v in correlations if type(v) is int and v >= 0}
    kernel_correlations = {e.get("args", {}).get("correlation") for e in kernels}
    matches = {v for v in kernel_correlations if type(v) is int and v >= 0} & correlations
    if not matches:raise ValueError("CUDA kernels must correlate with candidate-owned CUDA runtime process")
    return {"cuda_kernel_event_count": len(kernels), "cuda_runtime_event_count": len(runtime),
            "distinct_kernel_names": len({e.get("name") for e in kernels}),
            "candidate_kernel_runtime_correlation_count": len(matches), "candidate_process_bound": True,
            "cuda_execution_verified": True, "full_request_covered": False,
            "gpu_utilization_measured": False, "end_to_end_acceleration_proven": False}


def read_trace(path):
    before = path.stat()
    if path.is_symlink() or not path.is_file() or before.st_size > MAX_TRACE_BYTES:raise ValueError("bounded regular private trace required")
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:decoded = stream.read(MAX_DECOMPRESSED_TRACE_BYTES + 1)
    else:decoded = raw
    if len(decoded) > MAX_DECOMPRESSED_TRACE_BYTES:raise ValueError("decompressed trace exceeds bound")
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("trace changed during verification")
    return json.loads(decoded), {"trace_sha256": digest(raw), "trace_bytes": len(raw), "trace_mtime_unix_ns": after.st_mtime_ns}


def verify_binding(request_raw, response_raw, receipt, before, after, arm, trace, trace_metadata):
    if receipt.get("request_sha256") != digest(request_raw) or receipt.get("response_sha256") != digest(response_raw):
        raise ValueError("original request/response hash mismatch")
    validate_request(request_raw)
    response = validate_response(response_raw, receipt.get("http_status"))
    if any(receipt.get(k) != value for k, value in response.items()):
        raise ValueError("receipt cannot repair output or claim professional validation")
    expected_arm = {"output_dir": "/evidence/" + PROFILE_NAME, "num_steps": 8, "start_step": 0, "activities": ["CPU", "GPU"]}
    if (arm.get("request") != expected_arm or arm.get("http_status") != 200
            or arm.get("action") != "start" or not is_sha256(arm.get("response_sha256"))
            or arm.get("trace_files_before") != []):
        raise ValueError("fresh original eight-step profiler arm required")
    if (not is_sha256(trace_metadata.get("trace_sha256")) or type(trace_metadata.get("trace_bytes")) is not int
            or not 0 < trace_metadata["trace_bytes"] <= MAX_TRACE_BYTES):
        raise ValueError("bounded original trace hash and bytes required")
    times = [before.get("captured_at_unix_ns"), arm.get("started_at_unix_ns"), arm.get("finished_at_unix_ns"),
             receipt.get("request_started_at_unix_ns"), receipt.get("request_finished_at_unix_ns"), after.get("captured_at_unix_ns")]
    if (any(type(t) is not int for t in times) or times != sorted(times)
            or not times[3] <= trace_metadata["trace_mtime_unix_ns"] <= times[4]
            or receipt.get("inference_requests_sent") != 1 or receipt.get("automatic_retries") != 0):
        raise ValueError("one request and trace write time window not bound")
    counts = summarize(trace, stable_process_ids(before, after))
    return {**receipt, **counts, **trace_metadata, "container_id": CONTAINER_ID, "started_at": STARTED_AT,
            "image": IMAGE, "image_id": IMAGE_ID, "request_time_window_bound": True,
            "original_nim_entrypoint_preserved": True, "weights_revision": REVISION,
            "launch_profile_sha256": PROFILE_SHA256, "profile_step_limit": 8, "raw_trace_private": True,
            "public_source": PUBLIC_SOURCE,
            "input_images": [{k: row[k] for k in ("input_id", "bytes", "sha256")} for row in INPUTS]}


def run_probe(input_directory, *, operator_authorized):
    if operator_authorized is not True:raise PermissionError("coordinator must confirm ready, exclusive timing and authorize this probe")
    os.umask(0o077)
    output = NODE_ROOT / OUTPUT_NAME
    if output.exists() or output.is_symlink():raise FileExistsError("fresh private probe evidence required; never retry or overwrite")
    before = capture_identity(); profile_root = Path(before["profile_root"]); profiles = profile_root / PROFILE_NAME
    for path in (output, profile_root, input_directory):
        model = MODEL_VIEW.resolve(); other = path.resolve()
        if model == other or model in other.parents or other in model.parents:raise ValueError("probe paths must be disjoint from the model view")
    if profiles.exists() or profiles.is_symlink():raise FileExistsError("fresh profile directory required")
    output.mkdir(mode=0o700)
    profile_attempted = False; requests = 0; phase = "preconditions"
    try:
        write_json(output / "container-before.json", before)
        write_json(output / "health-before.json", health())
        request_raw, request_meta = build_request(input_directory)
        write_once(output / "request.raw.json", request_raw); write_json(output / "request-meta.json", request_meta)
        profiles.mkdir(mode=0o700)
        phase = "profile_arm"; profile_attempted = True; started_arm = time.time_ns()
        arm = profile_control("start")
        arm.update(started_at_unix_ns=started_arm, finished_at_unix_ns=time.time_ns(), trace_files_before=[])
        write_json(output / "profile-arm.json", arm)
        phase = "single_inference"; started = time.time_ns(); clock = time.monotonic(); requests = 1
        status, response_raw = http("http://127.0.0.1:8009/v1/chat/completions", request_raw, timeout=120)
        finished = time.time_ns(); elapsed = time.monotonic() - clock
        write_once(output / "response.raw.json", response_raw)
        response = validate_response(response_raw, status)
        receipt = {**response, "request_started_at_unix_ns": started, "request_finished_at_unix_ns": finished,
                   "elapsed_seconds": elapsed, "request_sha256": digest(request_raw), "response_sha256": digest(response_raw),
                   "inference_requests_sent": requests, "automatic_retries": 0}
        write_json(output / "receipt.json", receipt)
        phase = "trace_binding"; after = capture_identity(); write_json(output / "container-after.json", after)
        write_json(output / "health-after.json", health())
        traces = list(profiles.glob("*.trace.json*"))
        if len(traces) != 1:raise ValueError("exactly one fresh private trace required")
        trace, metadata = read_trace(traces[0])
        write_json(output / "trace-file-meta.json", {**metadata, "private_path": str(traces[0]), "raw_trace_exported": False})
        proof = verify_binding(request_raw, response_raw, receipt, before, after, arm, trace, metadata)
        proof["verifier_source_sha256"] = digest(Path(__file__).read_bytes())
        proof["acceptance_receipt_sha256"] = digest((output / "receipt.json").read_bytes())
        write_json(output / "gpu-proof.json", proof)
        print(serialized(proof).decode())
        return 0
    except Exception as exc:
        cleanup = {"attempted": False, "profile_may_remain_armed": profile_attempted}
        if profile_attempted:
            try:
                stable_process_ids(before, capture_identity())
                cleanup = {"attempted": True, "result": profile_control("stop"), "profile_may_remain_armed": False}
            except Exception as cleanup_error:
                cleanup["failure_type"] = type(cleanup_error).__name__
        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = exc.read(MAX_HTTP_BYTES + 1)
                if len(body) <= MAX_HTTP_BYTES:write_once(output / "http-error.raw", body)
            except Exception as body_error:
                cleanup["http_error_body_failure_type"] = type(body_error).__name__
        write_json(output / "failure.json", {"phase": phase, "failure_type": type(exc).__name__,
            "failure_reason": str(exc)[:300], "inference_requests_sent": requests, "automatic_retries": 0,
            "profile_cleanup": cleanup, "raw_trace_private": True, "historical_services_modified": False,
            "gpu_proof_published": False})
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--operator-authorized", action="store_true")
    args = parser.parse_args()
    return run_probe(args.input_directory, operator_authorized=args.operator_authorized)


if __name__ == "__main__":raise SystemExit(main())
