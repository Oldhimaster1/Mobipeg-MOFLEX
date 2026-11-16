#!/usr/bin/env python3
"""Full-frame and stereo-eye quality audit: V8 -> V9 vs identical source.

No perceptual parity claim against Nintendo: its source scaling, color and
frame timing differ. Reports are engineering diagnostics, not MOS scores.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
from v9_texture_sweep import FRAME_BYTES, PIXELS, H, W, local_ssim


def open_video(path, total):
    if not path.exists(): raise FileNotFoundError(path)
    if path.stat().st_size != total * FRAME_BYTES:
        raise ValueError(f'Unexpected decoded size {path}: {path.stat().st_size}')
    return np.memmap(path, dtype=np.uint8, mode='r').reshape(total, FRAME_BYTES)


def rgb(frame):
    y = frame[:PIXELS].reshape(H, W).astype(np.float32)
    u = frame[PIXELS:PIXELS+PIXELS//4].reshape(H//2,W//2).astype(np.float32)
    v = frame[PIXELS+PIXELS//4:].reshape(H//2,W//2).astype(np.float32)
    u = np.repeat(np.repeat(u,2,axis=0),2,axis=1)-128
    v = np.repeat(np.repeat(v,2,axis=0),2,axis=1)-128
    z = (y-16)*1.164
    r = np.clip(z+1.596*v,0,255)
    g = np.clip(z-.391*u-.813*v,0,255)
    b = np.clip(z+2.018*u,0,255)
    return Image.fromarray(np.stack([r,g,b],axis=-1).astype(np.uint8),'RGB')


def sample_flat_grain(y, mask):
    x = y.astype(np.float32)
    highpass = np.abs(x-gaussian_filter(x, sigma=.6))
    return float(np.mean(highpass[mask]))


def profile(encoded, total):
    p = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','packet=size','-of','csv=p=0',str(encoded)],
        capture_output=True,check=True)
    packet = np.array([int(z) for z in p.stdout.split()],dtype=np.int64)
    if len(packet) != total: raise ValueError(f'Bad coded packet count in {encoded}')
    sec=[int(packet[t:t+48].sum()) for t in range(0,total,48)]
    # Last second of shorter duration deliberately not included in 1-second peak.
    return {'packet_count':len(packet), 'total_video_bytes':int(packet.sum()),
            'peak_1s_kbps':float(max(sec[:-1])*8/1000),
            'per_second_video_bytes':sec,
            'key_packets': None}


def run(args):
    out=args.out;out.mkdir(exist_ok=True,parents=True)
    total=args.original.stat().st_size//FRAME_BYTES
    dat={'Source':open_video(args.original,total),
         'Nintendo':open_video(args.nintendo,total),
         'MobiPEG V8':open_video(args.v8,total),
         'MobiPEG V9':open_video(args.v9,total)}
    per={k:{'mse_y':[],'mse_u':[],'mse_v':[],'edge_sse':0.,'edge_pixels':0,
            'sampled_ssim':[],'grain':[],'flicker':[], 'offset_sum':0.}
         for k in dat if k!='Source'}
    grainsource=[]
    cut = []
    # Detect actual cuts from left eye only at 1/8 resolution.
    for i in range(2,total,2):
        a=dat['Source'][i,:PIXELS].reshape(H,W)[::8,::8].astype(np.int16)
        b=dat['Source'][i-2,:PIXELS].reshape(H,W)[::8,::8].astype(np.int16)
        if float(np.abs(a-b).mean()) > 38: cut.append(i)
    sampled=set(j for t in range(0,total,24) for j in (t,t+1) if j<total)
    aftercuts=set(j for i in cut for j in range(i,min(i+12,total)))
    scored=sampled|aftercuts
    flat_indices=sorted(sampled)
    static_indices=set(i for i in scored if i>=2)
    for i in range(total):
        sframe=dat['Source'][i]; sy=sframe[:PIXELS].reshape(H,W)
        sg=sy.astype(np.int16)
        if i in scored:
            edge=(np.abs(np.diff(sg,axis=1,prepend=sg[:,:1]))>24) | (
                  np.abs(np.diff(sg,axis=0,prepend=sg[:1,:]))>24)
        else:
            edge=None
        flat=None
        if i in sampled:
            gy=np.abs(np.diff(sg,axis=0,prepend=sg[:1,:]))
            gx=np.abs(np.diff(sg,axis=1,prepend=sg[:,:1]))
            flat=(gy+gx)<12
            grainsource.append(sample_flat_grain(sy,flat))
        source_delta=None
        static=None
        if i in static_indices:
            source_delta=sg-dat['Source'][i-2,:PIXELS].reshape(H,W).astype(np.int16)
            static=(np.abs(source_delta)<=3)
        for name in per:
            dframe=dat[name][i]; dy=dframe[:PIXELS].reshape(H,W)
            d=sg-dy.astype(np.int16)
            sq=np.square(d,dtype=np.int32)
            rec=per[name]
            rec['mse_y'].append(float(sq.mean()))
            du=sframe[PIXELS:PIXELS+PIXELS//4].astype(np.int16)-dframe[PIXELS:PIXELS+PIXELS//4].astype(np.int16)
            dv=sframe[PIXELS+PIXELS//4:].astype(np.int16)-dframe[PIXELS+PIXELS//4:].astype(np.int16)
            rec['mse_u'].append(float(np.square(du,dtype=np.int32).mean()))
            rec['mse_v'].append(float(np.square(dv,dtype=np.int32).mean()))
            rec['offset_sum']+=float(d.mean())
            if edge is not None:
                rec['edge_sse']+=float(sq[edge].sum())
                rec['edge_pixels']+=int(edge.sum())
                rec['sampled_ssim'].append(local_ssim(sy,dy))
            if flat is not None: rec['grain'].append(sample_flat_grain(dy,flat))
            if static is not None and static.any():
                decd=dy.astype(np.int16)-dat[name][i-2,:PIXELS].reshape(H,W).astype(np.int16)
                ed=(source_delta[static]-decd[static]).astype(np.float32)
                rec['flicker'].append(float(np.mean(ed*ed)))
        if i%500==0:print(f'Audit frames {i}/{total}',flush=True)
    report={'eye_frames':total,'stereo_pairs':total//2,'scene_cut_frames':cut,
            'sampled_eye_frames':len(sampled),'source_flat_grain':float(np.mean(grainsource)),
            'measurement_note':'Nintendo was independently resized/color-converted, and some frames have temporal offsets; do not compare its PSNR directly.',
            'encoders':{}}
    for name,z in per.items():
        arr=np.array(z['mse_y']); y=float(np.mean(arr));
        fifth=float(np.percentile(10*np.log10(65025/np.maximum(arr,1e-8)),5))
        postcut=float(np.mean(arr[sorted(aftercuts)])) if aftercuts else None
        report['encoders'][name]={
            'psnr_y_dB':10*math.log10(65025/max(y,1e-9)),
            'psnr_u_dB':10*math.log10(65025/max(float(np.mean(z['mse_u'])),1e-9)),
            'psnr_v_dB':10*math.log10(65025/max(float(np.mean(z['mse_v'])),1e-9)),
            'mean_ssim_sampled':float(np.mean(z['sampled_ssim'])),
            'source_edge_mse_sampled':z['edge_sse']/z['edge_pixels'],
            'grain_in_source_flat_areas':float(np.mean(z['grain'])),
            'flicker_error_static':float(np.mean(z['flicker'])),
            'worst_12p5_percent_mse':float(np.sort(arr)[-max(1,total//8):].mean()),
            'fifth_percentile_psnr_y_dB':fifth,
            'after_cut_mse':postcut,
            'y_offset_mean':z['offset_sum']/total,
        }
    report['encoders']['MobiPEG V8']['payload']=profile(args.v8_file,total)
    report['encoders']['MobiPEG V9']['payload']=profile(args.v9_file,total)
    # Original comparator retained for size and packet-count context only.
    report['encoders']['Nintendo']['payload']=profile(args.nintendo_file,total)
    (out/'V9_FULL_QUALITY_AUDIT.json').write_text(json.dumps(report,indent=2))
    print('VALIDATED',json.dumps(report['encoders'],indent=2),flush=True)

    xx=np.arange(math.ceil(total/48))
    fig,axs=plt.subplots(3,1,figsize=(13,10),sharex=True)
    for name in ('MobiPEG V8','MobiPEG V9'):
        mse=np.array(per[name]['mse_y']); av=[float(np.mean(mse[i:i+48])) for i in range(0,total,48)]
        axs[0].plot(xx,10*np.log10(65025/np.maximum(av,1e-6)),label=name,lw=1.4)
        payload=report['encoders'][name]['payload']['per_second_video_bytes']
        axs[1].plot(xx,[z*8/1000 for z in payload],label=name,lw=1.2)
        diff=np.array(per[name]['mse_y'])-np.array(per['MobiPEG V8']['mse_y'])
        if name=='MobiPEG V9':
            axs[2].plot(xx,[float(np.mean(diff[i:i+48])) for i in range(0,total,48)],
                        color='tab:green',label='V9 minus V8 MSE',lw=1.4)
    axs[0].set_ylabel('Luma PSNR vs normalized source (dB)')
    axs[1].set_ylabel('Video payload (kbps)')
    axs[2].set_ylabel('MSE difference; lower is better')
    axs[2].set_xlabel('Time (seconds)')
    for axis in axs:axis.legend();axis.grid(alpha=.16)
    axs[0].set_title('V8 vs V9 — 100-second Avatar test, both eyes, decoded pixels')
    fig.tight_layout();fig.savefig(out/'V9_V8_PSNR_Bitrate_FrameError.png',dpi=160)
    plt.close(fig)

    # Large source/official/V8/V9 contact sheet; comparison may reveal
    # temporal offsets and color differences in the Nintendo reference.
    frames=[int(t*48) for t in (4,24,54,82,94)]
    columns=list(dat)
    pxw,pxh=400,224
    sheet=Image.new('RGB',(pxw*4,pxh*len(frames)+36),'#10141c')
    drawer=ImageDraw.Draw(sheet)
    for c,name in enumerate(columns):drawer.text((c*pxw+6,12),name,fill='white')
    for r,f in enumerate(frames):
        for c,name in enumerate(columns):
            sheet.paste(rgb(dat[name][f]),(c*pxw,r*pxh+36))
    sheet.save(out/'V9_Source_Nintendo_V8_V9_ContactSheet.png')


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--original',type=Path,required=True)
    ap.add_argument('--nintendo',type=Path,required=True)
    ap.add_argument('--v8',type=Path,required=True)
    ap.add_argument('--v9',type=Path,required=True)
    ap.add_argument('--v8-file',type=Path,required=True)
    ap.add_argument('--v9-file',type=Path,required=True)
    ap.add_argument('--nintendo-file',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    run(ap.parse_args())
