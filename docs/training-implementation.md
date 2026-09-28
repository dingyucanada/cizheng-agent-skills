# 官方培训到本实现的对照

三份PDF共54页及两个notebook的完整学习记录保存在交付总入口的“官方培训逐页学习与落地对照.md”；此处只列本源码的具体落点，不把培训中的指令当用户授权或强制赛规。

| 培训位置 | 学到的约束 | 实际落点与边界 |
|---|---|---|
| 刘春晖p.2–4 | Skill是开放指令包；Verified含扫描/评测/签名/卡片 | 七个SKILL包（原四个方法包及编目研究、来源核查、文字凭据核查）、整包哈希、真实状态卡。未获NVIDIA Verified，不伪造签名 |
| 刘春晖p.6 | 同模型同任务有/无Skills；负例与发现能力 | paired_eval独立两臂，trigger_eval独立描述触发20例。工程测试不能充当专业增益 |
| 刘春晖p.8 | 卡片解释责任、依赖、风险和证据 | 每包skill-card.md。专家复核状态仍pending；许可另见THIRD_PARTY |
| StepFun p.8、p.11 | 像素细节与三级渐进加载 | skill_runtime安全YAML，描述→正文→资源；视觉原图保留，概览/按需局部，主上下文实际接图 |
| StepFun p.14、p.16 | 接口兼容不等于行为相同，效果用真实输出说明 | model_probe真实端点三项基础行为探针；尚未接节点，未写成绩 |
| StepFun p.17 | MCP连接、Skill知识、Harness调度 | 自研Engine调度、工具注册/合同、技能程序。MVP没有额外MCP层，不把函数调用伪装为MCP |
| Spark训练 p.8 | 能否串联看输出合同 | schema、media_id、observation_id、引用读取/看图检查；不给旧摘要冒充新观察 |
| Spark训练 p.9 | FP8 Qwen3.6/GB10、vLLM及具体兼容修复 | 保留FP8已有服务路线；新NVFP4部署用其独立官方配方。不是拼接参数或声明已测 |
| Spark训练 p.10 | 固定提交，官方Skill保持原样 | 本项目只借鉴官方方法和合同，环境差异在deploy。没有修改官方签名Skill |
| Spark训练 p.12 | 自研后处理与坐标映射、可验证输出 | EXIF1–8显示到文件坐标、区域原像素裁剪、HTML关联图像与JSON运行档案 |

来源：用户提供的三份官方培训PDF；[NVIDIA官方Skills目录](https://github.com/NVIDIA/skills)；模型及部署的当前一手来源见model-selection.md。培训的安装量、展示模型成绩、TAO参数和现场时长不计为本项目成绩，也不自动成为比赛要求。
