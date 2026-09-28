# Spark 原生模型生成的 Nsight 采集与核验

这些脚本只包装明确指定的新进程，以及读取已有报告。不发起模型请求、不下载模型、不停止已有服务。真实服务与业务请求由执行者另行管理。

## 已完成的现场核验

2026-09-28，Spark 上 Nsight Systems `2025.3.2.474-253236389321v0` 已在 v07-03 首次实际双图视觉调用中导出报告，随后业务服务继续运行并完成报告流程；不是纯色 warmup。私有报告 `v07-nsys-first-vision.nsys-rep` 为 29,060,529 bytes，SHA256 为 `f66fb4710713fc6cccc7ea14ae08eb66f07181b4a5ad9cfadabc8025d8845236`。

单次 `nsys stats` 的脱敏核验日志为 `work/spark-integration-evidence/v07-verify-nsys-01.log`：

| 检查 | 实际结果 |
|---|---|
| `:cizheng.model-generate` NVTX 范围 | `Instances=1`，`Total Time (ns)=19,920,507,616`，约 19.92 秒 |
| CUDA 内核摘要 | 144 个聚合行，合计 447,028 个内核实例 |
| 导出与服务 | 报告导出成功；`capture-range-end=stop` 后服务继续运行 |

这证明目标 NVTX 范围触发并记录了 CUDA 内核；不证明 GPU 利用率、端到端加速、模型专业质量、32B 或候选容器可运行。摘要中的 `Time (%)` 是所列范围或内核累计时长的比例，不能当作 GPU 利用率或应用总耗时比例。原始 `.nsys-rep`、SQLite 及原始输出可能包含环境、路径和启动参数，应留在私有证据区；公开材料只保留脱敏统计。

## 为何显式设置 NVTX 环境开关

现有模型适配器使用 PyTorch `torch.cuda.nvtx.range_push('cizheng.model-generate')`。PyTorch 实现调用 `rangePushA` / `nvtxRangePushA`，是普通字符串范围。Nsight 默认按注册字符串选择 capture 范围，因此包装器给目标进程显式传入 `NSYS_NVTX_PROFILER_REGISTER_ONLY=0`。未限定域的 `--nvtx-capture=cizheng.model-generate` 匹配默认域。

`--capture-range-end=stop` 停止采集并导出，应用继续运行，后续范围不再触发。无需为导出停止服务。包装器还显式使用 `--kill=none`。依据：[Nsight Systems 用户指南](https://docs.nvidia.com/nsight-systems/UserGuide/)、[PyTorch NVTX Python 实现](https://raw.githubusercontent.com/pytorch/pytorch/main/torch/cuda/nvtx.py)、[PyTorch CUDA NVTX 绑定](https://raw.githubusercontent.com/pytorch/pytorch/main/torch/csrc/cuda/shared/nvtx.cpp)、[Nsight NVTX 统计说明](https://docs.nvidia.com/nsight-systems/AnalysisGuide/#nvtx-sum-nvtx-range-summary)。

## 可复现的新采集

使用节点已有 Nsight，不安装软件。先准备私有输出目录与没有旧报告的新前缀，再对任务专属新进程执行；不要拿包装器重启正在工作的服务：

```bash
export CIZHENG_NSYS_OUTPUT=/absolute/private/evidence/new-profile
bash deploy/nvidia-profile-native.sh /absolute/existing/python /absolute/model-service.py --help
```

上面的 `--help` 仅展示包装入口，不会生成 GPU 采集。实际采集须将参数换成已经审查的服务启动参数，由执行者在已有授权的业务流程中触发首次真实视觉生成。包装器参数为 `--trace=cuda,nvtx --capture-range=nvtx --nvtx-capture=cizheng.model-generate --capture-range-end=stop --sample=none --cpuctxsw=none --kill=none --env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0`。报告不存在、NVTX 范围为零或没有内核时只记失败，不能自行反复请求模型补采样。

## 对已有报告只统计一次

```bash
/absolute/existing/python deploy/nvidia-verify-nsys.py \
  --report /absolute/private/evidence/new-profile.nsys-rep \
  --output-dir /absolute/private/evidence/new-profile-stats \
  --expected-count 1
```

核验器要求新的输出目录，保存版本、报告身份、一次 `nsys stats` 的命令与退出状态、CSV、SQLite 和摘要。该次 stats 同时导出 `nvtx_sum,cuda_api_sum,cuda_gpu_kern_sum`，只校验预期目标范围计数和正数内核计数，不碰服务。脚本实际参数可通过 `--help` 核对。包装器与核验器有 5 项 stdlib fake-CLI/CSV 离线测试；上述现场核验则是对真实已有报告的独立证据。

## 与 CPU 回归证据的区别

* 零模型字符解析微测：原策略 1.182 秒包含冷 Torch 导入，bounded 策略 0.00883 秒；不能据此计算公平性能倍率。
* 零模型、真实 tokenizer 的完整动作 Schema 前缀重放：同一个 25-token 合成序列，两次原策略在 15 秒截止时均只处理 14/25；bounded 两次完成 25/25，耗时 0.1022/0.0885 秒。原策略 profile 中集合交集自身约 12.49/12.81 秒，支持这个具体前缀的 CPU 状态枚举成本较高，不能证明 1393 秒业务异常的唯一原因或推导模型生成倍率。
* Spark 原生解码器 94 项全部通过、无 skip：真实模型环境中的 CPU parser/token-prefix/schema 合同回归，没有 GPU 模型请求。
* Spark 应用回归 567 passed、8 skipped，187.51 秒：应用软件合同，不代表视觉报告的专业质量。
* 上述 Nsight：一次真实双图视觉生成的范围与内核存在证据，不是基准对照。

CPU profile 日志分别为 `v07-decoder-cpu-profile.log`、`v07-full-schema-token-profile-remote.log`；回归日志为 `v07-native-cpu-tests-04.log`、`v07-app-tests-r3.log`，均位于 `work/spark-integration-evidence/`。原始输出后仍由完整 Schema 校验，不能把投影约束的通过当成原合同通过。
