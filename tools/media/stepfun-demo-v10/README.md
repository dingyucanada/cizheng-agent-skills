# 瓷证 Demo · StepFun 中文旁白与固定画面

当前影片采用18个完整场景段落，使用 StepFun `stepaudio-2.5-tts`、官方系统音色 `ruyananshi`（儒雅男士）及 `speed=1.0`。同一段落连续合成，字幕依照接口实际逐词时间戳对齐。固定1920×1080画面仅在场景边界做200毫秒淡入淡出，没有持续缩放和平移；原创轻音乐在旁白出现时自动压低。

素材为公开馆藏照片、实际教学界面截图和保存记录的重建。这是场景讲解，不是连续实时推理录像。教学例子、工程检查或配音质量不作为专家鉴定结果。

[固定发布视频](https://dingyucanada.github.io/cizheng-agent-skills/assets/cizheng-demo-v07.mp4) · [实际验收](../../../verification/media/stepfun-demo-v10/index.json) · [完整中文台词](../../../docs/demo-script.md) · [历史制作原件身份](../cinematic-demo-v08/material-source-manifest.json)

## 不用密钥的离线复现

仓库提供18张实际场景图、18段实际API生成的MP3、逐词时间戳和公开请求体。无密钥的离线模式不会调用服务。需要 Python 3.11+、NumPy、包含libass的FFmpeg及能显示中文的字体。实际制作使用macOS Hiragino Sans GB；其他平台可把build_movie.py中的ASS字体名改为已安装的Noto Sans CJK SC。字体及编码器版本变化会改变成片字节，不承诺跨设备字节一致。

在仓库根目录运行：

```bash
python -m pip install numpy
TASK_MEDIA_BUILD=/tmp/cizheng-stepfun-demo
mkdir -p "$TASK_MEDIA_BUILD"
python tools/media/stepfun-demo-v10/synthesize.py --offline --plan tools/media/stepfun-demo-v10/scene-plan.json --out tools/media/stepfun-demo-v10/audio
python tools/media/stepfun-demo-v10/generate_music.py --out "$TASK_MEDIA_BUILD/original-ambient.wav"
python tools/media/stepfun-demo-v10/build_movie.py --plan tools/media/stepfun-demo-v10/scene-plan.json --voice-root tools/media/stepfun-demo-v10/audio --scene-root tools/media/stepfun-demo-v10/scenes --reference-edit tools/media/stepfun-demo-v10/reference-edit.json --music "$TASK_MEDIA_BUILD/original-ambient.wav" --out "$TASK_MEDIA_BUILD/movie"
```

输出包含MP4、SRT、JSON、字幕ASS、场景片段和旁白轨。整体仍193.12秒、4828帧、25fps。音乐由本目录公式生成，实际本机重算与历史原声SHA一致。`reference-edit.json`是此前已发布剪辑的时长分配与材料边界，参考版本在Git提交c551758；不把它当成新版旁白回执。

如需重复声画机械检查，可安装Pillow并运行：

```bash
python -m pip install pillow
python tools/media/stepfun-demo-v10/verify_movie.py --movie "$TASK_MEDIA_BUILD/movie/cizheng-demo-v07.mp4" --metadata "$TASK_MEDIA_BUILD/movie/cizheng-demo-v07.json" --out "$TASK_MEDIA_BUILD/qa"
```

该检查完整解码音视频，读取字幕对应实际帧，采样18个画面区域及测量响度；不能替代听者对声音自然度的判断。

## 重新调用StepFun配音

只在修改台词时需要API密钥。通过私人进程环境设置 `STEPFUN_API_KEY`，调用同一脚本时去掉 `--offline`；匹配请求哈希和音频哈希的缓存直接复用。脚本限定官方Base URL，每段一次请求、最多两路并行、失败保留回执且不自动重试。不要把密钥写入台词、请求JSON、命令行参数或仓库。

当前配音只发送公开讲稿，不读取私有原图或案卷。SSE流模式使用MP3；实际兼容性探测发现WAV流模式返回400，因此改用支持的MP3流模式，失败记录保留。

官方说明：[StepFun音频Plan入口](https://platform.stepfun.com/docs/zh/step-plan/integrations/audio-api) · [TTS接口](https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio)

生成回执记录输入、状态、音频SHA和词时间戳；完整ASR、解码与稳定性检查绑定最终MP4。ASR核对讲述内容，不作为自然度评分或人工完整试听。TTS与案卷里的`step-3.7-flash`文字反证是两项不同用途，模型名称不会混用。
