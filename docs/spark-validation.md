# Spark 联调手册


最新完整第05轮已实际失败：4次模型、10次工具、服务端136.052秒。两张原图产生实际观察，协调器按本轮观察加载青花方法；下一主动作90秒超时，没有AI报告、该报告的NAT核查、StepFun反证或修订导出。固定文字格式合成探针也90秒超时，155.686秒晚到结构合格记录只按独占窗口关联。当前ARM开发源码129项流程CPU合同通过，不能替代以上业务失败。最新版本和证据见[当前状态](../STATUS.md)、[第05轮](../verification/nvidia/compact-workflow-05/README.md)。

状态：2026-09-28指定ARM64/GB10节点已通过历史c005冻结后端342项工程检查、真实CUDA计算、GPU模型加载和实际图像生成预热。8B已实际GPU预热并通过三项原始探针；2B、8B旧版完整工具流程失败，新版受约束格式已通过真实GPU验证；公开两图full-workflow01因调用预算耗尽没有报告。以下各步单独验收，部署就绪不等于专业质量。

## 先复用，再部署

在用户指定SSH主机及项目目录运行`bash deploy/spark-inventory.sh`，只检查环境和已有服务。本次没有可复用视觉服务；官方容器层下载未及时完成，已采用 [原生GPU适配器](../integrations/spark_transformers/README.md) 作为功能接入。容器脚本保留为未运行候选，详见 [模型选择](model-selection.md)。不修改其他项目或团队环境。

将开发包解压到用户指定项目目录。创建 Python3.11+ 虚拟环境、安装依赖、跑完整工程测试。ARM64/Spark 不能因为 macOS 通过就跳过验证。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-tested.txt -r requirements-structured-tested.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests integrations/spark_transformers/tests
```

设置实际本地服务地址（含 `/v1`）及模型名。密钥只通过节点的私人进程环境提供，不写到仓库、日志或演示画面。

```sh
export CIZHENG_MODEL_URL=http://127.0.0.1:8001/v1
export CIZHENG_MODEL=Qwen/Qwen3-VL-8B-Instruct
export CIZHENG_DISABLE_THINKING=0
# 使用真实下载清单的组合哈希，不填虚构revision。
export CIZHENG_MODEL_REVISION=files-sha256:ACTUAL_MANIFEST_SHA256
.venv/bin/python -m cizheng.model_probe --output results/probe-01.json
bash deploy/start-local.sh
```

笔记本选择一个空闲端口，替换为自己配置的SSH别名。本次转发示例使用18780，保留原有本机开发服务：

```sh
ssh -N -L 18780:127.0.0.1:8780 SPARK_SSH_ALIAS
```

浏览器访问`http://127.0.0.1:18780`。此结构不开放互联网端口；后端是单用户、单进程研发服务，无机构多人身份认证。

新适配器可选择启用结构化动作生成：确认服务端已安装固定 LM Format Enforcer 依赖并通过实际受约束探针后，给应用设置 `CIZHENG_STRUCTURED_OUTPUTS=1`。默认关闭；仅真正的主动作系统提示触发 `response_format`，视觉观察与通用探针不变。适配器记录约束模式、库版本、Schema哈希和最终结构校验。它不保证判断正确，原有数值、引用、权限与工作流校验继续执行。具体支持范围和兼容处理见原生适配器 README。

若启用 `CIZHENG_GUIDED_WORKFLOW=1`，按[受控材料准备](controlled-workflow.md)核对 `harness.strategy`、实际准备日志与原预算。它与结构约束开关独立；准备的方法和段落是协调器选取，不能作为自然Skill触发或未匹配的有/无Skills对照。


若同时选择 `CIZHENG_COMPACT_ACTIONS=1`，核对独立 `harness.compact_actions`、`action_transport.protocol=compact-visual-metadata-v1`及实际提示与解码模式哈希。该变体只缩短视觉动作传输，从本轮已读正文回执补回来源身份，判断与理由仍由模型写出；仍经原工具、权限、证据和预算校验。默认关闭，不影响文字核查。边界和上限见[受控材料准备与短传输](controlled-workflow.md)。
## 模型通过基础探针后

- 导入公开教学例，仅用于功能演示；使用公开身份不作为盲测答案。
- 准备专家独立器物和独立参照，先校验清单，再执行有/无Skills对照。专家标签保存在模型不可读的位置。
- StepFun凭据准备好后，先用公开文字验证一份完整反证闭环：预览→批准内容→单次审查→新版本→主 Agent 回看原图→逐项回应→导出。
- 页面“已配置”只表示环境配置完整，不等于探针或专业评测通过；依据实际结果文件记录成功。

## 失败与回退

模型超时/格式错误保留已发生调用、使用量（若提供）、图像派生关联和失败状态；不使用演示固定答案。容器参数不兼容时根据版本说明删改项目适配参数并记录，不能静默降为文本模型。本次实际原生模型使用BF16；培训中的FP8/triton配方可作为容器兼容排查参考，尚未在本项目实测FP8或NVFP4收益。

审查中断的外部调用状态可能未知，不自动重试。新案或明确补证按 Episode 预算继续；总36模型调用、60工具调用、900秒和最多初判加两次完成修订仍生效。

## 实测记录

每次写新结果目录：机器/GPU/驱动、CUDA/vLLM版本、容器digest、模型revision、generation设置、来源图哈希、预处理版本、冷/热定义、运行日志、所有失败、调用与usage、单次和总时间、专业盲评及其分母。缺失项写未测，不写0。
