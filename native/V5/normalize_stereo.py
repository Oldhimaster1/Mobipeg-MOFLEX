#!/usr/bin/env python3
"""Normalize HSBS to 400x224 per eye, 24 fps/eye, L/R interleaved raw YUV420p.
Same FFmpeg lanczos 800x224 normalization used for the November R-D experiments.
"""
import argparse, subprocess, hashlib
from pathlib import Path

def normalize(input_path,output,ffmpeg='ffmpeg'):
    W=800; H=224; FLEN=W*H*3//2; EYELEN=400*H*3//2
    cmd=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(input_path),'-vf',
         'fps=24,scale=800:224:flags=lanczos,format=yuv420p',
         '-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1']
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    n=0
    try:
      with open(output,'wb',buffering=1<<20) as out:
        while True:
          b=bytearray()
          while len(b)<FLEN:
            data=p.stdout.read(FLEN-len(b))
            if not data:break
            b.extend(data)
          if not b:break
          if len(b)!=FLEN:raise RuntimeError('truncated raw input')
          y=memoryview(b)[:W*H]; u=memoryview(b)[W*H:W*H+W*H//4];v=memoryview(b)[W*H+W*H//4:]
          for side in (0,1):
            for plane,stride,rows,cols in ((y,800,224,400),(u,400,112,200),(v,400,112,200)):
              start=cols*side
              for row in range(rows):out.write(plane[row*stride+start:row*stride+start+cols])
          n+=1
      error=p.stderr.read();rc=p.wait()
      if rc:raise RuntimeError(error.decode(errors='replace')[-800:])
    except:
      p.kill();p.wait();raise
    assert Path(output).stat().st_size==2*n*EYELEN
    print('normalized source stereo pairs',n,'coded eyes',2*n,'bytes',Path(output).stat().st_size,flush=True)
    return n

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('output');a.add_argument('--ffmpeg',default='ffmpeg');args=a.parse_args();normalize(args.source,args.output,args.ffmpeg)
