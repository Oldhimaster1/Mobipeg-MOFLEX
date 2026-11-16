#!/usr/bin/env python3
"""Decoder-exact MobiClip motion search and quality reallocation (V11).

Builds from the actually verified V10 GOP selection. Tests alternative
MobiClip-specific halfpel motion vectors and finer quantizers per 2-second
region. The final R-D optimization must stay inside V10's video budget.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time

from v9_full_reencode import VARIANTS, measure, mux, select
from v10_full_reencode import MODES as V10_MODES, param_for

HERE=Path(__file__).resolve().parent
MODES={
    'mvsearch_p0': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'},0,0),
    'mvsearch_p8': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},0,0),
    'mvsearch_p24': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'24'},0,0),
    'mvsearch_p8_qxfine': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},0,-1),
    'mvsearch_p0_qxfine': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'},0,-1),
    'mvsearch_p8_qyfine': ({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},-1,0),
}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--v9-profile',type=Path,default=HERE/'v9_full/V9_PEAK_CAPPED_REPORT.json')
    ap.add_argument('--v10-profile',type=Path,default=HERE/'v10_full/V10_MOTION_DETAIL_REPORT.json')
    ap.add_argument('--gop-folder',type=Path,default=HERE/'v9_full')
    ap.add_argument('--source',type=Path,default=HERE.parent/'references/Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4')
    ap.add_argument('--encoder',type=Path,default=HERE/'MobiPEG_Custom_V8/local/bin/ffmpeg')
    ap.add_argument('--probe',type=Path,default=HERE/'MobiPEG_Custom_V8/local/bin/ffprobe')
    ap.add_argument('--out',type=Path,default=HERE/'v11_full')
    ap.add_argument('--workers',type=int,default=9)
    ap.add_argument('--modes',nargs='+',choices=list(MODES),default=list(MODES))
    ap.add_argument('--peak-1s-kbps',type=float,default=2783)
    ap.add_argument('--budget',type=int)
    ap.add_argument('--only',nargs='+',type=int)
    ap.add_argument('--optimize-only',action='store_true')
    ap.add_argument('--name',default='Avatar_3D_MobiPEG_V11_DecoderAware.moflex')
    a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    v9={z['index']:z for z in json.loads(a.v9_profile.read_text())['selected_gops']}
    v10={z['index']:z for z in json.loads(a.v10_profile.read_text())['selected_gops']}
    refs=[v10[i] for i in sorted(v10) if a.only is None or i in a.only]
    budget=a.budget if a.budget is not None else sum(z['video_bytes'] for z in refs)
    original=[];jobs=[]
    for r in refs:
        idx=r['index']
        prev=v9[idx]
        prior_mode=r['variant'].split('_',2)[2]
        previous_env={**VARIANTS[prev['variant']],**V10_MODES[prior_mode][0]}
        original.append({**r,'variant':'baseline','v10_mode':prior_mode})
        for name in a.modes:
            switches,dy,dq=MODES[name]
            qyx=r['qyx']+dy
            qp=r['qp']+dq
            if qyx<0 or qp<0:continue
            key=f'v11_{idx}_{name}'
            VARIANTS[key]={**previous_env,**switches}
            row={'index':idx,'span':r['span'],'coded_frames':r['coded_frames'],
                 'option':r['v8_option']}
            jobs.append((row,key,a.gop_folder/f'gop_{idx:03d}_source.yuv',
                         a.out/f'gop_{idx:03d}_{name}.moflex',a.encoder,a.probe,
                         (qyx,qp,r['lambda_delta'],param_for(r))))
    cache=a.out/'v11_decoder_verified_candidates.json'
    signature_path=a.out/'v11_cache_signature.json'
    signature={'encoder':hashlib.sha256(a.encoder.read_bytes()).hexdigest(),
               'v9':hashlib.sha256(a.v9_profile.read_bytes()).hexdigest(),
               'v10':hashlib.sha256(a.v10_profile.read_bytes()).hexdigest(),
               'gop_folder':str(a.gop_folder.resolve()),
               'modes':{k:[env,dy,dq] for k,(env,dy,dq) in MODES.items()}}
    if signature_path.exists() and json.loads(signature_path.read_text())==signature:
        cached=json.loads(cache.read_text()) if cache.exists() else []
    else:
        cached=[]
        signature_path.write_text(json.dumps(signature,indent=2))
    completed={(r['index'],r['variant']):r for r in cached}
    todo=[j for j in jobs if (j[0]['index'],j[1]) not in completed]
    if a.optimize_only:todo=[]
    bad=[]
    started=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(measure,j):j for j in todo}
        for i,future in enumerate(concurrent.futures.as_completed(futures),1):
            j=futures[future]
            try:
                z=future.result()
                completed[(z['index'],z['variant'])]=z
                cache.write_text(json.dumps(sorted(completed.values(),
                        key=lambda z:(z['index'],z['variant'])),indent=2))
                print(f'{i:03d}/{len(todo)} GOP={z["index"]:02d} '
                      f'{z["variant"]} bytes={z["video_bytes"]} '
                      f'PSNR={z["psnr"]:.3f} SSIM={z["ssim"]:.5f}',flush=True)
            except Exception as e:
                bad.append({'gop':j[0]['index'],'variant':j[1],'exception':str(e)})
                print('REJECT',bad[-1],flush=True)
    if bad:
        (a.out/'v11_failures.json').write_text(json.dumps(bad,indent=2))
        raise RuntimeError('Incomplete decoder-verified candidate search')
    expected={(j[0]['index'],j[1]) for j in jobs}
    if not expected<=set(completed):
        raise RuntimeError(f'Missing candidate verification: {sorted(expected-set(completed))[:8]}')
    print('V11 tested',len(completed),'candidates in',round(time.monotonic()-started,1),flush=True)
    if a.only is not None:
        for r in original:
            choices=[z for z in completed.values() if z['index']==r['index']]
            print('SCENE',r['index'],'reference',r['video_bytes'],r['psnr'],
                  [(z['variant'],z['video_bytes'],round(z['psnr'],3)) for z in choices],flush=True)
        return
    chosen,base,margin=select(original+list(completed.values()),budget,
          profile='texture',peak_ceiling_bytes=int(a.peak_1s_kbps*1000/8),
          grain_tolerance=.04)
    modes=collections.Counter(z['variant'].split('_',2)[-1] if z['variant']!='baseline'
                              else 'V10_baseline' for z in chosen)
    print('V11 selected',dict(modes),'payload',sum(z['video_bytes'] for z in chosen),
          'budget',budget,flush=True)
    path=a.out/a.name
    verified=mux(chosen,a.encoder,a.source,None,a.out,path,a.probe)
    report={'experimental':True,'source_v9':str(a.v9_profile),
            'source_v10':str(a.v10_profile),'test_count':len(completed),
            'target_video_bytes':budget,'selected_video_bytes':verified['video_bytes'],
            'selected_modes':dict(modes),'selected_gops':chosen,'verified_file':verified,
            'old3ds_hardware_test':'PENDING'}
    (a.out/'V11_DECODER_AWARE_REPORT.json').write_text(json.dumps(report,indent=2))
    print('COMPLETE',json.dumps({'file':str(path),'size':verified['file_bytes'],
          'video':verified['video_bytes'],'sha256':verified['sha256'],
          'modes':modes},indent=2),flush=True)

if __name__=='__main__':main()
