#!/usr/bin/env python3
"""Non-destructive official Nintendo vs MobiPEG stereo image diagnostics.

Align both eyes by coded-frame parity before inferring image differences.
Important: this is not yet a calibrated subjective/perceptual metric.
"""
import json
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter, uniform_filter

W,H=400,224
PIX=W*H
FS=PIX*3//2
HOME=Path(__file__).resolve().parent
SRC=HOME/'Avatar_eyes_400x224_48fps.yuv'
NIN=HOME/'nintendo_full_decoded.yuv'
V10=HOME/'v10_full/v10_decoded_400x224.yuv'
OUT=HOME/'v11_forensics'

def mm(path):
    if path.stat().st_size % FS:raise ValueError(path)
    n=path.stat().st_size//FS
    return np.memmap(path,dtype=np.uint8,mode='r').reshape(n,FS)

def yframe(data,i,step=2):
    return data[i,:PIX].reshape(H,W)[::step,::step].astype(np.float32)

def mse(a,b):return float(np.mean((a-b)**2))

def gray_affine(a,b):
    x=a.reshape(-1); y=b.reshape(-1)
    cv=float(np.mean((x-x.mean())*(y-y.mean())))
    vr=float(np.var(y))
    gain=cv/max(vr,1e-6)
    offs=float(x.mean()-gain*y.mean())
    return mse(a,np.clip(gain*b+offs,0,255)),gain,offs

def structural(x,y):
    sx=uniform_filter(x,size=7);sy=uniform_filter(y,size=7)
    vx=uniform_filter(x*x,size=7)-sx*sx
    vy=uniform_filter(y*y,size=7)-sy*sy
    cov=uniform_filter(x*y,size=7)-sx*sy
    c1=(255*.01)**2;c2=(255*.03)**2
    return float(np.mean(((2*sx*sy+c1)*(2*cov+c2))/((sx*sx+sy*sy+c1)*(vx+vy+c2))))

def blockiness(x):
    # Excess 4x4-boundary gradients vs equally distributed non-boundaries.
    # Input is 400x224, not decimated; measures both horizontal and vertical.
    dx=np.abs(np.diff(x,axis=1));dy=np.abs(np.diff(x,axis=0))
    bx=dx[:,np.arange(1,W)%4==0].mean();nx=dx[:,np.arange(1,W)%4!=0].mean()
    by=dy[np.arange(1,H)%4==0,:].mean();ny=dy[np.arange(1,H)%4!=0,:].mean()
    return float(((bx-nx)+(by-ny))/2)

def image_stats(src,out):
    hs=np.abs(src-gaussian_filter(src,.65))
    ho=np.abs(out-gaussian_filter(out,.65))
    edge=(np.abs(np.diff(src,axis=0,prepend=src[:1]))+
          np.abs(np.diff(src,axis=1,prepend=src[:,:1])))>24
    smooth=(np.abs(np.diff(src,axis=0,prepend=src[:1]))+
            np.abs(np.diff(src,axis=1,prepend=src[:,:1])))<12
    return {'highpass_ratio':float(ho.mean()/max(hs.mean(),1e-8)),
            'source_edge_highpass_ratio':float(ho[edge].mean()/max(hs[edge].mean(),1e-8))
              if np.any(edge) else 0.,
            'source_flat_highpass':float(ho[smooth].mean()) if np.any(smooth) else 0.,
            'blockiness_minus_source':blockiness(out)-blockiness(src)}

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    s=mm(SRC); n=mm(NIN);v=mm(V10)
    assert s.shape==n.shape==v.shape
    frames=s.shape[0]
    sample=[j for i in range(24,frames-24,24) for j in (i,i+1) if j<frames-24]
    # Match the same eye only: index offset MUST be even.
    results=[]
    for shift in range(-16,17,2):
        raw=[];cal=[];ss=[]
        for i in sample:
            src=yframe(s,i)
            dst=yframe(n,i+shift)
            raw.append(mse(src,dst))
            em,_,_=gray_affine(src,dst)
            cal.append(em)
            if i%6==0:ss.append(structural(src,dst))
        results.append({'shift_eye_frames':shift//2,'shift_coded_frames':shift,
                        'mse':float(np.mean(raw)),
                        'affine_calibrated_mse':float(np.mean(cal)),
                        'ssim':float(np.mean(ss))})
    best=min(results,key=lambda z:z['affine_calibrated_mse'])
    # Repeat at official best shift for representative reference samples.
    stats={k:[] for k in ('Nintendo','V10')}
    for i in sample[::4]:
        orig=yframe(s,i,1)
        ni=yframe(n,i+best['shift_coded_frames'],1)
        vi=yframe(v,i,1)
        stats['Nintendo'].append({'mse':mse(orig,ni),'affine_mse':gray_affine(orig,ni)[0],
                                  'ssim':structural(orig,ni),**image_stats(orig,ni)})
        stats['V10'].append({'mse':mse(orig,vi),'affine_mse':gray_affine(orig,vi)[0],
                            'ssim':structural(orig,vi),**image_stats(orig,vi)})
    aggr={name:{key:float(np.mean([t[key] for t in values]))
                for key in values[0]} for name,values in stats.items()}
    # Inspect the entire decoded timeline. A sample every half-second can
    # hide periodic bad frames (decoder mode gaps or timestamp/cadence bugs).
    full_mse={'Nintendo':[],'V10':[]}
    shift_mse={-4:[], -2:[], 0:[], 2:[], 4:[]}
    for i in range(4,frames-4):
        orig=yframe(s,i,4)
        full_mse['Nintendo'].append(mse(orig,yframe(n,i,4)))
        full_mse['V10'].append(mse(orig,yframe(v,i,4)))
        for delta in shift_mse:
            shift_mse[delta].append(mse(orig,yframe(n,i+delta,4)))
    offsets=np.arange(4,frames-4)
    modulo={k:[float(np.mean(np.asarray(vals)[offsets%48==j])) for j in range(48)]
            for k,vals in full_mse.items()}
    near=np.stack([np.asarray(z) for z in shift_mse.values()])
    which=np.argmin(near,axis=0)
    values=list(shift_mse)
    best_near={str(delta):int((which==j).sum()) for j,delta in enumerate(values)}
    temporal={'nintendo_best_nearby_shift_counts':best_near,
              'nintendo_mse_same_frame':float(np.mean(full_mse['Nintendo'])),
              'nintendo_mse_best_local_shift':float(np.mean(np.min(near,axis=0))),
              'v10_mse_same_frame':float(np.mean(full_mse['V10'])),
              'mse_by_frame_mod48':modulo}
    result={'frames':frames,'alignment_trials':results,'best_nintendo_alignment':best,
            'representative_image_stats':aggr,
            'full_timeline':temporal,
            'warning':'Nintendo and this normalized input may differ in resampling/color/temporal preprocessing; values are not direct perceptual MOS scores.'}
    (OUT/'official_v10_alignment_and_artifact_audit.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'best_alignment':best,'stats':aggr,
          'temporal_summary':{k:v for k,v in temporal.items() if k!='mse_by_frame_mod48'}},indent=2))

if __name__=='__main__':main()
