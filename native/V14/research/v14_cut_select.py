#!/usr/bin/env python3
"""Pareto-select V14 true-scene-cut protected GOPs within a Nintendo-sized file.

Changed GOPs retain the original independent seek points and stereo layout.
Unchanged GOPs are reused verbatim from the decoder-checked V13 cache.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

import v13_adaptive_lab as lab
import v14_cut_lab as cut

HERE=Path(__file__).resolve().parent
BASE_FILE=HERE/'v13_release/Avatar_3D_MobiPEG_V13_Adaptive_Quality.moflex'
MAX_REFERENCE_SIZE=20588544


def select(budget_delta,cut_weight,max_nocut_regression_db=.20):
    base_rows=json.loads((HERE/'v13_release/V13_quality_45056_SELECTION.json').read_text())['selected_gops']
    baseline={r['index']:r for r in base_rows}
    original=json.loads((HERE/'v13_experiments/V13_TRIAL_RESULTS.json').read_text())
    new=json.loads((HERE/'v14_cut_lab/V14_ACTUAL_CUT_RESULTS.json').read_text())
    selected,groups=cut.reports()
    if set(selected)!=set(baseline) or len(groups)!=19 or len(new)!=19*len(cut.MODES):
        raise RuntimeError('Incomplete actual-cut experiment cache')
    baselines_cut={r['index']:r for r in new if r['variant']=='seed'}
    options=[]
    for idx in sorted(baseline):
        if idx in groups:
            candidates=[r for r in new if r['index']==idx]
        else:
            candidates=[r for r in original if r['index']==idx]
        b=baseline[idx]
        good=[]
        for r in candidates:
            if idx in groups and r['variant']=='coarse6_1':
                # Negative-control trial; never deliberately worsen a real cut.
                continue
            is_base=(r['file']==b['file']) if idx not in groups else r['variant']=='seed'
            if not is_base:
                if r['peak_1s_bytes']>max(b['peak_1s_bytes'],round(2701.392*1000/8)):continue
                if idx not in groups and r['psnr']<b['psnr']-max_nocut_regression_db:continue
                if r['psnr']<b['psnr']-.20 or r['ssim']<b['ssim']-.0014:continue
                if r['mse']>b['mse']*1.04+.6:continue
                if r['edge_mse']>b['edge_mse']*1.06+1.5:continue
                if r['grain']>b['grain']+.014:continue
                if r['flicker_mse']>b['flicker_mse']*1.07+1:continue
                if r['boundary_excess']>b['boundary_excess']+.06:continue
                if idx in groups and r['actual_postcut_mse']>baselines_cut[idx]['actual_postcut_mse']+.01:continue
            good.append(r)
        if idx in groups and not any(r['variant']=='seed' for r in good):
            raise RuntimeError(f'Lost GOP {idx} baseline')
        if idx not in groups and not any(r['file']==b['file'] for r in good):
            # Reuse the selected source row explicitly for an exact baseline.
            good.append(b)
        options.append(good)
    flat=[r for grp in options for r in grp]
    profit=[]
    for r in flat:
        idx=r['index'];b=baseline[idx];n=r['coded_frames']
        gain=n*((b['mse']-r['mse'])*.85+
                (b['edge_mse']-r['edge_mse'])*.014+
                (b['flicker_mse']-r['flicker_mse'])*.025+
                (b['grain']-r['grain'])*2.0+
                (b['boundary_excess']-r['boundary_excess'])*1.2)
        if idx in groups:
            control=baselines_cut[idx]
            gain+=cut_weight*(control['actual_postcut_mse']-r['actual_postcut_mse'])*r['actual_postcut_frames']
        profit.append(gain)
    payload=sum(r['video_bytes'] for r in base_rows)
    budget=payload+budget_delta
    A=lil_matrix((51,len(flat)),dtype=np.float64)
    idx_to_row={k:i for i,k in enumerate(sorted(baseline))}
    for j,r in enumerate(flat):
        A[idx_to_row[r['index']],j]=1
        A[50,j]=r['video_bytes']
    lower=np.r_[np.ones(50),0]
    upper=np.r_[np.ones(50),budget]
    ans=milp(-np.asarray(profit),integrality=np.ones(len(flat)),
             bounds=Bounds(np.zeros(len(flat)),np.ones(len(flat))),
             constraints=LinearConstraint(A.tocsr(),lower,upper),
             options={'time_limit':120,'mip_rel_gap':.0005})
    if ans.x is None:raise RuntimeError(f'Optimization failed: {ans.message}')
    chosen=sorted((flat[j] for j in range(len(flat)) if ans.x[j]>.5),key=lambda r:r['index'])
    assert len(chosen)==50
    chosen_size=sum(r['video_bytes'] for r in chosen)
    assert chosen_size<=budget
    changed=[r['index'] for r in chosen if r['index'] in groups and r['variant']!='seed']
    selected_cut=[r for r in chosen if r['index'] in groups]
    cut_frames=sum(r['actual_postcut_frames'] for r in selected_cut)
    before=sum(baselines_cut[r['index']]['actual_postcut_mse']*r['actual_postcut_frames']
               for r in selected_cut)/cut_frames
    after=sum(r['actual_postcut_mse']*r['actual_postcut_frames'] for r in selected_cut)/cut_frames
    return chosen,{'search_options':len(flat),'score':float(-ans.fun),
      'optimization_optimal':bool(ans.success),'video_payload_bytes':chosen_size,
      'video_budget_bytes':budget,'changed_cut_gops':changed,
      'number_cut_gops_improved':len(changed),
      'maximum_noncut_gop_psnr_regression_db':max_nocut_regression_db,
      'predicted_actual_postcut_mse_before':before,
      'predicted_actual_postcut_mse_after':after,
      'predicted_postcut_mse_reduction_pct':(before-after)/before*100,
      'mode_counts':dict(Counter(r['variant'] for r in chosen))}


def make(profile,extra,guard_db):
    weight={'balanced':3.0,'cutfocus':14.0}[profile]
    chosen,report=select(extra,weight,guard_db)
    out=HERE/'v14_release';out.mkdir(exist_ok=True)
    suffix=f'_Guard{round(guard_db*1000):03d}' if guard_db<.20 else ''
    movie=out/f'Avatar_3D_MobiPEG_V14_{profile}_CutGuard_Extra{extra}{suffix}.moflex'
    src=lab.LEGACY.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4'
    result=lab.mux(chosen,lab.ENC,src,None,out,movie,lab.PROBE)
    if result['file_bytes']>=MAX_REFERENCE_SIZE:
        raise RuntimeError('Exceeded official Nintendo size limit')
    decoded=out/(movie.stem+'_decoded.yuv')
    subprocess.run([str(lab.ENC),'-hide_banner','-nostdin','-v','error','-xerror',
         '-y','-i',str(movie),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo',str(decoded)],
         check=True,timeout=500)
    assert decoded.stat().st_size==4826*lab.FRAME_BYTES
    audio=subprocess.run([str(lab.ENC),'-hide_banner','-nostdin','-v','error',
         '-i',str(movie),'-map','0:a:0','-f','s16le','pipe:1'],
         capture_output=True,check=True,timeout=300).stdout
    report.update({'mux':result,'file':str(movie),'decoded_file':str(decoded),
                   'decoded_stereo_pairs':2413,'audio_bytes':len(audio),
                   'audio_sha256':hashlib.sha256(audio).hexdigest(),
                   'selected_gops':chosen})
    (out/f'V14_{profile}_{extra}{suffix}_SELECTION.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='selected_gops'},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['balanced','cutfocus'],default='cutfocus')
    p.add_argument('--extra',type=int,default=8000)
    p.add_argument('--max-nocut-regression-db',type=float,default=.20)
    a=p.parse_args()
    if not 0<=a.max_nocut_regression_db<=.20:raise ValueError('Invalid guard range')
    make(a.profile,a.extra,a.max_nocut_regression_db)
