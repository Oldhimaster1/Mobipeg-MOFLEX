#!/usr/bin/env python3
"""Generate the long browser regression fixture outside the checkout."""
import argparse
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--ffmpeg',default=str(ROOT/'native/local/bin/ffmpeg'))
p.add_argument('--audio-tail-seconds',type=float,default=1)
a=p.parse_args();out=a.output.resolve()
if ROOT==out or ROOT in out.parents:p.error('Store generated media outside the checkout')
if not 0<=a.audio_tail_seconds<=60:p.error('Audio tail must be between 0 and 60 seconds')
seconds=65+a.audio_tail_seconds
subprocess.run([a.ffmpeg,'-nostdin','-v','error','-n',
 '-f','lavfi','-i','color=red:s=200x224:r=24:d=65',
 '-f','lavfi','-i','color=blue:s=200x224:r=24:d=65',
 '-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:duration={seconds}',
 '-f','lavfi','-i',f'sine=frequency=880:sample_rate=48000:duration={seconds}',
 '-filter_complex','[0:v][1:v]hstack[v]','-map','[v]','-map','2:a','-map','3:a',
 '-metadata:s:a:0','language=eng','-metadata:s:a:1','language=jpn',
 '-c:v','mpeg4','-q:v','3','-c:a','aac',str(out)],check=True)
print(out)
