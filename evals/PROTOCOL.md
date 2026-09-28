# 评测协议

本目录给出协议，不给出未经执行的专业成绩。工程测试中的纯色图、脚本模型不计入模型基准。

## 固定资料有无Skills对照

使用 `python -m cizheng.paired_eval --manifest manifest.json --output checks.json` 只检查输入；加 `--run` 才调用已配置的本地视觉模型。运行时 output 是新的实验目录。既有结果不覆盖。

案例和参照的清单结构见 `manifest-example.json`。示例路径是需自行准备的私有资料，并不包含图片或结果。允许 reference 列表为空，但这种测试不能证明有参照时的专业能力。清单不能含标准答案；正确归属、标注依据和盲评表由独立评阅者另外保存。

程序按每件独立器物运行 plain 和 skills 两臂：同一图片字节、问题、参照及模型，共同事实约束和工具预算；两臂使用独立数据库和Episode，并交替哪一臂先执行。plain不读取Skill目录或正文；skills按需读取。媒体上传名规范化，避免带答案的文件名入提示。问题和来源描述仍须人工审查，不能把答案藏在其中。

协议保存每次失败、耗时、调用数、版本和模型身份。protocol_completed是完成软件合同的次数，不是正确判断数。程序不自动给真假打分。blind目录提供去除mode的意见、可回查图片与参照，reviewer-hidden-mapping.json和summary.json只给组织者。盲评者可能从风格猜测模式，因此只称标签盲化，不声称彻底消除偏差。

## 盲评口径

- 先由专家独立看同一批材料，记录时期/窑口/风格、依据、未知和争议，后看模型输出。
- 按器物统计：明确判断数、正确数、现代误收、欠证与范围外；同时报告覆盖，不删除失败或弃答。
- 逐项判断观察是否可见、参照是否可比、支持/冲突是否恰当、下一项补证是否能区分候选。
- 报告各组样本数和误差区间；12件探索不能证明广泛泛化或误收率为零。
- 同件多图不跨开发和盲测。程序可防完全同图/同物ID冲突；近重复和错误ID还需人工或专用工具检查。

## 主动补证实验

当前paired_eval仅执行固定资料首轮，不伪装为72个Episode的完整历史评测计划。主动补证需另建预登记：可取得哪些证据、每项成本、什么结果支持或削弱哪个假说；两臂补证预算相同，专家按最终质量和补证成本评估。工作台已保留真实补证与修订接口，但尚无真实模型的补证成绩。

## 技能触发

trigger-cases.json 是待执行的正负测试清单。后续通过真实宿主记录discover/load与实际工具调用来评分；仅通过frontmatter格式检查不能声称触发正确率。图像任务必须配对应真实图，不能把文字中的器类当作模型已经看见。

## Laya影子实验

应用默认不依赖Laya。准备好本地checkpoint和其依赖后，运行 `python -m cizheng.laya_shadow --state facts.json --model-dir /local/checkpoint --device cpu --output shadow.json`。程序设置HuggingFace离线模式，不自动下载，保存checkpoint文件哈希。输入字段仅facts、incumbent_next_step、review_required；incumbent取continue_analysis/request_evidence/out_of_scope，须由调用方把应用状态明确映射成同义标签。

confidence（choice中为分布集中度）和answer_confidence分开保存，均未在本项目校准。影子结果无权变更真实next_step或复核要求；预测错误/异常也不改变业务。checkpoint加载失败会退出，不会产生假推理结果。

不要将外部README的T4/GB10延迟或通用数据集正确率写成本项目结果。可比的收益必须来自同输入、同硬件、包含加载/预处理/失败的完整流程。

清单准备阶段要求每案1–8张可解码的JPEG/PNG，拒绝同案重复原始字节（即使文件名或视角声明不同），也拒绝同图分给不同测试器物。先修订清单再启动批次，避免模型去重后与评阅材料不一致。
