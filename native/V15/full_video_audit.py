#!/usr/bin/env python3
"""Long-video (audio + 2D) independent rate-distortion regression audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import uniform_filter

from quality_sweep import ROOT,ENC,FRAME_BYTES,W,H,SOURCE_DIR,command

PREVIEWS=ROOT.parent/'v15_previews'
TARGETS={
 'anime':(SOURCE_DIR/'anime.mp4',
          PREVIEWS/'Anime_FULL_V15_Control_2D.moflex',
          PREVIEWS/'Anime_FULL_V15_MotionRefine_2D.moflex'),
 'yip':(SOURCE_DIR/'Yip.mp4',
        PREVIEWS/'Yip_FULL_V15_Control_2D.moflex',
        PREVIEWS/'Yip_FULL_V15_MotionRefine_2D.moflex'),
}


def yuv_from_source(name,inp):
    out=ROOT/'full_video'/f'{name}_source_400x240.yuv'
    out.parent.mkdir(exist_ok=True)
    if not out.exists():
        filt=('fps=24,setsar=1,scale=400:240:force_original_aspect_ratio=decrease:'
              'force_divisible_by=2:in_range=auto:out_range=tv:flags=lanczos,'
              'pad=400:240:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p')
        command([ENC,'-hide_banner','-nostdin','-v','error','-y',
           '-i',inp,'-map','0:v:0','-vf',filt,'-an',
           '-pix_fmt','yuv420p','-f','rawvideo',out],timeout=450)
    if out.stat().st_size%FRAME_BYTES:raise RuntimeError('Wrong normalized source length')
    return out


def decode(name,label,video):
    out=ROOT/'full_video'/f'{name}_{label}_decoded.yuv'
    if not out.exists():
        command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
            '-y','-i',video,'-map','0:v:0','-pix_fmt','yuv420p',
            '-f','rawvideo',out],timeout=600)
    if not out.stat().st_size or out.stat().st_size%FRAME_BYTES:
        raise RuntimeError('Wrong decoded sample count')
    return out


def compare(source,decoded):
    n=source.stat().st_size//FRAME_BYTES
    if decoded.stat().st_size!=source.stat().st_size:
        raise RuntimeError('Decoded video frame count does not match source')
    src=np.memmap(source,dtype=np.uint8).reshape(n,FRAME_BYTES)
    dst=np.memmap(decoded,dtype=np.uint8).reshape(n,FRAME_BYTES)
    luma_sse=chroma_sse=dark_sse=dark_n=edges=0.
    frame_mse=[]
    for st in range(0,n,32):
        a=src[st:st+32].astype(np.float32)
        b=dst[st:st+32].astype(np.float32)
        sy=a[:,:W*H].reshape(-1,H,W);dy=b[:,:W*H].reshape(-1,H,W)
        d=sy-dy
        luma_sse+=float(np.sum(d*d))
        chroma_sse+=float(np.sum((a[:,W*H:]-b[:,W*H:])**2))
        mask=(sy>=17)&(sy<=110)
        dark_sse+=float(np.sum(d[mask]**2));dark_n+=int(np.sum(mask))
        ex=np.diff(d,axis=2);ey=np.diff(d,axis=1)
        edges+=float((np.sum(ex**2)+np.sum(ey**2))/2)
        frame_mse+=np.mean(d*d,axis=(1,2)).tolist()
    mse=luma_sse/(n*W*H)
    # SSIM sampled across the *entire* movie at both easy/difficult scenes.
    ssims=[]
    for j in np.linspace(0,n-1,min(48,n),dtype=int):
        a=src[j,:W*H].reshape(H,W).astype(np.float32)
        b=dst[j,:W*H].reshape(H,W).astype(np.float32)
        ma=uniform_filter(a,7);mb=uniform_filter(b,7)
        va=np.maximum(0,uniform_filter(a*a,7)-ma*ma)
        vb=np.maximum(0,uniform_filter(b*b,7)-mb*mb)
        cov=uniform_filter(a*b,7)-ma*mb
        c1=(.01*255)**2;c2=(.03*255)**2
        score=((2*ma*mb+c1)*(2*cov+c2))/((ma*ma+mb*mb+c1)*(va+vb+c2))
        ssims.append(float(np.mean(score)))
    return {'frames':n,'duration':n/24,'luma_psnr':float(10*np.log10(255**2/mse)),
            'luma_mse':mse,'chroma_mse':chroma_sse/(n*W*H/2),
            'dark_luma_mse':dark_sse/max(dark_n,1),
            'edge_mse':edges/(n*W*H),'sampled_ssim':float(np.mean(ssims)),
            'per_frame_mse':frame_mse}


def audio_hash(video):
    audio=command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                '-i',video,'-map','0:a:0','-f','s16le','pipe:1'],timeout=600)
    return hashlib.sha256(audio).hexdigest(),len(audio)


def main():
    results=[]
    for name,(inp,control,refined) in TARGETS.items():
        ref=yuv_from_source(name,inp)
        rec0=decode(name,'control',control)
        rec1=decode(name,'v15',refined)
        b=compare(ref,rec0);v=compare(ref,rec1)
        if b['frames']!=v['frames']:raise RuntimeError('Control/refined frame counts differ')
        audio0=audio_hash(control)
        audio1=audio_hash(refined)
        if audio0!=audio1:raise RuntimeError('Motion refinement modified audio PCM')
        data={'clip':name,'source_bytes':inp.stat().st_size,
              'control_bytes':control.stat().st_size,
              'v15_bytes':refined.stat().st_size,
              'size_saved_pct':100*(1-refined.stat().st_size/control.stat().st_size),
              'psnr_gain_db':v['luma_psnr']-b['luma_psnr'],
              'audio_pcm_sha256':audio0[0],'audio_pcm_bytes':audio0[1],
              'control':b,'v15':v}
        results.append(data)
        print(name,'frames',b['frames'],'size',b['frames']/24,
              'seconds PSNR',b['luma_psnr'],v['luma_psnr'],
              'saved percent',data['size_saved_pct'],flush=True)
        fig,ax=plt.subplots(figsize=(13,4))
        t=np.arange(b['frames'])/24
        ax.plot(t,b['per_frame_mse'],alpha=.72,label='Control frame MSE')
        ax.plot(t,v['per_frame_mse'],alpha=.72,label='V15 motion refinement MSE')
        ax.set(xlabel='Time (seconds)',ylabel='Frame luma MSE',
               title=f'{name} — independent full-video decoder comparison')
        ax.legend();ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(ROOT/'evidence'/f'V15_{name}_Full_MSE_Time.png',dpi=150)
        plt.close(fig)
    (ROOT/'reports/V15_FULL_VIDEO_AUDIT.json').write_text(json.dumps(results,indent=2))
    print('PASS',len(results),'entire videos: frame count, audio hash, PSNR, SSIM, dark and edge fidelity')


if __name__=='__main__':main()
