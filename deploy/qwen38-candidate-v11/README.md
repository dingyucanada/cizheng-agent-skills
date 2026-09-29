# Fixed 27B experiment after owned 4B rotation

This is a separate admission policy. It preserves the previous
`deploy/qwen38-candidate` source and all original CPU/download receipts. No
script here stops or restores the historical 4B container, main 8B, backend,
TRT service or Retriever. The coordinator performs the explicitly authorized
rotation of the independent 8007 text experiment.

The fixed NVIDIA model revision remains
`nvidia/Qwen3.8-27B-NVFP4@482ca0f3832238542f8f5295dde86b5f22711d80`.
All 19 official files are verified against the actual download receipt and
official LFS SHA256/Git blob hashes. Three weight files total 21,921,697,280
bytes (20.4162 GiB). The unchanged CLI profile has SHA256
`1c8ea9059772c186e081f141501c191e6f40a0b0b54113bd50b445c6bd68c9df`.
Its original 44/12 GiB resource metadata is historical and is superseded here
by the separately pinned `resource_policy.json`, SHA256
`22e6647836b72e60394aa4b38ccfd7cd993010920f37dc32ab1727585698aeb5`.
Both hashes appear in admission receipts. An old receipt without the new
policy hash cannot satisfy the immediate guard.

Admission requires at least 60 GiB `MemAvailable`, four HTTP 200 business
services (8005/8780/8006/8003), and the Retriever's unchanged ready metadata:
`minimum_remaining_memory_kib=33554432`, watchdog interval 2 seconds. The
system buffer estimate is 34 GiB: the original 32 GiB guard plus 2 GiB for
variation. The estimate is raw weights plus **5 GiB total** runtime overhead;
the 1.5 GiB raw BF16 full-attention KV payload at 24,576 tokens is included
within that 5 GiB assumption and is not added a second time. This leaves an
estimated 34.5838 GiB at exactly 60 GiB available. The 5 GiB is an assumption,
not a measured peak. The 40 GiB no-swap container limit is unchanged.

The exact historical 4B ID is pinned to the original evidence:
`1c963f41f4c1e844de77113eaa26f1b61c9e994a25bdd982c442a447e5d4acc5`,
owned name `cizheng-nim-qwen4b-v09-attempt-04`, original image digest/config ID, 4B model
environment and loopback 8007 port mapping. It must already be exited with no
process, and 8007 must be free. Another ID, a deleted container, still-running
4B or a replacement process on 8007 is a refusal. No caller can select a
different container, model revision, memory floor or model flags.

On 2026-09-29, the coordinator recorded actual before/after available memory
of 54,411,309,056 / 69,232,332,800 bytes, reclaiming 14,821,023,744 bytes
(13.8032 GiB), with all four business checks HTTP 200. This satisfies the
admission threshold for that snapshot. It does not prove that 27B will fit
during loading, prefill, vision encoding or generation.

The CLI retains dense Marlin, FlashInfer attention, Triton GDN/Mamba, BF16
with KV `auto`, context/max-total-tokens 24,576, one request, one Mamba state,
two images at 256 tokens each, no MTP, CUDA graph, overlap or radix cache.
Static fraction 0.58 is based on pre-load available system memory on the
integrated GPU. It is not a system memory reservation. The installed SGLang
0.5.16 cache configurator caps the token pool to the fixed max-total-tokens
and recomputes capped pool sizes; actual allocations must still be measured.
The original CPU receipts confirm imports, mixed precision metadata and
argument/processor parsing, not GPU kernel correctness or model quality.

The launcher creates the exact new container
`cizheng-nim-qwen38-v11-attempt-01` with the original NVIDIA NIM entrypoint,
arms a local guard **before starting it**, then repeats admission checks. The
guard samples `MemAvailable` every 0.5 seconds. A sample below 34 GiB causes
`docker stop --time 0` only for the full new Docker ID after independently
rechecking its name, image, model and port identity. It preserves sample,
inspect, stop-output and stop receipts; it never automatically restores old
4B or changes Retriever's watchdog. This sampled guard cannot guarantee no
instantaneous dip below 32 GiB. Its failure/error receipts require immediate
coordinator attention, and successful arming is not deployment success.

Only the coordinator executes, with a fresh absolute evidence directory:

```sh
bash start_nim_candidate.sh \
  "$HOME/cizheng-next-model27-20260929" \
  "$HOME/cizheng-next-model27-20260929/download-receipt.json" \
  "$HOME/cizheng-next-model27-20260929/config-probe-00" \
  "$HOME/cizheng-next-model27-20260929/gpu-attempt-v11-01"
```

The four path arguments are the only launcher inputs. Inspect
`memory-guard/ready.json`, its live samples, any `stop-receipt.json` or
`error.json`, and all NIM/request evidence. On admission refusal, startup or
guard failure, the coordinator stops only this new candidate if necessary
and restores the exact historical 4B container, verifying four business
services and original 4B readiness. If the pre-rotation snapshot does not
reach 60 GiB, restore 4B without trying GPU loading. Neither a ready endpoint
nor the memory estimate justifies replacing production 8B or claiming 27B
more accurate.

Run the stdlib offline contracts with:

```sh
python3 -B -S tests/test_candidate_contracts.py
bash -n start_nim_candidate.sh
```

Tests use tiny synthetic checkpoint files and replace only external resource
IO. They exercise real admission/hash/receipt logic and the actual launcher's
early refusal, with real network/GPU/process operations forbidden. The
memory guard tests cover the threshold boundary, bound-ID-only stop, wrong
ownership refusal and recording a failed Docker stop without claiming it
worked.
