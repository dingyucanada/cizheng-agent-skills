# Coordinator-rotated TRT: 27B attempt 04

This separate v14 preserves executed v11/v12/v13 sources and receipts.
Its owned candidate is `cizheng-nim-qwen38-v14-attempt-04`, loopback 8009.
Only the coordinator may temporarily stop the exact historical TRT 8006
and old NIM text experiment 8007 before running this launcher. The launcher
never stops or restores either historical container or any other service.
Main vision 8005, backend 8780 and Retriever 8003 must remain healthy.

Actual v13 attempt03 refused at preflight with MemAvailable
62,864,162,816 bytes, below 60 GiB (64,424,509,440 bytes). No template, CPU
or GPU container was created. The original refusal receipt SHA is
`24dbf319501f49784d461feb3c674459819637d96b48306800e7c95531d6b88b`.
The reason for the lower available memory after the main 8B workflow was
not established. v11 and v12 were previously stopped by the unchanged
34 GiB guard while weight loading was at 0/3; v12 was confirmed serial.
Flat layout and serial loading have not proved a successful GPU load.

The fixed profile has the same 43 CLI bytes as v12/v13, SHA256
`70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04`.
Resource policy SHA256 is
`92c2bc09a19bc56ca528d57b3e649ae43f8f9e574c9c516df4aa335ad662f217`.
60 GiB admission, 34 GiB buffer, 0.5-second candidate-only sampled guard,
40 GiB memory/no-swap and Retriever's original 32 GiB/2-second watchdog
are unchanged. Context/max-total-tokens 24,576, fraction 0.58, one request
and Mamba state, two 256-token images, dense Marlin, FlashInfer, Triton GDN,
BF16 KV auto, disabled MTP/graphs/overlap/radix and the original NVIDIA NIM
image/entrypoint are unchanged. Serial load remains exactly:

```text
--model-loader-extra-config {"enable_multithread_load":false}
```

The original mixed-precision checkpoint revision is
`482ca0f3832238542f8f5295dde86b5f22711d80`. Model input must still contain
exactly 19 official regular files; extra files/directories and symlinks
refuse before resource or weight IO. Regular hardlinks are allowed without
changing original modes. MODEL_DIR must be disjoint from source, evidence,
cache, profiles, CPU reports and download receipt; protected paths may nest
with each other. The original CPU report retains its original host model
mount provenance. New view layout and all 19 file hashes are independently
verified; the new CPU phase mounts the view without rewriting old receipts.

Admission also requires both exact historical identities already stopped:

| Service | Fixed name and complete ID |
| --- | --- |
| TRT 8006 | `cizheng-trt-qwen4b` / `14d1bf9ee812bcd32e2cf84caeec61e078b80b27b9af01930e9f0d7adf773c01` |
| NIM 8007 | `cizheng-nim-qwen4b-v09-attempt-04` / `1c963f41f4c1e844de77113eaa26f1b61c9e994a25bdd982c442a447e5d4acc5` |

TRT must have its exact official rc13 image/config ID, original NVIDIA
entrypoint, PyTorch serving command, 24 GiB memory/no-swap contract,
host network, restart policy=no and original read-only model/config mount
roles. Running, paused, restarting, wrong PID/state or changed identity
refuses. Ports 8006 and 8007 must bind freely, ruling out replacement
processes. Both identities, the three business health endpoints, checkpoint
layout and memory admission are repeated after hashing and immediately
before GPU start. No caller flag can select another service or profile.

The TRT fixture records actual *running* read-only metadata and must refuse
admission. Stopped variants in tests are explicitly synthetic. Only the
coordinator's later stop/rotation receipt and live exact-ID Docker inspect
establish a real stopped state; this source preparation does not claim it.

Only the coordinator executes this after preserving original TRT trace
and producing its exact-ID rotation receipt:

```sh
bash start_nim_candidate.sh \
  "$HOME/cizheng-model-checkpoints/qwen38-rev482ca0f" \
  "$HOME/cizheng-next-model27-20260929/download-receipt.json" \
  "$HOME/cizheng-next-model27-20260929/config-probe-00" \
  "$HOME/cizheng-next-model27-20260929/gpu-attempt-v14-04"
```

The four paths are the only inputs. A started candidate is not ready.
The sampled guard can stop only the bound full new candidate ID; it cannot
guarantee a hard reservation or automatically restore historical services.
5 GiB total overhead includes the raw BF16 KV estimate and is not a measured
loading peak. The coordinator must measure actual readiness, remaining
memory and restoration headroom, then restore the same old TRT ID, stopping
only this new candidate first if necessary. Never relax Retriever's guard.

Same-ID TRT restart retains disk files, but its previous GPU allocation,
KV and CUDA graph do not survive process exit. Warm-cache speed or safe
combined memory is not proven. Its original startup script refuses an
existing container and is not the recovery command. The old writable
`first-text.trace.json` must have a separate byte copy and SHA before a new
TRT process can profile to that path; a hardlink is unsafe for writable
evidence. The coordinator owns restoration, fresh receipts and validation.

The offline stdlib contracts run the real shell and preflight with synthetic
weights, no network, no GPU and read-only external fixtures. They check exact
TRT running/changed identity/limits/network/8006 occupation refusal, actual
metadata provenance, repeated stopped checks, all inherited flat layout,
old CPU/hash/budget refusals and candidate-only stops. Run:

```sh
python3 -B -S tests/test_candidate_contracts.py
bash -n start_nim_candidate.sh
```
