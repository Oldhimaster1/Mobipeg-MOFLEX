#!/usr/bin/env python3
"""Reproducible 3DS MobiClip encoder candidate tests; same YUV/GOP/quant settings
as verified V7, only toggling internal x264 psychovisual and search parameters.
Independent proprietary-free, full software decoding, both-eye scoring.
"""
from pathlib import Path
import sys,json,math,time,os,subprocess,concurrent.futures,collections,argparse
import numpy as np
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research';D.mkdir(exist_ok=True)
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda'; FP=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not FP.exists():FP=Path('/usr/bin/ffprobe')
G=R/'MobiPEG_V5_RateControl/tests/adaptive'
W,H=400,224;PIX=W*H;FRAME=PIX*3//2
cut_threshold=38
V7=json.loads((R/'MobiPEG_V7_Engineering/bench/cut_0.15_guard_2_selected.json').read_text())
allc=json.loads((R/'MobiPEG_V7_Engineering/bench/candidate_detail_metrics.json').read_text())+json.loads((R/'MobiPEG_V7_Engineering/bench/lambda2_gop_candidates.json').read_text())
lookup={(x['index'],x['option']):x for x in allc}
variants=[('psyoff',['-psy','0']),('umh',['-me_method','umh']),('psyoff_umh',['-psy','0','-me_method','umh']),('nr10',['-noise_reduction','10'])]

def video_bytes(path,n):
 p=subprocess.run([str(FP),'-v','error','-select_streams','v','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(path)],capture_output=True,text=True)
 a=[int(x.strip().rstrip(',')) for x in p.stdout.splitlines() if x.strip().rstrip(',').isdigit()]
 if len(a)!=n:raise ValueError(f'packet count {len(a)} != {n}: {path}')
 return sum(a)

def score(idx,decoded,n,source):
 y=np.fromfile(source,dtype=np.uint8).reshape(n,FRAME)[:,:PIX].reshape(n,H,W)
 rec=decoded.reshape(n,FRAME)[:,:PIX].reshape(n,H,W)
 diff=np.asarray(y,dtype=np.int16)-np.asarray(rec,dtype=np.int16)
 sq=np.square(diff,dtype=np.int32);fm=np.mean(sq,axis=(1,2));mse=float(np.mean(fm))
 ey=np.asarray(y,dtype=np.int16)
 edges=(np.abs(np.diff(ey,axis=2,prepend=ey[:,:,:1]))>24)|(np.abs(np.diff(ey,axis=1,prepend=ey[:,:1,:]))>24)
 edge_mse=float(sq[edges].mean()) if edges.any() else mse
 # V7 correct both-eye + cut onset definition, matching reference GOP candidate metrics
 yy=np.asarray(y[::2,::8,::8],dtype=np.int16)
 mad=np.abs(yy[1:]-yy[:-1]).mean(axis=(1,2)) if len(yy)>1 else np.array([])
 localcuts=[int(i)+1 for i in np.flatnonzero(mad>cut_threshold)]
 cut_idx=sorted({j for c in localcuts for j in range(2*c,min(n,2*c+12))})
 cutm=float(fm[cut_idx].mean()) if cut_idx else float(fm[:min(n,12)].mean())
 sampled=sorted(set([j for k in range(0,n,12) for j in (k,k+1) if j<n]+list(range(min(n,4)))+cut_idx[::4]))
 ss=np.array([ssim(y[j],rec[j],data_range=255) for j in sampled]);ss_mean=float(ss.mean())
 return {'mse_y':mse,'psnr_y':10*math.log10(65025/max(mse,1e-9)),'ssim_both':ss_mean,'ssim_left':float(np.mean([z for j,z in zip(sampled,ss) if j%2==0])),'ssim_right':float(np.mean([z for j,z in zip(sampled,ss) if j%2==1])),
   'edge_mse':edge_mse,'worst_8th_mse':float(np.mean(np.sort(fm)[-max(1,n//8):])),'left_mse':float(fm[::2].mean()),'right_mse':float(fm[1::2].mean()),'cut_count':len(localcuts),'cut_frames':len(cut_idx),'cut_mean_mse':cutm}

def encode(idx,name,opts):
 original=lookup[(idx,V7[idx]['option'])]
 n=original['coded_frames'];qp=original['qp'];qyx=original['qyx'];lam=original.get('lambda_delta',0)
 source=G/f'input_{idx:03d}.raw';out=D/f'part_{idx:03d}_{name}.moflex'
 if not out.exists() or out.stat().st_size<4096:
  env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_RDO_LAMBDA_DELTA=str(lam),MOBI_INTRA_RD_CAP='0',MOBI_RDO_PRED_COST='0')
  cmd=[str(FF),'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(source),'-an','-c:v','mobiclip','-mobiclip','1','-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g','96']+opts+['-mo_layout','0','-f','moflex',str(out)]
  t=time.monotonic();p=subprocess.run(cmd,env=env,capture_output=True,timeout=180)
  if p.returncode:raise RuntimeError(f'encode {idx} {name}: {p.stderr.decode(errors="replace")[-400:]}')
  seconds=round(time.monotonic()-t,3)
 else:seconds=-1
 dec=subprocess.run([str(FF),'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',str(out),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],capture_output=True,timeout=120)
 if dec.returncode or len(dec.stdout)!=n*FRAME:raise RuntimeError(f'decode {idx} {name} {len(dec.stdout)} {dec.stderr.decode(errors="replace")[-250:]}')
 ar=np.frombuffer(dec.stdout,dtype='u1').reshape(-1,FRAME);metrics=score(idx,ar,n,source)
 return {**metrics,'index':idx,'span':1,'option':name,'qyx':qyx,'qp':qp,'lambda_delta':lam,'video_bytes':video_bytes(out,n),'coded_frames':n,'file':str(out),'encoder_s':seconds}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--end',type=int,default=51);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args()
 f=D/'psy_motion_candidates.json';r=json.loads(f.read_text()) if f.exists() else [];done={(x['index'],x['option']):x for x in r}
 jobs=[(i,*v) for i in range(a.start,a.end) for v in variants if (i,v[0]) not in done]
 print('new tests',len(jobs),'cached',len(done),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  futs={pool.submit(encode,*x):x for x in jobs}
  for fu in concurrent.futures.as_completed(futs):
   try:
    z=fu.result();done[(z['index'],z['option'])]=z
    print('PASS',z['index'],z['option'],z['video_bytes'],round(z['psnr_y'],3),round(z['ssim_both'],5),flush=True)
    f.write_text(json.dumps(sorted(done.values(),key=lambda x:(x['index'],x['option'])),indent=2))
   except Exception as e:print('FAILED',futs[fu],str(e),flush=True)
 print('DONE',len(done),flush=True)
if __name__=='__main__':main()
