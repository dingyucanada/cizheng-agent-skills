# 瓷证的 NVIDIA 集成与实测边界


最新完整第05轮已实际失败：4次模型、10次工具、服务端136.052秒。两张原图产生实际观察，协调器按本轮观察加载青花方法；下一主动作90秒超时，没有AI报告、该报告的NAT核查、StepFun反证或修订导出。固定文字格式合成探针也90秒超时，155.686秒晚到结构合格记录只按独占窗口关联。当前ARM开发源码129项流程CPU合同通过，不能替代以上业务失败。最新版本和证据见[当前状态](../STATUS.md)、[第05轮](../verification/nvidia/compact-workflow-05/README.md)。

瓷证使用 NVIDIA NeMo Agent Toolkit 1.9.0 注册、组合、运行和评估真实证据工具，并用 NVIDIA SkillSpector 2.12.0 检查进入 Agent 的运行技能。两个集成都可在本地运行，不需要 NVIDIA 云 API 密钥。NVIDIA 官方的[插件模式](https://github.com/NVIDIA/NeMo-Agent-Toolkit)允许保留现有应用及其受控工具，逐项接入工作流。

这次集成解决两个具体问题：报告引用是否仍指向原来实际读到的版本；发布的 Skill 是否声明了它使用的工具，并包含可复查的扫描证据。视觉 Agent、StepFun 文字反证审查及 Spark 模型服务仍按各自实际调用记录说明运行状态。纯引用核验没有模型推理，不计作多 Agent 模型效果或 GPU 加速成绩。

## 1. 可运行的 NeMo Agent Toolkit 插件

源码位于 `integrations/nvidia_nat/`，独立包名 `cizheng-nvidia-nat==0.1.0`，通过官方 `nat.components` 入口注册：

| 注册类型 | 实际行为 |
|---|---|
| `cizheng_evidence_retrieve` | 调用现有固定快照检索、逐段实际阅读，保存本地阅读回执 |
| `cizheng_evidence_verify` | 核对文档 ID/版本/SHA256、段落 ID/SHA256、定位六个字段 |
| `cizheng_evidence_workflow` | 由 Toolkit Builder 组合并调用上述两个真实组件 |
| `cizheng_reference_contract` | 通过 `nat eval` 检查软件协议预期结果及零模型调用边界 |

工具预算上限为 20 次、300 秒；当前案卷最多读取 8 段、每段 800 字。输入只接受有界 JSON，不接受任意工具、命令或工作流路径。每次读取和核验都有本地哈希回执，保存至案件目录的 `nat-audit/`。输出持续标明 `review_required=true`、`inference_performed=false`、`claim_support_assessed=false`。

核验的两种时点严格区分：

- **当前案卷**：显式传 `case_id` 与 `expected_case_revision`，只冻结本案 `knowledge_document_ids` 和 `knowledge_links` 已关联的固定版本。没有关联资料的案卷只能看到空快照，不会取得整库访问权。
- **已保存报告**：再传 `assessment_run_id`；只使用该报告原有 `knowledge_snapshot`、快照哈希、`read_knowledge` 回执和报告知识引用。案卷后来重新关联资料，也不会替换旧报告依据。输出同时给出当前 `case_revision` 与原报告 `source_case_revision`。

本功能核对 `knowledge_citations` 和文书任务 `documentary_findings[].evidence_refs[kind=knowledge]` 的引用身份。视觉参照的 `reference_ids`、附件本身的真实性、文本是否足以支持归属、年代、产权或真伪结论，都不由这个软件核验评分确定。

### 安装与复现

从项目根目录操作，使用 Python 3.12 建议配置；Toolkit 官方支持 Python 3.11–3.13。隔离安装过程需要下载公开软件，运行证据核查不访问外网。

```bash
python3.12 -m venv .venv-nvidia
.venv-nvidia/bin/python -m pip install -e 'integrations/nvidia_nat[eval,test]'
PYTHONDONTWRITEBYTECODE=1 .venv-nvidia/bin/python scripts/nvidia-nat-verify.py
PYTHONDONTWRITEBYTECODE=1 .venv-nvidia/bin/python -m pytest tests/test_nvidia_nat.py tests/test_nvidia_skill_scan.py -q
```

验证脚本使用项目原创的 Met 48607 公开馆藏摘要，执行真实组件发现、配置校验、CLI 运行和 `nat eval`，输出到 `.tmp/nvidia-integration-evidence/`。数据集仅检验正常引用、段落哈希篡改、无读取证据三种软件情况；不是盲测、独立实物鉴定或模型效果基准。

截至 2026-09-28，本机隔离环境实测：`nvidia-nat==1.9.0`、`nvidia-nat-core==1.9.0`、`nvidia-nat-atif==1.9.0`、`nvidia-nat-langchain==1.9.0`、`nvidia-nat-eval==1.9.0`、`nvidia-nat-profiler==1.9.0`。组件发现、两个配置校验、CLI 运行及离线评估均返回成功；3 项协议结果全部符合预期，实际模型调用为 0。首次独立验收的17项边界测试通过，覆盖跨案访问、旧版本、哈希篡改、快照重绑定、完成与待补证意见、运行中拒绝、重复请求、预算、禁止网络及扫描结果解析；这是该轮适配器检查数，不是当前全项目测试总数。

`verification-status.json` 保存命令退出状态和版本；`run-result.json` 保存结构化核验；`nat-eval/` 保留 Toolkit 的工作流输出、ATIF 输出、协议与运行指标。微型协议任务的耗时不用于宣称模型优化或 Spark 性能提升。

Spark的Python 3.12.3 / Linux ARM64独立`.nat`环境已实际安装`nvidia-nat/core/atif/langchain` 1.9.0及插件0.1.0，完成构建、组件发现、配置校验、CLI运行与隔离应用ASGI HTTP合同。软件案卷中HTTP 200、未认证403、旧版本409、幂等重复和历史核查恢复均符合预期；旧报告使用第2版案卷的原资料，当前案卷是第3版，模型调用仍为0。三案`nat eval`在本机执行，Spark的这一组记录没有执行该评测，也不是已部署后台的视觉模型报告核查。见[节点插件](../verification/nvidia/nat-spark-plugin.json)与[节点接口合同](../verification/nvidia/nat-spark-api-contract.json)。

### 应用调用接口

工作台的正式入口为 `POST /api/cases/{case_id}/nvidia-audits`，报告页提供“NVIDIA 引用核查”操作；请求正文包含 `request_id`、`expected_case_revision`、`assessment_run_id`。应用将该动作记录为独立的 `nvidia_audit`，成功时返回 `state=succeeded` 和 Toolkit 核查结果，导出报告同时附上核查记录。此动作既不修改原研究意见，也不为资料准备分或陶瓷真伪赋分。

```json
{
  "request_id": "nvidia-audit-20260928-001",
  "expected_case_revision": 3,
  "assessment_run_id": "run_<32位十六进制ID>"
}
```

正式接口只接受本案已完成的 `ready` 或 `waiting_evidence` 固定意见；待补证状态仍需有效原快照和原阅读回执。运行中、取消或未形成意见的任务不能通过核验。未配置独立环境时，工作台明确返回未执行。实际 `API → 独立 Python → Toolkit 工作流 → 旧报告快照` 验收已返回 HTTP 200、`references_verified`、`inference_performed=false`；验收资料是明确标注的软件契约 fixture，没有模型生成或陶瓷准确率结果。

应用可用独立环境的 Python 调用 `scripts/nvidia-nat-call.py --data-dir <本地案件目录>`。JSON 从标准输入传入，标准输出只返回结果；使用正常子进程参数调用，无需拼接 shell。应用可将 Python 路径配置为 `CIZHENG_NAT_PYTHON`。

该配置使用隔离环境中 `bin/python` 的绝对路径，保留虚拟环境的入口符号链接；不要把它解析成系统 Python 路径，否则会丢失插件与 Toolkit 的环境。

当前案卷查询输入：

```json
{
  "case_id": "case_<32位十六进制ID>",
  "expected_case_revision": 3,
  "queries": ["山水纹花觚"],
  "limit": 2
}
```

核验一份已保存报告时，`expected_case_revision` 仍填写当前案卷版本；资料依据由报告运行 ID 明确选择：

```json
{
  "case_id": "case_<32位十六进制ID>",
  "expected_case_revision": 3,
  "assessment_run_id": "run_<32位十六进制ID>",
  "queries": []
}
```

典型结果字段：`status` 为 `references_verified` / `reference_mismatch` / `no_read_evidence`；`source_mode` 为 `current_case_pinned_versions` / `saved_assessment_run_snapshot`；`checks` 逐项保留定位和哈希，`usage.model_calls` 为 0。已保存报告模式须有完成的报告，并拒绝对当前资料库同时发起检索。若原报告引用没有对应原运行阅读回执，则返回 `not_read_in_this_run`，不补造证据。

子进程接口在导入 Toolkit 前关闭遥测、LangSmith/OTel 导出，并在 Python 层阻断外连 socket。它不读取或传输图片。配置信息写入案件目录下的专属 `nat-config/`，不改变用户全局设置。

## 2. SkillSpector 的真实静态检查

使用官方 [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector) 固定 commit `89e90872e2ec813bcb137bf6b3145c92e55811ae`，包版本 `2.12.0`。另建隔离环境，避免与 Toolkit 依赖混用：

```bash
python3.12 -m venv .venv-skillspector
.venv-skillspector/bin/python -m pip install 'skillspector @ https://github.com/NVIDIA/SkillSpector/archive/89e90872e2ec813bcb137bf6b3145c92e55811ae.tar.gz'
.venv-skillspector/bin/python scripts/nvidia-skill-scan.py
```

脚本调用真实 `skillspector scan --no-llm`，阻断外连 socket、不传入模型凭据、不自动抑制发现，并给每个完整 Skill 包和实际扫描范围记录哈希。按 NVIDIA [Tier-1 公开规范](https://docs.nvidia.com/skills/evaluating-agent-skills)，运行技能扫描使用暂存范围，排除评估和产物目录；这些排除项逐个记录在 `scope_exclusions`，不会冒充整个目录已扫描。

首次完整包诊断发现 documentary Skill 缺少工具范围声明，以及带引号版本号被识别成缺失本地路径。修正元数据后，完整包诊断仍发现评估脚本的文件读取能力未包含于运行技能工具声明中；该诊断原样保留。运行 Skill 声明的是瓷证受控工具，离线评估脚本单独执行，不额外授予运行 Agent 通用文件读取权限。

发布范围扫描与完整包诊断分别保存。`summary.json` 使用该版本的真实 `issues` / `risk_assessment` / `analysis_completeness` 字段；遇到陌生报告结构、未完成扫描或未处理发现即返回非零状态。无模型静态扫描不能代替语义安全检查，也不能证明对实时依赖漏洞库完成了查询。

本次七个运行技能的暂存范围均完成真实扫描，范围内覆盖率为 100%，发现数为 0，脚本返回 `static_checks_clear`。每个结果均显式列出 `evals/` 排除项；完整包的首次警告和修正后评估脚本诊断继续保留，不能将此结果解释为完整目录或 NVIDIA Verified 认证。

## 3. 官方 Skills 与待完成的效果评估

此次开发实际研读并应用以下 NVIDIA Skills，固定到官方 Toolkit commit `c7e1162a1c7ff18bbd797e090a56cad97c281c92`，并以已安装 1.9.0 API 和 CLI 的实际注册结果验证兼容性：

- [nat-user-rules](https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/c7e1162a1c7ff18bbd797e090a56cad97c281c92/skills/nat-user-rules/SKILL.md)：先发现注册组件，使用真实类型。
- [nat-workflow-creation](https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/c7e1162a1c7ff18bbd797e090a56cad97c281c92/skills/nat-workflow-creation/SKILL.md)：按实际配置校验和最小运行验证。
- [nat-tools-and-functions](https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/c7e1162a1c7ff18bbd797e090a56cad97c281c92/skills/nat-tools-and-functions/SKILL.md)：通过 `FunctionInfo.from_fn()` 与包入口注册工具。
- [nat-evaluation](https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/c7e1162a1c7ff18bbd797e090a56cad97c281c92/skills/nat-evaluation/SKILL.md)：运行小型明确数据集，保留评估结果并区分评分目的。

上述是开发阶段使用官方技能指导插件实现；用户运行的七个陶瓷技能仍为项目自研，两种使用证据分别记录。官方SkillEvaluator的Tier 3在Codex、Claude Code、OpenCode宿主进行live两臂任务；瓷证领域技能依赖自定义受控工具宿主，不能仅运行该CLI就声称评测了现有Qwen视觉Agent。若作官方宿主实验，需要真实工具环境映射，并与本项目同模型、同图片的视觉评测分开。[官方Tier 3说明](https://docs.nvidia.com/skills/skillevaluator/tier3-live-evaluation)

官方 [NVIDIA Skills 文档](https://docs.nvidia.com/skills/)把扫描、任务效果评估、签名、来源与 Skill Card 共同作为 Verified 的要求。瓷证目前提供运行技能、静态扫描、软件协议检查和既有成对评估能力，尚未完成官方 SkillEvaluator 的 live with/without-skill 沙箱评估或 NVIDIA catalog 签名流程。因此所有结果明确为 `nvidia_verified_skill=false`。

Spark 模型 `/v1` 接入与 StepFun 调用沿用瓷证的既有受控研究服务。NAT 引用核查可在模型调用前后运行；接入本地模型时仍由原服务保留图像权限、案件预算、专家复核及实际 token 记录。本次纯证据工作流没有配置模型提供者，也没有凭该流程给模型效果或 GPU 成绩赋分。

## 4. Spark的真实CUDA运行与观测

当前节点记录为NVIDIA GB10、CUDA 13.0运行库、`PyTorch 2.14.0+cu130`，以及ARM64的Transformers与Triton编译器。这里的Triton是PyTorch原生运算所用的编译器，**不是NVIDIA Triton Inference Server**；后者没有部署。依赖清单不意味着每个CUDA库、SDK或算法都已实际调用。

部署依次验证权重SHA、真实FP32/BF16矩阵计算、GPU参数加载与合成图实际生成；任一步失败，健康接口不返回就绪。首次生成遇到缺Python.h的Triton编译错误，修复是在项目内解压官方签名头文件，没有改系统解释器。原始失败和修复来源均保留。

适配器通过真实GPU API测量`model.generate`的CUDA Event区间和PyTorch内存高水位。CPU图片预处理在此区间外；Event时长可能包含主机发射计算时的空隙，不等于核函数耗时之和。内存字段包含本进程模型与缓存；GB10使用统一内存，这些字段不是整机或其它进程占用。失败保留未测状态，不补零。

实际合成单图记录中，2B的事件区间约318.234ms、allocator allocated峰值4,314,310,656字节；8B约542.147ms、峰值17,614,917,120字节，均有响应和请求日志相互对应。两个请求的输出长度和模型不同，不能据此计算模型速度优劣或平台加速收益。见[2B观测](../verification/nvidia/spark-cuda-observer.json)与[8B观测](../verification/nvidia/spark-qwen8b-cuda-observer.json)。

工作线程内部也保持串行：取消HTTP等待不会停止正在生成的GPU线程，下一次生成须等它真实结束，随机种子和内存测量才不交叉。回归以真实Python线程取消验证此边界，GPU测量由节点实际请求另证。观测不等于已经测出冷/热负载或性能提升。

2B模型已真实生成，但双图语义与工具规划失败。8B权重已实际下载，四个权重分片的尺寸和SHA256与独立读取的Qwen官方公开LFS指针一致；`master` / `main`仍是可变引用，保存的文件哈希界定本次实际运行内容。8B已通过真实GPU热身、JSON动作、合成单图颜色与双图顺序三项原始探针；这些结果只证明该范围的生成、图片传输和协议行为。

8B使用旧c005的公开实图run02仍失败：服务端约185.9154秒，7次模型调用、6次工具调用，没有研判意见。两个通过结构校验的观察，`visible`均为精确模板句“直接可见现象”，有效语义观察为0。区域图生成在GPU线程中继续运行约139.255秒，超过客户端90秒等待，最终生成1586 tokens、未触及2500上限；失败原因不能写成token截断。见[原始运行记录](../verification/nvidia/spark-public-8b-run-failed.json)与[失败摘要](../verification/nvidia/spark-public-8b-first-summary.json)。

开发版本`source-dev-c006-vision-bounded-01`的8B公开两图run03已失败：视觉产生两条具体描述（未由专家评定），但判断字段缺失与非法维度连续校验失败，服务端185.050秒、5次模型、2次工具，没有报告。新视觉协议上限为800 tokens，`visible` / `interpretation` / `limitation`分别限制48 / 24 / 32字符；动作请求仍为2500 tokens，压缩上下文保留可信的实际方法正文。模型12次、工具20次、总300秒、单次等待90秒的预算保持不变。当前615项Python软件合同测试通过（1条warning，41.71秒）；第03轮验收尚无完整成功结论，不能从回归或原始探针推定完整Agent、反证闭环或专家效果。公开已知馆藏只用于功能验收。

CUDA依据：[Event](https://docs.pytorch.org/docs/stable/generated/torch.cuda.Event.html)、[同步与内存口径](https://docs.pytorch.org/docs/stable/notes/cuda.html)；硬件依据：[DGX Spark统一内存](https://docs.nvidia.com/dgx/dgx-spark/hardware.html)。部署见 [原生适配器](../integrations/spark_transformers/README.md)。

## 真实结构约束与完整任务第01轮

结构约束已在真实GB10 GPU上执行：固定LM Format Enforcer 0.11.3通过token前缀限制生成合成红图JSON，7 completion tokens、2.348秒；这只验证格式与传输。随后公开两图full-workflow01仍失败：12次实际模型、16次工具、207.586秒，全部响应stop，9次动作结构校验通过，但模型反复读取资料和查看图片耗尽预算，没有报告、NAT核查或StepFun审查。五条入库观察未测专业准确性。旧失败保留，完整业务尚待验证。

新增依赖来自官方PyPI轮子；保持节点原有PyTorch、Transformers等版本，未新增模型权重。62项原生适配器CPU合同在ARM64实际解释器通过，0跳过；它们不是GPU领域成绩。约束库是第三方工程组件，不称为NVIDIA专属SDK。固定源文件清单、Schema及响应哈希与逐调用记录见[公开验收文件](../verification/nvidia/README.md)。


## 受控准备完整任务第02轮

受控准备后的 full-workflow02 也未完成：程序实际读取一段本案固定资料并看两张原照，模型2次、工具7次、服务端110.388秒。第一条主动作在客户端90秒处超时；原生GPU随后用133.981秒生成1029个 completion tokens，结构检查通过，但后台未接收该响应或形成报告。晚到响应仅按独占请求窗口、开始时刻、图片与模型参数关联，不能冒称客户端收到响应哈希或 finish_reason。没有执行NAT、StepFun或报告导出。

逐调用记录见[第02轮公开证据](../verification/nvidia/guided-workflow-02/phase-trace.json)。新策略仍需完整业务验收，不因模型输出结构合法或GPU线程结束而判成功。


## 真实 NAT profiler 时间轨迹

在独立 Python 3.12 环境安装 `integrations/nvidia_nat[eval,test]` 后，运行以下入口；输出目录必须不存在，每次保留独立记录：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-nvidia/bin/python scripts/nvidia-nat-profile.py --output .tmp/nat-profiler-01
```

实际执行使用 NVIDIA NeMo Agent Toolkit / eval / profiler 1.9.0。插件以官方 `track_function` 包装真正的检索、引用核查和组合工作流。三个软件样例分别覆盖匹配、哈希不匹配和没有读取回执；实际收到42条原始事件，其中9个tracked SPAN与9个原生FUNCTION各有开始和结束。ATIF共12 steps，CSV共42行，已生成原始轨迹、指标、报告与Gantt。引用合同符合预期；模型调用和LLM事件均为0，隔离环境的网络审计记录0次联网尝试。

CLI eval墙钟为16.371秒，包含初始化、评测、分析和绘图；三个内部工作流跨度为47.425、3.370和2.879毫秒，测量CPU证据工具。嵌套跨度不能相加为总耗时。原图把SPAN和FUNCTION均画作FUNCTION，共18行；其重叠并发指标不代表18次业务动作或4个案卷并行，本次案卷并发上限为1。它没有测量Qwen生成、GPU或陶瓷判断质量。

[实际运行与原始文件清单](../verification/nvidia/nat-profiler-01/README.md)保留源码SHA、原始与公开文件SHA的区别。CI另设真实NAT与profiler环境验证；工作流配置不等于已成功执行，最终以发布提交的CI结果为准。[NVIDIA profiler官方文档](https://docs.nvidia.com/nemo/agent-toolkit/latest/improve-workflows/profiler.html)

## 短动作完整任务第03轮

本轮源文件清单绑定238个文件。Spark ARM64实际解释器执行85项受控准备与短动作CPU合同通过，0跳过，没有加载Torch或执行模型。本轮真实两图任务用7次模型、13次工具、164.200秒，全部模型响应stop；六次动作结构校验通过，7/7客户端响应哈希、usage与节点原始生成直接一致，没有90秒等待超时。

流程仍失败：模型第一次未先加载归属比较方法，随后把实际读取的文献编号填入参照器物编号，空白和标点替代竞争解释。原证据合同拒绝形成报告；没有自动替换编号、补写意见或调用NAT / StepFun。后续修正只明确编号命名空间、当前确实获得引用资格的编号和方法前提，保留模型选择与原预算。[第03轮逐调用证据](../verification/nvidia/compact-workflow-03/phase-trace.json)、[源码与ARM64合同记录](../verification/nvidia/compact01-source-binding/source-binding.json)。格式通过说明传输受控，仍不能证明业务推理可靠。


第04轮保留失败：源清单270文件，Spark两图任务6次模型、10次工具、141.783秒，六次响应全部stop且直接匹配节点原始SHA和usage。3条实际观察未由专家审定；模型先用标点写竞争解释，修正时正确引用本轮已读文献，但遗漏必须加载的方法，原证据合同拒绝发布，没有报告、NAT或StepFun。证据见 [逐调用记录](../verification/nvidia/compact-workflow-04/phase-trace.json)。
