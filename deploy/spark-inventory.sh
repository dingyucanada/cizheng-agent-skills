#!/usr/bin/env bash
# Read-only inventory, does not print environment variables, credentials or case paths.
set -u
uname -m
python3 --version
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
fi
if command -v nvcc >/dev/null; then nvcc --version; fi
if command -v docker >/dev/null; then
  docker version --format '{{.Server.Version}}'
  docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'
fi
