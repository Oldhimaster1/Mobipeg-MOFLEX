#!/usr/bin/env python3
"""Produce honest, frame-aligned V15 rate-distortion charts and comparisons."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image,ImageDraw,ImageFont

from quality_sweep import ROOT,CLIPS,FRAME_BYTES,prepare
from stereo_sweep import FRAME_BYTES as SBS_BYTES,source as stereo_source

OUT=ROOT/'evidence'
OUT.mkdir(exist_ok=True)
CODEC=json.loads((ROOT/'reports/V15_CODEC_SWEEP.json').read_text())
STEREO=json.loads((ROOT/'reports/V15_STEREO_SWEEP.json').read_text())
SELECTED=['anime','anime_late','anime_end','badapple','badapple_late','yip',
          'yip_late','nature','sonic','stonelifts','sixtwo2','gamecube',
          'yippee_jazz','avatar_left','avatar_title']


def row(clip,mode,full=CODEC):
    return next(x for x in full if x['clip']==clip and x['variant']==mode)


def font(sz=22):
    p=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    return ImageFont.truetype(str(p),sz) if p.exists() else ImageFont.load_default()


def rgb_yuv420(buffer,w,h,frame):
    fb=w*h*3//2
    payload=buffer[frame*fb:(frame+1)*fb]
    a=np.frombuffer(payload,dtype=np.uint8)
    if len(a)!=fb:raise ValueError('Frame index out of range')
    yy=a[:w*h].reshape(h,w).astype(np.float32)
    uv_size=w*h//4
    u=a[w*h:w*h+uv_size].reshape(h//2,w//2).astype(np.float32)
    v=a[w*h+uv_size:].reshape(h//2,w//2).astype(np.float32)
    u=np.repeat(np.repeat(u,2,axis=0),2,axis=1)-128
    v=np.repeat(np.repeat(v,2,axis=0),2,axis=1)-128
    # Common studio-range BT.709 treatment across all compared videos.
    luma=1.1644*(yy-16)
    rgb=np.stack([luma+1.7927*v,
                  luma-0.2132*u-0.5329*v,
                  luma+2.1124*u],axis=-1)
    return Image.fromarray(np.clip(rgb,0,255).astype(np.uint8),'RGB')


def decoded(movie,w,h):
    from quality_sweep import ENC,command
    return command([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                    '-i',movie,'-map','0:v:0','-pix_fmt','yuv420p',
                    '-f','rawvideo','pipe:1'],timeout=300)


def comparison(choices,filename,w,h,caption_height=45):
    columns=len(choices[0][1]);rows=len(choices)
    canvas=Image.new('RGB',(w*columns,rows*(h+caption_height)),(11,17,27))
    d=ImageDraw.Draw(canvas)
    f=font(19)
    for i,(rowname,items) in enumerate(choices):
        for j,(label,img) in enumerate(items):
            x=j*w;y=i*(h+caption_height)
            canvas.paste(img,(x,y+caption_height))
            d.text((x+8,y+10),f'{rowname} · {label}',font=f,fill='white')
    out=OUT/filename
    canvas.save(out,optimize=True)
    return out


def samples_chart():
    labels=[];gains=[];savings=[]
    data=[]
    for clip in SELECTED:
        before=row(clip,'baseline');after=row(clip,'mvref0')
        gain=after['luma_psnr']-before['luma_psnr']
        saved=100*(1-after['file_bytes']/before['file_bytes'])
        labels.append(clip.replace('_',' '));gains.append(gain);savings.append(saved)
        data.append({'clip':clip,'baseline_bytes':before['file_bytes'],
                     'v15_bytes':after['file_bytes'],
                     'size_change_pct':-saved,'baseline_psnr':before['luma_psnr'],
                     'v15_psnr':after['luma_psnr'],'psnr_gain_db':gain,
                     'baseline_ssim':before['ssim'],'v15_ssim':after['ssim']})
    y=np.arange(len(labels))
    fig,axs=plt.subplots(1,2,figsize=(15,8.5),sharey=True)
    fig.patch.set_facecolor('#101725')
    for ax in axs:
        ax.set_facecolor('#142034')
        ax.tick_params(colors='white',labelsize=10)
        ax.spines[['top','right']].set_visible(False)
        ax.spines[['left','bottom']].set_color('#52627d')
        ax.grid(axis='x',alpha=.20,color='white')
        ax.axvline(0,color='#a1a8ba',lw=1)
    axs[0].barh(y,gains,color=['#36cfc0' if z>=0 else '#ef847d' for z in gains])
    axs[1].barh(y,savings,color=['#73aaff' if z>=0 else '#ef847d' for z in savings])
    axs[0].set_yticks(y,labels=labels,color='white')
    axs[0].invert_yaxis()
    axs[0].set_xlabel('PSNR improvement (dB)  → better',color='white')
    axs[1].set_xlabel('File size saved (%)  → smaller',color='white')
    axs[0].set_title('Quality change vs same-Q control',color='white',pad=13)
    axs[1].set_title('Size change vs same-Q control',color='white',pad=13)
    fig.suptitle('MobiPEG V15 motion refinement — 15 real-video clips, Q30, 24 FPS',
                 color='white',fontsize=16)
    fig.subplots_adjust(left=.17,right=.97,top=.85,bottom=.10,wspace=.08)
    fig.savefig(OUT/'V15_15_Samples_Quality_And_Size.png',dpi=165,facecolor=fig.get_facecolor())
    plt.close(fig)
    (OUT/'V15_15_Samples_Summary.json').write_text(json.dumps(data,indent=2))
    print('CHART',len(data),'clips improved PSNR',sum(x['psnr_gain_db']>0 for x in data),
          'reduced file size',sum(x['size_change_pct']<0 for x in data),flush=True)
    return data


def frame_comparisons_2d():
    choices=[]
    for clip,at in [('anime',42),('badapple',50),('stonelifts',56),
                    ('sixtwo2',50),('avatar_title',65),('gamecube',80)]:
        src=prepare(clip)
        control=row(clip,'baseline')['path']
        variant=row(clip,'mvref0')['path']
        original=rgb_yuv420(src.read_bytes(),400,240,at)
        before=rgb_yuv420(decoded(control,400,240),400,240,at)
        after=rgb_yuv420(decoded(variant,400,240),400,240,at)
        choices.append((clip,[('Source',original),('Q30 control',before),('V15 MVref',after)]))
    return comparison(choices,'V15_Six_Content_Frame_Comparisons.png',400,240)


def frame_comparisons_3d():
    choices=[]
    for name,at in [('avatar_action',48),('avatar_water',55),
                    ('avatar_title',72),('sbs_reference',60)]:
        src=stereo_source(name)
        old=next(x for x in STEREO if x['clip']==name and x['variant']=='control')
        new=next(x for x in STEREO if x['clip']==name and x['variant']=='v15_mvref0')
        original=rgb_yuv420(src.read_bytes(),800,224,at)
        before=rgb_yuv420(decoded(old['path'],800,224),800,224,at)
        after=rgb_yuv420(decoded(new['path'],800,224),800,224,at)
        choices.append((name,[('Source left',original.crop((0,0,400,224))),
              ('Control left',before.crop((0,0,400,224))),
              ('V15 left',after.crop((0,0,400,224))),
              ('V15 right',after.crop((400,0,800,224)))]))
    return comparison(choices,'V15_Real_3D_Stereo_Comparisons.png',400,224)


def avatar_full_comparisons():
    root=ROOT.parent
    oldfolder=Path('/workspace/scratch/2571fa6fb025/work')
    refs={
      'Source':oldfolder/'Avatar_eyes_400x224_48fps.yuv',
      'Nintendo':oldfolder/'nintendo_full_decoded.yuv',
      'V14 Safe':root/'v14_release/Avatar_3D_MobiPEG_V14_cutfocus_CutGuard_Extra0_Guard020_decoded.yuv',
      'V15 R-D':root/'v15_avatar_lab/V15_Avatar_Full_Decoded.yuv',
    }
    for path in refs.values():
        if not path.is_file():raise FileNotFoundError(path)
    columns=[]
    for idx,label in [(46*96+10,'Title 92.2s'),(46*96+70,'Title 93.5s'),
                      (47*96+24,'Title 94.5s'),(47*96+72,'Title 95.5s')]:
        images=[]
        for name,path in refs.items():
            with path.open('rb') as inp:
                inp.seek(idx*(400*224*3//2))
                frm=inp.read(400*224*3//2)
            images.append((name,rgb_yuv420(frm,400,224,0)))
        columns.append((label,images))
    return comparison(columns,'V15_V14_Nintendo_Aligned_Title_Comparison.png',400,224)


def main():
    stats=samples_chart()
    prints=[frame_comparisons_2d(),frame_comparisons_3d(),avatar_full_comparisons()]
    for p in prints:print('IMAGE',p,p.stat().st_size,flush=True)
    print('SUMMARY',json.dumps({'clips':len(stats),
       'psnr_improved':sum(s['psnr_gain_db']>0 for s in stats),
       'files_smaller':sum(s['size_change_pct']<0 for s in stats),
       'average_psnr_gain':float(np.mean([s['psnr_gain_db'] for s in stats])),
       'average_size_saved_pct':float(-np.mean([s['size_change_pct'] for s in stats]))},indent=2),flush=True)


if __name__=='__main__':main()
