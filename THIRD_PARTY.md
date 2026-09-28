# 来源、许可证与技术归属

瓷证自研源码按仓库 LICENSE（MIT）提供；Python依赖各自许可由其上游维护，本包不分发依赖、权重或私人案卷。公开仓库仅包含自研代码、许可公开材料及匿名的软件验证记录。

`examples/public-demo` 的 Met 公版图片和馆藏基本记录按馆方Open Access/CC0政策提供；明确来源、许可、下载URL和原始文件哈希见 sources.json。作品馆藏归属不代表本项目完成独立鉴定。私人专家样本须另外登记使用与公开许可。

专业 Skills 的结构遵循开放格式，业务方法为本项目研究程序，尚待陶瓷专家审阅。不复制 NVIDIA 的签名或Verified徽章。实际使用 NVIDIA SkillSpector 2.12.0 对七个运行范围进行静态扫描，明确排除 evals/，完整包诊断保留。未完成官方 SkillEvaluator live 对照或签名，扫描不等于Verified或专业准确率。整包 SHA256 用于本项目版本一致性，不证明可信机构签名或专业正确性。

官方培训和 NVIDIA/skills 的设计经验引用见外部学习报告及 docs/training-implementation.md。部署脚本是项目适配层，不包含NVIDIA官方已签名Skill修改件；本包没有完整TAO、VSS或RAG Blueprint依赖。候选模型和vLLM镜像须遵守各自上游许可及固定版本。

StepFun仅通过项目文字API适配器使用，没分发其权重。Laya影子入口默认关闭，若手动安装须检查上游许可证和模型来源；它不参与视觉判断。Jev浏览器外部服务不进入本地核心链路。

公开教学扩展包含 Met 51185（79.2.1202a, b）与 50839（61.200.30）的馆方公版JPEG。具体下载地址、原字节SHA256及对象页权利记录见 examples/public-demo/professional-cases.json；原有48607图像记录仍见 sources.json。知识资料仅分发项目原创短摘要及出处，机构页面全文、其他机构图片和私人文件未纳入代码包。项目原创摘要统一标为待专家核查；原页面版权不因写入摘要而改变。

中文扩展包含14件馆藏与1份修护研究的项目原创短摘要。逐条来源、原资料作者、权限与失败访问记录见 docs/chinese-source-audit.md 和 knowledge/chinese-source-expansion.json。仅在项目摘要上标authorized_text，不能解释为原机构全文或影像授权；CC BY注明题名、机构、出处和许可，未导入未获许可原图。

NVIDIA NeMo Agent Toolkit 1.9.0与SkillSpector 2.12.0在各自隔离环境安装；本包分发的是自研插件、调用脚本和范围明确的验证记录，不分发上游依赖或NVIDIA签名件。Spark原生适配器使用PyTorch、Transformers及Qwen官方模型；依赖和权重须遵守各自上游许可，模型不纳入公开仓库。技术作用、官方出处和实际验证见 docs/nvidia-integration.md、integrations/spark_transformers/README.md。

结构化动作生成采用第三方 LM Format Enforcer 0.11.3 与 interegular 0.3.3；上游源码见 [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)。这是格式约束依赖，不是NVIDIA专属框架，不提供真伪概率或知识正确性保证。GPU适配器的有界Schema检查与最终校验为本项目代码；原有主机数值、证据、权限与工作流校验仍独立执行。本包不分发上述依赖；固定CPU解析器检查环境见 requirements-structured-tested.txt。
