# 单次 27B 原请求 CUDA / 图像结构化探针

这是 v14 容器已 ready、协调器已完成基线并明确授权后才可执行的一次实验。准备源码和运行离线合同不会调用节点。当前源码固定的实验身份为：

- 容器 `cizheng-nim-qwen38-v14-attempt-04`，完整 ID `dccb16dfc75032a1742220a72a0eceef23c01a25e72ea4f64f7b8dcd0581556d`。
- `StartedAt=2026-09-29T10:01:38.393207957Z`；原 NVIDIA NIM 入口 `/opt/nim/start_server.sh`；镜像 digest `7d4aa1ac40b20583068c4ece1d274042c0a99e863fb25bd0450c2be1951841b9`，镜像 config ID `7031f03d016a125ab739d569e206eae638ed76f6612d7a60d66ad619015508ef`。
- 外部接口只使用 `127.0.0.1:8009`；模型 `Qwen3.8-27B-NVFP4`，固定权重 revision `482ca0f3832238542f8f5295dde86b5f22711d80`；原 43 参数 profile SHA256 `70877257acccf1a287b21b80f170404460d760a1f52009a9c08c8fa189b58e04`。

协调器在节点运行以下命令。输入目录必须含现有两张固定的公开 Met JPEG 原件；无论传入什么目录，字节数和 SHA256 都要与源码中的固定值一致。授权旗标缺失时，在任何 Docker、HTTP、profiler 或目录创建前拒绝。输出或 profiler 目录已存在时也拒绝，禁止覆盖和自动重试。

```sh
python3 -B -S /path/to/frozen-probe/probe_once.py \
  --operator-authorized \
  --input-directory "$HOME/cizheng-next-workflows-20260929/source-r5/inputs"
```

执行前和执行后均核对同容器、同开始时间、原入口、只读模型 view、40 GiB 无额外 swap、loopback 端口和稳定的进程 PID / start ticks / namespace PID。主 8B 8005、后端 8780、Retriever 8003 必须健康；Retriever 的原 32 GiB、2 秒守护必须保留；系统可用内存必须至少 34 GiB。它沿用当前 v14 候选守护，不启动、停止或恢复任何业务容器。源码不修改 NIM 入口或 SDK，不读取或导出安装源码。

通过原 NIM 容器内的 SGLang HTTP API `127.0.0.1:8001/start_profile`，传入 `CPU/GPU`、`start_step=0`、`num_steps=8` 和独立 `/evidence/probe-qwen38-image-01`。这个官方八步窗口只覆盖部分生成；必须实际得到一个新 trace 才能验收。失败时仅在 full ID、开始时间和进程身份仍一致的条件下通过官方 `stop_profile` 清理，禁止额外推理请求或重试。官方 API 可查阅 [固定 SGLang 原文件](https://github.com/sgl-project/sglang/blob/fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1/python/sglang/srt/entrypoints/http_server.py)。

仅发送一次双图请求，提示只描述可见轮廓、色彩、装饰分区，`enable_thinking=false`、`max_tokens=384`、温度 0.1。原响应必须是 `finish_reason=stop`、两字段无额外属性的 JSON，每字段 1–80 字符；completion 不得超过 384，真实 image tokens 必须为 1–512。截断或格式不符会保留失败和未经修补的响应。公开图像来源：[Met 馆藏页面](https://www.metmuseum.org/art/collection/search/48607)。

私有证据保存到 `$HOME/cizheng-next-model27-20260929/gpu-profile-image-01`；原 trace 留在原候选的 `/evidence` 对应私有目录。验收把同一个原请求和响应 SHA256、请求时间窗口内 trace 的 SHA256 / mtime、稳定候选进程与 CUDA runtime PID、kernel ↔ runtime correlation ID 绑定在一起。`gpu-proof.json` 只包含受控身份、字节数、哈希、token 用量和事件计数，不复制 raw trace 或原图片 / 提示 / 文本内容。

这个结果最多证明指定公开双图请求的结构化输出完成，且对应候选进程确实执行 CUDA kernel。它不证明瓷器判断正确、不证明整案加速，也不测 GPU 利用率；八步 profiler 本身有额外开销。27B 已有完整流程中的视觉误判，主 8B 不因此替换。

离线合同使用合成图片、进程和 trace，禁止网络与真实子进程。覆盖授权、健康/内存和原检索守护拒绝、固定容器/镜像/开始身份、图片损坏、截断/非法 JSON、请求与响应哈希、旧 trace、进程重启/PID 复用、CUDA correlation、一次请求、失败清理和原件不可覆盖。

```sh
python3 -B -S deploy/qwen38-gpu-probe/tests/test_probe_contract.py
```

本目录与已执行的 v14 源码、CPU 收据和此前失败证据相互独立。
