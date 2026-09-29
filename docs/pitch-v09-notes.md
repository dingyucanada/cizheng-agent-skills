# 瓷证中文路演讲稿

个人参赛作品，13 页，v0.9。

## 01 瓷证

瓷证面向陶瓷研究材料的整理、补证和交接。AI负责观察和证据整理，专业人员负责复核。器物为公开已知身份教学材料，不代表项目完成了独立鉴定。

来源：

- 图像：The Metropolitan Museum of Art，18.61.4，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/48607
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/examples/public-demo/sources.json
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/product-and-architecture.md

## 02 专业复核先要找回证据

这里描述的是产品解决的工作问题，不是市场规模调查。收藏档案、博物馆编目和图录准备都需要把描述和依据对应。系统组织研究路径，不能凭照片替代实物检测。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/product-and-architecture.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/professional-research.md
- 图像：The Metropolitan Museum of Art，79.2.1202a,b，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/51185

## 03 一份案卷承接整段研究工作

截图来自真实本地专业工作台的公开教学案。选区、图像操作、来源记录和离线交接可以在不调用模型时使用。截图中的馆方资料和人工教学观察不等同实际模型报告。原件、人工记录、固定资料版本、Agent运行和复核各有版本，材料更新后旧复核显示过期。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/site/assets/workbench-v06.jpg
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/user-guide.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/product-and-architecture.md

## 04 真实案卷的审查和修订闭环

这页以真实保存记录说明业务链路。主视觉模型处理公开Met48607两图，StepFun step-3.7-flash只接批准的四字段文字包，没有原图或图像访问地址。两版NAT引用核查及JSON、Markdown、HTML导出有实际记录。专业问题仍待解决：初稿把同器Met18.61.4资料写为不适用本件，修订删除该句，时期和风格支持理由仍需专业复核，三项审查问题均保留未解决。流程完成不能作为鉴定准确率或Skills因果效果。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/verification/nvidia/v07-workflows/round-12/workflow-summary.json
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/verification/nvidia/v07-workflows/round-12/text-review/executed.json
- https://dingyucanada.github.io/cizheng-agent-skills/assets/cizheng-ai-replay-v07.mp4

## 05 Agent Skills 把方法写成执行步骤

七包均为真实自研文件包，按description、SKILL正文和资源渐进加载，每包有适用范围和限制。整包SHA不是专家认可或NVIDIA Verified认证。宿主限制工具权限、实际读取和进入成功主动作的材料、累计模型和工具预算。真实运行还有可选协调器材料准备，协调器加载和模型自然触发分别记录；本页不把协调器行为当作Skills自然触发或专业提升。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/ceramic-route/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/ceramic-research-record/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/bluewhite-attribution-test/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/condition-hypothesis-test/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/provenance-evidence-audit/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/documentary-evidence-audit/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/skills/evidence-revise/SKILL.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/cizheng/skill_runtime.py
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/controlled-workflow.md
- NVIDIA Agent Skills平台参考：https://docs.nvidia.com/skills

## 06 本地证据和受控模型协作

架构是原生可编辑对象和连接线。本地案卷使用SQLite保存原件、版本和回执，主视觉为Spark Qwen3-VL-8B。35B和27B通过独立双图案卷验证而非默认切换，较大模型不自动证明更高准确率。27B公开原始权重和进程的绑定仍待核验。NAT经正式插件核查引用身份，不证明引用对专业结论的支持。StepFun只接明确批准的公开或脱敏文字。本轮NIM纯文本Qwen3-4B BF16为实际独立服务；TRT文字和官方Embedding+cuVS亦独立验收，主业务未自动切换。采集桥接是文件协议，不代表眼镜、手持仪器或桌面箱已完成厂商SDK和物理验收。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/product-and-architecture.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/nvidia-integration.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/spark-models-and-reasoning-v10.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/device-capture.md

## 07 Spark 本地部署和模型分工

8B主视觉继续承担案卷业务。Qwen3.6-35B-A3B-NVFP4经原厂NIM的SGLang后端完成独立双图案卷流程，GPU有限采样可回查，运行后停止。35B使用Marlin NVFP4 W4A16路径，不声称完整NVFP4硬件加速。Qwen3.8-27B完成另一条独立双图案卷流程，公开工作流的原始weights_revision仍为unverified，不能证明固定原始权重和实际进程绑定。较大模型均未默认替换8B，也没有证明更高专业准确率。4B NIM和TensorRT-LLM为独立文字端点，TRT使用PyTorch backend，没有序列化engine。Embedding为开放官方1B v2加cuVS，不是Embedding NIM或完整Retriever SDK。主业务资料仍使用SQLite。这里记录部署和业务位置，不将单次延迟当作整案加速。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/spark-models-and-reasoning-v10.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/nim-v09-update.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/verification/nvidia/tensorrt-llm-v08/README.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/integrations/nvidia_retriever/README-open-service.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/spark-validation.md

## 08 六维矛盾筛查：先安排复核工作

筛查是已实现的独立CPU规则功能，不调用视觉模型或StepFun。结构化记载绑定本件凭据SHA和定位，自动比较年份/高度区间、同编号体系的本件编号、来源事件先后。每维只计一次，固定总权重100。矛盾指数为冲突权重，所有未知时不可评价；复核优先为冲突权重加0.5倍未知权重；覆盖为已评价权重除100。截图只用于演示软件协议，两份300–301和350–351毫米高度是合成数字，不是馆藏实测或照片测量。权重和模型依据尚未完成专家标签校准。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/risk-triage.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/cizheng/risk_triage.py
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/site/assets/risk-workbench-v09.png
- https://dingyucanada.github.io/cizheng-agent-skills/triage.html

## 09 证据缺口决定下一项拍摄

整体照片能支持部分可见形态，但不能补造底足、款识或修复细节。本页的拍摄循环是产品逻辑，也是可编辑流程。现已实现统一本机multipart会话协议、客户端、SHA校验、原始blob、设备声明、时间/单位和归档回执，并通过真实本机HTTP上传下载保持公共图片原字节SHA。设备身份、相机时钟和传感器尚未厂商认证或实物标定。智能眼镜、专业手持和桌面箱先导出文件到本机桥接；厂商SDK、直接拍摄控制和箱式硬件为未来研究，当前不具备材料检测或物理鉴定能力。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/device-capture.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/scripts/device-capture-client.py
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/risk-triage.md
- 图像：The Metropolitan Museum of Art，18.61.4，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/48607

## 10 专业试用的交付和采用方式

三种入口已经以公共教学案演示材料工作，不代表真实机构委托或合作。当前为个人作品和单人受控试用。拟议试用从小范围案卷材料整理开始，以材料整理时间、关键疑点遗漏、专家复核可用性评估产品价值。商业模式是后续探索，不虚构客户、收入、团队或已签合作。多用户权限、可信专家签署、合规审计和灾备仍需产品化。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/README.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/product-and-architecture.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/examples/public-demo/professional-cases.json

## 11 专家反馈驱动方法和模型改进

这是下一阶段研究路线，不是已取得的专家成绩。样本应取得授权并按器物分割，专家标签和首轮证据分开，避免同器照片泄漏到训练和测试两侧。专家分别评价图像观察、区域定位、资料引用、理由、补证和拒绝判断。固定模型、资料和预算后比较有/无Skills，保留失败并在独立保留样本上回归。NVFLARE联合训练和NeMo RL后训练是未来研究，没有联合训练网络、自动在线学习或专业准确率。

来源：

- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/expert-validation-intake.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/training-implementation.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/evals/PROTOCOL.md

## 12 公开馆藏个案：逐条核对观察和理由

三件器物各两张Met CC0照片，保存了九次真实Spark流程。阶段A不向模型提供本件馆方年代和窑口，普通提示和Skills使用同模型、同预算；全部A结束后，阶段B再加入同件固定馆藏文字。四轮保存意见并等待补证，五轮停止，全部原件和模型原文保留，不能把停止写成成功报告。储水器由荷兰设计师Pronk设计不等同荷兰制作，彩瓷瓶没有外底或足内视角不能推出实物无款，青釉碗黄色修补外观不能单凭照片确定金缮工艺。碗的阶段B有一条来源语境引用，但底款建议和理由仍需专业评价。另有一次实际StepFun公开文字审查，属于AI反证而非专家意见。此页是公开馆藏资料的个案核查，不是独立专家鉴定或行业准确率。

来源：

- https://dingyucanada.github.io/cizheng-agent-skills/public-collection-check.html
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/docs/public-collection-case-check-20260929.md
- https://github.com/dingyucanada/cizheng-agent-skills/blob/main/verification/public-collection-20260929/index.json
- 图像：The Metropolitan Museum of Art，“射手”纹青花储水器，2021.321a, b，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/854455
- 图像：The Metropolitan Museum of Art，仿古铜器形彩瓷瓶，14.40.396，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/42239
- 图像：The Metropolitan Museum of Art，龙泉青釉碗，17.57.1，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/48450

## 13 瓷证

个人参赛作品。完整报告呈现产品、实际模型记录和部署证据。公开教学体验无需上传，不调用私有模型。公开仓库保留自研方法包、代码和脱敏部署记录。来源机构和NVIDIA不代表对本项目的背书或专业鉴定认证。

来源：

- https://dingyucanada.github.io/cizheng-agent-skills/report.html
- https://dingyucanada.github.io/cizheng-agent-skills/demo.html
- https://github.com/dingyucanada/cizheng-agent-skills
- 图像：The Metropolitan Museum of Art，61.200.30，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/50839
