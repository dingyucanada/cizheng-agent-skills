# 逐项观察、引用与理由审核

`cizheng.claim_support_audit` 是离线的报告后处理工具。它把已保存视觉意见拆成可阅评的主张、原图区域、观察支持／冲突关系和知识引用，保留模型原文，并生成绑定本轮输入与审核包哈希的独立标签模板。它不看图、不调用模型、不改报告、不提供专家身份认证，也不自动判定陶瓷归属。

第12轮真实材料显示了需要这项审核的原因：来源身份和读取合同已通过，修订理由仍有“装饰布局对称，符合清代风格”这样的推断。保存了观察编号只能证明引用关系存在；该特征是否可见、是否足以支持清代风格，仍需分别阅评。本工具不会用词语重合、来源年代或来源身份代替这种阅评。

## 使用

需要项目支持的 Python 3.11 或更高版本，使用已有项目依赖即可。以下路径可替换为任何真实保存的视觉研究 `run`；输出文件须为新文件，既有日志和意见保持原样。

```sh
python -m cizheng.claim_support_audit \
  --run verification/nvidia/qwen36-v10/workflows/main8b-r2/final-run.json \
  --output /tmp/saved-run-claim-audit.json \
  --review-template /tmp/saved-run-review-labels.json
```

没有标签时，输出 `semantic_status=awaiting_review`。全部语义条件分母为0，分数为`null`；一条有资格的引用也不会自动得到支持分。空模板是待填写资料，不是已完成的人工审核。

阅评者取得同一原图和审核包后另填模板，再运行：

```sh
python -m cizheng.claim_support_audit \
  --run verification/nvidia/qwen36-v10/workflows/main8b-r2/final-run.json \
  --labels /tmp/saved-run-review-labels.json \
  --output /tmp/saved-run-reviewed-audit.json
```

API为 `build_audit_packet(run)`、`review_template(packet)` 和 `audit_claim_support(run, labels=None)`。完整标签结构可从 `ReviewLabels.model_json_schema()` 取得。命令成功只表示生成了审核材料或核算了标签，不表示通过了专业验证。

本地工作台的视觉报告页提供“逐条理由核查 / 下载核查包”。只读接口 `GET /api/runs/{id}/claim-support` 返回固定保存轮次的未评结果与空白 `review_template`；加 `?download=true` 下载同一结构。接口不接受打分标签，不调用模型、读取原图、添加图像Base64或修改历史。不存在的轮次返回404，文字任务返回422，无法核查的保存结构返回409。

正文输出先校验冻结快照整体承诺、所属 run 的同版承诺、来源及段落唯一性和所属文档版本，再要求本案固定版本绑定、冻结快照中的 `authorized_text` 许可、段落文本与哈希、已读片段的准确切片和本轮精确送达记录全部一致。未绑定、许可不明、伪造读回执或缺少冻结快照时，不输出该来源正文；全库快照及其它案卷不进入核查包。报告页的本轮资料引用保持全局展示，不自动挂到每条主张。

## 图像观察区域与事实来源

审核包的 `images` 只复制原图ID、登记SHA、尺寸，以及明确命名为 `view_declaration` 和 `capture_role_declaration` 的上传者声明。工具未读图，因此 `image_bytes_verified_by_this_tool=false`。`snapshot.catalogue`、归属目标、专家答案和用户标注不会被提取成观察事实。

`observations` 分开保存 `model_visible_description`、`model_interpretation` 和 `model_limitation`；三个字段均为模型原文。`region`对应本轮保存的坐标，`coordinate_space=exif-corrected-original-normalized` 才能与阅评区域计算重叠度。坐标范围检查不能证明框中存在所述特征。

`ObservationJudgment`包含：

| 字段 | 含义 |
| --- | --- |
| `observation_id` | 审核包中对应的模型观察ID |
| `image_access` | 阅评者声明 `original_pixels` 或 `report_text_only` |
| `reviewed_media_sha256` | 取得的原图SHA声明；工具要求与本轮登记SHA相同，未自行核验图像字节或实际观看行为 |
| `visible_verdict` | `correct` / `partial` / `incorrect` / `not_assessable` |
| `region_verdict` | `appropriate` / `partial` / `incorrect` / `not_assessable` |
| `reviewer_region` | 人工参考区域，归一化 `[x0,y0,x1,y1]`；评定位时必填 |
| `basis` | 逐项说明可见、不可见或无法判断的原因 |

明确的图像正确性标签与人工区域必须声明取得原图并绑定SHA；只读报告不能获得图像正确性分数。自动文字阅评角色不能声明取得像素。区域IoU仅为模型框与所提交人工框的重叠描述，不设正确性阈值，不转换为专业能力或真品概率。

`reviewer_role`严格区分 `human_reviewer`、`declared_domain_expert`、`automated_text_reviewer`、`automated_multimodal_reviewer` 与 `synthetic_test`。多模态AI实际取得原图后可以使用 `automated_multimodal_reviewer`，原图SHA仍须精确绑定；这不是人工专家阅评。如模型评审与开发者共享当前上下文，须记录 `independent_of_model=false`，不称盲评或独立专家验证。原图是否实际读取仍由调用工作流保留图像调用日志，工具不认证该声明。

## 主张与证据关系

`claims`保存时期、窑口、风格候选、原状态、理由及观察编号。`observation_links`逐条列出模型实际声明的支持或冲突关系，重复的同一主张／观察／角色只计一次，同时报告重复诊断。未知、旧轮、无原图关联或未送达主动作的观察保留为不可用关系，不删除以提高覆盖率。

`ObservationLinkJudgment`引用 `link_id`，填写 `relation`、`claim_excerpt`、`visible_excerpt` 和 `basis`。关系取 `supports` / `partial` / `does_not_support` / `contradicts` / `not_assessable`。两个摘录须原样出现在该主张候选或理由，以及该观察的可见描述中；解释字段不能充当可见描述。这里评价的关系以保存的模型描述为条件。即使关系恰当，也不等于该模型描述已经通过原图验证。

引用审核包列出固定版本身份匹配、保存的正文送达凭据和本轮送达的精确片段。这些仍是提交记录中的软件事实，不能认证机构记载、本器物身份或归属。只读过全文所属段落，却未把某个片段送达主动作，不能引用那段未送达内容进行评分。

`CitationJudgment`包含 `citation_id`、`target_field`、`target_kind`、`relation`、`target_excerpt`、`receipt_body_sha256`、`source_excerpt` 和 `basis`。摘录必须原样对应审核包中的报告目标与实际送达正文；正文哈希也须对应同一片段。未送达、版本错配或旧轮引用只能登记 `not_assessable`，不能填已支持或已反驳。

`target_kind`必须由阅评者明确为 `source_statement`、`object_inference` 或 `method`。例如，正文可能支持“馆方记载某时期”这一来源陈述，而不足以支持从相似纹饰推断本器物的年代。两种目标分别核算，不能合并为一个“引用正确率”。同一引用在不同目标上可各有判断；未建立目标映射的引用单独报告覆盖数。目标选择及阅评本身需要审核，工具不自动决定引用在全文中支持了哪些推断。

## 理由量表与分母

`ReasoningJudgment`关联 `claim_id`，逐项填以下四个 `criterion`；`verdict`取 `adequate` / `partial` / `inadequate` / `not_assessable`，另填 `basis`。充分或部分充分的理由需要 `report_field` 和原样 `report_excerpt`；理由缺失可登记 `inadequate` 并说明缺少什么。不能拿另一条主张的理由当作本项依据。

| 维度 | 审核问题 |
| --- | --- |
| `observed_basis` | 说明了什么可见特征或哪些关键观察缺失？ |
| `inference_bridge` | 特征、来源或比较怎样支持候选？论证是否超出照片可核范围？ |
| `alternative_explanations` | 是否处理了相关替代解释，并说明区分依据？ |
| `missing_evidence` | 是否指出能改变判断的缺证和可执行补证？ |

欠证意见也可有充分理由；“未确定年代”不自动等于理由错误。四个维度各以本轮全部已保存主张为预定项目数，分别报告阅评覆盖与条件分数。没有意见的失败轮次保留 `run_state` 和 `no_saved_visual_assessment`，没有主张正确率分母，不能作零分或从流程统计中消失。

每个量表保留 `total_items`、`labels_received`、`pending_items`、`not_assessable`、`assessed_denominator`、`fully_positive_count` 和标签分布。条件分母仅为有明确非 `not_assessable` 标签的项目；`partial`计入分母、不计为完全充分。无人阅评时分数`null`，不填0或1。引用分母的单位是阅评者明确提交的“引用／报告目标”对，另保留全部声明引用数和未映射数，不能将所选关系分数称为全部引用的支持率。

所有分数都来自所提交的标签。`reviewer_role=declared_domain_expert`只是角色声明；`reviewer_identity_authenticated=false`、`expert_validation_established=false`和`ceramic_accuracy=not_measured`不会因此改变。真实专家盲评、独立器物样本和归属正确率须按[专家样本接入协议](../docs/expert-validation-intake.md)另行开展。

本工具的测试涵盖第12轮原始日志抽取、陈述与推断分轴、精确正文锚点、旧轮拒绝、图像访问边界、分母、重复标签及过期标签。合成阅评标签只是软件协议测试；第12轮测试也仅核查保存材料抽取，不证明其观察或理由正确。

## 本次真实保存材料

[公开双图工作流与分项AI阅评](../verification/nvidia/qwen36-v10/workflows/)保留一次协议失败和一次117.4秒完成记录。后者的馆方文字转述可核查，但具体年代、窑口和未看图的参照相似性仍缺支持。AI阅评实际查看原图，明确记录共享开发上下文，不作为独立专家验证。

旧公开round12回放包的知识快照整体承诺与当前公开正文重算不符。新工具保留 `knowledge_snapshot_invalid_commitment` 诊断并禁止该包正文导出；不重写历史承诺来消除失败。需要从原始私有归档核对脱敏／发布阶段的版本变化，不能拿该旧包当新的正文资格正例。
