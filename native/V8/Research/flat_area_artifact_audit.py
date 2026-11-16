#!/usr/bin/env python3
"""Measure reconstructed high-frequency luma energy in source-flat regions.
This is a descriptive ringing/grain proxy, NOT a proven perceptual score."""
from pathlib import Path
import numpy as np,cv2,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt,json
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research';W,H=400,224;N=4826;F=W*H*3//2
p={'Original MP4 normalized':R/'MobiPEG_V5_RateControl/tests/avatar_eyes_24fps.yuv',
   'Nintendo official':R/'MobiPEG_V5_RateControl/tests/full_decoded_official.yuv',
   'MobiPEG V7':R/'MobiPEG_V7_Engineering/bench/V7_decoded_400x224_eyes.yuv',
   'MobiPEG V8':D/'V8_full_decoded.yuv'}
a={k:np.memmap(v,dtype='u1',mode='r').reshape(N,F)[:,:W*H].reshape(N,H,W) for k,v in p.items()}
vals={k:[] for k in p}
for t in range(0,N,24):
 for idx in (t,t+1):
  if idx>=N:continue
  src=a['Original MP4 normalized'][idx];q=src.astype(np.int16)
  grad=np.abs(np.diff(q,axis=1,prepend=q[:,:1]))+np.abs(np.diff(q,axis=0,prepend=q[:1,:]))
  mask=grad<12
  if np.count_nonzero(mask)<500:continue
  for k in p:
   b=a[k][idx];blur=cv2.GaussianBlur(b,(3,3),0.6)
   hf=float(np.abs(b.astype(np.float32)-blur.astype(np.float32))[mask].mean());vals[k].append(hf)
report={'sampled_eye_frames':len(next(iter(vals.values()))),'high_frequency_energy_in_source_flat_regions':{k:float(np.mean(v)) for k,v in vals.items()},'interpretation':'Higher small-scale residual can indicate ringing, grain, or real detail; not automatically perceptually worse.'}
(D/'Flat_Region_Texture_Energy.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
fig,ax=plt.subplots(figsize=(10,5))
nam=list(p);xx=np.arange(len(nam));scores=[np.mean(vals[k]) for k in nam]
ax.bar(xx,scores);ax.set_xticks(xx);ax.set_xticklabels(nam,rotation=12,ha='right');ax.set_ylabel('Average 3×3 high-frequency luma deviation in source-flat areas');ax.set_title('Proxy for grain/ringing: identical source-flat pixel masks, 402 sampled eye frames');ax.grid(alpha=.15,axis='y');
for i,z in enumerate(scores):ax.text(i,z+.01,f'{z:.3f}',ha='center')
fig.tight_layout();fig.savefig(D/'Flat_Region_Grain_Proxy.png',dpi=160)
