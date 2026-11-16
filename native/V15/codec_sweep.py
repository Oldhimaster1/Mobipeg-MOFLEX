#!/usr/bin/env python3
"""V15 native codec search (GOP, subpel, motion estimation, RD options).

Every trial is independently decoded, checked for exact frame count and
compared against the same unfiltered source, with actual MOFLEX file bytes.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import time

import numpy as np
from quality_sweep import ROOT,ENC,PROBE,FRAME_BYTES,CLIPS,prepare,command,source_metrics,q_to_flags

CONFIG={
    'baseline':(9,'hex',48,{}),
    'subme2':(2,'hex',48,{}),
    'subme5':(5,'hex',48,{}),
    'subme7':(7,'hex',48,{}),
    'subme10':(10,'hex',48,{}),
    'me_umh':(9,'umh',48,{}),
    'me_esa':(9,'esa',48,{}),
    'gop24':(9,'hex',24,{}),
    'gop72':(9,'hex',72,{}),
    'gop96':(9,'hex',96,{}),
    'dc_match':(9,'hex',48,{'MOBI_V11_DC_MATCH':'1','MOBI_V11_DC_CLAMP':'4','MOBI_V11_DC_STRENGTH':'8'}),
    'intra_cap3':(9,'hex',48,{'MOBI_INTRA_RD_CAP':'3'}),
    'skip64':(9,'hex',48,{'MOBI_SKIP':'64'}),
    # Exact native-code coefficient and motion R-D knobs tested in earlier
    # MobiPEG versions. Keep them opt-in until measured on *other* content.
    'luma_dz4':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_DZ':'4','MOBI_CHROMA_DZ':'5'}),
    'luma_dz5':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_DZ':'5','MOBI_CHROMA_DZ':'5'}),
    'luma_dz6':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_DZ':'6','MOBI_CHROMA_DZ':'5'}),
    'luma_dz7':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_DZ':'7','MOBI_CHROMA_DZ':'5'}),
    'luma_dz8':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_DZ':'8','MOBI_CHROMA_DZ':'5'}),
    'flat_luma12':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_V9_INTER_FLAT_RANGE':'12',
                             'MOBI_DZ':'5','MOBI_CHROMA_DZ':'5'}),
    'flat_luma24':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_V9_INTER_FLAT_RANGE':'24',
                             'MOBI_DZ':'5','MOBI_CHROMA_DZ':'5'}),
    'flat_luma48':(9,'hex',48,{'MOBI_V9_INTER_LUMA_DZ':'1','MOBI_V9_INTER_FLAT_RANGE':'48',
                             'MOBI_DZ':'5','MOBI_CHROMA_DZ':'5'}),
    'activity2_9':(9,'hex',48,{'MOBI_V10_ACTIVITY':'1','MOBI_V10_FLAT_OFFSET':'2',
                              'MOBI_V10_EDGE_OFFSET':'9'}),
    'activity4_10':(9,'hex',48,{'MOBI_V10_ACTIVITY':'1','MOBI_V10_FLAT_OFFSET':'4',
                               'MOBI_V10_EDGE_OFFSET':'10'}),
    'mvref0':(9,'hex',48,{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'}),
    'mvref8':(9,'hex',48,{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'}),
    'mvref24':(9,'hex',48,{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'24'}),
    'mvref8_act':(9,'hex',48,{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8',
                            'MOBI_V10_ACTIVITY':'1','MOBI_V10_FLAT_OFFSET':'2',
                            'MOBI_V10_EDGE_OFFSET':'9'}),
    'seam_dc4':(9,'hex',48,{'MOBI_V13_SEAM_DC':'1','MOBI_V13_SEAM_WEIGHT':'4',
                           'MOBI_V13_SEAM_RANGE':'16'}),
    'seam_dc8':(9,'hex',48,{'MOBI_V13_SEAM_DC':'1','MOBI_V13_SEAM_WEIGHT':'8',
                           'MOBI_V13_SEAM_RANGE':'16'}),
}


def run_one(clip,variant,q):
    sub,me,gop,options=CONFIG[variant]
    raw=prepare(clip)
    frames=raw.stat().st_size//FRAME_BYTES
    name=f'{clip}_{variant}_q{q}'
    movie=ROOT/'codec'/f'{name}.moflex'
    movie.parent.mkdir(exist_ok=True)
    start=time.monotonic()
    if not movie.is_file():
        env={**os.environ,'MOBI_SUBME':str(sub),'MOBI_SKIP':'0',**options}
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
                 '-f','rawvideo','-pix_fmt','yuv420p','-s','400x240',
                 '-framerate','24','-i',raw,'-an','-c:v','mobiclip','-mobiclip','1',
                 *q_to_flags(q),'-preset','medium','-me_method',me,'-g',str(gop),
                 '-mo_layout','6','-f','moflex',movie],env=env,timeout=300)
    decoded=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                     '-i',movie,'-map','0:v:0','-pix_fmt','yuv420p',
                     '-f','rawvideo','pipe:1'],timeout=180)
    if len(decoded)!=frames*FRAME_BYTES:
        raise RuntimeError(f'Decoder failed {clip}/{variant} {len(decoded)}')
    packet_raw=command([PROBE,'-v','error','-select_streams','v:0',
                        '-show_entries','packet=size','-of','csv=p=0',movie])
    packets=[int(x) for x in packet_raw.split()]
    if len(packets)!=frames:raise RuntimeError('Incomplete GOP packet set')
    ref=np.memmap(raw,dtype=np.uint8).reshape(frames,FRAME_BYTES)
    rec=np.frombuffer(decoded,np.uint8).reshape(frames,FRAME_BYTES)
    return {'clip':clip,'variant':variant,'q':q,'frames':frames,
            'file_bytes':movie.stat().st_size,'video_bytes':sum(packets),
            'path':str(movie),'elapsed':round(time.monotonic()-start,3),
            **source_metrics(ref,rec)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clips',nargs='+',choices=CLIPS,default=list(CLIPS))
    p.add_argument('--variants',nargs='+',choices=CONFIG,default=list(CONFIG))
    p.add_argument('--quantizers',nargs='+',type=int,default=[30])
    p.add_argument('--workers',type=int,default=6)
    a=p.parse_args()
    report=ROOT/'reports/V15_CODEC_SWEEP.json'
    prior=json.loads(report.read_text()) if report.exists() else []
    cache={(r['clip'],r['variant'],r['q']):r for r in prior}
    jobs=[(clip,variant,q) for clip in a.clips for variant in a.variants
          for q in a.quantizers if (clip,variant,q) not in cache]
    print('CODEC',len(jobs),'new',len(cache),'cached',flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futures={ex.submit(run_one,*job):job for job in jobs}
        for i,f in enumerate(as_completed(futures),1):
            r=f.result()
            cache[(r['clip'],r['variant'],r['q'])]=r
            report.write_text(json.dumps(sorted(cache.values(),key=lambda r:(r['clip'],r['variant'],r['q'])),indent=2))
            print(f'{i}/{len(jobs)} {r["clip"]:9} {r["variant"]:15} '
                  f'bytes={r["file_bytes"]:8} PSNR={r["luma_psnr"]:.4f} '
                  f'dark={r["dark_mse"]:.3f} SSIM={r["ssim"]:.6f}',flush=True)
    print('PASS',len(cache),'codec trials',flush=True)


if __name__=='__main__':main()
