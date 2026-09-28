# TensorRT-LLM · Spark 实际独立部署

核对日期：2026-09-29。官方 ARM64 `1.3.0rc13` 镜像、Qwen3-4B-Instruct-2507 BF16 与独立服务 8006 已真实运行。主视觉 8005 / 案卷 8780 仍保持原服务。本模块采用 TensorRT-LLM 的 PyTorch backend，没有生成序列化 TensorRT engine。

- [实际镜像](local-image-identity.json)、[14 文件模型下载校验](qwen4b-verified-model.json)、[服务实际身份](service-identity-final.json)。
- [公开陶瓷原请求](public-text-once/claimed.json)、[原始响应](public-text-once/response.raw.json)、[单次请求回执](public-text-once/receipt.json)：1 POST、0 自动重试、`stop`、257 输入 + 93 输出 tokens。记录耗时约 4.056 秒含首请求追踪，不是速度对照。
- [CUDA 现场核验统计](gpu-proof-summary-final.json)：3653 kernel / 1264 CUDA runtime 事件、42 个不同 kernel 名称；同固定容器、进程、原输入/输出 SHA 和请求时间窗。只采集前八迭代，未覆盖完整请求。
- [请求前身份](container-before-public.json)、[请求后身份](container-after-public.json)、[资源与原服务健康](memory-health-summary.json)：原服务健康保持。系统共享内存快照、cgroup 和 `/metrics` 不是候选独占显存峰值。
- [实际部署的 10 文件清单](runtime-files-final.json)与[全部公开凭证 SHA](evidence-index.json)；对应源码见 [部署与复现说明](../../../deploy/tensorrt-llm-spark/README.md)。26 项 stdlib 测试在本机和 Spark 实际通过；没有新增模型请求。

原 GPU trace 和原进程快照留在私有证据中，公开文件只保留身份与统计。本机独立复核公开原件 SHA 和绑定链；GPU 事件重计由固定校验代码在节点执行，不能称本机重新计算过未取回的原 trace。

原回答没有保留请求中的藏品号，也没有严格只列两项补证；这些缺口保留在原回执。接口及限定 CUDA 验收不等于陶瓷专业意见正确、完整主流程完成、NIM 已部署或端到端提速。首次模型启动的文件权限失败容器、日志和早期绕过镜像 entrypoint 的失败均保留；最终候选保持官方初始化，只对本候选加入 `DAC_OVERRIDE` 读取公开只读权重。
