# NIM v09：公开文字核查候选已实部署

核验日期：2026-09-29。独立 NVIDIA NIM 服务已在 Spark 启动，并完成一次公开陶瓷文字请求及绑定该请求的 CUDA 核验。它的职责是**公开资料文字归纳与证据边界核查**；当前仍是独立候选，主报告工作流没有切换到该接口。

模型为纯文本 `Qwen/Qwen3-4B-Instruct-2507` BF16，接口仅监听 `127.0.0.1:8007`。本轮没有给它发送照片，也没有改动 `8005` 视觉主模型、`8780` 后端、`8006` TensorRT-LLM 或 `8003` Retriever。

## 实际验收与输出边界

唯一公开请求提供 [Met Bottle 79.2.467 的公开目录摘要](https://www.metmuseum.org/art/collection/search/48559)，另列一个缺少照片、底款、尺寸、来源及检测资料的未知器物归属主张，要求区分馆方记载与独立物证，指出两项待补证材料。没有私有图像或未经批准文字。

| 实测项 | 结果 |
| --- | --- |
| NIM 就绪、健康、模型列表 | 均 HTTP 200；模型 ID 精确为 `Qwen3-4B-Instruct-2507` |
| 唯一生成请求 | HTTP 200，`finish_reason=stop`，零自动重试 |
| 用量 | 213 prompt + 81 completion = 294 tokens；输出 115 字符 |
| 请求耗时 | 7.131013910 秒，**包含 profiler 开销** |
| CUDA 实证 | 前 8 个执行步骤：3,645 kernel 事件、37 种 kernel 名、5,639 CUDA runtime 事件 |
| 请求归属 | 固定镜像、同一容器与进程、原请求/响应 SHA、时间窗均绑定通过 |
| 验收后共存 | 既有四个服务与 NIM 健康均 200；MemAvailable 53,144,883,200 bytes，约 49.50 GiB |

原始 [请求](../evidence/nim-v09/public-text-once/claimed.json)、[模型响应](../evidence/nim-v09/public-text-once/response.raw.json)、[接口回执](../evidence/nim-v09/public-text-once/receipt.json)、[CUDA 摘要](../evidence/nim-v09/gpu-trace-summary.json)及 [共存记录](../evidence/nim-v09/final-coexistence.json)固定保存，未修改模型输出。

输出有专业与指令遵循局限：模型把馆方记载称作“属独立实物证据”，仅凭本轮提供的目录文字，这一表述需要专业复核；它也列出四项补证材料，而不是所求两项。因此本轮证明的是**原厂 NIM 文本接口及 GPU 执行实际运行**，不能据此证明鉴定准确率、主报告质量或专家认可。8 步 trace 不覆盖整个请求；未测 GPU 利用率，也不是与现有视觉模型或 TensorRT-LLM 的速度对照。

## 合法分发与实际身份

路线来自 [NVIDIA 官方中国 NIM 分发伙伴目录](https://catalog.ngc.nvidia.com/china-nim-distributors)，选用 [TGC 的公开 Spark 条目](https://tgc.turing-agi.com/nim/100372)。[同站匿名目录 API](https://tgc.turing-agi.com/tgc/api/resources/100372)标明 `PUBLIC`、`DGX Spark`、`LINUX / ARM64` 与免注册地址。匿名 manifest、完整下载、实际本地镜像及原入口均已核对；没有区域代理、非官方镜像、新账号或 NGC/HF 密钥。

| 固定项 | 值 |
| --- | --- |
| 伙伴发布标签 | `SGLang Model-Free NIM spark:2.1.8` |
| 分发镜像 | `tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark` |
| 实际 manifest digest | `sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9` |
| 实际 config/image ID | `sha256:7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef` |
| 平台 | `linux/arm64`；GB10 compute capability 12.1；driver 580.159.03 |
| 压缩层合计 | 11,503,898,101 bytes；111 manifest 条目，106 独立层 |
| 本地 Docker image size | 21,797,240,962 bytes；不是 GPU 峰值内存 |
| 原入口 | `/opt/nim/start_server.sh`；实际 SHA `bc8c7cca428dc1eb843752b518df7e8b5ecad747e315a764f9fb5512137f2e26` |
| 实际组件 | nim-stack 0.1.0、nim_sdk 0.12.7、nimlib 0.18.1、SGLang 0.5.16、Torch 2.11.0+cu130、Transformers 5.12.1 |

目录 API 原始响应 SHA 为 `621701148bd094fe7e66e05966342ad165417d420fe87effc10320b131cb97f7`。发布标签与组件版本是不同口径。[现场软件身份](../evidence/nim-v09/software-identity.json)和共存记录同时确认 NVIDIA `nim_stack.start_server`、NGINX 与 SGLang scheduler 实际存在；保留原 NIM 入口，没有把直接启动的开源 SGLang 改名为 NIM。

## 隔离配置、失败记录与复现

使用此前完成的官方 Qwen 纯文本权重：14 文件、8,060,918,292 bytes，启动前按固定 [模型清单](../evidence/nim-v09/public-model-manifest.json)逐文件重新校验，只读挂载。脚本要求至少 32 GiB MemAvailable、四个既有服务健康及候选端口空闲；24 GiB cgroup、4096 上下文/总 token 缓存上限、单并发、`mem-fraction-static=0.25`、关闭 CUDA graph。统一内存不能仅凭 cgroup 或 Docker memory usage 推算，故另读宿主 MemAvailable。实际验收后 Docker 口径为 `4.714GiB / 24GiB`，不是该服务的 GPU 峰值。

首次三次启动都在模型加载前退出、非 OOM、未发生成请求：依次定位到缓存目录 owner 权限、SDK 默认配置目录权限、未登记容器 UID 导致 `getpwuid` 失败及随后重复导入。最终仅用候选专属缓存、NGINX 和从固定镜像复制的配置目录；显式 HOME，给镜像账户文件副本增加合成 UID/GID 条目并只读挂载。没有读取宿主账户文件、改动 SDK/SGLang 源码、改变原权重权限或增加 capability；实际 `cap-drop=ALL`、`no-new-privileges`。前三个失败容器及完整私有日志保留，见 [失败摘要](../evidence/nim-v09/failed-attempts-summary.json)。

验收时 NIM 的公开 `/start_profile` 返回 404，尚未发模型请求即停止该步骤。随后在**同一个 NIM 容器的内部 loopback:8001**启用 SGLang 8 步 profiler，生成请求仍经原厂 NGINX:8007。该内部端口没有映射给宿主公网。保留 [profiler arm 回执](../evidence/nim-v09/profile-arm.json)及公开路由失败记录；最终 CUDA 核验不靠一个成功状态码单独证明，而要求真实 kernel/runtime、稳定进程、时间窗与原始 SHA 全部匹配。

独立部署代码位于 [deploy/nim-spark-v09](../deploy/nim-spark-v09/start_candidate.sh)。在项目已有四个服务、经授权的本地模型和 CDI GPU 设备就绪的节点，可执行：

```bash
bash deploy/nim-spark-v09/start_candidate.sh PUBLIC_MODEL_DIR VERIFIED_MODEL_RECEIPT EVIDENCE_DIR
```

脚本拒绝占用已有候选、修改失败快照或停现有服务；重现新候选可显式指定受限的 `NIM_CANDIDATE_NAME=cizheng-nim-qwen4b-v09-attempt-NN`。等真实 ready 与精确模型 ID 后，使用 `accept_text_once.py --evidence-directory NEW_REQUEST_EVIDENCE_DIR`；该客户端有独占 claim，失败也不自动重发。需要 CUDA 绑定核验时，按 `verify_gpu_trace.py` 的 CLI 保存前后身份，并保存内部 profiler 的 HTTP 200 arm 回执（精确请求为 `{"output_dir":"/evidence","num_steps":8,"start_step":0,"activities":["CPU","GPU"]}`），再给定原始 trace、回执与时间窗进行核验。

最终 6 个作者运行文件与远端实际 runtime-05 逐字节/SHA 一致，固定 [源码清单](../evidence/nim-v09/source-manifest.json) SHA `e7318938f2cbdf21fed45ceceea0d4d4deb731779dc48297f3c488dcf523002c`；Spark 实跑 **23 个离线合同测试通过**，与应用/native 全量回归不是同一组测试。另有原入口 show-build-info、无模型小 CUDA matmul、缓存/NGINX CPU 检查和 Torch/SGLang CPU 导入的现场证据。

本次完整镜像拉取耗时 **18 分 53 秒**；最终容器启动至首次观察 ready 约 **134 秒**（含检查间隔），从本次镜像拉取开始至唯一请求完成约 **37 分 37 秒**，含前三次已留证的 CPU 配置诊断。这些是此次现场耗时，不是未来下载保证。公开文字归纳已有 TensorRT-LLM:8006 可独立承担；本轮新增 NIM:8007 的真实独立接口，不应据框架数量承诺报告速度或鉴定质量。

## 官方资料与适用范围

- [用户给定的 NVIDIA NIM 页面](https://developer.nvidia.com/nim?sortBy=developer_learning_library%2Fsort%2Ffeatured_in.nim%3Adesc%2Ctitle%3Aasc)与 [Build 探索入口](https://build.nvidia.com/explore/discover)：发现入口，推荐型号不等于本节点共存容量满足。
- [NVIDIA 当前安装文档](https://docs.nvidia.com/nim/large-language-models/latest/get-started/installation.html)，更新 2026-09-24：符合条件的公开 LLM/VLM 可 keyless 下载；不覆盖所有 NIM，也不解除中国分发条件。
- [NVIDIA Model-Free NIM 说明](https://docs.nvidia.com/nim/large-language-models/latest/deployment/model-free-nim.html)，更新 2026-09-24：可使用预先放置的本地模型，仍需后端支持其架构。
- [NVIDIA 支持矩阵](https://docs.nvidia.com/nim/large-language-models/latest/reference/support-matrix.html)：GB10 出现在 vLLM Model-Free 验证表；不能把此后端表移用为 SGLang/Qwen4B 的官方认证。本轮另有 Spark 专属条目、实际 ARM64 manifest 与具体组合实跑。
- [TGC 使用说明](https://nim-wiki.turing-agi.com/model-free-nim/sglang-model-free-nim/basic_usage_sglang)：伙伴正文交叉引用；现场行为仍以固定镜像为准。
- [SGLang 官方 profiling 说明](https://github.com/sgl-project/sglang/blob/main/docs/docs/developer_guide/benchmark_and_profiling.mdx)：有限步骤采集；本轮按实际 0.5.16 OpenAPI 核对字段。

原始服务器日志、厂商闭源脚本和 raw trace 留在私有目录；[公开证据清单](../evidence/nim-v09/index.json)只包含脱敏身份、统计、获授权公开文字和 SHA。CUDA trace SHA 为 `b439786c1dc58e44a7cae6342b07a0bde94b4923c9f647363e4f947bf875c7c6`，不把私有 trace 当成已公开下载的文件。
