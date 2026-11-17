"""CPU-parallel V15 encoding via independently seeked 30-second ranges."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
import math
import os
import shutil
import subprocess

from moflex_join import join


def plan_ranges(seconds, fps, target=30, eyes=1):
    """Schedule aligned coded-frame ranges; no source chapters are required."""
    rate=Fraction(fps)
    if seconds<=0 or rate<=0:raise ValueError('Invalid duration or frame rate')
    quantum=256*rate.numerator//math.gcd(48000*rate.denominator,256*rate.numerator)
    target_frames=max(quantum,int(Fraction(target)*rate/quantum)*quantum)
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


def encode_parallel(*, args, inp, out, encoder, probe, media, filters, layout_options,
                    base_q, coded_fps_label, callback, progress=lambda slot, fraction:None,
                    invoke, verified_frame_count, probe_coded_rate, q_flags,
                    presets, scratch):
    """Write to a temporary assembled file; caller performs full verification."""
    workers=args.workers
    rate=Fraction(coded_fps_label)
    ranges=plan_ranges(media['duration'],rate,eyes=1 if args.mode=='2d' else 2)
    workers=min(workers,len(ranges))
    if args.max_size_mb is not None:
        raise ValueError('Parallel desktop mode currently requires no hard maximum file size')
    me=presets[args.preset]['me'];search=presets[args.preset]['search']
    improve=(args.motion_refinement=='on' or args.motion_refinement=='auto' and args.preset in ('best','quality'))
    env={k:v for k,v in os.environ.items() if not k.startswith('MOBI_')}
    env.update({'MOBI_SUBME':str(search),'MOBI_SKIP':'0'})
    if improve:env.update({'MOBI_V11_MV_REFINE':'1','MOBI_V11_MV_PENALTY':'0'})
    results=[None]*len(ranges)
    lanes=[ranges[math.floor(i*len(ranges)/workers):math.floor((i+1)*len(ranges)/workers)] for i in range(workers)]
    offsets=[math.floor(i*len(ranges)/workers) for i in range(workers)]
    output_dir=Path(scratch)
    callback(f'Parallel movie encoding: {workers} independent codec processes; {len(ranges)} timeline parts (source chapters not required)')

    def lane(slot):
        group=lanes[slot]
        for local,(start,length,expected) in enumerate(group):
            index=offsets[slot]+local
            video=output_dir/f'video-{index:05d}.moflex'
            final=output_dir/f'part-{index:05d}.moflex'
            callback(f'Worker {slot+1}/{workers}: part {index+1}/{len(ranges)} at {start:.3f}s')
            command=[encoder,'-hide_banner','-nostdin','-v','error','-y','-ss',f'{start:.8f}',
                     '-i',inp,*filters,'-an','-c:v','mobiclip','-mobiclip','1',
                     *q_flags(base_q),'-preset','medium','-me_method',me,
                     '-g',str(math.ceil(float(Fraction(args.fps))*2)),
                     *(['-r',coded_fps_label] if args.mode!='2d' else []),
                     '-frames:v',str(expected),*layout_options,
                     '-progress','pipe:2','-stats_period','0.25','-f','moflex',video]
            run_with_progress(command,env,expected,lambda f:progress(slot,(local+.92*f)/len(group)))
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
                invoke([encoder,'-hide_banner','-nostdin','-v','error','-y',*remux_input,'-i',video,
                        '-ss',f'{start:.8f}','-i',inp,'-map','0:v:0',
                        '-map',f'1:a:{args.audio_track}','-c:v','copy',
                        '-c:a','pcm_s16le','-ar','48000','-ac','2','-af','apad',
                        '-mo_audio','adpcm',*remux_output,*layout_options,
                        '-t',f'{seconds:.8f}','-f','moflex',final]);video.unlink()
            else:video.replace(final)
            results[index]=(final,frames)
            progress(slot,(local+1)/len(group))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(lane,i) for i in range(workers)]
        # Wait for *every* worker to finish before temporary-file cleanup,
        # including when an earlier worker throws an exception.
        errors=[]
        for future in futures:
            try:future.result()
            except Exception as exc:errors.append(exc)
        if errors:raise errors[0]
    if any(item is None for item in results):raise RuntimeError('Missing encoded movie range')
    assembled=output_dir/'assembled.moflex'
    frames=join(results,rate,assembled,callback=lambda f:progress(-1,f))
    callback(f'Joined one indexed MOFLEX: {frames:,} coded frames')
    return assembled,frames,len(results)
