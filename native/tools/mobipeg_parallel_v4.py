#!/usr/bin/env python3
"""Experimental multicore MobiPEG/MobiClip MOFLEX encoder, V4 validation pipeline.

Supports source video, SBS full/half stereoscopy -> 800x240 MOFLEX 3D
(layout=4, left eye first), actual video decoding validation, and immutable
QP/subme/skip settings across workers. Does NOT promise bit-exact sequential
output or physical 3DS playback. Uses the genuine MobiPEG FFmpeg binary.
"""
import argparse
import concurrent.futures
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


def call(argv, env=None, capture=False):
    argv=[str(a) for a in argv]
    p=subprocess.run(argv, env=env, text=True, errors='replace',
                     stdout=subprocess.PIPE if capture else None,
                     stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        s=(p.stderr or '') if capture else ''
        raise RuntimeError('Command failed (code %d): %s\n%s' % (p.returncode, repr(argv), s[-2000:]))
    return p.stdout if capture else None


def video_packet_hash(ffprobe, path):
    """SHA256 of *every MobiClip payload*; independent of mux/audio bytes."""
    encoded=call([ffprobe,'-v','error','-select_streams','v:0','-show_packets',
                  '-show_data_hash','sha256','-show_entries','packet=data_hash',
                  '-of','csv=p=0',path],capture=True)
    parts=[x.strip().strip(',') for x in encoded.splitlines() if x.strip()]
    if not parts or not all(p.startswith('SHA256:') for p in parts):
        raise RuntimeError('FFprobe could not hash all MobiClip packets')
    return hashlib.sha256('\n'.join(parts).encode('ascii')).hexdigest(),len(parts)


def assert_full_decode(ffmpeg,path):
    """A packet count is NOT a decoder test: reject corrupt slice-thread output."""
    digest=call([ffmpeg,'-nostdin','-hide_banner','-xerror','-v','error',
                 '-i',path,'-map','0:v:0','-an','-c:v','rawvideo',
                 '-f','md5','-'],capture=True)
    if not digest.strip().startswith('MD5='):
        raise RuntimeError('Decoder did not produce decoded frame digest')
    return digest.strip()


def probe_video(fp, path):
    p=call([fp,'-v','error','-select_streams','v:0', '-count_frames',
            '-show_entries','stream=width,height,nb_read_frames',
            '-of','json',path],capture=True)
    data=json.loads(p)
    streams=data.get('streams',[])
    if not streams:raise ValueError('No decodable video stream: '+str(path))
    d=streams[0]
    return (int(d['width']),int(d['height']),int(d['nb_read_frames']))


def moflex_layout(path):
    """Read first VideoWithLayout descriptor, or return None for unknown muxer."""
    with open(path,'rb') as fd:
        prefix=fd.read(256)
    if prefix[:4]!=b'\x4c\x32\xaa\xab':
        return None
    # The MobiPEG muxer writes a type-3, 13-byte descriptor in every header.
    pos=prefix.find(b'\x03\x0d',4)
    if pos<0 or pos+15>len(prefix):return None
    return {'width':int.from_bytes(prefix[pos+8:pos+10],'big'),
            'height':int.from_bytes(prefix[pos+10:pos+12],'big'),
            'layout':prefix[pos+14]}


def change_scores(y4m_path, frame_bytes, sample_step=128):
    """Score each input frame transition in luma; no external libraries.

    Absolute differences are taken from a fixed, uniformly sampled set of
    Y pixels, so neither movie content nor worker count changes the scores.
    No need to decompress lossy video twice: source is a normalized raw Y4M.
    """
    transitions=[0.0]
    with open(y4m_path,'rb') as f:
        header=f.readline()
        w=re.search(rb'\bW(\d+)\b',header)
        h=re.search(rb'\bH(\d+)\b',header)
        if not (header.startswith(b'YUV4MPEG2 ') and w and h):
            raise ValueError('Invalid Y4M header')
        ysize=int(w[1])*int(h[1]); prev=None
        while True:
            tag=f.readline()
            if not tag:break
            if not tag.startswith(b'FRAME'):
                raise ValueError('Corrupt Y4M frame tag')
            frame=f.read(frame_bytes)
            if len(frame)!=frame_bytes:raise ValueError('Truncated Y4M frame')
            sample=frame[:ysize:sample_step]
            if prev is not None:
                transitions.append(sum(abs(a-b) for a,b in zip(sample,prev))/len(sample))
            prev=sample
    return transitions


def count_y4m_frames(y4m_path, frame_bytes):
    """Fast frame count for fixed GOP chunks; no luma analysis is needed.

    The Y4M stream was freshly normalized by our own FFmpeg, so each frame
    consists of one FRAME header followed by the same raw byte count.
    """
    count = 0
    file_size = y4m_path.stat().st_size
    with y4m_path.open('rb') as fd:
        if not fd.readline().startswith(b'YUV4MPEG2 '):
            raise ValueError('Invalid normalized Y4M header')
        while True:
            tag = fd.readline()
            if not tag:
                break
            if not tag.startswith(b'FRAME'):
                raise ValueError('Unexpected Y4M frame marker')
            fd.seek(frame_bytes,1)
            if fd.tell() > file_size:
                raise ValueError('Truncated Y4M frame')
            count += 1
    return count


def choose_seams(scores, target_frames, radius=36, minimum=60, threshold=0.0):
    """Select high-motion/cut transitions close to target frame boundaries.

    The seam at index i begins with frame i. Looking at the change between
    frames i-1 and i, natural shot cuts are good candidates to hide resetting
    inter-frame prediction state. The algorithm never changes any frames.
    """
    n=len(scores)
    if target_frames<1 or radius<0 or minimum<1:
        raise ValueError('Invalid segmentation parameters')
    if n==0:return []
    boundaries=[]
    center=target_frames
    while center<n:
        lo=max(center-radius,(boundaries[-1]+minimum) if boundaries else minimum)
        hi=min(center+radius,n-minimum)
        if lo>hi:
            # Preserve minimum final chunk length: skip this split.
            center+=target_frames
            continue
        # Prefer significant cuts or motion, while gently discouraging large
        # deviations in the nominal chunk size.
        selected=max(range(lo,hi+1),key=lambda i:(scores[i]-0.015*abs(i-center),-abs(i-center)))
        if scores[selected]>=threshold:
            boundaries.append(selected)
        center+=target_frames
    return boundaries


def split_y4m(source, dest, boundaries):
    indices=set(boundaries)
    chunks=[]; total=0; writer=None
    with open(source,'rb') as f:
        header=f.readline()
        w=re.search(rb'\bW(\d+)\b',header);h=re.search(rb'\bH(\d+)\b',header)
        c=re.search(rb'\bC([^\s]+)',header)
        if not (header.startswith(b'YUV4MPEG2 ') and w and h and c and
                c[1] in (b'420',b'420jpeg',b'420mpeg2',b'420paldv')):
            raise ValueError('Expected 8-bit YUV420 Y4M source')
        frame_bytes=int(w[1])*int(h[1])*3//2
        try:
            while True:
                tag=f.readline()
                if not tag:break
                if not tag.startswith(b'FRAME'):raise ValueError('Bad frame tag')
                raw=f.read(frame_bytes)
                if len(raw)!=frame_bytes:raise ValueError('Truncated frame')
                if total==0 or total in indices:
                    if writer:writer.close()
                    path=dest/f'part_{len(chunks):04d}.y4m'
                    writer=path.open('wb');writer.write(header);chunks.append(path)
                writer.write(tag);writer.write(raw);total+=1
        finally:
            if writer:writer.close()
    if not total:raise ValueError('Source has no frames')
    if any(x<=0 or x>=total for x in boundaries):raise ValueError('Seams out of bounds')
    return chunks,total,frame_bytes


def normalized_video(ffmpeg, source, path, a):
    outw=a.eye_width*(2 if a.stereo_sbs else 1)
    common=[ffmpeg,'-y','-nostdin','-hide_banner','-loglevel','error','-i',source,
            '-map_metadata','-1']
    if a.stereo_sbs:
        sar='2' if a.sbs_type=='half' else '1'
        eye=(f'setsar={sar},scale={a.eye_width}:{a.eye_height}:'
             f'force_original_aspect_ratio=decrease:in_range=auto:out_range=tv:'
             f'flags=lanczos:reset_sar=1,'
             f'pad={a.eye_width}:{a.eye_height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
        filt=('[0:v:0]split=2[left][right];'
              '[left]crop=iw/2:ih:0:0,'+eye+'[l];'
              '[right]crop=iw/2:ih:iw/2:0,'+eye+'[r];'
              '[l][r]hstack=inputs=2,format=yuv420p[vid]')
        common+=['-filter_complex',filt,'-map','[vid]']
    else:
        vf=(f'scale={a.eye_width}:{a.eye_height}:'
            'force_original_aspect_ratio=decrease:in_range=auto:out_range=tv:'
            'flags=lanczos:reset_sar=1,'
            f'pad={a.eye_width}:{a.eye_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p')
        common+=['-map','0:v:0','-vf',vf]
    # FPS and scaling done ONCE, before segment splitting; no per-chunk
    # motion interpolation or independent timebase rounding is introduced.
    call(common+['-an','-r',a.fps,'-c:v','rawvideo','-pix_fmt','yuv420p',
                 '-f','yuv4mpegpipe',path])
    return outw,a.eye_height


def encode_chunk(config):
    ffmpeg,source,output,a=config
    env={**os.environ,'MOBI_SUBME':str(a.subme),'MOBI_SKIP':str(a.skip)}
    t=time.monotonic()
    argv=[ffmpeg,'-y','-nostdin','-hide_banner','-loglevel','error',
          '-stats_period','2','-progress','pipe:1',
          '-f','yuv4mpegpipe','-i',source,'-an','-c:v','mobiclip',
          '-mobiclip','1','-qp',a.qp,'-preset',a.preset,
          '-me_method',a.me,'-g',a.gop,'-mo_layout',4 if a.stereo_sbs else 6,
          '-f','moflex',output]
    # Progress is read in each Python worker thread, not in the parent.
    # FFmpeg's normal low-level errors go into a temporary file to avoid
    # blocking a child process on a full stderr pipe.
    with tempfile.TemporaryFile(mode='w+t',encoding='utf-8') as err:
        p=subprocess.Popen(list(map(str,argv)),env=env,stdout=subprocess.PIPE,
                           stderr=err,text=True,errors='replace')
        latest_frame=0;last_print=t
        for line in p.stdout:
            if line.startswith('frame='):
                try:latest_frame=int(line.split('=',1)[1].strip())
                except ValueError:pass
            if line.startswith('progress=') and time.monotonic()-last_print>=12:
                print(f'    {Path(output).name}: frame {latest_frame}, '
                      f'{time.monotonic()-t:.0f}s elapsed',flush=True)
                last_print=time.monotonic()
        rc=p.wait()
        if rc:
            err.seek(0)
            raise RuntimeError(f'Chunk {output} failed ({rc}): {err.read()[-2500:]}')
    return str(output),round(time.monotonic()-t,3)


def ffconcat_path(x):
    return "file '"+str(x.resolve()).replace('\\','/').replace("'","'\\''")+"'\n"


def run(a):
    if not a.source.is_file() or not a.ffmpeg.is_file() or not a.ffprobe.is_file():
        raise ValueError('One or more input/FFmpeg paths not found')
    if a.source.resolve()==a.output.resolve():raise ValueError('Source=output')
    if a.output.exists() and not a.overwrite:raise ValueError('Output already exists; use --overwrite')
    if not (1<=a.jobs<=32 and a.chunk_frames>=2 and a.radius>=0 and a.min_segment>=1):
        raise ValueError('Invalid worker or segmentation parameters')
    if a.scene_threshold<0:raise ValueError('Invalid scene threshold')
    if a.eye_width%2 or a.eye_height%2:raise ValueError('YUV420 eye dimensions must be even')
    if not (12<=a.qp<=63 and 2<=a.subme<=9):raise ValueError('Invalid encoder QP or subme')
    if a.stereo_sbs and a.eye_width*2>1024:raise ValueError('Unusually large packed stereo width')
    if not re.search(r'(?m)^\s*D\s+concat\s',call([a.ffmpeg,'-hide_banner','-demuxers'],capture=True)):
        raise ValueError('MobiPEG FFmpeg must support concat demuxer')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    scratch=Path(tempfile.mkdtemp(prefix='mobipeg-v3-'))
    t0=time.monotonic();stages={}
    try:
        norm=scratch/'normalized.y4m'
        expected_width,expected_height=normalized_video(a.ffmpeg,a.source,norm,a)
        stages['normalize_seconds']=round(time.monotonic()-t0,3)
        # Scan without using a codec: no bitstream or filter modifications.
        with norm.open('rb') as fp:
            header=fp.readline()
        w=int(re.search(rb'\bW(\d+)\b',header)[1]);h=int(re.search(rb'\bH(\d+)\b',header)[1]);frame_bytes=w*h*3//2
        if (w,h)!=(expected_width,expected_height):raise ValueError('Unexpected packed video shape')
        if a.seam_mode=='gop':
            if a.gop <= 0 or a.chunk_frames % a.gop:
                raise ValueError('GOP-aligned mode needs --chunk-frames to be a positive multiple of --gop')
            # Skip the otherwise expensive per-frame pixel-difference scan.
            nframes=count_y4m_frames(norm,frame_bytes)
            scores=None
        else:
            scores=change_scores(norm,frame_bytes)
            nframes=len(scores)
        nominal=list(range(a.chunk_frames,nframes,a.chunk_frames))
        if a.seam_mode in ('adaptive','strict'):
            boundaries=choose_seams(scores,a.chunk_frames,a.radius,a.min_segment,
                                    a.scene_threshold if a.seam_mode=='strict' else 0.0)
        else:boundaries=nominal
        chunks,total,_=split_y4m(norm,scratch,boundaries)
        if total!=nframes:raise ValueError('Segmentation frame-count mismatch')
        stages['analysis_split_seconds']=round(time.monotonic()-t0-stages['normalize_seconds'],3)
        print(f'{total} normalized {"stereo" if a.stereo_sbs else "2D"} frames; '
              f'{len(chunks)} segments; {a.jobs} workers; '
              f'seams={boundaries}; mode={a.seam_mode}',flush=True)
        chunkouts=[scratch/f'chunk_{i:04}.moflex' for i in range(len(chunks))]
        ts=time.monotonic();times=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
            fs=[pool.submit(encode_chunk,(a.ffmpeg,source,out,a)) for source,out in zip(chunks,chunkouts)]
            for future in concurrent.futures.as_completed(fs):
                result,secs=future.result();times.append(secs)
                print(f'  encoded {Path(result).name}: {secs:.2f}s',flush=True)
        stages['parallel_encode_seconds']=round(time.monotonic()-ts,3)
        t=time.monotonic()
        lst=scratch/'input.ffconcat'
        lst.write_text('ffconcat version 1.0\n'+''.join(map(ffconcat_path,chunkouts)),encoding='utf-8')
        joined=scratch/'joined.moflex'
        layout=4 if a.stereo_sbs else 6
        call([a.ffmpeg,'-y','-nostdin','-hide_banner','-loglevel','error',
              '-f','concat','-safe','0','-i',lst,'-map','0:v:0',
              '-c:v','copy','-mo_layout',layout,'-f','moflex',joined])
        jw,jh,jf=probe_video(a.ffprobe,joined)
        if (jw,jh,jf)!=(w,h,total):
            raise RuntimeError(f'Joined stream invalid: {jw}x{jh} {jf} frames; expected {w}x{h} {total}')
        stages['concat_validate_seconds']=round(time.monotonic()-t,3)
        t=time.monotonic()
        joined_hash, joined_count=video_packet_hash(a.ffprobe,joined)
        if joined_count!=total:raise RuntimeError('Joined packet count mismatch')
        if a.no_audio:shutil.copy2(joined,a.output)
        else:
            # Stop audio at the exact video duration before ADPCM rounding.
            # Prior MobiPEG users measured ~52 ms excess audio tail. With
            # -t, MOFLEX output can end within one 256-sample ADPCM block.
            clip_duration=total/float(Fraction(a.fps))
            call([a.ffmpeg,'-y','-nostdin','-hide_banner','-loglevel','error',
                  '-i',joined,'-i',a.source,'-map','0:v:0','-map','1:a:0?',
                  '-c:v','copy','-c:a','pcm_s16le','-mo_audio','adpcm',
                  '-mo_layout',layout,'-t',f'{clip_duration:.7f}','-f','moflex',a.output])
        # Full validation still runs, but independent decode/frame-count/hash
        # passes can use otherwise idle CPU cores after the encoders finish.
        # For video-only output shutil.copy2 is a literal byte copy, so there
        # is no need to hash those exact same packets a second time.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as validation_pool:
            decode_future=validation_pool.submit(assert_full_decode,a.ffmpeg,a.output)
            dimensions_future=validation_pool.submit(probe_video,a.ffprobe,a.output)
            if a.no_audio:
                output_hash,output_count=joined_hash,joined_count
                hash_future=None
            else:
                hash_future=validation_pool.submit(video_packet_hash,a.ffprobe,a.output)
            decoded_md5=decode_future.result()
            ow,oh,on=dimensions_future.result()
            if hash_future is not None:
                output_hash,output_count=hash_future.result()
        if (joined_hash,joined_count)!=(output_hash,output_count):
            raise RuntimeError('Final remux changed compressed video payloads')
        if (ow,oh,on)!=(w,h,total):raise RuntimeError('Final stream frames/dimensions mismatch')
        layout_check=moflex_layout(a.output)
        if layout_check is None or (layout_check['width'],layout_check['height'],layout_check['layout'])!=(w,h,layout):
            raise RuntimeError(f'MOFLEX image layout metadata missing/wrong: {layout_check}; '
                               f'expected {w}x{h} layout={layout}')
        stages['audio_validate_seconds']=round(time.monotonic()-t,3)
        elapsed=round(time.monotonic()-t0,3)
        # Plain frames sourced from Y4M as a convenience for subsequent QA:
        # record nominal and actual seam positions and representative change
        # magnitudes, rather than asserting that all boundaries are invisible.
        result={'source':str(a.source),'output':str(a.output),'bytes':a.output.stat().st_size,
                'frames':total,'width':w,'height':h,'fps_total':round(total/elapsed,2),
                'fps_parallel_encode_only':round(total/stages['parallel_encode_seconds'],2),
                'validated_full_decode':True,'concurrent_validation':True,
                'elapsed_seconds':elapsed,'jobs':a.jobs,'segments':len(chunks),
                'stereo_sbs':a.stereo_sbs,'sbs_type':a.sbs_type if a.stereo_sbs else None,
                'mo_layout':layout,'verified_header':layout_check,
                'copied_video_sha256':output_hash,'decoded_video_md5':decoded_md5,
                'audio_trimmed_to_video_duration':not a.no_audio,'seam_mode':a.seam_mode,'seams':boundaries,
                'nominal_seams':nominal,'source_change_at_seams':
                    ([round(scores[x],3) for x in boundaries] if scores is not None else None),
                'video_qp':a.qp,'subme':a.subme,'skip':a.skip,'gop':a.gop,
                'bit_exact_to_sequential':False,'hardware_validated':False,
                'stage_seconds':stages,'chunk_encode_seconds':times}
        report=a.report or a.output.with_suffix('.parallel.json')
        report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)
        return result
    except BaseException:
        print('Encoding stopped; scratch retained at '+str(scratch),file=sys.stderr)
        raise
    finally:
        if not a.keep_temp and 'result' in locals() and result.get('frames'):
            shutil.rmtree(scratch,ignore_errors=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--ffprobe',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--chunk-frames',type=int,default=120)
    parser.add_argument('--seam-mode',choices=['strict','adaptive','fixed','gop'],default='strict',
                        help='Strict: near scene changes; adaptive: prefer activity; fixed: exact chunk lengths; gop: exact GOP-aligned chunks without a scene-analysis pass')
    parser.add_argument('--scene-threshold',type=float,default=12.0,
                        help='For strict: minimum sampled luma mean absolute change for new GOP')
    parser.add_argument('--radius',type=int,default=36,help='Max displacement of a seam in frames')
    parser.add_argument('--min-segment',type=int,default=60,help='Minimum number of frames per segment')
    parser.add_argument('--eye-width',type=int,default=400)
    parser.add_argument('--eye-height',type=int,default=240)
    parser.add_argument('--stereo-sbs',action='store_true',help='Source is side-by-side; output 3D MOFLEX layout=4')
    parser.add_argument('--sbs-type',choices=['full','half'],default='full',help='Half SBS doubles horizontal SAR of each eye')
    parser.add_argument('--fps',default='30000/1001')
    parser.add_argument('--qp',type=int,default=12)
    parser.add_argument('--subme',type=int,default=9)
    parser.add_argument('--skip',type=int,default=0)
    parser.add_argument('--preset',default='medium')
    parser.add_argument('--me',default='hex')
    parser.add_argument('--gop',type=int,default=60)
    parser.add_argument('--no-audio',action='store_true')
    parser.add_argument('--overwrite',action='store_true')
    parser.add_argument('--keep-temp',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    try:run(args)
    except (RuntimeError,ValueError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':sys.exit(main())
