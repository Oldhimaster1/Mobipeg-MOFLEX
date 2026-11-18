#!/usr/bin/env python3
"""Inspect and convert MobiClip MOFLEX files with the bundled FFmpeg.

Stereo layout comes from the MOFLEX video descriptor, never from a filename.
Layouts 0/1 are alternating coded eyes, 2/3 are top/bottom, 4/5 are
side-by-side, and 6 is ordinary 2D.  Duplicate-eye detection is deliberately
reported as a heuristic because near-static genuine stereo can look similar.
"""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys, tempfile
from pathlib import Path
from super_moflex import describe, extract_audio, language_text, read_at, trailer, MAX_TEXT

ROOT=Path(__file__).resolve().parent
EXE='.exe' if os.name=='nt' else ''

def _varint(data,pos):
    value=0
    for _ in range(4):
        if pos>=len(data):raise ValueError('Truncated MOFLEX descriptor')
        byte=data[pos];pos+=1;value=(value<<7)|(byte&127)
        if not byte&128:return value,pos
    raise ValueError('Invalid MOFLEX descriptor varint')

def video_descriptor(path:Path):
    with path.open('rb') as source:
        data=source.read(4096)
    if len(data)<14 or data[:2]!=b'L2':raise ValueError('Not a MOFLEX file')
    pos=14
    while pos<len(data):
        kind,pos=_varint(data,pos);length,pos=_varint(data,pos)
        if kind==0:break
        if pos+length>len(data):raise ValueError('Malformed MOFLEX descriptor')
        if kind==3:
            b=data[pos:pos+length]
            if len(b)<13:raise ValueError('Short MOFLEX video descriptor')
            num=int.from_bytes(b[0:4],'big');den=int.from_bytes(b[4:6],'big')
            width=int.from_bytes(b[6:8],'big');height=int.from_bytes(b[8:10],'big');layout=b[12]
            if not num or not den or not 0<width<=4096 or not 0<height<=4096 or layout not in range(7):
                raise ValueError(f'Unsupported MOFLEX video descriptor (layout {layout})')
            family=('interleaved' if layout<2 else 'top-bottom' if layout<4 else
                    'side-by-side' if layout<6 else '2d')
            eyes=1 if layout==6 else 2
            return {'width':width,'height':height,'layout':layout,'family':family,
                    'eyes':eyes,'display_fps':num/den,
                    'coded_fps':num/den*(2 if layout<2 else 1)}
        pos+=length
    raise ValueError('No MobiClip video descriptor')

def _run(argv,stdout=subprocess.PIPE):
    result=subprocess.run([str(x) for x in argv],stdout=stdout,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[-3000:])
    return result.stdout

def _eye_filter(info,mode):
    layout=info['layout'];fps=info['display_fps']
    if layout==6:
        if mode in ('right','sbs'):raise ValueError('This MOFLEX descriptor is 2D')
        return None
    if layout<2:
        first="select='not(mod(n,2))',setpts=N/(%0.12g*TB)"%fps
        second="select='mod(n,2)',setpts=N/(%0.12g*TB)"%fps
    elif layout<4:
        first='crop=iw:ih/2:0:0';second='crop=iw:ih/2:0:ih/2'
    else:
        first='crop=iw/2:ih:0:0';second='crop=iw/2:ih:iw/2:0'
    left_first=(layout==1) if layout<2 else (layout%2==0)
    left,right=(first,second) if left_first else (second,first)
    if mode=='left' or mode=='2d':return left
    if mode=='right':return right
    return f'split=2[l0][r0];[l0]{left}[l];[r0]{right}[r];[l][r]hstack=inputs=2'

def classify_eyes(path,ffmpeg,info,frames=8):
    if info['eyes']==1:return {'stereo':'2d','difference':None,'heuristic':False}
    filt=_eye_filter(info,'sbs')
    width,height=128,64
    raw=_run([ffmpeg,'-v','error','-i',path,'-vf',f'{filt},scale={width}:{height},format=gray','-frames:v',str(frames),'-f','rawvideo','pipe:1'])
    frame=width*height;eye=width//2;total=0;count=0
    for off in range(0,len(raw)-frame+1,frame):
        buf=raw[off:off+frame]
        for y in range(height):
            row=y*width
            a=buf[row:row+eye];b=buf[row+eye:row+width]
            total+=sum(abs(x-y) for x,y in zip(a,b));count+=len(a)
    difference=total/(max(1,count)*255)
    return {'stereo':'duplicated-eyes' if difference<0.002 else 'genuine-3d',
            'difference':difference,'heuristic':True}

def inspect(path,ffmpeg):
    info=video_descriptor(path)
    extra=describe(path)
    media=media_uri(path,extra['moflex_bytes'])
    probe=Path(ffmpeg).with_name('ffprobe'+EXE)
    meta=json.loads(_run([probe,'-v','error','-count_packets','-show_entries','stream=index,codec_name,codec_type,sample_rate,channels,nb_read_packets:format=duration','-of','json',media]))
    info.update(classify_eyes(media,ffmpeg,info));info['streams']=meta.get('streams',[])
    video=next((x for x in info['streams'] if x.get('codec_type')=='video'),{})
    value=int(video.get('nb_read_packets','0'))/info['coded_fps']
    if not value:
        value=float(meta.get('format',{}).get('duration','nan'))
    info['duration']=value
    info['trailer']=extra
    return info

def media_uri(path, size):
    return path if size==path.stat().st_size else f'subfile,,start,0,end,{size},,:{path.resolve()}'


def convert(inp,out,mode='auto',ffmpeg=None,overwrite=False,audio='primary',subtitles='all'):
    ffmpeg=Path(ffmpeg) if ffmpeg else ROOT/('local/bin/ffmpeg'+EXE)
    if not ffmpeg.is_file():raise FileNotFoundError(ffmpeg)
    info=inspect(inp,ffmpeg)
    selected=('sbs' if info['eyes']==2 else '2d') if mode=='auto' else mode
    vf=_eye_filter(info,selected)
    if out.suffix.lower() not in ('.mp4','.mkv'):raise ValueError('Output must be MP4 or MKV')
    if out.exists() and not overwrite:raise FileExistsError(f'Will not overwrite: {out}')
    size,sections=trailer(inp)
    alternate=next((section for section in sections if section.tag in (b'AUD0',b'AUD1')),None)
    if audio=='alternate' and alternate is None:
        raise ValueError('The file has no alternate audio track')
    if not math.isfinite(info['duration']) or info['duration']<=0:
        raise ValueError('Could not determine the movie video duration')
    with tempfile.TemporaryDirectory(prefix='mobipeg-export-',dir=out.parent) as directory, inp.open('rb') as stream:
        work=Path(directory)
        args=[ffmpeg,'-hide_banner','-nostdin','-v','error','-xerror','-i',media_uri(inp,size)]
        maps=['-map','0:v:0']
        languages=[]
        if audio in ('primary','all') and any(s['codec_type']=='audio' for s in info['streams']):
            maps+=['-map','0:a:0']
            languages.append(info['trailer']['primary_language'])
        next_input=1
        if audio in ('alternate','all') and alternate:
            path=work/'alternate.wav'
            languages.append(extract_audio(stream,alternate,path,info['duration']))
            args+=['-i',path]
            maps+=['-map',f'{next_input}:a:0']
            next_input+=1
        selected_subs=[]
        if subtitles!='none':
            for section in sections:
                if section.tag not in (b'SUB0',b'SUB1'):
                    continue
                extra=4 if section.tag==b'SUB1' else 0
                language=language_text(read_at(stream,section.offset,4)) if extra else 'und'
                if subtitles!='all' and language.upper()!=subtitles.upper():
                    continue
                if not extra<section.length<=MAX_TEXT+extra:
                    raise ValueError('Invalid or too-large embedded subtitle')
                text=read_at(stream,section.offset+extra,section.length-extra)
                suffix='.ass' if b'[Events]' in text or b'[Script Info]' in text else '.srt'
                path=work/f'subtitle-{next_input}{suffix}'
                path.write_bytes(text)
                args+=['-i',path]
                maps+=['-map',f'{next_input}:s:0']
                selected_subs.append(language)
                next_input+=1
        args+=maps
        if vf:args+=['-vf',vf]
        args+=['-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p',
               '-c:a','aac','-b:a','160k','-af','aresample=async=0:first_pts=0',
               '-t',f"{info['duration']:.9f}"]
        for index,language in enumerate(languages):
            if language:args+= [f'-metadata:s:a:{index}',f'language={language.lower()}']
        if selected_subs:
            args+=['-c:s','mov_text' if out.suffix.lower()=='.mp4' else 'srt']
            for index,language in enumerate(selected_subs):
                args+=[f'-metadata:s:s:{index}',f'language={language.lower()}']
        if out.suffix.lower()=='.mp4':args+=['-movflags','+faststart']
        output=work/('export'+out.suffix)
        _run([*args,output])
        _run([ffmpeg,'-v','error','-xerror','-i',output,'-map','0:v:0','-map','0:a?','-f','null','-'])
        if out.exists() and not overwrite:
            raise FileExistsError(out)
        output.replace(out)
    return info

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('-o','--output',type=Path)
    p.add_argument('--mode',choices=('auto','2d','sbs','left','right'),default='auto')
    p.add_argument('--audio',choices=('primary','alternate','all','none'),default='primary')
    p.add_argument('--subtitles',default='all',help='all, none, or a language code')
    p.add_argument('--ffmpeg');p.add_argument('--overwrite',action='store_true');p.add_argument('--inspect',action='store_true')
    a=p.parse_args();ffmpeg=Path(a.ffmpeg) if a.ffmpeg else ROOT/('local/bin/ffmpeg'+EXE)
    try:
        if a.inspect or not a.output:print(json.dumps(inspect(a.input,ffmpeg),indent=2))
        else:print(json.dumps(convert(a.input,a.output,a.mode,ffmpeg,a.overwrite,a.audio,a.subtitles),indent=2))
    except (ValueError,RuntimeError,FileNotFoundError,FileExistsError) as e:print('ERROR:',e,file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
