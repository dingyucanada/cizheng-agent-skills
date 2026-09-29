"""Sample system memory every 0.5 s; stop only this fixed 27B candidate.

This is a best-effort sampled guard, not a hard system memory reservation.
It never restores or stops any historical business service. Original receipts
and Docker stop output are retained. The coordinator restores the old 4B.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import preflight

INTERVAL_SECONDS = 0.5
CREATED_TIMEOUT_SECONDS = 120
CANDIDATE_NAME = "cizheng-nim-qwen38-v13-attempt-03"


def write_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def inspect_candidate(container_id):
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise ValueError("one full Docker ID from this launcher required")
    raw = subprocess.run(["docker", "container", "inspect", container_id],
                         capture_output=True, check=True, timeout=5).stdout
    items = json.loads(raw)
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError("one exact candidate inspect required")
    item = items[0]
    config = item.get("Config", {})
    if (item.get("Id") != container_id or item.get("Name") != "/" + CANDIDATE_NAME
            or item.get("Image") != preflight.CONFIG_ID or config.get("Image") != preflight.IMAGE
            or config.get("Entrypoint") != ["/opt/nim/start_server.sh"]
            or "NIM_MODEL_PATH=/models/qwen38" not in config.get("Env", [])
            or "NIM_SERVED_MODEL_NAME=Qwen3.8-27B-NVFP4" not in config.get("Env", [])
            or item.get("HostConfig", {}).get("Memory") != preflight.CGROUP_LIMIT_BYTES
            or item.get("HostConfig", {}).get("MemorySwap") != preflight.CGROUP_LIMIT_BYTES
            or item.get("HostConfig", {}).get("PortBindings") != {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8009"}]}):
        raise ValueError("guard can stop only the exact fixed v11 27B candidate")
    return item, raw


def monitor(container_id, output_directory, *, clock=time.monotonic, pause=time.sleep):
    policy = preflight.require_resource_policy()
    output_directory.mkdir(mode=0o700)
    item, raw = inspect_candidate(container_id)
    with (output_directory / "initial-container-inspect.json").open("xb") as stream:
        stream.write(raw)
    started = clock()
    first = preflight.memory_snapshot()
    write_once(output_directory / "ready.json", {
        "memory_guard": "armed", "container_id": container_id, "container_name": CANDIDATE_NAME,
        "interval_seconds": INTERVAL_SECONDS, "minimum_system_buffer_bytes": preflight.MIN_BUFFER_BYTES,
        "resource_policy_sha256": preflight.RESOURCE_POLICY_SHA256,
        "initial_memory_bytes": first, "hard_reservation": False,
        "preserves_retriever_guard_bytes": policy["retriever_existing_guard_bytes"],
        "automatic_old_service_restore": False})
    minimum = first["MemAvailable"]
    samples = 0
    was_running = item.get("State", {}).get("Running") is True
    while True:
        sampled_at = clock()
        memory = preflight.memory_snapshot()
        available = memory.get("MemAvailable")
        if type(available) is not int:
            raise ValueError("memory sample must contain integer MemAvailable")
        minimum = min(minimum, available); samples += 1
        with (output_directory / "memory-samples.jsonl").open("a") as stream:
            stream.write(json.dumps({"elapsed_seconds": round(sampled_at - started, 6),
                                     "mem_available_bytes": available}) + "\n")
        if available < preflight.MIN_BUFFER_BYTES:
            # Verify the immutable Docker ID again immediately before the only
            # service mutation this guard can perform. Never select by port/name.
            item, raw = inspect_candidate(container_id)
            with (output_directory / "before-stop-container-inspect.json").open("xb") as stream:
                stream.write(raw)
            result = subprocess.run(["docker", "stop", "--time", "0", container_id],
                                    capture_output=True, timeout=10)
            for suffix, data in (("stdout", result.stdout), ("stderr", result.stderr)):
                with (output_directory / ("stop." + suffix)).open("xb") as stream:
                    stream.write(data)
            write_once(output_directory / "stop-receipt.json", {
                "memory_guard": "threshold_crossed", "container_id": container_id,
                "stopped_only_exact_candidate": result.returncode == 0,
                "stop_exit_code": result.returncode, "sample_count": samples,
                "minimum_sampled_available_bytes": minimum, "trigger_memory_bytes": memory,
                "threshold_bytes": preflight.MIN_BUFFER_BYTES, "interval_seconds": INTERVAL_SECONDS,
                "elapsed_seconds": round(clock() - started, 6),
                "restore_old_4b_required_by_coordinator": True,
                "gpu_peak_proven": False, "hard_reservation": False})
            return 1
        # State reads are less frequent than memory samples. A stopped candidate
        # ends the guard; a never-started created container expires after 120s.
        if samples % 10 == 0:
            item, _ = inspect_candidate(container_id)
            state = item.get("State", {})
            was_running = was_running or state.get("Running") is True
            if (state.get("Status") in ("exited", "dead")
                    or (not was_running and clock() - started >= CREATED_TIMEOUT_SECONDS)):
                write_once(output_directory / "completion.json", {
                    "memory_guard": "candidate_ended" if was_running else "candidate_not_started",
                    "container_id": container_id, "sample_count": samples,
                    "minimum_sampled_available_bytes": minimum,
                    "elapsed_seconds": round(clock() - started, 6), "no_service_stopped_by_guard": True})
                return 0 if was_running else 1
        pause(max(0.0, INTERVAL_SECONDS - (clock() - sampled_at)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container-id-file", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.output_directory.exists():
        raise FileExistsError("fresh guard evidence directory required")
    try:
        return monitor(args.container_id_file.read_text().strip(), args.output_directory)
    except Exception as exc:
        args.output_directory.mkdir(mode=0o700, exist_ok=True)
        write_once(args.output_directory / "error.json", {
            "memory_guard": "failed", "error_type": type(exc).__name__, "error": str(exc),
            "guard_ready_is_not_gpu_success": True})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
