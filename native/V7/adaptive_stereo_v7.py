#!/usr/bin/env python3
"""MobiPEG V7 — stereo-aware measured rate-distortion controller.

Independent MobiClip encoder (no Nintendo DLLs). V7 tests each quantizer
configuration at two mode-decision lambda offsets, decodes every trial,
measures BOTH eyes plus edge detail and scene-change onset, and selects one
candidate per 2-second GOP under a strict video-payload byte budget.

Provisional research build: stereo layout0, 400x224 per eye, 24 fps per eye.
Hardware testing on a real original 3DS is required before release.
"""
import argparse,collections,concurrent.futures,csv,hashlib,json,math,os,subprocess,time
from pathlib import Path
import numpy as np
from skimage.metrics import structural_similarity as ssim
W,H=400,224
PIX=W*H
FR=PIX*3//2
CODED_FPS=48
QUANT_SETTINGS=[('detail46',3,16),('detail47',3,17),('reference48',4,12),('save49',4,13),('save50',4,14)]


def run(args,env=None,timeout=300):
    p=subprocess.run([str(a) for a in args],capture_output=True,env=env,timeout=timeout)
    if p.returncode:raise RuntimeError(f'Command exit={p.returncode}: {" ".join(map(str,args))}\n{p.stderr.decode(errors="replace")[-1000:]}')
    return p


def video_packets(probe,f):
    p=run([probe,'-v','error','-show_packets','-show_entries','packet=stream_index,size','-of','csv=p=0',f],timeout=120)
    ct=collections.Counter();size=collections.Counter()
    for line in p.stdout.decode(errors='replace').splitlines():
        part=line.strip().strip(',').split(',')
        if len(part)>=2 and part[0].isdigit() and part[1].isdigit():ct[int(part[0])]+=1;size[int(part[0])]+=int(part[1])
    return ct,size


def detect_local_cuts(y,threshold):
    """Y is full 4x4? No: original 400x224 Y planes, L/R interleaved.
    Compare LEFT stereo eye in successive display frames at 1/8 resolution.
    """
    yy=np.asarray(y[::2,::8,::8],dtype=np.int16)
    if len(yy)<2:return []
    mad=np.abs(yy[1:]-yy[:-1]).mean(axis=(1,2))
    # Excludes very first pair; GOP starts at independently decoded keyframe.
    return [int(i)+1 for i in np.flatnonzero(mad>threshold)]


def eval_candidate(job):
    (idx,n,source,option,qyx,qp,delta,ffmpeg,ffprobe,folder,keyint,threshold)=job
    out=folder/f'part_{idx:03d}_{option}.moflex'
    env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0',MOBI_RDO_PRED_COST='0',MOBI_RDO_LAMBDA_DELTA=str(delta))
    cmd=[ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p',
         '-video_size',f'{W}x{H}','-framerate',str(CODED_FPS),'-i',source,'-an','-c:v','mobiclip','-mobiclip','1',
         '-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g',str(keyint),'-mo_layout','0','-f','moflex',out]
    started=time.monotonic()
    run(cmd,env,timeout=500)
    ct,size=video_packets(ffprobe,out)
    if ct[0]!=n:raise RuntimeError(f'{out.name}: expected {n}, got {ct[0]} video frames')
    dec=run([ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',out,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],timeout=200).stdout
    if len(dec)!=n*FR:raise RuntimeError(f'{out.name}: expected {n*FR}, got {len(dec)} decoded bytes')
    y=np.fromfile(source,dtype=np.uint8).reshape(n,FR)[:,:PIX].reshape(n,H,W)
    rec=np.frombuffer(dec,dtype=np.uint8).reshape(n,FR)[:,:PIX].reshape(n,H,W)
    diff=np.asarray(y,dtype=np.int16)-np.asarray(rec,dtype=np.int16)
    sq=np.square(diff,dtype=np.int32)
    frame_mse=np.mean(sq,axis=(1,2));mse=float(np.mean(frame_mse))
    left=float(np.mean(frame_mse[::2]));right=float(np.mean(frame_mse[1::2]))
    yy=np.asarray(y,dtype=np.int16)
    edges=(np.abs(np.diff(yy,axis=2,prepend=yy[:,:,:1]))>24)|(np.abs(np.diff(yy,axis=1,prepend=yy[:,:1,:]))>24)
    edge_mse=float(np.mean(sq[edges])) if np.count_nonzero(edges)>200 else mse
    local_cuts=detect_local_cuts(y,threshold)
    cut_idx=sorted({j for c in local_cuts for j in range(2*c,min(n,2*c+12))})
    cut_mse=float(np.mean(frame_mse[cut_idx])) if cut_idx else float(np.mean(frame_mse[:min(12,n)]))
    # Both stereo eyes: [L0,R0,L6,R6,...] plus scene-cut onset and first pairs.
    sampled=sorted(set([j for k in range(0,n,12) for j in (k,k+1) if j<n]
                       +list(range(min(n,4)))+cut_idx[::4]))
    ss=np.array([ssim(y[j],rec[j],data_range=255) for j in sampled])
    ssim_both=float(np.mean(ss))
    ssim_left=float(np.mean([s for j,s in zip(sampled,ss) if j%2==0]));ssim_right=float(np.mean([s for j,s in zip(sampled,ss) if j%2==1]))
    # Original V5's baseline objective is retained for the A/B reference.
    x=np.fromfile(source,dtype=np.uint8).reshape(n,FR).astype(np.int16)-np.frombuffer(dec,dtype=np.uint8).reshape(n,FR).astype(np.int16)
    u=float(np.mean(np.square(x[:,PIX:PIX+PIX//4],dtype=np.int32)))
    v=float(np.mean(np.square(x[:,PIX+PIX//4:],dtype=np.int32)))
    v5cost=(mse*.65+(u+v)*.075+(1-ssim_both)*500*.20)*n
    record={'index':idx,'coded_frames':n,'option':option,'qyx':qyx,'qp':qp,'lambda_delta':delta,'file':str(out),'file_bytes':out.stat().st_size,
           'video_bytes':size[0],'seconds':round(time.monotonic()-started,3),'mse_y':mse,'mse_u':u,'mse_v':v,
           'psnr_y':10*math.log10(65025/max(1e-9,mse)),'ssim_both':ssim_both,'ssim_left':ssim_left,'ssim_right':ssim_right,
           'left_mse':left,'right_mse':right,'worst_8th_mse':float(np.mean(np.sort(frame_mse)[-max(1,n//8):])),
           'edge_mse':edge_mse,'cut_count':len(local_cuts),'cut_frames':len(cut_idx),'cut_mean_mse':cut_mse,'v5_cost':v5cost}
    return record


def choose(groups,budget,score,step=512,anchors=None,mse_guard=2.):
    """Conservative multiple-choice knapsack. Optional GOP quality floor vs anchor."""
    choices=[]
    for i,gr in enumerate(groups):
        candidates=[dict(z) for z in gr if anchors is None or z['mse_y']<=anchors[i]['mse_y']+mse_guard]
        if not candidates:raise RuntimeError(f'no allowed candidates for GOP {i}')
        for z in candidates:z['cost']=score(z)*z['coded_frames']
        choices.append(candidates)
    cheapest=[min(z['video_bytes'] for z in grp) for grp in choices]
    capacity=(budget-sum(cheapest))//step
    if capacity<0:raise ValueError(f'Impossible video budget {budget:,}, minimum allowed {sum(cheapest):,}')
    dp=np.full(capacity+1,np.inf);dp[0]=0
    traces=[]
    for i,grp in enumerate(choices):
        nxt=np.full_like(dp,np.inf);parent=np.full(len(dp),-1,dtype=np.int32);opt=np.full(len(dp),-1,dtype=np.int16)
        for j,x in enumerate(grp):
            extra=math.ceil((x['video_bytes']-cheapest[i])/step)
            if extra>capacity:continue
            vals=dp[:len(dp)-extra]+x['cost']
            better=vals<nxt[extra:]
            nxt[extra:][better]=vals[better]
            parent[extra:][better]=np.flatnonzero(better)
            opt[extra:][better]=j
        if not np.isfinite(nxt).any():raise RuntimeError(f'DP failed GOP {i}')
        dp=nxt;traces.append((parent,opt))
    k=int(np.argmin(dp));result=[]
    for i in reversed(range(len(choices))):
        parent,opt=traces[i];j=int(opt[k])
        if j<0:raise RuntimeError(f'DP backtrack failure GOP {i}')
        result.append(choices[i][j]);k=int(parent[k])
    result.reverse()
    assert sum(r['video_bytes'] for r in result)<=budget
    return result


def quality_summary(rows):
    n=sum(x['coded_frames'] for x in rows)
    avg=lambda k:sum(x[k]*x['coded_frames'] for x in rows)/n
    pts=[x for x in rows if x['cut_count']]
    cut=sum(x['cut_mean_mse']*x['cut_frames'] for x in pts)/sum(x['cut_frames'] for x in pts) if pts else None
    return {'video_bytes':sum(x['video_bytes'] for x in rows),'coded_frames':n,'psnr_y':10*math.log10(65025/max(avg('mse_y'),1e-9)),
            'sampled_both_eye_ssim_y':avg('ssim_both'),'edge_mse':avg('edge_mse'),'cut_mse':cut,
            'left_psnr_y':10*math.log10(65025/max(avg('left_mse'),1e-9)),'right_psnr_y':10*math.log10(65025/max(avg('right_mse'),1e-9)),
            'lambda2_gops':sum(z['lambda_delta']==2 for z in rows),'options':dict(collections.Counter(z['option'] for z in rows))}


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as fp:
        for part in iter(lambda:fp.read(4<<20),b''):
            h.update(part)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',required=True);p.add_argument('--source',help='original MP4, for audio mux')
    p.add_argument('--encoder',required=True);p.add_argument('--probe',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--official',help='official reference MOFLEX for exact packet video budget')
    p.add_argument('--video-kbps',type=float,default=1266.5);p.add_argument('--target-video-bytes',type=int)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--max-gops',type=int)
    p.add_argument('--gop-frames',type=int,default=96);p.add_argument('--keyint',type=int,default=48)
    p.add_argument('--lambda-deltas',default='0,2',help='experimental modes; default 0 and 2')
    p.add_argument('--scene-threshold',type=float,default=38.0);p.add_argument('--scene-weight',type=float,default=.15)
    p.add_argument('--guard-mse',type=float,default=2.0)
    p.add_argument('--system-ffmpeg',default='ffmpeg')
    a=p.parse_args()
    if a.gop_frames<=0 or a.gop_frames%2 or a.keyint<2 or a.keyint%2:raise ValueError('segment and keyint must be positive even numbers of coded frames')
    if not 0<=a.scene_weight<=1:raise ValueError('scene weight must be [0,1]')
    if not 1<=a.workers<=32:raise ValueError('workers must be 1..32')
    deltas=sorted({int(x) for x in a.lambda_deltas.split(',')});assert 0 in deltas
    out=Path(a.out_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    p_raw=Path(a.raw).resolve();assert p_raw.stat().st_size%FR==0
    total=p_raw.stat().st_size//FR
    assert total%2==0
    gops=[]
    with p_raw.open('rb') as f:
        for i,offset in enumerate(range(0,total,a.gop_frames)):
            if a.max_gops is not None and i>=a.max_gops:break
            n=min(a.gop_frames,total-offset);name=out/f'input_{i:03d}.raw'
            data=f.read(n*FR)
            if len(data)!=n*FR:raise RuntimeError('Incomplete source')
            if not name.exists() or name.stat().st_size!=len(data) or hashlib.sha256(name.read_bytes()).digest()!=hashlib.sha256(data).digest():name.write_bytes(data)
            gops.append((i,n,name))
    if a.target_video_bytes is not None:budget=a.target_video_bytes
    elif a.official:budget=video_packets(a.probe,Path(a.official))[1][0]
    else:budget=int(a.video_kbps*1000/8*(total/CODED_FPS))
    if a.max_gops is not None:budget=int(budget*sum(n for i,n,z in gops)/total)
    print('source',total,'coded eye frames',len(gops),'segments', 'video budget',budget, 'bytes',flush=True)
    settings=[(f'{nm}_lambda{d}',q,qp,d) for nm,q,qp in QUANT_SETTINGS for d in deltas]
    jobs=[(i,n,f,nm,q,qp,d,a.encoder,a.probe,out,a.keyint,a.scene_threshold) for i,n,f in gops for nm,q,qp,d in settings]
    trials=[];t0=time.monotonic()
    cache=out/'v7_trial_measurements.json';fingerprint={'raw_sha256':file_hash(p_raw),'settings':settings,'keyint':a.keyint,'gop_frames':a.gop_frames,'scene_threshold':a.scene_threshold,'encoder_sha256':file_hash(a.encoder)}
    manifest=out/'cache_fingerprint.json'
    if cache.exists() and manifest.exists() and json.loads(manifest.read_text())==fingerprint:
        trials=json.loads(cache.read_text())
    else:
        if cache.exists():print('Ignoring old trial measurements (different source/settings)',flush=True)
        cache.write_text('[]');manifest.write_text(json.dumps(fingerprint,indent=2))
    by_name={(x['index'],x['option']):x for x in trials};todo=[j for j in jobs if (j[0],j[3]) not in by_name]
    print('existing',len(by_name),'trials',len(todo),'to encode/decode',flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(eval_candidate,job):job for job in todo}
        for fut in concurrent.futures.as_completed(futures):
            x=fut.result();by_name[(x['index'],x['option'])]=x
            print(' GOP',x['index'],'option',x['option'],'bytes',x['video_bytes'],'PSNR',round(x['psnr_y'],3),'SSIM',round(x['ssim_both'],4),flush=True)
            cache.write_text(json.dumps(sorted(by_name.values(),key=lambda z:(z['index'],z['option'])),indent=2))
    groups=[[by_name[(i,nm)] for nm,q,qp,d in settings] for i,n,f in gops]
    old_groups=[[x for x in g if x['lambda_delta']==0] for g in groups]
    # Retain a conservative V5-style anchor before optimizing the two-eye
    # scene-aware objective; V7 never silently degrades any GOP severely.
    baseline=choose(old_groups,budget,lambda x:x['v5_cost']/x['coded_frames'],step=512)
    def loss(x):
        base=.65*x['mse_y']+.15*(1-x['ssim_both'])*220+.20*x['edge_mse']*.27
        trans=x['cut_mean_mse'] if x['cut_count'] else x['mse_y']
        return (1-a.scene_weight)*base+a.scene_weight*trans
    result=choose(groups,budget,loss,step=512,anchors=baseline,mse_guard=a.guard_mse)
    summary={'baseline':quality_summary(baseline),'selected':quality_summary(result),'elapsed_trials_s':round(time.monotonic()-t0,2),
             'scene_weight':a.scene_weight,'scene_threshold':a.scene_threshold,'lambda_deltas':deltas,'keyint':a.keyint,'gop_frames':a.gop_frames,
             'hardware_validated':False}
    (out/'V7_RESULTS.json').write_text(json.dumps(summary,indent=2));print('V7 summary',json.dumps(summary),flush=True)
    chosen=[{'index':x['index'],'option':x['option'],'file':x['file'],'coded_frames':x['coded_frames'],'video_bytes':x['video_bytes']} for x in result]
    (out/'V7_SELECTED.json').write_text(json.dumps(chosen,indent=2))
    if a.max_gops is not None:
        print('Test mode: no completed final file assembled',flush=True);return
    if not a.source:raise ValueError('--source MP4 required for final ADPCM mux')
    pcm=out/'audio_44100_s16le.pcm'
    if not pcm.exists():
        run([a.system_ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y','-i',a.source,'-map','0:a:0','-ac','2','-ar','44100','-c:a','pcm_s16le','-f','s16le',pcm],timeout=180)
    manifest=out/'V7_COMBINE.ffconcat'
    manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{Path(z['file']).resolve()}'\nduration {z['coded_frames']/CODED_FPS:.9f}\n" for z in result))
    final=out/'MobiPEG_V7_STEREO_3D.moflex'
    run([a.encoder,'-nostdin','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',manifest,
         '-f','s16le','-ar','44100','-ac','2','-i',pcm,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le',
         '-mo_audio','adpcm','-mo_layout','0','-mo_interleave_input_double_rate','1','-f','moflex',final],timeout=300)
    ct,b=video_packets(a.probe,final)
    if ct[0]!=total or b[0]!=sum(x['video_bytes'] for x in result):raise RuntimeError('Corrupt concatenation or wrong bitstream byte count')
    if ct[2]!=total:raise RuntimeError('ADPCM packet/frame count mismatch')
    for mapping in ('0:v:0','0:a:0'):
        run([a.system_ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-xerror','-i',final,'-map',mapping,'-f','null','-'],timeout=300)
    summary['final']={'file':str(final),'bytes':final.stat().st_size,'coded_frames':ct[0],'video_packet_bytes':b[0],
                      'pcm_audio_packet_bytes':b[2],'sha256':hashlib.sha256(final.read_bytes()).hexdigest()}
    (out/'V7_RESULTS.json').write_text(json.dumps(summary,indent=2))
    print('OUTPUT',final,final.stat().st_size,'bytes; complete video/audio decoding verified',flush=True)

if __name__=='__main__':main()
