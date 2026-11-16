#!/usr/bin/env python3
"""User-friendly MobiPEG V7 CLI: MP4/MKV H-SBS -> 3DS layout0 MOFLEX.

Example:
  python3 V7/encode_stereo_v7.py movie_HSBS.mp4 --encoder local/bin/ffmpeg \
    --probe local/bin/ffprobe --video-kbps 1266 --workers 4

The source FFmpeg must be rebuilt with the V7 x264 patch for lambda tuning.
Never executes or needs Nintendo's proprietary MobiClip encoder.
"""
import argparse,subprocess,sys,json,hashlib
from pathlib import Path
from normalize_stereo_v7 import normalize


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('source');p.add_argument('--encoder',required=True);p.add_argument('--probe',required=True)
 p.add_argument('--system-ffmpeg',default='ffmpeg');p.add_argument('--out-dir')
 p.add_argument('--video-kbps',type=float,default=1266.5);p.add_argument('--official')
 p.add_argument('--workers',type=int,default=4);p.add_argument('--lambda-deltas',default='0,2')
 p.add_argument('--scene-weight',type=float,default=.15);p.add_argument('--scene-threshold',type=float,default=38)
 p.add_argument('--normalize',default='classic',choices=['classic','per-eye'])
 p.add_argument('--kernel',default='lanczos',choices=['lanczos','bicubic','bilinear','area','spline'])
 p.add_argument('--max-gops',type=int,help='Smoke tests; no final output')
 a=p.parse_args()
 src=Path(a.source).expanduser().resolve()
 if not src.exists():raise FileNotFoundError(src)
 root=Path(a.out_dir).expanduser().resolve() if a.out_dir else src.parent/(src.stem+'_MobiPEG_V7')
 root.mkdir(parents=True,exist_ok=True)
 raw=root/'source_stereo_400x224_48codedfps.yuv'
 # Input and scaling changes invalidate the raw-video cache. Without a stamp,
 # reusing an old 600+ MB raw file could silently encode the WRONG movie.
 stamp=root/'normalized_source_cache.json'
 def sha_file(f):
  h=hashlib.sha256()
  with Path(f).open('rb') as stream:
   for block in iter(lambda:stream.read(4<<20),b''):h.update(block)
  return h.hexdigest()
 fingerprint={'source_sha256':sha_file(src),'method':a.normalize,'kernel':a.kernel,
              'ffmpeg':str(a.system_ffmpeg),'format':'L0R0 interleaved yuv420p 400x224 24fps stereo'}
 valid=False
 if raw.is_file() and stamp.is_file():
  try:valid=(json.loads(stamp.read_text())==fingerprint and raw.stat().st_size>0 and raw.stat().st_size%134400==0)
  except (ValueError,OSError):pass
 if not valid:
  print('Normalizing source (input/config changed or first use)',flush=True)
  stamp.unlink(missing_ok=True)
  normalize(src,raw,a.system_ffmpeg,a.normalize,a.kernel)
  stamp.write_text(json.dumps(fingerprint,indent=2))
 else:print('Reusing verified normalized raw input:',raw,flush=True)
 argv=[sys.executable,str(Path(__file__).with_name('adaptive_stereo_v7.py')),'--raw',str(raw),'--source',str(src),'--out-dir',str(root),
       '--encoder',str(Path(a.encoder).resolve()),'--probe',str(Path(a.probe).resolve()),'--system-ffmpeg',a.system_ffmpeg,
       '--video-kbps',str(a.video_kbps),'--lambda-deltas',a.lambda_deltas,'--workers',str(a.workers),
       '--scene-weight',str(a.scene_weight),'--scene-threshold',str(a.scene_threshold)]
 if a.official:argv.extend(['--official',str(Path(a.official).resolve())])
 if a.max_gops is not None:argv.extend(['--max-gops',str(a.max_gops)])
 r=subprocess.run(argv)
 if r.returncode:raise SystemExit(r.returncode)
 if a.max_gops is None:print('MobiPEG V7 finished:',root/'MobiPEG_V7_STEREO_3D.moflex',flush=True)
if __name__=='__main__':main()
