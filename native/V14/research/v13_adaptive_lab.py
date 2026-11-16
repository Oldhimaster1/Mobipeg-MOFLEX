#!/usr/bin/env python3
"""Reproducible MobiPEG V13 scene-wise, stereo-paired quantizer experiment.

Uses the V12 full test suite as a source for exact flags and normalized eye
frames.  Every output is checked against the independent MOFLEX decoder.
This study is trailer-specific; the Q plan codec patch is more general.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

LEGACY = Path('/workspace/scratch/2571fa6fb025/work')
HERE = Path(__file__).resolve().parent
ENC = HERE / 'MobiPEG_V13_work/local/bin/ffmpeg'
PROBE = HERE / 'MobiPEG_V13_work/local/bin/ffprobe'
sys.path.insert(0, str(LEGACY))
from v9_full_reencode import VARIANTS, mux
from v10_full_reencode import MODES as M10, param_for
from v11_full_reencode import MODES as M11
from v9_texture_sweep import FRAME_BYTES, H, W, metrics
from v12_full_reencode import blockiness

ALL_MODES = ('same', 'fine1', 'coarse1', 'motion', 'motion2', 'gradient',
             'gradient2', 'error', 'error2', 'scene', 'stable', 'peak')


def run(cmd, env=None, timeout=150):
    p = subprocess.run([str(z) for z in cmd], capture_output=True,
                       timeout=timeout, env=env)
    if p.returncode:
        raise RuntimeError(f'cmd failed with {p.returncode}: {p.stderr[-1600:].decode(errors="replace")}')
    return p.stdout


def load_reports():
    def sel(name):
        return {int(z['index']):z for z in
                json.loads((LEGACY / name).read_text())['selected_gops']}
    return (sel('v9_full/V9_PEAK_CAPPED_REPORT.json'),
            sel('v10_full/V10_MOTION_DETAIL_REPORT.json'),
            sel('v11_full/V11_DECODER_AWARE_REPORT.json'),
            sel('v12_full/V12_SMOOTH_REPORT.json'))


def params_for(idx, reports):
    r9, r10, r11, r12 = (report[idx] for report in reports)
    env = dict(os.environ)
    env.update({'MOBI_SUBME':'9', 'MOBI_SKIP':'0', 'MOBI_QYX_RDO':'0',
                'MOBI_INTRA_RD_CAP':'0', 'MOBI_RDO_PRED_COST':'0',
                'MOBI_RDO_LAMBDA_DELTA':str(r12['lambda_delta'])})
    for key in ('MOBI_DZ', 'MOBI_CHROMA_DZ', 'MOBI_V9_INTER_LUMA_DZ',
                'MOBI_V9_INTER_FLAT_RANGE', 'MOBI_V9_FLAT_DZ',
                'MOBI_V9_FLAT_RANGE', 'MOBI_V9_FLAT_INTRA',
                'MOBI_V13_Q_PLAN', 'MOBI_V13_Q_TRACE'):
        env.pop(key,None)
    env9 = VARIANTS[r9['variant']]
    env10 = M10[r10['variant'].split('_',2)[-1]][0]
    env11 = M11[r11['variant'].split('_',2)[-1]][0]
    env.update(env9)
    env.update(env10)
    env.update(env11)
    if r12['variant'].startswith('v12_'):
        mode = r12['variant'].split('_',2)[-1]
        filtered = LEGACY / f'v12_full/gop_{idx:03d}_{mode}.yuv'
    else:
        filtered = LEGACY / f'v9_full/gop_{idx:03d}_source.yuv'
    unfiltered = LEGACY / f'v9_full/gop_{idx:03d}_source.yuv'
    if not filtered.is_file():
        raise FileNotFoundError(filtered)
    return r12, env, param_for(r10), filtered, unfiltered


def centered_rank(x):
    order = np.argsort(np.argsort(np.asarray(x,dtype=np.float64)))
    return (order.astype(np.float64)+.5)/len(order)


def plans(filtered_bytes, original_bytes, v12_bytes, n, qbase):
    raw=np.frombuffer(original_bytes,np.uint8).reshape(n,FRAME_BYTES)[:,:W*H].reshape(n,H,W)
    rec=np.frombuffer(v12_bytes,np.uint8).reshape(n,FRAME_BYTES)[:,:W*H].reshape(n,H,W)
    f=np.frombuffer(filtered_bytes,np.uint8).reshape(n,FRAME_BYTES)[:,:W*H].reshape(n,H,W)
    pairs=n//2
    # Lightweight pair-averaged features, each comparison with the SAME eye
    # 2 coded frames earlier to avoid treating stereo disparity as movement.
    motion=[]; edge=[]; err=[]; scene=[]; flat=[]
    for j in range(pairs):
        i=2*j
        a=raw[i:i+2].astype(np.float32)
        b=rec[i:i+2].astype(np.float32)
        c=f[i:i+2].astype(np.float32)
        err.append(float(np.mean((a-b)**2)))
        edge.append(float(np.mean(np.abs(np.diff(c,axis=1))) + np.mean(np.abs(np.diff(c,axis=2)))))
        flat.append(float(np.mean(np.abs(np.diff(c,axis=2))<4)))
        if i>=2:
            last=raw[i-2:i].astype(np.float32)
            difference=np.mean(np.abs(a-last),axis=(1,2))
            motion.append(float(difference.mean()))
            scene.append(float(np.mean((a-last)**2)))
        else:
            motion.append(0.)
            scene.append(0.)
    rm=centered_rank(motion)
    re=centered_rank(edge)
    rr=centered_rank(err)
    rs=centered_rank(scene)
    rf=centered_rank(flat)
    base=int(qbase)
    def choice(name,j):
        if name=='same': return base
        if name=='fine1': return base-1
        if name=='coarse1':return base+1
        if name=='motion':return base-1 if rm[j]>.64 else base+1 if rm[j]<.36 else base
        if name=='motion2':return base-2 if rm[j]>.83 else base+1 if rm[j]<.54 else base
        if name=='gradient':return base-1 if re[j]>.64 else base+1 if re[j]<.36 else base
        if name=='gradient2':return base-2 if re[j]>.85 else base+1 if re[j]<.54 else base
        if name=='error':return base-1 if rr[j]>.64 else base+1 if rr[j]<.36 else base
        if name=='error2':return base-2 if rr[j]>.82 else base+1 if rr[j]<.54 else base
        if name=='scene':return base-2 if rs[j]>.94 else base-1 if rs[j]>.73 else base+1 if rs[j]<.40 else base
        if name=='stable':return base-1 if (re[j]+rm[j])>.97 else base+1 if rf[j]>.7 else base
        if name=='peak':return base-2 if (rr[j]+re[j]+rm[j])>2.46 else base+1 if (rr[j]+re[j]+rm[j])<1.30 else base
        raise ValueError(name)
    return {mode: [int(np.clip(choice(mode,j),12,59)) for j in range(pairs) for _ in range(2)]
            for mode in ALL_MODES}


def experiment(idx,mode,reports):
    output=HERE/'v13_experiments'
    baseline,env,extra,rawpath,sourcepath=params_for(idx,reports)
    n=baseline['coded_frames']
    content=rawpath.read_bytes()
    original=sourcepath.read_bytes()
    if n*FRAME_BYTES!=len(content) or len(original)!=len(content):
        raise ValueError(f'Invalid source byte count for GOP {idx}')
    # V12 software reconstruction is the anchor for error-driven allocation.
    v12_decoded=(LEGACY/'v12_full/smoothfocus_decoded.yuv')
    with v12_decoded.open('rb') as inp:
        inp.seek(idx*96*FRAME_BYTES)
        rec12=inp.read(n*FRAME_BYTES)
    if len(rec12)!=len(content):raise ValueError('Missing V12 reconstruction')
    # V12 can request -qp 11; x264 clamps that to 12 before writing the
    # Mobiclip remainder.  Use actual emitted Q, not un-clamped CLI Q.
    qbase = 12+6*int(baseline['qyx'])+(max(12,int(baseline['qp']))%6)
    seq=plans(content,original,rec12,n,qbase)[mode]
    qfile=output/f'quant_{idx:03d}_{mode}.txt'
    qfile.write_text(''.join(f'{q}\n' for q in seq))
    target=output/f'gop_{idx:03d}_{mode}.moflex'
    env['MOBI_V13_Q_PLAN']=str(qfile)
    args=([ENC,'-hide_banner','-nostdin','-v','error','-y',
          '-f','rawvideo','-pix_fmt','yuv420p','-video_size',f'{W}x{H}',
          '-framerate','48','-i',rawpath,'-an',
          '-c:v','mobiclip','-mobiclip','1', '-qp',str(baseline['qp']),
          '-mobi_qyx',str(baseline['qyx']),'-preset','medium',
          '-me_method','hex','-g',str(n)] + extra +
         ['-mo_layout','0','-f','moflex',target])
    t=time.monotonic()
    run(args,env=env)
    decoded=run([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                 '-i',target,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
    if len(decoded)!=n*FRAME_BYTES:
        raise ValueError(f'Decoded {len(decoded)//FRAME_BYTES} frames, wanted {n}')
    sizes=run([PROBE,'-v','error','-select_streams','v:0',
               '-show_entries','packet=size','-of','csv=p=0',target])
    packets=[int(x) for x in sizes.split()]
    if len(packets)!=n: raise ValueError('Packet count mismatch')
    if mode=='same' and sum(packets)!=baseline['video_bytes']:
        raise ValueError(f'Baseline mismatch GOP {idx}: {sum(packets)} != {baseline["video_bytes"]}')
    score=metrics(original,decoded,n=n)
    report={'index':idx,'variant':mode,'coded_frames':n,'file':str(target),
            'video_bytes':sum(packets),
            'peak_1s_bytes':max((sum(packets[i:i+48]) for i in range(0,n,48)),default=0),
            'qbase':qbase,'mean_quantizer':float(np.mean(seq)),
            'changed_quantizer_frames':sum(q!=qbase for q in seq),
            'seconds':round(time.monotonic()-t,3),
            'boundary_excess':blockiness(original,decoded,n),**score}
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--indices',nargs='*',type=int,default=None)
    p.add_argument('--modes',nargs='*',choices=ALL_MODES,default=list(ALL_MODES))
    a=p.parse_args()
    out=HERE/'v13_experiments';out.mkdir(exist_ok=True)
    cache=out/'V13_TRIAL_RESULTS.json'
    rows=json.loads(cache.read_text()) if cache.exists() else []
    found={(r['index'],r['variant']):r for r in rows}
    reports=load_reports()
    if a.indices is None:
        a.indices=sorted(reports[3])
    jobs=[(idx,mode) for idx in a.indices for mode in a.modes if (idx,mode) not in found]
    print('RUN',len(jobs),'CACHED',len(found),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending={pool.submit(experiment,idx,mode,reports):(idx,mode) for idx,mode in jobs}
        for i,f in enumerate(concurrent.futures.as_completed(pending),1):
            key=pending[f]
            row=f.result()
            found[(row['index'],row['variant'])]=row
            cache.write_text(json.dumps(sorted(found.values(),key=lambda r:(r['index'],r['variant'])),indent=2))
            print(f'{i:4d}/{len(jobs)} GOP {key[0]:02d} {key[1]:12s} '+
                  f'{row["video_bytes"]:7d} bytes PSNR {row["psnr"]:7.3f} dB',flush=True)
    print('PASS',len(found),'decoder-verified trials',flush=True)

if __name__=='__main__':main()
