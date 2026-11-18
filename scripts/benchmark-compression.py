#!/usr/bin/env python3
"""Controlled mixed static/moving/noisy fixture, equal maximum size cap.
Reports actual bytes separately: this is not an equal-actual-size comparison.
"""
import json,os,re,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mobipeg-quality-') as folder:
 folder=Path(folder);source=folder/'source.mkv'
 subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=gray:s=400x240:r=24:d=6',
  '-f','lavfi','-i','testsrc2=s=400x240:r=24:d=6,noise=alls=12:allf=t+u:all_seed=733',
  '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0','-c:v','ffv1',str(source)],check=True)
 rows=[];static_bytes=None
 for mode in ['uniform','scene','matched-uniform']:
  output=folder/(mode+'.moflex');env=dict(os.environ);env.pop('MOBIPEG_UNIFORM_BUDGET',None)
  if mode!='scene':env['MOBIPEG_UNIFORM_BUDGET']='1'
  cap=800000 if mode!='matched-uniform' else 2*(rows[1]['actualBytes']-static_bytes+4096)
  start=time.monotonic()
  run=subprocess.run([sys.executable,'native/MobiPEG_Studio_V15.py','-i',str(source),'-o',str(output),
    '--preset','small','--q','36','--workers','2','--max-size-mb',str(cap/1e6)],cwd=ROOT,env=env,capture_output=True,text=True,check=True)
  seconds=time.monotonic()-start
  if mode=='uniform':static_bytes=int(re.search(r'Range 1: Q=\d+, ([\d,]+) bytes',run.stdout).group(1).replace(',',''))
  quality=subprocess.run(['ffmpeg','-v','info','-i',str(source),'-i',str(output),'-filter_complex',
    '[0:v]trim=start=6,setpts=PTS-STARTPTS[r];[1:v]trim=start=6,setpts=PTS-STARTPTS[d];[r][d]psnr',
    '-an','-f','null','-'],capture_output=True,text=True,check=True)
  psnr=float(re.findall(r'average:([\d.]+)',quality.stderr)[-1])
  row=dict(mode=mode,capBytes=cap,actualBytes=output.stat().st_size,seconds=seconds,busyScenePSNR=psnr,
    completeDecodeVerified=True,trials=len(re.findall('Range 2: Q=',run.stdout)))
  if mode=='matched-uniform' and row['actualBytes']!=rows[1]['actualBytes']:raise RuntimeError('Matched-byte target was not achieved')
  rows.append(row);print(json.dumps(row),flush=True)
