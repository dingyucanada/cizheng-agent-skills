# Spark 部署与验证

瓷证已在指定 DGX Spark / GB10 ARM64 节点实际执行 PyTorch / CUDA / BF16 视觉生成。当前已部署就绪的是 r15 后端配合未变化的 r11 Qwen3-VL-8B 原生适配器，保留同一数据目录和预算；就绪记录只说明对应检查时服务可用。[实际部署与工程检查](../verification/nvidia/v07-workflows/engineering-checks-v07.json)。

| 验证层 | 已执行结果 | 不代表什么 |
|---|---|---|
| r15 全应用工程回归 | 913 passed / 8 skipped / 1 warning；309.15 秒，0 GPU 模型请求 | 不衡量陶瓷判断 |
| r15 专项回归 | 403 passed / 6 skipped / 1 warning；143.49 秒，0 GPU 模型请求 | 不能替代真实 Agent 流程 |
| 原生与新增阶段 Schema 回归 | 147 passed / 1 warning；4.54 秒，0 GPU 模型请求；实际在 r14 执行，生产 native 与 r15 相同，运行服务仍为 r11 | 不证明推理速度或观察准确率 |
| 发布 Python 源码一致性 | 核心、测试与集成 86/86 文件与实际 r15 部署清单 SHA 一致 | 不是整个 Git；文档、页面与构建数据另行版本化 |
| 第 12 轮真实业务 | 初稿、一次批准文字审查、本地修订、两版 NAT 和 6 份导出已完成；两版各 1 body / 1 source_context cite | 技术 completed，专业质量 false；来源身份核查不等于专业支持或专家验证 |

部署前核对官方权重身份、解释器与依赖，使用 [原生适配器说明](../integrations/spark_transformers/README.md) 和 [Spark 配置](../deploy/serve-qwen-spark.sh)。公开仓库不包含凭证、私有启动命令、模型权重或原始性能日志。接入用户材料需要项目授权范围，不能使用此页的教学材料身份推断其它器物。

## 请求与输出合同

真实视觉和主动作已经使用受约束生成及原始完整 Schema 后校验；格式、数值坐标、引用、读取权限、工具顺序和预算继续由原宿主验证。视觉区域必须是合法原图归一化坐标，不能把未校验输出填成成功观察。格式合格不证明内容正确。

仅 guided + compact visual 路径从本次保存状态派生首 SYSTEM 与精确请求 Schema，未回应审查时禁止 record / build，未 record 时禁止 build。主 Agent 仍自主读取、補证、选择引用、写出三项裁决和理由；原来源 / 执行门禁及预算保留。原生服务验证收到的原 Schema，不独立推导应用状态；未启结构约束时只提供阶段提示，宿主门禁继续执行。r14 历史 fixture 3 项失败保留，r15 只修测试准备隔离，生产代码未因这个测试修复改变。

当前原生服务记录显式 EOS 与原 Schema 结果；对明确识别的 native deadline / token limit 等终止故障提供对应元数据。普通 provider 仍遵循原有失败合同，callback 抛错等情况可能没有完整 usage，不能声称所有期限故障都有费用或 token 明细。工程合同见实际测试，业务证据见 [逐轮运行索引](../verification/nvidia/v07-workflows/README.md)。

第 12 轮原生 6 次初稿、8 次修订与应用记录 14/14 按顺序匹配响应 SHA、三项 usage、图片数量与字节；排除前 34 条第 09–11 轮历史。最大 HTTP 47.780226 秒 < 90 秒，全部 EOS / 原 Schema 有效。运输与格式检查不能证明研究内容正确。[原生记录](../verification/nvidia/v07-workflows/round-12/native-requests.json)、[直接绑定](../verification/nvidia/v07-workflows/round-12/native-binding.json)。

StepFun 在本地预览、逐项批准后，只发送固定公开或脱敏文字包。本轮一次实际审查成功，10.635108 秒，818 + 1,707 = 2,525 tokens，cached 256 已包含在 prompt 内，返回 3 个疑点；原图未外发。主 Agent 回到本地原图与资料完成修订，三个疑点均自行裁决为 unresolved，修订零 validation error。初稿有 1 次来源门禁修复；原意见同器身份误句仍保留，修订理由与风格支持尚弱、质量 false。约 299 秒记录的是两轮推理加审查 / 核查 / 导出的单个流程，不是统计性能值。[真实性与质量记录](../verification/nvidia/v07-workflows/round-12/authenticity-audit.json)。不得自动重发已批准包或扩大任务预算掩盖失败。

## 性能、候选与专业评测

Nsight Systems 已限定采集第 03 轮首次双图生成区间 19.9205 秒，447,028 个 kernel 实例；这是实际 GPU 性能采集，不是速度提升、端到端耗时或专业效果。32B 实际加载、CUDA/BF16 和合成协议成功，真实业务失败后停止，恢复单 8B；vLLM 镜像未完整部署。[服务选择](model-serving-options.md)。

专家样本尚在另一台电脑，未接收验证；没有真品率或专家准确率。后续应固定样本、权限、同预算和盲评映射，保留失败及不足，见 [专家验证接入](expert-validation-intake.md)。
