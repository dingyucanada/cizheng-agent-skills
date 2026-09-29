"""Recreate the original 193.12 second procedural score; no third-party music."""
from pathlib import Path
import argparse, hashlib, wave
import numpy as np
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
a.out.parent.mkdir(parents=True, exist_ok=True)
rate = 48000
sample = 4828 * (rate // 25)
total = sample / rate
t=np.arange(sample)/rate;music=np.zeros(sample,dtype=np.float64)
chords=[[146.832,220.,293.665,369.994],[123.471,184.997,246.942,293.665],[97.999,146.832,195.998,246.942],[110.,164.814,220.,277.183]]
for idx,start in enumerate(np.arange(0,total,5)):
 mask=(t>=start)&(t<start+5);u=t[mask]-start;env=(1-np.exp(-u*2))*np.exp(-u*.35)
 for k,f in enumerate(chords[idx%4]):music[mask]+=.005*np.sin(2*np.pi*f*u+idx*.2)*env
 # Quiet airy harmonic, deliberately below the spoken narration.
 music[mask]+=.0015*np.sin(2*np.pi*chords[idx%4][-1]*2*u)*env
music*=np.minimum(t/2,1)*np.minimum((total-t)/3,1)
with wave.open(str(a.out),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes((np.clip(music,-1,1)*32767).astype('<i2').tobytes())
print(hashlib.sha256(a.out.read_bytes()).hexdigest())
