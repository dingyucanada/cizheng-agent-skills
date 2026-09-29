"""Synthesize only revised public narration; preserves previous full editions."""
from pathlib import Path
import json,subprocess,shutil,hashlib
b=Path(__file__).resolve().parent;plan=json.loads((b/'scene-plan-v3.json').read_text());out=b/'voice-v3';out.mkdir(exist_ok=True)
rows=[]
for i,s in enumerate(plan['scenes']):
 cues=[]
 for j,text in enumerate(s['cues']):
  f=out/f'{i+1:02d}-{j+1:02d}.aiff'
  if s['id'] in ['contradiction','actual-record']:
   subprocess.run(['/usr/bin/say','-v','Tingting','-r','185','-o',str(f),text],check=True)
  else:shutil.copy2(b/'voice'/f'{i+1:02d}-{j+1:02d}.aiff',f)
  m=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration,size','-of','json',str(f)]))['format'];assert float(m['duration'])>1 and int(m['size'])>10000
  cues.append({'text':text,'audio':str(f.relative_to(b)),'audio_seconds':float(m['duration']),'audio_sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
 rows.append({'id':s['id'],'cues':cues})
(b/'voice-receipt-v3.json').write_text(json.dumps({'synthetic':True,'provider':'Installed macOS system speech, no provider API/key','voice':plan['voice'],'scenes':rows,'model_call_to_Spark':False,'previous_audio_versions_preserved':True},ensure_ascii=False,indent=2)+'\n');print(json.dumps({'cue_count':sum(len(s['cues']) for s in rows),'five_new_public_cues':True,'raw_total_seconds':sum(c['audio_seconds']for s in rows for c in s['cues'])}))
