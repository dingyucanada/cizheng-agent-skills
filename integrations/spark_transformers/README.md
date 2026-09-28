# Spark 原生 Transformers 接入

这是在官方容器下载通道无法及时完成时使用的独立部署路径。它让 Spark 的 GPU 执行真实视觉推理，通过本机 OpenAI 格式接口连接瓷证后台。模型输出原样返回，可选约束解码在生成时限制 JSON 结构，原工具合同仍由后台核查；没有固定教学答案、CPU推理或云端替代。

原生适配器未配置时默认Qwen/Qwen3-VL-2B-Instruct；本页明确配置当前实际节点的Qwen/Qwen3-VL-8B-Instruct及8001端口。约17.55GB官方权重核对、GPU预热与三项原始探针通过；LMFE结构约束也已实际在GPU生成合成红图JSON。公开双图full-workflow01因重复调用耗尽预算，第02轮在程序准备后因主动作超过90秒等待而失败；基础部署、格式与完整业务分别验收。最新业务结果见[STATUS](../../STATUS.md)和[公开记录](../../verification/nvidia/README.md)。这些不是陶瓷准确率、Skills增益或真品概率。

## 安装与权重身份

在 ARM64 Spark 的独立 Python 3.12 环境安装，避免修改已有团队环境：

```sh
python3 -m venv .spark-model-venv
. .spark-model-venv/bin/activate
python -m pip install -r integrations/spark_transformers/requirements-gpu.txt
```

CUDA轮子来自 [PyTorch官方CUDA13.0索引](https://download.pytorch.org/whl/cu130/torch/)。实测选择 torch 2.14.0+cu130、torchvision 0.29.0+cu130、Transformers 5.14.1；主机驱动、GPU计算和加载仍须现场验证。安装来源缓慢时可以另行选择可用PyPI镜像取得公开依赖，不能把CPU版torch当作CUDA版。

下载独立环境只需 ModelScope，避免把下载器和推理运行库耦合：

```sh
python3 -m venv .spark-download-venv
.spark-download-venv/bin/python -m pip install -r integrations/spark_transformers/requirements-download.txt
.spark-download-venv/bin/python -m integrations.spark_transformers.download_model \
  --model Qwen/Qwen3-VL-8B-Instruct --revision master \
  --output "$HOME/cizheng-release/models/Qwen3-VL-8B-Instruct" \
  --cache-dir "$HOME/cizheng-release/models/modelscope-cache"
```

`master`是可变引用，下载器会逐文件计算SHA-256，写入`_file_manifest.json`并生成组合身份。启动前再次核对文件字节与清单；不会伪造固定git revision。已有权重可用`--hash-existing`离线生成清单，但该操作只证明文件身份，不能推出原始下载渠道。既有清单保留，不静默覆盖。

官方模型来源：[Qwen ModelScope](https://modelscope.cn/models/Qwen/Qwen3-VL-8B-Instruct)。推理接口依据：[Transformers Qwen3-VL](https://huggingface.co/docs/transformers/model_doc/qwen3_vl)。`trust_remote_code=False`与`local_files_only=True`始终启用，加载阶段不访问云端。

## 启动与真实就绪

本次 Ubuntu ARM64 节点没有 Python.h。实际 torch 2.14 原生 GPU 小矩阵运算触发 Triton 的 C 扩展编译，即使模型已加载也会导致首次生成失败。只禁 TorchDynamo 没有解决此问题；我们使用官方 Ubuntu 签名包的头文件，在项目目录解压，专门给视觉进程设置 include 路径，保留原解释器及系统环境。

如果同类节点也缺少 Python 3.12 头文件，可使用本次实测版本的固定配方：

```sh
.spark-model-venv/bin/python -m integrations.spark_transformers.prepare_python_headers \
  --project "$HOME/cizheng-release"
export CIZHENG_SPARK_HEADERS_DIR="$HOME/cizheng-release/runtime-headers-ubuntu-3.12.3-1ubuntu0.17"
export CIZHENG_SPARK_CACHE_DIR="$HOME/cizheng-release/runtime-cache"
```

配方只支持 Ubuntu ARM64 / Python3.12，固定 `libpython3.12-dev=3.12.3-1ubuntu0.17`、SHA256 `945ad3f651f683c11e72d19d804b1cff097308dcffa01057635cba038f875164`。软件索引、缓存、下载和解压全部留在指定项目内；没有 sudo、系统 apt 更新、软件安装或解释器升级。签名索引与下载字节必须一致，固定包不再可用就失败退出；应根据实际节点重新核实包版本。头文件检查通过仍不能代替实际生成验收。

```sh
. .spark-model-venv/bin/activate
export CIZHENG_SPARK_MODEL_NAME=Qwen/Qwen3-VL-8B-Instruct
export CIZHENG_SPARK_PORT=8001
export CIZHENG_SPARK_MODEL_DIR="$HOME/cizheng-release/models/Qwen3-VL-8B-Instruct"
export CIZHENG_SPARK_LOG_DIR="$HOME/cizheng-release/logs/native-vision"
bash integrations/spark_transformers/start.sh
```

按本页配置启动只绑定127.0.0.1:8001；脚本未配置端口时默认8000，单进程、单并发。`/health`只有在权重身份核对、真实CUDA float32/bfloat16矩阵乘法、GPU模型加载及一张合成白图的实际生成预热都通过后才返回HTTP200；缺GPU、缺依赖、权重变化、加载或生成失败返回HTTP503。`/v1/models`和生成接口同样拒绝未就绪状态。合成图预热只检验部署，不是陶瓷样本或专业效果验证。

可用`CIZHENG_SPARK_MODEL_MANIFEST`指定已有外部清单，例如本次下载的`integration-evidence/qwen-model-manifest.json`。默认读取模型目录下的`_file_manifest.json`。`/health`提供实际torch/CUDA、GPU及模型文件身份，不返回账户、环境内容或图片。`generation_in_progress`反映真实工作线程锁是否仍被持有，可用于受控部署前确认生成退出；它不改变就绪判定，HTTP 请求取消也不会提前释放该锁。

支持`/v1/chat/completions`：最多4张PNG/JPEG/WebP本地data URL；拒绝远程图片URL。初始32K总上下文、输出最多2500 tokens、温度0.1，禁止streaming/thinking附加选项。数据URL转成PIL图像后由固定版本的本地Qwen处理器预处理；模型加载及推理始终在Spark。仅可选记录token数量、图像字节哈希、耗时与响应哈希，不记录原始图片、完整提示或密钥。

后台环境使用 `CIZHENG_MODEL_URL=http://127.0.0.1:8001/v1`、`CIZHENG_MODEL=Qwen/Qwen3-VL-8B-Instruct`、`CIZHENG_DISABLE_THINKING=0`；将清单组合身份写成`CIZHENG_MODEL_REVISION=files-sha256:<files_manifest_sha256>`。后台与模型均留在指定Spark项目内，笔记本通过私人SSH转发访问，不开放未经认证的互联网端口。

模型健康后依次执行`python -m cizheng.model_probe --output <新结果文件>`及公开教学双图完整工具流程。真实运行失败必须保留，不能用模拟测试替代专业验收；复杂工具合同若超出2B能力，应升级并重新验证。当前没有独立专家器物盲测结果。

## 可选结构约束解码

固定使用 [LM Format Enforcer 0.11.3](https://pypi.org/project/lm-format-enforcer/0.11.3/) 和 [interegular 0.3.3](https://pypi.org/project/interegular/0.3.3/)。实现依据是该项目的 [官方 Transformers 集成](https://github.com/noamgat/lm-format-enforcer)：真实 `JsonSchemaParser` 与 `build_transformers_prefix_allowed_tokens_fn` 生成允许的 token 集合，并直接传给 `model.generate(prefix_allowed_tokens_fn=...)`。这项开源格式技术不是 NVIDIA 专有技术，也不评价内容真假。

原生接口接受以下标准形状。schema 必须是请求体内的 JSON 对象：

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "cizheng_actions",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
        "required": ["color"]
      }
    }
  }
}
```

请求 schema 的规范化 UTF-8 大小最多 100000 字节、嵌套深度最多24、节点最多4096；消息最多64条，模型名最多128字符。只接受声明的类型、必填字段、枚举、常量、长度、受控联合及本地定义引用。`$ref`只能是已有的 `#/$defs/<名称>`，禁止外部地址、文件路径、子路径和循环引用；不读取任何 schema 文件或符号链接。正则仅允许固定 SHA256 形式 `^[a-f0-9]{64}$` 和短动作单行解释 `^[A-Za-z0-9一-鿿][^\r\n]{0,39}$`。后者要求英数字或基本汉字开头，总长1–40字符。未知关键字、重叠 `oneOf`、数值上下界和其他不支持的约束明确返回 HTTP422，不退回自由生成。

应用的 `CIZHENG_STRUCTURED_OUTPUTS=1` 只给可信动作请求附加 typed tool plan；视觉与探针请求保留原行为。实际解码 schema 递归移除了数值范围关键字，原工具参数 schema、数值范围、跨字段关系、技能权限与证据语义继续由后台原校验器执行。解码器限定字段、类型、枚举和长度，不能保证论据成立、选对工具或研究完成。

适配器对该固定发行版做显式兼容：互斥且必填的工具标签使 `oneOf`等价转换为 `anyOf`；固定哈希及单行解释正则仅在解析副本中去掉规则已经覆盖的冗余长度限制；非字符串常量使用内部 JSON 字面量适配以正确生成 `false`、`null`和数值。请求原 schema、原哈希及最终长度校验保留，白名单正则用 `re.fullmatch` 再检。Transformers5 的已安装 `PreTrainedTokenizerBase` 类仅补到 LMFE 使用的旧导入位置，保持模型运行库版本。官方 tokenizer 预处理按当前 tokenizer 缓存；每次请求使用独立解析器。不会修改模型生成的响应正文。

实际 LMFE 0.11.3 / interegular 0.3.3 的字符及 token 前缀检查通过单行中文、英文与40／41字符边界；Python JSON schema 的 `$` 可接受末尾换行，而最终 `fullmatch` 会拒绝。合法引号或反斜杠转义还存在前缀库拒绝的限制：这是可生成文字的子集，不能声称所有合法 JSON 都等价支持。该规则只约束表达格式，不判断解释是否专业正确。CPU原始与公开检查见 [固定解释协议记录](../../verification/nvidia/observed-method-cpu-01/README.md)。

缺少指定解码器返回 HTTP503。生成文本若仍未通过输入结构 schema 的最终核查，返回 HTTP500，并保留这次真实生成的 CUDA 指标、token 数量与响应 SHA256；不修补内容。成功响应的 `cizheng_runtime.structured` 及生成日志记录 `enabled/enforced/library/version/mode/schema_sha256/output_valid`，不保存 schema 正文。`schema_sha256`对应实际请求 schema，身份公式是：

```python
hashlib.sha256(json.dumps(schema, ensure_ascii=False, sort_keys=True,
    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
```

默认 skills/visual_research 动作 schema 的当前规范身份为 `a5372b8ae7081a2619bdf37da983f8ed1e9aae984564d41eb6ba777657437fe3`；旧 `tool_schema_hash`身份和后台原合同不变。未附加 `response_format`时不加载解码集成，生成选项与返回格式保留原行为。

部署已有模型环境时仅新增两个小包，不升级 CUDA、Torch、Transformers、Pydantic、tokenizers、NumPy 等已有依赖。官方 PyPI 发行文件身份：[LMFE 0.11.3 元数据](https://pypi.org/pypi/lm-format-enforcer/0.11.3/json) 中 `lm_format_enforcer-0.11.3-py3-none-any.whl` 是45418字节，SHA256 `cf586350875def1ae7a8fba84fcbbfc8371424b6c9d05c1fcba70aa233fbf06f`；[interegular 0.3.3 元数据](https://pypi.org/pypi/interegular/0.3.3/json) 中 `interegular-0.3.3-py37-none-any.whl` 是23635字节，SHA256 `b0c07007d48c89d6d19f7204972d369b2a77222722e126b6aa63aa721dc3b19c`。应先检查已有 Pydantic、packaging、PyYAML 和 NumPy 可导入，再核验下载字节，离线 `--no-deps`安装新增包。

## CPU 合同测试与 GPU 验收边界

项目根目录提供固定的独立测试依赖，不安装 Torch、Transformers 或模型权重：

```sh
python3.12 -m venv .structured-tests
.structured-tests/bin/python -m pip install -r requirements-tested.txt -r requirements-structured-tested.txt
PYTHONDONTWRITEBYTECODE=1 .structured-tests/bin/python -m pytest -p no:cacheprovider \
  integrations/spark_transformers/tests/test_structured_generation.py \
  integrations/spark_transformers/tests/test_readiness.py \
  integrations/spark_transformers/tests/test_cuda_metrics.py \
  tests/test_action_output_contract.py
```

实际解析器合同覆盖四种应用 schema、必填字段、枚举、长度、哈希与 `false`常量，并拒绝 run03 发现的结构错误。prefix 合同使用真实发布包的 tokenizer 预处理与 token 过滤，只以微型 CPU tokenizer 和类型桥替代缺失的大型 Torch/Transformers 库；原生生成入口的测试使用生成与 CUDA 测量替身。因此这些测试证明软件合同，不构成模型或 GPU 生成证据。未安装可选测试依赖时，测试明确标记解析器项跳过；不能将跳过计为实际通过。节点需另行执行真实 GPU 合成 schema 请求并核对 `enforced=true`、schema 身份、CUDA 指标和输出结构，再验收公开双图完整 Agent。
