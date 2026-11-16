#!/usr/bin/env python3
"""Experimental V11 decoder-aware stereo MOFLEX encoder.

Runs V10's validated R-D baseline, searches MobiClip-exact motion-vector
adjustments at multiple finer quantizer settings, and re-muxes the best
combination inside the baseline's measured video budget.
"""
import argparse
from pathlib import Path
import subprocess
import sys

def call(args):
    subprocess.run([str(x) for x in args],check=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('--encoder',type=Path,required=True)
    ap.add_argument('--probe',type=Path,required=True)
    ap.add_argument('--system-ffmpeg',default='ffmpeg')
    ap.add_argument('--output-folder',type=Path)
    ap.add_argument('--video-kbps',type=float,default=1266.5)
    ap.add_argument('--target-video-bytes',type=int)
    ap.add_argument('--peak-1s-kbps',type=float)
    ap.add_argument('--workers',type=int,default=5)
    ap.add_argument('--skip-v10',action='store_true',help='reuse complete V10 encoder cache')
    a=ap.parse_args()
    source=a.source.resolve()
    if not source.is_file():raise FileNotFoundError(source)
    root=Path(__file__).resolve().parent.parent
    out=(a.output_folder.resolve() if a.output_folder else
         source.parent/(source.stem+'_MobiPEG_V11'))
    out.mkdir(parents=True,exist_ok=True)
    enc=a.encoder.resolve(); probe=a.probe.resolve()
    if not a.skip_v10:
        cmd=[sys.executable,root/'V10/encode_stereo_v10.py',source,
             '--encoder',enc,'--probe',probe,'--system-ffmpeg',a.system_ffmpeg,
             '--output-folder',out,'--video-kbps',a.video_kbps,
             '--workers',a.workers]
        if a.target_video_bytes is not None:cmd+=['--target-video-bytes',a.target_video_bytes]
        if a.peak_1s_kbps is not None:cmd+=['--peak-1s-kbps',a.peak_1s_kbps]
        call(cmd)
    baseline=out/'V10'/f'{source.stem}_MobiPEG_V10_STEREO_3D.moflex'
    v10profile=out/'V10/V10_MOTION_DETAIL_REPORT.json'
    v9profile=out/'V9_TEXTURE_QUALITY_REPORT.json'
    if not all(x.is_file() for x in (baseline,v10profile,v9profile)):
        raise FileNotFoundError('V10 baseline not built; run without --skip-v10')
    if a.peak_1s_kbps is None:
        data=subprocess.run([str(probe),'-v','error','-select_streams','v:0',
             '-show_entries','packet=size','-of','csv=p=0',str(baseline)],
             capture_output=True,check=True).stdout
        packets=[int(x) for x in data.split()]
        peak=max(sum(packets[i:i+48]) for i in range(0,len(packets)-47,48))*8/1000
    else:
        peak=a.peak_1s_kbps
    target=source.stem+'_MobiPEG_V11_STEREO_3D.moflex'
    call([sys.executable,root/'V11/v11_full_reencode.py',
          '--v9-profile',v9profile,'--v10-profile',v10profile,
          '--gop-folder',out,'--source',source,
          '--encoder',enc,'--probe',probe,'--out',out/'V11',
          '--workers',a.workers,'--peak-1s-kbps',max(1,peak),
          '--name',target])
    print('V11 3D MOFLEX:',out/'V11'/target)
    print('Software decoding passed individual candidate tests; Old 3DS verification is required.')

if __name__=='__main__':main()
