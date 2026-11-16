#!/usr/bin/env python3
"""Stereo-preservation and quality/bitrate tests on true HSBS and full-SBS.

Encoding operates on 800x224 packed stereoscopic frames with two separately
preprocessed eyes. All generated MOFLEX frames are independently decoded,
both eyes are compared to their corresponding originals, and decoded frame
and layout metadata are checked before a trial is called successful.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import time

import numpy as np
from quality_sweep import ROOT,ENC,PROBE,SOURCE_DIR,command,q_to_flags

W,H,FPS=800,224,24
FRAME_BYTES=W*H*3//2
SOURCES={
    'avatar_action':('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4',30,5,'half-sbs'),
    'avatar_water':('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4',61,5,'half-sbs'),
    'avatar_title':('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4',94,5,'half-sbs'),
    'avatar_opening':('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4',10,5,'half-sbs'),
    'sbs_reference':('MobiPEG_stereo_FULL_SBS_reference.mp4',0,5,'full-sbs'),
}
VARIANTS={
    'control':{},
    'v15_mvref0':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'},
    'v15_mvref8':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'8'},
    'v15_mvref24':{'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'24'},
}


def source(name):
    namefile,start,duration,layout=SOURCES[name]
    inp=SOURCE_DIR/namefile
    if not inp.is_file():raise FileNotFoundError(inp)
    dest=ROOT/'stereo'/f'{name}_800x224_24fps.yuv'
    dest.parent.mkdir(exist_ok=True)
    if not dest.is_file():
        sar=2 if layout=='half-sbs' else 1
        filter_eye=f'setsar={sar},scale=400:224:flags=lanczos,setsar=1'
        filter_complex=(f'[0:v:0]fps=24,split=2[left][right];'
              f'[left]crop=iw/2:ih:0:0,{filter_eye}[l];'
              f'[right]crop=iw/2:ih:iw/2:0,{filter_eye}[r];'
              '[l][r]hstack=inputs=2,format=yuv420p[out]')
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
                 '-ss',str(start),'-t',str(duration),'-i',inp,
                 '-filter_complex',filter_complex,'-map','[out]',
                 '-an','-pix_fmt','yuv420p','-f','rawvideo',dest],timeout=180)
    if not dest.stat().st_size or dest.stat().st_size%FRAME_BYTES:
        raise RuntimeError('Bad stereo sample size')
    return dest


def metrics(source_data,decoded_data):
    n=len(source_data)//FRAME_BYTES
    if len(source_data)!=len(decoded_data) or not n:
        raise RuntimeError('Stereo decode did not preserve frame count')
    luma_size=W*H
    s=np.frombuffer(source_data,np.uint8).reshape(n,FRAME_BYTES)
    d=np.frombuffer(decoded_data,np.uint8).reshape(n,FRAME_BYTES)
    sy=s[:,:luma_size].reshape(n,H,W).astype(np.float32)
    dy=d[:,:luma_size].reshape(n,H,W).astype(np.float32)
    eye_dist=[]
    for lo,hi in ((0,400),(400,800)):
        err=sy[:,:,lo:hi]-dy[:,:,lo:hi]
        mse=float(np.mean(err**2))
        eye_dist.append((mse,float(10*np.log10(255**2/max(mse,1e-12)))))
    # Reference left/right separation must not vanish in the output.
    reference_disparity=float(np.mean(np.abs(sy[:,:,:400]-sy[:,:,400:])))
    decoded_disparity=float(np.mean(np.abs(dy[:,:,:400]-dy[:,:,400:])))
    if reference_disparity>2 and decoded_disparity<reference_disparity*.25:
        raise RuntimeError('Stereo eyes collapsed or were mixed')
    mse=(eye_dist[0][0]+eye_dist[1][0])/2
    s_uv=s[:,luma_size:].astype(np.float32)
    d_uv=d[:,luma_size:].astype(np.float32)
    return {'luma_psnr':float(10*np.log10(255**2/max(mse,1e-12))),
            'left_psnr':eye_dist[0][1],'right_psnr':eye_dist[1][1],
            'chroma_mse':float(np.mean((s_uv-d_uv)**2)),
            'input_eye_disparity':reference_disparity,
            'decoded_eye_disparity':decoded_disparity,
            'eye_mse_difference':abs(eye_dist[0][0]-eye_dist[1][0])}


def test(name,variant,q):
    src=source(name)
    n=src.stat().st_size//FRAME_BYTES
    outfile=ROOT/'stereo'/f'{name}_{variant}_Q{q}.moflex'
    t=time.monotonic()
    if not outfile.exists():
        env={k:v for k,v in os.environ.items() if not k.startswith('MOBI_')}
        env.update({'MOBI_SUBME':'9','MOBI_SKIP':'0',**VARIANTS[variant]})
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
                 '-f','rawvideo','-pix_fmt','yuv420p','-s','800x224',
                 '-framerate','24','-i',src,'-an','-c:v','mobiclip',
                 '-mobiclip','1',*q_to_flags(q),'-preset','medium',
                 '-me_method','hex','-g','48','-mo_layout','4',
                 '-f','moflex',outfile],env=env,timeout=320)
    decoded=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                     '-i',outfile,'-map','0:v:0','-pix_fmt','yuv420p',
                     '-f','rawvideo','pipe:1'],timeout=260)
    packets=command([PROBE,'-v','error','-select_streams','v:0',
                      '-show_entries','packet=size','-of','csv=p=0',outfile])
    sizes=[int(z) for z in packets.split()]
    if len(sizes)!=n:raise RuntimeError('Missing stereo video packets')
    layout_info=command([PROBE,'-v','error','-select_streams','v:0',
          '-show_entries','stream=width,height','-of','csv=p=0',outfile]).decode().strip()
    if layout_info!='800,224':raise RuntimeError(f'Wrong SBS dimensions {layout_info}')
    return {'clip':name,'variant':variant,'quantizer':q,
            'file_bytes':outfile.stat().st_size,'packet_bytes':sum(sizes),
            'frames':n,'layout':'800x224 SBS','seconds':round(time.monotonic()-t,3),
            'path':str(outfile),
            **metrics(src.read_bytes(),decoded)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clips',nargs='+',choices=SOURCES,default=list(SOURCES))
    p.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    p.add_argument('--quantizers',nargs='+',type=int,default=[30])
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args()
    for c in args.clips:source(c)
    report=ROOT/'reports/V15_STEREO_SWEEP.json'
    prior=json.loads(report.read_text()) if report.exists() else []
    cache={(r['clip'],r['variant'],r['quantizer']):r for r in prior}
    jobs=[(c,v,q) for c in args.clips for v in args.variants
          for q in args.quantizers if (c,v,q) not in cache]
    print('STEREO',len(jobs),'trials',flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fs={pool.submit(test,*job):job for job in jobs}
        for i,f in enumerate(as_completed(fs),1):
            result=f.result()
            cache[(result['clip'],result['variant'],result['quantizer'])]=result
            report.write_text(json.dumps(sorted(cache.values(),key=lambda r:(r['clip'],r['variant'],r['quantizer'])),indent=2))
            print(f'{i}/{len(jobs)} {result["clip"]:15} {result["variant"]:15} '
                  f'{result["file_bytes"]} bytes PSNR={result["luma_psnr"]:.3f} '
                  f'eyes={result["left_psnr"]:.3f}/{result["right_psnr"]:.3f}',flush=True)
    print('PASS',len(cache),'stereo trials decoded and verified',flush=True)


if __name__=='__main__':main()
