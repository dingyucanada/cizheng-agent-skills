# Spark 模型升级和逐条理由核查

这次改进围绕两项工作：保持常驻业务并按内存预算轮换较大的视觉候选模型；把报告中的观察、理由、引用分开核查。升级依据是固定照片上的真实工作流、内存和理由质量，不按参数大小替换模型。

## 三种候选怎样取舍

| 候选 | 适合承担的工作 | 当前决定 |
|---|---|---|
| NVIDIA NIM Qwen3-32B / NVFP4 | 文字资料整理和文字复核；不是视觉模型 | 尚未部署的纯文字候选，不承担照片判断 |
| Qwen3.6-35B-A3B / 官方 NVIDIA NVFP4 | 原生多模态 MoE，35B 总参数、约3B激活；观察和理由生成候选 | 独立 NIM 服务实际加载，已完成双图请求与完整工作流；未替换8B主视觉 |
| Qwen3.8-27B / 官方 NVIDIA NVFP4 | 稠密多模态候选，适合后续与同一协议对照 | 19文件SHA与CPU检查通过；后续已完成首轮6次双图工作流调用，保留纹饰错误与欠证意见；未替换8B主视觉 |

官方 vLLM GB10 配方可作为另一条推理后端路线。本轮先复用节点已安装的官方 Spark ARM64 Model-Free NIM 镜像，减少额外镜像传输，保留原厂入口。NIM 接口部署不自动证明专业判断质量；CPU 兼容性检查也不证明 GPU 内核成功。

35B固定服务采用Marlin的NVFP4 W4A16 fallback路径，原厂NIM入口、权重版本和实际后端分别留档；GPU核查用于验证执行与请求关联，性能收益须另行测量。[固定配置与后端范围](../deploy/qwen36-candidate/README.md)

服务分为**常驻业务与按内存轮换的独立NIM候选**：Qwen3-VL-8B 在8005承担主视觉，案卷后端8780保留20个已有案件；TensorRT-LLM文字8006和 NVIDIA Embedding＋cuVS Retriever 8003为已部署旁路。4B NIM文字8007与35B视觉8008均保留已完成验收原件；35B已停止，4B在首次27B加载保护停止后按原合同恢复。[2026-09-29 09:22:53 UTC历史健康快照](../verification/nvidia/qwen38-v11/old4b-restoration-01/ready-receipt.json)中的五项服务均HTTP 200；该时间对应已公开回执，后续在线状态与实验分别核查。当前在线状态和已完成实验分别记录，不按20B / 30B参数档位推定更准确。[当前中文角色图](../site/report-assets/product-roles-v11.svg)

### 内存保护与实际轮换

35B加载后，Retriever的原32GiB内存保护看门狗在可用内存低于阈值时正常退出，没有发生OOM。停35B后，原CUDA 1B索引服务已恢复，25个原段落ID保持不变。首次27B试验前仅受控停止独立4B NIM；新`qwen38-candidate-v11`使用60GiB准入、34GiB缓冲、0.5秒检查，旧32GiB保护未弱化。隔离GPU容器于2026-09-29 09:12:35 UTC启动，69.6519秒时可用内存最低36,448,845,824字节（约33.95GiB），触发34GiB保护，只停止精确绑定的新候选。四项常驻业务保持HTTP 200，4B NIM随后恢复；候选未就绪、未发送模型HTTP请求，不能算部署成功。v12仅关闭多线程权重加载`enable_multithread_load=false`，也触发34GiB保护停止。v13使用19文件的平铺hardlink视图与相同串行配置，在准入检查阶段被拒绝，未启动候选容器；[公开预检查元数据](../verification/nvidia/qwen38-v11/flat-attempt-v13-03/preflight-metadata.json)保留。后续27B首轮6次真实调用与保存意见另列，不把工作流完成混作GPU执行片段或最终恢复回执。[隔离候选配置与保护范围](../deploy/qwen38-candidate-v11/README.md)

## 模型表现怎样比较

模型对照先固定同一组照片、获准资料、代码与提示版本，再分别记录下面几类表现。流程完成和意见质量分开，欠证意见也可以有清楚理由；失败、遗漏和无法评估的项目保留。

| 观察的方面 | 核对的问题 | 保存的材料与比较范围 |
|---|---|---|
| 流程完成 | 是否取得观察、保存意见并完成规定工具步骤？失败发生在哪一步？ | 原始状态、请求与输出、失败原因、调用预算；未保存意见的轮次不进入意见正确性分母 |
| 图像观察 | 器形与纹饰描述是否来自原图？解释或未知条件是否混入可见事实？ | 输入SHA、模型原文、区域和实际看图阅评；上传者标签与馆藏记载不能替代像素 |
| 引用支持 | 正文是否实际送达？支持的是来源陈述，还是本件推断？ | 固定快照、许可、段落与送达片段；逐目标映射，分开来源身份和语义支持 |
| 判断理由 | 是否说明可见依据、推断连接、竞争解释及能改变意见的缺证？ | 每项候选原理由与逐项阅评；不因肯定回答或一律拒判获得通过 |
| 补证价值 | 建议是否针对本轮确实缺少的材料？是否预设了不存在的款识、状况或检查结果？ | 已有输入覆盖、下一项具体采集及复核记录；建议不冒称已完成的检查 |
| 资源与服务 | 此轮墙钟、请求量、上下文和内存如何？哪些服务当前在线？ | 同版配置、单例耗时、GPU片段及服务状态；另测吞吐与整案性能，隔离候选按预算轮换 |

公开Met双图用于流程与错因研究，AI阅评标明实际图像访问和共享开发上下文。专家材料尚未取得，因此当前不报告独立专家准确率或真品概率。逐条核查包是阅评材料，空白模板不是已通过的标签。

## 已完成的本轮工程工作

- 固定 `nvidia/Qwen3.6-35B-A3B-NVFP4` 的 revision `1355db6a052410cfd62085d94b58866fd0f2c3c5`，17文件、23,462,477,857字节。实际下载后逐文件核对官方 LFS SHA256 / Git blob SHA1；保留中断恢复与最终收据。
- 主工作台的真实双图报告需要约1.5万 prompt tokens，因此候选设置24,576上下文和token池、单并发、两图及有限像素，保持40GiB容器上限。8k配置仅能通过配置检查，不能承载完整案卷。
- 按 GB10 的统一内存和 SGLang 的实际公式设置内存比例，记录加载期间余量；27B的新保护只停止绑定候选，原Retriever保护保持。
- 官方 Spark ARM64 Model-Free NIM 已完成实际双图预热和35B首轮案卷流程；保留九份请求、最终意见、输入SHA与源码清单。[原始字节索引](../verification/nvidia/qwen36-v10/current-original-index.json)分列部署、权重、CPU配置检查和实际请求，不把CPU检查当成GPU请求证据。
- 35B双图请求已另行绑定候选进程与请求时间窗，实际8步Profiler片段包含9,477个CUDA kernel事件、16,941个CUDA runtime事件和88种kernel名称。15,273,908字节原始trace的本机逐事件重计一致；[GPU执行证明](../verification/nvidia/qwen36-v10/deployment/gpu-profile-image-03/gpu-proof.json)与[重计记录](../verification/nvidia/qwen36-v10/deployment/gpu-profile-image-03/local-original-trace-recount.json)保留范围。该片段不覆盖全请求，不证明整案加速或语义质量。
- 理由核查模块拆分逐图可见描述、判断主张、观察关联、资料目标和四项理由量表。没有独立标签时分数为空，不默认通过。
- 只读核查接口和报告页已部署到 Spark 工作台；已公开的`source-v07-runtime-v11-claims-20260929`运行包包含92文件，包含冻结正文承诺验证和提示配置保护。20个已有案件与原视觉模型身份保持，实际已保存run的核查API通过。

## 公开双图记录说明了什么

相同公开照片的8B r2实际完成117.386秒，形成两条观察和三项欠证意见。来源段落已准确送达，馆方文字转述可从正文回查；这不代表具体年代、窑口或“与参照相似”的理由都成立。实际AI阅评将来源陈述和本件推断分别记录，没有删除原始错误或重写模型原文。

35B r1实际完成90.905秒，保存两条观察和三项欠证意见。其原始可见描述写出“青花六方笔筒”和“博古图、边饰缠枝莲”，存在器型、纹饰识别错误；最终未保存知识引用，时期、窑口和风格均为“未能判断”。完整流程完成只证明此次服务与工具路径跑通，不能据此认定理由质量提升。[35B原始意见](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/final-run.json) · [运行摘要](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/summary.json)

上述耗时是各自保存版本上的单例端到端墙钟记录，不代表器物准确率、吞吐、独立专家评估或同预算统计比较。原始提示、Skills、源码、模型身份与逐请求版本保留，失败轮次也保留；后续提示改进须另起轮次，不能覆盖这两份记录。

### 保存轮次与实际表现

| 模型 / 轮次 | 原始状态 / 单例耗时 | 请求与保存结果 | 此轮需要核查的具体问题 | 原件 |
|---|---|---|---|---|
| 8B / r2 | 等待补证 / 117.386秒 | 5请求、2观察、3项欠证意见、1引用 | 来源转述可回查；未看参照图却称相似，归属理由仍缺支持 | [意见](../verification/nvidia/qwen36-v10/workflows/main8b-r2/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/main8b-r2/summary.json) |
| 35B / r1 | 等待补证 / 90.905秒 | 9请求、2观察、3项欠证意见、0引用 | 器型与纹饰识别错误，最后均未能判断 | [意见](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/qwen36-r1/summary.json) |
| 8B / r3 | 失败 / 148.669秒 | 7请求、2观察、未保存意见 | 模型动作连续不符合证据合同，保留失败 | [原件](../verification/nvidia/qwen36-v10/workflows/main8b-r3/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/main8b-r3/summary.json) |
| 35B / r2 | 等待补证 / 123.653秒 | 10请求、2观察、3项欠证意见、1引用 | 来源句被60字符上限截断；康熙 / 景德镇推断缺支持，未见底款与修足却提出具体假说 | [意见](../verification/nvidia/qwen36-v10/workflows/qwen36-r2/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/qwen36-r2/summary.json) |
| 8B / r4 | 失败 / 178.579秒 | 5请求、未保存意见 | 来源明示转述却未附必要引用，同参数动作两次被合同拒绝 | [原件](../verification/nvidia/qwen36-v10/workflows/main8b-r4/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/main8b-r4/summary.json) |
| 35B / r3 | 等待补证 / 116.862秒 | 10请求、3项未能判断意见、1来源上下文引用 | 来源背景表述完整；第二图花篮仍被称博古，风格与补证理由仍欠区分特征 | [意见](../verification/nvidia/qwen36-v10/workflows/qwen36-r3/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/qwen36-r3/summary.json) |
| 8B / r5 | 失败 / 119.695秒 | 5请求、2观察、未保存意见 | 两次说明馆方记载范围却未附引用；第二次增加“未采用资料陈述”，仍未补上来源依据 | [原件](../verification/nvidia/qwen36-v10/workflows/main8b-r5/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/main8b-r5/summary.json) |
| 8B / r6 | 等待补证 / 109.059秒（墙钟） | 5请求、2观察、3项欠证意见、1来源上下文引用 | 首次保存意见即有引用，无修复或校验错误事件；参照相似、窑口理由及补证价值仍待逐项阅评 | [意见](../verification/nvidia/qwen36-v10/workflows/main8b-r6/final-run.json) · [摘要](../verification/nvidia/qwen36-v10/workflows/main8b-r6/summary.json) |
| 27B / r1 | 等待补证 / 174.339秒（墙钟） | 6请求均stop、2观察、3项欠证意见、1来源上下文引用 | 来源引用先已提交；风格判断被原合同拒绝后改欠证，仍有官窑解释及花篮误作博古问题 | [意见](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/final-run.json) · [摘要](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/summary.json) |

以上是同一公开器物、两张照片的重复试跑，不是九个独立样本。首次8B r1接口失败0.528秒、未保存意见，也保留[原件](../verification/nvidia/qwen36-v10/workflows/main8b-r1/final-run.json)。8B r4与35B r3运行时与27B权重组装 / 下载共存，不能据此公平比较模型速度。等待补证表示意见已经保存，不表示质量通过；失败轮次不填意见正确率。

同版对照的8B r4 / 35B r3使用68文件的[`source-r4`冻结清单](../verification/nvidia/qwen36-v10/workflows/qwen36-r3/source-snapshot-manifest.json)，整体SHA256为`c7e385281f5ffa04fecb80c40913ed961c9d25c732e662cfc6ef674c633ec0be`。35B保存了完整来源背景：“Met馆藏18.61.4记录为康熙早期景德镇青花，仅针对该馆藏，不自动赋于本件”，该引用支持来源陈述。第二图纹饰、清代风格区分和康熙 / 仿品补证特征仍需核查，不能称为专业验证或模型质量升级。生产默认提示保留`source-r2`；`source-r4`通过显式试验配置使用，未自动推广到主视觉。[r2至r5完整公开输入源码包及SHA索引](../verification/nvidia/qwen36-v10/source-snapshots/index.json)保留原始字节，源码冻结与生产采用分别记录。

追加的8B r5使用69文件的[`source-r5`源码冻结清单](../verification/nvidia/qwen36-v10/workflows/main8b-r5/source-snapshot-manifest.json)与默认`source-r2`提示配置，119.695秒后失败，保存2条观察，`assessment=null`。第4、5次请求的来源范围说明均没有引用，第二次增加“未采用资料陈述”也没有修正该缺口；提出的意见未进入已保存结果。提示配置身份与源码快照分别记录，默认配置不表示稳定性或专业质量已通过。

8B r6墙钟109.059秒、run内部109.032秒，保存2条观察和意见，状态为等待补证。69文件的[`source-r6`冻结清单](../verification/nvidia/qwen36-v10/sources/source-r6/snapshot-manifest.json)SHA256为`5423614a5763813fb349aa1b70d01b8d75fb2809d8148240161a1de447332874`，与r5相比仅`agent.py`的错误反馈改变；[完整源码包与收据](../verification/nvidia/qwen36-v10/sources/source-r6/archive-receipt.json)另存。r5与r6的默认`source-r2`提示内容、工具schema与阶段合同相同。r6在第4次请求首次调用`record_assessment`时已提交`read_index=1`、`use=source_context`引用，整轮没有`repair`或`validation_error`事件，因此不能说错误反馈被触发、造成这次完成或已经改善质量。来源上下文支持馆方记载；原理由中的参照相似、景德镇特征及补证价值须另行逐项阅评。AI复核与专家评审分别记录，不以这一次完成计算准确率。

27B首轮`run_3ee283431af842fb91662bf258e8897b`墙钟174.339秒、run内部174.304秒，采用同一`source-r5`源码与默认`source-r2`提示，保留[项目整理的源码绑定（非模型原答）](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/source-binding.json)。6次调用均正常stop，保存2条观察、3项欠证意见和1条来源上下文引用。第4次`record_assessment`已经提交`read_index=1/use=source_context`，但`style=supported`因缺少已查看参照而被原证据合同拒绝；第5次改为`insufficient`后保存。它使用r5源码，不能说是r6引用反馈的效果。时期与窑口均写“未能判断”，但原观察仍写“典型清代官窑风格”，第二图花篮被描述为“瓶、书卷”博古；风格候选也沿用该错误。欠证状态并不自动证明观察或理由正确，这一次完成不足以替换8B或计算准确率。原run的`weights_revision=unverified`原样保留；本轮公开工作流尚未附固定checkpoint与容器进程的绑定回执，不能只从模型名推定该检查已经完成。[逐项AI阅评](../verification/nvidia/qwen38-v11/ai-reviews/qwen38-r1/analysis.md)实际查看SHA匹配的两张公开原图，但共享开发上下文，非盲评、非专家，不汇总为专业正确率。

这组输入包含项目整理的公开馆藏记录，目的为检查来源适用边界和完整报告流程，不能作为未知器物断代准确率测试。AI阅评共享开发上下文；专家答案和专家身份未获得，不称为专家验证。

核查包先验证知识快照整体承诺、所属run的同版承诺、来源与段落唯一性、段落归属和文本哈希，再导出实际送达的许可正文。旧公开round12包的承诺不一致保留为诊断，不能用其正文作新的支持评分；其历史记录不被重写。

## 专家样本及研究路线

用户提供的专家Google Drive图片目录尚未连通，在本机和Spark直接访问均超时，实际下载0张，暂无该批专家标注。专家验证按授权样本、独立标签、固定输入和保留集开展；公开Met教学图不替代该批专家材料。

[机构联合训练和桌面采集箱](research-roadmap-20260929.md)是研究路线：先核实训练许可和专家纠错，按器物分组保留集，再研究离线微调、NVIDIA FLARE 多机构训练和后训练。采集箱先验证光照、色卡、尺度、重复性与多视角对应。逐条理由的现有功能用于审阅观察、依据、反例、补证和冻结正文；审核后的订正才能形成拟议训练材料。反馈不直接改写生产模型，尚未建立联邦网络或实物箱体。

## 复现入口

- [35B 独立候选部署](../deploy/qwen36-candidate/README.md)
- [逐条理由核查协议](../evals/CLAIM-SUPPORT-AUDIT.md)
- [图文报告：观察、候选理由与引用入口](https://dingyucanada.github.io/cizheng-agent-skills/report.html#reasoning-audit)
- [原始部署、双图与35B工作流收据索引](../verification/nvidia/qwen36-v10/current-original-index.json)
- [公开原始工作流和AI阅评](../verification/nvidia/qwen36-v10/workflows/)
- [r2至r5完整公开输入源码包](../verification/nvidia/qwen36-v10/source-snapshots/index.json)
- [27B首轮原件：2条观察、候选理由与来源](../verification/nvidia/qwen38-v11/workflows/qwen38-r1/) · [AI阅评（非专家、非盲评）](../verification/nvidia/qwen38-v11/ai-reviews/qwen38-r1/analysis.md)
- [r6完整源码包](../verification/nvidia/qwen36-v10/sources/source-r6/source-files.tar.gz) · [冻结清单与SHA](../verification/nvidia/qwen36-v10/sources/source-r6/snapshot-manifest.json)
- [NVIDIA Qwen3-32B Spark 支持表](https://docs.nvidia.com/nim/large-language-models/1.14.0/supported-models.html#qwen3-32b-dgx-spark)
- [vLLM Qwen3.6 GB10 官方配方](https://recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B?hardware=dgx_spark_gb10&features=tool_calling%2Creasoning)
- [Qwen3.8-27B 官方模型](https://huggingface.co/Qwen/Qwen3.8-27B)
