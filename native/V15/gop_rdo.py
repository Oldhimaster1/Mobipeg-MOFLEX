#!/usr/bin/env python3
"""Multi-scene MobiPEG R-D optimizer using *actual* decoded GOP trials.

Each independent one-second GOP is encoded at several quantizers, decoded
again, and compared to the same unfiltered source. A mixed integer program
chooses the lowest-distortion combination under the exact *video payload*
of the all-Q30 control. Final joined MOFLEX and frames are decoder-verified.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.optimize import Bounds,LinearConstraint,milp
from scipy.sparse import lil_matrix
from quality_sweep import ROOT,ENC,PROBE,FRAME_BYTES,W,H,CLIPS,prepare,command,source_metrics,q_to_flags

OUT=ROOT/'gop_rdo'


def segments(name,span=24):
    source=prepare(name)
    n=source.stat().st_size//FRAME_BYTES
    folder=OUT/name
    folder.mkdir(parents=True,exist_ok=True)
    src=np.memmap(source,dtype=np.uint8).reshape(n,FRAME_BYTES)
    jobs=[]
    for idx,start in enumerate(range(0,n,span)):
        count=min(span,n-start)
        raw=folder/f'GOP_{idx:03d}_input.yuv'
        if not raw.is_file():src[start:start+count].tofile(raw)
        if raw.stat().st_size!=count*FRAME_BYTES:
            raise RuntimeError('Incomplete raw GOP')
        jobs.append((idx,count,raw))
    return jobs


def test(name,idx,count,raw,q):
    output=OUT/name/f'GOP_{idx:03d}_Q{q}.moflex'
    t=time.monotonic()
    if not output.is_file():
        env={**os.environ,'MOBI_SUBME':'9','MOBI_SKIP':'0'}
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
                 '-f','rawvideo','-pix_fmt','yuv420p','-s',f'{W}x{H}',
                 '-framerate','24','-i',raw,'-an','-c:v','mobiclip',
                 '-mobiclip','1',*q_to_flags(q),'-preset','medium',
                 '-me_method','hex','-g',str(count),'-mo_layout','6',
                 '-f','moflex',output],env=env,timeout=240)
    rec=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                 '-i',output,'-map','0:v:0','-pix_fmt','yuv420p',
                 '-f','rawvideo','pipe:1'],timeout=180)
    if len(rec)!=count*FRAME_BYTES:raise RuntimeError('Wrong decoded GOP length')
    packet_raw=command([PROBE,'-v','error','-select_streams','v:0',
                  '-show_entries','packet=size','-of','csv=p=0',output])
    packets=[int(x) for x in packet_raw.split()]
    if len(packets)!=count:raise RuntimeError('Wrong encoded GOP packet count')
    original=np.memmap(raw,dtype=np.uint8).reshape(count,FRAME_BYTES)
    decoded=np.frombuffer(rec,np.uint8).reshape(count,FRAME_BYTES)
    return {'clip':name,'gop':idx,'q':q,'coded_frames':count,
            'video_bytes':sum(packets),'file_bytes':output.stat().st_size,
            'path':str(output),'seconds':round(time.monotonic()-t,3),
            **source_metrics(original,decoded)}


def optimize(name,span=24,base=30,guard=.20):
    report=OUT/name/'GOP_RDO_TRIALS.json'
    trials=json.loads(report.read_text())
    groups={}
    for t in trials:groups.setdefault(t['gop'],[]).append(t)
    if not groups:raise ValueError('No GOP trials')
    indices=sorted(groups)
    baseline={g:next((r for r in groups[g] if r['q']==base),None) for g in indices}
    if not all(baseline.values()):raise ValueError('Missing GOP control')
    budget=sum(x['video_bytes'] for x in baseline.values())
    allowed=[]
    for g in indices:
        b=baseline[g]
        opts=[]
        for r in groups[g]:
            if r['luma_psnr']<b['luma_psnr']-guard:continue
            if r['edge_mse']>b['edge_mse']*1.075+1:continue
            if r['ssim']<b['ssim']-.002:continue
            opts.append(r)
        if not opts:raise RuntimeError(f'No permissible options for GOP {g}')
        allowed.append(opts)
    rows=[item for group in allowed for item in group]
    A=lil_matrix((len(indices)+1,len(rows)),dtype=float)
    reward=[]
    for i,item in enumerate(rows):
        A[indices.index(item['gop']),i]=1
        A[len(indices),i]=item['video_bytes']
        # Summing MSE across GOPs gives true whole-movie PSNR optimum.
        weight=item['coded_frames']
        distortion=weight*(item['luma_mse']+0.035*item['edge_mse']+
                           0.12*item['chroma_mse'])
        reward.append(distortion)
    low=np.r_[np.ones(len(indices)),0]
    high=np.r_[np.ones(len(indices)),budget]
    ans=milp(np.asarray(reward),integrality=np.ones(len(rows)),
         bounds=Bounds(np.zeros(len(rows)),np.ones(len(rows))),
         constraints=LinearConstraint(A.tocsr(),low,high),
         options={'time_limit':120,'mip_rel_gap':.00001})
    if ans.x is None:raise RuntimeError(f'Cannot optimize: {ans.message}')
    chosen=sorted((rows[i] for i,x in enumerate(ans.x) if x>.5),key=lambda x:x['gop'])
    if len(chosen)!=len(indices):raise RuntimeError('MILP omitted a GOP')
    video_bytes=sum(r['video_bytes'] for r in chosen)
    if video_bytes>budget:raise RuntimeError('Optimizer exceeded video budget')
    def total_psnr(items):
        mse=sum(t['luma_mse']*t['coded_frames'] for t in items)/sum(t['coded_frames'] for t in items)
        return float(10*np.log10(255**2/mse))
    chosen_name=OUT/name/f'{name}_V15_RDO_Q{base}.moflex'
    control_name=OUT/name/f'{name}_V15_Control_Q{base}.moflex'
    for selection,dest in ((chosen,chosen_name),(list(baseline.values()),control_name)):
        if dest.exists():continue
        concat=OUT/name/(dest.stem+'.ffconcat')
        def quoting(s):return "'"+str(Path(s).resolve()).replace("'","'\\''")+"'"
        concat.write_text('ffconcat version 1.0\n'+''.join(
           f'file {quoting(item["path"])}\nduration {item["coded_frames"]/24:.9f}\n'
           for item in selection))
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
            '-f','concat','-safe','0','-i',concat,'-map','0:v:0',
            '-c:v','copy','-mo_layout','6','-f','moflex',dest],timeout=200)
    def decode_checks(dest):
        data=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                '-i',dest,'-map','0:v:0','-pix_fmt','yuv420p',
                '-f','rawvideo','pipe:1'],timeout=300)
        n=sum(z['coded_frames'] for z in chosen)
        if len(data)!=n*FRAME_BYTES:raise RuntimeError(f'Final joined frame count mismatch {dest}')
        packet_data=command([PROBE,'-v','error','-select_streams','v:0',
                  '-show_entries','packet=size','-of','csv=p=0',dest])
        p=[int(z) for z in packet_data.split()]
        if len(p)!=n:raise RuntimeError('Missing concat packets')
        ref=np.memmap(prepare(name),dtype=np.uint8).reshape(n,FRAME_BYTES)
        decoded=np.frombuffer(data,np.uint8).reshape(n,FRAME_BYTES)
        return {'bytes':dest.stat().st_size,'packet_bytes':sum(p),
                'frames':n,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
                **source_metrics(ref,decoded)}
    rc=decode_checks(chosen_name)
    bc=decode_checks(control_name)
    if rc['packet_bytes']!=video_bytes or bc['packet_bytes']!=budget:
        raise RuntimeError('MOFLEX concat packet size not preserved')
    result={'clip':name,'gops':len(indices),'coded_frames':rc['frames'],
            'budget_video_bytes':budget,'rdo_video_bytes':video_bytes,
            'predicted_control_psnr':total_psnr(list(baseline.values())),
            'predicted_optimized_psnr':total_psnr(chosen),
            'mux_control':bc,'mux_rdo':rc,
            'changed_gops':sum(t['q']!=base for t in chosen),
            'selected':[{'gop':t['gop'],'q':t['q'],'bytes':t['video_bytes'],
                         'psnr':t['luma_psnr']} for t in chosen],
            'control_file':str(control_name),'rdo_file':str(chosen_name)}
    (OUT/name/'GOP_RDO_FINAL_REPORT.json').write_text(json.dumps(result,indent=2))
    print('RDO',name,'control PSNR',bc['luma_psnr'],'optimized PSNR',rc['luma_psnr'],
          'control bytes',bc['bytes'],'optimized bytes',rc['bytes'],flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clips',nargs='+',choices=CLIPS,default=['anime','yip','nature','badapple'])
    p.add_argument('--quantizers',nargs='+',type=int,default=list(range(26,35)))
    p.add_argument('--base',type=int,default=30)
    p.add_argument('--gop',type=int,default=24)
    p.add_argument('--guard',type=float,default=.2)
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--optimize-only',action='store_true')
    args=p.parse_args()
    if args.gop<8 or args.gop>240:raise ValueError('GOP must be 8..240 frames')
    jobs=[];caches={}
    for name in args.clips:
        splits=segments(name,args.gop)
        report=OUT/name/'GOP_RDO_TRIALS.json'
        old=json.loads(report.read_text()) if report.is_file() else []
        cache={(r['gop'],r['q']):r for r in old}
        caches[name]=(report,cache)
        if not args.optimize_only:
            jobs.extend((name,idx,n,src,q) for idx,n,src in splits
                        for q in args.quantizers+[args.base]
                        if (idx,q) not in cache)
    jobs=list(dict.fromkeys(jobs))
    print('GOP_RDO',len(jobs),'new trials',flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(test,*job):job for job in jobs}
        for k,f in enumerate(as_completed(pending),1):
            row=f.result()
            name=row['clip']
            report,cache=caches[name]
            cache[(row['gop'],row['q'])]=row
            report.write_text(json.dumps(sorted(cache.values(),key=lambda r:(r['gop'],r['q'])),indent=2))
            if k%10==0 or k==len(jobs):
                print(f'{k}/{len(jobs)} {name} GOP {row["gop"]} Q{row["q"]} '
                      f'PSNR={row["luma_psnr"]:.3f} bytes={row["video_bytes"]}',flush=True)
    for name in args.clips:optimize(name,args.gop,args.base,args.guard)
    print('PASS: independently decoded',sum(len(v[1]) for v in caches.values()),
          'GOP candidates, plus joined MOFLEX control and RDO versions',flush=True)


if __name__=='__main__':main()
