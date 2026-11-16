#!/usr/bin/env python3
"""V9 experimental 3D quality profile for any stereo H-SBS/F-SBS video.

Runs the established V8 normalized and measured baseline, then searches for
decoder-verified V9 edge-aware luma variants inside the chosen video budget.
The final result is a normal interleaved-stereo MOFLEX, not an MP4.
"""
import argparse
import subprocess
import sys
from pathlib import Path

EYE_FRAME_BYTES = 400 * 224 * 3 // 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path, help='3D half-SBS or full-SBS MP4/MKV')
    ap.add_argument('--encoder', type=Path, required=True, help='locally built MobiPEG FFmpeg')
    ap.add_argument('--probe', type=Path, required=True, help='locally built MobiPEG ffprobe')
    ap.add_argument('--system-ffmpeg', default='ffmpeg')
    ap.add_argument('--output-folder', type=Path)
    ap.add_argument('--normalize', default='classic', choices=['classic','per-eye'])
    ap.add_argument('--kernel', default='lanczos', choices=['lanczos','bicubic','bilinear','area','spline'])
    ap.add_argument('--profile', choices=['texture','conservative'], default='texture')
    ap.add_argument('--video-kbps', type=float, default=1266.5)
    ap.add_argument('--target-video-bytes', type=int)
    ap.add_argument('--peak-1s-kbps', type=float,
                    help='Optional maximum packet payload per second for each newly encoded GOP')
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--skip-v8', action='store_true',help='reuse previously validated V8 GOP cache')
    a = ap.parse_args()
    source = a.source.resolve()
    if not source.is_file(): raise FileNotFoundError(source)
    if a.peak_1s_kbps is not None and a.peak_1s_kbps <= 0:
        raise ValueError('--peak-1s-kbps must be positive')
    home = Path(__file__).resolve().parent.parent
    work = (a.output_folder.resolve() if a.output_folder else
            source.parent/(source.stem+'_MobiPEG_V9'))
    work.mkdir(parents=True,exist_ok=True)
    enc = a.encoder.resolve()
    probe = a.probe.resolve()
    if not a.skip_v8:
        cmd=[sys.executable,str(home/'V8/encode_stereo_v8.py'),str(source),
             '--encoder',str(enc),'--probe',str(probe),
             '--system-ffmpeg',a.system_ffmpeg,'--output-folder',str(work),
             '--video-kbps',str(a.video_kbps), '--workers',str(a.workers),
             '--normalize',a.normalize,'--kernel',a.kernel]
        if a.target_video_bytes is not None:
            cmd += ['--target-video-bytes',str(a.target_video_bytes)]
        subprocess.run(cmd,check=True)
    raw=work/'normalized_3D_interleaved_400x224_48fps.yuv'
    sel=work/'V8_PROFILE_SELECTION.json'
    psy=work/'v8_extra_candidates.json'
    if not all(z.is_file() for z in (raw,sel,psy)):
        raise FileNotFoundError('V8 raw/selection cache missing; rerun without --skip-v8')
    frames=raw.stat().st_size//EYE_FRAME_BYTES
    if frames%2 or raw.stat().st_size!=frames*EYE_FRAME_BYTES:
        raise ValueError('Invalid V8 normalized stereo frame count')
    budget=(a.target_video_bytes if a.target_video_bytes is not None else
            int(a.video_kbps*1000/8*(frames/48)))
    cmd=[sys.executable,str(Path(__file__).with_name('v9_full_reencode.py')),
         '--raw',str(raw),'--mp4',str(source),'--encoder',str(enc),
         '--probe',str(probe),'--selection',str(sel),'--psy-metadata',str(psy),
         '--long-metadata',str(Path(__file__).with_name('empty_long_candidates.json')),
         '--out',str(work),'--budget',str(budget),'--workers',str(a.workers),
         '--profile',a.profile,
         '--output-name',f'{source.stem}_MobiPEG_V9_STEREO_3D.moflex']
    if a.peak_1s_kbps is not None:
        cmd += ['--peak-1s-kbps', str(a.peak_1s_kbps)]
    subprocess.run(cmd,check=True)
    print('V9 output:',work/(source.stem+'_MobiPEG_V9_STEREO_3D.moflex'))
    print('Playback on original Nintendo 3DS hardware is still required.')


if __name__=='__main__':main()
