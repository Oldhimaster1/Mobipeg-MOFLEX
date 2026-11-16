#!/usr/bin/env python3
"""Test opt-in V11 source-edge-aware DC bias vs verified V10 GOPs.

Measures actual decoder output, including 4x4 block-border excess contrast.
Quality improvements are not assumed merely from a lower blockiness score.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from v9_full_reencode import VARIANTS, measure
from v10_full_reencode import MODES as V10_MODES, param_for
from v9_texture_sweep import FRAME_BYTES, H, W

ROOT=Path(__file__).resolve().parent
MODES={
    'reference':{},
    'mvrefine_p0':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'},
    'mvrefine_p8':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},
    'mvrefine_p24':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'24'},
    'mvrefine_p64':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'64'},
    'mvrefine_p128':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'128'},
    'mvrefine_axes':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'24',
                     'MOBI_V11_MV_DIAGONAL':'0'},
    'dc4c2':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'4','MOBI_V11_DC_CLAMP':'2'},
    'dc4c4':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'4','MOBI_V11_DC_CLAMP':'4'},
    'dc8c2':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'8','MOBI_V11_DC_CLAMP':'2'},
    'dc8c4':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'8','MOBI_V11_DC_CLAMP':'4'},
    'dc8c8':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'8','MOBI_V11_DC_CLAMP':'8'},
    'dc12c4':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'12','MOBI_V11_DC_CLAMP':'4'},
    'dc16c4':{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_STRENGTH':'16','MOBI_V11_DC_CLAMP':'4'},
}

def blockiness(frame):
    # Difference between 4x4 borders and non-borders after subtracting
    # the source's preexisting boundary statistics.
    dx=np.abs(np.diff(frame.astype(np.float32),axis=1))
    dy=np.abs(np.diff(frame.astype(np.float32),axis=0))
    bx=dx[:,np.arange(1,W)%4==0].mean()
    nx=dx[:,np.arange(1,W)%4!=0].mean()
    by=dy[np.arange(1,H)%4==0,:].mean()
    ny=dy[np.arange(1,H)%4!=0,:].mean()
    return float(((bx-nx)+(by-ny))/2)

def inspect(result,raw,encoder):
    p=subprocess.run([str(encoder),'-nostdin','-v','error','-xerror',
                      '-i',result['file'],'-map','0:v:0','-pix_fmt','yuv420p',
                      '-f','rawvideo','pipe:1'],capture_output=True,check=True)
    n=result['coded_frames']
    src=np.fromfile(raw,dtype=np.uint8).reshape(n,FRAME_BYTES)
    dec=np.frombuffer(p.stdout,dtype=np.uint8).reshape(n,FRAME_BYTES)
    if len(p.stdout)!=n*FRAME_BYTES:raise ValueError('Truncated V11 decoded frame')
    bsrc=[];bdec=[]
    for i in range(0,n,8):
        bsrc.append(blockiness(src[i,:W*H].reshape(H,W)))
        bdec.append(blockiness(dec[i,:W*H].reshape(H,W)))
    result['excess_block_boundary_contrast']=float(np.mean(bdec)-np.mean(bsrc))
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scenes',nargs='+',type=int,default=[5,12,19,34,41])
    ap.add_argument('--workers',type=int,default=7)
    ap.add_argument('--out',type=Path,default=ROOT/'v11_forensics/dc_trials')
    ap.add_argument('--encoder',type=Path,default=ROOT/'MobiPEG_Custom_V8/local/bin/ffmpeg')
    ap.add_argument('--probe',type=Path,default=ROOT/'MobiPEG_Custom_V8/local/bin/ffprobe')
    ap.add_argument('--modes',nargs='+',choices=list(MODES),default=list(MODES))
    a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    v9={r['index']:r for r in json.load(open(ROOT/'v9_full/V9_PEAK_CAPPED_REPORT.json'))['selected_gops']}
    v10={r['index']:r for r in json.load(open(ROOT/'v10_full/V10_MOTION_DETAIL_REPORT.json'))['selected_gops']}
    args=[]
    for idx in a.scenes:
        original=v9[idx]; baseline=v10[idx]
        mode=baseline['variant'].split('_',2)[2]
        env={**VARIANTS[original['variant']],**V10_MODES[mode][0]}
        row={'index':idx,'span':baseline['span'],'coded_frames':baseline['coded_frames'],
             'option':baseline['v8_option']}
        params=(baseline['qyx'],baseline['qp'],baseline['lambda_delta'],param_for(baseline))
        for trial in a.modes:
            key=f'v11_{idx}_{trial}'
            VARIANTS[key]={**env,**MODES[trial]}
            args.append((row,key,ROOT/f'v9_full/gop_{idx:03d}_source.yuv',
                         a.out/f'gop_{idx:03d}_{trial}.moflex',a.encoder,a.probe,params))
    t0=time.monotonic()
    tested=[];bad=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        f={pool.submit(measure,j):j for j in args}
        for i,done in enumerate(concurrent.futures.as_completed(f),1):
            inp=f[done]
            try:
                z=inspect(done.result(),inp[2],a.encoder)
                z['trial']=inp[1].split('_',2)[2]
                tested.append(z)
                (a.out/'v11_dc_candidate_results.json').write_text(json.dumps(
                    sorted(tested,key=lambda k:(k['index'],k['trial'])),indent=2))
                print(i,'/',len(args),'gop',z['index'],z['trial'],
                      'PSNR',round(z['psnr'],3),'size',z['video_bytes'],
                      'block-excess',round(z['excess_block_boundary_contrast'],4),flush=True)
            except Exception as e:
                bad.append({'gop':inp[0]['index'],'mode':inp[1],'error':str(e)})
                print('ERROR',bad[-1],flush=True)
    print('COMPLETE',len(tested),'in',round(time.monotonic()-t0,1),'seconds','errors',bad)
    for idx in a.scenes:
        seg=[z for z in tested if z['index']==idx]
        ref=next((z for z in seg if z['trial']=='reference'),None)
        if not ref:continue
        print('SCENE',idx,'V10 source-edge error',round(ref['edge_mse'],3),
              'PSNR',round(ref['psnr'],3),'block-excess',round(ref['excess_block_boundary_contrast'],3))
        for z in sorted((z for z in seg if z['trial']!='reference'),
                        key=lambda z:z['excess_block_boundary_contrast']):
            print('  ',z['trial'],'dPSNR',round(z['psnr']-ref['psnr'],4),
                  'dEdge%',round((z['edge_mse']/ref['edge_mse']-1)*100,2),
                  'dBytes%',round((z['video_bytes']/ref['video_bytes']-1)*100,2),
                  'dBlock',round(z['excess_block_boundary_contrast']-
                                 ref['excess_block_boundary_contrast'],3))

if __name__=='__main__':main()
