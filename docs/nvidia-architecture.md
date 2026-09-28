# 瓷证架构与实际边界

瓷证把原图观察、固定版本资料、方法执行与意见修订放入同一案卷。公开教学页在浏览器编辑预置材料，不调用模型；专业工作台连接指定本机或 DGX Spark，按许可和预算处理实际材料。

![瓷证架构与原图、批准文字的流向](../site/assets/architecture.svg)

| 组件 | 实际职责与数据 | 已运行的范围 |
|---|---|---|
| 专业工作台 / FastAPI | 案件、输入许可、任务与模型调用 | 单人受控部署；保留运行、失败和版本 |
| DGX Spark / GB10 / PyTorch CUDA BF16 | Qwen3-VL-8B 接收本轮允许的原图或区域像素 | 已实际双图生成、受约束动作和原 Schema 后校验；记录逐请求 SHA 与 usage |
| SQLite / 原始文件 | 原图、附件、固定资料、观察及历史意见 | 原件保留，更新不改写已采用的资料版本 |
| 7 个项目自研 Skills | 按需读取方法正文与参考资源 | 工具范围、读取回执、权限与预算由宿主约束；专业增益未测 |
| SQLite 关键词 RAG | 25 条原创来源摘要及本案许可段落 | 绑定版本、文段、定位和真正送达主动作的正文；未使用 NeMo Retriever |
| NVIDIA NeMo Agent Toolkit | 核对所选报告的来源引用身份 | 固定版本、哈希、定位和成功读取凭据；不验证观点支持或真伪 |
| StepFun step-3.7-flash | 外部文字反证审查 | 只发送明确批准的公开或脱敏文字；原图与图像访问地址不发送 |
| 人工复核与导出 | 检查意见、说明待补证、交接报告与原件 | 保留历史；备注不是可信专家签名 |

原图位于服务所在本机：后端部署在笔记本时，笔记本保存原图；部署在 Spark 时，指定 Spark 项目保存和处理原图。不能把“本地处理”描述成照片在任何部署方式下都只停留于浏览器。

StepFun 路径包括本地预览、逐项批准、固定文字包和单次调用。正文的本地阅读许可不等于外发许可。项目已有第 06、09、11、12 轮真实批准文字审查成功记录；第 10 轮实际请求返回格式失败，未获有效审查。第 12 轮批准包恰为 question / claims / observations / references 四个字段，与预览、准备、实际执行及本地序列化 SHA 一致，原图和图像 URL 未发送。外部模型未看原图，不能据文字审查确认裂缝、款识或实物归属。

第 12 轮实际走完初稿 → 批准文字审查 → 本地修订 → 两版 NAT → 两版各三格式导出，技术状态 completed；两版均成功读取一段正文并保留一条 `source_context` 引用，NAT 身份核查通过。14 次新增原生调用逐 SHA / usage / 图片元数据绑定。单次整案记录约 299 秒，包含两轮推理、审查、核查与导出，不是单次 GPU 延迟或统计基准。

专业质量检查仍为 false：初稿对同件 Met 18.61.4 错写“不适用本件”；修订删去误句，但风格依据与三个 unresolved 疑点的理由尚不充分、未被专家核验。第 09 轮最终引用为空，第 10 轮文字格式失败，第 11 轮修订合同失败，均保留原记录。组件已运行、来源身份正确与专业研究质量分别说明，见 [逐轮证据索引](../verification/nvidia/v07-workflows/README.md) 与 [第 12 轮质量局限](../verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json)。

## NVIDIA 实际执行与候选

Nsight Systems 2025.3.2 已采集第 03 轮首次双图视觉请求。`cizheng.model-generate` 的一个 NVTX 区间为 19.920507616 秒，统计 144 行 kernel 聚合、447,028 个 kernel 实例。[限定区间记录](../verification/nvidia/v07-workflows/round-03/nsight-summary.json)。这是 GPU 性能采集，不是整个工作流时长、加速比例、GPU 利用率或模型质量结论；原始 nsys 文件不公开。

32B 官方 25 文件、66,726,510,714 字节权重已核验，CUDA/BF16 热身与三项合成协议通过；真实双照片流程因区域语义合同失败，尚未产生意见，候选已停止，恢复单 8B 服务。未获得专家或同条件模型比较结论。[候选证据](../verification/nvidia/v07-workflows/candidate-32b.json)。

官方 NVIDIA vLLM 25.11 ARM64 镜像拉取未完成、未部署；NIM 中国区官方分发限制阻止下载。TensorRT-LLM、Dynamo、NeMo Retriever 未部署，不列为已使用组件。候选说明见 [服务与优化选择](model-serving-options.md) 与 [更大模型候选](larger-model-candidates.md)。

## 工程证据与未完成验证

实测 r15 ARM64 全应用回归 913 passed / 8 skipped / 1 warning，309.15 秒；专项 403 passed / 6 skipped / 1 warning，143.49 秒。原生生产仍为 r11；147 passed / 1 warning、4.54 秒的原生与新增阶段 Schema 测试实际在 r14 执行，相关生产代码与 r15 相同。均为 0 次 GPU 模型请求。[工程记录](../verification/nvidia/v07-workflows/engineering-checks-v07.json) 与 [86/86 实际部署 Python 文件 SHA 一致性](../verification/nvidia/v07-workflows/runtime-public-python-parity.json)证明核心、集成与测试的限定范围，不是整个 Git 仓库，也不证明陶瓷判断质量。

仅在 guided + compact visual 路径，后端依据实际保存阶段派生首 SYSTEM 与请求 Schema，移除当前不合法的 record / build 工具：先回应审查再 record，先保存意见再 build。模型仍自主读取、补证、选择引用并写出裁决和理由；原执行 / 来源门禁和预算保留。原生服务校验收到的精确请求 Schema，不独立派生应用状态。历史 r14 的 3 项测试 fixture 失败留在工程记录，r15 修复测试隔离，没有据测试修复修改生产 Agent 或 native。

专家样本位于另一台电脑，尚未接收核验，也未完成真品率校准或有 / 无 Skills 同预算盲评。见 [专家验证接入](expert-validation-intake.md)。本项目没有 NVIDIA Verified、官方 catalog 签名、专家认证、获奖或未知器物准确率结论。
