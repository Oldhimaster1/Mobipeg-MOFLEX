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


ROOT = Path(__file__).resolve().parent
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
    stages=[f'setsar={sar}',
            f'scale={width}:{height}:force_original_aspect_ratio=decrease:'
            f'force_divisible_by=2:{"reset_sar=1:" if sar==2 else ""}in_range=auto:out_range=tv:flags=lanczos',
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2', 'setsar=1']
    if clean:stages.append(clean)
    stages.append('format=yuv420p')
    return ','.join(stages)


def video_filters(mode: str, width: int, height: int, fps: str,
                  quality_filter: str) -> tuple[list[str], str]:
    if mode not in MODES:raise ValueError('Unknown stereoscopic mode')
    if quality_filter not in FILTERS:raise ValueError('Unknown cleanup filter')
    clean=FILTERS[quality_filter]
    if mode=='2d':
        return ['-vf',f'fps={fps},'+scale_filter(width,height,clean=clean)],'6'
    # Apply spatial-only cleanup separately to each eye; never average
    # left and right or let the filter see the inter-eye seam.
    sar=2 if mode=='half-sbs' else 1
    eye=scale_filter(width,height,sar=sar,clean=clean)
    # A layout-0 MOFLEX is not packed SBS. For each displayed stereo frame,
    # emit one full-width LEFT eye followed by one full-width RIGHT eye.
    # Give the two branches distinct PTS in a 2x display-rate time base;
    # FFmpeg's temporal interleave merges them in L,R,L,R order. No frame
    # can leak between eyes because each branch is spatially filtered alone.
    eye_tb=f'1/(2*({fps}))'
    spec=(f'[0:v:0]fps={fps},split=2[left][right];'
          f'[left]crop=iw/2:ih:0:0,{eye},'
          f'settb=expr={eye_tb},setpts=2*N[l];'
          f'[right]crop=iw/2:ih:iw/2:0,{eye},'
          f'settb=expr={eye_tb},setpts=2*N+1[r];'
          '[l][r]interleave=nb_inputs=2,format=yuv420p[vid]')
    return ['-filter_complex',spec,'-map','[vid]'],'0'


def pick_encoder(explicit: str | None=None) -> Path:
    choices=([Path(explicit)] if explicit else [ROOT/'local/bin/ffmpeg',
             ROOT/'MobiPEG_V13_work/local/bin/ffmpeg'])
    for path in choices:
        if path.is_file() and os.access(path,os.X_OK):return path.resolve()
    raise FileNotFoundError('Custom MobiPEG ffmpeg not found. Build it with BUILD_FOR_LINUX.sh / BUILD_FOR_MAC.command or pass --ffmpeg PATH.')


def invoke(args, env=None, timeout=1800):
    result=subprocess.run([str(a) for a in args],capture_output=True,
                          env=env,timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Encoder failed (exit {result.returncode}):\n'+
                           result.stderr.decode(errors='replace')[-2500:])
    return result.stdout


def probe_media(probe: Path, inp: Path) -> dict:
    raw=invoke([probe,'-v','error','-show_entries',
                'stream=index,codec_type:format=duration',
                '-of','json',inp])
    info=json.loads(raw)
    if not any(x.get('codec_type')=='video' for x in info.get('streams',[])):
        raise ValueError('Input contains no video stream')
    duration=float(info.get('format',{}).get('duration','nan'))
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('Input duration must be known and positive')
    return {'duration':duration,'audio':any(x.get('codec_type')=='audio'
                   for x in info['streams'])}


def verified_frame_count(probe:Path, movie:Path) -> int:
    raw=invoke([probe,'-v','error','-select_streams','v:0',
         '-count_packets','-show_entries','stream=nb_read_packets',
         '-of','default=noprint_wrappers=1:nokey=1',movie]).strip()
    if not raw.isdigit() or int(raw)<=0:
        raise RuntimeError('Could not confirm encoded video frame count')
    return int(raw)


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


def encode(args: argparse.Namespace, callback: Callable[[str],None]=print) -> Path:
    inp=Path(args.input).expanduser().resolve()
    if not inp.is_file():raise FileNotFoundError(inp)
    encoder=pick_encoder(args.ffmpeg)
    probe=encoder.with_name('ffprobe')
    if not probe.is_file():raise FileNotFoundError(f'Custom ffprobe missing: {probe}')
    # These checks prevent accidental use of standard H.264 output or a
    # stock FFmpeg lacking the custom MOFLEX muxer.
    enc_help=invoke([encoder,'-hide_banner','-h','encoder=mobiclip'])
    mux_help=invoke([encoder,'-hide_banner','-h','muxer=moflex'])
    if (b'mobiclip' not in enc_help.lower() or b'mo_layout' not in mux_help
            or (args.mode!='2d' and
                b'mo_interleave_input_double_rate' not in mux_help)):
        raise RuntimeError('Wrong FFmpeg build: custom Mobiclip/MOFLEX required')
    media=probe_media(probe,inp)
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
    filters,layout=video_filters(args.mode,width,height,args.fps,args.filter)
    stereo=args.mode!='2d'
    coded_fps_label=coded_rate_label(args.fps,args.mode)
    coded_fps=rate_value(args.fps)*(2 if stereo else 1)
    layout_options=(['-mo_layout',layout,'-mo_interleave_input_double_rate','1']
                    if stereo else ['-mo_layout',layout])
    target_bytes=math.floor(args.max_size_mb*1000*1000) if args.max_size_mb else None
    if target_bytes is not None and target_bytes<4096:
        raise ValueError('Maximum output size is too small')
    rate=int(max(1,math.ceil(fps*2)))
    description={'input':str(inp),'output':str(out),'mode':args.mode,
                 'resolution':args.resolution,'fps':args.fps,'preset':args.preset,
                 'filter':args.filter,'base_quantizer':base_q,
                 'motion_refinement':args.motion_refinement,
                 'coded_fps':coded_fps_label,'layout':layout,
                 'maximum_bytes':target_bytes,'audio':media['audio'],
                 'ffmpeg':str(encoder)}
    callback(json.dumps(description,indent=2))
    if args.dry_run:return out

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
                invoke(command,env=env)
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
                    invoke([encoder,'-hide_banner','-nostdin','-v','error','-y',
                            *remux_input,
                            '-i',video,'-i',inp,'-map','0:v:0','-map','1:a:0',
                            '-c:v','copy','-c:a','pcm_s16le','-ar','44100',
                            '-ac','2','-af','apad','-mo_audio','adpcm',
                            *remux_output,*layout_options,'-t',f'{seconds:.8f}',
                            '-f','moflex',final])
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
                '-i',final,'-map','0:v:0','-f','null','-'],timeout=3600)
        if media['audio']:
            callback('Verifying complete audio decode...')
            invoke([encoder,'-hide_banner','-nostdin','-v','error','-xerror',
                    '-i',final,'-map','0:a:0','-f','null','-'],timeout=3600)
        if verified_frame_count(probe,final)!=selected['frames']:
            raise RuntimeError('Frame count mismatch after audio remux')
        if target_bytes is not None and final.stat().st_size>target_bytes:
            raise RuntimeError('Encoded output unexpectedly exceeded the hard size cap')
        if out.exists() and not args.overwrite:
            raise FileExistsError(f'File appeared during encoding; preserving it: {out}')
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
    app.geometry('760x530')
    app.columnconfigure(1,weight=1)
    paths={k:tk.StringVar() for k in ('input','output')}
    choices={'mode':tk.StringVar(value='2d'),
             'preset':tk.StringVar(value='quality'),
             'filter':tk.StringVar(value='detail'),
             'motion_refinement':tk.StringVar(value='auto'),
             'resolution':tk.StringVar(value='400x240'),
             'fps':tk.StringVar(value='24'),
             'max_size_mb':tk.StringVar(value='')}
    def add_row(num,label,var,kind='text',values=(),action=None):
        ttk.Label(app,text=label).grid(row=num,column=0,sticky='w',padx=12,pady=6)
        if kind=='select':widget=ttk.Combobox(app,textvariable=var,values=values,state='readonly')
        else:widget=ttk.Entry(app,textvariable=var)
        widget.grid(row=num,column=1,sticky='ew',padx=6)
        if action:ttk.Button(app,text='Browse…',command=action).grid(row=num,column=2,padx=9)
    add_row(0,'Input video',paths['input'],action=lambda:paths['input'].set(
        filedialog.askopenfilename(filetypes=[('Videos','*.mp4 *.mkv *.mov *.avi'),('All files','*.*')]) or paths['input'].get()))
    add_row(1,'Output MOFLEX',paths['output'],action=lambda:paths['output'].set(
        filedialog.asksaveasfilename(defaultextension='.moflex',filetypes=[('MOFLEX','*.moflex')]) or paths['output'].get()))
    add_row(2,'3DS video mode',choices['mode'],'select',MODES)
    add_row(3,'Quality preset',choices['preset'],'select',PRESETS.keys())
    add_row(4,'Image cleanup',choices['filter'],'select',FILTERS.keys())
    add_row(5,'Resolution per eye',choices['resolution'],'select',RESOLUTIONS)
    add_row(6,'Frames per second',choices['fps'],'select',RATES)
    add_row(7,'Max file size in MB (optional)',choices['max_size_mb'])
    add_row(8,'Motion refinement (V15)',choices['motion_refinement'],'select',MOTION_MODES)
    status=tk.StringVar(value='Ready. Your source file is never modified.')
    ttk.Label(app,textvariable=status).grid(row=10,column=0,columnspan=3,sticky='w',padx=12,pady=4)
    log=tk.Text(app,height=12,state='disabled',wrap='word')
    log.grid(row=11,column=0,columnspan=3,sticky='nsew',padx=12,pady=8)
    app.rowconfigure(11,weight=1)
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
        start.configure(state='disabled')
        status.set('Encoding and verifying…')
        # Tk variables are read only on Tk's own thread. Worker threads only
        # run the encoder and return UI updates via app.after(...).
        arguments=['--input',paths['input'].get(),
                   '--mode',choices['mode'].get(),
                   '--preset',choices['preset'].get(),
                   '--filter',choices['filter'].get(),
                   '--motion-refinement',choices['motion_refinement'].get(),
                   '--resolution',choices['resolution'].get(),
                   '--fps',choices['fps'].get()]
        if paths['output'].get():arguments+=['--output',paths['output'].get()]
        if choices['max_size_mb'].get():arguments+=['--max-size-mb',choices['max_size_mb'].get()]
        def worker():
            try:
                result=encode(parser().parse_args(arguments),callback=write)
                app.after(0,lambda:status.set('Success: '+str(result)))
            except Exception as error:
                write('ERROR: '+str(error))
                app.after(0,lambda:status.set('Failed — see log'))
            finally:app.after(0,lambda:start.configure(state='normal'))
        threading.Thread(target=worker,daemon=True).start()
    start=ttk.Button(app,text='Convert and verify MOFLEX',command=convert)
    start.grid(row=9,column=1,pady=10)
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
    p.add_argument('--ffmpeg',help='Path to the patched MobiPEG ffmpeg')
    p.add_argument('--overwrite',action='store_true',help='Replace existing exact output path')
    p.add_argument('--dry-run',action='store_true',help='Validate settings without writing a file')
    return p


def main():
    args=parser().parse_args()
    if args.gui or not args.input:
        gui()
    else:
        try:encode(args)
        except (ValueError,RuntimeError,FileNotFoundError,FileExistsError) as error:
            print('ERROR:',error,file=sys.stderr)
            return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
