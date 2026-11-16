#!/usr/bin/env python3
"""Measured original and visual-quality variants of MobiPEG's proprietary-format-independent codec.
Tests original normalized YUV eye samples, NOT Nintendo's DLLs."""
from pathlib import Path
import subprocess,os,time,json,math,concurrent.futures
import numpy as np
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research/codec_sweep';D.mkdir(parents=True,exist_ok=True)
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda';PROBE=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not PROBE.exists():PROBE=Path('/usr/bin/ffprobe')
RAW=R/'MobiPEG_V5_RateControl/tests/avatar_eyes_24fps.yuv';w,h=400,224;PIX=w*h;FR=PIX*3//2
all_src=np.memmap(RAW,dtype='u1',mode='r').reshape(-1,FR)
windows=[(8,96),(44,96),(72,96)]
for t,n in windows:
 p=D/f'source_{t}.yuv';p.exists() or p.write_bytes(all_src[t*48:t*48+n].tobytes())
options=[('baseline',9,'hex',[]),('subme10',10,'hex',[]),('subme11',11,'hex',[]),('umh',9,'umh',[]),('umhsub10',10,'umh',[]),('trellis2',9,'hex',['-trellis','2']),('psy0',9,'hex',['-psy','0']),('psy_rd_1p5',9,'hex',['-psy-rd','1.5:0.0']),('aq_variance',9,'hex',['-aq-mode','1','-aq-strength','0.6'])]

def process(t,n,name,subme,me,args):
 src=D/f'source_{t}.yuv';out=D/f'{t:02d}_{name}.moflex';Y=D/f'{t:02d}_{name}.raw'
 env=os.environ.copy();env.update(MOBI_SUBME=str(subme),MOBI_SKIP='0',MOBI_RDO_LAMBDA_DELTA='2')
 cmd=[str(FF),'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','yuv420p','-video_size','400x224','-framerate','48','-i',str(src),'-an','-c:v','mobiclip','-mobiclip','1','-qp','12','-mobi_qyx','4','-preset','medium','-me_method',me,'-g','96']+args+['-mo_layout','0','-f','moflex',str(out)]
 st=time.monotonic();p=subprocess.run(cmd,env=env,capture_output=True,timeout=120)
 if p.returncode:raise ValueError(p.stderr.decode(errors='replace')[-650:])
 elapsed=time.monotonic()-st
 p=subprocess.run([str(FF),'-hide_banner','-nostdin','-loglevel','error','-xerror','-y','-i',str(out),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo',str(Y)],capture_output=True,timeout=80)
 if p.returncode or Y.stat().st_size!=n*FR:raise ValueError('bad reconstructed frames '+p.stderr.decode(errors='replace')[-350:])
 arr=np.memmap(Y,dtype='u1',mode='r').reshape(-1,FR)
 src_arr=all_src[t*48:t*48+n]
 a=np.asarray(src_arr[:,:PIX].reshape(-1,h,w),dtype=np.int16)
 b=np.asarray(arr[:,:PIX].reshape(-1,h,w),dtype=np.int16)
 sq=(a-b).astype(np.float32)**2
 Y_mse=float(sq.mean());ids=[j for k in range(0,n,12) for j in (k,k+1) if j<n]
 S=float(np.mean([ssim(a[i],b[i],data_range=255) for i in ids]))
 edge=(np.abs(np.diff(a,axis=1,prepend=a[:,:1,:]))>24)|(np.abs(np.diff(a,axis=2,prepend=a[:,:,:1]))>24)
 edge_err=float(sq[edge].mean()) if edge.any() else Y_mse
 p=subprocess.run([str(PROBE),'-v','error','-select_streams','v','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(out)],capture_output=True,text=True)
 pk=[int(z.strip().rstrip(',')) for z in p.stdout.splitlines() if z.strip().rstrip(',').isdigit()]
 if len(pk)!=n:raise RuntimeError('unexpected video packet count')
 return dict(time=t,option=name,video_bytes=sum(pk),mse_y=Y_mse,psnr=10*math.log10(65025/Y_mse),ssim=S,edge_mse=edge_err,seconds=round(elapsed,2),valid=True,output=str(out))

results=[];sweep=D/'codec_variants.json'
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 futures={pool.submit(process,t,n,*p): (t,p[0]) for t,n in windows for p in options}
 for fut in concurrent.futures.as_completed(futures):
  try:
   x=fut.result();results.append(x);print('PASS',x['time'],x['option'],'bytes',x['video_bytes'],'PSNR',round(x['psnr'],3),'SSIM',round(x['ssim'],5),'speed',x['seconds'],flush=True)
  except Exception as e:print('FAILED',futures[fut],repr(e),flush=True)
  sweep.write_text(json.dumps(sorted(results,key=lambda z:(z['time'],z['option'])),indent=2))
print('TOTAL',len(results),flush=True)
