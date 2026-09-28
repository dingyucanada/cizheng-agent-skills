# Spark 联调手册

状态：连接信息尚未提供，以下命令已准备，未宣称节点部署成功。

## 先复用，再部署

在用户指定 SSH 主机及项目目录运行 `bash deploy/spark-inventory.sh`。只检查环境与已有服务。已有健康视觉服务时使用其实际模型名称，不因本文件推荐而删除容器或重装环境。新服务采用 `deploy/serve-qwen-spark.sh`，运行前核实官方 ARM64 镜像并设置固定 digest；详见 model-selection.md。

将开发包解压到用户指定项目目录。创建 Python3.11+ 虚拟环境、安装依赖、跑完整工程测试。ARM64/Spark 不能因为 macOS 通过就跳过验证。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-tested.txt
.venv/bin/python -m pytest -q
```

设置实际本地服务地址（含 `/v1`）及模型名。密钥只通过节点的私人进程环境提供，不写到仓库、日志或演示画面。

```sh
export CIZHENG_MODEL_URL=http://127.0.0.1:8000/v1
export CIZHENG_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4
export CIZHENG_DISABLE_THINKING=1
.venv/bin/python -m cizheng.model_probe --output results/probe-01.json
bash deploy/start-local.sh
```

先停止本机正在监听8780的开发服务，再在笔记本另开终端，替换为用户提供的 SSH 别名；否则转发端口会被占用：

```sh
ssh -N -L 8780:127.0.0.1:8780 SPARK_SSH_ALIAS
```

浏览器访问 `http://127.0.0.1:8780`。此结构不会开放互联网端口；后端是单用户、单进程研发服务，无多人身份认证。

## 模型通过基础探针后

- 导入公开教学例，仅用于功能演示；使用公开身份不作为盲测答案。
- 准备专家独立器物和独立参照，先校验清单，再执行有/无Skills对照。专家标签保存在模型不可读的位置。
- StepFun凭据准备好后，先用公开文字验证一份完整反证闭环：预览→批准内容→单次审查→新版本→主 Agent 回看原图→逐项回应→导出。
- 页面“已配置”只表示环境配置完整，不等于探针或专业评测通过；依据实际结果文件记录成功。

## 失败与回退

模型超时/格式错误保留已发生调用、使用量（若提供）、图像派生关联和失败状态；不使用演示固定答案。容器参数不兼容时根据版本说明删改项目适配参数并记录，不能静默降为文本模型。GB10的 DeepGEMM 错误可参照用户培训第9页 FP8/triton配方，但不要用于覆盖已验证NVFP4设置。

审查中断的外部调用状态可能未知，不自动重试。新案或明确补证按 Episode 预算继续；总36模型调用、60工具调用、900秒和最多初判加两次完成修订仍生效。

## 实测记录

每次写新结果目录：机器/GPU/驱动、CUDA/vLLM版本、容器digest、模型revision、generation设置、来源图哈希、预处理版本、冷/热定义、运行日志、所有失败、调用与usage、单次和总时间、专业盲评及其分母。缺失项写未测，不写0。
