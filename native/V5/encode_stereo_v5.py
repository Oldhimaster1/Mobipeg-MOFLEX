#!/usr/bin/env python3
"""End-to-end, software-only 3DS-compatible MOFLEX 3D encoder.

Usage (after building patched MobiPEG FFmpeg, pip install numpy scikit-image):
 python3 encode_stereo_v5.py "input_HSBS.mp4" --ffmpeg ./local/bin/ffmpeg --ffprobe ./local/bin/ffprobe --video-kbps 1266

The source normalization reproduces 400x224 per eye at 24 stereo FPS.
This is a V5 research-quality mode: costly exhaustive per-GOP test encodes,
not a realtime/production multipurpose transcoder.
"""
import argparse,os,shutil,subprocess,sys,json
from pathlib import Path
from normalize_stereo import normalize

def cli():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('source',help='Half-side-by-side 3D MP4/MOV/MKV input')
 p.add_argument('--ffmpeg',help='Patched MobiPEG FFmpeg binary (mobiclip encoder + moflex muxer)',default=None)
 p.add_argument('--ffprobe',help='Patched MobiPEG FFprobe binary',default=None)
 p.add_argument('--system-ffmpeg',default='ffmpeg',help='FFmpeg binary to normalize source and decode original audio')
 p.add_argument('--video-kbps',type=float,default=1266.5,help='TARGET VIDEO bitrate (audio additional), default 1266.5')
 p.add_argument('--workers',type=int,default=4)
 p.add_argument('--output',help='Final output MOFLEX filename',default=None)
 p.add_argument('--workdir',help='Reusable intermediate encoding work folder',default=None)
 p.add_argument('--perceptual-weight',type=float,default=0.5,help='0 prioritize pixel distortion, 1 prioritize SSIM, default 0.5')
 a=p.parse_args();src=Path(a.source).resolve()
 if not src.is_file():p.error('Source does not exist')
 home=Path(__file__).resolve().parent.parent
 enc=a.ffmpeg or str(home/'local'/'bin'/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg'))
 probe=a.ffprobe or str(home/'local'/'bin'/('ffprobe.exe' if os.name=='nt' else 'ffprobe'))
 for binary in (enc,probe,a.system_ffmpeg):
  if not shutil.which(str(binary)) and not Path(binary).is_file():p.error('Binary not found: '+str(binary))
 helpout=subprocess.run([enc,'-hide_banner','-h','muxer=moflex'],capture_output=True,text=True)
 if '-mo_interleave_input_double_rate' not in helpout.stdout+helpout.stderr:
  p.error('MobiPEG executable is too old; rebuild source with V5 stereoscopic MOFLEX descriptor fix')
 if not 200<=a.video_kbps<=10000:p.error('Video bitrate must be 200..10000 kbps')
 if not 1<=a.workers<=32:p.error('Worker count must be 1..32')
 dest=Path(a.output).resolve() if a.output else src.with_name(src.stem+'_MobiPEG_V5_3D.moflex')
 work=Path(a.workdir).resolve() if a.workdir else dest.with_suffix('.v5_work')
 work.mkdir(exist_ok=True,parents=True)
 norm=work/'normalized_3d_eyes_400x224_48_coded_fps.yuv'
 if not norm.exists():normalize(src,norm,a.system_ffmpeg)
 print('Encoding with V5 source-referenced GOP R-D rate control...',flush=True)
 cmd=[sys.executable,str(Path(__file__).parent/'adaptive_stereo.py'),
      '--raw',str(norm),'--out-dir',str(work),'--encoder',str(enc),'--probe',str(probe),
      '--target-video-kbps',str(a.video_kbps),'--source',str(src),'--system-ffmpeg',str(a.system_ffmpeg),
      '--perceptual-weight',str(a.perceptual_weight),'--workers',str(a.workers)]
 r=subprocess.run(cmd)
 if r.returncode:raise SystemExit(r.returncode)
 intermediate=work/'adaptive_V5.moflex'
 if not intermediate.is_file():raise SystemExit('Cannot find the completed stereo file: '+str(intermediate))
 shutil.copyfile(intermediate,dest)
 print('SUCCESS',dest,'bytes',dest.stat().st_size,flush=True)
 print('Important: verify 3D with Nintendo 3D Movie Viewer on actual 3DS hardware.',flush=True)

if __name__=='__main__':cli()
