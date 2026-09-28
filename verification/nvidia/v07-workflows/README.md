# v0.7 真实工作流与公开证据

这里记录实际 HTTP 教学案的视觉、Agent、NAT、批准文字审查、修订与导出，也保留未完成的运行。图片来自身份已知的 Met 公共馆藏；它们不是未知器物盲测、专家鉴定或模型 / Skills 效果排名。最新第 12 轮已技术 completed、两版来源任务检查通过，专业质量仍为 false。

“初稿成功”表示保存了研究意见；“技术流程完成”表示编排阶段走完；“质量通过”另要求有效来源和专业验证，不能相互替代。`source_context` 引用是馆方记载上下文，不自动赋予器物归属。NAT 身份一致也不证明来源支持观点。

| 本轮 | 实际结果 | 明确未通过的部分 | 原始结果的公开副本 |
|---|---|---|---|
| 02 | 初判 → 真实 StepFun → 本地修订 → NAT → 导出已执行 | 知识引用为空，专业质量未通过 | [summary](round-02/workflow-summary.json) |
| 03 | 同样执行至导出；实际 Nsight 限定采集首次双图生成 | 知识引用为空；性能采集不证明加速或判断质量 | [summary](round-03/workflow-summary.json)、[调用绑定](round-03/direct-call-binding.json)、[Nsight](round-03/nsight-summary.json) |
| 04 | 初稿 6 model / 13 tool，150.849 秒；1 条来源上下文引用，NAT `references_verified` | 真实 StepFun 调用 ValueError，6.413 秒 / 1,647 tokens；原始错误原因不能确证，无本地修订 | [summary](round-04/workflow-summary.json)、[failure](round-04/failure.json) |
| 05 | 初次运行 4 model / 10 tool | HTTP 500 / 原 native Schema 拒绝，无 assessment；不是超时 | [summary](round-05/workflow-summary.json)、[native diagnostic](round-05/native-failure-diagnostic.json) |
| 06 | 初稿 6 / 13，154.044 秒；1 body / 1 cite / NAT verified；StepFun 1 次成功，13.712 秒 / 3,109 tokens | 修订 7 / 16，171.131 秒，证据合同失败，无修订意见 / NAT / 导出 | [audit](round-06/authenticity-audit.json)、[summary](round-06/workflow-summary.json)、[binding](round-06/direct-call-binding.json) |
| 07 · 32B | 真实双图 1 model / 7 tool，80.329 秒；GPU 80.273 秒；原生调用直接匹配 | 区域不是合法原图归一化坐标，ValidationError；无意见 / NAT / StepFun，不是 HTTP 超时 | [audit](round-07/authenticity-audit.json)、[binding](round-07/direct-call-binding.json) |
| 08 · 8B | 1 model / 7 tool，15.776 秒；视觉请求 14.990 秒 | unstructured vision 漏必需 `region`，未进入主动作或形成意见，不是阶段提醒质量验收 | [audit](round-08/authenticity-audit.json)、[binding](round-08/direct-call-binding.json) |
| 09 | 初稿 6 / 13，146.657 秒，1 body / 1 cite / NAT verified；StepFun 14.500 秒 / 2,440 tokens；修订 10 / 18，170.917 秒，两版 6 种导出实字节验证 | 技术 completed，但修订读取正文后引用仍为 0，NAT `no_read_evidence`，来源任务与质量未通过 | [audit](round-09/authenticity-audit.json)、[binding 16/16](round-09/native-binding.json)、[lineage](round-09/derivation-manifest.json) |
| 10 | 初稿 5 / 12，111.472 秒，1 body / 1 source_context / NAT verified，3 导出实字节验证；实际单次 StepFun 18.890 秒 / 3,293 tokens | StepFun completion 达 2,500 配置上限、ValidationError `json_invalid`；无有效审查 / 修订，非 HTTP 超时；未保存明确 finish_reason，不能重建 raw 截断原因 | [audit](round-10/authenticity-audit.json)、[binding 5/5](round-10/native-binding.json)、[lineage](round-10/derivation-manifest.json) |
| 11 | 初稿 6 / 13，134.762 秒，1 body / 1 source_context / NAT verified，3 导出实字节验证；StepFun 一次 succeeded，9.252 秒 / 2,212 tokens / 3 issues | 修订 7 / 16，172.323 秒，证据合同连续失败、assessment null；无修订 NAT / 导出 / 最终引用链，非 HTTP 超时 | [audit](round-11/authenticity-audit.json)、[binding 13/13](round-11/native-binding.json)、[lineage](round-11/derivation-manifest.json) |
| 12 | 初稿 6 / 13，133.966 秒；StepFun 一次 succeeded，10.635 秒 / 2,525 tokens / 3 issues；修订 8 / 16，142.183 秒，零 validation error；两版各 1 body / 1 source_context / NAT verified，6 导出实字节验证；14/14 新增原生调用绑定 | 技术 completed、来源任务检查通过；初稿同器 Met 18.61.4 来源身份误句，修订风格依据及三个 unresolved 理由仍弱；专业质量 false、专家未验证 | [audit](round-12/authenticity-audit.json)、[quality limits](round-12/quality-limitations-audit.json)、[binding 14/14](round-12/native-binding.json)、[lineage](round-12/derivation-manifest.json) |

表内初稿 / 修订秒数来自各业务阶段，不是总闭环耗时；StepFun cached tokens 已包含在 prompt tokens 内，不额外相加。第 12 轮 helper 299.005838 秒包括两轮推理、一次文字审查、核查和导出，约 5 分钟；这是一个教学案流程记录，不是单次 GPU 延迟或统计性能基准。初稿一次来源门禁修复，修订零 validation error；程序没有替模型补写引用、意见或三个裁决。

Native 与 application 按事件次序、响应 SHA、三项 usage、图片数量和字节绑定；相同输出可能重复，不能只用单个 SHA 从历史日志挑请求。第 09 / 10 / 11 / 12 轮分别采用 16 / 5 / 13 / 14 条新增记录，分别排除 0 / 16 / 21 / 34 条历史。第 12 轮最大 HTTP 47.780226 秒 < 90 秒，全部 EOS / 原 Schema 有效，但格式和来源身份检查不能证明观点支持。

## 工程、候选与性能证据

- [r15 工程与实际部署](engineering-checks-v07.json)：全应用 913 passed / 8 skipped / 1 warning，309.15 秒；专项 403 / 6 / 1，143.49 秒。包含新增阶段 Schema 的原生回归 147 / 0 / 1，4.54 秒在 r14 实测；生产 native 与 r15 相同，服务仍为 r11。以上均 0 次 GPU 模型请求，历史 r14 fixture 3 项失败留存。
- [实际 r15 Python 文件一致性](runtime-public-python-parity.json)：核心、测试、集成文件 86/86 与实际部署清单 SHA 一致；不包含整个 Git，不衡量专业质量，文档和构建数据另行版本化。
- [32B 候选](candidate-32b.json)：官方 25 文件 / 66,726,510,714 字节、CUDA/BF16 热身与三项合成协议通过，真实双图失败后停止；当前不驻留，没有参数规模导致专业提升的结论。
- [CPU 解码重放](decoder-cpu-replay.json)：0 模型请求；私有 profiler 路径已移除，保留结构统计；不能替代 GPU benchmark。
- [Nsight 限定区间](round-03/nsight-summary.json)：2025.3.2，1 个 NVTX 区间 19.920507616 秒，144 kernel 聚合行 / 447,028 实例；原始 nsys 不公开，不宣称加速或模型质量。
- [StepFun JSON Mode 合成探针](stepfun-json-mode-probe.json)：一次 HTTP 200，4.881753 秒，295 + 567 = 862 tokens，cached 128，stop / 原 critic Schema 有效；只有公开合成四字段文字，无图片，不是业务验收。

vLLM 官方 25.11 ARM64 镜像拉取未完成，未部署；NIM 受中国区官方分发限制未下载；TensorRT-LLM、Dynamo、NeMo Retriever 未部署。[后续模型候选](../../../docs/larger-model-candidates.md)。专家样本仍在另一台电脑，未接收核验、真品率未校准，[专家验证接入](../../../docs/expert-validation-intake.md)。

## 脱敏、哈希与回查

[总公开派生清单](redaction-manifest.json)记录实际公开文件 SHA、已知原件 SHA 和派生范围。第 09–12 轮另保存原件 / 公开副本逐 SHA 的 `derivation-manifest.json`、实际源哈希复查和只读真实性 audit。第 12 轮 17 份工作流原件与原生 collector 重新读取 SHA 不变，批准的恰四字段包与 preview / prepared / executed 和实际项目序列化 SHA 一致，两张上传原图的实际字节与公开馆藏资产一致。原件被保留在私有 evidence；公开副本递归移除凭证、私有地址 / 路径、SSH 身份、原图编码、启动命令与 raw nsys。文字观点和缺失引用不由程序补写。

原始 JSON / Markdown / HTML 报告留在私有记录，对实际导出字节与 server / saved SHA 做验证后仅发布回执及 hash，不把内嵌原图 base64 放进公开证据。总清单不含自身 SHA，避免循环自绑定；发布前按实际文件字节再次核对。

[第 12 轮真实保存记录回放](../../../site/assets/cizheng-ai-replay-v07.mp4)为 80 秒静音中文图文，展示初稿、批准审查、本地修订、两版 NAT 与 6 份导出技术完成，同时保留质量 false 的局限；不是连续屏幕录制，也不是专家验收。对应 [来源清单](../../../site/assets/cizheng-ai-replay-v07.json)。[第 11 轮失败回放](../../../site/assets/cizheng-ai-replay-round11-v07.mp4)与 [原来源清单](../../../site/assets/cizheng-ai-replay-round11-v07.json)独立归档保留。163 秒 [教学界面演示](../../../site/assets/cizheng-demo-v07.mp4)未调用模型，不可与真实调用记录混为同一种证明。
