# 新版筛查与采集接口验收

本目录公开实际软件验收的安全摘录；不包含私人案卷、凭证或模型权重。测试中的馆藏原照来自 Met Open Access，尺寸冲突使用明确的合成记录，不是对该器物的实测。

- `reviewed-backend-stage.json`：Spark 13 份候选源码逐 SHA、54 项定向测试、真实 HTTP 图片上传 / 下载字节相等及零模型调用。
- `backend-promotion.json`：只切换案卷服务源码目录；视觉与三个独立服务未重启。历史记录中 application_version 为 null 是旧字段名取值，当前实际 app_version 在下条核验中为 0.7.0。
- `current-node-readonly.json`：五项当前健康状态、两个标准模型接口、公开源码身份和真实已配置的 StepFun 文字模型。无新增模型请求。
- `regression-summary.json`：本机工程回归与独立合同反例范围。不同测试集合存在重叠，不能相加成领域样本数。

实际专业研究和文字审查仍见第12轮独立归档；新的接口/数字检查不替代专家器物审核。
