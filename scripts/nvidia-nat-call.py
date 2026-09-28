#!/usr/bin/env python3
"""Bounded application subprocess interface to the real registered NAT graph.

Only a caller-selected case ID/revision/query or saved run ID enters this graph.
No model, network, images, shell code or arbitrary workflow path is accepted.
Use the Python from the isolated cizheng-nvidia-nat environment.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))


async def call(data_dir, payload):
    # Set before importing the toolkit; no user-wide config is modified.
    os.environ.update(NAT_TELEMETRY_ENABLED="false", NAT_CONFIG_DIR=str(data_dir / "nat-config"),
                      CIZHENG_DATA_DIR=str(data_dir), LANGCHAIN_TRACING_V2="false",
                      LANGSMITH_TRACING="false", OTEL_SDK_DISABLED="true")
    from cizheng_nat.evidence import parse_request
    from nat.runtime.loader import load_workflow
    request = parse_request(payload)
    config = SOURCE / "integrations/nvidia_nat/configs/evidence.yml"
    async with load_workflow(config) as manager:
        async with manager.session() as session:
            async with session.run(request.model_dump_json()) as runner:
                return json.loads(await runner.result(to_type=str))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    if not args.data_dir.is_dir():
        parser.error("data-dir must be an existing Cizheng local case directory")

    # An OS audit hook also blocks accidental exporters or dependency requests.
    def offline_guard(event, arguments):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise OSError("network disabled for Cizheng NVIDIA evidence workflow")
    sys.addaudithook(offline_guard)
    try:
        raw = sys.stdin.buffer.read(24_001)
        if len(raw) > 24_000:
            raise ValueError("request_too_large")
        result = asyncio.run(call(args.data_dir.resolve(), raw.decode("utf-8")))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        from cizheng_nat.evidence import EvidenceError
        reason = str(exc) if isinstance(exc, EvidenceError) else "nvidia_evidence_call_failed"
        print(json.dumps({"error": reason, "inference_performed": False, "review_required": True}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
