"""Read-only guards for the fixed Qwen3.8 NVFP4 coexistence experiment.

This does not allocate a GPU, create a container, or contact a model hub.
Four business services must remain healthy with the Retriever's original
32 GiB guard. The exact historical 4B experiment must already be stopped by
the coordinator. This script never stops or restores any service.
"""
import argparse
import hashlib
import json
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from loader_contract import require_serial_options

ROOT = Path(__file__).resolve().parent
IMAGE = "tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9"
CONFIG_ID = "sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef"
IDENTITY_SHA256 = "5b0571be04c9b70aeec7be22500866f4a6eb829fb39be8b2e149351b298d35ef"
PROFILE_SHA256 = "70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04"
RESOURCE_POLICY_SHA256 = "a18e4234fbbf7ec2dc60fe4a106a22649a044eb8f94c437ee6c9c93a423eb6f9"
CPU_COMPATIBILITY_SHA256 = "622dd9d519dc00a89aaa0e8130f9af30f12b2dda90f27d372dbb3471853de88c"
CPU_SOURCE_SHA256 = "c8b04ac63ede1fa7f27520e69249c4911eb2696191a0b0571c23f794f76cb40b"
ENTRYPOINT_SHA256 = "bc8c7cca428dc1eb843752b518df7e8b5ecad747e315a764f9fb5512137f2e26"
LOADER_CONTRACT_SHA256 = "92c946382d7ca80e5783e8d248b2a10420b2c25ce1085fad9dbc27238690a760"
MIN_AVAILABLE_BYTES = 60 * 1024**3
MIN_BUFFER_BYTES = 34 * 1024**3
RETRIEVER_GUARD_BYTES = 32 * 1024**3
RETRIEVER_WATCHDOG_SECONDS = 2
OVERHEAD_ESTIMATE_BYTES = 5 * 1024**3
CGROUP_LIMIT_BYTES = 40 * 1024**3
STATIC_FRACTION = 0.58
CONTEXT_LIMIT = 24576
BASELINE_ENDPOINTS = (
    "http://127.0.0.1:8005/health",
    "http://127.0.0.1:8780/api/status",
    "http://127.0.0.1:8006/health",
    "http://127.0.0.1:8003/v1/health/ready",
)
RETIRED_NIM_NAME = "cizheng-nim-qwen4b-v09-attempt-04"
RETIRED_NIM_ID = "1c963f41f4c1e844de77113eaa26f1b61c9e994a25bdd982c442a447e5d4acc5"


class BudgetRejected(ValueError):
    def __init__(self, message, budget):
        super().__init__(message)
        self.budget = budget


def read_pinned_json(path, expected_sha256):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("candidate identity or launch profile changed")
    return json.loads(raw)


def require_image(item):
    if (item.get("Id") != CONFIG_ID or item.get("Architecture") != "arm64"
            or item.get("Os") != "linux" or IMAGE not in item.get("RepoDigests", [])
            or item.get("Config", {}).get("Entrypoint") != ["/opt/nim/start_server.sh"]):
        raise ValueError("already-installed pinned ARM64 NIM image required")
    result = {key: item.get(key) for key in ("Id", "RepoDigests", "Architecture", "Os", "Size")}
    result["entrypoint"] = item.get("Config", {}).get("Entrypoint")
    return result


def memory_snapshot():
    return {line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:"))}


def budget_summary(memory, identity, static_fraction=STATIC_FRACTION):
    value = memory.get("MemAvailable")
    if type(value) is not int or value < MIN_AVAILABLE_BYTES:
        raise ValueError("at least 60 GiB MemAvailable required after coordinator-owned 4B rotation")
    weights = sum(f["bytes"] for f in identity["files"]
                  if re.fullmatch(r"model-\d{5}-of-\d{5}\.safetensors", f["name"]))
    peak_estimate = weights + OVERHEAD_ESTIMATE_BYTES
    result = {
        "memory_bytes": memory, "minimum_available_bytes": MIN_AVAILABLE_BYTES,
        "raw_weight_bytes": weights, "runtime_overhead_estimate_bytes": OVERHEAD_ESTIMATE_BYTES,
        "peak_estimate_bytes": peak_estimate, "estimate_is_measured": False,
        "runtime_overhead_includes_bf16_kv": True,
        "minimum_system_buffer_bytes": MIN_BUFFER_BYTES,
        "retriever_guard_bytes": RETRIEVER_GUARD_BYTES,
        "retriever_guard_extra_buffer_bytes": 2 * 1024**3,
        "estimated_remaining_system_bytes": value - peak_estimate,
        "cgroup_limit_bytes": CGROUP_LIMIT_BYTES, "static_fraction": static_fraction,
        "static_budget_estimate_bytes": int(value * static_fraction),
        "fraction_denominator": "pre_model_load_available_memory; integrated GPU uses system MemAvailable",
        "static_fraction_is_not_a_system_reservation": True,
        "token_pool_cap": CONTEXT_LIMIT,
        "gpu_peak_and_remaining_floor_verified": False,
        "legacy_profiles": [{"static_fraction": f, "static_budget_estimate_bytes": int(value * f),
                             "below_raw_weights": value * f <= weights}
                            for f in (0.24, 0.27)],
    }
    if peak_estimate > CGROUP_LIMIT_BYTES or value - peak_estimate < MIN_BUFFER_BYTES:
        raise BudgetRejected("estimated weights plus 5 GiB total overhead must preserve 34 GiB system buffer and fit 40 GiB; KV is included", result)
    if not 0 < static_fraction < 1 or value * static_fraction <= weights:
        raise BudgetRejected("static fraction cannot fit raw weights before any KV/Mamba pool; rejected before GPU loading", result)
    return result


def bf16_full_attention_kv_estimate(config, token_capacity=CONTEXT_LIMIT):
    """Raw K/V payload only; not a GPU peak or complete cache estimate."""
    text = config["text_config"]
    layers = text["layer_types"]
    full_layers = layers.count("full_attention")
    kv_heads = text["num_key_value_heads"]
    head_dim = text["head_dim"]
    raw_bytes = token_capacity * full_layers * 2 * kv_heads * head_dim * 2
    return {"token_capacity": token_capacity, "full_attention_layers": full_layers,
            "linear_attention_layers": layers.count("linear_attention"),
            "kv_heads": kv_heads, "head_dimension": head_dim,
            "kv_tensors": 2, "bf16_bytes_per_element": 2,
            "raw_kv_payload_bytes": raw_bytes, "is_measured": False,
            "excluded": ["GDN state", "scales", "pool/page bookkeeping", "vision encoder", "temporary buffers"],
            "budget_treatment": "explanatory component; 5 GiB assumed total runtime overhead is unchanged"}


def verify_model(directory, receipt_raw, identity):
    receipt = json.loads(receipt_raw)
    if (receipt.get("model") != identity["model"] or receipt.get("revision") != identity["revision"]
            or receipt.get("all_files_verified") is not True
            or receipt.get("file_count") != identity["file_count"]
            or receipt.get("total_file_bytes") != identity["total_file_bytes"]):
        raise ValueError("complete receipt for the fixed official revision required")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != identity["file_count"]:
        raise ValueError("complete checkpoint file list required")
    entries = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or item["name"] in entries:
            raise ValueError("unique named checkpoint files required")
        entries[item["name"]] = item
    if set(entries) != {f["name"] for f in identity["files"]}:
        raise ValueError("checkpoint file list differs from official fixed revision")
    directory = Path(directory).resolve(strict=True)
    verified = []
    for expected in identity["files"]:
        name = expected["name"]
        item = entries[name]
        path = directory / name
        if (Path(name).name != name or name in (".", "..") or path.is_symlink()
                or not path.is_file() or path.resolve(strict=True).parent != directory
                or type(item.get("bytes")) is not int or item["bytes"] != expected["bytes"]
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))):
            raise ValueError("flat regular checkpoint files with exact official sizes required")
        before = path.stat()
        if before.st_size != expected["bytes"]:
            raise ValueError("checkpoint size mismatch: " + name)
        digest = hashlib.sha256()
        git = hashlib.sha1(("blob " + str(expected["bytes"]) + "\0").encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(block)
                git.update(block)
        after = path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ValueError("checkpoint changed during verification: " + name)
        sha256 = digest.hexdigest()
        if sha256 != item["sha256"]:
            raise ValueError("receipt SHA256 mismatch: " + name)
        if expected.get("lfs_sha256"):
            if sha256 != expected["lfs_sha256"]:
                raise ValueError("official LFS SHA256 mismatch: " + name)
        elif git.hexdigest() != expected["git_blob_sha1"]:
            raise ValueError("official Git blob SHA1 mismatch: " + name)
        verified.append({"name": name, "bytes": expected["bytes"], "sha256": sha256,
                         "stat": {key: getattr(after, key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns")}})
    config = json.loads((directory / "config.json").read_text())
    quant = json.loads((directory / "hf_quant_config.json").read_text())["quantization"]
    if (config.get("architectures") != ["Qwen3_5ForConditionalGeneration"]
            or config.get("model_type") != "qwen3_5"
            or quant.get("quant_algo") != "MIXED_PRECISION"
            or quant.get("kv_cache_quant_algo") is not None
            or len(quant.get("quantized_layers", {})) != 401):
        raise ValueError("fixed multimodal dense/mixed precision metadata mismatch")
    return {"model": identity["model"], "revision": identity["revision"],
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "file_count": len(verified), "total_file_bytes": identity["total_file_bytes"],
            "all_files_verified": True, "files": verified,
            "bf16_full_attention_kv_estimate": bf16_full_attention_kv_estimate(config)}


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    entries = []
    for endpoint in BASELINE_ENDPOINTS:
        with opener.open(endpoint, timeout=6) as response:
            raw = response.read(1024**2 + 1)
            if response.status != 200 or len(raw) > 1024**2:
                raise ValueError("existing service health not successful")
        entry = {"endpoint": endpoint, "status": 200,
                 "body_sha256": hashlib.sha256(raw).hexdigest()}
        if endpoint.endswith("/v1/health/ready"):
            state = json.loads(raw)
            if (state.get("ready") is not True
                    or state.get("minimum_remaining_memory_kib") != RETRIEVER_GUARD_BYTES // 1024
                    or state.get("remaining_memory_watchdog_seconds") != RETRIEVER_WATCHDOG_SECONDS):
                raise ValueError("existing Retriever ready with unchanged 32 GiB / 2-second guard required")
            entry["minimum_remaining_memory_kib"] = state["minimum_remaining_memory_kib"]
            entry["remaining_memory_watchdog_seconds"] = state["remaining_memory_watchdog_seconds"]
        entries.append(entry)
    return entries


def require_resource_policy():
    policy = read_pinned_json(ROOT / "resource_policy.json", RESOURCE_POLICY_SHA256)
    if (policy.get("minimum_available_bytes") != MIN_AVAILABLE_BYTES
            or policy.get("minimum_system_buffer_bytes") != MIN_BUFFER_BYTES
            or policy.get("runtime_overhead_estimate_bytes") != OVERHEAD_ESTIMATE_BYTES
            or policy.get("runtime_overhead_includes_bf16_kv") is not True
            or policy.get("cli_profile_sha256") != PROFILE_SHA256
            or tuple(policy.get("baseline_endpoints", [])) != BASELINE_ENDPOINTS
            or policy.get("retired_nim", {}).get("name") != RETIRED_NIM_NAME
            or policy.get("retired_nim", {}).get("container_id") != RETIRED_NIM_ID):
        raise ValueError("fixed v11 coexistence resource policy required")
    return policy


def require_retired_nim():
    """Inspect one pinned historical container. No caller-selectable name/ID."""
    raw = subprocess.run(["docker", "container", "inspect", RETIRED_NIM_ID],
                         capture_output=True, check=True, timeout=20).stdout
    items = json.loads(raw)
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError("one exact stopped historical 4B container required")
    item = items[0]
    config = item.get("Config", {})
    state = item.get("State", {})
    environment = config.get("Env", [])
    if (item.get("Id") != RETIRED_NIM_ID or item.get("Name") != "/" + RETIRED_NIM_NAME
            or item.get("Image") != CONFIG_ID or config.get("Image") != IMAGE
            or config.get("Entrypoint") != ["/opt/nim/start_server.sh"]
            or "NIM_MODEL_PATH=/models/qwen3-4b" not in environment
            or "NIM_SERVED_MODEL_NAME=Qwen3-4B-Instruct-2507" not in environment
            or state.get("Running") is not False or state.get("Status") != "exited"
            or state.get("Paused") is not False or state.get("Restarting") is not False
            or state.get("Dead") is not False or state.get("Pid") != 0
            or item.get("HostConfig", {}).get("PortBindings") != {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8007"}]}):
        raise ValueError("exact owned 8007 4B experiment must already be stopped; no service is stopped automatically")
    # A different replacement process on 8007 is also forbidden.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8007))
    return {"container_id": item["Id"], "name": item["Name"], "image_id": item["Image"],
            "image": config["Image"], "running": False, "status": state["Status"],
            "exit_code": state.get("ExitCode"), "finished_at": state.get("FinishedAt"),
            "port_8007_free": True, "inspect_sha256": hashlib.sha256(raw).hexdigest(),
            "stop_was_performed_by_this_script": False}


def require_free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8009))


def require_cpu_compatibility(path, host_path, container_path, identity):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CPU_COMPATIBILITY_SHA256:
        raise ValueError("original fixed 27B CPU compatibility receipt SHA256 required")
    result = json.loads(raw)
    if (result.get("cpu_compatibility") != "passed" or result.get("gpu_requested") is not False
            or result.get("model_weights_loaded") is not False
            or result.get("model") != identity["model"] or result.get("revision") != identity["revision"]
            or result.get("mixed_quantization", {}).get("kv_cache_quant_algo") is not None
            or result.get("mixed_quantization", {}).get("quantized_layers") != 401
            or result.get("processor", {}).get("image_tokens_per_probe") != [256, 256]):
        raise ValueError("fixed dense model CPU result mismatch")
    host_raw = host_path.read_bytes(); host = json.loads(host_raw)
    container_raw = container_path.read_bytes(); container = json.loads(container_raw)[0]
    if (host.get("image") != IMAGE or host.get("image_id") != CONFIG_ID
            or host.get("architecture") != "arm64"
            or host.get("source_sha256", {}).get("cpu_compatibility.py") != CPU_SOURCE_SHA256
            or container.get("Image") != CONFIG_ID
            or container.get("Config", {}).get("Image") != IMAGE
            or container.get("State", {}).get("ExitCode") != 0
            or container.get("State", {}).get("Running") is not False
            or container.get("HostConfig", {}).get("NetworkMode") != "none"
            or container.get("HostConfig", {}).get("Memory") != 4 * 1024**3
            or container.get("HostConfig", {}).get("MemorySwap") != 4 * 1024**3
            or container.get("HostConfig", {}).get("Devices") != []
            or container.get("HostConfig", {}).get("DeviceRequests")):
        raise ValueError("original fixed-image no-GPU CPU container metadata required")
    environment = container["Config"].get("Env", [])
    if "CUDA_VISIBLE_DEVICES=" not in environment or "NVIDIA_VISIBLE_DEVICES=void" not in environment:
        raise ValueError("CPU probe GPU isolation metadata missing")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "host_sha256": hashlib.sha256(host_raw).hexdigest(),
            "container_sha256": hashlib.sha256(container_raw).hexdigest(), "result": result}


def require_cpu_profile_report(path):
    result = json.loads(path.read_bytes())
    require_serial_options(result.get("loader_extra_config"))
    if (result.get("cpu_preflight") != "passed" or result.get("gpu_initialized") is not False
            or result.get("launch_profile_sha256") != PROFILE_SHA256
            or result.get("original_nim_entrypoint_sha256") != ENTRYPOINT_SHA256
            or result.get("original_cpu_compatibility_sha256") != CPU_COMPATIBILITY_SHA256
            or result.get("requested_context_length") != CONTEXT_LIMIT
            or result.get("requested_max_total_tokens") != CONTEXT_LIMIT
            or result.get("memory_formula_verified") is not True
            or result.get("kv_cache_argument") != "auto"
            or result.get("kv_cache_expected_dtype") != "bfloat16"
            or result.get("loader_extra_config") != {"enable_multithread_load": False}
            or result.get("loader_contract_script_sha256") != LOADER_CONTRACT_SHA256
            or result.get("loader_selection_verified") is not True
            or result.get("serial_loader_lazy_reads_verified") is not True
            or result.get("image_tokens_per_probe") != [256, 256]):
        raise ValueError("exact image and launch profile CPU receipt required")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "result": result}


def require_verified_checkpoint(path, directory, identity):
    result = json.loads(path.read_bytes())
    model = result.get("model", {})
    if (result.get("preflight") != "passed" or result.get("guard_only") is not False
            or result.get("launch_profile_sha256") != PROFILE_SHA256
            or result.get("resource_policy_sha256") != RESOURCE_POLICY_SHA256
            or model.get("model") != identity["model"] or model.get("revision") != identity["revision"]
            or model.get("all_files_verified") is not True or model.get("file_count") != 19
            or model.get("total_file_bytes") != identity["total_file_bytes"]):
        raise ValueError("preceding complete fixed-checkpoint verification required")
    expected_names = {item["name"] for item in identity["files"]}
    if len(model.get("files", [])) != 19 or {item["name"] for item in model["files"]} != expected_names:
        raise ValueError("preceding fixed-checkpoint file set differs")
    for item in model["files"]:
        current = directory / item["name"]
        if current.is_symlink() or not current.is_file():
            raise ValueError("checkpoint changed after complete verification")
        if {key: getattr(current.stat(), key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns")} != item.get("stat"):
            raise ValueError("checkpoint changed after complete verification")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "file_count": 19,
            "unchanged_since_complete_hash": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--model-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guard-only", action="store_true")
    parser.add_argument("--cpu-compatibility-report", type=Path, required=True)
    parser.add_argument("--cpu-host-report", type=Path, required=True)
    parser.add_argument("--cpu-container-report", type=Path, required=True)
    parser.add_argument("--cpu-profile-report", type=Path)
    parser.add_argument("--verified-report", type=Path)
    args = parser.parse_args()
    # Require a new receipt path before checking anything; do not overwrite evidence.
    if args.output.exists():
        raise FileExistsError("fresh preflight output required")
    started = time.monotonic()
    summary = {"preflight": "failed", "gpu_model_requested": False,
               "production_modified": False, "guard_only": args.guard_only}
    try:
        identity = read_pinned_json(ROOT / "expected_identity.json", IDENTITY_SHA256)
        read_pinned_json(ROOT / "launch_profile.json", PROFILE_SHA256)
        summary["resource_policy"] = require_resource_policy()
        summary["resource_policy_sha256"] = RESOURCE_POLICY_SHA256
        summary["launch_profile_sha256"] = PROFILE_SHA256
        summary["requested_context_length"] = CONTEXT_LIMIT
        summary["requested_max_total_tokens"] = CONTEXT_LIMIT
        memory = memory_snapshot()
        summary["memory_bytes"] = memory
        summary["budget"] = budget_summary(memory, identity)
        require_free_port()
        image = json.loads(subprocess.run(["docker", "image", "inspect", IMAGE],
                                         capture_output=True, check=True, timeout=20).stdout)[0]
        summary["image"] = require_image(image)
        summary["retired_nim"] = require_retired_nim()
        summary["existing_services"] = health()
        summary["cpu_compatibility"] = require_cpu_compatibility(
            args.cpu_compatibility_report, args.cpu_host_report, args.cpu_container_report, identity)
        if not args.guard_only:
            summary["model"] = verify_model(args.model_directory, args.model_receipt.read_bytes(), identity)
            # Hashing 22 GB may change available memory: repeat all live guards.
            summary["budget_after_hash"] = budget_summary(memory_snapshot(), identity)
            summary["existing_services_after_hash"] = health()
            summary["retired_nim_after_hash"] = require_retired_nim()
            require_free_port()
        if args.cpu_profile_report:
            summary["cpu_launch_profile"] = require_cpu_profile_report(args.cpu_profile_report)
        if args.guard_only:
            if not args.verified_report or not args.cpu_profile_report:
                raise ValueError("immediate guard requires complete checkpoint and CPU profile receipts")
            summary["checkpoint_unchanged"] = require_verified_checkpoint(args.verified_report, args.model_directory, identity)
        summary["preflight"] = "passed"
    except Exception as exc:
        summary["error_type"] = type(exc).__name__
        if isinstance(exc, BudgetRejected):
            summary["budget"] = exc.budget
        # Errors involve only public model identities, local health and resources.
        summary["error"] = str(exc)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    raw = (json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n").encode()
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"preflight": summary["preflight"], "sha256": hashlib.sha256(raw).hexdigest(),
                      "error": summary.get("error")}, ensure_ascii=False))
    return 0 if summary["preflight"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
