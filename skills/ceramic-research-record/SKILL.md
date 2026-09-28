---
name: ceramic-research-record
description: >-
  Organize a general ceramic object study for museum cataloguing, collection research, or auction catalogue preparation. Separate operator declarations, visible observations, source records, and attribution. Use for ceramics outside the blue-and-white gu specialty; not for app status or authenticity certification.
compatibility: Requires Cizheng v0.4 image and fixed-source knowledge tools; no expert model is bundled.
metadata:
  version: "0.4.0"
  required-tools: "read_case,inspect_images,inspect_region,search_knowledge,read_knowledge,read_skill_resource,record_assessment,build_opinion"
  expert-review: "pending"
---

# 陶瓷档案与有限研究

先 read_case 查看任务场景、器物登记、来源声明、人工观察和本轮明确选用照片。登记内容不能当作真值，workflow不是使用者身份认证。

1. 实际 inspect_images 看本轮图像，先描述器形、装饰布局与可见部位。用 inspect_region 查看决定比较的细节，记录坐标、限制；不把放大产生的视觉感受当新事实。
2. 普通陶瓷使用 ceramic_research；明显非陶瓷才用 out_of_scope。青花花觚进入 bluewhite-attribution-test，其他器类不套用花觚经验。制作时期、窑口、装饰风格分别保留支持、冲突和不足。
3. search_knowledge 查询术语、状况记录或来源核查方法，read_knowledge 读取来源段落及版本。参照器物则 retrieve_references、read_reference，再实际看参照图。没有可靠、可比参照时，归属保持 insufficient；知识摘要不能替代图像参照或实物检查。
4. 按需 read_skill_resource 阅读[记录与证据层次](references/record-contract.md)。人工区域观察只是操作人记录；模型必须重新观察，不能把人工注释ID填入support/conflict。
5. 博物馆任务重点是登记来源、尺寸及状况和馆内复核；收藏任务重点是持有人主张与支持材料的区别；拍卖任务重点是图录用语与状况分开。三类均不提供未经实测的价格、真伪概率或专家身份背书。
6. 若有来源链问题，按描述加载 provenance-evidence-audit；若有可见状况疑点加载 condition-hypothesis-test。有旧意见加载 evidence-revise。
7. record_assessment 引用本轮模型观察和实际读到的知识段落。优先请求一项能区分解释的补证；在限制中明确未选图、缺少实物与未核来源。build_opinion结束，不输出证书。
