#!/usr/bin/env python3
"""Inspect and convert MobiClip MOFLEX files with the bundled FFmpeg.

Stereo layout comes from the MOFLEX video descriptor, never from a filename.
Layouts 0/1 are alternating coded eyes, 2/3 are top/bottom, 4/5 are
side-by-side, and 6 is ordinary 2D.  Duplicate-eye detection is deliberately
reported as a heuristic because near-static genuine stereo can look similar.
"""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys
from pathlib import Path

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
    data=path.read_bytes()[:4096]
    if data[:4]!=b'L2\xaa\xab':raise ValueError('Not a MOFLEX file')
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
            if not num or not den or not width or not height or layout not in range(7):
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
    left,right=(first,second) if layout%2==0 else (second,first)
    if mode=='left' or mode=='2d':return left
    if mode=='right':return right
    return f'split=2[l0][r0];[l0]{left}[l];[r0]{right}[r];[l][r]hstack=inputs=2'

def classify_eyes(path,ffmpeg,info,frames=8):
    if info['eyes']==1:return {'stereo':'2d','difference':None,'heuristic':False}
    filt=_eye_filter(info,'sbs')
    width=info['width']*(2 if info['layout']<4 else 1)
    height=info['height']//2 if 2<=info['layout']<4 else info['height']
    raw=_run([ffmpeg,'-v','error','-i',path,'-vf',f'{filt},format=gray','-frames:v',str(frames),'-f','rawvideo','pipe:1'])
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
    probe=Path(ffmpeg).with_name('ffprobe'+EXE)
    meta=json.loads(_run([probe,'-v','error','-count_packets','-show_entries','stream=index,codec_name,codec_type,sample_rate,channels,nb_read_packets:format=duration','-of','json',path]))
    info.update(classify_eyes(path,ffmpeg,info));info['streams']=meta.get('streams',[])
    value=float(meta.get('format',{}).get('duration','nan'))
    if not math.isfinite(value):
        video=next((x for x in info['streams'] if x.get('codec_type')=='video'),{})
        value=int(video.get('nb_read_packets',0))/info['coded_fps']
    info['duration']=value
    return info

def convert(inp,out,mode='auto',ffmpeg=None,overwrite=False):
    ffmpeg=Path(ffmpeg) if ffmpeg else ROOT/('local/bin/ffmpeg'+EXE)
    if not ffmpeg.is_file():raise FileNotFoundError(ffmpeg)
    info=video_descriptor(inp)
    selected=('sbs' if info['eyes']==2 else '2d') if mode=='auto' else mode
    vf=_eye_filter(info,selected)
    if out.suffix.lower() not in ('.mp4','.mkv'):raise ValueError('Output must be MP4 or MKV')
    if out.exists() and not overwrite:raise FileExistsError(f'Will not overwrite: {out}')
    args=[ffmpeg,'-hide_banner','-nostdin','-v','error','-xerror','-y' if overwrite else '-n','-i',inp]
    if vf:args+=['-vf',vf]
    args+=['-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','medium','-crf','18',
           '-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-af','aresample=async=0:first_pts=0',
           '-shortest']
    if out.suffix.lower()=='.mp4':args+=['-movflags','+faststart']
    args+=[out]
    _run(args)
    # Decode both streams after publication; malformed exports are removed.
    try:_run([ffmpeg,'-v','error','-xerror','-i',out,'-map','0:v:0','-map','0:a:0?','-f','null','-'])
    except Exception:
        out.unlink(missing_ok=True);raise
    return inspect(inp,ffmpeg)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('-o','--output',type=Path)
    p.add_argument('--mode',choices=('auto','2d','sbs','left','right'),default='auto')
    p.add_argument('--ffmpeg');p.add_argument('--overwrite',action='store_true');p.add_argument('--inspect',action='store_true')
    a=p.parse_args();ffmpeg=Path(a.ffmpeg) if a.ffmpeg else ROOT/('local/bin/ffmpeg'+EXE)
    try:
        if a.inspect or not a.output:print(json.dumps(inspect(a.input,ffmpeg),indent=2))
        else:print(json.dumps(convert(a.input,a.output,a.mode,ffmpeg,a.overwrite),indent=2))
    except (ValueError,RuntimeError,FileNotFoundError,FileExistsError) as e:print('ERROR:',e,file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
