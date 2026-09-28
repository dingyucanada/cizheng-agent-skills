---
name: provenance-evidence-audit
description: >-
  Audit the documentary provenance of a ceramic research case, distinguishing holder statements, dated records, gaps, and object-identity links. Use when a museum accession, collection purchase, or auction consignment asks about source history. Not for proving title, legality, price, or authenticity from a story.
compatibility: Requires Cizheng v0.4 image and fixed-source knowledge tools; no expert model is bundled.
metadata:
  version: 0.4.0
  required-tools: "read_case,inspect_images,inspect_region,search_knowledge,read_knowledge,read_skill_resource,record_assessment"
  expert-review: "pending"
---

# 来源材料与主张核查

适用：用户询问收藏经历、旧藏线索、征集资料或来源证明是否足以支持当前研究主张。此程序整理证据，不判产权或交易合法性。

1. read_case 读取 catalogue.provenance 与 source_declaration。将人物、机构、日期区间和转移行为当待核信息，不补造空缺时间段。
2. search_knowledge、read_knowledge 查来源记录方法与拍卖术语。引用明确到段落和版本；来源网页可访问不等于持有人经历属实。
3. 对每条来源主张，列明所需支持材料及其与本器物的对应方式：编号、尺寸、旧照片、标签或文书是否指向同一件。无法建立对应时注明“材料身份关系未核”，不能只凭相似文字确认。
4. 按需 read_skill_resource 读[来源事件与缺口](references/provenance-contract.md)。将资料缺失与反证分开，某阶段没有文献不能自动推出经历虚假，也不能算已验证。
5. 对需要的款识/标签实际 inspect_region；模糊不可辨则保留未知。故事不代替时期、窑口和风格的图像参照，不输出真假概率或市场估值。
6. 在最终 limitations 与一项优先 evidence_request 中说明最关键待核线索与验证方法。所有知识引用只接受实际读取版本；没有根据不使用“传承有序”“来源可靠”等肯定用语。
