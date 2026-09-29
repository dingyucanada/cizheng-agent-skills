# 可选 Laya 文字任务影子路由

当前 **disabled；没有在本工程安装、下载 checkpoint 或执行陶瓷领域模型推断**。工作台风险数字来自本地确定性公式，不依赖 Laya 输出。

2026-09-29 实际读取 [官方仓库](https://github.com/NandhaKishorM/laya)、[当前 pyproject](https://github.com/NandhaKishorM/laya/blob/main/pyproject.toml) 与 [Router 实现](https://github.com/NandhaKishorM/laya/blob/main/laya/router.py)：包版本0.3.21，中文文字应选择 multilingual（322M；默认1024 token）。Router 选择 checkpoint；它本身不是陶瓷专业任务分发规则。官方通用领域模型分布或 confidence 不能移植为真品率或陶瓷置信度。

`adapter.predict_local` 只接调用者已准备好的本地 checkpoint，明确 CPU、2线程、离线模式。复用已存在的 `cizheng.laya_shadow` 协议：建议继续研究、请求补证或超出范围；实际下一步与复核要求仍由原流程决定。模型权重文件SHA及文字/问题SHA进入影子记录，不接收像素，不改案卷、风险指数、工具预算或专家复核门禁。安装与 CPU实测须在独立环境完成；安装包、检查语言或合成协议测试不能算陶瓷模型验证。

本轮本机剩余磁盘约15GiB，现有小工程环境无Torch，不为演示下载全套模型依赖。未来可在专用CPU环境用固定版本、固定权重和公开文字先记录延时/峰值/失败，再由真实领域样本决定是否适合作文字分流。Jev 与 Laya 的 typed text decision 也不能代替像素观察或实物鉴定，因此本轮不强接浏览器抓图“鉴真”。
