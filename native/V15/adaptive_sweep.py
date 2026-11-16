#!/usr/bin/env python3
"""V15 bitrate-aware per-frame quantizer search across varied real content.

V13's per-frame Q is in the bitstream and decoder-exact. Test several actual
Q plans, *including* direct constant Q controls, at multiple base Q values.
All outcomes are independently decoded and compared to unchanged raw input.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from quality_sweep import ROOT,ENC,PROBE,FRAME_BYTES,W,H,CLIPS,prepare,command,source_metrics,q_to_flags

_source_home=(ROOT.parent/'V13')
if not _source_home.is_dir():
    _source_home=ROOT.parent/'MobiPEG_V14_Full_Source_and_Encoder/V13'
sys.path.insert(0,str(_source_home))
sys.path.insert(0,str(_source_home.parent/'V14'))
from plan_from_raw import make_plan
from scene_cut_plan import detect_cuts,protect

MODES=('uniform','motion1','motion2','detail1','detail2','balanced1',
       'balanced2','balanced2_cut_safe','balanced2_cut_focus')


def plan(name:str,mode:str,base:int):
    raw=prepare(name)
    n=raw.stat().st_size//FRAME_BYTES
    if mode=='uniform':q=[base]*n
    else:
        key=mode.split('_')[0]
        action=key[:-1]
        strength=int(key[-1])
        q=make_plan(raw,W,H,base,1,strength,action,2)
        if '_cut_' in mode:
            src=np.memmap(raw,dtype=np.uint8).reshape(n,FRAME_BYTES)
            cuts=detect_cuts(src,W,H,1,38.0)
            focus='cutfocus' if mode.endswith('focus') else 'safe'
            q=protect(q,cuts,n,1,focus,src,W,H)
    if len(q)!=n or any(x<12 or x>59 for x in q):
        raise RuntimeError('Wrong Q plan length or invalid quantizer')
    return q


def run_one(name,mode,base):
    src=prepare(name)
    n=src.stat().st_size//FRAME_BYTES
    prefix=f'{name}_{mode}_base{base}'
    target=ROOT/'adaptive'/f'{prefix}.moflex'
    target.parent.mkdir(exist_ok=True)
    q=plan(name,mode,base)
    qfile=target.with_suffix('.txt')
    if not qfile.is_file():qfile.write_text(''.join(f'{v}\n' for v in q))
    t0=time.monotonic()
    if not target.is_file():
        env={**os.environ,'MOBI_SUBME':'9','MOBI_SKIP':'0','MOBI_V13_Q_PLAN':str(qfile)}
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
                 '-f','rawvideo','-pix_fmt','yuv420p','-s','400x240',
                 '-framerate','24','-i',src,'-an','-c:v','mobiclip','-mobiclip','1',
                 *q_to_flags(base),'-preset','medium','-me_method','hex','-g','48',
                 '-mo_layout','6','-f','moflex',target],env=env,timeout=300)
    rec=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror','-i',target,
                 '-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=180)
    if len(rec)!=n*FRAME_BYTES:raise RuntimeError('Wrong decoded frame count')
    packets=command([PROBE,'-v','error','-select_streams','v:0',
                     '-show_entries','packet=size','-of','csv=p=0',target])
    packet_bytes=[int(z) for z in packets.split()]
    if len(packet_bytes)!=n:raise RuntimeError('Wrong packet count')
    raw=np.memmap(src,dtype=np.uint8).reshape(n,FRAME_BYTES)
    decoded=np.frombuffer(rec,np.uint8).reshape(n,FRAME_BYTES)
    return {'clip':name,'mode':mode,'base_q':base,
            'file_bytes':target.stat().st_size,'video_bytes':sum(packet_bytes),
            'frames':n,'mean_q':float(np.mean(q)),
            'q_histogram':{str(v):q.count(v) for v in set(q)},
            'elapsed':round(time.monotonic()-t0,3),'path':str(target),
            **source_metrics(raw,decoded)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clips',nargs='+',choices=CLIPS,default=list(CLIPS))
    p.add_argument('--modes',nargs='+',choices=MODES,default=list(MODES))
    p.add_argument('--bases',nargs='+',type=int,default=[29,30,31])
    p.add_argument('--workers',type=int,default=6)
    a=p.parse_args()
    report=ROOT/'reports/V15_ADAPTIVE_SWEEP.json'
    old=json.loads(report.read_text()) if report.is_file() else []
    cache={(r['clip'],r['mode'],r['base_q']):r for r in old}
    jobs=[(clip,mode,base) for clip in a.clips for mode in a.modes for base in a.bases
          if (clip,mode,base) not in cache]
    print('ADAPTIVE',len(jobs),'new,',len(cache),'cached',flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(run_one,*job):job for job in jobs}
        for i,fut in enumerate(as_completed(futures),1):
            row=fut.result()
            cache[(row['clip'],row['mode'],row['base_q'])]=row
            report.write_text(json.dumps(sorted(cache.values(),key=lambda r:(r['clip'],r['mode'],r['base_q'])),indent=2))
            print(f'{i}/{len(jobs)} {row["clip"]:9} {row["mode"]:25} '
                  f'Q{row["base_q"]} bytes={row["file_bytes"]:8} '
                  f'PSNR={row["luma_psnr"]:.5f} SSIM={row["ssim"]:.6f}',flush=True)
    print('PASS',len(cache),'fully decoded Q-plan trials',flush=True)


if __name__=='__main__':main()
