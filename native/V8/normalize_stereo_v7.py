#!/usr/bin/env python3
"""Normalize H-SBS / F-SBS MP4 to alternating 400x224 eyes at 48 coded FPS.

'classic' matches V5 measurements: resize full 2-up SBS to 800x224 then split.
'per-eye' independently crops/resizes eyes and prevents cross-eye mixing by
scaler kernels at the center seam. Per-eye is experimental until 3DS-tested.
"""
import argparse,subprocess,hashlib,os
from pathlib import Path
W,H=800,224
FR=W*H*3//2;EW=W//2;EYE=EW*H*3//2

def normalize(input_path,output,ffmpeg='ffmpeg',method='classic',kernel='lanczos'):
    if method not in ('classic','per-eye'):raise ValueError('choose classic or per-eye')
    if kernel not in ('lanczos','bicubic','bilinear','area','spline'):raise ValueError('unsupported scale kernel')
    if method=='classic':
        f='fps=24,scale=800:224:flags='+kernel+',format=yuv420p'
        cmd=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(input_path),'-vf',f,
             '-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1']
    else:
        flt=(f'[0:v:0]fps=24,split=2[l0][r0];'
             f'[l0]crop=iw/2:ih:0:0,scale=400:224:flags={kernel}[l];'
             f'[r0]crop=iw/2:ih:iw/2:0,scale=400:224:flags={kernel}[r];'
             f'[l][r]hstack=inputs=2,format=yuv420p[sbs]')
        cmd=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(input_path),'-filter_complex',flt,
             '-map','[sbs]','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1']
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    n=0;out=Path(output);out.parent.mkdir(exist_ok=True,parents=True)
    try:
        with out.open('wb',buffering=1<<20) as f:
            while True:
                buffer=bytearray(FR);read=0
                while read<FR:
                    chunk=p.stdout.read(FR-read)
                    if not chunk:break
                    buffer[read:read+len(chunk)]=chunk;read+=len(chunk)
                if read==0:break
                if read!=FR:raise RuntimeError(f'truncated stereo frame: {read}/{FR}')
                y=memoryview(buffer)[:W*H];u=memoryview(buffer)[W*H:W*H+W*H//4];v=memoryview(buffer)[W*H+W*H//4:]
                for eye in (0,1):
                    for plane,stride,rows,cols in ((y,W,H,EW),(u,W//2,H//2,EW//2),(v,W//2,H//2,EW//2)):
                        for row in range(rows):
                            j=row*stride+eye*cols
                            f.write(plane[j:j+cols])
                n+=1
        p.stdout.close();err=p.stderr.read();rc=p.wait()
        if rc:raise RuntimeError(err.decode(errors='replace')[-1500:])
    except BaseException:
        p.kill();p.wait();raise
    if out.stat().st_size!=n*2*EYE:raise RuntimeError('bad output size')
    print(f'Normalized {n} display stereo pairs / {n*2} eye frames, method={method}, kernel={kernel}, bytes={out.stat().st_size}',flush=True)
    return n

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output');p.add_argument('--ffmpeg',default='ffmpeg');p.add_argument('--method',default='classic',choices=['classic','per-eye']);p.add_argument('--kernel',default='lanczos',choices=['lanczos','bicubic','bilinear','area','spline']);a=p.parse_args()
    normalize(a.input,a.output,a.ffmpeg,a.method,a.kernel)
