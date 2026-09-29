# Flat-checkpoint 27B attempt 03

This independent v13 source preserves the executed v11/v12 sources and their
failure receipts. Its only owned candidate is
`cizheng-nim-qwen38-v13-attempt-03`, loopback port 8009. It retains the original
NVIDIA NIM image and entrypoint, fixed model revision, serial 43-argument CLI,
60 GiB admission, 34 GiB system buffer, 0.5-second sampled candidate-only guard,
40 GiB memory/no-swap limit, and all four business services.

Both prior attempts failed during weight loading at 0/3 and were not ready.
v11's guard stopped its multithreaded loader after 69.6519 seconds and 138
samples, at minimum 36,448,845,824 available bytes (33.945 GiB). v12's guard
stopped its confirmed serial loader after 54.559145 seconds and 108 samples,
at minimum 35,960,176,640 bytes (33.491 GiB). NIM recursive JSON/cache warnings
also appeared in v12; they are not the sole exit cause. The coordinator's
later layout check reported `was_running=false`, not a first stop by that
check. These failures do not prove a memory reduction or model quality.

The new model mount must be a separate flat view containing exactly the 19
fixed official regular files. No extra directory, file, or symlink is
allowed. Regular hardlinks are allowed, including link counts greater than
one; the launcher never moves, deletes or changes modes of model files.
The coordinator creates the view and records all 19 hashes and the original
inode identity independently. Evidence, cache, profiles, source, original
CPU evidence and download receipt must each be disjoint from the model
directory in both nesting directions. Evidence may contain its own cache
and profiles; those protected directories can nest with each other.

The original download receipt still verifies the same 19 bytes after the
host model path changes. The original CPU compatibility receipt and its
original `/models/qwen38` host mount provenance remain unchanged. Its scope
is original model configuration/processor/quantization compatibility, not a
claim that the old CPU probe mounted the new view. The new full preflight
records flat layout, canonical path isolation, inodes/link counts, and
complete SHA verification independently. A new isolated CPU phase then
mounts the new view and checks the real 43 arguments, LoadConfig and serial
loader behavior before GPU admission.

The profile bytes are identical to v12, SHA256
`70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04`.
Resource policy SHA256 is
`374b3430140bb1bab28e9ac25b677d876fb237c5b30f0e0b18a447f8fe9b216f`.
Relative to v11's 41 arguments, the sole added pair remains:

```text
--model-loader-extra-config {"enable_multithread_load":false}
```

Installed SGLang v0.5.16 loader source hashes matched the complete official
files at commit `fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1`. Only source hashes
were returned from the stopped container; internal source was not exported.
The [actual loader](https://github.com/sgl-project/sglang/blob/fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1/python/sglang/srt/model_loader/loader.py)
and [iterator](https://github.com/sgl-project/sglang/blob/fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1/python/sglang/srt/model_loader/weight_utils.py)
select serial safetensors loading for this JSON boolean false. mmap stays
enabled; checkpoint prefetch stays disabled. No other loader switch is added.
Serial loading does not remove GPU parameter allocation, repacking, vision
encoder or workspaces, and the actual v12 guard failure remains relevant.

Raw weights are 20.4162 GiB. The unchanged 5 GiB total overhead assumption
includes the raw 1.5 GiB BF16 KV estimate at 24,576 tokens; it is not a
measured loading peak. Static fraction 0.58 is not a system reservation.
Context/max-total-tokens 24,576, one request/Mamba state, two 256-token images,
dense Marlin, FlashInfer, Triton GDN, BF16 KV auto, and disabled MTP, graphs,
overlap and radix are unchanged. No successful GPU load or remaining memory
floor is claimed by this source preparation.

8005 main vision, 8780 backend, 8006 TRT and 8003 Retriever must remain
healthy. Retriever's original 32 GiB / 2-second watchdog is unchanged. The
exact historical 8007 experiment `cizheng-nim-qwen4b-v09-attempt-04`, ID
`1c963f41f4c1e844de77113eaa26f1b61c9e994a25bdd982c442a447e5d4acc5`,
must already have been stopped by the coordinator, with 8007 free. This
launcher never stops or restores historical services. Its sampled guard can
stop only the new exact bound candidate ID. If this attempt fails, preserve
all original receipts and let the coordinator restore that exact old 4B.

Only the coordinator executes this example after GPU timing is coordinated:

```sh
bash start_nim_candidate.sh \
  "$HOME/cizheng-model-checkpoints/qwen38-rev482ca0f" \
  "$HOME/cizheng-next-model27-20260929/download-receipt.json" \
  "$HOME/cizheng-next-model27-20260929/config-probe-00" \
  "$HOME/cizheng-next-model27-20260929/gpu-attempt-v13-03"
```

Those four paths are the only inputs. Preflight refuses bad layout or path
isolation before any weight/resource IO or CPU/GPU container creation. It
rechecks the layout after hashing and before GPU starts. A started candidate
is not ready; inspect actual loading, guard and request receipts.

44 offline stdlib contracts include the real shell's refusal of extra cache
directories, JSON files, symlinks and nested evidence/CPU/receipt paths before
CPU/GPU creation. They also test regular hardlinks without mode changes,
changed layout after hashing, original model hashes, actual retired-4B
metadata, low memory, old profiles and exact-ID guard stops. Run:

```sh
python3 -B -S tests/test_candidate_contracts.py
bash -n start_nim_candidate.sh
```
