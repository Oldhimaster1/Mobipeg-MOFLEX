#!/usr/bin/env python3
"""V14 scene-cut protection: optimize *actual* scene changes, not GOP starts.

Each candidate starts from the selected V13 Quality per-frame Q plan.  For
every true scene cut we test several protection durations/strengths.  Each
trial is independently decoded and scored against the original source.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import time

import numpy as np

import v13_adaptive_lab as lab

HERE=Path(__file__).resolve().parent
OUT=HERE/'v14_cut_lab'
MODES=('seed','cut2_1','cut6_1','cut6_2','cut12_1','cut12_2',
       'cut4_3_tail8_1','balanced6_2','balanced12_2','hold16_1','coarse6_1')


def reports():
    d=json.loads((HERE/'v13_release/V13_quality_45056_SELECTION.json').read_text())
    rows={r['index']:r for r in d['selected_gops']}
    audit=json.loads((HERE/'v13_audit_quality/V13_Quality_FULL_QUALITY_AUDIT.json').read_text())
    cuts=audit['scene_cut_frames']
    groups={}
    for idx,r in rows.items():
        inside=[cut for cut in cuts if idx*96<=cut<idx*96+r['coded_frames']]
        if inside:groups[idx]=inside
    if sum(map(len,groups.values()))!=len(cuts):
        raise ValueError('Scene cuts outside selected source GOPs')
    return rows,groups


def modify_plan(idx,row,cuts,mode,source):
    q=np.array([int(z) for z in (HERE/f'v13_experiments/quant_{idx:03d}_{row["variant"]}.txt').read_text().split()],dtype=np.int16)
    assert len(q)==row['coded_frames']
    assert np.all(q[0::2]==q[1::2])
    if mode=='seed':return q.astype(int).tolist()
    pairs=q[::2].copy()
    local=[(cut-idx*96)//2 for cut in cuts]
    for start in local:
        for t in range(start,len(pairs)):
            offset=t-start
            delta=0
            if mode=='cut2_1' and offset<2:delta=-1
            elif mode=='cut6_1' and offset<6:delta=-1
            elif mode=='cut6_2' and offset<6:delta=-2
            elif mode=='cut12_1' and offset<12:delta=-1
            elif mode=='cut12_2' and offset<12:delta=-2
            elif mode=='cut4_3_tail8_1':
                if offset<4:delta=-3
                elif offset<12:delta=-1
            elif mode=='balanced6_2' and offset<6:delta=-2
            elif mode=='balanced12_2' and offset<12:delta=-2
            elif mode=='hold16_1' and offset<16:delta=-1
            elif mode=='coarse6_1' and offset<6:delta=1
            pairs[t]+=delta
    if mode in ('balanced6_2','balanced12_2'):
        # Offset part of the additional cut cost only in slowly-changing
        # *same-eye* source areas, away from protected frames.
        n=len(pairs)
        pixels=np.frombuffer(source,np.uint8).reshape(row['coded_frames'],lab.FRAME_BYTES)[:,:lab.W*lab.H]
        mov=np.array([0 if j==0 else np.mean(np.abs(
            pixels[2*j:2*j+2].astype(np.int16)-pixels[2*j-2:2*j].astype(np.int16)))
            for j in range(n)])
        permitted=np.array([all(abs(j-start)>12 for start in local) for j in range(n)])
        threshold=float(np.percentile(mov,45))
        pairs[np.logical_and(mov<threshold,permitted)]+=1
    q=np.clip(np.repeat(pairs,2),12,59)
    assert np.all(q[::2]==q[1::2])
    return q.astype(int).tolist()


def postcut_metrics(src,dec,idx,cuts,n):
    a=np.frombuffer(src,np.uint8).reshape(n,lab.FRAME_BYTES)[:,:lab.W*lab.H]
    b=np.frombuffer(dec,np.uint8).reshape(n,lab.FRAME_BYTES)[:,:lab.W*lab.H]
    positions=sorted(set(j for cut in cuts for j in range(cut-idx*96,min(n,cut-idx*96+12))))
    if not positions:raise ValueError('No actual cut frames')
    dif=a[positions].astype(np.float32)-b[positions].astype(np.float32)
    return {'actual_postcut_mse':float(np.mean(dif*dif)),
            'actual_postcut_frames':len(positions),
            'first_cut_frame_mse':float(np.mean(dif[:1]**2)),
            'cut_frames_total_sse':float(np.sum(dif*dif))}


def trial(idx,mode,selected,cuts,reference):
    row=selected[idx]
    r12,env,extras,filtered,source=lab.params_for(idx,lab.load_reports())
    n=row['coded_frames']
    orig=source.read_bytes()
    base=filtered.read_bytes()
    if len(orig)!=n*lab.FRAME_BYTES or len(base)!=len(orig):raise ValueError('Invalid raw source')
    qp=modify_plan(idx,row,cuts,mode,orig)
    OUT.mkdir(exist_ok=True)
    path=OUT/f'gop_{idx:03d}_{mode}.moflex'
    qfile=OUT/f'q_{idx:03d}_{mode}.txt'
    qfile.write_text(''.join(f'{q}\n' for q in qp))
    env['MOBI_V13_Q_PLAN']=str(qfile)
    cmd=[lab.ENC,'-hide_banner','-nostdin','-v','error','-y',
        '-f','rawvideo','-pix_fmt','yuv420p','-video_size',f'{lab.W}x{lab.H}',
        '-framerate','48','-i',filtered,'-an','-c:v','mobiclip','-mobiclip','1',
        '-qp',str(r12['qp']),'-mobi_qyx',str(r12['qyx']),'-preset','medium',
        '-me_method','hex','-g',str(n)] + extras + [
        '-mo_layout','0','-f','moflex',path]
    t=time.monotonic()
    lab.run(cmd,env=env)
    dec=lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error','-xerror','-i',path,
       '-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
    if len(dec)!=n*lab.FRAME_BYTES:raise ValueError('Incomplete coded video')
    sizes=[int(z) for z in lab.run([lab.PROBE,'-v','error','-select_streams','v:0',
        '-show_entries','packet=size','-of','csv=p=0',path]).split()]
    if len(sizes)!=n:raise ValueError('Coded packet count mismatch')
    payload=sum(sizes)
    if mode=='seed' and payload!=row['video_bytes']:
        raise ValueError(f'V13 baseline mismatch GOP {idx}: {payload} != {row["video_bytes"]}')
    with reference.open('rb') as handle:
        handle.seek(idx*96*lab.FRAME_BYTES)
        v13=handle.read(n*lab.FRAME_BYTES)
    if mode=='seed' and dec!=v13:
        raise ValueError(f'V13 baseline pixel mismatch GOP {idx}')
    return {'index':idx,'variant':mode,'coded_frames':n,'file':str(path),
      'video_bytes':payload,
      'peak_1s_bytes':max((sum(sizes[i:i+48]) for i in range(0,n,48)),default=0),
      'actual_scene_cuts':cuts,
      'quant_changes_from_v13':sum(x!=y for x,y in zip(qp,modify_plan(idx,row,cuts,'seed',orig))),
      'seconds':round(time.monotonic()-t,3),
      **lab.metrics(orig,dec,n=n),
      **postcut_metrics(orig,dec,idx,cuts,n),
      'boundary_excess':lab.blockiness(orig,dec,n)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--modes',nargs='+',choices=MODES,default=list(MODES))
    p.add_argument('--indices',nargs='*',type=int)
    a=p.parse_args()
    selected,groups=reports()
    if a.indices is not None:groups={k:v for k,v in groups.items() if k in a.indices}
    cache=OUT/'V14_ACTUAL_CUT_RESULTS.json'
    if cache.exists():results=json.loads(cache.read_text())
    else:results=[]
    seen={(r['index'],r['variant']):r for r in results}
    jobs=[(idx,mode) for idx in sorted(groups) for mode in a.modes
           if (idx,mode) not in seen]
    print('TRUE CUTS',sum(len(v) for v in groups.values()),
          'GOPS',len(groups),'EXPERIMENTS',len(jobs),flush=True)
    reference=HERE/'v13_release/Avatar_3D_MobiPEG_V13_Adaptive_Quality.moflex.decoded.yuv'
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(trial,idx,mode,selected,groups[idx],reference):(idx,mode)
                 for idx,mode in jobs}
        for k,f in enumerate(concurrent.futures.as_completed(futures),1):
            r=f.result()
            seen[(r['index'],r['variant'])]=r
            cache.write_text(json.dumps(sorted(seen.values(),key=lambda z:(z['index'],z['variant'])),indent=2))
            print(f'{k:03d}/{len(jobs)} GOP={r["index"]:02d} {r["variant"]:20s} '
                  f'postcut_MSE={r["actual_postcut_mse"]:9.3f} payload={r["video_bytes"]}',flush=True)
    print('PASS',len(seen),'decoder-verified actual scene-cut candidate tests',flush=True)


if __name__=='__main__':main()
