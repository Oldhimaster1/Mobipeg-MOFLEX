#!/usr/bin/env python3
"""MobiPEG Studio V15 — easy, strictly verified MOFLEX encoding.

Works with the bundled *custom* Mobiclip-enabled FFmpeg, never stock FFmpeg.
The default quality profile is conservative.  Audio and complete video are
decoded and verified before the destination is published.  A user-supplied
maximum file size is a hard cap, not a bitrate estimate.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Callable

# The portable launcher uses Python -I. Add only this trusted application
# directory, never the caller's working directory or PYTHONPATH.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parallel_encode import audio_window, encode_parallel, measure_audio_peak, parallel_workspace
from moflex_join import FAT32_LIMIT, FAT32_MESSAGE


EXE_SUFFIX = '.exe' if os.name == 'nt' else ''
MODES = ('2d','full-sbs','half-sbs')
PRESETS = {
    'best': {'q':27,'search':9,'me':'umh'},
    'quality': {'q':30,'search':9,'me':'hex'},
    'balanced': {'q':32,'search':7,'me':'hex'},
    'small': {'q':36,'search':7,'me':'hex'},
}
FILTERS = {
    'detail': None,
    'clean': 'hqdn3d=0.7:1.1:0:0',
    'smooth': 'hqdn3d=1.4:1.8:0:0',
    'bilateral': 'bilateral=sigmaS=1.2:sigmaR=0.035:planes=1',
}
MOTION_MODES=('auto','on','off')
RATES = ('24','25','30','24000/1001','30000/1001')
RESOLUTIONS = ('400x240','400x224','320x240')


def q_flags(q: int) -> list[str]:
    """Map a real Mobiclip quantizer (12..59) into QYX and x264 remainder."""
    if not 12<=q<=59:raise ValueError('Mobiclip quantizer must be 12..59')
    return ['-qp',str(12+(q-12)%6),'-mobi_qyx',str((q-12)//6)]


def rate_value(rate: str) -> float:
    if rate not in RATES:raise ValueError(f'Unsupported frame rate: {rate}')
    if '/' in rate:
        top,bottom=map(int,rate.split('/'))
        return top/bottom
    return float(rate)


def estimate_storage(duration, resolution, fps, mode, q, audio, workers=1):
    """Rough storage budget, never a promise of the final compressed size."""
    width,height=map(int,resolution.split('x'))
    eyes=1 if mode=='2d' else 2
    video_bits=width*height*rate_value(fps)*eyes*.20*2**((30-q)/8)
    audio_bits=384000 if audio else 0
    center=(video_bits+audio_bits)*duration/8
    low=max(4096,math.floor(center*.55));high=max(low,math.ceil(center*1.8))
    if workers>1:
        max_range=high/max(1,math.ceil(duration/30))
        temporary=math.ceil(2.15*high+workers*max_range)
    else:temporary=math.ceil(high*2.15)
    return {'minimum':low,'maximum':high,'temporary':temporary}


def coded_rate_label(fps: str, mode: str) -> str:
    """Mobiclip receives twice the displayed frame rate for stereo eyes."""
    rate_value(fps)
    if mode not in MODES:raise ValueError('Unknown stereoscopic mode')
    if mode=='2d':return fps
    if '/' in fps:
        top,bottom=map(int,fps.split('/'))
        return f'{top*2}/{bottom}'
    return str(int(fps)*2)

def scale_filter(width: int, height: int, sar: int=1,
                 clean: str | None=None) -> str:
    if min(width,height)<=0 or width%2 or height%2:
        raise ValueError('YUV420 dimensions must be positive even numbers')
    stages=(['setsar=sar*2'] if sar==2 else [])+[
            f'scale={width}:{height}:force_original_aspect_ratio=decrease:'
            f'force_divisible_by=2:reset_sar=1:in_range=auto:out_range=tv:flags=lanczos',
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2', 'setsar=1']
    if clean:stages.append(clean)
    stages.append('format=yuv420p')
    return ','.join(stages)


def hdr_filter(transfer, mode='auto'):
    if transfer not in ('smpte2084','arib-std-b67') or mode=='off':
        return ''
    operator='mobius' if mode=='auto' else mode
    if operator not in ('mobius','hable','reinhard'):
        raise ValueError('Invalid HDR tone mapping mode')
    return ('scale=out_transfer=linear,format=gbrpf32le,tonemap='+operator+
            ':desat=2,scale=out_transfer=bt709:out_primaries=bt709:out_color_matrix=bt709:out_range=tv,format=yuv420p,')


def video_filters(mode: str, width: int, height: int, fps: str,
                  quality_filter: str, hdr='') -> tuple[list[str], str]:
    if mode not in MODES:raise ValueError('Unknown stereoscopic mode')
    if quality_filter not in FILTERS:raise ValueError('Unknown cleanup filter')
    clean=FILTERS[quality_filter]
    if mode=='2d':
        return ['-vf',hdr+f'fps={fps},'+scale_filter(width,height,clean=clean)],'6'
    # Apply spatial-only cleanup separately to each eye; never average
    # left and right or let the filter see the inter-eye seam.
    sar=2 if mode=='half-sbs' else 1
    eye=scale_filter(width,height,sar=sar,clean=clean)
    # A layout-1 MOFLEX is not packed SBS. For each displayed stereo frame,
    # emit one full-width LEFT eye followed by one full-width RIGHT eye.
    # Give the two branches distinct PTS in a 2x display-rate time base;
    # FFmpeg's temporal interleave merges them in L,R,L,R order. No frame
    # can leak between eyes because each branch is spatially filtered alone.
    eye_tb=f'1/(2*({fps}))'
    spec=(f'[0:v:0]{hdr}fps={fps},split=2[left][right];'
          f'[left]crop=iw/2:ih:0:0,{eye},'
          f'settb=expr={eye_tb},setpts=2*N[l];'
          f'[right]crop=iw/2:ih:iw/2:0,{eye},'
          f'settb=expr={eye_tb},setpts=2*N+1[r];'
          '[l][r]interleave=nb_inputs=2,format=yuv420p[vid]')
    return ['-filter_complex',spec,'-map','[vid]'],'1'


def pick_encoder(explicit: str | None=None) -> Path:
    choices=([Path(explicit)] if explicit else [ROOT/('local/bin/ffmpeg'+EXE_SUFFIX),
             ROOT/('MobiPEG_V13_work/local/bin/ffmpeg'+EXE_SUFFIX)])
    for path in choices:
        if path.is_file() and os.access(path,os.X_OK):return path.resolve()
    raise FileNotFoundError('Custom MobiPEG ffmpeg not found. Build it with BUILD_FOR_LINUX.sh / BUILD_FOR_MAC.command or pass --ffmpeg PATH.')


def invoke(args, env=None, timeout=None):
    result=subprocess.run([str(a) for a in args],capture_output=True,
                          env=env,timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Encoder failed (exit {result.returncode}):\n'+
                           result.stderr.decode(errors='replace')[-2500:])
    return result.stdout


def probe_media(probe: Path, inp: Path) -> dict:
    raw=invoke([probe,'-v','error','-show_entries',
                'stream=index,codec_type,color_transfer:stream_tags=language,title:format=duration',
                '-of','json',inp])
    info=json.loads(raw)
    if not any(x.get('codec_type')=='video' for x in info.get('streams',[])):
        raise ValueError('Input contains no video stream')
    duration=float(info.get('format',{}).get('duration','nan'))
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('Input duration must be known and positive')
    tracks=[x for x in info['streams'] if x.get('codec_type')=='audio']
    data={'tracks':tracks,'duration':duration,'audio':bool(tracks)}
    first_video=next(x for x in info['streams'] if x.get('codec_type')=='video')
    if first_video.get('color_transfer') in ('smpte2084','arib-std-b67'):
        data['hdr_transfer']=first_video['color_transfer']
    return data


def verified_frame_count(probe:Path, movie:Path) -> int:
    raw=invoke([probe,'-v','error','-select_streams','v:0',
         '-count_packets','-show_entries','stream=nb_read_packets',
         '-of','default=noprint_wrappers=1:nokey=1',movie]).strip()
    if not raw.isdigit() or int(raw)<=0:
        raise RuntimeError('Could not confirm encoded video frame count')
    return int(raw)


def verify_audio_duration(encoder: Path, movie: Path, seconds: float) -> None:
    output=invoke([encoder,'-hide_banner','-nostdin','-v','error','-xerror','-nostats',
                   '-progress','pipe:1','-i',movie,'-map','0:a:0','-f','null','-'])
    end_times=[int(value) for line in output.splitlines()
               if line.startswith(b'out_time_us=') and (value:=line.split(b'=',1)[1]).isdigit()]
    if not end_times or abs(end_times[-1]/1_000_000-seconds)>257/48000:
        raise RuntimeError('Decoded audio duration does not match video within one audio block')


def probe_coded_rate(probe:Path, movie:Path) -> float:
    """Read the actual rate exposed by this FFmpeg's MOFLEX demuxer.

    Older builds expose the *display* rate for interleaved stereo packets.
    Corrected builds expose the doubled coded rate. The remux must support
    both without losing half the eye frames or halving the descriptor FPS.
    """
    raw=invoke([probe,'-v','error','-select_streams','v:0',
         '-show_entries','stream=r_frame_rate','-of','json',movie])
    value=json.loads(raw)['streams'][0]['r_frame_rate']
    return float(Fraction(value))


def encode(args: argparse.Namespace, callback: Callable[[str],None]=print,
           progress: Callable[[int,float],None] | None=None) -> Path:
    inp=Path(args.input).expanduser().resolve()
    if not inp.is_file():raise FileNotFoundError(inp)
    encoder=pick_encoder(args.ffmpeg)
    probe=encoder.with_name('ffprobe'+EXE_SUFFIX)
    if not probe.is_file():raise FileNotFoundError(f'Custom ffprobe missing: {probe}')
    # These checks prevent accidental use of standard H.264 output or a
    # stock FFmpeg lacking the custom MOFLEX muxer.
    enc_help=invoke([encoder,'-hide_banner','-h','encoder=mobiclip'])
    mux_help=invoke([encoder,'-hide_banner','-h','muxer=moflex'])
    if (b'mobiclip' not in enc_help.lower() or b'mo_layout' not in mux_help
            or (args.mode!='2d' and
                b'mo_interleave_input_double_rate' not in mux_help)):
        raise RuntimeError('Wrong FFmpeg build: custom Mobiclip/MOFLEX required')
    if args.audio_codec=='fastaudio':
        try:
            help_text=invoke([encoder,'-hide_banner','-h','encoder=fastaudio'])
            if b'Encoder fastaudio' not in help_text or b'fastaudio' not in mux_help:
                raise RuntimeError('FastAudio encoder or muxer support is missing')
        except RuntimeError:
            callback('FastAudio is unavailable in this build; using ADPCM compatibility audio.')
            args.audio_codec='adpcm'
    media=probe_media(probe,inp)
    if media['audio'] and not 0 <= args.audio_track < len(media['tracks']):
        raise ValueError('Selected audio track does not exist')
    audio_offset=getattr(args,'audio_offset_ms',0)
    if not isinstance(audio_offset,int) or abs(audio_offset)>30000:
        raise ValueError('Audio offset must be between -30000 and 30000 ms')
    width,height=map(int,args.resolution.split('x'))
    fps=rate_value(args.fps)
    if args.q is not None and not 12<=args.q<=59:
        raise ValueError('Q must be between 12 and 59')
    base_q=args.q if args.q is not None else PRESETS[args.preset]['q']
    out=Path(args.output).expanduser().resolve() if args.output else inp.with_name(
        inp.stem+'_MobiPEG_V15_'+args.mode.upper().replace('-','_')+'.moflex')
    if out.suffix.lower()!='.moflex':raise ValueError('Output must have .moflex extension')
    if out==inp:raise ValueError('Input and output cannot be the same file')
    if out.is_file() and not args.overwrite:raise FileExistsError(f'Will not overwrite: {out}')
    if not out.parent.is_dir():raise FileNotFoundError(f'Output folder does not exist: {out.parent}')
    available_cores=os.cpu_count() or 1
    if not 1<=args.workers<=available_cores:
        raise ValueError(f'Worker count must be 1–{available_cores} on this device')
    tone_map=hdr_filter(media.get('hdr_transfer'),getattr(args,'hdr_mode','auto'))
    filters,layout=video_filters(args.mode,width,height,args.fps,args.filter,tone_map)
    if tone_map:
        callback(f"Converting {media['hdr_transfer']} HDR to BT.709 SDR.")
    stereo=args.mode!='2d'
    coded_fps_label=coded_rate_label(args.fps,args.mode)
    coded_fps=rate_value(args.fps)*(2 if stereo else 1)
    layout_options=(['-mo_layout',layout,'-mo_interleave_input_double_rate','1']
                    if stereo else ['-mo_layout',layout])
    if args.max_size_mb is not None and (not math.isfinite(args.max_size_mb) or args.max_size_mb<0.004096):
        raise ValueError('Maximum output size must be at least 0.004096 MB')
    target_bytes=None
    if args.max_size_mb is not None:
        target_bytes=(FAT32_LIMIT if args.max_size_mb>=FAT32_LIMIT/1_000_000
                      else math.floor(args.max_size_mb*1_000_000))
    rate=int(max(1,math.ceil(fps*2)))
    description={'input':str(inp),'output':str(out),'mode':args.mode,
                 'resolution':args.resolution,'fps':args.fps,'preset':args.preset,
                 'filter':args.filter,'base_quantizer':base_q,
                 'motion_refinement':args.motion_refinement,
                 'coded_fps':coded_fps_label,'layout':layout,
                 'maximum_bytes':target_bytes,'audio':media['audio'],
                 'audio_codec':args.audio_codec,
                 'audio_offset_ms':audio_offset,
                 'ffmpeg':str(encoder),'workers':args.workers}
    callback(json.dumps(description,indent=2))
    estimate=estimate_storage(media['duration'],args.resolution,args.fps,args.mode,
                              base_q,media['audio'],args.workers)
    available=shutil.disk_usage(out.parent).free
    callback(f"Storage estimate (rough): output {estimate['minimum']/1e6:.1f}–{estimate['maximum']/1e6:.1f} MB; "
             f"up to {estimate['temporary']/1e6:.1f} MB temporary; {available/1e6:.1f} MB free on destination disk")
    if available<estimate['temporary']:
        callback('WARNING: Estimated temporary usage exceeds free disk space. Encoding may fail.')
    if estimate['maximum']>FAT32_LIMIT:
        callback(f"WARNING: Estimated output may exceed the FAT32 per-file limit by "
                 f"{estimate['maximum']-FAT32_LIMIT:,} bytes. {FAT32_MESSAGE}")
    else:
        callback(f"FAT32 file limit: {FAT32_LIMIT:,} bytes. Estimated headroom: "
                 f"{FAT32_LIMIT-estimate['maximum']:,} bytes.")
    if args.dry_run:return out

    peak_gain=0
    if getattr(args,'normalize_audio',False) and media['audio']:
        callback('Measuring audio peak across the selected track...')
        peak_gain=measure_audio_peak(encoder,inp,args.audio_track)
        callback(f'Using {peak_gain:+.1f} dB of gain for the entire movie.')

    if getattr(args,'resume',False) and args.workers==1:
        raise ValueError('Saved range recovery requires at least two workers.')
    if args.workers>1:
        with parallel_workspace(args,inp,out,encoder,media,callback) as scratch:
            final,frames,parts=encode_parallel(
                args=args,inp=inp,out=out,encoder=encoder,probe=probe,media=media,
                filters=filters,layout_options=layout_options,base_q=base_q,
                coded_fps_label=coded_fps_label,callback=callback,
                progress=progress or (lambda lane,fraction:None),
                invoke=invoke,verified_frame_count=verified_frame_count,
                probe_coded_rate=probe_coded_rate,q_flags=q_flags,
                presets=PRESETS,scratch=scratch,target_bytes=target_bytes,peak_gain=peak_gain)
            callback('Verifying complete parallel movie video decode...')
            invoke([encoder,'-hide_banner','-nostdin','-v','error','-xerror',
                    '-i',final,'-map','0:v:0','-f','null','-'])
            if media['audio']:
                callback('Verifying complete parallel movie audio decode...')
                verify_audio_duration(encoder,final,frames/coded_fps)
            if verified_frame_count(probe,final)!=frames:
                raise RuntimeError('Joined movie frame count differs from encoded ranges')
            if out.exists() and not args.overwrite:
                raise FileExistsError(f'Output appeared during conversion: {out}')
            if final.stat().st_size>FAT32_LIMIT:raise ValueError(FAT32_MESSAGE)
            os.replace(final,out)
            callback(f'PASS: {out} ({out.stat().st_size:,} bytes, {parts} parallel parts)')
            return out

    search=PRESETS[args.preset]['search']
    me=PRESETS[args.preset]['me']
    with tempfile.TemporaryDirectory(prefix='mobipeg-v15-',dir=out.parent) as scratch:
        tmp=Path(scratch)
        best=None
        seen={}
        low=12
        high=59
        q=base_q
        # If a hard cap is specified, find the lowest feasible quantizer.
        # Each candidate is an ACTUAL encoded+remuxed MOFLEX file, not a
        # guessed bitrate; container padding and ADPCM are accounted for.
        attempts=1 if target_bytes is None else 9
        for i in range(attempts):
            video=tmp/f'video_q{q}.moflex'
            final=tmp/f'final_q{q}.moflex'
            if q not in seen:
                callback(f'Encoding candidate {i+1}/{attempts} (actual Q={q})')
                command=[encoder,'-hide_banner','-nostdin','-v','error','-y',
                         '-i',inp,*filters,'-an','-c:v','mobiclip',
                         '-mobiclip','1',*q_flags(q),'-preset','medium',
                         '-me_method',me,'-g',str(rate),
                         *(['-r',coded_fps_label] if stereo else []),
                         *layout_options,'-f','moflex',video]
                # Experimental knobs from another terminal/session must not
                # accidentally alter this reproducible Studio encode.
                env={k:v for k,v in os.environ.items() if not k.startswith('MOBI_')}
                env.update({'MOBI_SUBME':str(search),'MOBI_SKIP':'0'})
                improve_motion=(args.motion_refinement=='on' or
                    (args.motion_refinement=='auto' and args.preset in ('best','quality')))
                if improve_motion:
                    env['MOBI_V11_MV_REFINE']='1'
                    env['MOBI_V11_MV_PENALTY']='0'
                invoke(command,env=env,timeout=None)
                frames=verified_frame_count(probe,video)
                if stereo and frames%2:
                    raise RuntimeError('Stereo encode lost an eye: odd number of coded frames')
                # Use encoded frame count, not input's nominal duration.
                seconds=frames/coded_fps
                if media['audio']:
                    remux_input=[]
                    remux_output=[]
                    if stereo:
                        exposed_fps=probe_coded_rate(probe,video)
                        if math.isclose(exposed_fps,fps,rel_tol=0.001):
                            # Legacy demuxer timestamps each coded eye at
                            # 1/display_fps, i.e. double real duration.
                            remux_input=['-itsscale','0.5']
                        elif not math.isclose(exposed_fps,coded_fps,rel_tol=0.001):
                            raise RuntimeError(f'Unexpected stereo packet rate: {exposed_fps}')
                        # Stream-copy output must advertise 2x coded FPS;
                        # muxer then writes the correct 1x display FPS.
                        remux_output=['-r',coded_fps_label]
                    seek,audio_map=audio_window(None,seconds,args.audio_track,audio_offset,peak_gain)
                    audio_command=[encoder,'-hide_banner','-nostdin','-v','error','-y',
                            *remux_input,
                            '-i',video,*seek,'-i',inp,'-map','0:v:0',*audio_map,
                            '-c:v','copy','-c:a','pcm_s16le','-ar','48000',
                            '-ac','2','-mo_audio',args.audio_codec,
                            *remux_output,*layout_options,'-t',f'{seconds:.8f}',
                            '-f','moflex',final]
                    try:invoke(audio_command,timeout=None)
                    except RuntimeError:
                        if args.audio_codec!='fastaudio':raise
                        callback('FastAudio encode failed; retrying this output with ADPCM compatibility audio.')
                        audio_command[audio_command.index('fastaudio')]='adpcm'
                        invoke(audio_command,timeout=None)
                else:shutil.copyfile(video,final)
                seen[q]={'bytes':final.stat().st_size,'frames':frames,'file':final}
            info=seen[q]
            callback(f'Q={q}, output={info["bytes"]:,} bytes, {info["frames"]} video frames')
            if target_bytes is None or info['bytes']<=target_bytes:
                if best is None or q<best[0]:best=(q,info)
                high=q-1
            else:
                low=q+1
            if target_bytes is None or low>high:break
            q=(low+high)//2
            if q in seen:break
        if best is None:
            raise RuntimeError('Cannot meet requested size even at the coarsest supported quantizer')
        chosen_q,selected=best
        final=selected['file']
        callback('Verifying complete video decode...')
        invoke([encoder,'-hide_banner','-nostdin','-v','error','-xerror',
                '-i',final,'-map','0:v:0','-f','null','-'],timeout=None)
        if media['audio']:
            callback('Verifying complete audio decode...')
            verify_audio_duration(encoder,final,selected['frames']/coded_fps)
        if verified_frame_count(probe,final)!=selected['frames']:
            raise RuntimeError('Frame count mismatch after audio remux')
        if target_bytes is not None and final.stat().st_size>target_bytes:
            raise RuntimeError('Encoded output unexpectedly exceeded the hard size cap')
        if out.exists() and not args.overwrite:
            raise FileExistsError(f'File appeared during encoding; preserving it: {out}')
        if final.stat().st_size>FAT32_LIMIT:raise ValueError(FAT32_MESSAGE)
        os.replace(final,out)
        callback(f'PASS: {out} ({out.stat().st_size:,} bytes, Q={chosen_q})')
    return out


def gui():
    try:
        import tkinter as tk
        from tkinter import filedialog,messagebox,ttk
    except ImportError as error:
        raise RuntimeError('Tkinter is not installed. Use CLI mode instead.') from error
    app=tk.Tk()
    app.title('MobiPEG Studio V15 — Nintendo 3DS Video Converter')
    app.geometry('760x590')
    app.columnconfigure(1,weight=1)
    paths={k:tk.StringVar() for k in ('input','output')}
    choices={'mode':tk.StringVar(value='2d'),
             'preset':tk.StringVar(value='quality'),
             'filter':tk.StringVar(value='detail'),
             'motion_refinement':tk.StringVar(value='auto'),
             'resolution':tk.StringVar(value='400x240'),
             'fps':tk.StringVar(value='24'),
             'audio_track':tk.StringVar(value='0 — First audio track'),
             'max_size_mb':tk.StringVar(value=''),
             'audio_offset_ms':tk.StringVar(value='0'),
             'normalize_audio':tk.BooleanVar(value=False),
             'hdr_mode':tk.StringVar(value='auto'),
             'audio_codec':tk.StringVar(value='adpcm')}
    cpu_count=os.cpu_count() or 1
    cpu_workers=tk.IntVar(value=min(2,cpu_count))
    def add_row(num,label,var,kind='text',values=(),action=None):
        ttk.Label(app,text=label).grid(row=num,column=0,sticky='w',padx=12,pady=6)
        if kind=='select':widget=ttk.Combobox(app,textvariable=var,values=values,state='readonly')
        else:widget=ttk.Entry(app,textvariable=var)
        widget.grid(row=num,column=1,sticky='ew',padx=6)
        if action:ttk.Button(app,text='Browse…',command=action).grid(row=num,column=2,padx=9)
    def browse_input():
        selected=filedialog.askopenfilename(filetypes=[('Videos','*.mp4 *.mkv *.mov *.avi'),('All files','*.*')])
        if not selected:return
        paths['input'].set(selected)
        try:
            encoder=pick_encoder()
            tracks=probe_media(encoder.with_name('ffprobe'+EXE_SUFFIX),Path(selected))['tracks']
            labels=[f"{i} — {t.get('tags',{}).get('language','Unknown language')} {t.get('tags',{}).get('title','')}" for i,t in enumerate(tracks)] or ['0 — No audio']
            audio_box.configure(values=labels)
            choices['audio_track'].set(labels[0])
        except Exception as error:messagebox.showerror('Cannot inspect audio',str(error))
    add_row(0,'Input video',paths['input'],action=browse_input)
    add_row(1,'Output MOFLEX',paths['output'],action=lambda:paths['output'].set(
        filedialog.asksaveasfilename(defaultextension='.moflex',filetypes=[('MOFLEX','*.moflex')]) or paths['output'].get()))
    add_row(2,'3DS video mode',choices['mode'],'select',MODES)
    add_row(3,'Quality preset',choices['preset'],'select',PRESETS.keys())
    add_row(4,'Image cleanup',choices['filter'],'select',FILTERS.keys())
    add_row(5,'Resolution per eye',choices['resolution'],'select',RESOLUTIONS)
    add_row(6,'Frames per second',choices['fps'],'select',RATES)
    add_row(7,'Max file size in MB (optional)',choices['max_size_mb'])
    add_row(8,'Motion refinement (V15)',choices['motion_refinement'],'select',MOTION_MODES)
    audio_box=ttk.Combobox(app,textvariable=choices['audio_track'],values=['0 — First audio track'],state='readonly')
    ttk.Label(app,text='Audio language / track').grid(row=9,column=0,sticky='w',padx=12)
    audio_box.grid(row=9,column=1,sticky='ew',padx=6)
    ttk.Label(app,text='MOFLEX audio codec').grid(row=10,column=0,sticky='w',padx=12)
    ttk.Combobox(app,textvariable=choices['audio_codec'],values=('adpcm','fastaudio'),state='readonly').grid(row=10,column=1,sticky='ew',padx=6)
    ttk.Label(app,text='Parallel encoders (logical CPUs)').grid(row=11,column=0,sticky='w',padx=12,pady=4)
    cpu_scale=ttk.Scale(app,from_=1,to=cpu_count,orient='horizontal',
                        command=lambda value:cpu_workers.set(max(1,round(float(value)))))
    cpu_scale.set(cpu_workers.get());cpu_scale.grid(row=11,column=1,sticky='ew',padx=6)
    ttk.Label(app,textvariable=cpu_workers).grid(row=11,column=2,padx=8)
    timeline=tk.Canvas(app,height=18,bg='#e1e4dc',highlightthickness=0)
    timeline.grid(row=12,column=0,columnspan=3,sticky='ew',padx=12,pady=5)
    add_row(13,'Audio offset (ms, + delays audio)',choices['audio_offset_ms'])
    ttk.Checkbutton(app,text='Normalize audio peak',variable=choices['normalize_audio']).grid(row=13,column=2,padx=9)
    add_row(14,'HDR to SDR',choices['hdr_mode'],'select',('auto','off','mobius','hable','reinhard'))
    lane_state={}
    def update_timeline(lane,fraction):
        if lane<0:return
        lane_state[lane]=max(lane_state.get(lane,0),max(0,min(1,fraction)))
        def render():
            timeline.delete('all');width=max(1,timeline.winfo_width());count=max(1,int(cpu_workers.get()))
            for i in range(count):
                left=width*i/count;right=width*(i+1)/count-3
                timeline.create_rectangle(left,0,right,18,fill='#d5d9d4',outline='')
                timeline.create_rectangle(left,0,left+(right-left)*lane_state.get(i,0),18,fill='#44745b',outline='')
        app.after(0,render)
    status=tk.StringVar(value='Ready. Your source file is never modified.')
    ttk.Label(app,textvariable=status).grid(row=16,column=0,columnspan=3,sticky='w',padx=12,pady=4)
    log=tk.Text(app,height=12,state='disabled',wrap='word')
    log.grid(row=17,column=0,columnspan=3,sticky='nsew',padx=12,pady=8)
    app.rowconfigure(17,weight=1)
    def write(message):
        def update():
            log.configure(state='normal')
            log.insert('end',message+'\n')
            log.see('end')
            log.configure(state='disabled')
        app.after(0,update)
    def convert():
        if not paths['input'].get():
            messagebox.showerror('Missing file','Choose an input video first.')
            return
        try:
            offset=int(choices['audio_offset_ms'].get() or '0')
            if abs(offset)>30000:raise ValueError()
        except ValueError:
            messagebox.showerror('Invalid audio offset','Enter an integer between -30,000 and 30,000 milliseconds.')
            return
        start.configure(state='disabled')
        status.set('Encoding and verifying…')
        lane_state.clear()
        # Tk variables are read only on Tk's own thread. Worker threads only
        # run the encoder and return UI updates via app.after(...).
        arguments=['--input',paths['input'].get(),
                   '--audio-track',choices['audio_track'].get().split()[0],
                   '--audio-offset-ms',str(offset),
                   '--hdr-mode',choices['hdr_mode'].get(),
                   '--audio-codec',choices['audio_codec'].get(),
                   '--mode',choices['mode'].get(),
                   '--preset',choices['preset'].get(),
                   '--filter',choices['filter'].get(),
                   '--motion-refinement',choices['motion_refinement'].get(),
                   '--resolution',choices['resolution'].get(),
                   '--fps',choices['fps'].get(),
                   '--workers',str(cpu_workers.get())]
        if paths['output'].get():arguments+=['--output',paths['output'].get()]
        if choices['max_size_mb'].get():arguments+=['--max-size-mb',choices['max_size_mb'].get()]
        if choices['normalize_audio'].get():arguments.append('--normalize-audio')
        def worker():
            try:
                result=encode(parser().parse_args(arguments),callback=write,progress=update_timeline)
                app.after(0,lambda:status.set('Success: '+str(result)))
            except Exception as error:
                write('ERROR: '+str(error))
                app.after(0,lambda:status.set('Failed — see log'))
            finally:app.after(0,lambda:start.configure(state='normal'))
        threading.Thread(target=worker,daemon=True).start()
    start=ttk.Button(app,text='Convert and verify MOFLEX',command=convert)
    start.grid(row=15,column=1,pady=10)
    app.mainloop()


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gui',action='store_true',help='Open a simple video conversion window')
    p.add_argument('--input','-i',help='Any FFmpeg-supported input video')
    p.add_argument('--output','-o',help='MOFLEX output; existing files preserved by default')
    p.add_argument('--mode',choices=MODES,default='2d')
    p.add_argument('--preset',choices=PRESETS,default='quality')
    p.add_argument('--filter',choices=FILTERS,default='detail')
    p.add_argument('--motion-refinement',choices=MOTION_MODES,default='auto',
                   help='auto enables native V15 MV refinement for best/quality presets')
    p.add_argument('--resolution',choices=RESOLUTIONS,default='400x240')
    p.add_argument('--fps',choices=RATES,default='24')
    p.add_argument('--q',type=int,default=None,help='Override actual 12..59 quantizer')
    p.add_argument('--max-size-mb',type=float,default=None,
                   help='Hard decimal-MB final file-size limit; trials may be slow')
    p.add_argument('--budget-mode',choices=('scene','uniform'),default='scene',help='Size-target range allocation: source texture/motion or legacy uniform')
    p.add_argument('--audio-track',type=int,default=0,help='Audio track number, starting at 0; use --list-audio-tracks to inspect languages')
    p.add_argument('--audio-offset-ms',type=int,default=0,help='Shift audio by up to 30 seconds; positive delays audio')
    p.add_argument('--normalize-audio',action='store_true',help='Measure the selected track and apply one peak-normalizing gain to the entire movie')
    p.add_argument('--hdr-mode',choices=('auto','off','mobius','hable','reinhard'),default='auto',
                   help='Tone map tagged PQ and HLG input to BT.709; auto uses Mobius')
    p.add_argument('--audio-codec',choices=('adpcm','fastaudio'),default='adpcm',help='ADPCM is the hardware-tested default; FastAudio is smaller but 3DS-unverified')
    p.add_argument('--workers',type=int,default=1,
                   help='Parallel encoders for movie-sized inputs, 1 up to logical CPU count')
    p.add_argument('--resume',action='store_true',
                   help='Save verified parallel ranges and resume with the same input, output and settings')
    p.add_argument('--list-audio-tracks',action='store_true',help='List audio languages/titles for --input and exit')
    p.add_argument('--ffmpeg',help='Path to the patched MobiPEG ffmpeg')
    p.add_argument('--overwrite',action='store_true',help='Replace existing exact output path')
    p.add_argument('--dry-run',action='store_true',help='Validate settings without writing a file')
    return p


def main():
    args=parser().parse_args()
    if args.list_audio_tracks and args.input:
        encoder=pick_encoder(args.ffmpeg)
        media=probe_media(encoder.with_name('ffprobe'+EXE_SUFFIX),Path(args.input))
        print(json.dumps([{'track':i,**t.get('tags',{})} for i,t in enumerate(media['tracks'])],indent=2))
        return 0
    if args.gui or not args.input:
        gui()
    else:
        try:encode(args)
        except (ValueError,RuntimeError,FileNotFoundError,FileExistsError) as error:
            print('ERROR:',error,file=sys.stderr)
            return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
