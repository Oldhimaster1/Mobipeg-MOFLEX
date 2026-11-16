#!/usr/bin/env python3
"""Compare *real detected scene-cut frames* across baseline and V14 output."""
from pathlib import Path
import sys

import numpy as np
from PIL import Image,ImageDraw,ImageFont

HERE=Path(__file__).resolve().parent
OLD=Path('/workspace/scratch/2571fa6fb025/work')
sys.path.insert(0,str(OLD))
from v9_full_quality_audit import rgb
from v9_texture_sweep import FRAME_BYTES

N=4826
FRAMES=[2976,1620,2296,1516]
FILES={
 'Nintendo':OLD/'nintendo_full_decoded.yuv',
 'V12':OLD/'v12_full/smoothfocus_decoded.yuv',
 'V13 Quality':HERE/'v13_release/Avatar_3D_MobiPEG_V13_Adaptive_Quality.moflex.decoded.yuv',
 'V14 Safe':HERE/'v14_release/Avatar_3D_MobiPEG_V14_cutfocus_CutGuard_Extra0_Guard020_decoded.yuv',
 'V14 CutFocus':HERE/'v14_release/Avatar_3D_MobiPEG_V14_cutfocus_CutGuard_Extra0_Guard050_decoded.yuv',
}


def font(sz):
    name='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(name,sz) if Path(name).exists() else ImageFont.load_default()


def main():
    dat={}
    for name,path in FILES.items():
        if path.stat().st_size!=N*FRAME_BYTES:raise ValueError('Wrong frame count '+name)
        dat[name]=np.memmap(path,dtype=np.uint8,mode='r').reshape(N,FRAME_BYTES)
    names=list(dat)
    w,h=400,224;top=42;side=45
    frames=[k for cut in FRAMES for k in (cut,cut+4)]
    sheet=Image.new('RGB',(len(names)*w,len(frames)*(h+side)+top),'#0b1320')
    draw=ImageDraw.Draw(sheet)
    for c,name in enumerate(names):
        draw.text((c*w+8,9),name,font=font(22),fill='white')
    for r,index in enumerate(frames):
        y=top+r*(h+side)
        annotation=(f'CUT {index/48:.3f}s' if index in FRAMES
                    else f'AFTER CUT {index/48:.3f}s')
        for c,name in enumerate(names):
            draw.text((c*w+8,y+8),annotation,font=font(17),fill='#d1dbeb')
            sheet.paste(rgb(dat[name][index]),(c*w,y+side))
    p=HERE/'V14_True_Scene_Cut_5_Way_Comparison.png'
    sheet.save(p,optimize=True)
    print('WROTE',p)

    names2=['V13 Quality','V14 Safe','V14 CutFocus']
    zoom=2
    picked=[2976,1620]
    zoomed=Image.new('RGB',(len(names2)*w*zoom,len(picked)*(h*zoom+side)),'#0b1320')
    d=ImageDraw.Draw(zoomed)
    for r,index in enumerate(picked):
        y=r*(h*zoom+side)
        for c,name in enumerate(names2):
            d.text((c*w*zoom+8,y+10),f'{name} — scene cut {index/48:.3f}s',
                   font=font(22),fill='white')
            frame=rgb(dat[name][index]).resize((w*zoom,h*zoom),resample=Image.Resampling.NEAREST)
            zoomed.paste(frame,(c*w*zoom,y+side))
    p2=HERE/'V14_Actual_Cuts_2x_Quality_Comparison.png'
    zoomed.save(p2,optimize=True)
    print('WROTE',p2)


if __name__=='__main__':main()
