#!/usr/bin/env python3
"""Produce a native MobiPEG V13 per-frame quantizer plan.

Accepts planar YUV420p frames.  By default expects interleaved left/right
stereo eyes, at two coded frames per displayed 3D frame.  Q is an actual
Mobiclip decoder quantizer (12..59), not the six-step x264 -qp remainder.

This is a safe heuristic for experiments, not a file-size or visual-quality
guarantee.  For stringent size targets, trial encodes and R-D selection are
still required.
"""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np


def make_plan(raw: Path, width: int, height: int, base: int, eye_stride: int,
              strength: int, mode: str, max_delta: int):
    if width%2 or height%2 or width<=0 or height<=0:
        raise ValueError('YUV420p width and height must be positive and even')
    if not 12<=base<=59 or strength not in (1,2) or max_delta not in (1,2,3):
        raise ValueError('Q must be 12..59; strength 1..2; max delta 1..3')
    frame_bytes=width*height*3//2
    if raw.stat().st_size%frame_bytes:
        raise ValueError('Raw file length is not a multiple of one YUV420p frame')
    frames=raw.stat().st_size//frame_bytes
    if not frames or frames%eye_stride:
        raise ValueError('Frame count must be positive and divisible by eye stride')
    arrays=np.memmap(raw,mode='r',dtype=np.uint8).reshape(frames,frame_bytes)
    count=frames//eye_stride
    activity=np.empty(count,dtype=np.float64)
    detail=np.empty(count,dtype=np.float64)
    cuts=np.empty(count,dtype=np.float64)
    prev=None
    for j in range(count):
        # The same quantizer is assigned to all eyes of a stereo pair.
        eye=[]
        for k in range(eye_stride):
            cur=arrays[j*eye_stride+k,:width*height].reshape(height,width)[::4,::4]
            eye.append(cur.astype(np.int16))
        act=0.0 if prev is None else float(np.mean(
            [np.abs(a-b).mean() for a,b in zip(eye,prev)]))
        activity[j]=act
        detail[j]=float(np.mean([np.abs(np.diff(a,axis=0)).mean()+
                                 np.abs(np.diff(a,axis=1)).mean() for a in eye]))
        cuts[j]=act
        prev=eye
    def rank(x):
        if len(x)<2:return np.full(len(x),.5)
        return (np.argsort(np.argsort(x))+.5)/len(x)
    motion=rank(activity)
    gradient=rank(detail)
    if mode=='motion':importance=motion
    elif mode=='detail':importance=gradient
    elif mode=='balanced':importance=.55*motion+.45*gradient
    else:raise ValueError('Unknown mode')
    q=np.full(count,base,dtype=np.int16)
    for j in range(count):
        if importance[j]>.76:q[j]-=strength
        elif importance[j]<.28:q[j]+=1
        # Protect the first eye pair after an unusually strong scene cut.
        if j>0 and cuts[j]>35:q[j]=min(q[j],base-1)
    # Avoid quantizer pumping within smooth motion.  At a real scene cut a
    # larger step is okay because the source itself is discontinuous.
    for j in range(1,count):
        if cuts[j]<=35:
            q[j]=np.clip(q[j],q[j-1]-max_delta,q[j-1]+max_delta)
    q=np.clip(q,12,59)
    return np.repeat(q,eye_stride).astype(int).tolist()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path,help='planar YUV420p coded eye-frame file')
    p.add_argument('output',type=Path,help='text file, one actual Q per coded frame')
    p.add_argument('--width',type=int,default=400)
    p.add_argument('--height',type=int,default=224)
    p.add_argument('--base-quant',type=int,default=32)
    p.add_argument('--eye-stride',type=int,choices=[1,2],default=2)
    p.add_argument('--strength',type=int,choices=[1,2],default=1)
    p.add_argument('--mode',choices=['balanced','motion','detail'],default='balanced')
    p.add_argument('--max-delta',type=int,choices=[1,2,3],default=1)
    a=p.parse_args()
    levels=make_plan(a.input,a.width,a.height,a.base_quant,a.eye_stride,
                     a.strength,a.mode,a.max_delta)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(''.join(f'{z}\n' for z in levels))
    print('WROTE',a.output,'coded frames',len(levels),
          'actual Q distribution',dict(sorted(Counter(levels).items())))

if __name__=='__main__':main()
