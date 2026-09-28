---
name: ceramic-route
description: >-
  Identify the visible ceramic category for a new object study and route museum, collection, or auction research and determine whether
  blue-and-white gu attribution is in the specialty scope. Not for downloading reports or querying run status.
compatibility: Requires the Cizheng v0.4 tool host and a working multimodal endpoint.
metadata:
  version: 0.4.0
  required-tools: "read_case,inspect_images,load_skill"
  expert-review: "pending"
---

# 器类与专科路由

通过 read_case 读取问题与媒体登记，调用 inspect_images 观察轮廓、口部、颈腹足的关系、装饰区域。器物名称不能从目录编号或用户猜测获得。

青花花觚使用专科归属核验；一般陶瓷可做档案与有限研究，加载 ceramic-research-record，scope使用 ceramic_research。把“器类判断”和“制作年代判断”分开。看不到足够形制或装饰时保留观察限制；非花觚不继续套用康熙器的规则；明显非陶瓷才使用 out_of_scope。

照片只覆盖某局部、来源或尺度不足时，按需 read_skill_resource 读取 [范围与采集条件](references/scope-and-capture.md)，决定缺失是否影响任务。不得因为存在范围内词语而跳过器类观察。

输出到最终 basic_info 的内容包括可见形制、装饰、当前缺失的尺度和来源。只描述照片支持的信息。胎土配方、真实釉色、重量、工艺年代不能由普通照片直接测得。

青花花觚加载 bluewhite-attribution-test，其他陶瓷加载 ceramic-research-record。来源经历核查按描述加载 provenance-evidence-audit。仅在观察到需解释的状况现象时加载 condition-hypothesis-test。有上一版意见时使用 evidence-revise。工具失败停止推断，不能用用户目标填补视觉结果。
