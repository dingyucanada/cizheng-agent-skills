# 独立 NVIDIA 开放模型 + cuVS 检索服务

2026-09-29，Spark 回环 `8003` 已实际就绪。固定 NVIDIA `llama-nemotron-embed-1b-v2` 官方公开权重在 GB10 上以 BF16 执行，25条原项目授权中文摘要得到2048维向量，cuVS在CUDA矩阵上构建、搜索cosine brute-force索引。原 `RetrieverClient` 未修改，真实调用 `/v1/embeddings`，独立服务另提供 `/v1/retrieval` 与原正文身份核对接口。

**生产默认仍是原 SQLite 检索。** 本次没有改8005视觉模型、8780业务后端或生产证据门禁，不给候选段落颁发生产读取回执、引用权限。这是已实测的独立开放组件服务，不是 Embedding NIM；服务环境 `SDK_installed=false`、`SDK_pipeline_used=false`。相似性排名不是可靠性、真伪概率或专业准确率，专家相关性与业务收益尚未测量。

## 实际验收

- 前后两次真实健康HTTP响应各核对37项：模型/revision/权重SHA、快照、当前代码清单、隔离包版本、header/编译器、GB10能力12.1、实际CUDA参数、2048维、25条GPU矩阵与真实cuVS索引等。
- 原客户端真实发送9次向量请求：4批 `passage` 覆盖原25段，5次 `query` 覆盖青花、旧修复、款识、Met18.61.4馆藏参照及盐类剥釉问题。全部HTTP200；五条真实query的实际ordered IDs与CPU/client一致。距离最大误差1.19×10⁻⁷，客户端共同结果分数最大误差6.28×10⁻⁸。这些是数值/身份核验，不是专业相关性评测。
- 50条返回身份与原冻结来源/段落revision、SHA和locator逐项一致；10个正文视图的内容SHA与原 `read_snapshot` 结果一致。公开验收摘要只保留身份和SHA，省略正文与完整向量。
- 实际修改snapshot、来源绑定分别HTTP409；未授权passage HTTP403。CPU原身份负例五项实际拒绝，脚本与结果一并保存。
- 启动业务计算16.3138秒，含25段编码与warmup，不含之前导入/完整SHA校验；Torch峰值分配2,523,421,696字节。有限验收总1.7868秒；25条小库的GPU搜索实测约0.339–0.971毫秒，不能外推大库吞吐。验收后系统MemAvailable约63.07GiB，8005/8780/TRT8006/本候选均HTTP200。

资料原件 `knowledge/seeds.json` SHA `613257e15b09f8a5d86edb7515ae98ee45ffb518364a67e7787364fbdae9ee6b`；独立冻结快照逻辑SHA `e3b1f9290e502d27d2ecae2b16fc8a611aed5367d693e4f678df7f2b0cc1be24`。这是当前25条项目摘要的小库验收，未接入私有专家资料，也不是生产某案例的运行快照。

## 固定部署身份与失败记录

官方模型revision `113abe4acafa848e77ead9c0623205e511932348`，权重2,471,644,736B、SHA `45f8440682a89ac577cc8d53b1bb345804772adb7b34e0573562e2fca4e62b0d`。13模型文件合计2,480,835,358B均实际SHA匹配。只执行已审阅固定原Python代码，local_files_only与离线环境开启。

本服务没有容器，因此 `container_digest=null`。组合运行identity `sha256:2772939ad8e9d1ad54354ce18e6df5bf289f153a9c9b4f8be9643aa24f2efc2f`；清单文件SHA `85350e818f706ae4fb98079927942272eb39cee0d7417415931d40f814971809`。身份绑定是本地逐字节检查与实际HTTP响应匹配，未宣称硬件或密码学远程证明。

首次启动遇原Transformers5.14.1配置兼容错误，未ready；只在隔离环境固定官方模型声明的4.44.2/tokenizers0.19.1。第二次在首个CUDA前向中遇Triton辅助模块编译缺 `Python.h`，未ready。保留两次实际失败，没有改原权重/模型实现或生产Torch。官方Ubuntu签名索引核验后下载arm64开发包3.12.3-1ubuntu0.17，仅解压候选236文件，CPATH只用于候选；原driver.c实际CPU编译/link通过，所有header/包/compiler SHA已绑定。系统Python仍原3.12.3-1ubuntu0.10，没有全局apt升级。第三次启动实际完成CUDA计算与验收。

启动要求MemAvailable≥45GiB；运行每2秒软检查，低于32GiB只停止候选。**这不是硬资源限额**，采样间隙可能越界。新模型加载须协调单一窗口，检查现有服务，不允许脚本隐式替换生产或下载受限NIM。

## 材料位置与复核

公开记录位于 `verification/nvidia/retriever-v07/`：`startup-receipt.json`、`real-client-acceptance.json`、`deployment-runtime-manifest.json`、`actual-public-byte-bindings.json`，以及原权重/模型代码/下载/隔离头文件与两个失败摘要。10份部署现场JSON与远端保存文件字节一致；客户端摘要经明确allowlist归一化，公开SHA与远端原件SHA不同，见清单，不能称原字节副本。原始完整收据私下保留。

在该目录运行 `audit_public_evidence.py`，只做离线身份核对，不发送HTTP/GPU请求。主仓库原21客户端合同测试已在独立环境实际通过；它们不替代上述真实服务验收。

`deploy/nvidia-serve-retriever-open.sh` 只控制既有隔离候选；新加载必须显式设置已协调的 `CIZHENG_RETRIEVER_LOAD_APPROVED=1`，服务回环绑定8003。复现时把本目录 `gpu_service.py`、`runtime_contract.py` 复制到候选根，`verify_runtime_manifest.py` 保存为 `verify-and-runtime-manifest.py`，`real_client_acceptance.py` 保存为 `real-client-acceptance.py`；`deploy/nvidia-retriever-candidate-launch.sh` 保存为 `launch-candidate.sh`。原客户端/知识实现保存为只读快照，按已固定清单取得官方公开权重、隔离依赖和header，不从生产目录写入或替换任何文件。清单发生变化必须重建并重新协调加载，禁止把旧health与新source混用。

官方支持、合法分发边界、下载和许可来源见 `verification/nvidia/retriever-v07/official-route.md`。正式Embedding NIM镜像当前仍受官方中国区域分发与认证要求限制；本开放服务成功不代表NIM镜像部署成功。
