from pathlib import Path
import numpy as np,cv2,subprocess,os,time,concurrent.futures,json,math
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research/prefilter';D.mkdir(parents=True,exist_ok=True)
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda';FP=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not FP.exists():FP=Path('/usr/bin/ffprobe')
W,H=400,224;PIX=W*H;FR=PIX*3//2
idx=[8,22,35];strategies=[('no_filter',0,0),('weak_flat',0.35,8),('medium_flat',0.7,8),('strong_flat',1,8),('weak_broad',0.5,14),('strong_broad',0.85,14)]

def process(i,name,strength,csigma):
 orig=R/f'MobiPEG_V5_RateControl/tests/adaptive/input_{i:03d}.raw';raw=np.fromfile(orig,dtype='u1').reshape(-1,FR);n=len(raw)
 temp=D/f'{i:03d}_{name}.yuv'
 if name!='no_filter':
  a=raw.copy();
  for j in range(n):
   inp=a[j,:PIX].reshape(H,W);b=cv2.bilateralFilter(inp,3,csigma,1.3)
   s=inp.astype(np.int16);grad=np.abs(np.diff(s,axis=1,prepend=s[:,:1]))+np.abs(np.diff(s,axis=0,prepend=s[:1,:]))
   alpha=strength*np.clip((24-grad)/24,0,1)
   new=np.rint(inp.astype(np.float32)*(1-alpha)+b.astype(np.float32)*alpha).clip(0,255).astype('u1')
   inp[:]=new
  temp.write_bytes(a.tobytes())
 else:temp=orig
 out=D/f'{i:03d}_{name}.moflex'
 env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_RDO_LAMBDA_DELTA='2')
 cmd=[str(FF),'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(temp),'-an','-c:v','mobiclip','-mobiclip','1','-qp','12','-mobi_qyx','4','-preset','medium','-me_method','umh','-psy','0','-g','48','-mo_layout','0','-f','moflex',str(out)]
 t=time.monotonic();p=subprocess.run(cmd,env=env,capture_output=True,timeout=120)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace')[-400:])
 p=subprocess.run([str(FF),'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',str(out),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],capture_output=True,timeout=120)
 if p.returncode or len(p.stdout)!=n*FR:raise RuntimeError('decoder incomplete '+p.stderr.decode(errors='replace')[-200:])
 b=np.frombuffer(p.stdout,dtype='u1').reshape(-1,FR)[:,:PIX].reshape(-1,H,W);a=raw[:,:PIX].reshape(-1,H,W)
 sq=(a.astype('f4')-b.astype('f4'))**2;mse=float(sq.mean());ss=float(np.mean([ssim(a[j],b[j],data_range=255) for k in range(0,n,12) for j in (k,k+1) if j<n]))
 ag=a.astype(np.int16);edge=(np.abs(np.diff(ag,axis=1,prepend=ag[:,:1]))>24)|(np.abs(np.diff(ag,axis=2,prepend=ag[:,:,:1]))>24)
 hf=[];hfs=[]
 for j in range(n):
  s=a[j];im=b[j];grad=np.abs(np.diff(s.astype('i2'),axis=1,prepend=s[:,:1].astype('i2')))+np.abs(np.diff(s.astype('i2'),axis=0,prepend=s[:1,:].astype('i2')))
  mask=(grad<12);low=cv2.GaussianBlur(im,(3,3),0.6);low_s=cv2.GaussianBlur(s,(3,3),0.6)
  hf.append(float(np.abs(im.astype('f4')-low.astype('f4'))[mask].mean()));hfs.append(float(np.abs(s.astype('f4')-low_s.astype('f4'))[mask].mean()))
 p=subprocess.run([str(FP),'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(out)],capture_output=True,text=True)
 pk=[int(x.strip().rstrip(',')) for x in p.stdout.splitlines() if x.strip().rstrip(',').isdigit()]
 if len(pk)!=n:raise RuntimeError('packet mismatch')
 return dict(gop=i,preset=name,bytes=sum(pk),psnr=10*math.log10(65025/mse),ssim=ss,edge_mse=float(sq[edge].mean()),flat_highfreq_decoded=float(np.mean(hf)),flat_highfreq_source=float(np.mean(hfs)),seconds=round(time.monotonic()-t,2))
records=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 futs={pool.submit(process,i,*x):(i,x[0]) for i in idx for x in strategies}
 for f in concurrent.futures.as_completed(futs):
  try:
   a=f.result();records.append(a);print('PASS',a,flush=True)
  except Exception as e:print('FAIL',futs[f],str(e),flush=True)
  (D/'prefilter_results.json').write_text(json.dumps(records,indent=2))
