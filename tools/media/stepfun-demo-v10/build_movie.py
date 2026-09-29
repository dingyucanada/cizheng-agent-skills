"""Create a fixed-camera narrated film from verified scene images and StepFun timestamps."""
from pathlib import Path
import argparse,concurrent.futures,hashlib,json,math,subprocess,wave
FPS=25;RATE=48000
ASS_HEADER='''[Script Info]
Title: 瓷证业务场景讲解
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Hiragino Sans GB,43,&H00FFFFFF,&H00FFFFFF,&H00102A3D,&H00102A3D,0,0,0,0,100,100,0,0,1,1.4,0,2,115,115,38,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
def run(args):
 r=subprocess.run(args,capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr[-4000:])
 return r

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(t):return ''.join(x.lower()for x in t if x.isalnum())
def stamp(v):
 ms=round(v*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000);return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
def wrap(t):
 if len(t)<=25:return t
 if len(t)<=50:
  low=max(8,len(t)-25);high=min(25,len(t)-8);c=[i+1 for i,x in enumerate(t)if x in '，。；：？！'and low<=i+1<=high];split=min(c,key=lambda x:abs(x-len(t)/2))if c else math.ceil(len(t)/2);return t[:split]+'\n'+t[split:]
 return '\n'.join(t[i:i+25]for i in range(0,len(t),25))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--voice-root',type=Path,required=True);p.add_argument('--scene-root',type=Path,required=True);p.add_argument('--reference-edit',type=Path,required=True);p.add_argument('--music',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
 plan=json.loads(a.plan.read_text());voice=json.loads((a.voice_root/'voice-receipt.json').read_text());old=json.loads(a.reference_edit.read_text());assert len(plan['scenes'])==len(voice['scenes'])==len(old['scenes'])==18
 converted=a.out/'pcm';converted.mkdir(exist_ok=True);voices=[];minimum=[]
 for i,row in enumerate(voice['scenes']):
  source=a.voice_root/row['audio'];assert sha(source)==row['audio_sha256'];f=converted/f'{i+1:02d}.wav';run(['ffmpeg','-v','error','-y','-i',str(source),'-ac','1','-ar',str(RATE),'-c:a','pcm_s16le',str(f)])
  with wave.open(str(f))as w:pcm=w.readframes(w.getnframes());samples=w.getnframes()
  voices.append((pcm,samples));minimum.append(math.ceil((samples/RATE+.4)*FPS))
 total_frames=old['frames'];extra=total_frames-sum(minimum);assert extra>=0,{'natural_speech_exceeds_original_length':-extra/FPS}
 slack=[max(0,old['scenes'][i]['frames']-minimum[i])for i in range(18)];den=sum(slack)or 18;weights=slack if sum(slack)else[1]*18;fraction=[extra*x/den for x in weights];alloc=[int(x)for x in fraction]
 for i in sorted(range(18),key=lambda i:fraction[i]-alloc[i],reverse=True)[:extra-sum(alloc)]:alloc[i]+=1
 frames=[minimum[i]+alloc[i]for i in range(18)];assert sum(frames)==total_frames
 track=[];scene_rows=[];cues=[];frame_cursor=0
 for i,(scene,row)in enumerate(zip(plan['scenes'],voice['scenes'])):
  start=frame_cursor/FPS;length=frames[i]/FPS;intro=round(.2*RATE);pcm,n=voices[i];padding=frames[i]*(RATE//FPS)-intro-n;assert padding>=0;track.extend([bytes(intro*2),pcm,bytes(padding*2)])
  words=[w for sub in row['subtitles']for w in sub['items']];normalized=''.join(norm(w['text'])for w in words);assert normalized==norm(''.join(scene['cues'])),{'scene':scene['id'],'timestamp_text_mismatch':True}
  word_intervals=[];cursor=0
  for w in words:
   size=len(norm(w['text']));word_intervals.append((cursor,cursor+size,w['start_time']/1000,w['end_time']/1000));cursor+=size
  cursor=0
  for t in scene['cues']:
   n=len(norm(t));matches=[x for x in word_intervals if x[1]>cursor and x[0]<cursor+n];assert matches;begin=start+.2+matches[0][2];end=start+.2+matches[-1][3];assert start<=begin<end<=start+length+.04
   cues.append({'scene':i+1,'text':t,'start':round(begin,6),'end':round(end,6),'alignment':'StepFun actual word timestamps; paragraph synthesized together','voice_file':row['audio']});cursor+=n
  image=a.scene_root/f'{i+1:02d}-{scene["id"]}.png';assert image.is_file();scene_rows.append({'id':scene['id'],'number':i+1,'start':start,'end':start+length,'frames':frames[i],'seconds':length,'voice_start':start+.2,'voice_seconds':voices[i][1]/RATE,'image_sha256':sha(image)});frame_cursor+=frames[i]
 narration=a.out/'narration.wav'
 with wave.open(str(narration),'wb')as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(RATE);w.writeframes(b''.join(track))
 assert len(cues)==45
 srt=a.out/'cizheng-demo-v07.srt';srt.write_text('\n'.join(f'{i+1}\n{stamp(x["start"])} --> {stamp(x["end"])}\n{wrap(x["text"])}\n'for i,x in enumerate(cues)))
 ass=ASS_HEADER
 for x in cues:ass+=f'Dialogue: 0,{stamp(x["start"]).replace(",",".")[1:-1]},{stamp(x["end"]).replace(",",".")[1:-1]},Default,,0,0,0,,{wrap(x["text"]).replace(chr(10),chr(92)+"N")}\n'
 (a.out/'captions.ass').write_text(ass);clips=a.out/'clips';clips.mkdir(exist_ok=True)
 def encode(row):
  png=a.scene_root/f'{row["number"]:02d}-{row["id"]}.png';target=clips/f'{row["number"]:02d}.mp4';vf=f'fade=t=in:st=0:d=0.2,fade=t=out:st={row["seconds"]-.2}:d=0.2,format=yuv420p'
  run(['ffmpeg','-v','error','-y','-loop','1','-framerate',str(FPS),'-i',str(png),'-vf',vf,'-frames:v',str(row['frames']),'-an','-c:v','libx264','-preset','fast','-crf','18','-threads','2',str(target)]);print(json.dumps({'scene_encoded':row['number'],'fixed_camera':True,'seconds':row['seconds']}),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:list(pool.map(encode,scene_rows))
 (a.out/'clips.concat').write_text(''.join("file '"+str(clips/f'{x["number"]:02d}.mp4')+"'\n"for x in scene_rows));picture=a.out/'picture-track.mp4';run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(a.out/'clips.concat'),'-c','copy',str(picture)])
 filters=f'[0:v]ass={a.out/"captions.ass"}[v];[1:a]asplit=2[voice][duckref];[2:a][duckref]sidechaincompress=threshold=0.03:ratio=4:attack=25:release=500[bg];[voice][bg]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=8[a]'
 final=a.out/'cizheng-demo-v07.mp4';total=total_frames/FPS;run(['ffmpeg','-v','error','-y','-i',str(picture),'-i',str(narration),'-i',str(a.music),'-filter_complex',filters,'-map','[v]','-map','[a]','-t',str(total),'-c:v','libx264','-preset','fast','-crf','18','-threads','3','-c:a','aac','-b:a','160k','-ar',str(RATE),'-movflags','+faststart',str(final)])
 result={**old,'version':'v5-stepfun-stable','seconds':total,'frames':total_frames,'voice':{'provider':'StepFun API','model':voice['model'],'voice':voice['voice'],'synthetic':True,'speed':1.0,'instruction':voice['instruction'],'unit':'complete scene paragraphs'},'voice_tempo_adjustment':1.0,'post_generation_time_stretch':False,'camera_motion':'none; static1920x1080scene images,200msfade only','scenes':scene_rows,'subtitle_cues':cues,'subtitle_timing':'45 cues aligned to actual StepFun word timestamps; risk-index and supplementary-material phrasing clarified after ASR review','video_sha256':sha(final),'video_bytes':final.stat().st_size,'production_replacement_status':'Prepared reviewed build; publication verified separately','voice_receipt_sha256':sha(a.voice_root/'voice-receipt.json'),'music_source_sha256':sha(a.music)}
 (a.out/'cizheng-demo-v07.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'movie_done':True,'seconds':total,'frames':total_frames,'bytes':final.stat().st_size,'sha256':sha(final),'fixed_camera':True,'stepfun_tts':True}),flush=True)
