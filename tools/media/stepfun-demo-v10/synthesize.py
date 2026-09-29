"""Synthesize public demo paragraphs with StepFun TTS. Keys stay in the environment."""
from pathlib import Path
import argparse,base64,concurrent.futures,hashlib,json,os,subprocess,time,urllib.request,urllib.error
INSTRUCTION='自然、亲切、专业的普通话项目讲解，像研究员向同行介绍工作台。中等语速，按完整句子连贯表达。语气沉稳有叙述感，避免逐词断开、夸张播音腔和长时间停顿。疑问句自然上扬。'
def sha(data):return hashlib.sha256(data).hexdigest()
def payload(scene,voice):return {'model':'stepaudio-2.5-tts','voice':voice,'input':''.join(scene['cues']),'instruction':INSTRUCTION,'response_format':'mp3','sample_rate':24000,'speed':1.0,'text_normalization':'enhanced','stream_format':'sse','timestamp':True}
def synth(scene,number,voice,base,out,key):
 stem=f'{number:02d}-{scene["id"]}';data=json.dumps(payload(scene,voice),ensure_ascii=False,separators=(',',':')).encode();receipt=out/(stem+'.json');audio=out/(stem+'.mp3')
 if receipt.exists() and audio.exists():
  saved=json.loads(receipt.read_text())
  if saved.get('request_sha256')==sha(data) and saved.get('audio_sha256')==sha(audio.read_bytes()) and saved.get('status')==200:return saved
 if not key:raise RuntimeError(f'TTS {stem}: matching cache is absent; --offline cannot generate new audio')
 (out/(stem+'-request.json')).write_bytes(data);request=urllib.request.Request(base+'/audio/speech',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+key,'User-Agent':'Cizheng-Demo-Voice/1.0'},method='POST');a=time.monotonic()
 try:
  with urllib.request.urlopen(request,timeout=60)as response:raw=response.read();status=response.status;ctype=response.headers.get('Content-Type')
 except urllib.error.HTTPError as e:
  raw=e.read();(out/(stem+'-error.txt')).write_text(raw.decode(errors='replace').replace(key,'[REDACTED]'));(out/(stem+'-failed.json')).write_text(json.dumps({'scene':scene['id'],'status':e.code,'request_sha256':sha(data),'response_sha256':sha(raw),'retry_count':0},indent=2));raise RuntimeError(f'TTS {stem}: HTTP{e.code}; failure retained; no automatic retry')from None
 (out/(stem+'.sse')).write_bytes(raw);chunks=[];subtitles=[];events=[]
 for line in raw.decode().splitlines():
  if not line.startswith('data:'):continue
  event=line[5:].strip()
  if not event or event=='[DONE]':continue
  obj=json.loads(event);events.append(obj.get('type'))
  if obj.get('type')=='speech.audio.error':raise RuntimeError(f'TTS {stem}: server audio error; raw stream retained')
  if obj.get('audio'):chunks.append(base64.b64decode(obj['audio']))
  if obj.get('type')=='response.subtitle':subtitles.append(obj['data'])
 assert 'speech.audio.done'in events and subtitles and chunks,f'{stem}: incomplete audio/subtitles'
 pcm=b''.join(chunks);audio.write_bytes(pcm);duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(audio)]).decode())
 result={'scene':scene['id'],'number':number,'status':status,'content_type':ctype,'model':'stepaudio-2.5-tts','voice':voice,'request_sha256':sha(data),'response_sse_sha256':sha(raw),'audio':audio.name,'audio_sha256':sha(pcm),'audio_bytes':len(pcm),'duration_seconds':duration,'elapsed_seconds':time.monotonic()-a,'input':payload(scene,voice)['input'],'subtitles':subtitles,'event_types':sorted(set(events)),'retry_count':0}
 receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'scene':scene['id'],'status':status,'seconds':duration,'word_times':sum(len(x.get('items',[]))for x in subtitles)}),flush=True);return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--voice',default='ruyananshi');p.add_argument('--base-url',default='https://api.stepfun.com/step_plan/v1');p.add_argument('--offline',action='store_true',help='Verify and reuse cached audio without a key or network');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 key='' if args.offline else os.environ.get('STEPFUN_API_KEY','');assert args.offline or key,'Set STEPFUN_API_KEY privately, or use --offline with matching audio';base=args.base_url.rstrip('/');assert base in ['https://api.stepfun.com/step_plan/v1','https://api.stepfun.com/v1'],'Use the official StepFun endpoint'
 scenes=json.loads(args.plan.read_text())['scenes'];assert len(scenes)<=20 and all(0<len(''.join(s['cues']))<=1000 for s in scenes)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:rows=list(pool.map(lambda item:synth(item[1],item[0]+1,args.voice,base,args.out,key),enumerate(scenes)))
 receipt={'schema':'cizheng.demo-stepfun-voice.v1','endpoint':base+'/audio/speech','model':'stepaudio-2.5-tts','voice':args.voice,'instruction':INSTRUCTION,'speed':1.0,'post_generation_time_stretch':False,'synthesis_unit':'one complete paragraph per scene, not separate sentences','approved_input_scope':'Authored public demo narration only; no object images, private attachments or expert answers','request_count':len(rows),'scenes':rows}
 (args.out/'voice-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'all_scenes':len(rows),'all_http200':all(x['status']==200 for x in rows),'total_raw_speech_seconds':sum(x['duration_seconds']for x in rows)}),flush=True)
