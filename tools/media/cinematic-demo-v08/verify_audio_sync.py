"""Cross-check saved narration cue audio against the actual decoded AAC film."""
from pathlib import Path
import subprocess,json,wave,sys
import numpy as np
b=Path(__file__).resolve().parent;v=sys.argv[1] if len(sys.argv)>1 else 'v2';out=b/v;q=out/'qa';meta=json.loads((out/'cizheng-demo-v07.json').read_text())
subprocess.run(['ffmpeg','-v','error','-y','-i',str(out/'cizheng-demo-v07.mp4'),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(q/'decoded-audio.wav')],check=True)
with wave.open(str(q/'decoded-audio.wav')) as w:film=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
receipts=[]
for cue in meta['subtitle_cues']:
 stem=Path(cue['voice_file']).stem
 with wave.open(str(b/(f'audio-converted-{v}' if v not in ['v1','v2'] else 'audio-converted')/f'{stem}.wav')) as w:ref=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
 # Find a high-energy 0.5s segment, then compare against the actual movie ±120ms.
 width=min(24000,len(ref));positions=range(0,max(1,len(ref)-width),4800)
 start=max(positions,key=lambda a:float(np.mean(ref[a:a+width]**2)))
 signal=ref[start:start+width:12];expected=round(cue['start']*48000)+start;pad=5760
 chunk=film[max(0,expected-pad):expected+width+pad:12]
 corr=np.correlate(chunk,signal,mode='valid');power=np.convolve(chunk**2,np.ones(len(signal)),mode='valid');denom=np.sqrt(np.maximum(power,1)*sum(signal**2));score=corr/denom
 offset=int(np.argmax(score));lag=(offset*12-pad)/48000;best=float(score[offset]);assert abs(lag)<.035 and best>.85,(cue,lag,best)
 receipts.append({'scene':cue['scene'],'cue_start':cue['start'],'text':cue['text'],'decoded_aac_to_original_narration_alignment_seconds':lag,'normalized_correlation':round(best,6)})
report={'method':'Actual AAC decoded at48kHz; per-cue highest-energy0.5s window cross-correlated against original narration PCM with ±120ms search, downsampled4kHz for analysis','cue_count':len(receipts),'all_pass':True,'maximum_absolute_offset_seconds':max(abs(r['decoded_aac_to_original_narration_alignment_seconds'])for r in receipts),'minimum_correlation':min(r['normalized_correlation']for r in receipts),'receipts':receipts}
(q/'audio-sync-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k]for k in ['cue_count','all_pass','maximum_absolute_offset_seconds','minimum_correlation']}))
