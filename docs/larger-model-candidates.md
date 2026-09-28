# 更大视觉模型的选择与采用条件

更新：2026-09-29。当前服务继续使用原版 Qwen3-VL-8B-Instruct；报告修订的工具顺序和引用行为仍需改进。参数量本身不能证明陶瓷判断更准，当前没有独立专家样本或同条件8B/32B专业比较。

## 已实际试过的32B

Qwen3-VL-32B-Instruct 官方权重25文件、66,726,510,714字节已逐SHA核验。在Spark单模型加载、CUDA/BF16和三项合成JSON/图像顺序探针通过。一件真实双照片业务在区域语义合同处失败：1次模型调用HTTP80.329秒，无意见、NAT、StepFun或导出；并非90秒HTTP超时。失败发生在旧r10视觉合同，不能据此推论更新后的32B专业效果。候选停止，原8B恢复，权重与失败保留。[真实候选证据](../verification/nvidia/v07-workflows/candidate-32b.json)

## 优先研究的下一候选

**Qwen3-VL-30B-A3B-Instruct-FP8**。官方模型卡说明采用128块细粒度FP8，并建议vLLM或SGLang部署，正文明确当前不支持用Transformers直接加载这些FP8权重；页面自动生成的通用Transformers示例不能当作这一模型的兼容证明。项目尚未下载或部署该候选。[Qwen官方模型卡](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct-FP8)

A3B表示激活规模，不意味着只需3B模型的常驻内存。应分别记录下载字节、权重常驻、图像编码、KV缓存、工作区与运行峰值；仓库文件体积不等于Spark所需内存。FP8也须按实际硬件和后端确认，不能由‘支持Blackwell’推定特定多模态量化路径可用。

NVIDIA vLLM 25.11官方容器含CUDA13.0.2及vLLM0.11.0。项目已核对ARM64 manifest，但镜像仅部分下载、没有完成服务；不能声称已经用其推理或加速。[NVIDIA发行说明](https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-25-11.html)

TensorRT-LLM应核对对应版本中的模型、精度、GPU及功能支持，而不只看量化名称。本次已部署独立TensorRT-LLM rc13 / Qwen3-4B BF16文字服务并完成接口/CUDA验收，但没有部署其Qwen3-VL视觉路径或生成序列化TRT engine。小型文本模型不能代替本页视觉候选比较。[本次实际部署](spark-deployment-update-v08.md)。[官方支持矩阵](https://nvidia.github.io/TensorRT-LLM/reference/support-matrix.html)

## 换模型前必须验证

1. 先停止现有唯一模型，保存回滚；不要让8B与候选同时占用统一内存。
2. 逐文件核验权重，确认ARM64/CUDA/实际GPU可用；合成协议探针只能作为部署检查。
3. 固定同一组照片、任务、资料快照、Skill版本、提示及预算，保存不同模型的完整原始行为、拒绝、失败、引用和导出。
4. 用专家样本逐件检查观察、来源和判断理由；已知馆藏身份案例不能替代隐藏答案的专业验证。
5. 只有实测显示可接受的完成率、延迟和专业行为，才提升为默认模型。少量个案不报告行业准确率或稳定分位数。

当前工作顺序仍是先修复报告流程，再用专家样本验证；更大的模型作为可替换候选，避免用参数量掩盖证据和流程缺陷。
