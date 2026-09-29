# Fixed Qwen3.8-27B-NVFP4 preparation

This directory prepares one official NVIDIA checkpoint, a CPU compatibility
audit, and one fixed GPU candidate launcher for the root coordinator to execute.
No 27B GPU server has been started by this preparation. The existing 8B service
and the other original services remain in place; a larger parameter count does
not establish better ceramic identification or better support for citations.

The checkpoint is `nvidia/Qwen3.8-27B-NVFP4` at revision
`482ca0f3832238542f8f5295dde86b5f22711d80`. The fixed manifest contains 19 files
totaling 21,945,291,730 bytes. Its three weight shards total 21,921,697,280 bytes
(20.416 GiB). Every file has its official Git blob identity; LFS files also have
their official SHA256. Manifest SHA256:
`c05398358bdde37fe7ce1656bea3388bf270012f216d10bcaa25fcbf6e085795`.
The generic downloader is an unchanged copy of the 35B downloader, SHA256
`27a61dd6f49a3ad03f1164efcb1a72a2991c913992046a6ff17fb55becb711b7`.

`prepare_stage.py --stage ABSOLUTE_PRIVATE_DIRECTORY --attempt 1` verifies the
16 small files and resolves only HEAD requests for the three large weights.
The temporary signed public CDN URLs are stored in a private file with mode
600. They must not be printed, published or committed. The stage directory has
mode 700. A numbered preparation receipt is never overwritten. The generic
downloader reads that stage's fixed manifest and private URL map, verifies
Content-Range and final file identities, and writes its download receipt only
after all files verify. An in-progress byte count is not a verified checkpoint.

On 2026-09-29 the small-file preparation succeeded and the three HEAD requests
returned HTTP 200 from `us.aws.cdn.hf.co`. An independently named download was
started on Spark in `$HOME/cizheng-next-model27-20260929`. A later read-only check
retrieved the original completed `download-receipt.json`: all 19 files verified,
21,945,291,730 bytes, SHA256
`1045b80ad92a9130880d0d5171de6998ca8272f470d8dd2e7cf260dedc45609b`.
All 19 receipt SHA256 values matched the official LFS hashes or previously
verified small-file hashes. The original remote manifest also matched its pin.
Download took 1890.122 seconds; shard assembly/hashing shared the node with a
workflow comparison and this time is not an isolated inference-speed result.
The launcher still verifies all files again before GPU loading.

The CPU audit uses the already installed Linux ARM64 NIM image digest
`7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9`
and image config ID
`7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef`.
Run `start_cpu_only.sh PREPARED_STAGE FRESH_STAGE/config-probe-00` from that
prepared stage, after copying this launcher there. It rejects an existing audit
directory or owned container, copies the image's account files for a host UID
cache, uses no GPU device and `--network none`, caps memory and swap at 4 GiB,
and retains the stopped probe plus original diagnostics. No model tensors are
opened or instantiated.

The actual `config-probe-00` exited 0. Its original CPU receipt has SHA256
`622dd9d519dc00a89aaa0e8130f9af30f12b2dda90f27d372dbb3471853de88c`.
The installed packages were SGLang 0.5.16, Transformers 5.12.1, Torch
2.11.0+cu130 and FlashInfer 0.6.14. Despite the model's export field
`transformers_version=5.13.1`, both configuration loaders read the dense
`Qwen3_5ForConditionalGeneration` architecture. The `swish` gate, attention
output gate, rotary settings and state dtype were retained without differences.
The actual installed SGLang source registered the dense model and passed the
gate value into its gated norm.

The actual ModelOpt parser selected `modelopt_mixed` with 401 quantized layers.
Its `kv_cache_quant_algo` was null, so it does not establish a calibrated FP8 KV
configuration equivalent to the 35B checkpoint. This candidate fixes KV to
`auto`, expected to select BF16. Its actual GPU dtype must be recorded after loading.
The CPU
processor resolved to `Qwen3VLProcessor` / `Qwen2VLImageProcessor`; two synthetic
1024×1024 images, capped at area 262144, produced grids `[1,32,32]` and 256 visual
tokens each. This checks the preprocessing limit, not ceramic visual accuracy.

The configuration has 64 text layers: 48 linear attention and 16 full attention,
with 4 KV heads of dimension 256. At context 24576, raw full-attention KV storage
is 768 MiB for FP8 or 1.5 GiB for BF16. This excludes GDN state, metadata,
alignment, temporary tensor conversion, vision work and allocator peaks; it is
not a measured memory bound. The existing workflow already consumed roughly
14–15.4k prompt tokens, so an 8192-only experiment cannot establish full workflow
compatibility.

CPU success does not validate weight names or shapes, SM121 kernels, GPU
allocation, inference timing, visual recognition or citation quality. The
official SGLang GB10/aarch64 recipe tested version 0.5.19; the local 0.5.16 result
is an experiment using the fixed installed NIM, not NVIDIA certification of this
new checkpoint. Root owns subsequent bounded GPU deployment and comparisons.

The fixed GPU profile targets loopback port 8009 and the owned container
`cizheng-nim-qwen38-v10-attempt-01`. It requests 24576 context and total tokens,
one running request, dense Marlin, FlashInfer attention, Triton linear/GDN,
no MTP/CUDA graph/overlap/radix, and at most two 256-token images. Static fraction
is 0.58, the container memory and memory+swap limits are both 40 GiB, admission
requires at least 44 GiB MemAvailable, and the weights-plus-5-GiB assumption must
leave at least 12 GiB for the system. These are admission estimates, not a
measured GPU peak. The currently active 35B candidate makes memory insufficient
for a concurrent 27B load; the launcher refuses and never stops it.

The launcher accepts exactly four paths and no caller-supplied flags:

```text
bash start_nim_candidate.sh FIXED_MODEL_DIR DOWNLOAD_RECEIPT ORIGINAL_CPU_AUDIT_DIR FRESH_EVIDENCE_DIR
```

The original CPU audit directory is `config-probe-00` from the earlier actual
CPU run. The launcher verifies its pinned receipt SHA and no-GPU fixed-image
container metadata, hashes all 19 checkpoint files against their official
identities and download receipt, and checks the original five health endpoints.
It copies vendor configuration and account files from the fixed image, keeping
the original NIM server entrypoint and host UID cache convention. Its separate
4-GiB offline CPU profile probe parses the exact SGLang CLI without constructing
a GPU-dependent ServerArgs object. The profile probe must succeed before GPU
loading. The independently executed `config-probe-01` actually exited 0, with
CPU receipt SHA256
`76ee905472f67f8a6096af77452a44a5902b32e555ff02b30a8da6502f55cb89`.
It parsed all 41 fixed CLI arguments, verified the original entrypoint and memory
formula, processed the two images, and kept CUDA uninitialized. Actual GPU KV
dtype remains unobserved. Immediately before GPU startup, live guards repeat and all 19
file identities must be unchanged since the complete hash. Every attempt uses
a fresh evidence directory and preserves failure output and owned containers.

The profile SHA256 is
`1c8ea9059772c186e081f141501c191e6f40a0b0b54113bd50b445c6bd68c9df`.
Twenty offline standard-library contracts passed, including a real execution of
the shell launcher with low-memory resource IO substituted: it refused before
any template, CPU or GPU creation and issued no stop/restart commands. Other
cases cover corrupt weights/receipts/profile, mismatched CPU/image evidence,
old service failures, occupied port, and changes after hashing. The independent
`qwen38-deployment-contracts` CI job runs these without a network or GPU.

Sources: [fixed model metadata](https://huggingface.co/api/models/nvidia/Qwen3.8-27B-NVFP4/revision/482ca0f3832238542f8f5295dde86b5f22711d80?blobs=true),
[fixed config](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4/raw/482ca0f3832238542f8f5295dde86b5f22711d80/config.json),
[fixed quantization metadata](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4/raw/482ca0f3832238542f8f5295dde86b5f22711d80/hf_quant_config.json),
[official SGLang recipe](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B),
[SGLang 0.5.16 architecture](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.16/python/sglang/srt/models/qwen3_5.py).
