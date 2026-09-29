# 更大视觉模型的选择与采用条件

更新：2026-09-29。当前主视觉继续使用 Qwen3-VL-8B-Instruct BF16；35B与27B已通过独立官方Spark ARM64 Model-Free NIM入口完成真实公开双图和完整案卷工作流，均未替换8B。候选按统一内存预算轮换，当前选择以观察、引用、理由和补证结果为依据，参数量本身不能证明陶瓷判断更准。

## 已完成的35B与27B候选工作流

| 独立视觉候选 | 实际完成结果 | 身份与执行证据范围 |
|---|---|---|
| Qwen3.6-35B-A3B-NVFP4 / 8008 | r1真实双图及完整案卷流程90.905秒，保存2条观察和3项欠证意见；后续轮次和原始识别错误继续保留 | NVIDIA官方权重revision `1355db6a052410cfd62085d94b58866fd0f2c3c5`；公开前8步CUDA片段绑定候选进程和请求时间窗；[工作流原件](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/final-run.json) / [GPU证明](../verification/nvidia/qwen36-v10/deployment/gpu-profile-image-03/gpu-proof.json) |
| Qwen3.8-27B-NVFP4 / 8009 | 首轮6次真实双图调用，174.339秒；保存2观察、3项欠证意见和1条来源上下文引用 | 原run保留`weights_revision=unverified`；当前公开工作流未附固定checkpoint与容器进程的绑定回执，不由模型名补作GPU证明；[工作流原件](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/final-run.json) / [摘要](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/summary.json) |

35B公开GPU片段包含9,477个CUDA kernel事件、16,941个CUDA runtime事件和88种kernel名称，[公开重计回执](../verification/nvidia/qwen36-v10/deployment/gpu-profile-image-03/local-original-trace-recount.json)一致；片段不覆盖完整请求，也不证明整案加速或语义质量。27B已有真实服务请求和保存意见，与固定权重/GPU执行的绑定核查是两个完成条件，原有版本边界不补写。

35B仍有器型与纹饰误读，27B仍有花篮误作博古、官窑风格解释和补证理由问题。流程完成与欠证状态分别记录，不转成准确率。新三件馆藏九轮、52次主模型请求及一次StepFun文字审查使用8B；35B与27B没有参加该批实验。下一步固定输入、方法、资料、预算和身份再比较，不将不同保存版本的单例耗时称为模型提速。[完整逐轮结果与当前服务分工](spark-models-and-reasoning-v10.md) · [三件公开个案](public-collection-case-check-20260929.md)

## 历史已实际试过的32B

Qwen3-VL-32B-Instruct 官方权重25文件、66,726,510,714字节已逐SHA核验。在Spark单模型加载、CUDA/BF16和三项合成JSON/图像顺序探针通过。一件真实双照片业务在区域语义合同处失败：1次模型调用HTTP80.329秒，无意见、NAT、StepFun或导出；并非90秒HTTP超时。失败发生在旧r10视觉合同，不能据此推论更新后的32B专业效果。候选停止，原8B恢复，权重与失败保留。[真实候选证据](../verification/nvidia/v07-workflows/candidate-32b.json)

## 此前未部署的30B FP8路线

**Qwen3-VL-30B-A3B-Instruct-FP8**是此前列出的备选，公开记录尚无下载或部署，当前重点已转为上述35B/27B实际工作流核查。此前核对的官方模型卡说明采用128块细粒度FP8，并建议vLLM或SGLang部署，正文明确不支持用Transformers直接加载这些FP8权重；页面自动生成的通用Transformers示例不能当作这一模型的兼容证明。[Qwen官方模型卡](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct-FP8)

A3B表示激活规模，不意味着只需3B模型的常驻内存。应分别记录下载字节、权重常驻、图像编码、KV缓存、工作区与运行峰值；仓库文件体积不等于Spark所需内存。FP8也须按实际硬件和后端确认，不能由‘支持Blackwell’推定特定多模态量化路径可用。

NVIDIA vLLM 25.11官方容器含CUDA13.0.2及vLLM0.11.0。项目已核对ARM64 manifest，但镜像仅部分下载、没有完成服务；不能声称已经用其推理或加速。[NVIDIA发行说明](https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-25-11.html)

TensorRT-LLM应核对对应版本中的模型、精度、GPU及功能支持，而不只看量化名称。已部署的独立TensorRT-LLM rc13 / Qwen3-4B BF16文字服务完成接口/CUDA验收，使用PyTorch backend，没有部署其Qwen3-VL视觉路径或生成序列化TRT engine。NIM视觉候选复用原厂Spark ARM64 Model-Free入口，NIM文字与TensorRT文字分别验收；NVIDIA NIM Qwen3-32B / NVFP4为尚未部署的纯文字候选，与历史Qwen3-VL-32B视觉模型不是同一项。小型文本模型不能代替本页视觉候选比较。[技术栈](technology-stack.md) · [本次实际部署](spark-deployment-update-v08.md) · [官方支持矩阵](https://nvidia.github.io/TensorRT-LLM/reference/support-matrix.html)

## 换模型前必须验证

1. 区分常驻8B、案卷和独立候选；按内存准入及原保护合同只轮换获准候选，保存恢复回执，不降低原检索服务的保护阈值。历史32B的单模型加载方式不作为当前分工。
2. 逐文件核验权重，确认ARM64/CUDA/实际GPU可用；合成协议探针只能作为部署检查。
3. 固定同一组照片、任务、资料快照、Skill版本、提示及预算，保存不同模型的完整原始行为、拒绝、失败、引用和导出。
4. 用专家样本逐件检查观察、来源和判断理由；已知馆藏身份案例不能替代隐藏答案的专业验证。
5. 只有实测显示可接受的完成率、延迟和专业行为，才提升为默认模型。少量个案不报告行业准确率或稳定分位数。

当前工作顺序是逐条核查已完成工作流的原图观察、理由和补证，补齐27B固定身份关联，再用获准专家样本与同条件任务验证。8B仍承担主视觉，SQLite保留主案卷正文；GPU检索旁路不自动替换固定资料路径。已发生的错误和失败原样保存，采用候选需要实测收益。
