---
name: evidence-revise
description: >-
  Revise a prior ceramic assessment after new photos, corrections, refreshed references
  or an approved text-critic result. Not for rereading an unchanged report.
compatibility: Requires Cizheng v0.3 versioned cases, image tools and dependency-review tools.
metadata:
  version: 0.3.0
  required-tools: "review_dependencies,inspect_images,read_skill_resource,respond_critic,record_assessment"
  expert-review: "pending"
---

# 补证后修订

激活条件：案件存在 parent_run_id，且新增照片、人工订正或用户显式确认的参照库刷新进入案件版本。

1. review_dependencies 读取前版意见、新媒体ID、订正以及 reference_changes 中新增／移除／更改的参照ID；区分新原始证据、用户描述与专家意见。身份未认证的本地记录不可称为已完成独立专家鉴定。
2. 对新照片执行 inspect_images。当前P0采用全案图像重新观察，旧视觉观察不复用，所有下游归属重新比较；不得声称实现了局部DAG缓存。
3. 明确新证据解决了哪项歧义、仍不能解决什么。订正也可能与当前图像冲突，应保留冲突而不是无条件接受。
4. 参照库刷新也是资料补证，即使器物照片未增加也需重新检索、读取和查看需要引用的参照。仅登记或看见新参照ID不等于已核验；无授权或已移除的参照不得沿用。不能直接沿用旧 observation_id；每一项新判断引用本轮观察。
5. revision_explanation 写明前版与本版的差异及实际证据原因。无变化也说明原因；“版本更新”不是结论改变的理由。
6. 初判加最多两轮成功补证。仍不足时列上手／检测建议，不无限追问。保存新意见，历史原意见不覆写。

有文字审查时，按需读取 [修订与审查回应](references/revision-contract.md)。审查未看到原图，必须重看并respond_critic逐项采纳、驳回或保留待核实，不能无条件接收。

证据读取失败则停止本轮；输出失败状态，不将旧意见包装为已根据新图核验。
