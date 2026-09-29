# 来源、许可证与技术归属

瓷证自研源码按仓库 LICENSE（MIT）提供；Python依赖各自许可由其上游维护，本包不分发依赖、权重或私人案卷。公开仓库仅包含自研代码、许可公开材料及匿名的软件验证记录。

`examples/public-demo` 的 Met 公版图片和馆藏基本记录按馆方Open Access/CC0政策提供；明确来源、许可、下载URL和原始文件哈希见 sources.json。作品馆藏归属不代表本项目完成独立鉴定。私人专家样本须另外登记使用与公开许可。

2026-09-29 公开馆藏个案核查新增 Met [854455](https://www.metmuseum.org/art/collection/search/854455)、[42239](https://www.metmuseum.org/art/collection/search/42239)、[48450](https://www.metmuseum.org/art/collection/search/48450)，共六张原始 JPEG。馆方 API 的 isPublicDomain 字段均为 true；图片和基本记录使用 [Met Open Access / CC0](https://www.metmuseum.org/policies/image-resources)，原件、下载地址、图片身份和权利核对记录保存在 verification/public-collection-20260929。中文题名及核查备注为项目翻译和 AI 核查，不是馆方专家意见；网页长篇解说未作为 CC0 全文再分发，模型原输出及失败状态保留。

专业 Skills 的结构遵循开放格式，业务方法为本项目研究程序，尚待陶瓷专家审阅。不复制 NVIDIA 的签名或Verified徽章。实际使用 NVIDIA SkillSpector 2.12.0 对七个运行范围进行静态扫描，明确排除 evals/，完整包诊断保留。未完成官方 SkillEvaluator live 对照或签名，扫描不等于Verified或专业准确率。整包 SHA256 用于本项目版本一致性，不证明可信机构签名或专业正确性。

官方培训和 NVIDIA/skills 的设计经验引用见外部学习报告及 docs/training-implementation.md。部署脚本是项目适配层，不包含NVIDIA官方已签名Skill修改件；本包没有完整TAO、VSS或RAG Blueprint依赖。候选模型和vLLM镜像须遵守各自上游许可及固定版本。

StepFun通过项目文字API适配器审查获批文字；公开Demo讲稿另调用`stepaudio-2.5-tts`官方系统音色生成中文旁白，`stepaudio-2.5-asr`用于成片内容转写检查。没有发送器物原图、克隆第三方真人声音或分发StepFun权重；[配音素材及实际回执](verification/media/stepfun-demo-v10/index.json)与器物研究输入分开。Laya影子入口默认关闭，若手动安装须检查上游许可证和模型来源；它不参与视觉判断。Jev浏览器外部服务不进入本地核心链路。

公开教学扩展包含 Met 51185（79.2.1202a, b）与 50839（61.200.30）的馆方公版JPEG。具体下载地址、原字节SHA256及对象页权利记录见 examples/public-demo/professional-cases.json；原有48607图像记录仍见 sources.json。知识资料仅分发项目原创短摘要及出处，机构页面全文、其他机构图片和私人文件未纳入代码包。项目原创摘要统一标为待专家核查；原页面版权不因写入摘要而改变。

中文扩展包含14件馆藏与1份修护研究的项目原创短摘要。逐条来源、原资料作者、权限与失败访问记录见 docs/chinese-source-audit.md 和 knowledge/chinese-source-expansion.json。仅在项目摘要上标authorized_text，不能解释为原机构全文或影像授权；CC BY注明题名、机构、出处和许可，未导入未获许可原图。

NVIDIA NeMo Agent Toolkit 1.9.0与SkillSpector 2.12.0在各自隔离环境安装；本包分发的是自研插件、调用脚本和范围明确的验证记录，不分发上游依赖或NVIDIA签名件。Spark原生适配器使用PyTorch、Transformers及Qwen官方模型；依赖和权重须遵守各自上游许可，模型不纳入公开仓库。技术作用、官方出处和实际验证见 docs/nvidia-integration.md、integrations/spark_transformers/README.md。

结构化动作生成采用第三方 LM Format Enforcer 0.11.3 与 interegular 0.3.3；上游源码见 [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)。这是格式约束依赖，不是NVIDIA专属框架，不提供真伪概率或知识正确性保证。GPU适配器的有界Schema检查与最终校验为本项目代码；原有主机数值、证据、权限与工作流校验仍独立执行。本包不分发上述依赖；固定CPU解析器检查环境见 requirements-structured-tested.txt。

本次独立 TensorRT-LLM 部署使用 NVIDIA 官方 rc13 ARM64 容器与 Qwen3-4B BF16，容器、CUDA及模型按各自上游条款，权重和镜像不进入本公开仓库。[NVIDIA项目许可](https://github.com/NVIDIA/TensorRT-LLM/blob/v1.3.0rc13/LICENSE) · [Qwen模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)。NVIDIA开放 `llama-nemotron-embed-1b-v2` 模型依原固定版本的[官方模型许可](https://huggingface.co/nvidia/llama-nemotron-embed-1b-v2/blob/113abe4acafa848e77ead9c0623205e511932348/LICENSE)；cuVS、CuPy和隔离依赖保留各自许可。本仓库仅提供适配源码、固定身份与范围明确的凭证，不分发权重、wheel、Ubuntu开发包或依赖。NIM另按官方中国伙伴公开 Spark ARM64 Model-Free NIM 2.1.8 固定镜像部署，原厂服务入口与 SDK 身份、实际请求和 CUDA 轨迹见 [本次说明](docs/nim-v09-update.md)。不分发其容器、SDK或权重；开放embedding服务仍不称Embedding NIM，所有组件使用不代表NVIDIA认证。

报告自托管字体为 Adobe Source Han Serif SC 2.003 与 Source Han Sans SC 2.005 的报告字符子集，按 SIL Open Font License 1.1 提供。派生字体已更名 Cizheng Report Serif / Sans，原轮廓、版权与许可保留；上游 commit、原件及子集 SHA、生成程序见 [字体来源清单](site/report-assets/fonts/FONT-SOURCES.json) 和同目录两份 OFL。新增专业示意图由本项目制作，采集箱图明确为设计概念。旧项目 PPT 仅作为方法参考，未分发其原图、专利或身份陈述。
