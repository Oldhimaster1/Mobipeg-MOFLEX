#!/usr/bin/env python3
"""Experimental V10 quality encoder for an HSBS/FSBS stereo movie.

First builds the decoded-and-verified V9 reference with its normalized
source cache, then searches V10 restored-motion and finer-quantizer trials.
All improvements must fit the V9 video-packet budget.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

def call(args):
    subprocess.run([str(x) for x in args],check=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--encoder',type=Path,required=True)
    p.add_argument('--probe',type=Path,required=True)
    p.add_argument('--system-ffmpeg',default='ffmpeg')
    p.add_argument('--output-folder',type=Path)
    p.add_argument('--video-kbps',type=float,default=1266.5)
    p.add_argument('--target-video-bytes',type=int)
    p.add_argument('--peak-1s-kbps',type=float)
    p.add_argument('--workers',type=int,default=5)
    p.add_argument('--skip-v9',action='store_true',help='reuse complete validated V9 baseline')
    a=p.parse_args()
    source=a.source.resolve()
    if not source.is_file():raise FileNotFoundError(source)
    root=Path(__file__).resolve().parent.parent
    out=(a.output_folder.resolve() if a.output_folder else
         source.parent/(source.stem+'_MobiPEG_V10'))
    out.mkdir(parents=True,exist_ok=True)
    encoder=a.encoder.resolve();probe=a.probe.resolve()
    if not a.skip_v9:
        cmd=[sys.executable,root/'V9/encode_stereo_v9.py',source,
             '--encoder',encoder,'--probe',probe,'--system-ffmpeg',a.system_ffmpeg,
             '--output-folder',out,'--video-kbps',a.video_kbps,
             '--workers',a.workers]
        if a.target_video_bytes is not None:cmd+=['--target-video-bytes',a.target_video_bytes]
        if a.peak_1s_kbps is not None:cmd+=['--peak-1s-kbps',a.peak_1s_kbps]
        call(cmd)
    profile=out/'V9_TEXTURE_QUALITY_REPORT.json'
    base=out/(source.stem+'_MobiPEG_V9_STEREO_3D.moflex')
    if not profile.is_file() or not base.is_file():
        raise FileNotFoundError('V9 baseline/cache missing; run without --skip-v9')
    if a.peak_1s_kbps is None:
        result=subprocess.run([str(probe),'-v','error','-select_streams','v:0',
            '-show_entries','packet=size','-of','csv=p=0',str(base)],
            capture_output=True,check=True)
        pkt=[int(z) for z in result.stdout.split()]
        peak=max(sum(pkt[i:i+48]) for i in range(0,len(pkt)-47,48))*8/1000
    else:peak=a.peak_1s_kbps
    name=source.stem+'_MobiPEG_V10_STEREO_3D.moflex'
    call([sys.executable,root/'V10/v10_full_reencode.py',
          '--profile',profile,'--gop-folder',out,
          '--source',source,'--encoder',encoder,'--probe',probe,
          '--out',out/'V10','--name',name,'--workers',a.workers,
          '--peak-1s-kbps',max(1,peak)])
    print('V10 stereo MOFLEX:',out/'V10'/name)
    print('Physical Old 3DS verification is required before publication.')

if __name__=='__main__':main()
