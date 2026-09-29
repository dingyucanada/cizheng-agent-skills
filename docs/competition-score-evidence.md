# 瓷证 · 参赛要求与当前实现对照

更新于2026年9月29日。本页用于工程与提交核查；产品主页以业务场景、报告和体验为主，不展示比赛评分表。官方权重来自参赛者提供的本届培训截图：实用性与创新25%、智能体与模型技术25%、完整性20%、平台适配15%、演示10%、征文5%。这些是材料组织依据，不是获奖或得分预测。

## 当前成果与六项评分要求

| 官方维度 | 当前可定位成果 | 实际证据 | 后续专业验证 |
|---|---|---|---|
| 实用性、行业价值与创新25% | 博物馆编目、收藏来源、拍品研究三类流程；照片区域、来源、分项理由和版本交接；六维矛盾筛查决定下一项补证 | [完整报告](../site/report.html)、[三案免上传体验](../site/demo.html)、[风险筛查](risk-triage.md)、[设备采集](device-capture.md) | 专家样本评估与真实业务试用；不把教学案写成独立鉴定 |
| 智能体与模型技术25% | 七个领域Skills逐步发现、按需加载和固定包身份；本地视觉与工具预算；资料实际读取及引用身份约束；StepFun批准文字审查与本地修订 | [领域Skills](../skills/)、[第12轮保存记录](../verification/nvidia/v07-workflows/round-12/workflow-summary.json)、[NAT集成](nvidia-integration.md) | 对观察、引用支持和理由进行独立专家评审；同预算有/无Skills对照 |
| 项目完整性20% | FastAPI / SQLite专业工作台与完整公开体验；原件、幂等、阶段任务、修订、导出；材料更改后旧判断不能回流为新证据 | [当前软件核验](../verification/software/v09/README.md)：本机1120项Python、37项DOM；Spark54项专项及实际HTTP照片回取；[CI](../.github/workflows/ci.yml) | 机构多用户权限与可信签署属于后续生产化，当前为单人受控试用 |
| 平台适配15% | GB10真实CUDA/BF16视觉；NAT引用身份核查；Nsight限定视觉区间；原厂NIM、官方TensorRT-LLM文字及开放Embedding+cuVS GPU检索三个独立服务 | [当前五服务核对](../verification/software/v09/current-node-readonly.json)、[NIM实际部署](nim-v09-update.md)、[TRT-LLM](../verification/nvidia/tensorrt-llm-v08/README.md)、[Retriever核验](../verification/nvidia/retriever-v07/index.json) | 三项新增服务各有真实验收，尚未替换8B视觉/SQLite主流程；未声称完整Retriever SDK、整案提速或NVIDIA Verified |
| 演示效果10% | 193.12秒中文旁白、原创音乐与字幕的场景演示；真实保存记录另有回放；12页可编辑中文PPT、19页完整图文PDF | [固定Demo网址](https://dingyucanada.github.io/cizheng-agent-skills/assets/cizheng-demo-v07.mp4)、[PPT预览](../site/assets/cizheng-pitch-v07-preview.html)、[媒体清单](../site/assets/media-manifest-v07.json) | 场景演示由实际界面与保存记录制作，非连续模型录屏；B站等正式渠道以实际发布回执为准 |
| 征文5% | 十个主题章节记录真实开发、部署取舍、失败与修复；用户已手动发布固定知乎地址 | [当前文章](development-story.md)、[固定知乎征文](https://zhuanlan.zhihu.com/p/2088103686509744413) | 仓库新稿与知乎同步由用户手动完成；十章不宣称已开发十天 |

## NVIDIA 与 StepFun 为什么各有具体职责

- NVIDIA Skills文档和目录用于开发方法、技能发现、扫描、评测与治理；自研领域SKILL.md不冒称NVIDIA认证。领域方法决定该看什么、该读什么与缺少什么，宿主承担权限、工具执行与预算。
- CUDA视觉使用当前Qwen3-VL-8B原生服务。32B候选保留真实失败与权重，不因参数更多就宣称专业更强。
- NeMo Agent Toolkit核对固定资料、读取回执、段落与哈希；引用身份正确不能替代推断支持与专家判断。
- NIM保留官方Spark ARM64 Model-Free NIM原厂SDK及入口，独立8007提供标准文字接口；一次公开陶瓷文字请求正常结束并绑定同进程前八步CUDA。
- TensorRT-LLM官方ARM64 rc13独立8006运行4B文字模型；一次公开请求和限定PyTorch CUDA轨迹已保存。它采用PyTorch backend，不冒称已经生成序列化TensorRT engine。
- 官方开放Embedding 1B v2与cuVS独立8003，25段/2048维索引已运行；原客户端9次向量HTTP、5个中文查询，50条身份与10个正文SHA核对。它不是Embedding NIM，也不是完整Retriever SDK管线。
- StepFun step-3.7-flash对获批文字执行真实反证审查，本地模型回查并修订；原图不外发。外部角色的意见也需要检查，不自动成为专家真值。
- Nsight Systems只采集归档第03轮双图视觉区间；独立NIM与TensorRT-LLM文字请求分别采用SGLang/PyTorch Profiler核对前八步。各自绑定请求，不混称整案性能结果。

原图位于后端部署所在本机；部署在Spark时保存在指定Spark项目。公开GitHub Pages教学体验不调用私有模型、不包含用户原图、节点凭证或API密钥。

## 当前专业研究与数字的边界

第12轮已经完成初稿、批准文字审查、本地修订、两版引用身份核查及六份导出。原模型意见、观察和失败记录按原件保留；专业准确性评估列为下一阶段专家工作。报告正文分别显示观察、资料、候选和判断理由，不能用模型自信代替材料。

六维筛查是可解释的工作优先级：总权重100，每项只计一次；冲突指数为冲突权重之和，复核优先为冲突权重加一半未知权重，已评覆盖为已评权重。全部未知时冲突指数为未评；它们不是真品率。Laya的score适合后续文字任务路由校准，Jev适合浏览器资料访问，不被强行写成瓷器真伪概率模型。

设备桥接已实现真实受控HTTP采集与原字节回取。眼镜厂商SDK、桌面采集箱、XRF/热释光等模块仍为适配或硬件研究方向。NVIDIA FLARE机构联合训练与NeMo RL后训练按授权数据、专家审核、离线训练、保留集、发布/回滚规划，未宣称已经联邦训练或在线强化学习。

## 固定提交地址与原始记录

已提交主页、Demo与知乎三个地址保持不变。更新内容不代表代替用户修改知乎或补出B站回执。个人参赛，中文网页与报告不使用NVIDIA雇员身份。

较早第05轮、r15回归及部署候选记录保存在Git历史和各自原始verification目录；不把旧状态表当作当前实现。最新入口：[STATUS](../STATUS.md)、[提交清单](demo-and-submission.md)、[软件回执](../verification/software/v09/README.md)、[NIM更新](nim-v09-update.md)。官方开发参考：[NVIDIA Skills](https://docs.nvidia.com/skills)、[官方技能目录](https://github.com/nvidia/skills)、[NeMo Agent Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit)。
