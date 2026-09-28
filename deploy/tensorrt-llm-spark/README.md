# Spark TensorRT-LLM 独立文本候选

核对日期：2026-09-29。此目录与现有视觉原生适配器及业务后端独立。没有修改生产的模型选择、报告结论、预算、Schema、引文合同或门禁。

## 当前事实与验收界限

Spark 上的独立文本候选已实际部署并完成一次接口与 CUDA 验收：`127.0.0.1:8006` 的 `/health`、`/version`、`/v1/models` 均正常，版本 1.3.0rc13、模型别名 Qwen3-4B-Instruct-2507。唯一公开陶瓷文字请求返回 `stop`，257 输入、93 输出、350 总 tokens；0 自动重试。完整原始响应及输入留证，没有修补模型答案。包含首请求追踪开销的记录耗时约 4.056 秒，不是性能对照。

官方 Qwen 模型完整下载：14 个文件、8,060,918,292 字节，逐文件大小和原 SHA256 校验通过，无 partial，下载进程退出 0；校验 receipt SHA256 为 `a41c5affd0d9dcc418f5d7aed2071c146347d3c4f676ee46a02b3a8ee0cba694`。固定官方 ARM64 镜像原单次下载退出 0、82 个唯一层全部完成，展开大小 35,567,949,547 字节。容器内实际版本为 TensorRT-LLM 1.3.0rc13、PyTorch 2.11.0a0（NVIDIA 26.02）、CUDA 13.1；无模型 256×256 BF16 CUDA 矩阵乘法通过，PyTorch 记录分配 8,781,824 字节、峰值 8,847,872 字节。此数不包括全部驱动/统一内存。

真实请求的私有 trace 为 6,547,029 字节，SHA256 `e5d1252c94222ba9f150fbbaaed05a6619ea777a1e3bcaa94f5b25bdf2036452`；现场核验 3,653 个有时长 CUDA kernel 事件、42 个不同 kernel 名称、1,264 个 CUDA runtime 事件。核验还绑定相同容器 ID/镜像/启动时间/服务进程、原始请求及响应 SHA、唯一 POST 的时间窗、trace mtime 和 profiler 0→8 日志。只覆盖前八次执行器迭代，不覆盖完整请求，不测 GPU 利用率，不证明端到端加速或语义质量。原 trace 和进程快照留私有，公开只保留脱敏统计。

这次原话区分了馆方记载与未知器物的证据边界，但未复述藏品号，并列出多个待补资料而不是严格两项；本验收没有判定领域意见正确、引用定位合格、满足全部指令或完成原报告流程。该模型仍是独立文本候选。

远程只读检查确认 NVIDIA GB10、compute capability 12.1、Linux aarch64、driver 580.159.03、约 82 GiB MemAvailable、约 3.07 TB 可用磁盘。NVIDIA Container Toolkit/CDI 由主任务统一配置；本目录不安装全局组件、不重启 Docker、不操作未知容器。

选择 `Qwen/Qwen3-4B-Instruct-2507` BF16 作为小型文字归纳候选，理由是可访问的 Qwen 官方分发及较低的权重占用。它是文本模型，本部署不承诺视觉能力、更高鉴定质量、替换 8B 主模型或端到端加速。TensorRT-LLM 的 PyTorch backend 使用其运行时与 CUDA 内核；本路径没有生成或验收序列化 TensorRT engine。

## 固定版本和官方来源

- [NVIDIA Spark TensorRT-LLM playbook](https://build.nvidia.com/spark/trt-llm/instructions)：明确使用 `release:1.3.0rc13`，提供 OpenAI 兼容文本服务路径。实际下载按 ARM64 内容摘要固定，避免漂移。示例的高批量和 90% 缓存不适合三模型共享内存，未沿用。
- [rc13 官方服务源码](https://raw.githubusercontent.com/NVIDIA/TensorRT-LLM/v1.3.0rc13/tensorrt_llm/commands/serve.py) 与 [rc13 配置源码](https://raw.githubusercontent.com/NVIDIA/TensorRT-LLM/v1.3.0rc13/tensorrt_llm/llmapi/llm_args.py)：CLI 提供 PyTorch backend；KV `max_tokens` 与 `free_gpu_memory_fraction` 同时设置时取较小分配。实际容器中的 CLI 和字段仍要核验，不能以较新主分支代替当前组合实测。
- [NVIDIA 硬件文档](https://nvidia.github.io/TensorRT-LLM/supported-hardware.html)：列出 DGX Spark。架构支持不证明某一 checkpoint、精度和容器组合已运行。
- [Qwen 官方项目](https://github.com/QwenLM/Qwen3)：模型作者链接其 ModelScope 分发；[ModelScope 模型页](https://modelscope.cn/models/Qwen/Qwen3-4B-Instruct-2507) 是本次实际文件来源。[作者模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) 明确 4B、BF16、Apache-2.0、纯文本且仅 non-thinking 模式。
- [NVIDIA Qwen3-8B-NVFP4](https://huggingface.co/nvidia/Qwen3-8B-NVFP4) 是原低内存候选。节点直接访问 Hugging Face 元数据报 `network unreachable`，不是凭据拒绝。本次没有绕过网络/地区限制，没有下载第三方转换权重。

固定镜像：

```text
nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965
```

匿名官方 manifest 已现场确认 `linux/arm64`、101 层、压缩总量 19,547,210,461 字节。此数是传输体积，不是展开后的磁盘大小或模型 GPU 峰值。

官方 ModelScope 清单共 14 个文件，8,060,918,292 字节。API 请求使用 `Revision=master`；最终身份必须由保存的逐文件 revision、大小、SHA256 共同绑定，不能把 mutable alias 称为不可变版本。原 metadata 与校验 receipt 保存在私有验收目录，不把完整节点路径/连接配置写入公开文档。

## 有边界的执行顺序

1. 下载固定镜像并保存原 manifest。下载与模型加载分开，不重复开启拉取。
2. `download_model.py` 按官方 API 保存的清单下载，拒绝越界路径、重复文件、symlink、内容不符和未审查的 partial。完全匹配后才原子发布文件；全部文件通过才产生 receipt。失败记录保留，不以临时文件充数。
3. 镜像完成且 CDI 已就绪时，执行 `probe_cuda.sh`。它使用 `--device nvidia.com/gpu=all`，无网络、无模型，仅版本核对及 256×256 BF16 CUDA 矩阵乘法。此测试本身不证明模型推理成功。
4. 主任务协调后才执行 `TRT_LOAD_COORDINATED=yes bash start_candidate.sh`。脚本重新核对全部文件，并要求加载前可用共享内存至少 32 GiB、端口 8006 空闲、同名容器不存在。不会替换/重启已存在服务。
5. 核对 `/health`、`/version`、`/v1/models`，再发送一次公开陶瓷文字核查输入到 `/v1/chat/completions`：采用 [Met 馆藏 79.2.467](https://www.metmuseum.org/art/collection/search/48559) 的公开文字摘要，同时明确另一件待核查器物只是演示用未知对象；要求区分馆方记载、未知器物的证据边界和待补物证。请求没有图片或私有资料，最大输出 256 tokens、HTTP 期限 80 秒。保留完整原输入、响应、usage、finish_reason、耗时与摘要；只在 `stop` 与原始 usage 合法时接受接口，不修补输出、不偷偷重发失败请求。无需请求会实际生成 token 的 `/health_generate`。
6. `start_candidate.sh` 配置 rc13 自带的 `TLLM_PROFILE_START_STOP=0-8` 和私有 PyTorch trace 输出。固定版本[执行器源码](https://raw.githubusercontent.com/NVIDIA/TensorRT-LLM/v1.3.0rc13/tensorrt_llm/_torch/pyexecutor/py_executor.py)明确排除 warmup；首个实际请求执行前八次迭代后自动导出，候选服务继续运行。用 `verify_gpu_trace.py --capture-runtime --output ...` 在唯一 POST 前后分别保存容器/进程身份；核验时传入 `--container-before`、`--container-after`、`--trace` 和 `--acceptance-receipt`。核验要求实际 `kernel` 与 `cuda_runtime` 有有效时长事件，原请求/响应 SHA 一致，同一容器未重启、CPU trace PID 与候选进程匹配、trace 在请求时间窗内生成且日志确认 0→8 范围。原 trace 留私有，只输出 SHA 和统计。再检查内存变化、服务健康和生产服务仍正常。

本次规划：单请求，最大总序列 4096、每批输入 2048、KV 不超过 4096 tokens 且 free-memory fraction 0.05、CUDA graph 仅 batch 1、offline 权重只读、只监听 `127.0.0.1:8006`。加载峰值预留 24 GiB、稳态约 10–16 GiB 是估计，必须以实测取代。容器 cgroup 内存限制不能被当作全部 CUDA/统一内存的峰值保证，仍需监控系统可用内存。GB10 统一内存不能将文件大小当峰值 GPU 内存。当前业务 8005/8780 不由此目录管理。

实际第二次启动前系统 MemAvailable 为 86,027,325,440 字节，请求后快照 72,258,371,584 字节；这是同时存在其它活动的系统快照，差值不能称本模型独占峰值。容器快照为 3.96 GiB / 24 GiB，cgroup 也不包括全部 CUDA 统一内存。`/metrics` 的 `gpuMemUsage` 为约 118.69–118.71 GB，未核实为单候选内存口径，不能将其当 4B 模型独占显存或峰值。请求后原 8005/8780 健康均 200、响应摘要与加载前一致。

首个候选容器因文件权限在配置解析阶段退出，容器身份和完整日志保留为 attempt-01。下载文件保持原 owner/600；容器保留 `cap-drop ALL`、`no-new-privileges`，只增加 `DAC_OVERRIDE` 以读取公开只读权重并写本候选 profile 挂载，不使用 privileged、不挂载私有凭据。无模型 AutoConfig 先确认原 SHA 文件成功识别 Qwen3Config，第二次启动随后成功，没有重试模型 POST。

必须保留镜像默认 NVIDIA entrypoint。首次绕过它的 probe/CLI 在 import 时找不到 `libnvonnxparser.so.10`；官方镜像内的库实际存在于 `/usr/local/tensorrt/lib`，保留初始化后 import 和小矩阵测试通过，没有安装其它库或修改全局配置。初始化实际启用 CUDA 13.1 forward compatibility（用户态 590.48.01、内核 driver 580.159.03）。官方镜像仍提示 torchao C++ 扩展版本不符和 ModelOpt/Transformers 版本警告；小矩阵通过不能替这些组合的模型推理背书。

只停止本目录自建且身份已核对的候选时可使用 `docker stop cizheng-trt-qwen4b`。不执行全局 prune，不清除其它模型/容器，不修改 NVIDIA 分发限制或 Docker 运行时。

## 离线验证

```bash
python3 -B -S deploy/tensorrt-llm-spark/tests/test_download_model.py
python3 -B -S deploy/tensorrt-llm-spark/tests/test_accept_text_once.py
python3 -B -S deploy/tensorrt-llm-spark/tests/test_gpu_trace.py
bash -n deploy/tensorrt-llm-spark/probe_cuda.sh
bash -n deploy/tensorrt-llm-spark/start_candidate.sh
```

2026-09-29 本机和实际 Spark stdlib 离线测试均 26 项通过，两个脚本语法检查通过。它们覆盖文件身份、原子下载、一次公开陶瓷文字请求、失败分类、容器/进程/时间窗绑定与失败快照不发布边界。离线测试与上述实际模型/CUDA 验收分别记录，不能把测试通过称为语义质量证明。
