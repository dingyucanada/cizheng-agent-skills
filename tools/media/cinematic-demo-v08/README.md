当前发布视频已升级为 [StepFun 中文旁白与固定画面版](../stepfun-demo-v10/README.md)。本目录保留旧版制作与回执，不代表当前配音或镜头设置。

# 历史版本 / 瓷证 Demo 制作记录

本目录保留实际多轮制作脚本、中文台词、原材料身份、合成旁白收据与修改记录。影片采用公开馆藏照片、真实教学界面截图，以及保存记录的图文重建；不是连续 AI 录屏。Tingting 为本机合成普通话，配乐为原创程序化合成。

工具版本：@napi-rs/canvas 0.1.100；FFmpeg 实际版本记录在公开验收索引。1080p25；字幕由实际旁白 PCM 样本边界生成。当前45段旁白逐条与成片AAC解码交叉比对；此前v2为46段。没有调用 Spark 模型或远程 TTS。

复现输入按 material-source-manifest.json 的文件名放到 materials/；声音生成需要 macOS 已安装 Tingting。原始教学截图和音频留在本地制作材料中，公共台词、素材身份和验收结论可独立查阅。不同系统语音/字体版本可能产生不同字节，未承诺跨设备字节一致。

先按保留的v2台词运行 synthesize_voice.py，再用 synthesize_revision_voice.py 仅替换审阅要求的五句公开台词。完成NIM实证后，用 synthesize_nim_revision_voice.py 仅更新第15场三句公开台词。第四版依次运行 render_scenes.mjs v4、encode_movie.py v4、verify_movie.py v4、verify_audio_sync.py v4、contact_sheets.mjs v4。v3完整修订片保留。Python 需要 NumPy；Node 需要该固定 canvas 包。字幕及原照片保持真实材料边界；若服务部署状态改变，应核验保存记录后仅替换对应场景。私有 staging 路径和原始日志不进入发布材料。
