# 视觉模型选择与节点接入决策

更新：2026-09-28。结论是部署候选，不是陶瓷效果排名；尚未连接 Spark、未下载权重、未测 GPU 或专业样本。

## 决定

**新部署先试 `nvidia/Qwen3.6-35B-A3B-NVFP4`。节点已有稳定运行的 Qwen3.6 FP8 服务则先复用。** 模型由同一服务承担主 Agent 的图片推理和视觉观察工具，避免两天内维护两个大模型。StepFun 仅承担公开或获准脱敏文字的反证审查。

| 路线 | 适用情况 | 取舍与验证 |
|---|---|---|
| Qwen3.6-35B-A3B-NVFP4 | 节点需要新建服务 | NVIDIA 官方给出 Spark 配方；优先解决 ARM64/GB10 兼容及内存成本。量化对陶瓷细节的影响必须用任务图片核查 |
| Qwen3.6-35B-A3B-FP8 | 培训配方/节点已有服务 | 用户培训第三份 PDF 第9页演示此路线，65K上下文、禁用 DeepGEMM 并使用 triton；复用已验证环境有利于赶进度 |
| Qwen3-VL-8B-Instruct | 主路线不能及时启动 | 可作较小的视觉服务候选，优先跑通多图、局部与中文动作格式；未验证其 Spark 部署和本任务表现，不能声称达到主路线水平 |

官方资料确认 Qwen3.6 NVFP4 接收文本、图像与视频，并提供 Spark 专门配方；其通用基准不能推出古陶瓷最优。见 [NVIDIA 模型卡](https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4)、[Spark vLLM playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md)。FP8 属于 [Qwen 官方权重](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)，备用路线见 [Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)。

## 我们采用的工程调整

`deploy/serve-qwen-spark.sh` 是项目适配脚本，**尚未在 Spark 执行**。要求固定官方镜像 digest，而不是每次浮动升级；初始32K上下文、单并发、每次4图、主机回环端口。采用官方配方中的 FP8 KV、FlashInfer、Marlin 等候选设置，不在首次上线引入 MTP。实际容器必须支持这些参数。保留现场已经验证的版本，不能把培训中 FP8/triton 和新 NVFP4/marlin 的参数盲目拼接。

32K/单并发是本项目短流程的起点，不是官方质量推荐；官方长上下文配置更大。如果真实系统提示、参照和多图使上下文不足，按日志提高到65K，再验证内存和任务表现。温度0.1、输出上限2500属于项目动作合同；如果输出截断，需要先修订合同和回归，不将被截断的结果列为成功。

Qwen3.6 默认会进行 thinking。本项目可显式设置 `CIZHENG_DISABLE_THINKING=1`，发送 `chat_template_kwargs.enable_thinking=false`；这是 [Qwen 官方 API 示例](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) 支持的方式。对不支持该参数的已有服务不设置它。不同模式可能影响表现，探针和 A/B 两臂必须固定同一设置，不能据 JSON 接口兼容推断行为等价。

## 接入后立即执行

1. 只读检查 ARM64、驱动、CUDA、已有容器、可用内存及模型缓存，不读取或输出密钥。
2. 优先复用现有健康服务；需要新建时检查官方镜像架构、固定 digest 与模型 revision，然后执行部署脚本。记录真实版本、启动日志与实际内存，失败保留。
3. 在 Spark 运行 `python -m cizheng.model_probe --output results/probe-01.json`：JSON动作、单合成图、两图顺序三项。它只证明协议基本可用，不证明陶瓷能力。
4. 用一件公开教学案检验完整工具流程，再用专家的3–5件独立器物跑 `paired_eval`；观察图像描述、错误引用、应保留不足的主张与预算。
5. 首次服务调优只比较冷/热请求、图片负载、延迟与专业表现。记录失败和 token usage，缺失 usage 标为未知；不预写 tokens/s、准确率或“提升XX%”。
6. 若NVFP4在关键细节明显不稳且时间/内存允许，比较FP8同一任务。以专家能核查的证据定位、误收与耗时决定保留版本。

## 算力与数据位置

推荐正式演示把工作台后端、数据库及VLM放在同一 Spark 项目目录。笔记本通过 SSH 转发 `8778` 访问界面；原图只在笔记本和指定节点之间传输，由节点处理。若后端临时仍在笔记本，必须如实披露本机也保存原图，不宣称“原始数据只在盒子里”。

StepFun [官方仓库](https://github.com/stepfun-ai/Step-3.7-Flash) 给出 `step-3.7-flash` 和地区端点；中国/全球平台密钥必须匹配域名。本项目默认中国端点，不自动回退其他云服务。文字审查不是独立专家，也不能验证原图中的裂缝或款识。
