from pathlib import Path
import numpy as np,subprocess,concurrent.futures,json,math,time,os
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research/lambda_expanded';D.mkdir(exist_ok=True,parents=True)
FF=R/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda';FP=R/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not FP.exists():FP=Path('/usr/bin/ffprobe')
ORG=R/'MobiPEG_V5_RateControl/tests/adaptive';PIX=400*224;FR=PIX*3//2
jobs=[(i,lam) for i in (4,22,35,38) for lam in (-2,-1,0,1,2,3,4,5,6,8)]

def run(i,lam):
 inp=ORG/f'input_{i:03d}.raw';src=np.fromfile(inp,dtype='u1').reshape(-1,FR);n=len(src)
 out=D/f'part_{i:03d}_lambda_{lam:+}.moflex';rec=D/f'part_{i:03d}_lambda_{lam:+}.raw'
 env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0',MOBI_RDO_LAMBDA_DELTA=str(lam))
 cmd=[str(FF),'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(inp),'-an','-c:v','mobiclip','-mobiclip','1','-qp','12','-mobi_qyx','4','-preset','medium','-me_method','umh','-psy','0','-g','48','-mo_layout','0','-f','moflex',str(out)]
 t=time.monotonic();p=subprocess.run(cmd,env=env,capture_output=True,timeout=150)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace')[-200:])
 p=subprocess.run([str(FF),'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',str(out),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],capture_output=True,timeout=80)
 if p.returncode or len(p.stdout)!=n*FR:raise RuntimeError('decoder incomplete')
 dec=np.frombuffer(p.stdout,dtype='u1').reshape(-1,FR);d=(src[:,:PIX].astype(np.float32)-dec[:,:PIX].astype(np.float32))
 mse=float((d*d).mean());a=src[:,:PIX].reshape(-1,224,400);b=dec[:,:PIX].reshape(-1,224,400)
 ss=np.mean([ssim(a[k],b[k],data_range=255) for k in range(0,n,12) for j in (k,k+1) if j<n]) if False else np.mean([ssim(a[j],b[j],data_range=255) for k in range(0,n,12) for j in (k,k+1) if j<n])
 p=subprocess.run([str(FP),'-v','error','-select_streams','v','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(out)],capture_output=True,text=True)
 pkt=[int(s.strip().rstrip(',')) for s in p.stdout.splitlines() if s.strip().rstrip(',').isdigit()]
 if len(pkt)!=n:raise RuntimeError('packet count incomplete')
 return {'gop':i,'lambda_delta':lam,'video_bytes':sum(pkt),'PSNR_Y':10*math.log10(65025/mse),'SSIM':float(ss),'seconds':round(time.monotonic()-t,2)}
rs=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 fut={pool.submit(run,i,lam):(i,lam) for i,lam in jobs}
 for f in concurrent.futures.as_completed(fut):
  try:
   a=f.result();rs.append(a);print('PASS',a,flush=True)
  except Exception as e:print('FAIL',fut[f],str(e),flush=True)
  (D/'lambda_sweep_results.json').write_text(json.dumps(rs,indent=2))
