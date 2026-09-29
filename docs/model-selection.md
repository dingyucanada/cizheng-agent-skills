# 模型选择与实际结果

更新：2026-09-29。当前主视觉与动作服务继续使用 DGX Spark 上的 Qwen3-VL-8B-Instruct BF16，案卷后端为 0.7.0。官方 Spark ARM64 Model-Free NIM 的35B和27B独立视觉候选均已完成真实公开双图及完整案卷工作流，没有替换8B主视觉。主案卷资料仍走 SQLite 固定正文路径，GPU检索和 TensorRT-LLM 文字服务保留独立旁路范围。

| 当前角色 | 已完成的实际工作 | 当前决定与证据边界 |
|---|---|---|
| Qwen3-VL-8B-Instruct 主视觉 | r6保存双图观察、三项欠证意见及来源上下文引用；新增三件馆藏九轮运行、52次主模型请求，另有一次真实StepFun批准文字审查 | 继续承担主流程；四轮保存意见并等待补证、五轮停止，原文与失败保留；[模型逐轮记录](spark-models-and-reasoning-v10.md) / [新个案核查](public-collection-case-check-20260929.md) |
| Qwen3.6-35B-A3B-NVFP4 独立候选 | 官方固定权重经核验，已完成双图请求和完整案卷工作流；r1墙钟90.905秒，保存2观察、3项欠证意见 | 已完成候选实跑，未替换主视觉；公开CUDA片段绑定候选进程、请求时间窗和固定revision，限前8步，不证明整案提速或理由质量；[工作流](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/summary.json) / [CUDA证明](../verification/nvidia/qwen36-v10/deployment/gpu-profile-image-03/gpu-proof.json) |
| Qwen3.8-27B-NVFP4 独立候选 | 首轮6次真实双图调用，墙钟174.339秒，保存2观察、3项欠证意见和1条来源上下文引用 | 已完成首轮案卷工作流，未替换主视觉；原run的`weights_revision=unverified`保持原样，公开工作流未附checkpoint与候选容器进程的绑定回执；[原run](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/final-run.json) / [摘要](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/summary.json) |

35B原记录存在器型、纹饰识别错误，27B仍有花篮误作博古及官窑风格解释等问题；完成工具路径不代表理由质量提升。新三件馆藏实验使用8B，35B与27B没有加入该九轮实验，不能把两组记录混成同条件模型比较。选择依据是原图观察、引用适用范围、逐项理由、补证价值及资源占用；后续固定同一输入和预算再比较。[完整取舍及原始错误](spark-models-and-reasoning-v10.md)

## 历史部署与第12轮记录

此前归档版本采用 Qwen3-VL-8B 原生服务与 reviewed-v09 后端；r15为更早工程版本。下表及第09至12轮属于历史实验序列，StepFun只审查批准文字，原有失败和专业复核备注保持原样。

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

新公开个案已保留普通提示与Skills的相同输入、预算和合同，后续核查也记录收到的标签范围；这不构成独立专家盲评或统计质量优势。当前尚未取得该批专家材料，也没有真品率校准。接入规则见 [专家验证](expert-validation-intake.md)。部署探针与纯软件回归都不计为陶瓷能力测试。

## 当前选择与下一步

35B与27B按内存预算轮换独立NIM候选，8B继续承担业务。下一步核查固定条件下的观察、理由、来源引用和具体补证收益，并补全27B工作流的固定权重与进程身份关联；在取得可比较结果前不提升为默认模型。[更大模型候选](larger-model-candidates.md)保留各次尝试和采用条件。

此前的 Qwen3-VL-30B-A3B-FP8 路线尚无公开下载或部署记录；其已核对模型卡要求 vLLM / SGLang，不能按 Transformers 普通权重直接加载。NVIDIA NIM Qwen3-32B / NVFP4仍是未部署的纯文字候选，与上表历史 Qwen3-VL-32B 视觉试验分别记录。NVIDIA vLLM镜像未完成服务，Dynamo未部署。

官方Spark NIM保留原厂入口；独立4B文字服务的接口/CUDA验收与35B、27B视觉候选工作流分别归档。TensorRT-LLM rc13 / Qwen3-4B文字服务使用 PyTorch backend，没有序列化TRT engine；官方1B v2 embedding＋cuVS为GPU检索旁路，主案卷仍用SQLite。接口与数值验收不证明专业优劣。[技术栈及范围](technology-stack.md) · [本次部署](spark-deployment-update-v08.md) · [优化路线](model-serving-options.md)。

历史模型、旧紧凑协议和超时记录见 [NVIDIA 运行证据](../verification/nvidia/README.md)。旧轮次编号与 `v07-workflows/round-*` 属于不同实验序列，不可混写。
