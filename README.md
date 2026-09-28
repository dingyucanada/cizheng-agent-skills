# 瓷证 · 陶瓷证据研究 Agent

**把器物照片、来源凭据、专业资料和研究意见，组织成能够回到原始证据的案卷。**

面向博物馆编目研究、收藏档案整理与拍卖图录准备。瓷证提供完整的公开教学体验和可在本机 / DGX Spark 部署的专业工作台：先观察和定位，再查资料和提出竞争解释，补证后比较版本，由人工复核并导出案卷。

[项目主页](https://dingyucanada.github.io/cizheng-agent-skills/) · [免上传完整体验](https://dingyucanada.github.io/cizheng-agent-skills/demo.html) · [使用手册](docs/user-guide.md) · [比赛交付清单](docs/demo-and-submission.md) · [当前状态](STATUS.md)

网站地址对应本仓库的 GitHub Pages 发布目标；部署是否成功以仓库的 Pages 工作流及实际网页为准。公开体验使用真实公开馆藏图片和项目编写的研究示例，**当前不调用 AI 模型，示例不是鉴定结论或专家签署**。实时推理需要连接模型服务。Spark 与 StepFun 的现场验证尚待完成。

## 为什么做瓷证

专业研究工作会同时遇到几类问题：器物名称和时期标签混在一起，照片中的可见现象被直接写成制作工艺判断，转引资料失去页码和版本，来源经历只有叙述而没有对应文件，研究意见改变后无法解释改了什么。单次聊天回答难以承载这些责任。瓷证将器物登记、图像观察、资料记载、归属主张和人工复核分别保存，并通过定位、版本和文件哈希把它们联系起来。

博物馆场景强调编目、状况和文献核查；收藏场景强调来源凭据、未知经历及补拍计划；拍卖场景强调图录措辞、归属依据与条件说明。三个入口改变研究任务和材料重点，不代表系统已经接入某家机构或具备机构审批资格。输出是可以继续研究、交接和订正的证据案卷，供专业人员判断。

这也是 Agent Skills 的具体用处：把“下一步怎样研究、需要读什么、遇到矛盾怎样保留不足”组织成可复用方法包。模型运行由有限工具、实际读取回执和执行预算约束。没有模型时，材料登记、检索关联、图像操作、准备复核与离线导出仍然可用；有模型时，工具执行、证据引用、补证修订和失败记录进入同一案卷。系统不会用预先写好的答案替代实际模型调用。

## 不上传材料，也能完整体验

公开体验预置三套教学案卷：山水纹花觚、青花镂空茶壶和五彩耕织图瓶。真实图片与馆藏基本资料来自 Met Open Access；资料出处、文件哈希和图片许可均可回查。三件身份已知，不能用于宣称未知器物鉴定准确率。

进入 [体验页](https://dingyucanada.github.io/cizheng-agent-skills/demo.html) 后可以直接：

1. 选择业务场景和器物，阅读准备好的照片、档案、来源与研究问题。
2. 编辑登记内容与自己的观察，点击证据回到图像区域或文字定位。
3. 阅读实际 Skill 方法，检查示例解释的支持、冲突和缺口，按提示查看预置补证。
4. 比较补证前后的记录与意见，保存本浏览器的人工复核备注。
5. 导出研究报告及带清单的证据交接包，并核对文件哈希。

访客的修改保存在自己的浏览器，不上传服务器。所有预写意见均标为教学示例；浏览器复核备注不是可信专家签名。公开体验与本地服务的能力边界详见 [公开体验说明](docs/public-experience.md)。

## 本地专业工作台

要求 Python 3.11+。`requirements-tested.txt` 固定本项目实际测试的依赖，`requirements.txt` 保留兼容范围。以下命令创建本地环境、导入完整教学材料并启动服务：

```bash
git clone https://github.com/dingyucanada/cizheng-agent-skills.git
cd cizheng-agent-skills
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-tested.txt
python -m cizheng.demo --guided --data-dir ./data
python -m uvicorn cizheng.api:create_app --factory --host 127.0.0.1 --port 8780
```

浏览器打开 `http://127.0.0.1:8780`。完整教学材料可重复导入，不覆盖后续人工修改，不请求模型。仅需基本照片和馆藏登记可改用 `--professional`。

| 工作区 | 可以实际完成的工作 |
|---|---|
| 案件总览 | 选择博物馆、收藏、拍卖任务，查看准备度与下一项工作 |
| 器物档案 | 记录尺寸、款识、来源事件、状况检查及对应原文件 |
| 图像研究 | 原图、双图、缩放、局部框选、人工区域观察；档案最多 30 图，本轮选 1–8 图 |
| 知识资料库 | 中文关键词检索、查看出处及段落、固定本案采用的资料版本 |
| 研判与补证 | 连接模型后执行有预算的工具流程，保存证据主张和修订历史 |
| 报告复核 | 分别复核材料准备与模型意见，导出 JSON、Markdown、HTML 和离线交接 ZIP |

无照片委托可以使用“文字凭据核查”：只读本案许可 UTF-8 TXT 和固定资料段落，逐项记录相符、冲突、缺失与需复核。PDF 保留原始文件和定位登记，当前不自动 OCR；这条任务不作年代、窑口、风格或真伪归属。

## Agent Skills 与证据执行

本项目使用开放的 Skill 目录与 Markdown 方法结构，学习 [NVIDIA/skills](https://github.com/nvidia/skills) 的方法包与运行框架分工。业务技能均为项目自研，**未获得 NVIDIA Verified、专家签名或专业准确率认证**。Skill 文件本身不等于运行系统：前端、后端、工具、模型适配器和验证合同共同完成流程。

| Skill | 方法与边界 |
|---|---|
| [ceramic-route](skills/ceramic-route/SKILL.md) | 根据材料与任务选择研究路径，明确需要补拍或保留不足 |
| [ceramic-research-record](skills/ceramic-research-record/SKILL.md) | 分开对象登记、可见观察、资料记载与归属主张 |
| [bluewhite-attribution-test](skills/bluewhite-attribution-test/SKILL.md) | 对青花花觚提出竞争解释，不以相似风格直接推出制作时期 |
| [condition-hypothesis-test](skills/condition-hypothesis-test/SKILL.md) | 分开照片中的现象与实物状况解释，指出未检范围 |
| [provenance-evidence-audit](skills/provenance-evidence-audit/SKILL.md) | 核对来源事件、同器联系与实际凭据，保留经历缺口 |
| [documentary-evidence-audit](skills/documentary-evidence-audit/SKILL.md) | 依据实际读到的文字片段核查记载，不做视觉归属 |
| [evidence-revise](skills/evidence-revise/SKILL.md) | 补证后比较主张和依据，保留旧运行、失败和未解决项 |

描述 → 方法正文 → 按需参考资源，形成渐进加载；整包 SHA256 固定实际采用的方法版本。工具执行不开放通用 Shell。运行固定案卷、图片、资料及 Skill 版本，引用必须对应成功读取的段落和定位。单轮预算为 12 次主模型、20 次工具、300 秒；初轮与最多两次修订共享 36 / 60 / 900 的累计上限，取消和失败同样保留用量。

## RAG：可回查的资料，不是自动可信标签

`knowledge/` 提供 25 条项目原创来源短摘要，覆盖馆藏个案、编目、来源、状况及研究方法，注明机构链接、作者、适用范围、文字权利和局限，均待专家核查。没有分发机构页面全文、用户培训 PDF 或私人专家资料。逐条中文来源见 [来源核查表](docs/chinese-source-audit.md)。

后端使用 SQLite 和中文重叠双字词的关键词索引，不是向量模型。检索分表示文字匹配程度；实际引用还要读到指定段落，校验资料版本、文档哈希、段落哈希和定位。知识库更新不会静默改写旧案。馆藏时期标签只属于对应编号的器物，不能变成待鉴对象答案。RAG 和证据链有助于回查，不能保证模型不出错。

## Spark、NVIDIA 与 StepFun

推荐将正式模型演示的后端、数据库与视觉模型部署在同一 Spark 项目目录，笔记本通过 SSH 转发访问。原图由指定本机 / Spark 服务处理；如果后端仍在笔记本，笔记本也保存原图，需如实说明。

| 技术 | 当前事实 | 接入后的验证 |
|---|---|---|
| DGX Spark / CUDA | 部署和只读环境检查脚本已提供，节点尚未连接 | 记录真实 ARM64、驱动、CUDA、内存和运行日志 |
| Qwen3.6-35B-A3B-NVFP4 + vLLM | 按 NVIDIA Spark 配方准备的首选部署候选，未在节点执行 | 先复用健康现有服务；新增时固定镜像 digest 与模型 revision，验证多图、局部和动作合同 |
| 量化、上下文、并发调整 | 初始参数为项目候选，不是已证明的性能收益 | 比较真实冷 / 热请求、图片负载、内存、延迟及专家案例 |
| StepFun 文字反证审查 | API 适配、预览、批准包固定与单次提交逻辑已实现，实际凭据联调待完成 | 仅提交公开或明确获准脱敏的文字，不发原图，不自动重试 |
| NVIDIA Agent Skills 生态 | 方法包设计和培训落地对照已完成 | 实际运行记录 Skill 发现、加载、参考读取与效果边界 |

详见 [模型选择](docs/model-selection.md)、[Spark 部署验收](docs/spark-validation.md)、[培训落地对照](docs/training-implementation.md)。当前没有实测 tokens/s、GPU 使用率、准确率或 Skills 提升百分比。Jev 不在本地核心链路，Laya 仅保留默认关闭的文本影子实验；没有将二者宣传成陶瓷视觉预审模型。

## 验证与复现

```bash
python -m pytest -q
python scripts/build-public-site.py
npm ci --ignore-scripts
npm run test:web
python -m cizheng.paired_eval --manifest examples/public-demo/manifest.json --output prepared-teaching-input.json
```

工程测试检查原文件保留、跨案权限、资料版本、已读回执、预算、补证和导出等合同；纯色图、脚本模型、模拟网络不能衡量陶瓷鉴定能力。公开教学样本用于说明流程。有 / 无 Skills 的专业比较需使用独立专家样本、相同模型、资料和预算，保留无改善和失败例；3–5 件个案也不能推出行业准确率。见 [评测协议](evals/PROTOCOL.md) 与 [专家材料接入](docs/expert-intake.md)。

## 仓库与参赛交付

```text
cizheng/              FastAPI、案卷、工具执行、资料库、模型与评测适配
static/               本地专业工作台前端
skills/               七个 SKILL.md、方法卡、参考文件与评测合同
knowledge/            25 条原创来源摘要与出处
examples/public-demo/ 公开馆藏照片、许可、来源与教学材料
site/                 GitHub Pages 主页与免上传体验
deploy/               本地与 Spark 启动、环境检查及配置示例
docs/                 产品、使用、模型、部署、比赛与权利说明
evals/ tests/          专业评测协议与工程验证
```

官方要求的 500 字以上作品说明、技术架构、部署 / 优化 / Skills 设计与技能 Markdown 已组织在本仓库。按六项评分对应的事实、证据和待补项见 [比赛交付清单](docs/demo-and-submission.md)。公开仓库和教学体验不能替代真实 Spark / StepFun 模型演示、B 站视频、真实团队合影及组委会表单提交；这些事项完成后，应以实际链接和记录更新状态。

## 适用范围与许可

本版提供可在本地受控试用的单人工作台，尚未实现机构多用户授权、可信专家签署、实物检测、价格评估或产权审批。原件校验和复核记录用于证据回查，不能直接变成自动鉴定证书。

项目自研代码采用 [MIT](LICENSE)。Met 公版图片与基本记录遵守馆方 Open Access / CC0；图片、资料和依赖不因代码采用 MIT 就统一改变许可。见 [第三方来源与权利](THIRD_PARTY.md)。GitHub Pages 只发布 `site/`，不发布私人数据库、密钥、模型权重或用户提供的培训材料。可先阅读 [公开部署说明](docs/github-pages.md) 再发布自己的副本。
