# Serial-load 27B attempt 02

This separate v12 candidate preserves the executed v11 source and failure
receipts. The fixed new owned container is
`cizheng-nim-qwen38-v12-attempt-02`, loopback port 8009. The original NVIDIA
NIM image, entrypoint, model revision and 19-file hashes remain unchanged.

v11 attempt 01 was stopped by its 34 GiB sampled guard after 69.6519 seconds
and 138 samples, at 36,448,845,824 available bytes (33.945 GiB). The new
candidate alone was stopped; `OOMKilled=false`, exit 137, four business
services HTTP 200. It was still loading multithreaded shards at 0/3 and had
not become ready. This is a loading failure, not a successful deployment or
model quality result.

The only CLI change from the old 41 arguments is the following pair, making
43 arguments:

```text
--model-loader-extra-config {"enable_multithread_load":false}
```

The new profile SHA256 is
`70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04`.
Its 60/34 GiB metadata now agrees with the separate fixed resource policy,
SHA256 `a18e4234fbbf7ec2dc60fe4a106a22649a044eb8f94c437ee6c9c93a423eb6f9`.
An old 41-argument CPU report cannot satisfy v12 admission. The actual
original config compatibility receipt remains unchanged, because the model
architecture, quantization and image processor have not changed.

The stopped v11 container's installed `loader.py`, `weight_utils.py` and
`load_config.py` SHA256 values match the public SGLang v0.5.16 commit
`fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1` exactly. Only hashes were returned
from the remote machine; no internal source was exported. The effective
false option selects the inherited serial safetensors iterator. Its mmap
path reads one tensor at a time and does not open the next shard early.
Keeping `enable_multithread_load=true` with `num_threads=1` retains a sliding
buffer and is a different policy. mmap stays enabled, checkpoint prefetch
stays disabled. Disabling mmap reads an entire shard into a buffer; cache
dropping acts only after a shard has been consumed and is not added here.
See the [fixed loader source](https://github.com/sgl-project/sglang/blob/fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1/python/sglang/srt/model_loader/loader.py)
and [fixed iterator source](https://github.com/sgl-project/sglang/blob/fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1/python/sglang/srt/model_loader/weight_utils.py).

This removes simultaneous host shard tensor dictionaries. It does not
eliminate the model's GPU parameter allocation, quantization repacking,
vision encoder or workspace. The three shard sizes are 9,965,652,544,
9,985,757,064 and 1,970,287,672 bytes. Their raw total is 20.4162 GiB. No
measured memory reduction or successful GPU load is claimed. The existing
5 GiB total runtime overhead remains an assumption, including the raw
1.5 GiB BF16 KV estimate; v11 already disproved treating that estimate as
a loading peak guarantee.

Admission still requires 60 GiB available, an estimated 34 GiB system
buffer, 40 GiB memory/no-swap limit, four healthy business endpoints
8005/8780/8006/8003, and Retriever's unchanged 32 GiB / 2-second guard.
The exact historical 8007 text experiment
`cizheng-nim-qwen4b-v09-attempt-04`, container ID
`1c963f41f4c1e844de77113eaa26f1b61c9e994a25bdd982c442a447e5d4acc5`,
must already be stopped by the coordinator and 8007 free. v12 never stops
or restores any historical service. The coordinator restored the old 4B
after v11 failure and must explicitly pause it again before a new attempt.

Context/max-total-tokens 24,576, static fraction 0.58, one request, one
Mamba state, two 256-token images, dense Marlin, FlashInfer, Triton GDN,
BF16 KV auto and disabled MTP/graphs/overlap/radix are unchanged. The
launcher creates the exact v12 container without running its entrypoint,
arms the 0.5-second candidate-only 34 GiB guard, repeats admission, then
starts it. A threshold sample stops only the bound full new Docker ID with
zero grace time. Sampling is not a hard reservation; error/stop receipts
require coordinator action and exact old4B recovery.

The original-image no-GPU/no-network 4 GiB CPU phase parses all 43 real CLI
arguments and constructs the real LoadConfig. `loader_contract.py` also
checks the three complete installed source hashes, then executes selected
actual upstream functions with synthetic external file/tensor IO. It verifies
ModelOpt inheritance selects the serial iterator and taking one next()
does not read another tensor or open a second shard. This contract allocates
no model tensor and initializes no GPU. It is not a memory measurement.

Only the coordinator executes this launcher after coordinating GPU timing:

```sh
bash start_nim_candidate.sh \
  "$HOME/cizheng-next-model27-20260929" \
  "$HOME/cizheng-next-model27-20260929/download-receipt.json" \
  "$HOME/cizheng-next-model27-20260929/config-probe-00" \
  "$HOME/cizheng-next-model27-20260929/gpu-attempt-v12-02"
```

The four path arguments are the only inputs. Inspect CPU, preflight,
memory-guard, NIM loading and request receipts. If serial loading fails or
the guard stops it, preserve the failure and restore the exact old 4B
through the coordinator. Retrying must not lower Retriever's protection
or count a started container as ready.

The 35 offline stdlib contracts cover inherited refusals, real retired4B
metadata, exact bound-ID stops, JSON boolean false, refusal of threaded/
string/zero/old-profile reports, and the unique two-argument CLI diff. The
actual public-source branch/lazy-read contract was also executed locally
without model tensors. Run:

```sh
python3 -B -S tests/test_candidate_contracts.py
bash -n start_nim_candidate.sh
```
