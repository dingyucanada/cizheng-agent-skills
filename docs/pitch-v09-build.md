# 瓷证路演 v0.9

本目录的幻灯片为 13 页中文个人参赛作品，使用 `@oai/artifact-tool` JavaScript 创作。中文架构、业务链路、方法加载和研究路线均为原生可编辑文本、形状和连接线；第 7、8、10 页为原生表格。截图和馆藏照片为图像。

稳定入口保留为 `site/assets/cizheng-pitch-v07.pptx`、`site/assets/cizheng-pitch-v07.pdf` 和 `site/assets/cizheng-pitch-v07-preview.html`。版本号不改变已提交的网址。

## 复现

准备 Node.js、`@oai/artifact-tool`、presentations 技能运行时、可用中文字体、LibreOffice 和 Poppler。将运行时绝对路径仅放入本机环境变量，不写入公开文件。源目录应包含公开仓库的 `site/assets` 输入素材。

1. 设置 `PITCH_SOURCE`（源仓库）、`PITCH_WORKSPACE`（独立私有构建目录）、`PITCH_REVISION`（版本标签）、`PRESENTATIONS_SKILL_DIR`、`RUNTIME_PYTHON` 和 `RUNTIME_NODE_MODULES`，运行 `scripts/build-pitch-v09.mjs`。
2. 用独立 LibreOffice 用户配置将最终 PPTX 转为 PDF。为中文字体设置本机 Fontconfig；不要将字体缓存、配置路径或运行时日志放入公开包。
3. 用 `pdftoppm -png -scale-to-x 1920 -scale-to-y 1080` 渲染该 PDF 的每一页，文件前缀为 `slide`。逐页核对实际导出的文字、表格、连接线、图像和链接色。
4. 设置 `PITCH_FINAL_PPTX`、`PITCH_FINAL_PDF`、`PITCH_RENDER_DIR`、`PITCH_NOTES_JSON`、`PITCH_QA_JSON`、`PITCH_OVERLAY` 和 `PITCH_AUTHORING_SOURCE`，运行 `scripts/export-pitch-v09.mjs`。该步骤只复制已核对的文件和真实 PDF 渲染图，不重新绘制页面。QA JSON 参照本目录记录格式，绑定实际成品的 SHA。

## 素材和边界

馆藏器物图像来自 Met Public Domain / CC0：18.61.4（48607，整体正面和另一面分别使用一次）、79.2.1202a,b（51185）、61.200.30（50839）。本轮新增2021.321a,b（854455）、14.40.396（42239）、17.57.1（48450）三件公开馆藏照片和个案核查。每张原图只在一页使用，来源和 SHA 见清单。公开工作台截图来自项目已保存的软件界面；教学案和合成协议练习均在讲稿及相关页面明确标记。未复制参考演讲的图片、设备、专利或身份。

主视觉仍为 Qwen3-VL-8B 和 SQLite 案卷资料路径。35B和27B已完成独立案卷核查，未默认替换8B。27B原始权重和进程的绑定待补验。NIM、TensorRT-LLM 文字和 Embedding + cuVS 为独立已部署、实测服务。Agent Skills 方法效果、真品概率校准和独立专家评价列入发展计划。受控采集、眼镜 SDK、桌面箱、NVFLARE 和 NeMo RL 为后续研究。没有虚构团队、合作、专业准确率或厂商背书。

## 验证范围

最终 PPTX 的包完整性、布局几何、字体选择、13 页数量、最终文件回读、3 张原生表格及六维权重合计 100 已通过结构检查。实际 LibreOffice PDF 有 13 页，已全页渲染并逐页视觉核对；HTML 预览使用该 PDF 的 13 张图。此结果不等于在原生 Microsoft PowerPoint 中执行验证，也不证明专业鉴定准确率。
