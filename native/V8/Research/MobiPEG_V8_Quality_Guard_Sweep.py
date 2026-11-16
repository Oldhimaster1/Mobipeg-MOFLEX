#!/usr/bin/env python3
"""Search Pareto-safe stereo GOP allocation; do not accept losses to structural, edge or cut metrics."""
from pathlib import Path
import numpy as np,math,json,collections,sys
ROOT=Path('/mnt/data');D=ROOT/'MobiPEG_V8_Research';BASE=ROOT/'MobiPEG_V7_Engineering/bench'
old=json.loads((BASE/'candidate_detail_metrics.json').read_text())+json.loads((BASE/'lambda2_gop_candidates.json').read_text())
long=json.loads((D/'candidates_4sec.json').read_text())
g=[[] for i in range(51)]
for x in old:
 z={**x,'span':1,'ssim_both':x['mean_ssim_both']};g[z['index']].append(z)
for x in long:
 if x['index']<50 and x['coded_frames']==192:g[x['index']].append(x)
sel=json.loads((BASE/'cut_0.15_guard_2_selected.json').read_text());bykey={(x['index'],x['option']):x for options in g for x in options}
orig=[bykey[(x['index'],x['option'])] for x in sel];budget=sum(x['video_bytes'] for x in orig)

def aggregate(x):
 n=sum(z['coded_frames'] for z in x);av=lambda k:sum(z[k]*z['coded_frames'] for z in x)/n
 cut=[z for z in x if z['cut_count']]
 cutm=sum(z['cut_mean_mse']*z['cut_frames'] for z in cut)/max(1,sum(z['cut_frames'] for z in cut))
 return {'video_bytes':sum(z['video_bytes'] for z in x),'GOPs':len(x),'longGOPs':sum(z['span']==2 for z in x),'PSNR_Y':10*math.log10(65025/av('mse_y')),'SSIM':av('ssim_both'),'edge_mse':av('edge_mse'),'worst_mse':av('worst_8th_mse'),'cut_mse':cutm}
BASEMET=aggregate(orig)
STEP=512;CAP=budget//STEP

def optimize(weights):
 # normalized feature magnitudes based on observed video, not arbitrary raw coefficients
 wy,ws,we,wc,ww=weights
 score={}
 for rows in g:
  for z in rows:
   key=(z['index'],z['option'],z['span']);n=z['coded_frames'];y=z['mse_y']
   score[key]=n*(wy*y+ws*(1-z['ssim_both'])*220+we*z['edge_mse']*.27+ww*z['worst_8th_mse']+wc*max(0,z['cut_mean_mse']-y)*(z['cut_frames']/n))
 dp=np.full((52,CAP+1),np.inf)
 pre_v=np.full((52,CAP+1),-1,dtype=np.int16)
 pre_b=np.full((52,CAP+1),-1,dtype=np.int32)
 pre_o=np.full((52,CAP+1),-1,dtype=np.int16)
 dp[0,0]=0
 for i in range(51):
  for j,z in enumerate(g[i]):
   to=i+z['span'];delta=math.ceil(z['video_bytes']/STEP)
   if to>51 or delta>CAP:continue
   vals=dp[i,:CAP-delta+1]+score[(z['index'],z['option'],z['span'])]
   tgt=dp[to,delta:];mask=vals<tgt
   if mask.any():
    tgt[mask]=vals[mask]
    ids=np.flatnonzero(mask)+delta;pre_v[to,ids]=i;pre_b[to,ids]=ids-delta;pre_o[to,ids]=j
 k=int(np.argmin(dp[51]));i=51;chosen=[]
 if not np.isfinite(dp[51,k]):raise RuntimeError('no feasible')
 while i:
  j=int(pre_o[i,k]);prev=int(pre_v[i,k]);chosen.append(g[prev][j]);k=int(pre_b[i,k]);i=prev
 chosen.reverse();return chosen

# The search is deliberately broad but deterministic and replayable.
weights=[(1,0,0,0,0),(.6,.15,.14,.15,0),(.35,.45,.12,.08,0),(.5,.3,.2,0,0),(.45,.2,.25,.1,0),(.5,.15,.2,.15,0),(.4,.3,.1,.2,0),(.5,.22,.13,.1,.05),(.4,.2,.2,.15,.05),(.4,.25,.25,.05,.05),(.35,.28,.23,.09,.05),(.4,.35,.15,.1,0),(.4,.25,.1,.2,.05),(.3,.30,.20,.15,.05),(.65,.1,.1,.15,0),(.4,.15,.15,.25,.05),(.42,.30,.18,.06,.04)]
allres=[]
for j,w in enumerate(weights):
 z=optimize(w);metrics=aggregate(z)
 diff={'PSNR':metrics['PSNR_Y']-BASEMET['PSNR_Y'],'SSIM':metrics['SSIM']-BASEMET['SSIM'],'edge':BASEMET['edge_mse']-metrics['edge_mse'],'cut':BASEMET['cut_mse']-metrics['cut_mse'],'worst':BASEMET['worst_mse']-metrics['worst_mse']}
 ok=diff['PSNR']>=-.001 and diff['SSIM']>=-0.00002 and diff['edge']>=-.01 and diff['cut']>=-.02 and diff['worst']>=-.01
 res={'test':j,'weights':w,'metrics':metrics,'delta':diff,'all_metrics_nondegrading':ok}
 allres.append(res)
 print('TEST',j,'PSNR',round(diff['PSNR'],4),'SSIM',round(diff['SSIM'],6),'edge',round(diff['edge'],3),'cut',round(diff['cut'],3),'worst',round(diff['worst'],3),'LONG',metrics['longGOPs'],'OK',ok,flush=True)
 (D/f'V8_SWEEP_{j:02d}_selected.json').write_text(json.dumps([{k:y[k] for k in ('index','span','option','file','video_bytes','coded_frames')} for y in z],indent=2))
 (D/'V8_OPTIMIZER_SWEEP.json').write_text(json.dumps({'V7':BASEMET,'sweep':allres},indent=2))
print('PARETO_PASS',[(x['test'],x['delta']) for x in allres if x['all_metrics_nondegrading']],flush=True)
