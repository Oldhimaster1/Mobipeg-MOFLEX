#!/usr/bin/env python3
"""Video -> MobiPEG V8 3D, no Nintendo SDK. Input HSBS or FSBS.

python3 V8/encode_stereo_v8.py avatar_HSBS.mp4 --encoder local/bin/ffmpeg --probe local/bin/ffprobe --video-kbps 1260 --workers 4

Requires a built MobiPEG V7+ FFmpeg (correct MOFLEX interleaving and MobiClip codec),
Python numpy/scikit-image, and system FFmpeg for MP4/audio normalization.
This is an opt-in experimental quality mode, not 3DS production-certified.
"""
import argparse,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'V7'))
from normalize_stereo_v7 import normalize

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('source',help='stereo half-side-by-side or full-side-by-side MP4/MKV')
 p.add_argument('--encoder',required=True,help='custom-built MobiPEG FFmpeg path')
 p.add_argument('--probe',required=True,help='custom MobiPEG ffprobe')
 p.add_argument('--video-kbps',type=float,default=1266.5)
 p.add_argument('--target-video-bytes',type=int)
 p.add_argument('--workers',type=int,default=4)
 p.add_argument('--output-folder')
 p.add_argument('--normalize',choices=['classic','per-eye'],default='classic')
 p.add_argument('--kernel',choices=['lanczos','bicubic','bilinear','area','spline'],default='lanczos')
 p.add_argument('--system-ffmpeg',default='ffmpeg')
 p.add_argument('--max-gops',type=int)
 args=p.parse_args()
 source=Path(args.source).resolve()
 if not source.exists():raise FileNotFoundError(source)
 folder=Path(args.output_folder).resolve() if args.output_folder else source.parent/(source.stem+'_MobiPEG_V8')
 folder.mkdir(exist_ok=True,parents=True)
 raw=folder/'normalized_3D_interleaved_400x224_48fps.yuv'
 norm_meta=folder/'normalized_settings.txt'
 settings=f'{source.resolve()}|{source.stat().st_mtime_ns}|{args.normalize}|{args.kernel}'
 if not raw.exists() or not norm_meta.exists() or norm_meta.read_text()!=settings:
  normalize(source,raw,ffmpeg=args.system_ffmpeg,method=args.normalize,kernel=args.kernel)
  norm_meta.write_text(settings)
 cmd=[sys.executable,str(Path(__file__).with_name('adaptive_stereo_v8.py')),'--raw',str(raw),'--source',str(source),
     '--encoder',str(Path(args.encoder).resolve()),'--probe',str(Path(args.probe).resolve()),
     '--out-dir',str(folder),'--system-ffmpeg',args.system_ffmpeg,'--video-kbps',str(args.video_kbps),
     '--workers',str(args.workers)]
 if args.target_video_bytes is not None:cmd+=['--target-video-bytes',str(args.target_video_bytes)]
 if args.max_gops is not None:cmd+=['--max-gops',str(args.max_gops)]
 subprocess.run(cmd,check=True)
 if args.max_gops is None:print('Output:',folder/'MobiPEG_V8_STEREO_3D.moflex')
if __name__=='__main__':main()
