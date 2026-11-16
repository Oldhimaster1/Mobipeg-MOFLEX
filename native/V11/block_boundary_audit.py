#!/usr/bin/env python3
"""Source-relative 4x4 block boundary audit of Nintendo, V10 and V11.

The official Nintendo stream may be temporally offset from the normalized
source, so report this *only* as a compression artifact proxy, not MOS.
"""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
W,H=400,224
FS=W*H*3//2
PATHS={
    'Source':ROOT/'Avatar_eyes_400x224_48fps.yuv',
    'Nintendo':ROOT/'nintendo_full_decoded.yuv',
    'V10':ROOT/'v10_full/v10_decoded_400x224.yuv',
    'V11':ROOT/'v11_full/v11_decoded_400x224.yuv',
}

def load(path):
    n=path.stat().st_size//FS
    assert n*FS==path.stat().st_size
    return np.memmap(path,mode='r',dtype='uint8').reshape(n,FS)

def block(y):
    dx=np.abs(np.diff(y,axis=1))
    dy=np.abs(np.diff(y,axis=0))
    return float(((dx[:,np.arange(1,W)%4==0].mean()-dx[:,np.arange(1,W)%4!=0].mean())+
            (dy[np.arange(1,H)%4==0,:].mean()-dy[np.arange(1,H)%4!=0,:].mean()))/2)

def main():
    data={k:load(v) for k,v in PATHS.items()}
    n=min(map(len,data.values()))
    assert n>400
    frames=range(18,n-18,20)
    rows=[]
    for i in frames:
        nums={}
        for name,p in data.items():
            y=p[i,:W*H].reshape(H,W).astype(np.float32)
            nums[name]=block(y)
        rows.append({'frame':i,**nums,
                     'Nintendo_source_excess':nums['Nintendo']-nums['Source'],
                     'V10_source_excess':nums['V10']-nums['Source'],
                     'V11_source_excess':nums['V11']-nums['Source']})
    result={'sample_frames':len(rows),'frame_count':n,
        'mean_boundary_excess':{name:float(np.mean([r[f'{name}_source_excess'] for r in rows]))
            for name in ('Nintendo','V10','V11')},
        'median_boundary_excess':{name:float(np.median([r[f'{name}_source_excess'] for r in rows]))
            for name in ('Nintendo','V10','V11')},
        'caveat':'This is an uncalibrated boundary-contrast proxy; temporal resampling differs for Nintendo.'}
    out=Path(__file__).resolve().parent/'V11_BLOCK_BOUNDARY_AUDIT.json'
    out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
