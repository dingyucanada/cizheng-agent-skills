# NVIDIA 集成与复现范围

瓷证实际使用 DGX Spark / GB10 的 CUDA 视觉生成、NVIDIA NeMo Agent Toolkit 的引用身份审查，并执行了 Nsight Systems GPU 性能采集。它们分别有运行证据；没有 NVIDIA Verified、专家认证或模型质量背书。

| 项目 | 瓷证实际怎样用 | 证据 |
|---|---|---|
| Spark / PyTorch / CUDA | 原图在指定本机视觉服务生成；保存模型请求、图片数量和字节、响应 SHA 与 usage | [第 12 轮原生记录](../verification/nvidia/v07-workflows/round-12/native-requests.json) 与 [14/14 应用绑定](../verification/nvidia/v07-workflows/round-12/native-binding.json) |
| NeMo Agent Toolkit | 已选报告的资料版本、SHA、段落定位与成功读取回执核查 | [第 12 轮初稿 NAT](../verification/nvidia/v07-workflows/round-12/initial/nat-audit.json)、[修订 NAT](../verification/nvidia/v07-workflows/round-12/revision/nat-audit.json) 与 [插件](../integrations/nvidia_nat/) |
| Nsight Systems 2025.3.2 | 限定第 03 轮首个双图视觉 `cizheng.model-generate` 区间 | [公开统计](../verification/nvidia/v07-workflows/round-03/nsight-summary.json)；原始 nsys 不公开 |
| NVIDIA Skills 工具链 | 保存已有发布范围静态扫描与运行方法包记录 | [历史验证索引](../verification/nvidia/README.md)；没有官方 Verified / catalog 签名 |

NAT 只核对引用身份，不推断来源支持、实物归属或真伪。第 12 轮初稿与修订各一条 `source_context` 引用通过身份核查，批准四字段文字进入 StepFun 实际单次审查，两版各三格式导出完成。但专业质量 false：初稿同器来源身份错句保留，修订理由与风格支持仍弱，三项疑点仍 unresolved。技术流程和来源任务检查通过不能替代专业核验。[本轮质量局限](../verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json)。

## 软件回归与运行源码

实测 r15 应用 913 passed / 8 skipped / 1 warning，309.15 秒；专项 403 passed / 6 skipped / 1 warning，143.49 秒。原生生产仍为 r11；包含 8 个新增阶段 Schema 测试的 147 passed / 1 warning、4.54 秒记录实际在 r14 执行，生产代码与 r15 相同。均未请求 GPU 模型。[真实工程记录](../verification/nvidia/v07-workflows/engineering-checks-v07.json)。发布的核心、测试和集成 Python 文件另与实际 r15 清单逐 SHA 比较 86/86；未把整个 Git、文档和页面纳入模型 runtime 清单。[源码一致性](../verification/nvidia/v07-workflows/runtime-public-python-parity.json)。

工程回归覆盖权限、固定版本、读取回执、预算、幂等与导出。合成图片、脚本模型或模拟网络只测试软件合同，不能计为鉴定效果。专家材料仍在另一台电脑，尚未接收或校准；[专家接入与盲评](expert-validation-intake.md)。

## 性能证据与未部署组件

Nsight 的一个 NVTX 区间 19.920507616 秒、144 行 kernel 聚合、447,028 个实例，证明限定区间的 GPU 活动已采集，不是整案时长、利用率或提速结果。CPU 解码重放亦是无模型请求的工程诊断，私有 profiler 路径已经脱敏。[重放记录](../verification/nvidia/v07-workflows/decoder-cpu-replay.json)。

32B 官方权重已核验并实际热身，合成协议通过，但真实双图流程违反区域合同，未形成意见，已停止候选。没有同条件专业效果排名。官方 NVIDIA vLLM 25.11 ARM64 镜像未完整存在；NIM 下载受中国区官方分发限制阻止；TensorRT-LLM、Dynamo 与 NeMo Retriever 未部署。[候选与服务路线](model-serving-options.md) 和 [更大模型候选](larger-model-candidates.md)。

复现前阅读 [NAT 插件](../integrations/nvidia_nat/)、[Spark 适配器](../integrations/spark_transformers/README.md) 和 [限定范围证据](../verification/nvidia/v07-workflows/README.md)。公开副本保留原件与脱敏副本 SHA，不含密码、API key、SSH 身份、原图 base64、私有启动命令或原始 nsys。
