"""Build a narrated 1080p film from pinned real materials. No model calls."""
from pathlib import Path
import subprocess,json,wave,math,hashlib,sys,concurrent.futures
import numpy as np
b=Path(__file__).resolve().parent;version=sys.argv[1] if len(sys.argv)>1 else 'v1';out=b/version;out.mkdir(exist_ok=True)
FF='ffmpeg';FP='ffprobe';fps=25;rate=48000;tempo=1.15
planfile=b/f'scene-plan-{version}.json';voicefile=b/f'voice-receipt-{version}.json';plan=json.loads((planfile if planfile.exists() else b/'scene-plan.json').read_text());voice=json.loads((voicefile if voicefile.exists() else b/'voice-receipt.json').read_text());audio=b/f'audio-converted-{version}' if version not in ['v1','v2'] else b/'audio-converted';audio.mkdir(exist_ok=True)
def run(args):
 r=subprocess.run(args,capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr[-3500:])
 return r
for i,scene in enumerate(voice['scenes']):
 for j,c in enumerate(scene['cues']):
  p=audio/f'{i+1:02d}-{j+1:02d}.wav'
  if not p.exists():run([FF,'-v','error','-y','-i',str(b/c['audio']),'-af',f'atempo={tempo}','-ac','1','-ar',str(rate),'-c:a','pcm_s16le',str(p)])
  with wave.open(str(p)) as w:c['converted_samples']=w.getnframes();c['PCM']=w.readframes(w.getnframes())
# All scene/cue boundaries derive from real audio samples, rounded to video frames.
track=[];cue_rows=[];scenes=[];sample=0
for i,scene in enumerate(voice['scenes']):
 start=sample;intro=int(rate*.6);track.append(bytes(intro*2));sample+=intro
 for j,c in enumerate(scene['cues']):
  a=sample;track.append(c['PCM']);sample+=c['converted_samples'];z=sample
  cue_rows.append({'scene':i+1,'text':c['text'],'start':a/rate,'end':z/rate,'voice_file':c['audio']})
  gap=int(rate*.1);track.append(bytes(gap*2));sample+=gap
 tail=int(rate*.6);track.append(bytes(tail*2));sample+=tail
 end=math.ceil(sample/(rate/fps))*int(rate/fps);track.append(bytes((end-sample)*2));sample=end
 scenes.append({'id':scene['id'],'number':i+1,'start':start/rate,'end':sample/rate,'frames':int((sample-start)/(rate/fps)),'seconds':(sample-start)/rate})
total=sample/rate;assert 150<=total<=200,total
with wave.open(str(out/'narration.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b''.join(track))
# Original procedural ambient score; no third-party music or sampled instrument.
t=np.arange(sample)/rate;music=np.zeros(sample,dtype=np.float64)
chords=[[146.832,220.,293.665,369.994],[123.471,184.997,246.942,293.665],[97.999,146.832,195.998,246.942],[110.,164.814,220.,277.183]]
for idx,start in enumerate(np.arange(0,total,5)):
 mask=(t>=start)&(t<start+5);u=t[mask]-start;env=(1-np.exp(-u*2))*np.exp(-u*.35)
 for k,f in enumerate(chords[idx%4]):music[mask]+=.005*np.sin(2*np.pi*f*u+idx*.2)*env
 # Quiet airy harmonic, deliberately below the spoken narration.
 music[mask]+=.0015*np.sin(2*np.pi*chords[idx%4][-1]*2*u)*env
music*=np.minimum(t/2,1)*np.minimum((total-t)/3,1)
with wave.open(str(out/'original-ambient.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes((np.clip(music,-1,1)*32767).astype('<i2').tobytes())
def srt_time(v):
 ms=round(v*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000);return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
def wrap(text,maxchar=25):
 a=list(text)
 # v4 only: avoid a one-word second line without changing any narrated text.
 if version=='v4' and maxchar<len(a)<=maxchar*2:
  lower=max(8,len(a)-maxchar);upper=min(maxchar,len(a)-8);middle=len(a)/2
  candidates=[i+1 for i,c in enumerate(a) if c in '，；。：？' and lower<=i+1<=upper]
  split=min(candidates,key=lambda i:abs(i-middle)) if candidates else math.ceil(middle)
  return ''.join(a[:split])+'\n'+''.join(a[split:])
 return '\n'.join(''.join(a[n:n+maxchar]) for n in range(0,len(a),maxchar))
(out/'cizheng-demo-v07.srt').write_text('\n'.join(f'{i+1}\n{srt_time(c["start"])} --> {srt_time(c["end"])}\n{wrap(c["text"])}\n' for i,c in enumerate(cue_rows)))
def ass_time(v):return srt_time(v).replace(',','.')[1:-1]
ass='''[Script Info]
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
for c in cue_rows:ass+=f'Dialogue: 0,{ass_time(c["start"])},{ass_time(c["end"])},Default,,0,0,0,,{wrap(c["text"]).replace(chr(10),chr(92)+"N")}\n'
(out/'captions.ass').write_text(ass)
clips=out/'clips';clips.mkdir(exist_ok=True)
def encode_scene(s):
 p=clips/f'{s["number"]:02d}.mp4';scene=out/'scenes'/f'{s["number"]:02d}-{s["id"]}.png'
 frames=s['frames'];z=.024 if version=='v1' else .018
 receipt=clips/f'{s["number"]:02d}.source.json'
 identity={'scene_png_sha256':hashlib.sha256(scene.read_bytes()).hexdigest(),'frames':frames,'zoom':z}
 if '--reuse-clips' in sys.argv and p.exists() and receipt.exists():
  old=json.loads(receipt.read_text())
  if old.get('input_identity')==identity and old.get('clip_sha256')==hashlib.sha256(p.read_bytes()).hexdigest():return p
 vf=f"scale=2880:1620,zoompan=z='1+{z}*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s=1920x1080:fps=25,fade=t=in:st=0:d=0.23,fade=t=out:st={s['seconds']-.20}:d=0.20,format=yuv420p"
 run([FF,'-v','error','-y','-i',str(scene),'-vf',vf,'-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','20','-threads','3',str(p)])
 receipt.write_text(json.dumps({'input_identity':identity,'clip_sha256':hashlib.sha256(p.read_bytes()).hexdigest()},indent=2)+'\n')
 print(json.dumps({'version':version,'encoded_scene':s['number'],'seconds':s['seconds']}),flush=True);return p
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(encode_scene,scenes))
if '--clips-only' in sys.argv:
 print(json.dumps({'prepared_scene_clips_only':True,'version':version,'seconds':total}),flush=True);sys.exit(0)
(out/'clips.concat').write_text(''.join("file '"+str(clips/(f"{s['number']:02d}.mp4"))+"'\n" for s in scenes))
run([FF,'-v','error','-y','-f','concat','-safe','0','-i',str(out/'clips.concat'),'-c','copy',str(out/'picture-track.mp4')])
filters=f"[0:v]ass={out/'captions.ass'}[v];[1:a]asplit=2[voice][duckref];[2:a][duckref]sidechaincompress=threshold=0.03:ratio=4:attack=25:release=500[bg];[voice][bg]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=8[a]"
run([FF,'-v','error','-y','-i',str(out/'picture-track.mp4'),'-i',str(out/'narration.wav'),'-i',str(out/'original-ambient.wav'),'-filter_complex',filters,'-map','[v]','-map','[a]','-t',str(total),'-c:v','libx264','-preset','fast','-crf','20','-threads','4','-c:a','aac','-b:a','160k','-ar',str(rate),'-movflags','+faststart',str(out/'cizheng-demo-v07.mp4')])
result={'schema':'cizheng-cinematic-edit.v1','version':version,'seconds':total,'frames':sum(s['frames'] for s in scenes),'resolution':[1920,1080],'fps':fps,'synthetic_narration':True,'voice':plan['voice'],'voice_tempo_adjustment':tempo,'music':'Original procedural ambient score, no third-party music','scenes':scenes,'subtitle_cues':cue_rows,'permanent_truth_scope':'Real public catalogue photos, actual teaching-interface screenshots and saved-record reconstruction; not continuous AI recording or expert validation','nvidia_boundary':plan.get('nvidia_boundary','TRT text/open NVIDIA embedding+cuVS independently verified; original visual/SQLite production path kept, not NIM'),'video_sha256':hashlib.sha256((out/'cizheng-demo-v07.mp4').read_bytes()).hexdigest(),'video_bytes':(out/'cizheng-demo-v07.mp4').stat().st_size}
(out/'cizheng-demo-v07.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'movie_done':True,'version':version,'seconds':total,'sha256':result['video_sha256']}),flush=True)
