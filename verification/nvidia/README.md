# NVIDIA 与 Spark 实际运行证据

当前 v0.7 主入口为 [逐轮工作流与证据索引](v07-workflows/README.md)：第 02–12 轮实际初判、NAT、批准文字审查、修订及失败记录。第 12 轮技术 completed、两版来源任务检查通过，但专业质量 false；历史紧凑协议轮次与 v07 round 编号属于不同实验序列，不能混写。

- [当前工程与部署](v07-workflows/engineering-checks-v07.json)：实测 r15 应用 913 passed / 8 skipped / 1 warning，309.15 秒；专项 403 / 6 / 1，143.49 秒。原生含新增阶段 Schema 的 147 / 0 / 1、4.54 秒在 r14 测试，生产 native 不变、服务仍为 r11。以上均 0 次 GPU 模型请求，r14 三项失败留在历史工程记录。
- [部署源码一致性](v07-workflows/runtime-public-python-parity.json)：86/86 核心、测试、集成 Python 文件与实际 r15 部署清单 SHA 匹配，不是整个 Git，也不代表陶瓷能力。
- [真实第 12 轮](v07-workflows/round-12/authenticity-audit.json)：初稿、一次 StepFun 审查、本地修订、两版 NAT 与 6 份导出完成；两版各 1 body / 1 source_context cite，来源任务检查通过。[14/14 新增调用绑定](v07-workflows/round-12/native-binding.json)排除 34 历史行，最大 HTTP 47.780226 秒 < 90 秒，全部 EOS / 原 Schema 有效。
- [第 12 轮专业质量局限](v07-workflows/round-12/quality-limitations-audit.json)：quality false，初稿同器来源身份误句保留，修订理由与风格支持仍弱；三项疑点均 unresolved，未经专家验证。第 09–11 轮引用、格式及修订失败保留在索引。
- [Nsight 实际采集](v07-workflows/round-03/nsight-summary.json)：2025.3.2，1 区间 19.920507616 秒、144 聚合行 / 447,028 kernel 实例；不是加速或专业质量结论。
- [32B 候选](v07-workflows/candidate-32b.json)：官方权重 / CUDA / BF16 / 合成协议通过，真实双图业务失败后停止，当前不驻留。
- [CPU 解码重放](v07-workflows/decoder-cpu-replay.json)：无模型请求，私有 profiler 路径脱敏。
- [JSON Mode 探针](v07-workflows/stepfun-json-mode-probe.json)：公开合成四字段，1 次 / stop / Schema 有效，不是业务验收。
- [总公开派生与 SHA 清单](v07-workflows/redaction-manifest.json)：原件保留，公开证据移除凭证、私有地址 / 路径、原图 base64、SSH 身份与 raw nsys；不由程序补写意见或引用。

本次新增 [TRT实际部署](tensorrt-llm-v08/README.md) 与 [开放embedding/cuVS Retriever](retriever-v07/index.json)：分别为独立文字接口/CUDA前8迭代，以及25段/2048维/原client9 HTTP/5query数值与身份核验。原8B视觉和SQLite主流程未替换。[完整部署范围](../../docs/spark-deployment-update-v08.md)。

NAT核对引用身份，不验证观点或真伪；StepFun只收批准文字。NIM仍受官方中国区分发与伙伴授权限制，vLLM镜像未完整部署，Dynamo未部署。开放Retriever不称NIM/完整SDK。专家样本尚未接收，真品概率未校准。

## 历史记录

下方保留此前 v0.6、紧凑协议、结构约束等原索引文字，作为当时状态记录；其中“最新”“当前”“待验证”指该段历史实验，不代表上方 v0.7 现状。旧失败未删除，不将旧 90 秒超时与第 10 / 11 轮非超时的失败混写。

<details>
<summary>展开原始历史索引</summary>

# 已执行的集成证据

最新第05轮仍没有AI报告：双图观察和适用方法已加载，下一主动作90秒超时。当前新增[原生恢复与晚到格式记录](observed05-native/README.md)、[296文件开发源与129项ARM CPU合同](compact03-source-binding/README.md)、[完整第05轮实际阶段](compact-workflow-05/README.md)。CPU合同、GPU格式和完整业务分别验收，不能相互替代。


更新：2026-09-28。这里发布实际运行的少量可公开记录，避免把安装、配置或测试替身称为真实推理。没有密钥、SSH账户、私有案卷或原始培训材料。

- `nat-cli-eval.json`：真实NeMo Agent Toolkit 1.9.0的组件发现、配置校验、工作流和评测CLI均返回0。三个软件引用合同，0次模型调用，1.0是该合同的均分，不是鉴定准确率、Skills增益或GPU速度。
- `nat-backend-api.json`：真实应用API调用隔离Toolkit环境，核对固定历史报告的知识来源身份；使用手工创建的软件合同案卷，未运行视觉模型。案卷第3版核对的是原报告第2版资料，而不是改用当前资料。
- `nat-documentary-api.json`：修复文字凭据引用字段后，真实API与Toolkit子进程核对一条实际读取的知识引用；保留原报告快照并导出MD/HTML。合成协议案卷，没有瓷器准确率验证。
- `nat-source-manifest.json`：相应插件、脚本及边界测试的文件SHA256；后续版本若改动，应重新运行验证。
- `skillspector-runtime.json`：真实SkillSpector 2.12.0、固定官方源码，静态且禁止外连；7个运行范围扫描complete/coverage100、未发现问题。完成度只指本次暂存范围的静态检查，未在线查询依赖漏洞数据库。每包明确排除`evals/`；这是官方Tier-1暂存范围，不能解释为全包或NVIDIA Verified。
- `skillspector-full-bundle-diagnostic.json`：全包扫描仍发现`evals/run_contract_checks.py`的HIGH LP1文件读取诊断。未自动抑制或隐去。离线测试脚本不进入运行技能范围，也不因此向Agent开放通用文件读取。只将本机绝对路径改为仓库路径，原报告SHA记录在内。
- `stepfun-public-text-probe.json`：真实StepFun文字适配器请求，结构和引用ID通过；仅发送公开文字、未发送图片。该探针不是完整主Agent与反证修订，也不是独立专家复核。
- `engineering-checks.json`：按来源区分当前开发检查、历史c005节点342项及真实模型试验。工程检查不等于专家验收，原始与脱敏日志哈希分别保留。

[当前只读开发阶段的实际回归](current-engineering-01/README.md)：615项Python合同通过（2项可选NAT检查跳过、1条依赖warning、41.71秒）、33项DOM与站点校验通过；独立真实NAT1.9环境22项通过、0跳过、2.85秒。独立套件与主套件范围有重叠，不相加。较早576、380及c005节点342均为历史检查，不等于陶瓷准确率或模型任务成功。

另有实际Spark节点记录：

- `spark-gpu-math.json`：GB10上真实CUDA float32/BF16矩阵检查；不是模型质量评估。
- `spark-qwen2b-probe-01.json`、`spark-python-headers.json`、`spark-public-headers-script.json`、`spark-public-start.json`：首次生成因缺少Python头文件失败，随后用官方Ubuntu签名仓库的固定包在项目目录内修复，再实际执行公开启动配方。没有修改系统Python或申请管理员安装。
- `spark-qwen2b-warmup.json`：真实GPU加载与生成热身成功；合成白图不用于领域评估，健康检查不提前把权重加载成功当可推理。
- `spark-qwen2b-probe-02.json`：JSON动作与单图颜色探针通过，原始两图合同失败。失败记录原样保留，不能称模型全项验收通过。
- `spark-public-2b-run-failed.json`：真实HTTP后台使用两张有来源的公开Met照片；4次主动作请求、2次工具调用、全部模型请求未含图片，未形成观察或研判意见。这是Agent协议流程失败，不是照片鉴定结果。
- `spark-public-2b-direct.json`：同两张真实照片直接发送视觉模型，得到自由文字描述；没有完成Agent合同，描述内容仍需人工核对，不能替代前一项失败。
- `spark-cuda-observer.json`：一次2B合成单图的真实GPU请求，CUDA事件间隔约318.234ms，allocator allocated峰值4,314,310,656字节，响应与日志匹配。这是当前流事件与本进程分配器口径，包含模型和缓存；不是纯kernel速度、节点总内存或吞吐基准。
- `spark-triton-compiler-cache.json`：真实Triton CUDA kernel缓存及架构记录。Triton编译器与NVIDIA Triton Inference Server是不同项目，本期没有部署后者。
- `nat-spark-plugin.json`、`nat-spark-api-contract.json`：Spark ARM64隔离环境中的真实插件发现、配置、CLI与隔离应用ASGI HTTP合同；核查固定历史报告的知识引用。软件合同案卷、0次模型调用；不是已部署后台的视觉模型报告核查或专业准确率。三案Toolkit评测见本机的`nat-cli-eval.json`，不声称Spark执行了这项评测。
- `spark-runtime-freeze.txt`：实际节点的依赖版本，只发布包名和版本，不包含下载令牌、模型权重或私人路径。

8B另有九份公开实测记录，权重已完成下载：

- `spark-qwen8b-model-manifest.json`、`spark-qwen8b-official-weights.json`：实际文件哈希及四个权重分片与独立Qwen官方公开LFS指针的尺寸、SHA256对照全部匹配。`master` / `main`仍是可变引用，不声称两个仓库所有内容或历史版本相同。
- `spark-qwen8b-runtime-stage.json`、`spark-qwen8b-guard-tests.json`：独立运行副本和文件哈希、ARM64 CPU保护合同测试。未修改冻结source；测试替身不算GPU或领域评估。
- `spark-qwen8b-health.json`、`spark-qwen8b-probe.json`：GB10 / CUDA 13.0 / PyTorch 2.14.0+cu130的实际GPU热身通过，JSON动作、合成单图颜色与双图顺序三项原始探针通过。证明对应协议和图像传输，不证明复杂业务成功。
- `spark-qwen8b-cuda-observer.json`：8B合成单图真实请求，事件间隔约542.147ms、allocator allocated峰值17,614,917,120字节，响应与日志匹配。与2B的模型、输出长度不同，不能算速度对照。
- `spark-public-8b-run-failed.json`、`spark-public-8b-first-summary.json`：旧c005公开实图run02实际失败，服务端185.9154秒，7次模型、6次工具，没有研判意见。两个schema accepted观察的`visible`都是精确模板句“直接可见现象”，有效语义观察为0。区域图GPU生成约139.255秒，超过客户端90秒；生成1586 tokens、未触及2500上限，不是token截断。原始失败保留，不把图片已发送、观察结构合格或GPU线程后来结束当成完整成功。

开发版本`source-dev-c006-vision-bounded-01`的8B两图run03已失败，尚无完整成功结论。`spark-public-8b-bounded-run-failed.json`和`spark-public-8b-bounded-phase-trace.json`保存实际185.050秒、5次模型、2次工具与逐调用记录。视觉224 completion tokens、20.947秒，产生两条具体描述（未由专家评定）；随后主动作遗漏必填字段和使用非法判断维度，连续校验失败。全部响应finish_reason为stop，不是输出截断或超时。视觉输出改为800 tokens与`visible` / `interpretation` / `limitation`的48 / 24 / 32字符限制，动作仍2500 tokens；压缩保留可信实际方法正文，模型12次 / 工具20次 / 总300秒 / 单次等待90秒预算不变。

复现环境、命令和边界见 [NVIDIA集成](../../docs/nvidia-integration.md)、[模型选择](../../docs/model-selection.md)。真实GPU生成、完整Agent流程、现场有/无Skills对照及专家验收各有独立口径，不能相互推定。后续候选TensorRT-LLM、NIM、Dynamo、NeMo Retriever与RAG Blueprint未计入本期已集成技术；所有Skill结果均不声称NVIDIA Verified。

## 真实结构约束与完整任务第01轮

结构约束已在真实GB10 GPU上执行：固定LM Format Enforcer 0.11.3通过token前缀限制生成合成红图JSON，7 completion tokens、2.348秒；这只验证格式与传输。随后公开两图full-workflow01仍失败：12次实际模型、16次工具、207.586秒，全部响应stop，9次动作结构校验通过，但模型反复读取资料和查看图片耗尽预算，没有报告、NAT核查或StepFun审查。五条入库观察未测专业准确性。旧失败保留，完整业务尚待验证。

新增依赖来自官方PyPI轮子；保持节点原有PyTorch、Transformers等版本，未新增模型权重。62项原生适配器CPU合同在ARM64实际解释器通过，0跳过；它们不是GPU领域成绩。约束库是第三方工程组件，不称为NVIDIA专属SDK。固定源文件清单、Schema及响应哈希与逐调用记录见本目录公开验收文件。

- [`structured-workflow-01/ready-summary.json`](structured-workflow-01/ready-summary.json)：固定源清单、官方依赖轮子、ARM64 CPU合同与真实GPU结构约束探针。
- [`structured-workflow-01/final-run.json`](structured-workflow-01/final-run.json)、[`phase-trace.json`](structured-workflow-01/phase-trace.json)：真实公开两图失败及12次模型响应与原生日志逐条哈希匹配，全部stop，预算耗尽。
- [`structured-workflow-01/redaction-manifest.json`](structured-workflow-01/redaction-manifest.json)：原记录与公共脱敏副本SHA分别保留；内部定位、节点身份和端点不公开。


## 受控准备完整任务第02轮

受控准备后的 full-workflow02 也未完成：程序实际读取一段本案固定资料并看两张原照，模型2次、工具7次、服务端110.388秒。第一条主动作在客户端90秒处超时；原生GPU随后用133.981秒生成1029个 completion tokens，结构检查通过，但后台未接收该响应或形成报告。晚到响应仅按独占请求窗口、开始时刻、图片与模型参数关联，不能冒称客户端收到响应哈希或 finish_reason。没有执行NAT、StepFun或报告导出。

- [`guided01-source-binding/source-binding.json`](guided01-source-binding/source-binding.json)与[`deployment-ready.json`](guided01-source-binding/deployment-ready.json)：实际229文件准备版本的清单与后台身份，不是业务成功证据。
- [`guided-workflow-02/final-run.json`](guided-workflow-02/final-run.json)与[`phase-trace.json`](guided-workflow-02/phase-trace.json)：真实两图任务、90秒超时与晚到CUDA记录；关联方式和直接观测的边界分别说明。
- [`guided-workflow-02/redaction-manifest.json`](guided-workflow-02/redaction-manifest.json)：原始与公共副本哈希分别保存。


新增实际运行记录：

- [NAT profiler 1.9.0](nat-profiler-01/README.md)：三个CPU引用软件样例、真实轨迹与Gantt；0模型调用，嵌套跨度不代表主视觉性能。
- [短动作开发版源码与ARM64合同](compact01-source-binding/source-binding.json)：238文件清单绑定，85项实际CPU检查通过，0跳过。
- [完整任务第03轮](compact-workflow-03/phase-trace.json)：7次模型响应全部直接匹配节点原始SHA，但引用编号语义错误使报告失败；不把结构成功记成业务成功。

- [完整任务第04轮](compact-workflow-04/phase-trace.json)与[独立节点对照](compact-workflow-04/native-trace.json)：6/6响应直接匹配，但短解释占位和方法遗漏使报告失败。
- [第04轮开发源码、ARM64检查与实际NAT源码绑定](compact02-source-binding/source-binding.json)：270文件，103项CPU检查通过；自研插件已优先于旧editable配置，未升级依赖。

- [首批实见方法与固定短解释协议的CPU检查](observed-method-cpu-01/README.md)：198项工具合同、52项真实解析库检查；两组范围有重叠，不相加为独立样本数，不是GPU或领域质量。

[发布前最后回归](release-engineering-01/README.md)：Python615／DOM33通过；39.18秒与1.547秒分别描述本次套件，开发阶段41.71秒记录继续保留。源码／方法／知识未改，说明文档与公开证据另有版本，最终冻结绑定在质量记录中。


</details>
