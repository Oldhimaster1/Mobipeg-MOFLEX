#!/usr/bin/env python3
"""V10 motion fix + detail reinvestment, decoder-verified at fixed V9 budget.

Each V9-selected source GOP is re-encoded with preserved real MVs and optional
finer qx/qyx or source-activity AC rounding. The knapsack optimizer spends
the recovered bytes where decoded image quality benefits most.
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

from v9_full_reencode import VARIANTS, measure, mux, select, run

MODES = {
    'mv0': ({'MOBI_V10_MV_SNAP':'0'}, 0, 0),
    'mv0_activity': ({'MOBI_V10_MV_SNAP':'0','MOBI_V10_ACTIVITY':'1',
                       'MOBI_V10_FLAT_OFFSET':'2','MOBI_V10_EDGE_OFFSET':'9'}, 0, 0),
    'mv0_qxfine': ({'MOBI_V10_MV_SNAP':'0'}, 0, -1),
    'mv0_qxfine_activity': ({'MOBI_V10_MV_SNAP':'0','MOBI_V10_ACTIVITY':'1',
                       'MOBI_V10_FLAT_OFFSET':'2','MOBI_V10_EDGE_OFFSET':'9'}, 0, -1),
    'mv0_qyfine': ({'MOBI_V10_MV_SNAP':'0'}, -1, 0),
    'mv0_qyfiner': ({'MOBI_V10_MV_SNAP':'0'}, -2, 0),
}

def param_for(row):
    option=row['v8_option']
    switches=[]
    if 'psyoff' in option:switches+=['-psy','0']
    if 'umh' in option:switches+=['-me_method','umh']
    if option=='nr10':switches+=['-noise_reduction','10']
    return switches

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile',type=Path,default=Path(__file__).parent/'v9_full/V9_PEAK_CAPPED_REPORT.json')
    ap.add_argument('--gop-folder',type=Path,default=Path(__file__).parent/'v9_full')
    ap.add_argument('--source',type=Path,default=Path(__file__).parent.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4')
    ap.add_argument('--encoder',type=Path,default=Path(__file__).parent/'MobiPEG_Custom_V8/local/bin/ffmpeg')
    ap.add_argument('--probe',type=Path,default=Path(__file__).parent/'MobiPEG_Custom_V8/local/bin/ffprobe')
    ap.add_argument('--out',type=Path,default=Path(__file__).parent/'v10_full')
    ap.add_argument('--workers',type=int,default=8)
    ap.add_argument('--mode',nargs='+',choices=list(MODES),default=list(MODES))
    ap.add_argument('--budget',type=int,default=None)
    ap.add_argument('--peak-1s-kbps',type=float,default=2897)
    ap.add_argument('--name',default='Avatar_3D_MobiPEG_V10_MotionDetail.moflex')
    ap.add_argument('--only',nargs='+',type=int,help='Selected GOP indices for pilot')
    ap.add_argument('--optimize-only',action='store_true')
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    base_report=json.loads(args.profile.read_text())
    original=sorted(base_report['selected_gops'],key=lambda z:z['index'])
    orig_profiles={r['index']:r for r in original}
    if args.only is not None:
        original=[orig_profiles[i] for i in args.only]
    budget=(args.budget if args.budget is not None else
            sum(z['video_bytes'] for z in original))

    # Fully decoded V9 reference candidates are immutable, verified anchors.
    baseline=[]
    tasks=[]
    for r in original:
        b={**r,'variant':'baseline','v9_selected_variant':r['variant']}
        baseline.append(b)
        for mode in args.mode:
            env, dy, dq=MODES[mode]
            qyx=r['qyx']+dy
            qp=r['qp']+dq
            if qyx<0 or qp<0:continue
            key=f'v10_{r["index"]}_{mode}'
            VARIANTS[key]={**VARIANTS[r['variant']],**env}
            row={'index':r['index'],'span':r['span'],'coded_frames':r['coded_frames'],
                 'option':r['v8_option']}
            source=args.gop_folder/f'gop_{r["index"]:03d}_source.yuv'
            out=args.out/f'gop_{r["index"]:03d}_{mode}.moflex'
            tasks.append((row,key,source,out,args.encoder,args.probe,
                          (qyx,qp,r['lambda_delta'],param_for(r))))
    # A reference is never silently replaced with a stale cached experiment.
    cache_path=args.out/'v10_candidate_results.json'
    sig_path=args.out/'v10_cache_signature.json'
    source_sig=hashlib.sha256(args.encoder.read_bytes()).hexdigest()
    signature={'encoder_sha256':source_sig,'v9_report_sha256':hashlib.sha256(args.profile.read_bytes()).hexdigest(),
               'modes':{key:[env,dy,dq] for key,(env,dy,dq) in MODES.items()},
               'source_gop_folder':str(args.gop_folder.resolve())}
    if sig_path.exists() and json.loads(sig_path.read_text())==signature:
        cached=json.loads(cache_path.read_text()) if cache_path.exists() else []
    else:
        cached=[]
        sig_path.write_text(json.dumps(signature,indent=2))
    completed={(z['index'],z['variant']):z for z in cached}
    todo=[t for t in tasks if (t[0]['index'],t[1]) not in completed]
    if args.optimize_only:todo=[]
    start=time.monotonic()
    failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(measure,t):t for t in todo}
        for i, future in enumerate(concurrent.futures.as_completed(futures),1):
            t=futures[future]
            try:
                z=future.result()
                completed[(z['index'],z['variant'])]=z
                cache_path.write_text(json.dumps(sorted(completed.values(),
                              key=lambda z:(z['index'],z['variant'])),indent=2))
                print(f'{i:03d}/{len(todo)} gop={z["index"]:02d} {z["variant"]} '
                      f'bytes={z["video_bytes"]} PSNR={z["psnr"]:.3f} '
                      f'SSIM={z["ssim"]:.5f}',flush=True)
            except Exception as e:
                failures.append((t[0]['index'],t[1],str(e)))
                print('FAILED',failures[-1],flush=True)
    print('Experiments complete',len(completed),'failure',len(failures),
          'wall seconds',round(time.monotonic()-start,1),flush=True)
    if failures:raise RuntimeError('One or more candidate encodes failed; refusing incomplete release')
    if args.only is not None:
        for b in baseline:
            variants=[z for z in completed.values() if z['index']==b['index']]
            winners=sorted(variants,key=lambda z:z['psnr'],reverse=True)
            print('PILOT',b['index'],'reference',b['video_bytes'],round(b['psnr'],3),
                  'best',[(z['variant'],z['video_bytes'],round(z['psnr'],3),round(z['ssim'],4))
                          for z in winners[:6]],flush=True)
        return

    full=list(baseline)+list(completed.values())
    required={(r['index'],f'v10_{r["index"]}_{m}') for r in original for m in args.mode
              if r['qyx']+MODES[m][1]>=0 and r['qp']+MODES[m][2]>=0}
    missing=required-set(completed)
    if missing:raise RuntimeError(f'Unmeasured candidates: {sorted(missing)[:10]}')
    # Original references have been independently measured before and carry
    # exactly the same quality metrics and packet sizes as candidate results.
    winners, refs, margin=select(full,budget,profile='texture',
                   peak_ceiling_bytes=int(args.peak_1s_kbps*1000/8),
                   grain_tolerance=.04)
    counts=collections.Counter(z['variant'].split('_',2)[-1] if z['variant']!='baseline'
                               else 'original_v9' for z in winners)
    print('V10 modes:',dict(counts),'V10 payload',sum(z['video_bytes'] for z in winners),
          'budget',budget,flush=True)
    outfile=args.out/args.name
    verified=mux(winners,args.encoder,args.source,None,args.out,outfile,args.probe)
    report={'experimental':True,'source_profile':str(args.profile),
            'v9_video_budget':budget,'V10_payload_bytes':sum(z['video_bytes'] for z in winners),
            'candidate_tests':len(completed),'tested_modes':args.mode,
            'selected_modes':dict(counts),'selected_gops':winners,
            'verified_output':verified,'hardware_validation':'PENDING Old 3DS test'}
    (args.out/'V10_MOTION_DETAIL_REPORT.json').write_text(json.dumps(report,indent=2))
    print('COMPLETE',json.dumps({'file':str(outfile),
          'bytes':verified['file_bytes'],'video_bytes':verified['video_bytes'],
          'sha256':verified['sha256'],'counts':counts},indent=2),flush=True)

if __name__=='__main__':main()
