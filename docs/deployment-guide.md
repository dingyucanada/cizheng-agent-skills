# 瓷证部署指南

[仓库主页](../README.md) · [项目说明](project-overview.md) · [技术栈清单](technology-stack.md)

本指南分开说明**本机无模型试用、Spark 主流程、已部署的独立 NVIDIA 服务**。应用版本为 **0.7.0**。当前部署记录的核验时刻为 **2026-09-29 00:41:18 UTC**；服务状态是该次实际核验结果，重新部署须再次检查。

## 一、本机试用：无需模型或 API key

需要 Python 3.11+。在仓库根目录执行：

```bash
git clone https://github.com/dingyucanada/cizheng-agent-skills.git
cd cizheng-agent-skills
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m cizheng.demo --guided --data-dir ./data
bash deploy/start-local.sh
```

打开 `http://127.0.0.1:8780`。`start-local.sh` 使用仓库的 `.venv/bin/python`、绑定回环地址、保持一个后端 worker；如端口已占用，可在启动前设置 `CIZHENG_PORT`。教学导入为零模型调用，支持重复导入和保留后续人工修改。

没有视觉模型时，可以完成器物登记、照片查看和区域操作、关键词资料检索、来源与状况整理、六维规则筛查、准备复核与离线交接。点击 AI 研究会明确提示未配置模型，不会伪造一份 AI 报告。GitHub Pages 的[免上传体验](https://dingyucanada.github.io/cizheng-agent-skills/demo.html)则可直接打开，不用安装；公开网页采用预置教学记录和浏览器本地状态。

## 二、Spark 当前实际拓扑

| 端口 | 实际服务 | 实际模型 / 软件 | 主流程关系 |
|---|---|---|---|
| `127.0.0.1:8780` | 瓷证案卷后端 0.7.0 | FastAPI / SQLite / 自研工具与七个 Skills | 业务入口；当前视觉模型为 8005 |
| `127.0.0.1:8005` | 原生 Transformers 视觉接口 | Qwen3-VL-8B-Instruct / BF16 / Torch 2.14.0+cu130 | 主视觉、观察和本地修订 |
| `127.0.0.1:8006` | TensorRT-LLM 1.3.0rc13 | Qwen3-4B-Instruct-2507 / BF16 / PyTorch backend | 已部署独立文字服务 |
| `127.0.0.1:8003` | NVIDIA 开放 Embedding＋cuVS | llama-nemotron-embed-1b-v2 / 2048 维 / cuVS 26.8.1 | 已部署独立检索；主案卷仍 SQLite |
| `127.0.0.1:8007` | 原厂 Model-Free NIM Spark 分发 2.1.8 | Qwen3-4B-Instruct-2507 / BF16 / nim_sdk 0.12.7 | 已部署独立标准文字接口 |

这五项服务实际共存，并有[当前只读回执](../verification/software/v09/current-node-readonly.json)。NIM / TensorRT-LLM 是纯文字服务，不承担照片识别；三个独立模块没有自动替换主视觉或主资料路径。当前节点为 Ubuntu Linux ARM64、NVIDIA GB10、compute capability 12.1、driver 580.159.03；统一内存约 119.7 GiB。版本和模型身份详见[技术栈](technology-stack.md)。

## 三、先准备视觉服务，再连接业务后端

### 1. 隔离运行环境与权重

在 Spark 项目目录建立独立视觉环境，使用实际 CUDA 轮子配方：

```bash
python3 -m venv .spark-model-venv
.spark-model-venv/bin/python -m pip install -r integrations/spark_transformers/requirements-gpu.txt
```

配方固定 Torch 2.14.0+cu130、Torchvision 0.29.0+cu130、Transformers 5.14.1 和结构约束库。实际驱动、CUDA 运算、模型加载与生成仍由就绪检查核验。下载器环境与推理环境分开；已有经核对权重时不重复下载。

```bash
python3 -m venv .spark-download-venv
.spark-download-venv/bin/python -m pip install -r integrations/spark_transformers/requirements-download.txt
.spark-download-venv/bin/python -m integrations.spark_transformers.download_model \
  --model Qwen/Qwen3-VL-8B-Instruct --revision master \
  --output "$HOME/cizheng-release/models/Qwen3-VL-8B-Instruct" \
  --cache-dir "$HOME/cizheng-release/models/modelscope-cache"
```

本次视觉权重约 17.55 GB，官方公开来源为 ModelScope；不要求先登录 Hugging Face。下载器生成 `_file_manifest.json` 并逐文件计算 SHA256；`master` 是可变引用，最终身份以文件清单为准。原生服务重新核对全部权重、使用 `local_files_only=True` / `trust_remote_code=False`。已有权重的离线清单生成只证明本地文件身份，不追认下载来源。[完整视觉配方](../integrations/spark_transformers/README.md)

### 2. 启动视觉接口：当前使用 8005

下例模型目录对应上一步；如果节点已有验证模型，设置实际目录和对应清单。若当前 8005 已在运行，直接健康检查，不重复启动。

```bash
source .spark-model-venv/bin/activate
export CIZHENG_SPARK_MODEL_NAME=Qwen/Qwen3-VL-8B-Instruct
export CIZHENG_SPARK_MODEL_DIR="$HOME/cizheng-release/models/Qwen3-VL-8B-Instruct"
export CIZHENG_SPARK_PORT=8005
export CIZHENG_SPARK_LOG_DIR="$HOME/cizheng-release/logs/native-vision"
bash integrations/spark_transformers/start.sh
```

`start.sh` 的未配置默认端口为 8000，历史视觉配方及 `deploy/local.env.example` 使用 8001；**当前部署应显式覆盖为 8005**。接口回环绑定、单进程、单并发；权重核对、实际 CUDA 小矩阵、GPU 加载和合成白图预热全部通过后 `/health` 才返回 200。合成预热只证明部署就绪。

若同类 Ubuntu ARM64 / Python 3.12 节点缺少 `Python.h`，先按[固定头文件配方](../integrations/spark_transformers/README.md#启动与真实就绪)执行项目内解压，再设置 `CIZHENG_SPARK_HEADERS_DIR` 与 `CIZHENG_SPARK_CACHE_DIR`。配方固定特定 Ubuntu 签名包；不能把其他系统或不可取得的版本当作已满足。项目不自动升级系统 Python 或全局 CUDA。

### 3. 配置主后端与模型优化开关

主后端使用自己的 `.venv`，不要把视觉、NAT 和 Retriever 的依赖混装。按照本机试用步骤准备后端环境，在启动前导出：

```bash
source .venv/bin/activate
export CIZHENG_MODEL_URL=http://127.0.0.1:8005/v1
export CIZHENG_MODEL=Qwen/Qwen3-VL-8B-Instruct
export CIZHENG_DISABLE_THINKING=0
export CIZHENG_GUIDED_WORKFLOW=1
export CIZHENG_STRUCTURED_OUTPUTS=1
export CIZHENG_COMPACT_ACTIONS=1
export CIZHENG_DATA_DIR=./data
bash deploy/start-local.sh
```

启动前把 `CIZHENG_MODEL_REVISION` 设置为 `/health` 中已核对的 `weights_revision`，形如 `files-sha256:<真实组合SHA256>`；否则保持 `unverified`，不把路径、`master` 或手工标签当作固定权重身份。`deploy/local.env.example` 只提供变量示例，程序不会自动读取该文件；编辑后须在私有启动环境导出变量。模型加载完毕不等于业务报告已通过，需另核验实际照片、观察、引用、修订及导出。

三个开关分别记录：协调器有界预读本案材料和首批图片；LM Format Enforcer 在生成中限制 JSON 结构；短动作协议缩短动作传输。宿主继续核对权限、数字范围、图像关联和证据资格，保留原模型响应，不补写专业理由。默认配置关闭这些开关，启用时需固定版本。[受控工作流及预算](controlled-workflow.md)

当前每轮上限为 12 次模型调用、20 次工具与 300 秒，单次模型请求最多 90 秒；整个案卷最多 36 次模型、60 次工具与 900 秒。视觉输出上限 800 tokens、动作上限 2500 tokens。超时和截断保留已消耗费用，不重置预算。优化效果还需同预算完整业务比较，不以健康接口、短文本请求或库名推出整案提速。

## 四、StepFun 文字协作与 NVIDIA NAT

### 1. StepFun：仅批准文字进入 API

启动后端前设置以下非敏感变量；`CIZHENG_STEPFUN_KEY` 由私人进程环境提供，不写入 README、Git、脚本或网页。

```bash
export CIZHENG_STEPFUN_URL=https://api.stepfun.com/step_plan/v1
export CIZHENG_STEPFUN_MODEL=step-3.7-flash
```

Plan 的 Base URL 保留到 `/v1`，客户端只追加一次 `/chat/completions`。普通 API 账户的默认地址是 `https://api.stepfun.com/v1`，两种账户与接口权限应分别核实。工作台先准备可见的公开或脱敏文字摘要，用户批准后才发送；原图不会进入文字审查请求。实际反证审查和本地修订保存在[真实流程记录](../verification/nvidia/v07-workflows/README.md)。Demo 配音使用的语音 API 与研究文字审查是独立用途，部署研究后端不依赖配音服务。

### 2. NAT：独立离线身份核查

使用 Python 3.11–3.13 的独立环境：

```bash
python3.11 -m venv .nat
.nat/bin/python -m pip install -e ./integrations/nvidia_nat
export CIZHENG_NAT_PYTHON="$PWD/.nat/bin/python"
```

上述变量同样须在案卷后端启动前导出。依赖固定 `nvidia-nat==1.9.0`、`nvidia-nat-langchain==1.9.0`；实际注册图为 `integrations/nvidia_nat/configs/evidence.yml`，工作流没有 LLM 或云端 exporter。应用通过 `scripts/nvidia-nat-call.py` 限制请求和禁用网络，核对本案已保存意见对应的资料版本、段落、SHA 和读取回执。NAT 身份核查成功不表示文献支持结论或器物真伪正确。

## 五、三个已部署独立 NVIDIA 服务怎样复现

各脚本按**固定现场配方**验收，不是任意模型的一键安装器。模型、镜像与资源先核对，再按唯一加载窗口启动；已运行服务只检查，不覆盖原容器、旧 trace 或失败记录。

### 1. TensorRT-LLM:8006

实际镜像为官方 ARM64 `1.3.0rc13`，模型为 14 文件、8,060,918,292 字节的 Qwen3-4B-Instruct-2507。固定目录为 `models/trt-qwen3-4b-instruct-2507`，真实权重验收清单为 `integration-evidence/trt-deploy/qwen4b-verified-model.json`。**在包含这些目录的部署根**，完成固定镜像 / 模型核对后：

```bash
bash deploy/tensorrt-llm-spark/probe_cuda.sh
TRT_LOAD_COORDINATED=yes bash deploy/tensorrt-llm-spark/start_candidate.sh
```

实际使用 `--backend pytorch`，没有生成序列化 TensorRT engine。单并发、最大序列 4096、每批 token 2048、KV 缓存上限 4096、24 GiB 容器限额；容器限额不等于全部统一内存峰值。加载前至少 32 GiB MemAvailable。镜像压缩传输约 19.55 GB，展开约 35.57 GB，下载与 GPU 加载应分开。[固定镜像、下载器参数及完整复现](../deploy/tensorrt-llm-spark/README.md)

### 2. Embedding＋cuVS:8003

实际开放模型为 NVIDIA `llama-nemotron-embed-1b-v2`，固定 revision `113abe4acafa848e77ead9c0623205e511932348`；13 文件合计约 2.48 GB。隔离服务有 25 段固定中文摘要 / 2048 维 CUDA 索引，原 `RetrieverClient` 实际完成五个中文查询与返回身份核对。主案卷仍使用 SQLite，完整 Retriever SDK 未安装。

现场候选 launcher 固定 `/tmp/cizheng-retriever-v07`，不能只改环境变量就称脚本适配了任意目录。先按[独立服务复现说明](../integrations/nvidia_retriever/README-open-service.md)准备该候选、原客户端只读快照、固定模型 / 依赖 / 头文件及运行清单，再执行：

```bash
export CIZHENG_RETRIEVER_ROOT=/tmp/cizheng-retriever-v07
export CIZHENG_RETRIEVER_PYTHON=/tmp/cizheng-retriever-v07/.gpu-venv/bin/python
bash deploy/nvidia-serve-retriever-open.sh health
# 仅在尚未启动、已协调模型加载且全部清单核对通过时使用 start：
CIZHENG_RETRIEVER_LOAD_APPROVED=1 bash deploy/nvidia-serve-retriever-open.sh start
```

开始加载要求 45 GiB MemAvailable；运行每两秒检查 32 GiB 阈值，越限只停候选。这是软保护，不能当作硬资源隔离。检索相似性不等于引用许可、专业相关性或真品概率。

### 3. 原厂 NIM:8007

实际路线为 NVIDIA 官方中国分发伙伴公开 Spark ARM64 Model-Free NIM 2.1.8，保留 `/opt/nim/start_server.sh` 原入口。固定镜像、原 SDK 身份与实际请求见[NIM 部署回执](nim-v09-update.md)。它复用经完整校验的 Qwen3-4B 纯文字权重；不是把直接启动的开源 SGLang 改名为 NIM。

在此前四服务都健康、固定镜像已取得、CDI GPU 设备与模型核对就绪后，启动脚本需要**恰好三个参数**：公开模型目录、固定模型验收清单、全新的证据目录。可在终端先设置实际路径：

```bash
export CIZHENG_NIM_MODEL_DIR=/absolute/path/to/verified/qwen3-4b
export CIZHENG_NIM_MODEL_RECEIPT="$PWD/verification/nvidia/tensorrt-llm-v08/qwen4b-verified-model.json"
export CIZHENG_NIM_EVIDENCE_DIR=/absolute/path/to/new/nim-evidence
bash deploy/nim-spark-v09/start_candidate.sh \
  "$CIZHENG_NIM_MODEL_DIR" "$CIZHENG_NIM_MODEL_RECEIPT" "$CIZHENG_NIM_EVIDENCE_DIR"
```

模型和新证据目录需换成节点真实位置；公开模型清单 SHA 为 `a41c5affd0d9dcc418f5d7aed2071c146347d3c4f676ee46a02b3a8ee0cba694`，脚本按它重新核对模型，不能临时造一份 JSON。该脚本要求原四项服务实际健康、8007 空闲和至少 32 GiB MemAvailable。实际配置单并发、4096 上下文 / 总 token 缓存、`mem-fraction-static=0.25`、关闭 CUDA graph、24 GiB cgroup、非 root、`cap-drop=ALL`；镜像压缩层约 11.50 GB、展开约 21.80 GB。当前唯一公开生成和八步 GPU trace 证明接口及执行，不是专业质量结论。[原始 NIM 证据](../evidence/nim-v09/index.json)

## 六、Skills 怎样设计与运行

`skills/<方法名>/SKILL.md` 使用 `name`、`description`、`compatibility` 与 `metadata`，正文写出适用范围、研究程序、工具、竞争解释和失败处理；可比较方法放在 `references/`。`cizheng/skill_runtime.py` 先发现描述，再按任务加载正文及资源，校验文件哈希与整包 SHA，拒绝越界、符号链接或变动资源。

宿主提供 `inspect_images`、`inspect_region`、`retrieve_references`、`read_reference`、`read_skill_resource`、`record_assessment` 等注册工具，按案卷权限、资料读取资格和实际预算执行。受控准备可以由协调器选取方法，此行为明确记录；未把它声称为模型自然发现。领域包由本项目开发，不携带模型权重或官方认证，标准格式不自动带来陶瓷判断能力。[七个方法入口](../README.md#skills方法怎样变成下一步) · [真实青花方法](../skills/bluewhite-attribution-test/SKILL.md)

## 七、验收、访问与更新

健康检查只读，不发模型请求：

```bash
curl --fail --silent http://127.0.0.1:8005/health
curl --fail --silent http://127.0.0.1:8780/api/status
curl --fail --silent http://127.0.0.1:8006/health
curl --fail --silent http://127.0.0.1:8003/v1/health/ready
curl --fail --silent http://127.0.0.1:8007/v1/health/ready
```

`/api/status` 可能包含本地会话信息，现场查看即可；对外仅发布已脱敏白名单回执。随后使用公开且获许可的材料核验生成、工具、引用、文字批准、重新看图、逐项回应及导出。照片 SHA 往返相等、NAT 身份正确、接口正常与专家判断正确是不同验收层。

本机离线工程检查：

```bash
python -m pip install -r requirements-structured-tested.txt
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests integrations/spark_transformers/tests integrations/nvidia_retriever/tests
npm ci --ignore-scripts
npm run test:web
python scripts/build-public-site.py
```

当前本机回归 1120 项通过，浏览器 37 项通过，Spark 新筛查 / 采集合同 54 项通过；集合存在重叠，不能相加成领域样本数。[本次软件回归范围](../verification/software/v09/regression-summary.json)

从笔记本通过本机已配置 SSH 别名访问案卷后端，例如 `ssh -N -L 8780:127.0.0.1:8780 YOUR_CONFIGURED_SPARK_ALIAS`；替换为自己的私人连接配置，不把地址、账号或密码写入仓库。公开 Pages 由 `site/` 构建发布，保持固定项目与视频地址；它不托管 Spark 模型、私人案卷或密钥。更新时保留原运行版本和失败证据，先验证新源码及实际健康，再有界切换后端；不要因新增独立候选停掉现有模型。[公开网页部署](github-pages.md)
