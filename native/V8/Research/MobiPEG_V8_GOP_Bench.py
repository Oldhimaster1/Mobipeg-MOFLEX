#!/usr/bin/env python3
"""Compare identical stereoscopic 4-s clips with original V7 results vs longer GOPs.
No vendor encoders. Creates reproducible per-scene MP4-independent tests."""
import subprocess,time,os,json,math,concurrent.futures
from pathlib import Path
import numpy as np
from skimage.metrics import structural_similarity as ssim
base=Path('/mnt/data');out=base/'MobiPEG_V8_GOP_Research';out.mkdir(exist_ok=True)
raw=base/'MobiPEG_V5_RateControl/tests/avatar_eyes_24fps.yuv'
v7raw=base/'MobiPEG_V7_Engineering/bench/V7_decoded_400x224_eyes.yuv'
enc=base/'MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda'
probe=base/'MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe'
if not probe.exists():probe=Path('/usr/bin/ffprobe')
PIX=400*224;FB=PIX*3//2;duration=192;STARTS=[0,8,40,60,92]
ref=np.memmap(raw,mode='r',dtype=np.uint8).reshape(-1,FB)
v7=np.memmap(v7raw,mode='r',dtype=np.uint8).reshape(-1,FB)
assert len(ref)==len(v7)==4826
files=[]
for s in STARTS:
 src=out/f'raw_{s:03d}s.yuv';bs=s*48;count=min(duration,len(ref)-bs)
 if not src.exists():src.write_bytes(ref[bs:bs+count].tobytes())
 files.append((s,src,bs,count))

def mse(a,b):
 diff=a.astype(np.int16)-b.astype(np.int16)
 return float(np.mean(diff.astype(np.float32)**2))

def scores(s,frames):
 bs=s*48;refy=ref[bs:bs+len(frames),:PIX].reshape(-1,224,400)
 cury=frames[:,:PIX].reshape(-1,224,400)
 sq=(np.array(refy,dtype=np.int16)-np.array(cury,dtype=np.int16)).astype(np.float32)**2
 fm=np.mean(sq,axis=(1,2));Y=float(np.mean(fm))
 subs=list(range(0,len(frames),12));ids=sorted(set([j+k for j in subs for k in (0,1) if j+k<len(frames)]))
 ss=float(np.mean([ssim(refy[i],cury[i],data_range=255) for i in ids]))
 grad=np.abs(np.diff(refy.astype(np.int16),axis=2,prepend=refy[:,:,:1].astype(np.int16)))>24
 edges=float(np.mean(sq[grad])) if grad.any() else Y
 return {'psnr_y':round(10*math.log10(65025/max(1e-9,Y)),5),'mse_y':Y,'ssim':round(ss,6),'worst12p5_mse':round(float(np.sort(fm)[-max(1,len(fm)//8):].mean()),4),'edge_mse':round(edges,4),'left_mse':round(float(fm[::2].mean()),4),'right_mse':round(float(fm[1::2].mean()),4)}

# Count V7 packet bytes by slicing full video according to timestamps, rather than container overhead.
full=base/'MobiPEG_V7_Engineering/outputs/Avatar_3D_MobiPEG_V7_SceneBalanced.moflex'
packet_bytes=[]
r=subprocess.run([str(probe),'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(full)],capture_output=True,text=True,timeout=120)
for line in r.stdout.splitlines():
 try:packet_bytes.append(int(line.strip().rstrip(',')))
 except:pass
print('PACKETS',len(packet_bytes),flush=True)
if len(packet_bytes)!=4826:raise ValueError('incorrect video packet count!')
baselines={}
for s,source,bs,n in files:
 a=scores(s,v7[bs:bs+n]);a.update(start_seconds=s,variant='V7 original 2sec',video_bytes=sum(packet_bytes[bs:bs+n]),coded_frames=n)
 baselines[s]=a;print('BASE',a,flush=True)

params=[(3,16,0),(3,17,2),(4,12,0),(4,12,2),(4,13,2),(4,14,2),(5,12,2)]
experiments=[]
for s,source,bs,n in files:
 for qyx,qp,lam in params:
  for keyint in [96,192]:
   experiments.append((s,source,n,qyx,qp,lam,keyint))

def test(item):
 s,source,n,qyx,qp,lam,keyint=item
 suffix=f'g{keyint}_q{qyx}_{qp}_l{lam}';outfile=out/f'{s:03d}s_{suffix}.moflex';rec=out/f'{s:03d}s_{suffix}.raw'
 if not outfile.exists() or outfile.stat().st_size<2000:
  args=[str(enc),'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',str(source),'-an','-c:v','mobiclip','-mobiclip','1','-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g',str(keyint),'-mo_layout','0','-f','moflex',str(outfile)]
  env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0',MOBI_RDO_PRED_COST='0',MOBI_RDO_LAMBDA_DELTA=str(lam))
  t=time.monotonic();p=subprocess.run(args,env=env,capture_output=True,timeout=150)
  if p.returncode:raise RuntimeError(f'encoder failed {item}: {p.stderr.decode(errors="replace")[-400:]}')
  encode_seconds=time.monotonic()-t
 else:encode_seconds=-1
 if not rec.exists() or rec.stat().st_size!=n*FB:
  p=subprocess.run([str(enc),'-hide_banner','-nostdin','-loglevel','error','-xerror','-y','-i',str(outfile),'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo',str(rec)],capture_output=True,timeout=80)
  if p.returncode:raise RuntimeError(f'decode failure {item}: {p.stderr.decode(errors="replace")[-300:]}')
 if rec.stat().st_size != n*FB:raise ValueError(f'output frame mismatch {item}')
 r=subprocess.run([str(probe),'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=size','-of','csv=p=0',str(outfile)],capture_output=True,text=True)
 pack=[int(x.strip().rstrip(',')) for x in r.stdout.splitlines() if x.strip().rstrip(',').isdigit()]
 if len(pack)!=n:raise RuntimeError(f'packet mismatch {item} {len(pack)}')
 reconstructed=np.memmap(rec,dtype='u1',mode='r').reshape(n,FB)
 data=scores(s,reconstructed)
 data.update(start_seconds=s,variant=suffix,video_bytes=sum(pack),coded_frames=n,encode_seconds=round(encode_seconds,2),qyx=qyx,qp=qp,lambda_delta=lam,keyint=keyint,file=str(outfile))
 return data

results=list(baselines.values());result_path=out/'gop_trial_results.json';result_path.write_text(json.dumps(results,indent=2))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 futures={pool.submit(test,e):e for e in experiments}
 for fut in concurrent.futures.as_completed(futures):
  try:
   data=fut.result();results.append(data)
   print('DONE',data['start_seconds'],data['variant'],data['video_bytes'],data['psnr_y'],data['ssim'],flush=True)
  except Exception as e:print('FAIL',futures[fut],repr(e),flush=True)
  result_path.write_text(json.dumps(results,indent=2))
print('FINISH',len(results),flush=True)
