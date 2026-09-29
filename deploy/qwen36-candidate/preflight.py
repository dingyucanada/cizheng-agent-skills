"""Read-only guards for the fixed Qwen3.6 NVFP4 coexistence experiment.

This does not allocate a GPU, create a container, or contact a model hub.
The five existing services must all be healthy. A failed guard is recorded.
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

ROOT = Path(__file__).resolve().parent
IMAGE = "tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9"
CONFIG_ID = "sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef"
IDENTITY_SHA256 = "5928d4659a1059f54776611e8dfe2dc306d19a807e88f7f53642a418fe848120"
PROFILE_SHA256 = "2e4f0d0b02e4769be5b92487cbba4a9bb4d2f346e18602de31e8fa108ece571e"
MIN_AVAILABLE_BYTES = 44 * 1024**3
MIN_BUFFER_BYTES = 16 * 1024**3
OVERHEAD_ESTIMATE_BYTES = 5 * 1024**3
CGROUP_LIMIT_BYTES = 40 * 1024**3
STATIC_FRACTION = 0.58
CONTEXT_LIMIT = 24576
BASELINE_ENDPOINTS = (
    "http://127.0.0.1:8005/health",
    "http://127.0.0.1:8780/api/status",
    "http://127.0.0.1:8006/health",
    "http://127.0.0.1:8007/health",
    "http://127.0.0.1:8003/v1/health/ready",
)


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
            or item.get("Os") != "linux" or IMAGE not in item.get("RepoDigests", [])):
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
        raise ValueError("at least 44 GiB MemAvailable required")
    weights = sum(f["bytes"] for f in identity["files"]
                  if re.fullmatch(r"model-\d{5}-of-\d{5}\.safetensors", f["name"]))
    peak_estimate = weights + OVERHEAD_ESTIMATE_BYTES
    result = {
        "memory_bytes": memory, "minimum_available_bytes": MIN_AVAILABLE_BYTES,
        "raw_weight_bytes": weights, "runtime_overhead_estimate_bytes": OVERHEAD_ESTIMATE_BYTES,
        "peak_estimate_bytes": peak_estimate, "estimate_is_measured": False,
        "minimum_system_buffer_bytes": MIN_BUFFER_BYTES,
        "estimated_remaining_system_bytes": value - peak_estimate,
        "cgroup_limit_bytes": CGROUP_LIMIT_BYTES, "static_fraction": static_fraction,
        "static_budget_estimate_bytes": int(value * static_fraction),
        "fraction_denominator": "pre_model_load_available_memory; integrated GPU uses system MemAvailable",
        "legacy_profiles": [{"static_fraction": f, "static_budget_estimate_bytes": int(value * f),
                             "below_raw_weights": value * f <= weights}
                            for f in (0.24, 0.27)],
    }
    if peak_estimate > CGROUP_LIMIT_BYTES or value - peak_estimate < MIN_BUFFER_BYTES:
        raise BudgetRejected("estimated weights plus 5 GiB overhead must preserve 16 GiB system buffer and fit 40 GiB", result)
    if not 0 < static_fraction < 1 or value * static_fraction <= weights:
        raise BudgetRejected("static fraction cannot fit raw weights before any KV/Mamba pool; rejected before GPU loading", result)
    return result


def fp8_full_attention_kv_estimate(config, token_capacity=CONTEXT_LIMIT):
    """Raw K/V payload only; not a GPU peak or complete cache estimate."""
    text = config["text_config"]
    layers = text["layer_types"]
    full_layers = layers.count("full_attention")
    kv_heads = text["num_key_value_heads"]
    head_dim = text["head_dim"]
    raw_bytes = token_capacity * full_layers * 2 * kv_heads * head_dim
    return {"token_capacity": token_capacity, "full_attention_layers": full_layers,
            "linear_attention_layers": layers.count("linear_attention"),
            "kv_heads": kv_heads, "head_dimension": head_dim,
            "kv_tensors": 2, "fp8_bytes_per_element": 1,
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
        verified.append({"name": name, "bytes": expected["bytes"], "sha256": sha256})
    config = json.loads((directory / "config.json").read_text())
    quant = json.loads((directory / "hf_quant_config.json").read_text())["quantization"]
    if (config.get("architectures") != ["Qwen3_5MoeForConditionalGeneration"]
            or config.get("model_type") != "qwen3_5_moe"
            or quant.get("quant_algo") != "MIXED_PRECISION"
            or quant.get("kv_cache_quant_algo") != "FP8"
            or len(quant.get("quantized_layers", {})) != 291):
        raise ValueError("fixed multimodal MoE/mixed precision metadata mismatch")
    return {"model": identity["model"], "revision": identity["revision"],
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "file_count": len(verified), "total_file_bytes": identity["total_file_bytes"],
            "all_files_verified": True, "files": verified,
            "fp8_full_attention_kv_estimate": fp8_full_attention_kv_estimate(config)}


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    entries = []
    for endpoint in BASELINE_ENDPOINTS:
        with opener.open(endpoint, timeout=6) as response:
            raw = response.read(1024**2 + 1)
            if response.status != 200 or len(raw) > 1024**2:
                raise ValueError("existing service health not successful")
        if endpoint.endswith("/v1/health/ready") and json.loads(raw).get("ready") is not True:
            raise ValueError("existing retriever not ready")
        entries.append({"endpoint": endpoint, "status": 200,
                        "body_sha256": hashlib.sha256(raw).hexdigest()})
    return entries


def require_free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8008))


def require_cpu_report(path):
    result = json.loads(path.read_bytes())
    if (result.get("cpu_preflight") != "passed" or result.get("gpu_initialized") is not False
            or result.get("launch_profile_sha256") != PROFILE_SHA256
            or result.get("requested_context_length") != CONTEXT_LIMIT
            or result.get("requested_max_total_tokens") != CONTEXT_LIMIT
            or result.get("memory_formula_verified") is not True
            or result.get("image_tokens_per_probe") != [256, 256]):
        raise ValueError("exact image CPU compatibility receipt required")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "result": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--model-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guard-only", action="store_true")
    parser.add_argument("--cpu-report", type=Path)
    parser.add_argument("--static-fraction", type=float, default=STATIC_FRACTION,
                        choices=(0.24, 0.27, STATIC_FRACTION), help="0.24/0.27 exist only to record the rejected legacy budget")
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
        summary["launch_profile_sha256"] = PROFILE_SHA256
        summary["requested_context_length"] = CONTEXT_LIMIT
        summary["requested_max_total_tokens"] = CONTEXT_LIMIT
        memory = memory_snapshot()
        summary["memory_bytes"] = memory
        summary["budget"] = budget_summary(memory, identity, args.static_fraction)
        require_free_port()
        image = json.loads(subprocess.run(["docker", "image", "inspect", IMAGE],
                                         capture_output=True, check=True, timeout=20).stdout)[0]
        summary["image"] = require_image(image)
        summary["existing_services"] = health()
        if not args.guard_only:
            summary["model"] = verify_model(args.model_directory, args.model_receipt.read_bytes(), identity)
            # Hashing 23 GB may change available memory: repeat all live guards.
            summary["budget_after_hash"] = budget_summary(memory_snapshot(), identity, args.static_fraction)
            summary["existing_services_after_hash"] = health()
            require_free_port()
        if args.cpu_report:
            summary["cpu_compatibility"] = require_cpu_report(args.cpu_report)
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
