#!/usr/bin/env python3
"""V15 Avatar stereo: independently verify V14 and re-optimize native MV R-D.

Never alters V14's source, GOPs, or MOFLEX deliverables. Reuses the EXACT
filtered raw scenes and paired-eye quantizer timelines used to build V14.
Control experiments must reproduce original V14 GOP bytes identically.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import Bounds,LinearConstraint,milp
from scipy.sparse import lil_matrix

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import v13_adaptive_lab as lab
import v14_cut_lab as cuts

OUTPUT=HERE/'v15_avatar_lab'
BASE_FILE=HERE/'v14_release/V14_cutfocus_0_Guard020_SELECTION.json'
MODES={
 'control':{},
 'mvref0':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'},
 'mvref8':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},
}


def selected_rows():
    b=json.loads(BASE_FILE.read_text())
    rows={r['index']:r for r in b['selected_gops']}
    if len(rows)!=50:raise RuntimeError('V14 release selection is incomplete')
    return rows


def qplan(idx,row):
    origin=Path(row['file'])
    if not origin.is_absolute():origin=HERE/origin
    folder=origin.parent.name
    if folder=='v14_cut_lab':
        plan=HERE/f'v14_cut_lab/q_{idx:03d}_{row["variant"]}.txt'
    elif folder=='v13_experiments':
        plan=HERE/f'v13_experiments/quant_{idx:03d}_{row["variant"]}.txt'
    else:raise RuntimeError(f'Unexpected GOP selection source: {origin}')
    if not plan.is_file():raise FileNotFoundError(plan)
    q=[int(x) for x in plan.read_text().split()]
    if len(q)!=row['coded_frames'] or q[0::2]!=q[1::2]:
        raise RuntimeError('Invalid stereo-paired V14 quantizer plan')
    return origin,plan


def trial(idx,mode,rows,groups):
    row=rows[idx]
    original_file,plan=qplan(idx,row)
    r12,env,extras,filtered,source=lab.params_for(idx,lab.load_reports())
    n=row['coded_frames']
    if source.stat().st_size!=n*lab.FRAME_BYTES:
        raise ValueError('Wrong source GOP dimensions')
    if filtered.stat().st_size!=n*lab.FRAME_BYTES:
        raise ValueError('Wrong filtered source GOP dimensions')
    OUT=OUTPUT/f'GOP_{idx:03d}'
    OUT.mkdir(parents=True,exist_ok=True)
    movie=OUT/f'GOP_{idx:03d}_{mode}.moflex'
    env['MOBI_V13_Q_PLAN']=str(plan)
    if mode!='control':env.update(MODES[mode])
    t=time.monotonic()
    if not movie.is_file():
        cmd=[lab.ENC,'-hide_banner','-nostdin','-v','error','-y',
            '-f','rawvideo','-pix_fmt','yuv420p','-video_size',f'{lab.W}x{lab.H}',
            '-framerate','48','-i',filtered,'-an','-c:v','mobiclip','-mobiclip','1',
            '-qp',str(r12['qp']),'-mobi_qyx',str(r12['qyx']),'-preset','medium',
            '-me_method','hex','-g',str(n),*extras,
            '-mo_layout','0','-f','moflex',movie]
        lab.run(cmd,env=env,timeout=300)
    if mode=='control' and hashlib.sha256(movie.read_bytes()).digest()!=hashlib.sha256(original_file.read_bytes()).digest():
        raise RuntimeError(f'V14 bit-exact control failed on GOP {idx}')
    decoded=lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error','-xerror',
             '-i',movie,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=180)
    if len(decoded)!=n*lab.FRAME_BYTES:raise RuntimeError(f'Bad decoded frame count GOP {idx}')
    packets=[int(x) for x in lab.run([lab.PROBE,'-v','error','-select_streams','v:0',
             '-show_entries','packet=size','-of','csv=p=0',movie]).split()]
    if len(packets)!=n:raise RuntimeError('Missing GOP packets')
    score=lab.metrics(source.read_bytes(),decoded,n=n)
    r={'index':idx,'variant':mode,'coded_frames':n,'file':str(movie),
       'video_bytes':sum(packets),'peak_1s_bytes':max(
           (sum(packets[i:i+48]) for i in range(0,n,48)),default=0),
       'seconds':round(time.monotonic()-t,3),
       'boundary_excess':lab.blockiness(source.read_bytes(),decoded,n),**score}
    if idx in groups:
        r.update(cuts.postcut_metrics(source.read_bytes(),decoded,idx,groups[idx],n))
    if mode=='control' and r['video_bytes']!=row['video_bytes']:
        raise RuntimeError(f'Wrong control packet bytes GOP {idx}')
    return r


def choose(rows,trials,groups,guard_db=.03):
    choices=[]
    baseline_bytes=sum(r['video_bytes'] for r in rows.values())
    # Nintendo's 20,588,544-byte comparison file is 18,432 bytes above
    # V14 Safe; leave 4 KiB room for variable MOFLEX container padding.
    payload_budget=baseline_bytes+14336
    for idx,base in sorted(rows.items()):
        possible=[r for r in trials if r['index']==idx and r['variant']!='control']
        good=[base]
        for r in possible:
            if r['psnr']<base['psnr']-guard_db:continue
            if r['ssim']<base['ssim']-.00035:continue
            if r['mse']>base['mse']*1.005:continue
            if r['edge_mse']>base['edge_mse']*1.017+.15:continue
            if r['grain']>base['grain']+.006:continue
            if r['flicker_mse']>base['flicker_mse']*1.025+.2:continue
            if r['peak_1s_bytes']>max(base['peak_1s_bytes'],337674):continue
            if idx in groups:
                if r['actual_postcut_mse']>base['actual_postcut_mse']+.02:continue
            good.append(r)
        choices.append(good)
    flat=[r for grp in choices for r in grp]
    ids=sorted(rows)
    A=lil_matrix((len(ids)+1,len(flat)),dtype=np.float64)
    objective=[]
    for j,r in enumerate(flat):
        base=rows[r['index']]
        A[ids.index(r['index']),j]=1
        A[len(ids),j]=r['video_bytes']
        # Source-fidelity objective weighted by GOP length; protected cuts
        # get an extra penalty if they regress even slightly.
        score=((r['mse']-base['mse'])+
               .014*(r['edge_mse']-base['edge_mse'])+
               .024*(r['flicker_mse']-base['flicker_mse'])+
               .03*(r['grain']-base['grain']))*r['coded_frames']
        if r['index'] in groups:
            score+=.9*(r['actual_postcut_mse']-base['actual_postcut_mse'])*r['actual_postcut_frames']
        objective.append(score)
    lower=np.r_[np.ones(len(ids)),0]
    upper=np.r_[np.ones(len(ids)),payload_budget]
    answer=milp(np.asarray(objective),integrality=np.ones(len(flat)),
                bounds=Bounds(np.zeros(len(flat)),np.ones(len(flat))),
                constraints=LinearConstraint(A.tocsr(),lower,upper),
                options={'time_limit':90,'mip_rel_gap':.00001})
    if answer.x is None:raise RuntimeError(f'V15 R-D optimizer failed: {answer.message}')
    out=sorted([r for j,r in enumerate(flat) if answer.x[j]>.5],key=lambda r:r['index'])
    if len(out)!=len(ids):raise RuntimeError('MILP dropped a GOP')
    improvements=[]
    for winner in out:
        idx=winner['index'];base=rows[idx]
        if winner is not base:
            improvements.append({'index':idx,'variant':winner['variant'],
                'mse_gain':base['mse']-winner['mse'],
                'saved_bytes':base['video_bytes']-winner['video_bytes']})
    if sum(r['video_bytes'] for r in out)>payload_budget:
        raise RuntimeError('Selection exceeded strict global video budget')
    return out,improvements


def final_build(rows,groups):
    report=OUTPUT/'V15_AVATAR_MV_TRIAL_RESULTS.json'
    trials=json.loads(report.read_text())
    selection,improvements=choose(rows,trials,groups)
    OUTPUT.mkdir(exist_ok=True)
    final=OUTPUT/'Avatar_3D_MobiPEG_V15_MotionRefine_EXPERIMENTAL.moflex'
    src=lab.LEGACY.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4'
    metadata=lab.mux(selection,lab.ENC,src,None,OUTPUT,final,lab.PROBE)
    if metadata['file_bytes']>=20588544:
        raise RuntimeError('V15 exceeds official Nintendo test file size')
    decoded=OUTPUT/'V15_Avatar_Full_Decoded.yuv'
    lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error','-xerror',
         '-y','-i',final,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo',decoded],timeout=800)
    if decoded.stat().st_size!=4826*lab.FRAME_BYTES:
        raise RuntimeError('V15 complete stereo decoder verification failed')
    audio=lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                '-i',final,'-map','0:a:0','-f','s16le','pipe:1'],timeout=450)
    baseline=HERE/'v14_release/Avatar_3D_MobiPEG_V14_cutfocus_CutGuard_Extra0_Guard020_decoded.yuv'
    source_raw=lab.LEGACY/'Avatar_eyes_400x224_48fps.yuv'
    n=4826
    reference=np.memmap(source_raw,dtype=np.uint8).reshape(n,lab.FRAME_BYTES)
    old=np.memmap(baseline,dtype=np.uint8).reshape(n,lab.FRAME_BYTES)
    new=np.memmap(decoded,dtype=np.uint8).reshape(n,lab.FRAME_BYTES)
    # Large files are scored in controlled chunks to bound peak memory.
    def quality(movie):
        sse=0.;sse_c=0.
        for start in range(0,n,48):
            o=reference[start:start+48].astype(np.float32)
            p=movie[start:start+48].astype(np.float32)
            sse+=float(np.sum((o[:,:lab.W*lab.H]-p[:,:lab.W*lab.H])**2))
            sse_c+=float(np.sum((o[:,lab.W*lab.H:]-p[:,lab.W*lab.H:])**2))
        mse=sse/(n*lab.W*lab.H)
        return {'luma_mse':mse,'luma_psnr':float(10*np.log10(255**2/mse)),
                'chroma_mse':sse_c/(n*lab.W*lab.H//2)}
    full={'v14_safe':quality(old),'v15_mvref':quality(new)}
    result={'final_file':str(final),'full_comparison':full,
            'movie':metadata,'changed_gops':improvements,'changed_count':len(improvements),
            'audio_pcm_sha256':hashlib.sha256(audio).hexdigest(),
            'audio_pcm_bytes':len(audio),'coded_frames':n}
    (OUTPUT/'V15_AVATAR_FINAL_REPORT.json').write_text(json.dumps(result,indent=2))
    print('FULL V15',json.dumps(result,indent=2),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--indices',nargs='*',type=int)
    p.add_argument('--modes',nargs='+',choices=MODES,default=['mvref0'])
    p.add_argument('--workers',type=int,default=5)
    p.add_argument('--build-final',action='store_true')
    args=p.parse_args()
    rows=selected_rows()
    _,groups=cuts.reports()
    if args.indices is None:indices=sorted(rows)
    else:indices=args.indices
    for idx in indices:
        if idx not in rows:raise ValueError(f'No selected GOP {idx}')
    OUTPUT.mkdir(exist_ok=True)
    report=OUTPUT/'V15_AVATAR_MV_TRIAL_RESULTS.json'
    old=json.loads(report.read_text()) if report.is_file() else []
    cache={(r['index'],r['variant']):r for r in old}
    jobs=[(idx,mode) for idx in indices for mode in args.modes
          if (idx,mode) not in cache]
    print('V15 AVATAR',len(jobs),'new GOP experiments',len(cache),'cached',flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(trial,idx,mode,rows,groups):(idx,mode) for idx,mode in jobs}
        for i,f in enumerate(as_completed(futures),1):
            r=f.result()
            cache[(r['index'],r['variant'])]=r
            report.write_text(json.dumps(sorted(cache.values(),key=lambda r:(r['index'],r['variant'])),indent=2))
            print(f'{i}/{len(jobs)} GOP {r["index"]:02d} {r["variant"]} '
                  f'bytes={r["video_bytes"]} PSNR={r["psnr"]:.4f}',flush=True)
    if args.build_final:final_build(rows,groups)


if __name__=='__main__':main()
