#!/usr/bin/env python3
"""V12: stereo-safe perceptual smoothness plus bitrate-neutral detail search.

Every candidate is decoded and compared against the *unfiltered* source.
Temporal filtering is forbidden because coded source eye frames alternate.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import numpy as np

from v9_full_reencode import VARIANTS, measure, mux
from v10_full_reencode import MODES as V10_MODES, param_for
from v11_full_reencode import MODES as V11_MODES
from v9_texture_sweep import FRAME_BYTES, H, W, metrics

HERE=Path(__file__).resolve().parent
MODES={
 'bilateral': ('bilateral=sigmaS=1.2:sigmaR=0.035:planes=1',0),
 'bilateral_qpfine': ('bilateral=sigmaS=1.2:sigmaR=0.035:planes=1',-1),
 'hq_medium': ('hqdn3d=1.4:1.8:0:0',0),
 'hq_medium_qpfine': ('hqdn3d=1.4:1.8:0:0',-1),
 'bilat_mid': ('bilateral=sigmaS=1.7:sigmaR=0.06:planes=1',0),
 'bilat_mid_qpfine': ('bilateral=sigmaS=1.7:sigmaR=0.06:planes=1',-1),
 'bilat_strong': ('bilateral=sigmaS=2.2:sigmaR=0.09:planes=1',0),
 'bilat_strong_qpfine': ('bilateral=sigmaS=2.2:sigmaR=0.09:planes=1',-1),
}

def blockiness(src,dst,n):
    ss=np.frombuffer(src,np.uint8).reshape(n,FRAME_BYTES)[:,:W*H].reshape(n,H,W)
    dd=np.frombuffer(dst,np.uint8).reshape(n,FRAME_BYTES)[:,:W*H].reshape(n,H,W)
    def excess(x):
        x=x.astype(np.float32)
        d=np.abs(np.diff(x,axis=2));e=np.abs(np.diff(x,axis=1))
        return float(((d[:,:,np.arange(1,W)%4==0].mean()-d[:,:,np.arange(1,W)%4!=0].mean())+
                      (e[:,np.arange(1,H)%4==0,:].mean()-e[:,np.arange(1,H)%4!=0,:].mean()))/2)
    return excess(dd)-excess(ss)

def run(cmd,timeout=300):
    x=subprocess.run([str(z) for z in cmd],capture_output=True,timeout=timeout)
    if x.returncode:raise RuntimeError((x.stderr or b'')[-1600:].decode(errors='replace'))
    return x.stdout

def job(j):
    row, mode, original, filtered, outfile, enc, probe, v9env, v10env, v11env, extras=j
    source=Path(original).read_bytes()
    chosen_filter,qpdelta=MODES[mode]
    run(['ffmpeg','-hide_banner','-nostdin','-v','error','-y',
       '-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224',
       '-framerate','48','-i',original,'-vf',chosen_filter,
       '-pix_fmt','yuv420p','-f','rawvideo',filtered],timeout=240)
    name=f'v12_{row["index"]}_{mode}'
    VARIANTS[name]={**v9env,**v10env,**v11env}
    z=measure(({'index':row['index'],'span':row['span'],
                'coded_frames':row['coded_frames'],'option':row['v8_option']},
          name,filtered,outfile,enc,probe,
          (row['qyx'],row['qp']+qpdelta,row['lambda_delta'],extras)))
    rec=run([enc,'-hide_banner','-nostdin','-v','error','-xerror',
       '-i',outfile,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=150)
    n=row['coded_frames']
    if len(rec)!=len(source) or len(rec)!=n*FRAME_BYTES:
        raise ValueError('Decoder frame count mismatch')
    return {**z,**metrics(source,rec,n=n),'variant':name,
            'boundary_excess':blockiness(source,rec,n),
            'input_filter':chosen_filter,'qp_delta':qpdelta}

def optimize(baselines,candidates,budget,peak_bytes,profile='balanced'):
    groups=collections.defaultdict(list)
    for z in candidates:groups[z['index']].append(z)
    options=[]
    smooth=profile=='smooth'
    for b in baselines:
        acceptable=[(b,0.,0)]
        for z in groups[b['index']]:
            # Reject perceptual improvement claims paid for by lost sharpness,
            # unstable image quality or disproportionate bitrate peaks.
            if (z['psnr']<b['psnr']-(.5 if smooth else .22) or
                z['ssim']<b['ssim']-(.0035 if smooth else .0017) or
                z['edge_mse']>b['edge_mse']*(1.095 if smooth else 1.055)+1.0 or
                z['cut_mse']>b['cut_mse']*(1.12 if smooth else 1.07)+1 or
                z['flicker_mse']>b['flicker_mse']*(1.18 if smooth else 1.13)+1 or
                z['boundary_excess']>b['boundary_excess']+(.04 if smooth else .06) or
                (z['peak_1s_bytes']>peak_bytes and z['peak_1s_bytes']>b['peak_1s_bytes'])):
                continue
            psnr_gain=z['psnr']-b['psnr']
            grain_gain=(b['grain']-z['grain'])/max(.2,b['grain'])
            boundary_gain=(b['boundary_excess']-z['boundary_excess'])/max(.2,abs(b['boundary_excess']))
            edge_gain=(b['edge_mse']-z['edge_mse'])/max(1,b['edge_mse'])
            flicker_gain=(b['flicker_mse']-z['flicker_mse'])/max(1,b['flicker_mse'])
            score=psnr_gain*(.38 if smooth else .55)+grain_gain*(8.5 if smooth else 5.0)+\
                boundary_gain*(3.5 if smooth else 2.0)+edge_gain*.30+flicker_gain*.18
            if score<=.001:continue
            delta=z['video_bytes']-b['video_bytes']
            acceptable.append((z,score,delta))
        options.append(acceptable)
    gran=512
    margin=budget-sum(b['video_bytes'] for b in baselines)
    if margin<0:raise ValueError('Budget less than V11 baseline')
    suffix_min=[0]*(len(options)+1)
    for i in range(len(options)-1,-1,-1):
        suffix_min[i]=suffix_min[i+1]+min(math.ceil(d/gran) for _,_,d in options[i])
    states={0:(0.,[])}
    for idx,variants in enumerate(options):
        nxt={}
        for cost,(value,rows) in states.items():
            for z,score,delta in variants:
                key=cost+math.ceil(delta/gran)
                if key+suffix_min[idx+1]>margin//gran:continue
                new_value=value+score
                if key not in nxt or new_value>nxt[key][0]:
                    nxt[key]=(new_value,rows+[z])
        states={}
        best=-1.e30
        for cost,candidate in sorted(nxt.items()):
            if candidate[0]>best+1e-7:
                states[cost]=candidate
                best=candidate[0]
        print('Selecting',idx+1,'/',len(options),'states',len(states),flush=True)
        if not states:raise RuntimeError('No feasible bitrate selection')
    best=max((v for k,v in states.items() if k*gran<=margin),key=lambda t:t[0])
    chosen=best[1]
    assert sum(z['video_bytes'] for z in chosen)<=budget
    return chosen,best[0]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--v9-profile',type=Path,default=HERE/'v9_full/V9_PEAK_CAPPED_REPORT.json')
    ap.add_argument('--v10-profile',type=Path,default=HERE/'v10_full/V10_MOTION_DETAIL_REPORT.json')
    ap.add_argument('--v11-profile',type=Path,default=HERE/'v11_full/V11_DECODER_AWARE_REPORT.json')
    ap.add_argument('--source',type=Path,default=HERE.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4')
    ap.add_argument('--gop-folder',type=Path,default=HERE/'v9_full')
    ap.add_argument('--encoder',type=Path,default=HERE/'MobiPEG_Custom_V8/local/bin/ffmpeg')
    ap.add_argument('--probe',type=Path,default=HERE/'MobiPEG_Custom_V8/local/bin/ffprobe')
    ap.add_argument('--workers',type=int,default=9)
    ap.add_argument('--modes',nargs='+',choices=list(MODES),default=list(MODES))
    ap.add_argument('--out',type=Path,default=HERE/'v12_full')
    ap.add_argument('--name',default='Avatar_3D_MobiPEG_V12_SmoothDetail.moflex')
    ap.add_argument('--budget',type=int,default=15777000)
    ap.add_argument('--peak-1s-kbps',type=float,default=2782.552)
    ap.add_argument('--profile',choices=['balanced','smooth'],default='balanced')
    ap.add_argument('--optimize-only',action='store_true')
    a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    v9={r['index']:r for r in json.loads(a.v9_profile.read_text())['selected_gops']}
    v10={r['index']:r for r in json.loads(a.v10_profile.read_text())['selected_gops']}
    base=json.loads(a.v11_profile.read_text())['selected_gops']
    work=[]
    for row in base:
        idx=row['index']
        prior=v10[idx]
        env9=VARIANTS[v9[idx]['variant']]
        env10=V10_MODES[prior['variant'].split('_',2)[-1]][0]
        env11=V11_MODES[row['variant'].split('_',2)[-1]][0]
        extras=param_for(prior)
        for mode in a.modes:
            work.append((row,mode,a.gop_folder/f'gop_{idx:03d}_source.yuv',
                  a.out/f'gop_{idx:03d}_{mode}.yuv',
                  a.out/f'gop_{idx:03d}_{mode}.moflex',a.encoder,a.probe,
                  env9,env10,env11,extras))
    cache=a.out/'V12_CANDIDATES.json'
    signature={'encoder':hashlib.sha256(a.encoder.read_bytes()).hexdigest(),
          'v11':hashlib.sha256(a.v11_profile.read_bytes()).hexdigest(),
          'modes':a.modes,'filters':MODES,'source':str(a.source.resolve())}
    signfile=a.out/'V12_CACHE_SIGNATURE.json'
    old_signature=json.loads(signfile.read_text()) if signfile.exists() else {}
    # Extend the same decoder-checked sweep without rerunning previously
    # validated modes. Existing individual filter definitions must match.
    same_base=all(old_signature.get(k)==signature[k] for k in ('encoder','v11','source'))
    safe_filters=all(json.dumps(signature['filters'].get(k))==json.dumps(v)
                     for k,v in old_signature.get('filters',{}).items())
    cached=(json.loads(cache.read_text()) if cache.exists() and same_base and safe_filters else [])
    signfile.write_text(json.dumps(signature,indent=2))
    seen={(z['index'],z['variant']):z for z in cached}
    todo=[j for j in work if (j[0]['index'],f'v12_{j[0]["index"]}_{j[1]}') not in seen]
    started=time.monotonic()
    if not a.optimize_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
            pending={pool.submit(job,j):j for j in todo}
            for i,f in enumerate(concurrent.futures.as_completed(pending),1):
                z=f.result()
                seen[(z['index'],z['variant'])]=z
                cache.write_text(json.dumps(sorted(seen.values(),key=lambda z:(z['index'],z['variant'])),indent=2))
                print(f'{i}/{len(todo)} GOP={z["index"]} {z["variant"]} bytes={z["video_bytes"]} '
                      f'PSNR={z["psnr"]:.3f} grain={z["grain"]:.3f}',flush=True)
    if len(seen)<len(work):raise RuntimeError(f'Only {len(seen)} of {len(work)} candidates verified')
    print('Decoder-verified',len(seen),'in',round(time.monotonic()-started,1),'seconds',flush=True)
    for row in base:
        original=(a.gop_folder/f'gop_{row["index"]:03d}_source.yuv').read_bytes()
        existing=Path(row['file'])
        if not existing.is_absolute(): existing=HERE.parent/existing
        decoded=run([a.encoder,'-hide_banner','-nostdin','-v','error','-xerror',
             '-i',existing,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=150)
        row['boundary_excess']=blockiness(original,decoded,row['coded_frames'])
    # Peak 1-second bitrate stays below V11's measured hardware test limit.
    chosen,score=optimize(base,list(seen.values()),a.budget,int(a.peak_1s_kbps*1000/8),a.profile)
    modes=collections.Counter(z['variant'].split('_',2)[-1] if z['variant']!='baseline' else 'V11'
                              for z in chosen)
    file=a.out/a.name
    verified=mux(chosen,a.encoder,a.source,None,a.out,file,a.probe)
    report={'experimental':True,'candidates_tested':len(seen),'budget':a.budget,
        'profile':a.profile,
        'selected_modes':dict(modes),'smoothness_score':score,'selected_gops':chosen,
        'verified_file':verified,'old3ds_hardware_test':'PENDING',
        'warning':'Experimental smoothness-biased R-D. Hardware and subjective tests required.'}
    (a.out/f'V12_{a.profile.upper()}_REPORT.json').write_text(json.dumps(report,indent=2))
    print('DONE',json.dumps({'size':verified['file_bytes'],'video_bytes':verified['video_bytes'],
          'modes':dict(modes),'sha256':verified['sha256']},indent=2),flush=True)

if __name__=='__main__':main()
