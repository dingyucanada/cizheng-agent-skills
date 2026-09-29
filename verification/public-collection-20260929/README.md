# 基于公开馆藏资料的个案核查

本运行包对应三件新纳入核查的Met馆藏、六张CC0原始照片，和九次实际Spark工作流。它是公开资料个案核查，不是真人专家验证或真伪概率评测。未提供来源的首轮与给定馆藏来源的后续轮分开，所有停止和欠证记录保留。保留52次主模型消息记录；另有1次StepFun公开文字审查，不接收图像。

- `preregistration.md`：运行前固定条件。新增范围不重置此前质量迭代预算。
- `frozen-source-and-inputs.tar`、`source-stage-manifest.json`：上传Spark的完整源码、方法包和中性图片输入；固定驱动原字节另列。模型预训练曝光无法由本次输入控制排除。
- `phase-a/`：三件×普通提示/Skills，共六次。首轮知识与参照为空。
- `phase-b-pc01/02/03/`：原六次结束后，三件各一轮非盲来源上下文核查。照片字节不变。
- `source-context-b/`：本轮实际加入的官方基础字段转录，许可与适用范围明确。
- `model-input-images/`（各phase目录内）：实际送模型的JPEG字节。消息文件记录精确文字与图片哈希投影，Base64可由该JPEG恢复；不是完整HTTP信封存档。
- `requests/request-NN.json`：消息哈希、模型返回正文、usage及耗时。`final-run.json`为本轮实际保存意见；rejected提交不替代正式意见。
- `record-integrity-audit.json`：本机独立重建所有消息，对照实际run事件输入/输出哈希，核验图片、A/B同件绑定及各B来源正文。
- `image-review-pre-model/`：未接收馆藏标签或目标输出的先行AI看图记录。
- `semantic-review-a/`：随机包名的AI语义核查；已给馆藏参考，未给普通/Skills标签。不是专业真值或真人盲评。
- `semantic-review-b/`：明确给定来源的AI核查，保留判断理由的欠证和不一致。
- `public-text-critic/`：StepFun真实文字审查和项目AI逐项处理。外部审查建议本身也受输入范围核对，不自动改写主模型意见。

读取来源、通过数据合同和专业判断正确是不同检查。三件均无经核实的现代赝品，未计算行业准确率或真品率。可复现脚本依赖项目requirements，模型服务与模型文件须单独准备；tar内驱动默认只检查清单（零模型调用），使用`--run`才执行。为防污染，A使用全新空案卷，完成六轮后才允许B。详细中文方案见仓库docs/public-collection-case-check-20260929.md。
