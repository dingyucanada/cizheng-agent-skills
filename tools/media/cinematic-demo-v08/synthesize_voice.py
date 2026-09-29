from pathlib import Path
import subprocess,json,hashlib,math
b=Path(__file__).resolve().parent;p=json.loads((b/'scene-plan.json').read_text());out=b/'voice';out.mkdir(exist_ok=True)
rows=[]
for i,s in enumerate(p['scenes']):
 cues=[]
 for j,text in enumerate(s['cues']):
  f=out/f'{i+1:02d}-{j+1:02d}.aiff'
  subprocess.run(['/usr/bin/say','-v',p['voice']['voice'],'-r',str(p['voice']['rate']),'-o',str(f),text],check=True)
  meta=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_entries','format=duration,size','-of','json',str(f)]))['format']
  assert float(meta.get('duration',0))>1 and int(meta['size'])>10000
  cues.append({'text':text,'audio':str(f.relative_to(b)),'audio_seconds':float(meta['duration']),'audio_sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
 rows.append({'id':s['id'],'cues':cues})
 print(json.dumps({'scene':i+1,'seconds':sum(x['audio_seconds'] for x in cues)}),flush=True)
(b/'voice-receipt.json').write_text(json.dumps({'synthetic':True,'provider':'Installed macOS native system speech, no provider API/key','voice':p['voice'],'scenes':rows,'model_call_to_Spark':False},ensure_ascii=False,indent=2)+'\n')
