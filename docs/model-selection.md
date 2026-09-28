# 模型选择与实际结果

当前已归档可用服务是 DGX Spark 单 Qwen3-VL-8B-Instruct 原生视觉与动作服务，配合 r15 后端。主 Agent 与视觉观察使用同一模型，StepFun 只审查批准文字。选择依据是已发生的请求、接口合同、资源占用和业务结果，参数规模不能代替专家样本表现。

| 模型或服务 | 实际证据 | 结论范围 |
|---|---|---|
| Qwen3-VL-8B-Instruct | 官方权重逐文件核验、真实 GPU 热身、双图视觉与动作生成；第 12 轮初稿 6 model / 13 tool，133.966 秒，修订 8 / 16，142.183 秒 | 两版各 1 body / 1 `source_context` 引用、NAT verified、各三格式导出；技术流程完成，专业质量未通过 |
| StepFun step-3.7-flash | 第 12 轮一次批准文字审查成功，10.635108 秒，818 + 1,707 = 2,525 tokens，cached 256，3 个疑点 | 未发送原图；是文字反证服务，不是专家认证或图片鉴定；本地修订三项均 unresolved |
| Qwen3-VL-32B-Instruct | 官方 25 文件、66,726,510,714 字节核验；实际 CUDA/BF16 热身、三项合成协议成功 | 实际双图区域合同失败，无意见、NAT 或 StepFun，候选停止；未证明优于 8B |
| 历史 Qwen3-VL-2B | 留有部署、合成协议与业务失败记录 | 保留对照，不列为当前服务或专业基准 |

资料引用绑定馆方记载上下文，并非对未知器物的鉴定证明。第 12 轮技术流程完成且两版来源任务检查通过，但初稿错写同件馆藏记录“不适用本件”；修订删除误句，风格依据和未解决疑点理由仍弱，专业质量 false。第 09 轮最终引用为空、第 10 轮 StepFun JSON 失败、第 11 轮修订合同停止，均单独保留，不把局部成功合并成质量通过。[逐轮记录](../verification/nvidia/v07-workflows/README.md) 与 [当前质量局限](../verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json)。

第 12 轮新增 14 次原生调用与应用事件逐条匹配响应 SHA、三项 usage、图片数量与字节；排除前 34 条历史记录。最大 HTTP 47.780226 秒低于 90 秒，全部 EOS、原 Schema 有效。流程约 299 秒包含两次推理阶段、一次外部文字审查、核查与导出；不能作为单次推理延迟或统计基准。[调用绑定](../verification/nvidia/v07-workflows/round-12/native-binding.json)。

## 固定模型与比较条件

模型身份采用实际下载权重 SHA 组合；官方仓库 `main` / `master` 是可变引用，不能冒充固定提交。保留图片字节、资料快照、提示、解码模式、预算和源码清单，才能解释不同运行的差异。已改变视觉合同、提示和 Schema 时，不能宣称只由参数规模或 Skills 导致结果变化。

专家材料仍在另一台电脑，当前没有独立盲评、有 / 无 Skills 同预算研究质量比较或真品率校准。接入规则见 [专家验证](expert-validation-intake.md)。部署探针与纯软件回归都不计为陶瓷能力测试。

## 服务候选

官方 30B-A3B-FP8 仅为后续候选，尚未下载或部署；其当前官方说明要求 vLLM / SGLang 路线，不能按 Transformers 普通权重直接加载。详细证据和边界由 [更大模型候选](larger-model-candidates.md)单独记录。NVIDIA vLLM 镜像未完整存在，NIM 下载受中国区官方分发限制；TensorRT-LLM、Dynamo 与 NeMo Retriever 也未部署。[优化路线](model-serving-options.md)。

历史模型、旧紧凑协议和超时记录见 [NVIDIA 运行证据](../verification/nvidia/README.md)。旧轮次编号与 `v07-workflows/round-*` 属于不同实验序列，不可混写。
