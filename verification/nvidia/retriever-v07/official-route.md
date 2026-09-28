# NeMo Retriever 官方路线与独立候选验收

截至2026-09-29。以下记录仅说明官方支持、实际分发和候选部署，不代表陶瓷专业质量或专家验收。

## 首选：Embedding NIM 2.3

[NVIDIA Embedding 支持矩阵](https://docs.nvidia.com/nim/nemo-retriever/embedding/latest/support-matrix.html)明确列出 DGX Spark / Arm64。GB10 的 `llama-nemotron-embed-vl-1b-v2` 支持 FP16/FP8；`nemotron-3-embed-1b` 的 GB10 配置为 FP16。对应[Reranking 支持矩阵](https://docs.nvidia.com/nim/nemo-retriever/reranking/latest/support-matrix.html)也列出 Spark，自2.3起支持 ARM64；VL 1B v2 在 GB10 采用 FP16。本次不同时加载 reranker。

[官方2.3发布说明](https://docs.nvidia.com/nim/nemo-retriever/embedding/latest/release-notes.html)明确新增VL1B的GB10支持。[Get Started](https://docs.nvidia.com/nim/nemo-retriever/embedding/latest/getting-started.html)说明 NGC 容器认证及 HF / NGC 权重提供方式。下载专用模式可在 CUDA 初始化前结束；正式验收应检查 `/v1/health/ready` 和实际 `/v1/embeddings`，仅包安装、Docker状态或静态测试不能算服务成功。

Spark 实际尝试读取三份官方 manifest：`nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2:2.3`、同模型`:2.3.0`、`nvcr.io/nim/nvidia/nemotron-3-embed-1b:2.3`。三者被 NVIDIA CND 中国IP分发规则拒绝，未取得可固定的镜像digest。现有 NGC/HF 环境凭证与 Docker NGC 认证均未发现。正式路线必须从[NVIDIA 指定中国合作门户](https://catalog.ngc.nvidia.com/china-nim-distributors)取得合法版本映射、ARM64镜像digest、资产与授权；不能更换非官方仓库或经其他区域代理绕过该规则。当前 Embedding NIM 没有部署。

## 开放组件候选：官方 embedding 模型 + cuVS

[NVIDIA 官方模型卡](https://huggingface.co/nvidia/llama-nemotron-embed-1b-v2)将公开文本模型定位为多语言、跨语言检索，包含中文评估；2048维输出，模型上下文上限8192token。本候选使用固定revision `113abe4acafa848e77ead9c0623205e511932348`，不是未经固定的 `main`。HF元数据实测 `gated=false`，safetensors 为2,471,644,736字节，官方LFS SHA256 `45f8440682a89ac577cc8d53b1bb345804772adb7b34e0573562e2fca4e62b0d`。许可证与官方Python实现随原件保存，模型代码已查看，运行时仅使用本地文件。

Spark 到官方 HF 的普通请求实测网络不可达；IPv4请求也超时。桌面可访问官方公开仓库。先通过可恢复的 SHA 分块 SSH 传输了模型元数据与官方 CuPy wheel；长单流 SSH 曾断开，原因未确定，保留失败记录。随后按固定版本官方 HF 响应解析到其官方 CDN，Spark IPv4 实际返回200并成功恢复分段下载；13份文件共2,480,835,358字节已完整校验，权重 SHA 与官方 LFS SHA 一致。签名 URL 仅私下保存，不进入公开代码和日志。最后两段恢复加整体 SHA 用时10.31秒，不是整个权重下载时间。此路线使用 NVIDIA 开放模型，不访问受限 NIM镜像，不称 Embedding NIM。

[cuVS 安装指南](https://docs.nvidia.com/cuvs/installation)提供 Linux aarch64 预编译包，[Python 安装说明](https://docs.nvidia.com/cuvs/installation/python)提供 CUDA13 pip路线。候选固定 `cuvs-cu13==26.8.1`、`pylibraft-cu13==26.8.0`、`cupy-cuda13x==14.2.0`。官方镜像未取得，因此开放服务不报告容器digest；使用完整模型manifest、Python依赖下载SHA与部署代码SHA分别固定执行身份。

[cuVS Brute Force API](https://docs.nvidia.com/cuvs/api-reference/python-api-neighbors-brute-force)接受CUDA数组并在GPU计算精确近邻。25条摘要采用小型cosine平坦索引，保留GPU矩阵，并将实际结果与CPU同向量计算交叉核对。小语料服务实测不能推算大库吞吐、检索收益或器物准确率。

[NeMo Retriever Library支持矩阵](https://docs.nvidia.com/nemo/retriever/26.8.1/extraction/prerequisites-support-matrix/)规定本地GPU路径为Linux/CUDA13/Python3.12；当前官方SDK版本26.8.2。SDK安装与本服务实际调用是不同状态。候选使用官方NeMo Retriever开放embedding模型及cuVS，不会把仅安装SDK写成运行官方完整SDK管线，也不称NVIDIA认证。

## 数据与原证据边界

候选只使用当前 `knowledge/seeds.json` 的25条项目原创授权中文摘要，原件SHA256为 `613257e15b09f8a5d86edb7515ae98ee45ffb518364a67e7787364fbdae9ee6b`。独立测试快照包含25个来源、25个正文段落，沿用项目原知识实现生成和验证document revision/SHA、chunk ID/SHA及locator；正文或locator变更即拒绝。独立快照SHA256为 `e3b1f9290e502d27d2ecae2b16fc8a611aed5367d693e4f678df7f2b0cc1be24`，不是生产案例的运行快照。

GPU检索只能排序实际冻结段落。中文查询后仍读取原 `read_snapshot` 正文，核对返回身份与内容；候选服务不颁发生产阅读回执、引用权限或研判意见，也不改变现有8005模型、8780后端、80/90秒预算和证据门禁。摘要及相关性仍未经专家核验。

## 资源与待验范围

启动前协调GPU加载，最多一个新embedding模型，回环8003；已有单8B保持运行。Spark统一内存不能用离散显卡VRAM读数替代，按实际MemAvailable观察。候选启动要求至少45GiB可用，正式就绪检查剩余不少于32GiB，并每2秒读取系统 MemAvailable。低于32GiB时只终止本候选进程；这属于软检查，采样间隙可能发生越界，不是硬内存限额或资源隔离。batch最多2，输入超过1024token拒绝而不静默截断。本候选限制小于官方模型最大上下文，不宣称改变原模型能力。

独立开放模型/cuVS服务已实际完成CUDA前向、25段编码、5条中文查询与原客户端9次HTTP验收，实际健康和身份核查通过；生产默认仍SQLite。具体现场数字和收据见 `integrations/nvidia_retriever/README-open-service.md` 与本目录 `real-client-acceptance.json`。专业相关性、专家验收、全文报告收益均未测量，Embedding NIM仍未部署。

## 已完成的实际基础验证

官方 `cuvs-cu13==26.8.1`、`libcuvs-cu13==26.8.1`、`pylibraft-cu13==26.8.0` 与 `cupy-cuda13x==14.2.0` 在独立环境实际安装，cuVS 先经只读生产 Torch 加载 CUDA 动态库。无模型探针在 GB10 构建32×8 CUDA矩阵与真实 cuVS brute-force索引，GPU池1536字节；距离与CPU点积最大误差5.96×10⁻⁸。近共线样本的一处邻居次序有差异，原始返回值保留，不能称 exact top-k parity，更不代表中文业务检索质量。

首次模型启动在配置读取阶段退出，原因是隔离环境原继承的 Transformers5.14.1 与该固定版本原配置不兼容；没有成功向量输出，也不是专业模型质量失败。原官方配置、Python代码和权重均未改动。只在候选隔离环境固定 Transformers4.44.2/tokenizers0.19.1，生产包仍保持原版本。CPU实测可读取原模型配置与2048维 tokenizer，25段共2628token、最长130token，该CPU检查自身不算GPU部署；随后第三次启动已实际完成GPU服务验收。

每次修改服务后重建组合运行清单，启动前实际检查13份模型文件、原快照文件及逻辑 SHA、7份部署/原客户端代码和14份隔离包版本/来源 SHA。该身份是本地组合清单 SHA，不是容器 digest 或硬件远程证明。正式验收还要求实际健康响应绑定相同模型、revision、权重 SHA、资料快照、代码清单、CUDA设备与索引、2048维和25段数据；客户端前后两次核查，并记录真实 HTTP 响应 SHA。


第二次启动进一步暴露Triton编译缺Python.h，实际停止。官方Ubuntu旧apt缓存包0.15下载404被保留；只在候选下载新的官方签名InRelease/Packages索引、验证标准archive keyring签名与索引SHA，再固定3.12.3-1ubuntu0.17 arm64 dev deb SHA945ad3f651f683c11e72d19d804b1cff097308dcffa01057635cba038f875164。仅候选解压、CPATH限定候选，原Triton driver.c实际CPU编译/link通过；未改变系统0.10包或生产Torch。最终运行清单逐项绑定header、编译器和代码字节，第三次实际GPU运行与原客户端验收完成。
