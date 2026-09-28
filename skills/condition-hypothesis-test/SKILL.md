---
name: condition-hypothesis-test
description: >-
  Compare explanations for actually observed ceramic lines, deposits, patches or possible repairs.
  Not for unrelated attribution questions or deciding age from a worn appearance.
compatibility: Requires Cizheng v0.3 inspect_images, inspect_region and evidence-request tools.
metadata:
  version: 0.3.0
  required-tools: "inspect_images,inspect_region,request_evidence,read_skill_resource"
  expert-review: "pending"
---

# 状况假说比较

在 inspect_images 中实际观察到线条、色块、附着物或拼接疑点后使用。不要根据其他AI的旧结论认定修复或仿造。

把“细黑线”“亮白区域”“局部边缘不连续”等可见现象与“裂纹／开片／绘线／反光／抠图残留／修复”解释分开。列至少两种适用解释，描述哪种新增观察可将它们区分。

同一区域不同照片出现差异时，先核对视角、光源和后期处理状态；跨图不一致不是修复证据。明确图像定位，避免把背景边缘伪影写成器物缺陷。

需要设计能区分现象的补证时，按需读取 [观察条件与补证](references/condition-evidence.md)。

补证优先请求含同一区域的原始近照、漫射光和侧光对照，或由上手专家核查连续性；不能通过生成式“高清修复”获得新的鉴定事实。

输出 condition_hypotheses 与一项优先补证；如果修复没有被证实，保留“待核实”而非断言。裂缝和残留即使存在，也不能单独证明制作年代或真伪。
