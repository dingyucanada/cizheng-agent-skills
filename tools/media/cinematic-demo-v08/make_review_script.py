from pathlib import Path
import json,sys
b=Path(__file__).resolve().parent;v=sys.argv[1] if len(sys.argv)>1 else 'v2';pf=b/f'scene-plan-{v}.json';p=json.loads((pf if pf.exists() else b/'scene-plan.json').read_text());m=json.loads((b/v/'cizheng-demo-v07.json').read_text());notices=json.loads((b/v/'scene-boundaries.json').read_text());out=b/(f'review-{v}' if v not in ['v1','v2'] else 'review');out.mkdir(exist_ok=True)
rows=['# 瓷证 Demo 成片完整台词与审阅单','',f'成片{v}：{m["seconds"]:.2f} 秒，1920×1080，25 fps。Tingting 本机合成普通话旁白，原创程序化轻音乐。','', '内容以真实公开器物照片、实际教学工作台截图和真实保存记录摘要为材料。教学画面未调用模型；记录摘要不是连续推理录屏。没有虚构客户使用、专家签署或实物仪器测量。','', p.get('nvidia_release_note','新增能力槽位单独在第15场；当前仅写已实测的独立 TensorRT-LLM 文字服务与官方开放 NVIDIA embedding + cuVS 服务。NIM 未写成部署成功。'),'']
for s,t,n in zip(p['scenes'],m['scenes'],notices):
 rows+= [f'## {t["number"]:02d} · {t["start"]:.2f}–{t["end"]:.2f} 秒 · {s["eyebrow"]}','', '画面：'+ ' / '.join({'workbench':['原图在左。','研究意见在旁。'],'read':['找到资料，','读到原段落。'],'export':['导出案卷，','继续核查。']}.get(s['id'],s['title'])),'','旁白：','']
 for c in [x for x in m['subtitle_cues'] if x['scene']==t['number']]:rows+=[f'- {c["start"]:.3f}–{c["end"]:.3f}：{c["text"]}']
 rows+=['','常驻边界：'+n['permanent_notice'],'']
rows+=['## 发布入口与手动修订提醒','','以下三个已提交链接保持原字符不变：','',*[f'- {x}' for x in p['submitted_urls'].values()],'','知乎由作者手动维护。建议同步新版成片简介：专业业务流程、合成旁白、教学截图与真实保存记录的区别，以及独立新服务已实测但未切换原主流程；保留专家样本与专业质量验证待开展的准确边界。无需登录或代发。','']
(out/'demo-script.md').write_text('\n'.join(rows));print(out/'demo-script.md')
