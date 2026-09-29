"""Read-only guards for the pinned, official China-distributed Spark NIM candidate."""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

IMAGE = "tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9"
CONFIG_ID = "sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_RECEIPT_SHA256 = "a41c5affd0d9dcc418f5d7aed2071c146347d3c4f676ee46a02b3a8ee0cba694"
MIN_AVAILABLE_BYTES = 32 * 1024**3
BASELINE_ENDPOINTS = (
    "http://127.0.0.1:8005/health", "http://127.0.0.1:8780/api/status",
    "http://127.0.0.1:8006/health", "http://127.0.0.1:8003/v1/health/ready",
)


def require_image(item):
    if (item.get("Id") != CONFIG_ID or item.get("Architecture") != "arm64"
            or item.get("Os") != "linux" or IMAGE not in item.get("RepoDigests", [])):
        raise ValueError("pinned official ARM64 image identity mismatch")
    return {key: item.get(key) for key in ("Id", "RepoDigests", "Architecture", "Os", "Size")}


def require_resources(memory):
    value = memory.get("MemAvailable")
    if type(value) is not int or value < MIN_AVAILABLE_BYTES:
        raise ValueError("at least 32 GiB MemAvailable required")
    return {"memory_bytes": memory, "minimum_available_bytes": MIN_AVAILABLE_BYTES}


def verify_model(directory, receipt_raw):
    if hashlib.sha256(receipt_raw).hexdigest() != MODEL_RECEIPT_SHA256:
        raise ValueError("authorized public model manifest mismatch")
    receipt = json.loads(receipt_raw)
    if (receipt.get("model") != MODEL or receipt.get("all_files_verified") is not True
            or receipt.get("file_count") != 14 or len(receipt.get("files", [])) != 14):
        raise ValueError("complete verified public model manifest required")
    directory = Path(directory).resolve(strict=True)
    for entry in receipt["files"]:
        name = entry["name"]
        path = directory / name
        if (not isinstance(name, str) or Path(name).is_absolute()
                or ".." in Path(name).parts or path.is_symlink()
                or path.resolve(strict=True).parent != directory):
            raise ValueError("model file must be directly inside the approved directory")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(block)
        if path.stat().st_size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError("model file content mismatch")
    return {"model": MODEL, "model_manifest_sha256": MODEL_RECEIPT_SHA256,
            "file_count": 14, "total_file_bytes": receipt["total_file_bytes"],
            "all_files_verified": True}


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    entries = []
    for endpoint in BASELINE_ENDPOINTS:
        with opener.open(endpoint, timeout=6) as response:
            raw = response.read()
            if response.status != 200:
                raise ValueError("existing service health not successful")
        if endpoint.endswith("/v1/health/ready") and json.loads(raw).get("ready") is not True:
            raise ValueError("existing retriever not ready")
        entries.append({"endpoint": endpoint, "status": 200,
                        "body_sha256": hashlib.sha256(raw).hexdigest()})
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--model-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    memory = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
              for line in Path("/proc/meminfo").read_text().splitlines()
              if line.startswith(("MemTotal:", "MemAvailable:"))}
    summary = require_resources(memory)
    image = json.loads(subprocess.run(["docker", "image", "inspect", IMAGE],
                                     capture_output=True, check=True).stdout)[0]
    summary["image"] = require_image(image)
    summary["model"] = verify_model(args.model_directory, args.model_receipt.read_bytes())
    summary["existing_services"] = health()
    summary.update({"gpu_model_requested": False, "production_modified": False})
    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    with args.output.open("xb") as stream:
        stream.write(serialized)
    print(json.dumps({"preflight": "passed", "sha256": hashlib.sha256(serialized).hexdigest(),
                      "mem_available_bytes": memory["MemAvailable"]}))


if __name__ == "__main__":
    main()
