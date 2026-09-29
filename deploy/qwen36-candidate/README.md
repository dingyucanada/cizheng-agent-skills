# Qwen3.6 35B NVFP4 isolated experiment

This directory starts one candidate at `127.0.0.1:8008` and reads the health of
the existing 8005, 8006, 8007, 8003 and 8780 services. It never stops or replaces
them. A new attempt name and evidence directory are required on every run.
It pulls no image, downloads no checkpoint, and preserves the actual server's
original NIM entrypoint. Root owns `download_fixed.py` and `checkpoint.json`.

```bash
NIM_CANDIDATE_NAME=cizheng-nim-qwen36-v10-attempt-01 \
  bash deploy/qwen36-candidate/start_nim_candidate.sh \
  /absolute/fixed/model /absolute/download-receipt.json /absolute/fresh/evidence
```

The image must already be installed with digest
`7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9`,
config ID `7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef`,
Linux ARM64. The single checkpoint is
`nvidia/Qwen3.6-35B-A3B-NVFP4` at revision
`1355db6a052410cfd62085d94b58866fd0f2c3c5`: 17 files, 23,462,477,857 bytes,
including 23,424,338,320 bytes of weights. The independent identity file checks
LFS SHA256 or actual Git blob SHA1 as appropriate, in addition to every receipt
SHA256. The index and tokenizer JSON files are also LFS objects.

The fixed startup profile uses 40 GiB memory and swap limits, no restart,
context and token pool caps of 24576, one running request, 512-token prefill
chunks, FP8 E4M3 KV, Marlin for NVFP4 MoE and linear layers, FlashInfer full
attention, SDPA vision attention, and Triton GDN. Prefix caching, overlap
scheduling and CUDA graphs are disabled. Mamba gets one state slot with
`no_buffer` and page size 1. Multimodal feature transport uses CPU. At most two
images are allowed; video and audio are disabled. The processor's pixel-area
range is 4,096–262,144, approximately 256 tokens per image for patch16/merge2.
The exact installed processor is tested using two synthetic images on CPU.

The earlier 8192 profile passed the operator's isolated CPU check, but the
real 8B-r2 workflow took 117.4 seconds and its main actions reported prompt
tokens of 15,250 / 15,362 / 14,324 / 14,684. Thus 8192 cannot accommodate the
actual workflow. The current 24,576 limit allows room for those measured
prompts and completion; it still requires a complete same-workflow inference
test. The old profile's exact bytes are preserved privately in
`work/spark-next-20260929/research-evidence/legacy-8192-profile.json`, with its
original SHA256
`aa4d19bb8124c15103da16edd8aafb6d4befc706a4352cc6c904e56a9bf4ba35`.
The existing on-node CPU receipt is unchanged and does not validate the new profile.

The fixed model config has 10 full-attention layers, 30 GDN layers, two KV
heads and head dimension 256. With FP8 K/V elements and TP1, the raw full
attention KV payload at 24,576 tokens is
`24576 * 10 * 2(K/V) * 2(heads) * 256 * 1(byte) = 251658240 bytes`, or
**240 MiB**. The earlier 8192 payload was 80 MiB, so this component grows by
160 MiB. This lower-bound payload estimate omits GDN state, scales, allocator
or page bookkeeping, encoder allocations and temporary buffers. It does not
prove the peak or that the actual token pool can reach the requested cap.
The 5 GiB total runtime-overhead assumption is unchanged; this component is
recorded separately, without adding a measured-memory claim to that budget.

**Memory correction:** SGLang v0.5.16 calculates
`postload_available - preload_available * (1 - static_fraction)` for the KV
pool. Its integrated-GPU branch uses system `MemAvailable`. On a node with
49 GiB available, fractions 0.24 and 0.27 give only 11.76 and 13.23 GiB before
weights; both are below the raw 21.816 GiB weights. They would fail even with
the earlier 8192-token cap. Startup records the 0.24 rejection before any GPU loading.
The authorized experiment uses **0.58 of the initially available memory**.
This is distinct from importing a vLLM total-capacity fraction from a recipe.

Preflight requires at least 44 GiB available, and the raw weights plus a
**5 GiB assumed, unmeasured** runtime overhead must fit the 40 GiB container
limit while leaving at least 16 GiB system memory. This estimate cannot
predict Marlin temporary allocations, CUDA context accounting, JIT cost or
peak memory. The cgroup limit and conservative single-request profile remain
in force; actual GPU loading and generation must be measured.

After hashing the full checkpoint, startup copies configuration, passwd and
group only from a stopped container of the fixed image. It creates an
independent cache and synthetic host UID/GID entries in these copies. The
CPU audit overrides the entrypoint only for inspection: no GPU device is
attached, networking is disabled and memory is capped at 4 GiB. It checks
the actual SGLang 0.5.16 / Transformers 5.12.1 / Torch 2.11.0+cu130 packages,
entrypoint SHA, supported CLI values, EntryClass registration, mixed ModelOpt
and FP8 KV metadata, the actual pool formula and image processing. Only a
passed audit permits the original NIM entrypoint to start the GPU candidate.
An audit failure is preserved and exits without starting that candidate.

`candidate_started=true` means Docker accepted startup, **not readiness or
successful inference**. The operator must observe startup, five-service
coexistence, memory peak, health and the same public text/image/reason tests.
On failure, preserve logs and adjust or stop only the exact owned attempt
name. No automatic cleanup of an existing candidate or old service occurs.

Marlin is the documented NVFP4 **W4A16 fallback**, not a promise of native
W4A4 speed. CPU success does not validate SM121 kernels or professional ceramic
attribution. The current official Qwen3.6 SGLang cookbook says >=0.5.10 but
lists B200/B300 for NVFP4; it does not certify this older fixed NIM on GB10.
Its B200/B300 `trtllm_mha` examples are not used with the smaller `no_buffer`
profile, which requires another full-attention backend.

Primary sources:

- [Official fixed model](https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4/tree/1355db6a052410cfd62085d94b58866fd0f2c3c5)
- [v0.5.16 CLI definitions](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/server_args.py)
- [v0.5.16 pool calculation](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/mem_cache/kv_cache_configurator.py)
- [v0.5.16 integrated-memory path](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/utils/common.py)
- [v0.5.16 mixed ModelOpt loader and Marlin](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/layers/quantization/modelopt_quant.py)
- [v0.5.16 processor configuration forwarding](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/multimodal/processors/base_processor.py)
- [Current official Qwen3.6 SGLang cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.6)
