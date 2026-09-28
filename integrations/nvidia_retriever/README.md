# NeMo Retriever 独立候选客户端

本目录提供可选的本地文字 embedding 检索合同，不改变默认后台，也不替代原知识阅读工具。没有在 Spark 启动真实 NeMo NIM；离线协议测试使用合成文字和 MockTransport，不能证明中文检索收益。

## 接口与证据边界

`RetrieverClient.build_index(snapshot, expected_snapshot_sha256, allowed_bindings)` 接收运行已经冻结的知识快照与本案确切版本绑定。它核对原快照 SHA、来源范围、document revision、正文与 locator 的 chunk SHA，再只发送 `authorized_text` 段落到指定私有 endpoint。公共元数据、source URL、器物照片、全馆未绑定资料不会上传。

`search(index, query, expected_snapshot_sha256=..., limit=8)` 返回最多8个原段落的 identity 和 `semantic_score`。身份包含 document ID/revision/SHA、chunk ID/SHA 与 locator。服务端只返回向量；段落身份来自本地校验后的冻结索引。相似性分数不能当真伪、可靠性或支持论断的概率，返回结果没有阅读回执。

宿主必须通过现有 `read_snapshot` 阅读候选段落，并由原证据守门逻辑发放回执和引用权限。新轮次、不同 snapshot、模型或容器 digest 都重新建索引。`SnapshotIndex` 是当前进程的只读对象，没有从服务端或文件导入索引的入口。

```python
from integrations.nvidia_retriever import RetrieverClient

client = RetrieverClient(
    "http://127.0.0.1:8003",
    "nvidia/llama-nemotron-embed-vl-1b-v2",
    runtime_identity="sha256:" + verified_container_digest_hex,
)
try:
    index = client.build_index(
        frozen_snapshot,
        run_snapshot_sha256,  # 来自既有运行记录，不能临时相信检索响应
        case_document_version_bindings,
    )
    candidates = client.search(
        index, "口沿及底足形制", expected_snapshot_sha256=run_snapshot_sha256,
    )
    # 下一步调用原 read_snapshot；candidates 本身不可发放引用权限。
finally:
    client.close()
```

容器 digest 是执行者已核实的身份，不是客户端自动验证远程容器的方法。客户端要求回环或 RFC1918/IPv6 ULA 的字面 IP，拒绝公共地址、DNS名称、URL凭据与重定向；默认忽略环境代理。请求批次最多8段，最多512段、每段2000字符、查询200字符，响应上限2MB，向量必须有限、非零并维度一致。字符上限不是 tokenizer 的 token 上限；真实 NIM 返回超长输入错误时不截断或静默换模型。HTTP 超时默认为每阶段20秒，可设至60秒；服务排队与总工作流预算应由宿主统一限制。

## 候选部署

官方 NeMo Embedding 2.3 明确支持 `llama-nemotron-embed-vl-1b-v2` 的 ARM64/GB10，但尚未验证本机组合。其分发凭据规则与当前 LLM/VLM keyless NIM不同，见 [官方 Get Started](https://docs.nvidia.com/nim/nemo-retriever/embedding/latest/getting-started.html)。中国地区按 [NVIDIA正式合作渠道](https://catalog.ngc.nvidia.com/china-nim-distributors) 获取镜像及资产；门户授权、ARM64 tag、digest 与许可必须分别确认，不使用非正式重打包镜像。

[候选脚本](../../deploy/nvidia-serve-retriever.sh)默认只运行已经预取的 `/model/embed` 权重，挂载只读模型和独立 `/opt/cache`，使用回环8003、保留容器与日志，不传入模型下载凭据。脚本没有启动、拉取或登录的隐式动作。`prefetch` 是显式的下载专用模式，使用已有环境凭据而不打印值，无需 GPU；执行者只有在镜像分发及凭据条件均通过后才调用。当前脚本只接受原 NVIDIA 仓库；如正式中国合作门户提供另一个仓库，先核验其与官方版本的映射再单独更新允许仓库，不能仅替换前缀绕过身份检查。

```bash
export CIZHENG_RETRIEVER_IMAGE=nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2@sha256:<verified-64-hex>
export CIZHENG_RETRIEVER_WEIGHTS=/absolute/existing/staged-weights-root
export CIZHENG_RETRIEVER_CACHE=/absolute/existing/isolated-runtime-cache
export CIZHENG_RETRIEVER_PORT=8003
# 由执行者选择资产预取（需既有HF_TOKEN或NGC_API_KEY）；此命令会下载。
# CIZHENG_RETRIEVER_PROVIDER=ngc bash deploy/nvidia-serve-retriever.sh prefetch
bash deploy/nvidia-serve-retriever.sh
```

正式检查 `/v1/health/ready` 的 `ready=true`，不能只用 Docker 状态代替。保存模型 ID、容器 digest、权重校验结果、响应向量维度、系统可用内存与进程峰值。FP8不能默认当更省内存：官方在其它 GPU 的 VL模型完整 footprint 为FP16约5.26–5.49GiB、FP8约7.96–9.04GiB，未列GB10结果。[官方内存表](https://docs.nvidia.com/nim/nemo-retriever/embedding/latest/performance.html#llama-nemotron-embed-vl-1b-v2)

25条摘要先比较已有关键词检索与 embedding 的中文专家相关性标注、Recall@k、错误引用和延迟。没有收益就淘汰或仅离线建索引；没有必要同机常驻 Milvus、PDF extraction、reranker。32B视觉推理的内存峰值必须先测，不能据纯权重大小认定多个容器可并存。

## 本机离线协议检查

在已具备项目依赖的 Python≥3.11 环境运行，不安装新软件：

```bash
python -m pytest -q integrations/nvidia_retriever/tests/test_client.py
bash -n deploy/nvidia-serve-retriever.sh
```

覆盖版本绑定、快照及段落变更、外部／含凭据 endpoint、错误响应顺序、向量异常、模型／runtime身份变化和空语料不请求。测试没有真实网络、模型调用、专业结论或质量评分。

2026-09-28验证：现存Python3.11环境的21项协议测试全部通过（测试本身0.21秒；首次依赖读取时间另计）。另以临时fake Docker验证5项启动合同，检查固定digest、ARM64拒绝、回环端口、保留NVIDIA entrypoint、显式prefetch和凭据不输出；不运行真实Docker镜像。所有候选shell脚本语法检查通过。
