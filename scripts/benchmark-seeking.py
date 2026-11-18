#!/usr/bin/env python3
"""Benchmark indexed reads in generated 30–120 minute repeated stress fixtures.
Uses the same 24-second motif as stress-long-movie.py. Checks every pixel and
sample against a forward-decoded short reference. Optional --baseline measures
the same final seek using forward decoding. Does not benchmark arbitrary media.
"""
import hashlib,json,os,subprocess,sys,tempfile,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
folder=Path(sys.argv[1]);encoder=root/'native/local/bin/ffmpeg'
rows=[]
with tempfile.TemporaryDirectory(prefix='mobipeg-seek-bench-') as work:
 def decode(path,stamp,forward):
  env=dict(os.environ);env.pop('MOBIPEG_FORWARD_SEEK',None)
  if forward:env['MOBIPEG_FORWARD_SEEK']='1'
  video=Path(work)/'video.yuv';audio=Path(work)/'audio.pcm'
  start=time.monotonic()
  log=subprocess.run([str(encoder),'-v','debug','-xerror','-y','-ss',str(stamp),'-i',str(path),
    '-map','0:v:0','-t','0.25','-pix_fmt','yuv420p','-f','rawvideo',str(video),
    '-map','0:a:0','-t','0.25','-ar','48000','-ac','2','-f','s16le',str(audio)],env=env,check=True,capture_output=True).stderr
  return {'seconds':time.monotonic()-start,'videoHash':hashlib.sha256(video.read_bytes()).hexdigest(),
    'audioHash':hashlib.sha256(audio.read_bytes()).hexdigest(),'videoBytes':video.stat().st_size,'audioBytes':audio.stat().st_size,'indexed':b'MOFLEX indexed seek:' in log}
 for minutes in [30,60,90,120]:
  for fraction in [.1,.5,.95]:
   stamp=minutes*60*fraction
   expected=decode(folder/'movie-5min.moflex',stamp%24+24,True)
   row=decode(folder/f'movie-{minutes}min.moflex',stamp,False)
   for key in ['videoHash','audioHash','videoBytes','audioBytes']:
    if row[key]!=expected[key]:raise RuntimeError(f'{minutes}min at {stamp}: {key} differs')
   if not row['indexed']:raise RuntimeError('Indexed path not used')
   row.update(minutes=minutes,targetSeconds=stamp,verified=True);rows.append(row);print(json.dumps(row),flush=True)
 if '--baseline' in sys.argv:
  row=decode(folder/'movie-120min.moflex',6840,True);row.update(minutes=120,targetSeconds=6840,baseline=True)
  for key in ['videoHash','audioHash','videoBytes','audioBytes']:
   if row[key]!=rows[-1][key]:raise RuntimeError('Forward baseline differs')
  print(json.dumps(row),flush=True)
