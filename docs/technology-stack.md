# 瓷证技术栈说明

[仓库主页](../README.md) · [项目说明](project-overview.md) · [部署指南](deployment-guide.md)

本页按**主案卷流程、已部署独立服务、后续研究路线**列出实际技术栈。版本来自当前源码、固定配方和实际运行回执；当前后端为 **0.7.0**，素材迭代号不是应用版本号。核验日期为 2026-09-29。

## 一、主流程：研究方法、视觉与可追溯报告

![瓷证系统架构：本地视觉、Skills、固定资料、NAT与批准文字协作](../site/report-assets/product-architecture-v09.svg)

| 技术 / 模型 | 实际版本或身份 | 在项目中做什么 | 实现及运行证据 |
|---|---|---|---|
| NVIDIA DGX Spark / GB10 | Linux ARM64；compute capability 12.1；driver 580.159.03；约 119.7 GiB 统一内存 | 本地照片、视觉生成、方法执行、案卷和独立模型服务共存 | [五服务只读记录](../verification/software/v09/current-node-readonly.json) / [NIM现场硬件及共存](../evidence/nim-v09/final-coexistence.json) |
| NVIDIA CUDA / PyTorch | 原生视觉 Torch **2.14.0+cu130**、Torchvision 0.29.0+cu130；CUDA 13.0 | 在 GB10 实际运行视觉生成，保存 token、图像身份、耗时及响应 SHA | [视觉配方](../integrations/spark_transformers/requirements-gpu.txt) / [实际14调用绑定](../verification/nvidia/v07-workflows/round-12/native-binding.json) |
| Qwen3-VL-8B-Instruct | `Qwen/Qwen3-VL-8B-Instruct`；BF16；本地官方权重逐文件 SHA；Transformers **5.14.1** | 多图 / 局部观察、制作时期 / 窑口 / 风格研究及补证修订 | [`adapter.py`](../integrations/spark_transformers/adapter.py) / [真实原生请求](../verification/nvidia/v07-workflows/round-12/native-requests.json) |
| NVIDIA Agent Skills 方法参考 | 参考 [NVIDIA Skills文档](https://docs.nvidia.com/skills) 与[官方仓库](https://github.com/nvidia/skills)；本项目七个自研包按整包 SHA 固定 | 将路由、编目、比较、状况、来源、文字凭据与修订写成按需加载方法 | [`skill_runtime.py`](../cizheng/skill_runtime.py) / [`skills/`](../skills/)；不冒称官方 Verified |
| NVIDIA NeMo Agent Toolkit | `nvidia-nat==1.9.0` / `nvidia-nat-langchain==1.9.0`；自研插件 0.1.0 | 独立离线图核对已选报告的资料版本、段落、哈希与成功读取回执 | [固定依赖](../integrations/nvidia_nat/pyproject.toml) / [注册图](../integrations/nvidia_nat/configs/evidence.yml) / [实际修订审计](../verification/nvidia/v07-workflows/round-12/revision/nat-audit.json) |
| StepFun 阶跃星辰文字模型 | **`step-3.7-flash`**；Plan Base URL `https://api.stepfun.com/step_plan/v1` | 真实批准公开或脱敏文字的反证审查；不发送照片；问题交回本地模型重新观察和修订 | [`review_client.py`](../cizheng/review_client.py) / [真实审查与修订记录](../verification/nvidia/v07-workflows/README.md) / [当前配置](../verification/software/v09/current-node-readonly.json) |
| LM Format Enforcer | **0.11.3** / interegular **0.3.3** | 可选生成期 JSON 约束与短动作协议；宿主继续检查语义、证据、权限 | [结构实现](../integrations/spark_transformers/structured_generation.py) / [CPU固定依赖](../requirements-structured-tested.txt) |
| Python / FastAPI / Pydantic / Uvicorn | Python 3.11+；本机固定 FastAPI **0.115.6**、Pydantic **2.13.4**、Uvicorn **0.51.0** | 案卷 API、权限、预算、异步任务、版本与导出 | [`requirements-tested.txt`](../requirements-tested.txt) / [`pyproject.toml`](../pyproject.toml) |
| SQLite / 文件存储 | 案卷 revision / 原件 SHA / 固定资料版本与段落 | 本案资料检索、实际正文读取、工具回执、修订历史和离线案卷 | [`store.py`](../cizheng/store.py) / [`knowledge.py`](../cizheng/knowledge.py) |
| HTML / CSS / JavaScript | 原生浏览器界面；DOM 检查用 jsdom **29.1.1** | 本地专业工作台、图像区域、三套公开教学案卷、六维规则筛查 | [`static/`](../static/) / [`site/`](../site/) / [`package.json`](../package.json) |

**主流程关系**：视觉与逐项判断由本地模型承担；Skill 提供研究方法；资料读取与权限由工具宿主执行；NAT 核查来源身份；StepFun 提出批准文字反证；本地模型重新看图和修订。NAT 引用身份正确不等于文献支持归属，工具格式正确不等于专业判断正确。

## 二、实际部署的独立 NVIDIA 服务

| 服务 | 实际固定版本 / 模型 | 已完成工作 | 业务接入边界 |
|---|---|---|---|
| **NVIDIA NIM:8007** | 官方中国伙伴 Spark ARM64 Model-Free NIM **2.1.8**；nim-stack 0.1.0 / **nim_sdk 0.12.7** / nimlib 0.18.1 / SGLang 0.5.16 / Torch 2.11.0+cu130 / Transformers 5.12.1；Qwen3-4B-Instruct-2507 BF16 | 保留原厂入口、NGINX 和 SDK；实际唯一公开文本 POST 与同容器前八步 CUDA trace 绑定 | 纯文字标准接口；未替换视觉 / 主报告；原始输出的来源措辞仍需专业复核 |
| **TensorRT-LLM:8006** | 官方 ARM64 **1.3.0rc13**；Torch 2.11.0a0（NVIDIA 26.02）/ CUDA 13.1；Qwen3-4B-Instruct-2507 BF16 | 实际唯一公开文字 POST、模型 / 容器身份与前八迭代 CUDA 绑定 | **PyTorch backend**；没有序列化 TRT engine；不是已完成的视觉加速或整案替换 |
| **NVIDIA Embedding＋cuVS:8003** | `nvidia/llama-nemotron-embed-1b-v2` 固定 revision `113abe4acafa848e77ead9c0623205e511932348`；2048 维 BF16；cuVS / libcuvs **26.8.1**；RAFT / RMM **26.8.0**；CuPy **14.2.0**；Torch 2.14.0+cu130 / Transformers 4.44.2 | 25 段授权中文摘要 CUDA cosine brute-force 索引；原客户端 9 次实际向量 HTTP / 5 个查询；50 条返回身份 / 10 个正文 SHA 核对 | NVIDIA 开放组件服务；**非 Embedding NIM，完整 Retriever SDK 未安装**；主案卷检索仍 SQLite |

NIM 与 TensorRT-LLM 复用同一组固定纯文本 Qwen 4B 权重：14 文件、8,060,918,292 字节。它们的发布标签、SDK 版本、CUDA 版本和模型参数量是不同口径；不能把其中一个版本填给所有服务。

| 独立组件固定身份 | 实际值与来源 |
|---|---|
| NIM 镜像 | `tgcr-gz.turing-agi.com/public/nvidia/sglang-model-free-nim-spark@sha256:7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9` |
| NIM 原入口 | `/opt/nim/start_server.sh`；[现场软件身份](../evidence/nim-v09/software-identity.json) / [完整部署及失败边界](nim-v09-update.md) |
| TensorRT-LLM 镜像 | `nvcr.io/nvidia/tensorrt-llm/release@sha256:4f30c464ead64fb9727a24064b25057dacc07bef848022421108e544c91f0965` |
| TensorRT-LLM 原件 | [固定配方](../deploy/tensorrt-llm-spark/README.md) / [实际接口及GPU证据](../verification/nvidia/tensorrt-llm-v08/README.md) |
| 独立检索身份 | 无容器 digest；固定运行清单、权重、模型代码、依赖与读取快照共同绑定，见[实际运行清单](../verification/nvidia/retriever-v07/deployment-runtime-manifest.json)和[复现说明](../integrations/nvidia_retriever/README-open-service.md) |

## 三、GPU 观测与工程验证工具

| 工具 | 版本 / 实际范围 | 结果如何解读 |
|---|---|---|
| NVIDIA Nsight Systems | **2025.3.2**；限定第 03 轮首个双图视觉 NVTX 区间 | 实际采集 GPU 活动；[摘要](../verification/nvidia/v07-workflows/round-03/nsight-summary.json)不等同整案时长或提速比 |
| PyTorch / SGLang Profiler | TRT-LLM 执行器前八迭代；NIM 同一容器内部 SGLang 前八步 | 核对实际 CUDA kernel / runtime、容器、PID、请求响应 SHA 与时间窗；不是完整请求基准 |
| NVIDIA Container Toolkit / CDI | 实际 Docker GPU `--device nvidia.com/gpu=all` 路线 | NIM 与 TensorRT-LLM 固定镜像执行；版本不能从设备参数倒推，因此未填未核验的精确包号 |
| pytest / 浏览器 DOM | pytest 8.3.4；37 项实际浏览器合同；完整工程回归见[软件记录](../verification/software/v09/regression-summary.json) | 校验权限、版本、输入、索引身份、预算与导出；不计作陶瓷准确率或独立专家样本 |

不同服务的运行库相互隔离。尤其原生视觉 Transformers 5.14.1 与开放检索 Transformers 4.44.2 不应混装；NIM 和 TRT-LLM 保留官方容器内软件。系统 MemAvailable、容器 cgroup、Torch allocator 与下载体积是不同指标，不把任何一个直接称作整机 GPU 峰值。

## 四、进一步优化与扩展路线

| 技术 | 当前状态 | 拟验证的用途 |
|---|---|---|
| 更大视觉模型 / 量化 | 32B 候选曾做协议检查，真实双图区域合同失败，未采用；35B / NVFP4 等配方为候选 | 以固定专家样本、模型 / 资料 / 预算比较质量与完成时延后再选型 |
| NVIDIA FLARE | 研究路线，未部署联合训练网络 | 经许可的博物馆 / 机构数据留在各自端，探索受控联合训练与独立保留集评估 |
| NVIDIA NeMo RL | 研究路线，未实施自动在线强化学习 | 经专家审核的反馈形成离线训练材料，评估后训练与可回滚模型版本 |
| Laya | 有界离线文字影子适配入口，默认禁用；未运行其路由模型 | 对任务选择及补证路由做真实标注、影子评测；不生成真品概率 |
| Jev | 尚未接入；浏览器 Agent 方向 | 在授权范围研究公开目录资料采集；不作为照片真假分类器 |
| 智能眼镜 / 手持设备 / 桌面采集箱 | 受控采集桥接与 Python 客户端已有；未适配品牌 SDK 或制造采集箱 | 多视角、色卡、比例尺与传感器单位进入同器案卷；采集硬件需标定及业务验证 |
| Dynamo / vLLM / 完整 NeMo Retriever SDK | 未作为当前生产服务部署 | 依据多用户负载、支持矩阵和实际收益决定是否引入 |

[模型选择](model-selection.md) · [32B候选及边界](larger-model-candidates.md) · [设备接口](device-capture.md) · [Laya适配](../integrations/laya_router/README.md) · [专家验证接入](expert-validation-intake.md)

## 五、作品演示与软件许可

主 Demo 使用公开馆藏素材、真实软件页面和已归档运行记录的重建呈现；它不是连续实时推理录像或专家鉴定证明。文字审查模型与视频配音服务为独立用途，音频不承载器物研究输入。

| Demo 生产配音 | 实际使用 |
|---|---|
| StepFun TTS 模型 | **`stepaudio-2.5-tts`**；实际 Plan 模型列表确认并完成语音调用 |
| 官方系统音色 | **`ruyananshi`（儒雅男士）**；不是克隆真人声线 |
| 合成与素材范围 | 18 个场景的公开中文讲稿；请求均 HTTP 200；SSE 返回 MP3 与逐词时间戳；无原图或私有案卷输入 |
| 语速与视频制作 | 请求 `speed=1.0`，后期不做语音加速；固定场景画面，仅 200ms 淡入淡出；固定视频地址不变 |

[18段实际配音及成片验收](../verification/media/stepfun-demo-v10/index.json) · [公开输入与离线复现](../tools/media/stepfun-demo-v10/README.md)。最终视频已完整解码，45条字幕对应实际成片帧已查看，18场景画面区域采样稳定；ASR用于内容核对，不作为自然度评分。

项目自研代码 [MIT](../LICENSE)，Qwen 与 NVIDIA 权重 / 容器遵守各自许可，公开馆藏图与记录依 Met Open Access / CC0；原机构不背书本项目。[第三方素材及权利](../THIRD_PARTY.md) · [视频固定地址](https://dingyucanada.github.io/cizheng-agent-skills/assets/cizheng-demo-v07.mp4)
