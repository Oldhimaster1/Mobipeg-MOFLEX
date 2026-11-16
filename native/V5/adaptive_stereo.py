#!/usr/bin/env python3
"""MobiPEG V5: source-matched per-GOP 2-pass stereo rate-distortion allocation.

Pass 1: encode a family of independent 2-second 48-FPS interleaved-eye MobiClip
chunks at different QYX/QP. Record exact video packet bytes, decoded luma/chroma
MSE and sampled SSIM against the same normalized raw eyes.
Pass 2: dynamic-programming bit-budget optimization; remux chosen GOPs with
single MOFLEX stereo descriptor at 24 FPS per eye + 44.1kHz stereo ADPCM.

Requires a patched MobiPEG FFmpeg with 'moflex' muxer and the optional
'-mo_interleave_input_double_rate' flag. Does not use Nintendo executables.
"""
import argparse,concurrent.futures,copy,csv,hashlib,json,math,os,subprocess,time
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from skimage.metrics import structural_similarity as ssim

W=400;H=224;PIX=W*H; FRAMEBYTES=PIX*3//2; FPS=48; GOP=96
SETTINGS=[('detail46',3,16),('detail47',3,17),('reference48',4,12),('save49',4,13),('save50',4,14)]

def run(cmd,env=None,timeout=300):
    r=subprocess.run([str(z) for z in cmd],env=env,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError(f'command failed {r.returncode}: {" ".join(map(str,cmd))}\n{r.stderr.decode(errors="replace")[-2400:]}')
    return r

def packets(probe,path):
    r=run([probe,'-v','error','-show_packets','-show_entries','packet=stream_index,size','-of','csv=p=0',path],timeout=150)
    ct=Counter();by=Counter()
    for line in r.stdout.decode(errors='replace').splitlines():
        z=line.strip().strip(',').split(',')
        if len(z)>=2 and z[0].isdigit() and z[1].isdigit():
            ct[int(z[0])]+=1;by[int(z[0])]+=int(z[1])
    return ct,by

def encode_trial(job):
    (idx,n,cfg,infile,folder,encoder,probe)=job
    name,qyx,qp=cfg
    p=folder/f'part_{idx:03d}_{name}.moflex'
    env=os.environ.copy();env.update(MOBI_SUBME='9',MOBI_SKIP='0',MOBI_QYX_RDO='0',MOBI_INTRA_RD_CAP='0')
    valid=False
    if p.exists() and p.stat().st_size>=4096:
        try:
            prior,_=packets(probe,p)
            valid=(prior[0]==n)
        except Exception:
            valid=False
    if not valid:
        if p.exists():p.unlink()
        cmd=[encoder,'-hide_banner','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','yuv420p',
             '-video_size','400x224','-framerate','48','-i',infile,'-an','-c:v','mobiclip','-mobiclip','1',
             '-qp',str(qp),'-mobi_qyx',str(qyx),'-preset','medium','-me_method','hex','-g','48',
             '-mo_layout','0','-f','moflex',p]
        t0=time.monotonic();run(cmd,env=env,timeout=300);t=time.monotonic()-t0
    else:t=0
    c,b=packets(probe,p)
    if c[0]!=n:raise RuntimeError(f'{p.name}: frames {c[0]} != expected {n}')
    decoded=run([encoder,'-hide_banner','-nostdin','-loglevel','error','-xerror','-i',p,'-map','0:v:0',
                 '-pix_fmt','yuv420p','-f','rawvideo','pipe:1']).stdout
    if len(decoded)!=n*FRAMEBYTES:raise RuntimeError(f'decoded {len(decoded)} != {n*FRAMEBYTES} for {p.name}')
    orig=np.fromfile(infile,dtype=np.uint8).reshape(n,FRAMEBYTES)
    rec=np.frombuffer(decoded,dtype=np.uint8).reshape(n,FRAMEBYTES)
    def mse_range(a,b,begin,end):
        # float64 avoids overflow / accumulator saturation
        x=a[:,begin:end].astype(np.int16)-b[:,begin:end].astype(np.int16)
        return float(np.mean(x.astype(np.float32)**2))
    ym=mse_range(orig,rec,0,PIX)
    um=mse_range(orig,rec,PIX,PIX+PIX//4)
    vm=mse_range(orig,rec,PIX+PIX//4,FRAMEBYTES)
    # SSIM every 12th eye frame, both eyes sampled evenly; replicateable.
    ids=list(range(0,n,12));vals=[]
    for i in ids:
        a=orig[i,:PIX].reshape(H,W);z=rec[i,:PIX].reshape(H,W)
        vals.append(ssim(a,z,data_range=255))
    # Include a modest SSIM penalty to preserve structure/detail while optimizing MSE.
    structure=1-float(np.mean(vals))
    distortion=(ym*0.65 + (um+vm)*0.075 + structure*500*0.20)*n
    row={'index':idx,'coded_frames':n,'option':name,'qyx':qyx,'qp':qp,'file_bytes':p.stat().st_size,
         'video_bytes':b[0],'seconds':round(t,3),'mse_y':round(ym,6),'mse_u':round(um,6),
         'mse_v':round(vm,6),'psnr_y':round(10*math.log10(65025/max(ym,1e-9)),4),
         'ssim_y':round(1-structure,7),'cost':round(distortion,4),'file':str(p)}
    return row

def dp_allocate(groups,target,guard_psnr=1.45,guard_ssim=0.015,step=512):
    """Bounded multiple-choice knapsack; round extra bytes up to preserve budget."""
    groups=[[x for x in grp] for grp in groups]
    raw_min=sum(min(x['video_bytes'] for x in grp) for grp in groups)
    if raw_min>target:raise ValueError(f'No feasible allocation: minimum payload {raw_min} > target {target}')
    # Avoid hard per-GOP artifacts if feasible; compare to uniform baseline.
    guards=[]
    for gr in groups:
        base=next(x for x in gr if x['option']=='reference48')
        allowed=[x for x in gr if x['psnr_y']>=base['psnr_y']-guard_psnr and x['ssim_y']>=base['ssim_y']-guard_ssim]
        guards.append(allowed or gr)
    guarded_min=sum(min(x['video_bytes'] for x in grp) for grp in guards)
    if guarded_min<=target:groups=guards
    else:print(f'Guard infeasible ({guarded_min:,} > {target:,}); keeping all modes',flush=True)
    minimum=[min(x['video_bytes'] for x in gr) for gr in groups]
    base=sum(minimum);extras=int((target-base)//step)
    INF=1e30;dp=np.full(extras+1,INF,dtype=np.float64);dp[0]=0
    traces=[]
    for i,gr in enumerate(groups):
        nd=np.full(extras+1,INF,dtype=np.float64)
        prev=np.full(extras+1,-1,dtype=np.int32)
        opts=np.full(extras+1,-1,dtype=np.int16)
        for j,item in enumerate(gr):
            cost=math.ceil((item['video_bytes']-minimum[i])/step)
            if cost>extras:continue
            dist=item['cost']
            sl=dp[:extras+1-cost]+dist
            to=nd[cost:]
            improve=sl<to
            to[improve]=sl[improve]
            prev[cost:][improve]=np.flatnonzero(improve).astype(np.int32)
            opts[cost:][improve]=j
        if not np.isfinite(nd).any():raise RuntimeError(f'no feasible DP state in GOP {i}')
        dp=nd;traces.append((prev,opts))
    k=int(np.argmin(dp));chosen=[]
    for i in reversed(range(len(groups))):
        prev,opts=traces[i];j=int(opts[k]);
        if j<0:raise RuntimeError('DP backtrack failed')
        chosen.append(groups[i][j]);k=int(prev[k])
    chosen.reverse()
    assert sum(x['video_bytes'] for x in chosen)<=target
    return chosen

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True);ap.add_argument('--out-dir',required=True)
    ap.add_argument('--encoder',required=True);ap.add_argument('--probe',required=True)
    ap.add_argument('--source',help='original MP4 for ADPCM audio')
    ap.add_argument('--official',help='official MOFLEX to derive matching payload budget')
    ap.add_argument('--target-video-bytes',type=int)
    ap.add_argument('--target-video-kbps',type=float,help='target video bitrate instead of official reference')
    ap.add_argument('--system-ffmpeg',default='ffmpeg',help='FFmpeg for input MP4 audio decoding')
    ap.add_argument('--perceptual-weight',type=float,default=None,help='0=prioritize PSNR; 1=prioritize SSIM. Default uses blended quality model.')
    ap.add_argument('--workers',type=int,default=4);ap.add_argument('--max-gops',type=int)
    ap.add_argument('--target-total-bytes',type=int)
    args=ap.parse_args()
    root=Path(args.out_dir); root.mkdir(parents=True,exist_ok=True)
    p=Path(args.raw);assert p.stat().st_size%FRAMEBYTES==0
    total=p.stat().st_size//FRAMEBYTES
    if total%2:raise ValueError('coded eye count must be even')
    gops=[]
    with p.open('rb') as f:
        for i,start in enumerate(range(0,total,GOP)):
            if args.max_gops is not None and i>=args.max_gops:break
            n=min(GOP,total-start);file=root/f'input_{i:03d}.raw'
            if not file.exists() or file.stat().st_size!=n*FRAMEBYTES:
                file.write_bytes(f.read(n*FRAMEBYTES))
            else:f.seek(n*FRAMEBYTES,1)
            gops.append((i,n,file))
    if args.target_video_bytes:budget=args.target_video_bytes
    elif args.target_video_kbps:budget=int(args.target_video_kbps*1000/8*(total/FPS))
    elif args.official:
        _,b=packets(args.probe,Path(args.official));budget=b[0]
    else:raise ValueError('provide --official or --target-video-bytes')
    if args.max_gops is not None:
        budget=int(budget * (sum(n for _,n,_ in gops)/total))
    print('Normalized interleaved coded eye frames',total,'GOP count',len(gops),'video budget',budget,'bytes',flush=True)
    trialmap={};metricfile=root/'all_trials.json'
    if metricfile.exists():
        for d in json.loads(metricfile.read_text()):trialmap[(d['index'],d['option'])]=d
    todo=[(i,n,cfg,f,root,args.encoder,args.probe) for (i,n,f) in gops for cfg in SETTINGS if (i,cfg[0]) not in trialmap]
    print('Existing results',len(trialmap),'new full encode-decode trials',len(todo),flush=True)
    t0=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as exe:
        futs={exe.submit(encode_trial,t):t for t in todo}
        for fut in concurrent.futures.as_completed(futs):
            info=futs[fut]
            try:
                r=fut.result();trialmap[(r['index'],r['option'])]=r
                print(f"  GOP {r['index']:02d} {r['option']:<12} size={r['video_bytes']:>7,} PSNR={r['psnr_y']:.2f} SSIM={r['ssim_y']:.4f}",flush=True)
            except Exception as e:print('FAILED',info[0],info[2][0],str(e)[-600:],flush=True);raise
            metricfile.write_text(json.dumps(sorted(trialmap.values(),key=lambda r:(r['index'],r['qyx'],r['qp'])),indent=2))
    print('trial time',round(time.monotonic()-t0,2),'s',flush=True)
    groups=[[trialmap[(i,o[0])] for o in SETTINGS] for i,n,f in gops]
    baseline=[next(x for x in gr if x['option']=='reference48') for gr in groups]
    if args.perceptual_weight is not None:
        weight=args.perceptual_weight
        if not 0<=weight<=1:raise ValueError('--perceptual-weight must be from 0 to 1')
        search_groups=[[{**x,'cost':x['coded_frames']*((1-weight)*(x['mse_y']/50)+weight*(1-x['ssim_y'])*10)} for x in group] for group in groups]
    else:search_groups=groups
    chosen=dp_allocate(search_groups,budget)
    def agg(rows):
        framecount=sum(x['coded_frames'] for x in rows)
        y=sum(x['coded_frames']*x['mse_y'] for x in rows)/framecount
        u=sum(x['coded_frames']*x['mse_u'] for x in rows)/framecount
        v=sum(x['coded_frames']*x['mse_v'] for x in rows)/framecount
        ss=sum(x['coded_frames']*x['ssim_y'] for x in rows)/framecount
        return {'video_bytes':sum(x['video_bytes'] for x in rows),'coded_frames':framecount,'psnr_y':10*math.log10(65025/max(y,1e-9)),
                'psnr_u':10*math.log10(65025/max(u,1e-9)),'psnr_v':10*math.log10(65025/max(v,1e-9)),
                'ssim_sampled_y':ss,'video_kbps':sum(x['video_bytes'] for x in rows)*8/(framecount/FPS)/1000}
    report={'method':'measured GOP-level two-pass rate-distortion optimization (coded frames, FFmpeg decoder)',
            'perceptual_weight':args.perceptual_weight,
            'reference_video_target_bytes':budget,'baseline_uniform_qyx4qp12':agg(baseline),
            'selected':agg(chosen),'selected_counts':dict(Counter(x['option'] for x in chosen)),
            'per_gop':[{**x,'baseline_option':'reference48','baseline_video_bytes':b['video_bytes'],
                        'baseline_psnr_y':b['psnr_y'],'baseline_ssim_y':b['ssim_y']} for x,b in zip(chosen,baseline)]}
    (root/'optimization.json').write_text(json.dumps(report,indent=2))
    print('BASELINE',json.dumps(report['baseline_uniform_qyx4qp12']),flush=True)
    print('SELECTED',json.dumps(report['selected']),flush=True)
    print('COUNTS',report['selected_counts'],flush=True)
    if args.max_gops is not None:
        print('Smoke test requested: no full final MOFLEX assembled',flush=True)
        return
    if not args.source:raise ValueError('full audio mux requires --source')
    # Encode source audio as PCM with system FFmpeg. The custom MOFLEX muxer
    # converts it to ADPCM internally, exactly once, preserving input timestamps.
    pcm=root/'audio_44100_stereo.pcm'
    if not pcm.exists():
        run([args.system_ffmpeg,'-nostdin','-hide_banner','-v','error','-y',
             '-i',args.source,'-map','0:a:0','-ar','44100','-ac','2','-c:a','pcm_s16le','-f','s16le',pcm],timeout=100)
    def mux(rows,outname):
        manifest=root/('manifest_'+outname+'.ffconcat')
        manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{Path(r['file']).name}'\nduration {r['coded_frames']/FPS:.9f}\n" for r in rows))
        out=root/(outname+'.moflex')
        run([args.encoder,'-hide_banner','-nostdin','-loglevel','error','-y',
             '-f','concat','-safe','0','-i',manifest,'-f','s16le','-ar','44100','-ac','2','-i',pcm,
             '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le','-mo_audio','adpcm',
             '-mo_layout','0','-mo_interleave_input_double_rate','1','-f','moflex',out],timeout=170)
        counts,by=packets(args.probe,out)
        if counts[0]!=total:raise ValueError(f'combined video packets {counts[0]} != {total}')
        if by[0]!=sum(x['video_bytes'] for x in rows):raise ValueError('payload bytes mismatch')
        return out,counts,by
    for typ,rows in [('uniform_QYX4',baseline),('adaptive_V5',chosen)]:
        out,c,b=mux(rows,typ);print(typ,'output',out.stat().st_size,'bytes','video payload',b[0],'video frames',c[0],flush=True)
        report[typ+'_final']={'file':str(out),'bytes':out.stat().st_size,'video_bytes':b[0],'packets':dict(c),
            'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}
    (root/'optimization.json').write_text(json.dumps(report,indent=2))
    print('FINAL PASS COMPLETE',flush=True)

if __name__=='__main__':main()
