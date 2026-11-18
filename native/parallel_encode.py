"""CPU-parallel V15 encoding via independently seeked 30-second ranges."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from queue import Empty, Queue
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from threading import Event, Lock

from scene_complexity import analyze_complexity

from moflex_join import BLOCK, FAT32_LIMIT, inspect, join


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(8*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_checkpoint(path, data):
    pending=path.with_suffix('.tmp')
    with pending.open('w', encoding='utf-8') as stream:
        json.dump(data,stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending,path)


@contextmanager
def parallel_workspace(args, inp, out, encoder, media, notify):
    if not getattr(args,'resume',False):
        with tempfile.TemporaryDirectory(prefix='mobipeg-v15-parallel-',dir=out.parent) as scratch:
            yield Path(scratch)
        return
    notify('Checking source and encoder for saved ranges…')
    fields=('mode','preset','filter','motion_refinement','resolution','fps','q','audio_track','audio_codec','workers')
    if args.max_size_mb is not None:
        fields+=('max_size_mb',)
    if getattr(args,'audio_offset_ms',0):
        fields+=('audio_offset_ms',)
    if getattr(args,'normalize_audio',False):
        fields+=('normalize_audio',)
    if media.get('hdr_transfer') and getattr(args,'hdr_mode','auto')!='auto':
        fields+=('hdr_mode',)
    config={'version':1,'source':inp.name,'bytes':inp.stat().st_size,'source_sha256':file_hash(inp),
            'encoder_sha256':file_hash(encoder),'media':media,
            'settings':{key:getattr(args,key) for key in fields}}
    if args.max_size_mb is not None:config['budget_analysis']='uniform' if os.environ.get('MOBIPEG_UNIFORM_BUDGET') or getattr(args,'budget_mode','scene')=='uniform' else 'scene-v1'
    if args.mode!='2d':
        config['stereo_layout']=1
    root=out.parent/'.mobipeg-checkpoints'
    root.mkdir(exist_ok=True)
    key=hashlib.sha256(json.dumps([out.name,config],sort_keys=True).encode()).hexdigest()
    work=root/key
    work.mkdir(exist_ok=True)
    with (work/'job.lock').open('a+b') as lock:
        try:
            if os.name=='nt':
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('This movie is already being converted by another Studio process.') from error
        write_checkpoint(work/'job.json',config)
        notify(f'Saved ranges are stored in {work}')
        yield work
        # A normal return follows verification and publication. Failed jobs
        # keep their verified ranges for the next identical invocation.
        for pattern in ('part-*.moflex','part-*.json','part-*.tmp','video-*.moflex'):
            for artifact in work.glob(pattern):
                try:artifact.unlink()
                except OSError as error:notify(f'Could not remove temporary range: {error}')
        (work/'job.json').unlink(missing_ok=True)


def restore_range(record, final, timeline, expected, last):
    try:
        saved=json.loads(record.read_text(encoding='utf-8'))
        frames=saved['frames']
        if (saved['timeline']==list(timeline) and isinstance(frames,int) and
                0<frames<=expected+2 and (last or frames==expected) and
                final.stat().st_size==saved['bytes'] and file_hash(final)==saved['sha256']):
            inspect(final,frames)
            return frames
    except (OSError,ValueError,KeyError,TypeError):
        pass
    return None


def plan_ranges(seconds, fps, target=30, eyes=1, workers=1):
    """Schedule aligned coded-frame ranges; no source chapters are required."""
    rate=Fraction(fps)
    if seconds<=0 or rate<=0:raise ValueError('Invalid duration or frame rate')
    quantum=256*rate.numerator//math.gcd(48000*rate.denominator,256*rate.numerator)
    target_frames=max(quantum,int(Fraction(target)*rate/quantum)*quantum)
    if workers>1:
        # Balance whole-movie coded frames across independent CPU processes.
        lanes=min(int(workers),max(1,int(seconds//4)))
        total=int(Fraction(str(seconds))*rate/eyes)*eyes
        quantum=math.lcm(quantum,eyes)
        units=total//quantum
        count=min(max(lanes,math.ceil(seconds/(29*lanes))*lanes),max(1,units))
        lengths=[(units//count+(1 if i<units%count else 0))*quantum
                 for i in range(count)]
        lengths[-1]+=total-units*quantum
        ranges=[];frames=0
        for amount in lengths:
            start=Fraction(frames,1)/rate
            ranges.append((float(start),float(Fraction(amount,1)/rate),amount))
            frames+=amount
        return ranges
    ranges=[];frames=0
    while float(Fraction(frames,1)/rate)+float(Fraction(1,2)/rate)<seconds:
        start=Fraction(frames,1)/rate
        length=min(Fraction(target_frames,1)/rate,Fraction(str(seconds))-start)
        coded_frames=round(length*rate/eyes)*eyes
        if coded_frames<=0:break
        ranges.append((float(start),float(length),coded_frames))
        frames+=coded_frames
        if len(ranges)>math.ceil(seconds/5)+4:raise ValueError('Movie schedule did not advance')
    if not ranges:raise ValueError('Video has no encodable frames')
    return ranges


def run_with_progress(argv, env, frames, notify):
    command=[str(x) for x in argv]
    errors=[]
    with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                          env=env,text=True,bufsize=1) as process:
        for line in process.stderr:
            line=line.rstrip()
            if len(errors)>35:errors.pop(0)
            errors.append(line)
            if line.startswith('frame='):
                try:notify(min(.99,int(line.partition('=')[2])/frames))
                except ValueError:pass
        exit_code=process.wait()
    if exit_code:raise RuntimeError(f'FFmpeg failed (exit {exit_code}): '+ '\n'.join(errors[-20:]))

def measure_audio_peak(encoder, source, track):
    result=subprocess.run([str(encoder),'-hide_banner','-nostdin','-v','info','-nostats',
                           '-i',str(source),'-map',f'0:a:{track}','-af',
                           'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                           'astats=metadata=0:reset=0:measure_perchannel=none:measure_overall=Peak_level',
                           '-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    peak=re.search(rb'Peak level dB:\s*(-inf|-?\d+(?:\.\d+)?)',result.stderr)
    if result.returncode or peak is None:
        raise RuntimeError('Could not measure the selected audio track')
    db=float(peak.group(1))
    return 0 if db==-math.inf else min(24,math.floor((-1-db)*10)/10)


def audio_window(start, seconds, track, offset_ms, peak_gain=0):
    samples=round(seconds*48000)
    source_sample=round((start or 0)*48000)-offset_ms*48
    seek=max(0,source_sample)/48000 if offset_ms else start
    delay=max(0,-source_sample)
    seek_args=[] if seek is None else ['-ss',f'{seek:.8f}']
    if delay>=samples:
        return seek_args,['-filter_complex',f'anullsrc=r=48000:cl=stereo,atrim=end_sample={samples}[audio]',
                          '-map','[audio]']
    pad=f'adelay={delay}S:all=1,' if delay else ''
    volume=f'volume={peak_gain}dB,' if peak_gain else ''
    audio_filter=f'aresample=48000:async=0:first_pts=0,{volume}{pad}apad,atrim=end_sample={samples},asetpts=N/SR/TB'
    return seek_args,['-map',f'1:a:{track}','-af',audio_filter]


def allocate_movie_budget(ranges, target_bytes, complexity=None, audio_rate=0):
    blocks=min(target_bytes,FAT32_LIMIT)//BLOCK
    floors=[2+math.ceil(length*audio_rate/BLOCK) for start,length,frames in ranges]
    remaining=blocks-sum(floors)
    if not ranges or remaining<0:
        raise ValueError('Maximum size is too small for the movie ranges and seek indexes.')
    weights=[frames*(complexity[i] if complexity is not None else 1) for i,(_,_,frames) in enumerate(ranges)]
    total=sum(weights)
    cumulative=previous=0
    budgets=[]
    for i,(_,_,frames) in enumerate(ranges):
        cumulative+=weights[i]
        allocated=remaining if i==len(ranges)-1 else math.floor(remaining*cumulative/total)
        budgets.append((floors[i]+allocated-previous)*BLOCK)
        previous=allocated
    return budgets


def encode_parallel(*, args, inp, out, encoder, probe, media, filters, layout_options,
                    base_q, coded_fps_label, callback, progress=lambda slot, fraction:None,
                    invoke, verified_frame_count, probe_coded_rate, q_flags,
                    presets, scratch, target_bytes=None, peak_gain=0):
    """Write to a temporary assembled file; caller performs full verification."""
    workers=args.workers
    rate=Fraction(coded_fps_label)
    ranges=plan_ranges(media['duration'],rate,eyes=1 if args.mode=='2d' else 2,workers=workers)
    workers=min(workers,len(ranges))
    analysis=None
    if target_bytes is not None and len(ranges)>1 and not os.environ.get('MOBIPEG_UNIFORM_BUDGET') and getattr(args,'budget_mode','scene')!='uniform':
        cache=Path(scratch)/'complexity.json'
        if getattr(args,'resume',False):
            try:
                candidate=json.loads(cache.read_text())
                rows=candidate['clips']
                if candidate['version']==1 and len(rows)==len(ranges) and all(
                    abs(row['start']-start)<1e-6 and abs(row['seconds']-seconds)<1e-6 and
                    all(isinstance(row[k],(int,float)) and math.isfinite(row[k]) and 0<=row[k]<=1 for k in ('texture','motion')) and
                    abs(row['score']-(.025+row['texture']+2*row['motion']))<1e-9
                    for row,(start,seconds,frames) in zip(rows,ranges)):analysis=candidate
            except (OSError,ValueError,TypeError,KeyError):pass
        if analysis is None:
            analysis=analyze_complexity(encoder,inp,ranges,callback)
            if getattr(args,'resume',False):write_checkpoint(cache,analysis)
    audio_rate=(15000 if args.audio_codec=='fastaudio' else 49500) if media.get('audio') else 0
    budgets=allocate_movie_budget(ranges,target_bytes,[r['score'] for r in analysis['clips']] if analysis else None,audio_rate if analysis else 0) if target_bytes is not None else None
    reservations={};budget_lock=Lock()
    me=presets[args.preset]['me'];search=presets[args.preset]['search']
    improve=(args.motion_refinement=='on' or args.motion_refinement=='auto' and args.preset in ('best','quality'))
    env={k:v for k,v in os.environ.items() if not k.startswith('MOBI_')}
    env.update({'MOBI_SUBME':str(search),'MOBI_SKIP':'0'})
    if improve:env.update({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'})
    results=[None]*len(ranges)
    pending=Queue()
    for item in enumerate(ranges):
        pending.put(item)
    stopped=Event()
    output_dir=Path(scratch)
    callback(f'Parallel movie encoding: {workers} independent codec processes; {len(ranges)} timeline parts (source chapters not required)')

    def lane(slot):
        while not stopped.is_set():
            try:index,(start,length,expected)=pending.get_nowait()
            except Empty:return
            progress(slot,0)
            video=output_dir/f'video-{index:05d}.moflex'
            final=output_dir/f'part-{index:05d}.moflex'
            record=output_dir/f'part-{index:05d}.json'
            if analysis is not None:
                with budget_lock:
                    spent=sum(path.stat().st_size for item in results if item for path in [item[0]])+sum(reservations.values())
                    available=[i for i in range(len(ranges)) if results[i] is None and i not in reservations]
                    caps=allocate_movie_budget([ranges[i] for i in available],min(target_bytes,FAT32_LIMIT)-spent,[analysis['clips'][i]['score'] for i in available],audio_rate)
                    for i,cap in zip(available,caps):budgets[i]=cap
                    reservations[index]=budgets[index]
            if getattr(args,'resume',False):
                restored=restore_range(record,final,(start,length,expected),expected,index==len(ranges)-1)
                if restored and (budgets is None or final.stat().st_size<=budgets[index]):
                    callback(f'Reusing verified range {index+1}/{len(ranges)}.')
                    with budget_lock:
                        results[index]=(final,restored);reservations.pop(index,None)
                    progress(slot,1)
                    continue
            callback(f'Worker {slot+1}/{workers}: part {index+1}/{len(ranges)} at {start:.3f}s')
            def encode_range(q):
                command=[encoder,'-hide_banner','-nostdin','-v','error','-y','-ss',f'{start:.8f}',
                         '-i',inp,*filters,'-an','-c:v','mobiclip','-mobiclip','1',
                         *q_flags(q),'-preset','medium','-me_method',me,
                         '-g',str(math.ceil(float(Fraction(args.fps))*2)),
                         *(['-r',coded_fps_label] if args.mode!='2d' else []),
                         '-frames:v',str(expected),*layout_options,
                         '-progress','pipe:2','-stats_period','0.25','-f','moflex',video]
                run_with_progress(command,env,expected,lambda f:progress(slot,.92*f))
                frames=verified_frame_count(probe,video)
                if frames!=expected and index!=len(ranges)-1:
                    raise RuntimeError('Input ended before an independently scheduled range; retry with 1 worker')
                if frames>expected+2 or args.mode!='2d' and frames%2:
                    raise RuntimeError('Unexpected coded frame count or lost stereo eye pair')
                seconds=frames/float(rate)
                if media['audio']:
                    remux_input=[];remux_output=[]
                    if args.mode!='2d':
                        exposed=probe_coded_rate(probe,video)
                        original=float(Fraction(args.fps))
                        if math.isclose(exposed,original,rel_tol=.001):remux_input=['-itsscale','0.5']
                        elif not math.isclose(exposed,float(rate),rel_tol=.001):
                            raise RuntimeError(f'Unexpected stereoscopic stream rate {exposed}')
                        remux_output=['-r',coded_fps_label]
                    seek,audio_map=audio_window(start,seconds,args.audio_track,getattr(args,'audio_offset_ms',0),peak_gain)
                    audio_command=[encoder,'-hide_banner','-nostdin','-v','error','-y',*remux_input,'-i',video,
                            *seek,'-i',inp,'-map','0:v:0',*audio_map,'-c:v','copy',
                            '-c:a','pcm_s16le','-ar','48000','-ac','2',
                            '-mo_audio',args.audio_codec,*remux_output,*layout_options,
                            '-t',f'{seconds:.8f}','-f','moflex',final]
                    invoke(audio_command)
                    video.unlink()
                else:video.replace(final)
                return frames

            if budgets is None:
                frames=encode_range(base_q)
            else:
                budget=budgets[index]
                saved=output_dir/f'video-best-{index:05d}.moflex'
                q=low=base_q
                high=59
                selected=None
                while low<=high and not stopped.is_set():
                    frames=encode_range(q)
                    size=final.stat().st_size
                    callback(f'Range {index+1}: Q={q}, {size:,} bytes, budget {budget:,} bytes')
                    if size<=budget:
                        final.replace(saved)
                        selected=frames
                        high=q-1
                    else:
                        low=q+1
                    q=(low+high)//2
                if selected is None:
                    if stopped.is_set():return
                    raise RuntimeError(f'Range {index+1} cannot meet its size budget at Q=59. '
                                       'Raise the maximum size or choose a smaller resolution or frame rate.')
                saved.replace(final)
                frames=selected
            if getattr(args,'resume',False):
                inspect(final,frames)
                invoke([encoder,'-hide_banner','-nostdin','-v','error','-xerror','-i',final,
                        '-map','0:v:0','-map','0:a:0?','-f','null','-'])
                write_checkpoint(record,{'timeline':[start,length,expected],'frames':frames,
                                         'bytes':final.stat().st_size,'sha256':file_hash(final)})
            with budget_lock:
                results[index]=(final,frames);reservations.pop(index,None)
            progress(slot,1)

    def encode_lane(slot):
        try:lane(slot)
        except Exception:
            stopped.set()
            raise

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(encode_lane,i) for i in range(workers)]
        # Wait for *every* worker to finish before temporary-file cleanup,
        # including when an earlier worker throws an exception.
        errors=[]
        for future in futures:
            try:future.result()
            except Exception as exc:errors.append(exc)
        if errors:raise errors[0]
    if any(item is None for item in results):raise RuntimeError('Missing encoded movie range')
    assembled=output_dir/'assembled.moflex'
    frames=join(results,rate,assembled,callback=lambda f:progress(-1,f),max_bytes=target_bytes)
    callback(f'Joined one indexed MOFLEX: {frames:,} coded frames')
    return assembled,frames,len(results)
