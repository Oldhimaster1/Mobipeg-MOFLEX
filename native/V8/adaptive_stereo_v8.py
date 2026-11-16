#!/usr/bin/env python3
"""MobiPEG V8 TextureGuard — stereo-aware, measured R-D controller.

Source: open MobiPEG V7, extended with independently decoded candidate tests.
The original V7 quality candidates remain feasible. V8 additionally tests
psy-off and alternate motion-search candidates and uses a non-degradation
screen before replacing the V7 selection. No Nintendo binaries are used.

V8 still needs physical 3DS verification. Default stereo output: interleaved
24fps/eye (48 coded frames/sec), 400x224 per eye, MOFLEX layout 0.
"""
from pathlib import Path
import argparse,sys,math,hashlib,json,subprocess,concurrent.futures,collections,os,time
import numpy as np
from skimage.metrics import structural_similarity as ssim
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'V7'))
from adaptive_stereo_v7 import run, video_packets, eval_candidate, choose, quality_summary, file_hash, QUANT_SETTINGS, detect_local_cuts
W,H=400,224;PIX=W*H;FR=PIX*3//2;CODED_FPS=48
EXTRAS=[('psyoff',['-psy','0']),('umh',['-me_method','umh']),('psyoff_umh',['-psy','0','-me_method','umh'])]

def measured_extended(job):
 idx,n,source,option,qyx,qp,lam,ffmpeg,ffprobe,folder,keyint,threshold,extra=job
 out=folder/f'v8_part_{idx:03d}_{option}.moflex'
 env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0',MOBI_RDO_PRED_COST='0',MOBI_RDO_LAMBDA_DELTA=str(lam))
 cmd=[ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224','-framerate','48','-i',source,'-an','-c:v','mobiclip','-mobiclip','1','-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g',str(keyint)]+extra+['-mo_layout','0','-f','moflex',out]
 t0=time.monotonic();run(cmd,env,timeout=500)
 ct,size=video_packets(ffprobe,out)
 if ct[0]!=n:raise RuntimeError('encoder produced wrong number of eye frames')
 decoded=run([ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',out,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=240).stdout
 if len(decoded)!=n*FR:raise RuntimeError(f'{option} decoded only {len(decoded)//FR} out of {n} frames')
 src=np.fromfile(source,dtype=np.uint8).reshape(n,FR)
 rec=np.frombuffer(decoded,dtype=np.uint8).reshape(n,FR)
 y=src[:,:PIX].reshape(n,H,W);r=rec[:,:PIX].reshape(n,H,W)
 delta=y.astype(np.int16)-r.astype(np.int16);sq=np.square(delta,dtype=np.int32)
 fm=sq.mean(axis=(1,2));mse=float(fm.mean())
 edge=(np.abs(np.diff(y.astype(np.int16),axis=1,prepend=y[:,:1,:].astype(np.int16)))>24) | (np.abs(np.diff(y.astype(np.int16),axis=2,prepend=y[:,:,:1].astype(np.int16)))>24)
 edge_mse=float(sq[edge].mean()) if np.count_nonzero(edge)>200 else mse
 cuts=detect_local_cuts(y,threshold)
 cutids=sorted({j for c in cuts for j in range(2*c,min(n,2*c+12))})
 cutm=float(fm[cutids].mean()) if cutids else float(fm[:min(n,12)].mean())
 inds=sorted(set([j for k in range(0,n,12) for j in (k,k+1) if j<n]+list(range(min(n,4)))+cutids[::4]))
 ss=np.array([ssim(y[j],r[j],data_range=255) for j in inds]);mss=float(ss.mean())
 src16=src.astype(np.int16);d=src16-rec.astype(np.int16)
 u=float(np.square(d[:,PIX:PIX+PIX//4],dtype=np.int32).mean());v=float(np.square(d[:,PIX+PIX//4:],dtype=np.int32).mean())
 v5cost=(mse*.65+(u+v)*.075+(1-mss)*500*.20)*n
 return {'index':idx,'coded_frames':n,'option':option,'qyx':qyx,'qp':qp,'lambda_delta':lam,'file':str(out),'file_bytes':out.stat().st_size,'video_bytes':size[0],
  'seconds':round(time.monotonic()-t0,2),'mse_y':mse,'mse_u':u,'mse_v':v,'psnr_y':10*math.log10(65025/max(1e-9,mse)),
  'ssim_both':mss,'ssim_left':float(np.mean([s for j,s in zip(inds,ss) if j%2==0])),'ssim_right':float(np.mean([s for j,s in zip(inds,ss) if j%2==1])),
  'left_mse':float(fm[::2].mean()),'right_mse':float(fm[1::2].mean()),'worst_8th_mse':float(np.sort(fm)[-max(1,n//8):].mean()),
  'edge_mse':edge_mse,'cut_count':len(cuts),'cut_frames':len(cutids),'cut_mean_mse':cutm,'v5_cost':v5cost}

def metric_summary(rows):
 n=sum(z['coded_frames'] for z in rows);avg=lambda k:sum(z[k]*z['coded_frames'] for z in rows)/n
 cut=[z for z in rows if z['cut_count']];cutm=sum(z['cut_mean_mse']*z['cut_frames'] for z in cut)/max(1,sum(z['cut_frames'] for z in cut)) if cut else None
 return {'coded_frames':n,'video_bytes':sum(z['video_bytes'] for z in rows),'psnr_y':10*math.log10(65025/max(1e-9,avg('mse_y'))),
  'ssim_both':avg('ssim_both'),'edge_mse':avg('edge_mse'),'worst12p5_mse':avg('worst_8th_mse'),'cut_mse':cutm,
  'left_psnr_y':10*math.log10(65025/max(1e-9,avg('left_mse'))),'right_psnr_y':10*math.log10(65025/max(1e-9,avg('right_mse'))),
  'variant_counts':dict(collections.Counter(z['option'] for z in rows))}

def acceptable(new,old):
 # Conservative tolerances account for sampled SSIM noise, while requiring
 # strict PSNR protection and non-degradation of detail/transition metrics.
 if new['psnr_y']<old['psnr_y']-0.002 or new['ssim_both']<old['ssim_both']-0.00003:return False
 if new['edge_mse']>old['edge_mse']+.03 or new['worst12p5_mse']>old['worst12p5_mse']+.03:return False
 if old['cut_mse'] is not None and new['cut_mse'] is not None and new['cut_mse']>old['cut_mse']+.04:return False
 return True

def evaluate(groups,budget,v7baseline):
 variants=[(.5,.15,.2,.15),(.4,.25,.2,.15),(.55,.25,.1,.1),(.4,.35,.2,.05),(.6,.15,.15,.1),(.6,.2,.15,.05)]
 base=metric_summary(v7baseline);winners=[(v7baseline,base,False)]
 for wy,ws,we,wc in variants:
  def objective(z):
   y=z['mse_y'];trans=z['cut_mean_mse'] if z['cut_count'] else z['mse_y']
   return wy*y+ws*220*(1-z['ssim_both'])+we*.27*z['edge_mse']+wc*trans
  try:
   choice=choose(groups,budget,objective,step=512,anchors=v7baseline,mse_guard=2.0)
   met=metric_summary(choice)
   if acceptable(met,base):winners.append((choice,met,True))
  except (ValueError,RuntimeError) as e:print('Variant optimizer skipped:',str(e),flush=True)
 def rank(p):
  m=p[1];return (m['psnr_y']-base['psnr_y'])*3+(m['ssim_both']-base['ssim_both'])*250+ (base['edge_mse']-m['edge_mse'])*.005+((base['cut_mse']-m['cut_mse'])*.008 if base['cut_mse'] is not None else 0)
 return max(winners,key=rank),base,len(winners)-1

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--raw',required=True,help='pre-normalized 400x224 alternating-eye YUV420p 48 coded fps')
 p.add_argument('--source',help='input MP4/MKV for audio')
 p.add_argument('--encoder',required=True,help='MobiPEG V7/V8 FFmpeg with MOFLEX muxer')
 p.add_argument('--probe',required=True);p.add_argument('--out-dir',required=True)
 p.add_argument('--system-ffmpeg',default='ffmpeg');p.add_argument('--video-kbps',type=float,default=1266.5)
 p.add_argument('--target-video-bytes',type=int);p.add_argument('--official',help='reference MOFLEX to match video payload, optional')
 p.add_argument('--workers',type=int,default=4);p.add_argument('--max-gops',type=int,help='smoke-test limit, no final video')
 p.add_argument('--scene-threshold',type=float,default=38);p.add_argument('--long-gops',action='store_true',help='reserved (not yet portable, use 96-frame safe segmentation)')
 args=p.parse_args()
 if args.long_gops:raise ValueError('Long-GOP merging requires separate hardware qualification; V8 portable runner currently uses V7-compatible segmentation')
 if not 1<=args.workers<=16:raise ValueError('workers must be 1..16')
 raw=Path(args.raw).resolve();out=Path(args.out_dir).resolve();out.mkdir(parents=True,exist_ok=True)
 if raw.stat().st_size%FR:raise ValueError('incomplete source YUV frame')
 total=raw.stat().st_size//FR
 if total%2:raise ValueError('stereo source must contain left+right pairs')
 gops=[]
 with raw.open('rb') as f:
  for idx,offset in enumerate(range(0,total,96)):
   if args.max_gops is not None and idx>=args.max_gops:break
   n=min(96,total-offset);data=f.read(n*FR);part=out/f'input_{idx:03d}.raw'
   if not part.exists() or part.stat().st_size!=len(data) or hashlib.sha256(part.read_bytes()).digest()!=hashlib.sha256(data).digest():part.write_bytes(data)
   gops.append((idx,n,part))
 if args.target_video_bytes is not None:budget=args.target_video_bytes
 elif args.official:budget=video_packets(args.probe,Path(args.official))[1][0]
 else:budget=int(args.video_kbps*1000/8*(total/CODED_FPS))
 if args.max_gops is not None:budget=int(budget*sum(x[1] for x in gops)/total)
 source_hash=file_hash(raw);encoder_hash=file_hash(args.encoder)
 print('MobiPEG V8: source',total,'coded eye frames, GOPs',len(gops),'video budget',budget,'bytes',flush=True)
 settings=[(f'{tag}_lambda{lam}',q,qp,lam) for tag,q,qp in QUANT_SETTINGS for lam in (0,2)]
 first_cache=out/'v8_initial_candidates.json'
 signature={'source_sha256':source_hash,'encoder_sha256':encoder_hash,'initial_settings':settings,'threshold':args.scene_threshold}
 meta=out/'v8_cache_signature.json'
 cache_ok=meta.exists() and json.loads(meta.read_text())==signature
 initial=json.loads(first_cache.read_text()) if cache_ok and first_cache.exists() else []
 if not cache_ok:meta.write_text(json.dumps(signature,indent=2))
 completed={(x['index'],x['option']):x for x in initial}
 first=[(idx,n,part,tag,q,qp,lam,args.encoder,args.probe,out,48,args.scene_threshold) for idx,n,part in gops for tag,q,qp,lam in settings if (idx,tag) not in completed]
 print('Stage 1: initial R-D tests',len(first),'cache',len(completed),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(eval_candidate,job):job for job in first}
  for fut in concurrent.futures.as_completed(futures):
   z=fut.result();completed[(z['index'],z['option'])]=z
   first_cache.write_text(json.dumps(sorted(completed.values(),key=lambda x:(x['index'],x['option'])),indent=2))
   print('BASE',z['index'],z['option'],z['video_bytes'],round(z['psnr_y'],3),flush=True)
 groups=[[completed[(idx,tag)] for tag,q,qp,lam in settings] for idx,n,part in gops]
 initial_only=[[z for z in group if z['lambda_delta']==0] for group in groups]
 v5=choose(initial_only,budget,lambda z:z['v5_cost']/z['coded_frames'],step=512)
 def v7loss(z):
  baseline=.65*z['mse_y']+.15*(1-z['ssim_both'])*220+.2*.27*z['edge_mse']
  transition=z['cut_mean_mse'] if z['cut_count'] else z['mse_y']
  return .85*baseline+.15*transition
 v7sel=choose(groups,budget,v7loss,step=512,anchors=v5,mse_guard=2.0)
 print('Measured baseline V7 profile:',json.dumps(metric_summary(v7sel)),flush=True)
 # Stage 2 tests psy-off, UMH motion search, and their combination on the
 # measured V7 selection only. Invalid decoding is rejected, never shipped.
 extra_cache=out/'v8_extra_candidates.json';extra_meta=out/'v8_extra_signature.json'
 fingerprint={'baseline':[(z['index'],z['option'],z['qyx'],z['qp'],z['lambda_delta']) for z in v7sel],'base_signature':signature}
 ok=extra_meta.exists() and json.loads(extra_meta.read_text())==fingerprint
 extras=json.loads(extra_cache.read_text()) if ok and extra_cache.exists() else []
 if not ok:extra_meta.write_text(json.dumps(fingerprint,indent=2))
 extra_done={(z['index'],z['option']):z for z in extras}
 jobs=[]
 for old,(idx,n,part) in zip(v7sel,gops):
  for name,options in EXTRAS:
   if (idx,name) not in extra_done:jobs.append((idx,n,part,name,old['qyx'],old['qp'],old['lambda_delta'],args.encoder,args.probe,out,48,args.scene_threshold,options))
 print('Stage 2: texture/psychovisual experiments',len(jobs),flush=True)
 failures=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(measured_extended,j):j for j in jobs}
  for fut in concurrent.futures.as_completed(futures):
   job=futures[fut]
   try:
    z=fut.result();extra_done[(z['index'],z['option'])]=z
    extra_cache.write_text(json.dumps(sorted(extra_done.values(),key=lambda x:(x['index'],x['option'])),indent=2))
    print('EXTENDED',z['index'],z['option'],z['video_bytes'],round(z['psnr_y'],3),flush=True)
   except Exception as e:
    msg=f'{job[0]} {job[3]}: {e}';failures.append(msg);print('REJECT (invalid output)',msg,flush=True)
 allgroups=[group+[x for nm,opt in EXTRAS if (x:=extra_done.get((idx,nm))) is not None] for idx,group in enumerate(groups)]
 (best,met,innovated),base,viable=evaluate(allgroups,budget,v7sel)
 print('V8 candidate',json.dumps(met,indent=2),'passed constraints',innovated,'Pareto alternatives',viable,flush=True)
 (out/'V8_PROFILE_REPORT.json').write_text(json.dumps({'v7_baseline':base,'V8_texture_guard':met,'new_profile_selected':innovated,'rejected_candidates':failures},indent=2))
 (out/'V8_PROFILE_SELECTION.json').write_text(json.dumps([{k:z[k] for k in ('index','option','file','coded_frames','video_bytes')} for z in best],indent=2))
 if args.max_gops is not None:print('Smoke-test complete. No final video generated.',flush=True);return
 if not args.source:raise ValueError('--source MP4/MKV required for audio encoding')
 pcm=out/'audio_44100_s16le.pcm'
 if not pcm.exists():run([args.system_ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y','-i',args.source,'-map','0:a:0','-ac','2','-ar','44100','-c:a','pcm_s16le','-f','s16le',pcm],timeout=300)
 manifest=out/'V8_COMBINE.ffconcat'
 manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{Path(z['file']).resolve()}'\nduration {z['coded_frames']/CODED_FPS:.9f}\n" for z in best))
 final=out/'MobiPEG_V8_STEREO_3D.moflex'
 run([args.encoder,'-nostdin','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',manifest,
      '-f','s16le','-ar','44100','-ac','2','-i',pcm,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le','-mo_audio','adpcm','-mo_layout','0','-mo_interleave_input_double_rate','1','-f','moflex',final],timeout=400)
 ct,b=video_packets(args.probe,final)
 if ct[0]!=total or b[0]!=sum(z['video_bytes'] for z in best) or ct[2]!=total:raise RuntimeError('output packet validation failed')
 for mapstr in ('0:v:0','0:a:0'):
  run([args.system_ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',final,'-map',mapstr,'-f','null','-'],timeout=400)
 print('V8 VERIFIED',final,final.stat().st_size,'bytes; 3D hardware test still needed',flush=True)
if __name__=='__main__':main()
