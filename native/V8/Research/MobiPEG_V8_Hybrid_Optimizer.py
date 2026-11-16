#!/usr/bin/env python3
"""MobiPEG V8 experimental hybrid-GOP measured rate/distortion allocator.
Combines 2-second V7 stereo GOPs with verified 4-second independent GOPs.
Includes V7 candidates, so the new optimizer never has to select an inferior
long-GOP candidate; every chosen output is independently decodable.
"""
from pathlib import Path
import numpy as np,json,math,collections,subprocess,hashlib,os,time
ROOT=Path('/mnt/data');D=ROOT/'MobiPEG_V8_Research';D.mkdir(exist_ok=True)
BASE=ROOT/'MobiPEG_V7_Engineering/bench';Q=ROOT/'MobiPEG_V7_Engineering/outputs'
original=json.loads((BASE/'candidate_detail_metrics.json').read_text())+json.loads((BASE/'lambda2_gop_candidates.json').read_text())
long=json.loads((D/'candidates_4sec.json').read_text()); graph=[[] for i in range(51)]; allrows=[]
for x in original:
 x=dict(x);x['span']=1;x['ssim_both']=x['mean_ssim_both'];allrows.append(x)
for x in long:
 if x['index']<50 and x['coded_frames']==192:
  allrows.append(dict(x))
for x in allrows:
 n=x['coded_frames'];x['cost']=n*(0.60*x['mse_y']+0.15*(1-x['ssim_both'])*220+0.14*x['edge_mse']*.27+0.11*(x['cut_mean_mse'] if x['cut_count'] else x['worst_8th_mse']))
 if not Path(x['file']).exists():continue
 graph[x['index']].append(x)
selected_orig=json.loads((BASE/'cut_0.15_guard_2_selected.json').read_text());selkey={(x['index'],x['option']):x for x in allrows}
origrows=[selkey[(z['index'],z['option'])] for z in selected_orig]
budget=sum(z['video_bytes'] for z in origrows)
step=512;cap=budget//step
print('candidate graph',sum(len(z) for z in graph),'original GOP count',len(origrows),'budget',budget,'cap',cap,flush=True)
def aggregate(rows):
 n=sum(x['coded_frames'] for x in rows);acc=lambda key:sum(x[key]*x['coded_frames'] for x in rows)/n
 cut=[x for x in rows if x['cut_count']]; cutm=sum(x['cut_mean_mse']*x['cut_frames'] for x in cut)/max(1,sum(x['cut_frames'] for x in cut))
 return {'GOPs':len(rows),'coded_eye_frames':n,'video_bytes':sum(x['video_bytes'] for x in rows),'PSNR_Y':round(10*math.log10(65025/acc('mse_y')),6),'SSIM_sampled':round(acc('ssim_both'),6),'edge_mse':round(acc('edge_mse'),5),'after_scene_cut_mse':round(cutm,5),'worst12p5_frame_mse':round(acc('worst_8th_mse'),4),'long_4sec_GOPs':sum(x['span']==2 for x in rows),'score':round(sum(x['cost'] for x in rows),3)}
print('V7 measured selection',aggregate(origrows),flush=True)
# Byte bucket rounds UP to keep exact payload within budget even in the worst case.
dp=np.full((52,cap+1),np.inf,dtype=np.float64)
previous_v=np.full((52,cap+1),-1,dtype=np.int16)
previous_b=np.full((52,cap+1),-1,dtype=np.int32)
prev_opt=np.full((52,cap+1),-1,dtype=np.int16)
dp[0,0]=0
for i in range(51):
 for j,x in enumerate(graph[i]):
  to=i+x['span'];d=math.ceil(x['video_bytes']/step)
  if d>cap:continue
  vals=dp[i,:cap-d+1]+x['cost'];target=dp[to,d:];mask=vals<target
  if mask.any():
   target[mask]=vals[mask]
   offsets=np.flatnonzero(mask)+d
   previous_v[to,offsets]=i
   previous_b[to,offsets]=offsets-d
   prev_opt[to,offsets]=j
 if i%10==0:print('DP positions',i,'reachable',np.isfinite(dp[i]).sum(),flush=True)
if not np.isfinite(dp[51]).any():raise RuntimeError('no solution')
bs=int(np.argmin(dp[51]));i=51;rows=[]
while i>0:
 j=int(prev_opt[i,bs]);prev=int(previous_v[i,bs]);before=int(previous_b[i,bs])
 if j<0 or prev<0:raise RuntimeError('broken traceback')
 rows.append(graph[prev][j]);i=prev;bs=before
rows.reverse();summary={'V7_baseline':aggregate(origrows),'V8_hybrid':aggregate(rows),'official_file_bytes':20588544,'hardware_tested':False}
print('V8 result',summary['V8_hybrid'],flush=True)
print('selected long GOPs',[(r['index'],r['option']) for r in rows if r['span']==2],flush=True)
assert summary['V8_hybrid']['video_bytes']<=budget
assert sum(r['coded_frames'] for r in rows)==4826
(D/'V8_OPTIMIZATION.json').write_text(json.dumps(summary,indent=2))
(D/'V8_SELECTED.json').write_text(json.dumps([{k:r[k] for k in ('index','option','file','span','coded_frames','video_bytes','mse_y','ssim_both','edge_mse')} for r in rows],indent=2))
# Reuse known-good V7 audio from original source and DO NOT change codec algorithm.
manifest=D/'V8_COMBINE.ffconcat'
manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{Path(r['file']).resolve()}'\nduration {r['coded_frames']/48:.9f}\n" for r in rows))
