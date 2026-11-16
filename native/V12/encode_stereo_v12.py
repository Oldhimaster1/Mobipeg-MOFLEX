#!/usr/bin/env python3
"""Experimental stereo MOFLEX V12: smoothness-biased, detail-guarded encode."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

def call(args):subprocess.run([str(x) for x in args],check=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('--encoder',type=Path,required=True)
    ap.add_argument('--probe',type=Path,required=True)
    ap.add_argument('--system-ffmpeg',default='ffmpeg')
    ap.add_argument('--output-folder',type=Path)
    ap.add_argument('--video-kbps',type=float,default=1266.5)
    ap.add_argument('--target-video-bytes',type=int)
    ap.add_argument('--workers',type=int,default=5)
    ap.add_argument('--skip-v11',action='store_true',help='Reuse a verified V11 profile and GOP cache')
    ap.add_argument('--smoothness-budget-extra-pct',type=float,default=0.15,
                    help='Maximum extra video budget above V11, percent (default 0.15)')
    ap.add_argument('--smoothness-profile',choices=['balanced','smooth'],default='balanced')
    a=ap.parse_args()
    source=a.source.resolve()
    if not source.is_file():raise FileNotFoundError(source)
    root=Path(__file__).resolve().parent.parent
    out=a.output_folder.resolve() if a.output_folder else source.parent/(source.stem+'_MobiPEG_V12')
    out.mkdir(parents=True,exist_ok=True)
    enc=a.encoder.resolve();probe=a.probe.resolve()
    if not a.skip_v11:
        cmd=[sys.executable,root/'V11/encode_stereo_v11.py',source,
          '--encoder',enc,'--probe',probe,'--system-ffmpeg',a.system_ffmpeg,
          '--output-folder',out,'--video-kbps',a.video_kbps,'--workers',a.workers]
        if a.target_video_bytes is not None:cmd+=['--target-video-bytes',a.target_video_bytes]
        call(cmd)
    v11profile=out/'V11/V11_DECODER_AWARE_REPORT.json'
    v9profile=out/'V9_TEXTURE_QUALITY_REPORT.json'
    v10profile=out/'V10/V10_MOTION_DETAIL_REPORT.json'
    v11file=out/'V11'/f'{source.stem}_MobiPEG_V11_STEREO_3D.moflex'
    if not all(p.is_file() for p in (v11profile,v9profile,v10profile,v11file)):
        raise FileNotFoundError('Complete V11 profile/cache not present. Run without --skip-v11.')
    v11=json.loads(v11profile.read_text())
    baseline=int(v11['selected_video_bytes'])
    if not 0<=a.smoothness_budget_extra_pct<=5:raise ValueError('Extra budget must be 0..5%')
    budget=baseline+round(baseline*a.smoothness_budget_extra_pct/100)
    sizes=subprocess.run([str(probe),'-v','error','-select_streams','v:0',
      '-show_entries','packet=size','-of','csv=p=0',str(v11file)],
      check=True,capture_output=True).stdout
    packets=[int(x) for x in sizes.split()]
    peak=max(sum(packets[i:i+48]) for i in range(0,len(packets)-47,48))*8/1000
    name=source.stem+'_MobiPEG_V12_'+a.smoothness_profile.upper()+'_STEREO_3D.moflex'
    call([sys.executable,root/'V12/v12_full_reencode.py',
      '--v9-profile',v9profile,'--v10-profile',v10profile,
      '--v11-profile',v11profile,'--gop-folder',out,
      '--source',source,'--encoder',enc,'--probe',probe,
      '--workers',a.workers,'--budget',budget,'--peak-1s-kbps',max(1.,peak),
      '--profile',a.smoothness_profile,'--out',out/'V12','--name',name])
    print('MobiPEG V12 smooth/detail test:',out/'V12'/name)
    print('Experimental. Confirm Old 3DS stereo playback in Nintendo 3D Movie Viewer.')

if __name__=='__main__':main()
