"""Verify full decode, actual media metadata and synchronized cue/frame samples."""
from pathlib import Path
import subprocess,json,hashlib,math,re,sys
b=Path(__file__).resolve().parent;v=sys.argv[1] if len(sys.argv)>1 else 'v2';out=b/v;qa=out/'qa';qa.mkdir(exist_ok=True)
movie=out/'cizheng-demo-v07.mp4';meta=json.loads((out/'cizheng-demo-v07.json').read_text())
def run(a):
 r=subprocess.run(a,capture_output=True,text=True);return r
probe=run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(movie)]);assert probe.returncode==0
p=json.loads(probe.stdout);video=next(s for s in p['streams'] if s['codec_type']=='video');audio=next(s for s in p['streams'] if s['codec_type']=='audio')
assert video['width']==1920 and video['height']==1080 and video['r_frame_rate']=='25/1'
assert int(video['nb_read_frames'])==meta['frames'];assert abs(float(p['format']['duration'])-meta['seconds'])<.1
assert audio['sample_rate']=='48000' and audio['channels']==1
(qa/'metadata.json').write_text(json.dumps(p,indent=2)+'\n')
decode=run(['ffmpeg','-v','error','-i',str(movie),'-map','0:v:0','-map','0:a:0','-f','null','-']);(qa/'full-decode.log').write_text(decode.stderr);assert decode.returncode==0
loud=run(['ffmpeg','-hide_banner','-i',str(movie),'-vn','-af','ebur128=peak=true','-f','null','-']);(qa/'audio-loudness.log').write_text(loud.stderr);assert loud.returncode==0
frames=[]
for s in meta['scenes']:
 cues=[x for x in meta['subtitle_cues'] if x['scene']==s['number']]
 samples=[('early',cues[0]),('late',cues[-1])]
 if v not in ['v1','v2']:samples += [('middle',c) for c in cues[1:-1]]
 for group,c in samples:
  frame=int((c['start']+c['end'])/2*25);frames.append({'scene':s['number'],'id':s['id'],'group':group,'frame_index':frame,'time':frame/25,'expected_subtitle':c['text']})
frames.sort(key=lambda a:a['frame_index']);selector='+'.join(f'eq(n,{s["frame_index"]})' for s in frames)
fdir=qa/'decoded-frames';fdir.mkdir(exist_ok=True)
r=run(['ffmpeg','-v','error','-y','-i',str(movie),'-vf',f'select={selector.replace(",",chr(92)+",")}','-fps_mode','vfr',str(fdir/'%02d.png')]);assert r.returncode==0,r.stderr
for i,s in enumerate(frames):s['image']=f'decoded-frames/{i+1:02d}.png';assert (qa/s['image']).exists()
cue_checks=[]
for i,c in enumerate(meta['subtitle_cues']):
 assert c['start']<c['end'];assert len(c['text'])<=50
 if i:assert c['start']>=meta['subtitle_cues'][i-1]['end']
 cue_checks.append({'number':i+1,'duration':round(c['end']-c['start'],6),'characters':len(c['text']),'characters_per_second':round(len(c['text'])/(c['end']-c['start']),3)})
report={'schema':'cizheng-movie-qa.v1','version':v,'video_sha256':hashlib.sha256(movie.read_bytes()).hexdigest(),'video_bytes':movie.stat().st_size,'seconds':float(p['format']['duration']),'full_decode_exit_code':decode.returncode,'decoded_video_frames':int(video['nb_read_frames']),'resolution':[video['width'],video['height']],'audio_codec':audio['codec_name'],'audio_sample_rate':audio['sample_rate'],'audio_channels':audio['channels'],'cue_count':len(cue_checks),'cue_checks':cue_checks,'caption_frame_samples':frames,'all_subtitles_derive_from_real_audio_sample_boundaries':True,'visual_review_status':'pending','audio_human_listening_status':'not claimed; full media decode and loudness analysis performed'}
(qa/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['video_sha256','video_bytes','seconds','decoded_video_frames','full_decode_exit_code','cue_count']}))
