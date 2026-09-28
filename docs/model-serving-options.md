# 模型服务与优化选择

当前已经归档的服务为 Spark 上单 Qwen3-VL-8B-Instruct 原生 Transformers / PyTorch / CUDA / BF16，r15 后端配合未变化的 r11 原生适配器。已有视觉、主动作受约束生成与原 Schema 校验记录；改引擎或更大参数量尚未证明业务质量更好。

| 路线 | 本项目状态 | 接下来需要单独验证 |
|---|---|---|
| Transformers 8B | 第 12 轮技术流程完成，14 次原生请求与应用逐 SHA / usage / 图片元数据绑定，两版来源任务检查通过 | 当前意见依据和修订理由的专业质量；尚无专家验证 |
| Transformers 32B BF16 | 官方 25 文件 / 66.73 GB 核验、CUDA 热身与三项合成协议成功；真实双图流程失败后停止 | 新视觉合同下的独立实际流程，固定条件的专业比较 |
| 官方 NVIDIA vLLM 25.11 ARM64 | 镜像拉取随专属会话退出而停止，镜像尚未完整存在，未部署 | 镜像 digest、平台、真实模型及图片 / 完整 Schema / 内存 / 耗时 |
| NIM | 中国区官方分发限制阻止下载，未部署 | 官方允许的分发与对应模型 / 硬件配置 |
| TensorRT-LLM / Dynamo | 未部署 | 对应 Qwen3-VL checkpoint、GB10、精度及完整业务，不据通用支持表推断 |
| NeMo Retriever | 未部署；当前仍为 SQLite 中文关键词 RAG | 专家相关段落、Recall@k / 错误引用 / 耗时及同机峰值内存 |

32B 权重与失败保留，当前不驻留。替换旧 profile 子进程时专属 tmux 会话同时意外退出；节点未重启，已查 kernel journal 未发现 OOM 匹配，原因不能确证。不能写成确诊 OOM、主动完成镜像拉取或部署成功。[候选原始边界](../verification/nvidia/v07-workflows/candidate-32b.json)。

## 用实际测量选择优化

Nsight Systems 2025.3.2 真正采集了第 03 轮首个双图生成，NVTX 一个区间 19.920507616 秒，144 行 kernel 聚合 / 447,028 实例。此数据只描述限定范围，不表示端到端耗时、GPU 利用率、加速或观察质量。[采集统计](../verification/nvidia/v07-workflows/round-03/nsight-summary.json)。CPU 解码重放是无模型请求的工程诊断，不能代替真实 GPU benchmark；其私有路径已脱敏。[重放记录](../verification/nvidia/v07-workflows/decoder-cpu-replay.json)。

任何候选都先保留图片、权重、提示、Schema、输出长度和预算，分别记录初始化、CPU 前缀工作、GPU 区间与 HTTP 时长。更换服务需要重新验证本项目完整数值、权限、工具、引用与终止合同；格式正确不等于专业判断正确。不得通过放宽预算、填补模型意见或自动补引用伪造成功。

## 更大候选与兼容性

官方 30B-A3B-FP8 仅是规划，未下载或部署。其官方说明当前不能按 Transformers 普通权重直接加载，建议 vLLM / SGLang；相关正文与 NVIDIA 25.11 发行说明见 [更大模型候选](larger-model-candidates.md)。vLLM 0.11.0 已注册 VL / MoE 架构，不能把没有在本项目部署误写成架构未注册。

通用多模态或硬件支持表不证明指定 checkpoint × GB10 × 精度组合已经验收。官方资料：[Qwen3-VL-32B 模型卡](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct)、[NVIDIA Spark vLLM](https://build.nvidia.com/spark/vllm/instructions)、[Spark SGLang](https://build.nvidia.com/spark/sglang/instructions)、[TRT-LLM 固定 rc18 多模态矩阵](https://nvidia.github.io/TensorRT-LLM/1.3.0rc18/models/supported-models.html#multimodal-feature-support-matrix-pytorch-backend)。采用前必须按实际固定版本与本项目条件再测。

专家样本尚未接收，没有 8B / 32B 专业排名、真品率或 Skills 增益。[逐轮真实结果](../verification/nvidia/v07-workflows/README.md)、[工程检查](../verification/nvidia/v07-workflows/engineering-checks-v07.json) 与 [专家验证接入](expert-validation-intake.md)分别说明不同验证范围。
