from pathlib import Path
import numpy as np,cv2,subprocess,json,math,os,concurrent.futures,time
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research/deblock';D.mkdir(parents=True,exist_ok=True)
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda';FP=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not FP.exists():FP=Path('/usr/bin/ffprobe')
W,H=400,224;PIX=W*H;FR=PIX*3//2
indices=[8,22,35];variants=[('baseline',None),('weak','1:1'),('medium','2:2'),('strong','3:3'),('negative','-2:-2'),('zero','0:0')]

def job(i,name,deblock):
 src=R/f'MobiPEG_V5_RateControl/tests/adaptive/input_{i:03d}.raw';o=D/f'part_{i:03d}_{name}.moflex'
 inp=np.fromfile(src,dtype='u1').reshape(-1,FR);n=len(inp)
 env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_RDO_LAMBDA_DELTA='2')
 cmd=[str(FF),'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(src),'-an','-c:v','mobiclip','-mobiclip','1','-qp','12','-mobi_qyx','4','-preset','medium','-me_method','umh','-psy','0','-g','48']
 if deblock is not None:cmd+=['-deblock',deblock]
 cmd+=['-mo_layout','0','-f','moflex',str(o)]
 p=subprocess.run(cmd,env=env,capture_output=True,timeout=120)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace')[-500:])
 p=subprocess.run([str(FF),'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',str(o),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],capture_output=True,timeout=120)
 if p.returncode or len(p.stdout)!=n*FR:raise RuntimeError('decode failed: '+p.stderr.decode(errors='replace')[-500:])
 a=inp[:,:PIX].reshape(-1,H,W);b=np.frombuffer(p.stdout,dtype='u1').reshape(-1,FR)[:,:PIX].reshape(-1,H,W)
 d=a.astype('f4')-b.astype('f4');sq=d*d;mse=float(sq.mean());mean_ss=np.mean([ssim(a[k],b[k],data_range=255) for k in range(0,n,12) for j in (k,k+1) if j<n]) if False else np.mean([ssim(a[j],b[j],data_range=255) for k in range(0,n,12) for j in (k,k+1) if j<n])
 g=a.astype(np.int16);edge=(np.abs(np.diff(g,axis=1,prepend=g[:,:1,:]))>24)|(np.abs(np.diff(g,axis=2,prepend=g[:,:,:1]))>24)
 eng=[]
 for k in range(n):
  s=a[k];sm=cv2.GaussianBlur(s,(3,3),0.6);gradx=np.abs(np.diff(s.astype('i2'),axis=1,prepend=s[:,:1].astype('i2')));grady=np.abs(np.diff(s.astype('i2'),axis=0,prepend=s[:1,:].astype('i2')))
  mask=(gradx+grady)<12
  bb=b[k];low=cv2.GaussianBlur(bb,(3,3),0.6)
  eng.append(float(np.mean(np.abs(bb.astype('f4')-low.astype('f4'))[mask])))
 p=subprocess.run([str(FP),'-v','error','-select_streams','v','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(o)],capture_output=True,text=True)
 pk=[int(x.strip().rstrip(',')) for x in p.stdout.splitlines() if x.strip().rstrip(',').isdigit()]
 return {'gop':i,'mode':name,'bytes':sum(pk),'psnr_y':10*math.log10(65025/mse),'ssim':float(mean_ss),'edge_mse':float(sq[edge].mean()),'flat_high_freq':float(np.mean(eng))}
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 futs={pool.submit(job,i,*z):(i,z[0]) for i in indices for z in variants}
 for f in concurrent.futures.as_completed(futs):
  try:
   o=f.result();results.append(o);print('PASS',o,flush=True)
  except Exception as e:print('FAIL',futs[f],repr(e),flush=True)
  (D/'deblock_tests.json').write_text(json.dumps(results,indent=2))
