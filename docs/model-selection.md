# 视觉模型选择与节点接入决策


最新完整第05轮已实际失败：4次模型、10次工具、服务端136.052秒。两张原图产生实际观察，协调器按本轮观察加载青花方法；下一主动作90秒超时，没有AI报告、该报告的NAT核查、StepFun反证或修订导出。固定文字格式合成探针也90秒超时，155.686秒晚到结构合格记录只按独占窗口关联。当前ARM开发源码129项流程CPU合同通过，不能替代以上业务失败。最新版本和证据见[当前状态](../STATUS.md)、[第05轮](../verification/nvidia/compact-workflow-05/README.md)。

更新：2026-09-28。Spark上的2B与8B均已实际GPU生成。8B通过三项原始协议探针，但在旧版主Agent双照片流程中未完成报告；原始失败保留。短输出第03轮已产生具体观察，但报告字段连续不合规而失败；结构约束已通过真实GPU格式验证，但full-workflow01反复调用后耗尽预算，仍未形成报告；没有陶瓷模型效果排名。

## 决定

**当前集成候选采用`Qwen/Qwen3-VL-8B-Instruct`与原生Transformers GPU适配器；是否用于正式演示取决于完整报告实测。** 实际节点没有现成健康视觉服务。Hugging Face通道不可达，Docker Hub超时，NGC镜像元数据可读但层下载未能完成；这些现场限制使原定vLLM容器路线尚未启动。Qwen官方ModelScope权重和PyTorch官方ARM64 CUDA13轮子可访问，因此采用独立原生环境。失败路径继续保留，未将下载失败解释为模型质量问题。

2B保留为部署与失败对照；8B已经通过文字动作、单图和双图顺序三项原始探针。这些合成任务不证明专业能力。模型由同一服务承担主Agent与视觉观察，StepFun只承担公开或获准脱敏文字的反证审查。原图和资料留在指定Spark项目内。

| 路线 | 适用情况 | 取舍与验证 |
|---|---|---|
| Qwen3-VL-2B-Instruct / 原生Transformers | 已完成真实部署与失败对照 | 权重11文件、4,266,640,357字节；GPU计算、加载和生成已运行，双图语义与完整工具流程失败，不作为专业就绪模型 |
| Qwen3.6-35B-A3B-NVFP4 / vLLM | 官方容器下载恢复后较大模型候选 | NVIDIA给出Spark配方；需ARM64/GB10兼容、内存与量化细节实测，目前未运行 |
| Qwen3.6-35B-A3B-FP8 | 培训配方/节点已有服务 | 用户培训第三份 PDF 第9页演示此路线，65K上下文、禁用 DeepGEMM 并使用 triton；复用已验证环境有利于赶进度 |
| Qwen3-VL-8B-Instruct | 2B已实际不达标后的扩大候选 | 17,545,907,304字节官方权重已逐文件核验SHA；GPU生成预热与三项原始探针通过，旧版主Agent流程失败，新协议正在实测；模型规模不能代替专家样本效果 |

官方资料确认 Qwen3.6 NVFP4 接收文本、图像与视频，并提供 Spark 专门配方；其通用基准不能推出古陶瓷最优。见 [NVIDIA 模型卡](https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4)、[Spark vLLM playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md)。FP8 属于 [Qwen 官方权重](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)，备用路线见 [Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)。

## 实际原生路径与容器候选

可复现原生路径见 [Spark Transformers接入](../integrations/spark_transformers/README.md)。服务只绑定回环、单并发，本地data URL最多4图，拒绝远程图片URL；`trust_remote_code=False`、`local_files_only=True`。权重SHA、真实CUDA float32/bfloat16运算、GPU加载及合成图生成预热通过后，健康接口才返回200。输出原样交给后台合同核查，合成预热不是专业验收。

2B和8B下载来自Qwen官方ModelScope仓库；8B的四个权重分片SHA和大小已交叉核对[Qwen官方仓库](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)的LFS指针。`master`是可变引用，实际身份采用下载文件SHA组合，不能冒充固定git revision。CUDA轮子来自 [PyTorch官方CUDA13索引](https://download.pytorch.org/whl/cu130/torch/)。运行库固定版本、完整依赖与实际GPU情况须由安装及探针证据分别确认；驱动显示CUDA13不证明所有库已兼容。

`deploy/serve-qwen-spark.sh`是保留的容器候选适配脚本，**尚未运行**。要求固定官方镜像digest；初始32K上下文、单并发、每次4图、回环端口。官方配方中的FP8 KV、FlashInfer、Marlin等只用于支持该参数的相应容器；没有用于当前原生Transformers路径，也未宣称量化加速。培训中的FP8/triton和NVFP4/marlin参数不能盲目拼接。

应用将待发送文字限制为32,000字符，保留实际加载的方法正文和当前动作；保护内容超出上限时明确失败，不截断方法。原生服务的32,768输入加输出token限制是另一个约束，不能用字符数替代。动作输出上限2,500 tokens，观察输出800 tokens；逐图短句与字段长度由宿主校验，细节通过局部观察补充。单轮仍为12次模型（包括视觉观察）、20次工具、300秒，单调用90秒；截断或格式失败保留实际finish_reason，不补写结果。

Qwen3.6 默认会进行 thinking。本项目可显式设置 `CIZHENG_DISABLE_THINKING=1`，发送 `chat_template_kwargs.enable_thinking=false`；这是 [Qwen 官方 API 示例](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) 支持的方式。对不支持该参数的已有服务不设置它。不同模式可能影响表现，探针和 A/B 两臂必须固定同一设置，不能据 JSON 接口兼容推断行为等价。

## 接入后立即执行

1. 已完成只读环境检查：ARM64、NVIDIA GB10、驱动580.159.03，统一内存与磁盘充足；没有现成视觉服务。不读取其他团队受限目录，不改已有容器。
2. 优先复用现有健康服务；需要新建时检查官方镜像架构、固定 digest 与模型 revision，然后执行部署脚本。记录真实版本、启动日志与实际内存，失败保留。
3. 在 Spark 运行 `python -m cizheng.model_probe --output results/probe-01.json`：JSON动作、单合成图、两图顺序三项。它只证明协议基本可用，不证明陶瓷能力。
4. 公开教学双图旧版2B与8B流程均未完成；8B局部生成139.255秒超过客户端90秒，已接受的两条观察只是模板句。新协议限制短输出并拒收该模板，再测完整流程。模型相同而协议改变，不能声称纯模型因果比较或Skills质量增益。再用专家的3–5件独立器物跑`paired_eval`，核查描述、引用与应保留不足的主张。
5. 首次服务调优只比较冷/热请求、图片负载、延迟与专业表现。记录失败和 token usage，缺失 usage 标为未知；不预写 tokens/s、准确率或“提升XX%”。
6. 若NVFP4在关键细节明显不稳且时间/内存允许，比较FP8同一任务。以专家能核查的证据定位、误收与耗时决定保留版本。

## 算力与数据位置

推荐正式演示把工作台后端、数据库及VLM放在同一 Spark 项目目录。笔记本通过 SSH 转发 `18780` 到节点回环端口 `8780` 访问界面；原图只在笔记本和指定节点之间传输，由节点处理。若后端临时仍在笔记本，必须如实披露本机也保存原图，不宣称“原始数据只在盒子里”。

StepFun使用实际账户提供的Step Plan端点`https://api.stepfun.com/step_plan/v1`及`step-3.7-flash`。已通过一次真实公开文字适配器请求，936tokens、4.829秒；未发原图。它不是独立专家，也不能验证图片裂缝或款识。地区端点和计划端点只按明确配置使用，不自动回退云服务；不公开密钥。
