#!/usr/bin/env python3
"""Enhance an existing MobiPEG frame-Q plan around actual scene changes.

The codec requires one quantizer per coded eye frame.  This helper detects
large same-eye changes in raw planar YUV420p and protects a short period
after each cut while keeping stereo pairs synchronized.  It deliberately
does not promise a fixed output bitrate; run constrained R-D trials for that.
"""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np


def detect_cuts(frames, width, height, eye_stride, threshold):
    ysize=width*height
    small=[]
    for i in range(frames.shape[0]):
        small.append(frames[i,:ysize].reshape(height,width)[::8,::8].astype(np.int16))
    changes=[]
    for i in range(eye_stride,len(small),eye_stride):
        v=np.mean([np.abs(small[i+k]-small[i+k-eye_stride]).mean()
                   for k in range(eye_stride)])
        if v>threshold:changes.append(i)
    return changes


def protect(plan,cuts,frame_count,eye_stride,mode,frames=None,width=400,height=224):
    if len(plan)!=frame_count or frame_count%eye_stride:
        raise ValueError('Wrong quantizer count for interleaved source')
    q=np.array(plan,dtype=np.int16)
    if np.any(q<12) or np.any(q>59):raise ValueError('Mobiclip quantizers must be 12..59')
    if eye_stride==2 and not np.all(q[0::2]==q[1::2]):
        raise ValueError('Stereo eyes must share one quantizer')
    per=q[::eye_stride].copy()
    marked=np.zeros(len(per),dtype=bool)
    for cut in cuts:
        if cut%eye_stride or cut<0 or cut>=frame_count:
            raise ValueError(f'Illegal cut frame {cut}')
        start=cut//eye_stride
        if mode=='safe':length=2;delta=-1
        elif mode=='cutfocus':length=6;delta=-2
        else:raise ValueError(mode)
        per[start:start+length]+=delta
        marked[start:start+12]=True
    if mode=='cutfocus' and frames is not None:
        # Save bits where same-eye temporal motion is very low, well away
        # from cuts.  Never compare left eye directly to right eye.
        pixels=frames[:,:width*height]
        motion=np.zeros(len(per),dtype=np.float32)
        for j in range(1,len(per)):
            i=j*eye_stride
            motion[j]=np.mean(np.abs(pixels[i:i+eye_stride].astype(np.int16)-
                                     pixels[i-eye_stride:i].astype(np.int16)))
        allowed=np.flatnonzero(~marked)
        if len(allowed):
            threshold=float(np.percentile(motion[allowed],45))
            per[np.logical_and(~marked,motion<threshold)]+=1
    return np.repeat(np.clip(per,12,59),eye_stride).astype(int).tolist()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('raw',type=Path,help='Input YUV420p (frame order matches plan)')
    p.add_argument('old_plan',type=Path,help='One actual Mobiclip Q per coded frame')
    p.add_argument('new_plan',type=Path)
    p.add_argument('--width',type=int,default=400)
    p.add_argument('--height',type=int,default=224)
    p.add_argument('--eye-stride',type=int,choices=[1,2],default=2)
    p.add_argument('--cut-threshold',type=float,default=38.0)
    p.add_argument('--mode',choices=['safe','cutfocus'],default='safe')
    p.add_argument('--known-cuts',type=Path,help='Optional text file: one coded-frame index per cut')
    a=p.parse_args()
    if min(a.width,a.height)<=0 or a.width%2 or a.height%2:
        raise ValueError('YUV420p dimensions must be positive and even')
    frame_size=a.width*a.height*3//2
    if a.raw.stat().st_size%frame_size:raise ValueError('Bad planar raw frame size')
    n=a.raw.stat().st_size//frame_size
    if not n or n%a.eye_stride:raise ValueError('Bad coded frame count')
    src=np.memmap(a.raw,dtype=np.uint8,mode='r').reshape(n,frame_size)
    q=[int(z) for z in a.old_plan.read_text().split()]
    if a.known_cuts:
        cuts=[int(x) for x in a.known_cuts.read_text().split()]
    else:
        cuts=detect_cuts(src,a.width,a.height,a.eye_stride,a.cut_threshold)
    result=protect(q,cuts,n,a.eye_stride,a.mode,src,a.width,a.height)
    a.new_plan.parent.mkdir(parents=True,exist_ok=True)
    a.new_plan.write_text(''.join(f'{z}\n' for z in result))
    print('WROTE',a.new_plan,'coded_frames',n,'detected_cuts',len(cuts),
          'Q_distribution',dict(sorted(Counter(result).items())))


if __name__=='__main__':main()
