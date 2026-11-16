#!/usr/bin/env python3
"""Locate per-frame quality regressions that aggregate PSNR can conceal."""
import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
OLD=Path('/workspace/scratch/2571fa6fb025/work')
FRAME_BYTES=400*224*3//2
PIXELS=400*224
N=4826


def raw_mse(path,src):
    decoded=np.memmap(path,dtype=np.uint8,mode='r').reshape(N,FRAME_BYTES)
    out=np.empty(N)
    for k in range(0,N,64):
        z=slice(k,min(k+64,N))
        error=src[z,:PIXELS].astype(np.int16)-decoded[z,:PIXELS].astype(np.int16)
        out[z]=np.square(error,dtype=np.float32).mean(axis=1)
    return out


def main():
    src=np.memmap(OLD/'Avatar_eyes_400x224_48fps.yuv',dtype=np.uint8,mode='r').reshape(N,FRAME_BYTES)
    v13=raw_mse(HERE/'v13_release/Avatar_3D_MobiPEG_V13_Adaptive_Quality.moflex.decoded.yuv',src)
    v14=raw_mse(HERE/'v14_release/Avatar_3D_MobiPEG_V14_cutfocus_CutGuard_Extra4000_decoded.yuv',src)
    psnr13=10*np.log10(65025/np.maximum(v13,1e-9))
    psnr14=10*np.log10(65025/np.maximum(v14,1e-9))
    diff=psnr14-psnr13
    worst=np.argsort(psnr14)[:int(np.ceil(.05*N))]
    regress=np.argsort(diff)[:60]
    out={'p5_v13':float(np.percentile(psnr13,5)),
         'p5_v14':float(np.percentile(psnr14,5)),
         'worst_v14_frames':[{'frame':int(i),'time_s':i/48,
                             'gop':int(i//96),'psnr_v13':float(psnr13[i]),
                             'psnr_v14':float(psnr14[i]),'gain_db':float(diff[i])}
                            for i in worst],
         'largest_regressions':[{'frame':int(i),'time_s':i/48,
                                'gop':int(i//96),'psnr_v13':float(psnr13[i]),
                                'psnr_v14':float(psnr14[i]),'gain_db':float(diff[i])}
                               for i in regress],
         'per_gop_delta_mse':{str(i):float(np.mean(v14[i*96:min((i+1)*96,N)]-
                                                      v13[i*96:min((i+1)*96,N)]))
                              for i in range(51) if i*96<N}}
    (HERE/'v14_release/V14_WORST_FRAME_DIAGNOSTICS.json').write_text(json.dumps(out,indent=2))
    print('P5 V13',out['p5_v13'],'V14',out['p5_v14'])
    print('Largest regressions',out['largest_regressions'][:12])
    from collections import Counter
    print('Worst 5% GOPs',Counter(x['gop'] for x in out['worst_v14_frames']).most_common(12))


if __name__=='__main__':main()
