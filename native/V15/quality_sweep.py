#!/usr/bin/env python3
"""Reproducible multi-content, independently decoded MobiPEG quality sweep.

The source is always the *unfiltered* planar YUV reference. Comparisons
therefore cannot accidentally reward a filter just for smoothing its input.
No temporal prefilter is used on interleaved stereoscopic video.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
_DEFAULT_ENC = WORKSPACE/'local/bin/ffmpeg'
if not _DEFAULT_ENC.is_file():
    _DEFAULT_ENC=WORKSPACE/'MobiPEG_V13_work/local/bin/ffmpeg'
ENC = Path(os.environ.get('MOBIPEG_TEST_FFMPEG',str(_DEFAULT_ENC))).resolve()
PROBE = ENC.with_name('ffprobe')
SOURCE_DIR = Path(os.environ.get('MOBIPEG_TEST_VIDEO_DIR',str(WORKSPACE/'v15_library_sources'))).resolve()
W, H, FPS = 400, 240, 24
FRAME_BYTES = W*H*3//2
CLIPS = {
    'anime': ('anime.mp4', 3, 5),
    'anime_late': ('anime.mp4', 30, 5),
    'anime_end': ('anime.mp4', 53, 5),
    'yip': ('Yip.mp4', 4, 5),
    'yip_late': ('Yip.mp4', 17, 5),
    'nature': ('Video by nathanleeallen.mp4', 3, 5),
    'badapple': ('Bad_apple.mp4', 20, 5),
    'badapple_late': ('Bad_apple.mp4', 160, 5),
    'sonic': ('sonic2.mp4', 0, .92),
    'stonelifts': ('Video by stonelifts.mp4', 2, 5),
    'sixtwo2': ('Video by sixtwo2.mp4', 12, 5),
    'gamecube': ('Just a normal Gamecube intro.mp4', 3, 5),
    'yippee_jazz': ("NA - YIPPEE but it's JAZZ (tbh creature)(1).mp4", 9, 5),
    'avatar_left': ('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4', 30, 5),
    'avatar_title': ('Avatar 2 Way of Water 4K 3D H-SBS teaser trailer.mp4', 94, 5),
}
FILTERS = {
    'none': None,
    'hq_light': 'hqdn3d=0.7:1.1:0:0',
    'hq_medium': 'hqdn3d=1.4:1.8:0:0',
    'bilat_light': 'bilateral=sigmaS=1.2:sigmaR=0.035:planes=1',
    'deband_light': 'deband=1thr=0.006:2thr=0.006:3thr=0.006:range=8:blur=true',
    'gradfun': 'gradfun=strength=1.2:radius=16',
    'gradfun_strong': 'gradfun=strength=2.5:radius=16',
}


def command(args: list[str | Path], env: dict | None = None, timeout: int = 150):
    proc = subprocess.run([str(x) for x in args], capture_output=True,
                          env=env, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f'Command exit {proc.returncode}: {proc.stderr[-1800:].decode(errors="replace")}')
    return proc.stdout


def source_path(name: str) -> Path:
    return ROOT/'sources'/f'{name}_400x240_24fps.yuv'


def prepare(name: str) -> Path:
    inp, start, dur = CLIPS[name]
    src = SOURCE_DIR/inp
    if not src.is_file():
        raise FileNotFoundError(f'Missing requested video: {src}')
    out = source_path(name)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        scale = ('fps=24,scale=400:240:force_original_aspect_ratio=decrease:'
                 'force_divisible_by=2:in_range=auto:out_range=tv:flags=lanczos,'
                 'pad=400:240:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p')
        if name.startswith('avatar_'):
            # Treat the left stereoscopic eye as a separate 2D rate-distortion
            # source; NEVER cross-average the two eyes in the codec sweep.
            scale='crop=iw/2:ih:0:0,'+scale
        command([ENC,'-hide_banner','-nostdin','-v','error','-y','-ss',str(start),
                 '-t',str(dur),'-i',src,'-vf',scale,'-an',
                 '-pix_fmt','yuv420p','-f','rawvideo',out])
    if not out.stat().st_size or out.stat().st_size%FRAME_BYTES:
        raise RuntimeError(f'Incomplete normalized source: {out}')
    return out


def source_metrics(src: np.ndarray, rec: np.ndarray):
    """Framewise error, texture retention, and 4x4 seams in flat source regions."""
    if src.shape!=rec.shape:raise ValueError('Frame shape mismatch')
    n=src.shape[0]
    x=src[:,:W*H].reshape(n,H,W).astype(np.float32)
    y=rec[:,:W*H].reshape(n,H,W).astype(np.float32)
    diff=x-y
    mse=float(np.mean(diff**2))
    uv_src=src[:,W*H:].astype(np.float32)
    uv_rec=rec[:,W*H:].astype(np.float32)
    chroma_mse=float(np.mean((uv_src-uv_rec)**2))
    dx=np.diff(x,axis=2);dy=np.diff(x,axis=1)
    ex=np.diff(y,axis=2)-dx;ey=np.diff(y,axis=1)-dy
    edge_mse=float((np.mean(ex**2)+np.mean(ey**2))/2)
    flat_x=(np.abs(dx)<=5)
    flat_y=(np.abs(dy)<=5)
    bx=(np.arange(1,W)%4)==0
    by=(np.arange(1,H)%4)==0
    def flat_mean(values, mask):
        return float(np.mean(values[mask])) if np.any(mask) else 0.
    block_x=flat_mean(ex**2,flat_x & bx[None,None,:])
    base_x=flat_mean(ex**2,flat_x & ~bx[None,None,:])
    block_y=flat_mean(ey**2,flat_y & by[None,:,None])
    base_y=flat_mean(ey**2,flat_y & ~by[None,:,None])
    # Also report smooth, dark luma fidelity (compressing an area into a
    # uniform patch can otherwise look deceptively "less noisy").
    dark=(x>=17)&(x<=110)
    dark_mse=flat_mean(diff**2,dark)
    # Penalize *induced* flicker, not natural source motion/texture.
    flicker=float(np.mean(np.diff(diff,axis=0)**2)) if n>1 else 0.
    # Fast local SSIM on 12 representative luma frames, at native pixels.
    subset=np.linspace(0,n-1,min(n,12),dtype=int)
    sample_ssim=[]
    for j in subset:
        a=x[j];b=y[j]
        ma=uniform_filter(a,7);mb=uniform_filter(b,7)
        va=np.maximum(0,uniform_filter(a*a,7)-ma*ma)
        vb=np.maximum(0,uniform_filter(b*b,7)-mb*mb)
        cov=uniform_filter(a*b,7)-ma*mb
        c1=(.01*255)**2;c2=(.03*255)**2
        v=((2*ma*mb+c1)*(2*cov+c2))/((ma*ma+mb*mb+c1)*(va+vb+c2))
        sample_ssim.append(float(np.mean(v)))
    return {
        'luma_mse':mse,
        'luma_psnr':float(10*np.log10(255**2/max(1e-12,mse))),
        'chroma_mse':chroma_mse,
        'edge_mse':edge_mse,
        'dark_mse':dark_mse,
        'flat_4x4_seam_excess':float((block_x-base_x+block_y-base_y)/2),
        'flicker_mse':flicker,
        'ssim':float(np.mean(sample_ssim)),
    }


def q_to_flags(q: int):
    if not 12 <= q <= 59:raise ValueError('Actual Mobiclip Q must be 12..59')
    return ['-qp',str(12+(q-12)%6),'-mobi_qyx',str((q-12)//6)]


def run_one(name: str, mode: str, q: int):
    src=prepare(name)
    n=src.stat().st_size//FRAME_BYTES
    prefix=f'{name}_{mode}_q{q}'
    target=ROOT/'encodes'/f'{prefix}.moflex'
    target.parent.mkdir(parents=True,exist_ok=True)
    vf=FILTERS[mode]
    t=time.monotonic()
    if not target.is_file():
        args=[ENC,'-hide_banner','-nostdin','-v','error','-y',
              '-f','rawvideo','-pix_fmt','yuv420p','-s','400x240','-framerate','24',
              '-i',src]
        if vf:args+=['-vf',vf]
        args+=['-an','-c:v','mobiclip','-mobiclip','1',*q_to_flags(q),
               '-preset','medium','-me_method','hex','-g','48','-mo_layout','6',
               '-f','moflex',target]
        env={**os.environ,'MOBI_SUBME':'9','MOBI_SKIP':'0'}
        command(args,env=env,timeout=300)
    rec=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                 '-i',target,'-map','0:v:0','-pix_fmt','yuv420p',
                 '-f','rawvideo','pipe:1'],timeout=200)
    if len(rec)!=n*FRAME_BYTES:
        raise RuntimeError(f'Incomplete video decode {prefix}: {len(rec)} vs {n*FRAME_BYTES}')
    packet_sizes=command([PROBE,'-v','error','-select_streams','v:0',
                          '-show_entries','packet=size','-of','csv=p=0',target])
    packets=[int(x) for x in packet_sizes.split()]
    if len(packets)!=n:raise RuntimeError(f'Wrong packet count {prefix}: {len(packets)} != {n}')
    a=np.memmap(src,mode='r',dtype=np.uint8).reshape(n,FRAME_BYTES)
    b=np.frombuffer(rec,dtype=np.uint8).reshape(n,FRAME_BYTES)
    values=source_metrics(a,b)
    return {'clip':name,'filter':mode,'q':q,'frames':n,'duration_s':n/FPS,
            'file_bytes':target.stat().st_size,'video_bytes':sum(packets),
            'video_kbps':sum(packets)*8/(n/FPS)/1000,
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'path':str(target),'encode_decode_seconds':round(time.monotonic()-t,3),
            **values}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--clips',nargs='+',choices=CLIPS,default=list(CLIPS))
    ap.add_argument('--filters',nargs='+',choices=FILTERS,
                    default=['none','hq_light','hq_medium','bilat_light','deband_light','gradfun'])
    ap.add_argument('--quantizers',nargs='+',type=int,default=[28,30,32])
    ap.add_argument('--workers',type=int,default=4)
    a=ap.parse_args()
    if a.workers<1 or a.workers>12:ap.error('Use 1..12 workers')
    for name in a.clips:prepare(name)
    result_path=ROOT/'reports'/'V15_CONTENT_SWEEP.json'
    result_path.parent.mkdir(exist_ok=True)
    prior=json.loads(result_path.read_text()) if result_path.is_file() else []
    done={(v['clip'],v['filter'],v['q']):v for v in prior}
    jobs=[(name,mode,q) for name in a.clips for mode in a.filters for q in a.quantizers
          if (name,mode,q) not in done]
    print('JOBS',len(jobs),'CACHED',len(done),flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        pending={ex.submit(run_one,*job):job for job in jobs}
        for i,future in enumerate(as_completed(pending),1):
            row=future.result()
            done[(row['clip'],row['filter'],row['q'])]=row
            result_path.write_text(json.dumps(sorted(done.values(),key=lambda x:(x['clip'],x['filter'],x['q'])),indent=2))
            print(f'{i}/{len(jobs)} {row["clip"]:9} {row["filter"]:15} '
                  f'Q{row["q"]} bytes={row["file_bytes"]:8} '
                  f'PSNR={row["luma_psnr"]:.4f} SSIM={row["ssim"]:.6f} '
                  f'dark={row["dark_mse"]:.3f} seam={row["flat_4x4_seam_excess"]:.3f}',
                  flush=True)
    print('PASS:',len(done),'decoded video experiments; results=',result_path,flush=True)


if __name__=='__main__':main()
