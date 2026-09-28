---
name: bluewhite-attribution-test
description: >-
  Compare manufacturing-period, kiln and style hypotheses for visibly in-scope
  blue-and-white gu vases using real reference images and competing explanations.
  Not for other ceramic types, price estimates, or authenticity certification.
compatibility: Requires Cizheng v0.3 image, reference and skill-resource tools; no dating model is bundled.
metadata:
  version: 0.3.0
  required-tools: "inspect_images,inspect_region,retrieve_references,read_reference,read_skill_resource,record_assessment"
  expert-review: "pending"
---

# 青花花觚归属核验

适用条件：器类观察支持青花花觚。本技能是研究程序，不携带已经专家验证的断代规则；没有可靠标本时主动保留不足。

1. 将目标转换为可证伪主张：某时期实际制作，与仿该时期风格不同。保持 period、kiln、style 三种维度各自的候选与判断。
2. 用 inspect_images 查看器形比例、分区纹饰、口沿、接胎与底足等当前可见部位；记录可见现象与解释，不以单一铁锈斑、裂纹、釉面黄旧或青色决定年代。
3. retrieve_references 检索器类与候选；read_reference 查馆藏编号／图版、归属依据与许可；inspect_images 实看参照图，优先将器物及参照同批对比。需要决定资料是否可比或引用支持程度时，read_skill_resource 读取 [参照与竞争解释](references/comparison-method.md)。没有同类可比部位就明确不可比。
4. 比较至少一个最强竞争解释，例如历史时期近似作品、后世仿古、现代仿古或图像处理差异。不要把“找不到反证”当作目标成立。
5. 对每个维度写出支持、冲突和缺失。support/conflict 填本轮 observation_id；在 reasoning_summary 说明证据与结论之间的有限联系，不输出隐藏思维过程。reference_comparison 指明哪项相似、哪项不同及参照ID。
6. request_evidence 只请求当前信息价值最高的一项，说明它如何区分竞争解释。普通照片无法解决的材料／烧成／年代问题应转为上手或专业检测需求，不反复索取同类照片。
7. record_assessment 后 build_opinion。照片不足或空参照库使用 insufficient；不发明百分比。所谓 supported 只表示当前资料支持某归属，不能变成实物真品证书。

失败处理：参照不匹配或来源仅为卖家自述时降低其证明力；模型无法识别时保留欠证，不编造款识与图案文字。

细节看不清时用 inspect_region 查看原图局部，并引用返回的观察ID；放大或生成增强不能创造事实。制作时期、窑口和风格分别核验，某一维度有支持不自动放行另外两维度。
