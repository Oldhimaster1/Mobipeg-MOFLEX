#!/usr/bin/env python3
"""Select codec-verified MobiPEG adaptive quantizer GOPs at a strict size cap.

The choices use one option per original independently seekable V12 GOP, so the
experimental mux does not insert new dependence across scene boundaries.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from v13_adaptive_lab import HERE, LEGACY, ENC, PROBE, load_reports, mux


def permitted(row, base, ceiling):
    if row['variant']=='same':return True
    if row['peak_1s_bytes']>max(base['peak_1s_bytes'],ceiling):return False
    if row['psnr']<base['psnr']-.18:return False
    if row['ssim']<base['ssim']-.001:return False
    if row['mse']>base['mse']*1.028+.4:return False
    if row['edge_mse']>base['edge_mse']*1.055+2:return False
    if row['cut_mse']>base['cut_mse']*1.065+1:return False
    if row['flicker_mse']>base['flicker_mse']*1.08+1:return False
    if row['grain']>base['grain']+.015:return False
    if row['boundary_excess']>base['boundary_excess']+.08:return False
    return True


def reward(r,b,profile):
    n=r['coded_frames']
    # Magnitudes are weighted by *coded eye frames*.  PSNR must ultimately be
    # recomputed from pooled decoded MSE, never by averaging GOP dB values.
    if profile=='quality':
        return n*((b['mse']-r['mse'])*1.0 +
                  (b['edge_mse']-r['edge_mse'])*.015 +
                  (b['flicker_mse']-r['flicker_mse'])*.015 +
                  (b['grain']-r['grain'])*2.5 +
                  (b['boundary_excess']-r['boundary_excess'])*1.5)
    if profile=='smooth':
        return n*((b['mse']-r['mse'])*.82 +
                  (b['edge_mse']-r['edge_mse'])*.012 +
                  (b['flicker_mse']-r['flicker_mse'])*.05 +
                  (b['grain']-r['grain'])*9.0 +
                  (b['boundary_excess']-r['boundary_excess'])*4.5)
    raise ValueError(profile)


def choose(rows,extra,profile):
    groups={}
    for z in rows:groups.setdefault(z['index'],[]).append(z)
    keys=sorted(groups)
    baselines={key:next((z for z in groups[key] if z['variant']=='same'),None) for key in keys}
    if any(b is None for b in baselines.values()):raise ValueError('Missing a baseline')
    options=[r for idx in keys for r in groups[idx]
             if permitted(r,baselines[idx],round(2701.392*1000/8))]
    payload=sum(z['video_bytes'] for z in baselines.values())
    if len(keys)!=50 or sum(z['coded_frames'] for z in baselines.values())!=4826:
        raise ValueError('Incomplete 3D trailer')
    target=payload+extra
    # Exact integer byte constraint; no upward cost bucketing or rounding.
    objective=np.array([-reward(z,baselines[z['index']],profile) for z in options])
    A=lil_matrix((len(keys)+1,len(options)),dtype=np.float64)
    for j,z in enumerate(options):
        A[keys.index(z['index']),j]=1
        A[-1,j]=z['video_bytes']
    lo=np.array([1.]*len(keys)+[0.])
    hi=np.array([1.]*len(keys)+[float(target)])
    result=milp(objective,integrality=np.ones(len(options)),
                bounds=Bounds(np.zeros(len(options)),np.ones(len(options))),
                constraints=LinearConstraint(A.tocsr(),lo,hi),
                options={'time_limit':180,'mip_rel_gap':0.001})
    if result.x is None:raise RuntimeError(f'MILP selection failed: {result.message}')
    selected=sorted((options[i] for i in range(len(options)) if result.x[i]>.5),
                    key=lambda r:r['index'])
    if len(selected)!=len(keys):raise AssertionError('Selected duplicate GOP')
    size=sum(r['video_bytes'] for r in selected)
    if size>target:raise AssertionError('Payload over budget')
    return selected,{'feasible':bool(result.success),'message':result.message,
                     'baseline_video_bytes':payload,'video_budget_bytes':target,
                     'selected_video_bytes':size,
                     'selected_modes':dict(Counter(r['variant'] for r in selected)),
                     'weighted_objective':float(-result.fun),'candidate_count':len(options)}


def create(profile,extra):
    source=LEGACY/'v13'  # no external dependency; resolve below
    cache=HERE/'v13_experiments/V13_TRIAL_RESULTS.json'
    trials=json.loads(cache.read_text())
    reports=load_reports()
    if len(trials)!=len(reports[3])*12:
        raise RuntimeError(f'Expected {len(reports[3])*12} verified candidates; got {len(trials)}')
    selected,description=choose(trials,extra,profile)
    out=HERE/'v13_release';out.mkdir(exist_ok=True)
    title=('Avatar_3D_MobiPEG_V13_Adaptive_Lean.moflex' if not extra else
           'Avatar_3D_MobiPEG_V13_Adaptive_Smooth.moflex' if profile=='smooth' else
           'Avatar_3D_MobiPEG_V13_Adaptive_Quality.moflex')
    final=out/title
    source=LEGACY.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4'
    verified=mux(selected,ENC,source,None,out,final,PROBE)
    n=sum(row['coded_frames'] for row in selected)
    assert n==4826 and verified['file_bytes']<20588544
    # Full-file decode and audio equality are independent of per-GOP tests.
    decoded=out/(title+'.decoded.yuv')
    subprocess.run([str(ENC),'-hide_banner','-nostdin','-v','error','-xerror',
                    '-y','-i',str(final),'-map','0:v:0','-pix_fmt','yuv420p',
                    '-f','rawvideo',str(decoded)],check=True,timeout=500)
    assert decoded.stat().st_size==4826*400*224*3//2
    aud=out/(title+'.audio.pcm')
    subprocess.run([str(ENC),'-hide_banner','-nostdin','-v','error','-xerror',
                    '-y','-i',str(final),'-map','0:a:0','-f','s16le',str(aud)],
                   check=True,timeout=500)
    description.update({'video_file':str(final),'verified_mux':verified,
                        'decoded_eye_frames':4826,'decoded_stereo_pairs':2413,
                        'decoded_audio_bytes':aud.stat().st_size,
                        'decoded_audio_sha256':hashlib.sha256(aud.read_bytes()).hexdigest(),
                        'selected_gops':selected})
    (out/f'V13_{profile}_{extra}_SELECTION.json').write_text(json.dumps(description,indent=2))
    print(json.dumps({k:v for k,v in description.items() if k!='selected_gops'},indent=2),flush=True)
    return final


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['quality','smooth'],default='quality')
    p.add_argument('--extra',type=int,default=45056)
    a=p.parse_args()
    create(a.profile,a.extra)
