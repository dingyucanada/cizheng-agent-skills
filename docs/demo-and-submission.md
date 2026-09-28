# 演示、材料与提交清单

瓷证的公开交付包括产品主页、三套可操作教学案、真实保存记录回放、教学视频、可编辑介绍 PPT、开发纪实和公开源码。教学功能、真实模型调用和专业研究质量分别标注，不能用预写教学例子代替 AI 运行结果。

| 入口或材料 | 当前交付 | 边界与待办 |
|---|---|---|
| [产品主页](https://dingyucanada.github.io/cizheng-agent-skills/) | 博物馆 / 收藏者 / 拍卖图录三类流程、Skills 案例、架构和资料入口 | 单人受控试用；首页不展示比赛评分表 |
| [免上传完整体验](https://dingyucanada.github.io/cizheng-agent-skills/demo.html) | 三个真实公开馆藏教学案，编辑、定位、补证、复核、导出可实际操作 | 项目编写研究示例，不调用模型，不是未知器物鉴定 |
| [2:43 教学视频](../site/assets/cizheng-demo-v07.mp4) | 已真实生成 163 秒 / 1920×1080 静音中文字幕界面讲解 | 预置教学 / 未调用模型；非连续真实推理录像 |
| [1:20 真实 AI 记录回放](../site/assets/cizheng-ai-replay-v07.mp4) | 根据第 12 轮真实保存记录生成 80 秒静音中文图文；附 [来源 JSON](../site/assets/cizheng-ai-replay-v07.json) 与 [字幕](../site/assets/cizheng-ai-replay-v07.srt) | 初稿、一次批准文字审查、本地修订、NAT 和两版导出技术完成，专业质量 false；非连续屏幕录制、非专家验收 |
| [第 11 轮历史失败回放](../site/assets/cizheng-ai-replay-round11-v07.mp4) | 原 80 秒回放与 [来源 JSON](../site/assets/cizheng-ai-replay-round11-v07.json) / [字幕](../site/assets/cizheng-ai-replay-round11-v07.srt)另存归档，未删除旧失败 | 展示第 11 轮初稿 / 审查成功、修订合同停止；不是最新第 12 轮终态 |
| [产品与架构 PPT](../site/assets/cizheng-pitch-v07.pptx) | 10 页可编辑 PowerPoint，产品、架构、Skills 与透明边界 | 用于介绍，不把工程测试或合成探针当专业效果 |
| [开发纪实](development-story.md) / [公开 story 页面](https://dingyucanada.github.io/cizheng-agent-skills/story.html) | 已有完整文章与公开页文件，记录实际制作、失败和证据 | 当前入口使用完整纪实；B站 / CSDN 正式发布尚未发生 |
| [源码与运行证据](../verification/nvidia/v07-workflows/README.md) | 软件、失败、脱敏回执、来源 / 公开 SHA 和逐调用绑定 | 本轮由根任务统一发布；不含用户私有材料、密钥或权重 |
| 专家验证 | 已有 [接入字段与盲评流程](expert-validation-intake.md) | 样本在另一台电脑，尚未接收验证 / 校准真品率 / 完成 Skills 对照 |

介绍幻灯片也可 [预览实际 PPT 渲染](../site/assets/cizheng-pitch-v07-preview.html)或 [下载 PDF](../site/assets/cizheng-pitch-v07.pdf)。[最终媒体清单](../site/assets/media-manifest-v07.json)记录实际文件 SHA 与演示边界；预览来自最终 PPT 的实际 Office 渲染，不能将它计为专家质量验证。

视频与 PPT 是已制作文件，不再写“尚未录制”。网站文件就绪不等于 B站视频 URL、CSDN正式文章 URL 或比赛提交已经完成；正式渠道发布时需另登记实际地址。GitHub Pages 的本轮版本由最终提交与发布记录确认，不能拿旧线上版本截图宣称新版本已经公开。

## 真实功能与质量口径

第 12 轮技术状态 completed：真实 Spark 初稿 6 model / 13 tool，133.966 秒；StepFun 一次成功，10.635108 秒，818 + 1,707 = 2,525 tokens，cached 256，3 个疑点，原图未外发；本地修订 8 model / 16 tool，142.183 秒、零 validation error。两版各 1 条正文送达 / 1 条来源上下文引用，NAT verified；两版各三格式共 6 份导出实际字节 / server / saved SHA 全部匹配。14 次原生调用按顺序绑定业务事件，最大 HTTP 47.780226 秒 < 90 秒，全部 EOS / 原 Schema 有效。[第 12 轮 audit](../verification/nvidia/v07-workflows/round-12/authenticity-audit.json)。约 299 秒是单个全流程两轮推理加审查 / 核查 / 导出耗时，不是统计性能基准。

技术完成与两版来源任务检查通过仍不等于专业质量通过。本轮初稿对身份已知的同件 Met 18.61.4 错写“不适用本件”；修订删除误句，但风格支持与三个 unresolved 疑点的理由薄弱、未专家核验，`quality_audit_passed=false`。第 09 轮最终引用为空、第 10 轮文字格式失败、第 11 轮修订失败均保留，不合并局部成功冒称质量通过。[质量局限](../verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json) 与 [全部逐轮记录](../verification/nvidia/v07-workflows/README.md)。

## 赛题要求与证据对应

评分对照只留在此提交文档，产品主页使用业务介绍与试用范围。

| 评估维度 | 已有可审查材料 | 仍需真实补齐 |
|---|---|---|
| 场景、价值与创新 | 三类可操作工作流、案卷交接、原图区域与固定资料、渐进 Skills | 机构实际委托或专业反馈，不捏造用户采用 |
| 智能体与技术深度 | 有预算工具流程、正文读取与版本引用、来源合同、真实审查、技术修订与 6 份导出；来源任务检查通过 | 专业有效性仍未通过；独立专家质量与同预算有 / 无 Skills 对照 |
| 方案与工程完整性 | FastAPI / SQLite / 文件保留、权限、幂等、导出；r15 ARM64 全应用 913 passed / 8 skipped / 1 warning，0 GPU 模型请求 | 工程回归不能代替研究意见质量，多用户授权未实现 |
| 平台适配 | Spark 实际 CUDA/BF16 视觉，NAT 实际引用审查，Nsight 实际限定区间采集；StepFun 实际批准文字请求 | 未部署 NIM / vLLM / TRT / Dynamo / Retriever；没有 NVIDIA Verified |
| 演示与发布 | 已生成两类明确标注视频、10 页 PPT、完整开发纪实与页面 | 登记正式视频 / 文章 URL；按比赛渠道完成提交 |

## 建议展示顺序

1. 打开免上传案卷，明确教学材料已知身份且未调用模型。
2. 实际编辑观察并定位原图，查看方法、资料和证据缺口。
3. 纳入预置补证，比较版本并下载带教学标记的报告 / 原件清单。
4. 切到独立真实记录回放与原始 audit：初稿、批准文字包、一次审查、本地修订、两版核查与导出；指出技术完成与专业质量 false 的区别。保留第 11 轮失败回放供回查，明确记录回放不是连续录屏。
5. 展示架构与原图 / 文字许可边界，回查失败、源码一致性和仍需专家验证的事项。

最后核对公开文件实际 SHA、站点构建与既有前端检查；正式比赛提交所需团队 / 身份 / 联系信息只使用获准材料，不虚构证明或已发布地址。
