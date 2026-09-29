# 瓷证 Demo · 器物照片、从容结尾与中国风轻配乐

这一版按用户确认将“入藏研究”的旁白和场景标题改为“器物研究”，第二场标题不用句号；来源场景改为“先核对具体器物”，结尾改为“判断理由可核查”；18场角标统一为“从材料出发，让判断有据。”。第53秒的来源场景放入 **Met 18.61.4同一件器物的两幅公开照片**，保留完整器形和来源编号；前一场的资料阅读界面也有对应原图。没有生成或修饰器物细节。

中文配音由 StepFun `stepaudio-2.5-tts`、官方系统音色 `ruyananshi`（儒雅男士）生成。每个场景为完整段落；主体请求速度1.0，展望段0.95，最后一段0.90。后期不拉伸、压缩或加速语音。最后一段提前留0.65秒，旁白结束后保留至少4.2秒，画面以1.6秒淡出。

配乐《瓷证·藏影疏弦》是原创合成的D宫五声音阶轻音乐，用拨弦与箫的声音意象衬托器物研究。它不是采样的真实古琴、古筝或箫演奏，不含外部音乐。音乐3秒淡入、4秒淡出，混音先衰减6dB，人声出现时继续自动压低。全部画面固定，场景之间仅200毫秒淡入淡出，无持续缩放或平移。 最终混音在4倍采样下限制瞬时峰值，AAC编码后重新测量响度和峰值。

最终影片 **203.36秒 / 5084帧 / 1920×1080 / 25fps**，45条字幕按每段实际接口词时间戳对齐。原提交地址不变：[观看视频](https://dingyucanada.github.io/cizheng-agent-skills/assets/cizheng-demo-v07.mp4) · [实际检查](../../../verification/media/stepfun-demo-v11/index.json) · [中文台词](../../../docs/demo-script.md)。旧版制作记录继续保留在v10目录。

素材为公开馆藏照片、实际教学界面截图及保存记录的重建，是剪辑场景讲解。配音与媒体检查不作为陶瓷鉴定结果或人类专家验证。

## 无密钥离线制作

Python需要NumPy、Pillow；FFmpeg需要libass和H.264编码器。源场景和18段实际MP3及其回执都已提供。中文字幕默认使用macOS Hiragino Sans GB，其他平台应在build_movie.py中选择已安装的中文字体。字体和FFmpeg版本变化可能改变编码字节。

在仓库根目录执行：

```bash
python -m pip install numpy pillow
TASK_MEDIA_BUILD=/tmp/cizheng-stepfun-demo-v11
mkdir -p "$TASK_MEDIA_BUILD"
python tools/media/stepfun-demo-v11/synthesize.py --offline --plan tools/media/stepfun-demo-v11/scene-plan.json --out tools/media/stepfun-demo-v11/audio
python tools/media/stepfun-demo-v11/generate_music.py --duration 203.36 --out "$TASK_MEDIA_BUILD/chinese-original.wav"
python tools/media/stepfun-demo-v11/build_movie.py --plan tools/media/stepfun-demo-v11/scene-plan.json --voice-root tools/media/stepfun-demo-v11/audio --scene-root tools/media/stepfun-demo-v11/scenes --reference-edit tools/media/stepfun-demo-v11/reference-edit.json --music "$TASK_MEDIA_BUILD/chinese-original.wav" --out "$TASK_MEDIA_BUILD/movie"
python tools/media/stepfun-demo-v11/verify_movie.py --movie "$TASK_MEDIA_BUILD/movie/cizheng-demo-v07.mp4" --metadata "$TASK_MEDIA_BUILD/movie/cizheng-demo-v07.json" --out "$TASK_MEDIA_BUILD/qa"
```

输出MP4、SRT、JSON、ASS、完整旁白轨和场景片段。reference-edit.json是修订前的实际影片时间分配；新版保持场景顺序，按每段实际声音长度调整画面停留，并延长结尾，不强行限制在原193.12秒内。

照片构图可用add_catalogue_photos.py和仓库的两张Met原图重建。原图SHA、照片来源与处理方式见photo-compositing-receipt.json。运行update_motto.py可统一重画18场角标，之后再编码影片。音乐公式、固定随机种子及其声学测量侧车支持重算；LUFS或频谱测量不能代替听者对音乐风格的判断。

## 重新配音

只在修改台词时需要服务。将 `STEPFUN_API_KEY` 留在私有环境变量中，执行synthesize.py时去掉 `--offline`。脚本使用官方端点，缓存同时核对请求与音频哈希，每个完整场景一次调用、最多两路并行；错误不自动重试。只发送公开讲稿，不发送器物原图、私有案卷或专家材料。

[StepFun TTS接口](https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio) · [Plan音频接入](https://platform.stepfun.com/docs/zh/step-plan/integrations/audio-api)。生成回执和字幕检查不等同于真人完整试听或自然度评分。
