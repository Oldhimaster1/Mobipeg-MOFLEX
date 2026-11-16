#!/usr/bin/env python3
"""Opt-in V8 encoder research: 4-second GOP candidates, same MobiClip bitstream/quality pipeline.
This does not touch known-working V7. All candidate outputs are decoded and independently evaluated."""
import os,sys,json,math,subprocess,time,concurrent.futures,argparse
from pathlib import Path
import numpy as np
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data')
D=R/'MobiPEG_V8_Research';D.mkdir(exist_ok=True)
SRC=R/'MobiPEG_V5_RateControl/tests/avatar_eyes_24fps.yuv'
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda'
FP=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not FP.exists():FP=Path('/usr/bin/ffprobe')
W,H=400,224; PIX=W*H;FB=PIX*3//2
ref=np.memmap(SRC,mode='r',dtype=np.uint8).reshape(-1,FB)
CUT=set(json.loads((R/'MobiPEG_V7_Engineering/bench/scenes.json').read_text())['cuts'])
assert len(ref)==4826
settings=[('fine3_16',3,16,0),('fine3_17',3,17,2),('mid4_12',4,12,2),('mid4_13',4,13,2),('mid4_14',4,14,2)]

def score(decoded,refstart):
 n=len(decoded); orig=np.asarray(ref[refstart:refstart+n])
 a=orig[:,:PIX].reshape(-1,H,W);b=decoded[:,:PIX].reshape(-1,H,W)
 sq=(a.astype(np.float32)-b.astype(np.float32))**2;fm=sq.mean(axis=(1,2));mean=float(fm.mean())
 sampled=sorted(set([j for k in range(0,n,12) for j in (k,k+1) if j<n]+list(range(min(4,n)))))
 ss=float(np.mean([ssim(a[i],b[i],data_range=255) for i in sampled]))
 dy=np.abs(np.diff(a.astype(np.int16),axis=1,prepend=a[:,:1,:].astype(np.int16)))>24
 dx=np.abs(np.diff(a.astype(np.int16),axis=2,prepend=a[:,:,:1].astype(np.int16)))>24
 edge=np.logical_or(dx,dy)
 edge_err=float(sq[edge].mean()) if edge.any() else mean
 # cut pair indexes are global; include first ~6 display frames after each cut
 idx=[j for pair in CUT for j in range(pair*2-refstart,min(pair*2-refstart+12,n)) if 0<=j<n]
 cutm=float(fm[idx].mean()) if idx else mean
 return dict(mse_y=mean,psnr_y=10*math.log10(65025/max(mean,1e-9)),ssim_both=ss,edge_mse=edge_err,worst_8th_mse=float(np.sort(fm)[-max(1,n//8):].mean()),left_mse=float(fm[::2].mean()),right_mse=float(fm[1::2].mean()),cut_count=len(set(x//2 for x in idx)),cut_frames=len(idx),cut_mean_mse=cutm)

def measure_file(p,refstart,n):
 pr=subprocess.run([str(FP),'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(p)],capture_output=True,text=True,timeout=60)
 if pr.returncode:raise RuntimeError(pr.stderr[:500])
 sizes=[int(x.strip().rstrip(',')) for x in pr.stdout.splitlines() if x.strip().rstrip(',').isdigit()]
 if len(sizes)!=n:raise ValueError(f'packet mismatch {len(sizes)} vs {n}: {p}')
 d=subprocess.run([str(FF),'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',str(p),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],capture_output=True,timeout=95)
 if d.returncode:raise RuntimeError(d.stderr.decode(errors='replace')[-700:])
 if len(d.stdout)!=n*FB:raise ValueError(f'frame mismatch from {p}: {len(d.stdout)//FB} vs {n}')
 dec=np.frombuffer(d.stdout,dtype=np.uint8).reshape(-1,FB)
 return {**score(dec,refstart),'video_bytes':sum(sizes),'coded_frames':n}

def job(i,option,qyx,qp,lam):
 bs=i*96;n=min(192,4826-bs);raw=D/f'input_{i:02d}.yuv';out=D/f'part_{i:02d}_{option}.moflex'
 if not raw.exists() or raw.stat().st_size!=n*FB:
  tmp=raw.with_suffix('.tmp_'+option);tmp.write_bytes(ref[bs:bs+n].tobytes());os.replace(tmp,raw)
 if raw.stat().st_size!=n*FB:raise ValueError('bad sliced source')
 if not out.exists() or out.stat().st_size<2000:
  env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0',MOBI_RDO_PRED_COST='0',MOBI_RDO_LAMBDA_DELTA=str(lam))
  cmd=[str(FF),'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(raw),'-an','-c:v','mobiclip','-mobiclip','1','-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g','192','-mo_layout','0','-f','moflex',str(out)]
  t=time.monotonic();p=subprocess.run(cmd,env=env,capture_output=True,timeout=200)
  if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace')[-500:])
  elapsed=time.monotonic()-t
 else:elapsed=-1
 res=measure_file(out,bs,n)
 res.update(index=i,span=2,option=option,qyx=qyx,qp=qp,lambda_delta=lam,file=str(out),elapsed_seconds=round(elapsed,2))
 return res

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--from-index',type=int,default=0);ap.add_argument('--to-index',type=int,default=25);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args()
 result_path=D/'candidates_4sec.json';done={}
 if result_path.exists():
  for x in json.loads(result_path.read_text()):done[(x['index'],x['option'])]=x
 # Prepare source pieces exactly once to avoid concurrent truncated reads.
 for i in range(a.from_index,a.to_index):
  bs=i*96;n=min(192,4826-bs);raw=D/f'input_{i:02d}.yuv'
  if not raw.exists() or raw.stat().st_size!=n*FB:raw.write_bytes(ref[bs:bs+n].tobytes())
 jobs=[(i,*z) for i in range(a.from_index,a.to_index) for z in settings if (i,z[0]) not in done]
 print('jobs',len(jobs),'cached',len(done),flush=True)
 t0=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  futures={pool.submit(job,*x):x for x in jobs}
  for f in concurrent.futures.as_completed(futures):
   try:
    x=f.result();done[(x['index'],x['option'])]=x
    print('PASS',x['index'],x['option'],x['video_bytes'],'PSNR',round(x['psnr_y'],3),'SSIM',round(x['ssim_both'],4),'t',x['elapsed_seconds'],flush=True)
    result_path.write_text(json.dumps(sorted(done.values(),key=lambda x:(x['index'],x['option'])),indent=2))
   except Exception as e:print('FAILED',futures[f],repr(e),flush=True)
 print('completed',len(done),'in',round(time.monotonic()-t0,1),'seconds',flush=True)
if __name__=='__main__':main()
