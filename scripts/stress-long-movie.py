#!/usr/bin/env python3
"""Join generated six-second MOFLEX clips into long fixtures and decode them.

python3 scripts/stress-long-movie.py quiet.moflex complex.moflex output-dir
Inputs must be 400x240, 24 fps, 144 frames, stereo 48 kHz ADPCM. Repetition
exercises clocks, IO and boundaries, not movie scene variety or quality.
Use --audio-only to audit existing outputs; MOBIPEG_STRESS_MINUTES=120 selects
specific durations. Seeking uses the project's patched FFmpeg; full sequential
video/audio decoding and exact PCM comparison use independent system FFmpeg.
"""
import hashlib,json,os,subprocess,sys,time
from fractions import Fraction
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from moflex_join import join,inspect
quiet,complex_clip,destination=map(Path,sys.argv[1:4])
audio_only='--audio-only' in sys.argv[4:]
seek_decoder=os.environ.get('MOBIPEG_SEEK_FFMPEG',str(Path(__file__).resolve().parents[1]/'native/local/bin/ffmpeg'))
minutes_list=[int(n) for n in os.environ.get('MOBIPEG_STRESS_MINUTES','5,10,30,60,90,120').split(',')]
if any(n<=0 for n in minutes_list):raise ValueError('Durations must be positive minutes')
destination.mkdir(parents=True,exist_ok=True)

def audio_args(path):
    return ['ffmpeg','-v','error','-xerror','-nostdin','-i',str(path),'-map','0:a:0','-ac','2','-ar','48000','-f','s16le','pipe:1']

reference=[]
for path in [complex_clip,quiet]:
    pcm=subprocess.check_output(audio_args(path))
    if len(pcm)!=6*48000*4:raise RuntimeError('Fixture audio is not exactly six seconds')
    reference.append(hashlib.sha256(pcm).digest())

def audit_audio(path,minutes):
    process=subprocess.Popen(audio_args(path),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    total=0;segment=0;remaining=6*48000*4;digest=hashlib.sha256()
    while chunk:=process.stdout.read(65536):
        total+=len(chunk)
        while chunk:
            size=min(remaining,len(chunk));digest.update(chunk[:size]);chunk=chunk[size:];remaining-=size
            if not remaining:
                if digest.digest()!=reference[0 if segment%4==0 else 1]:raise RuntimeError('PCM changed at six-second range '+str(segment))
                segment+=1;remaining=6*48000*4;digest=hashlib.sha256()
    error=process.stderr.read().decode();code=process.wait()
    if code:raise RuntimeError(error)
    if total!=minutes*60*48000*4 or remaining!=6*48000*4:raise RuntimeError('Decoded audio duration mismatch')
    return {'audioSamplesPerChannel':total//4,'audioRangesByteVerified':segment}

report=[]
for minutes in minutes_list:
    output=destination/f'movie-{minutes}min.moflex'
    row={'minutes':minutes}
    if not audio_only:
        parts=[(complex_clip if i%4==0 else quiet,144) for i in range(minutes*10)]
        start=time.monotonic();join(parts,Fraction(24),output)
        row['joinSeconds']=time.monotonic()-start
        inspect(output,minutes*60*24)
        start=time.monotonic()
        result=subprocess.run(['ffmpeg','-v','error','-xerror','-nostdin','-threads','1','-i',str(output),
            '-map','0:v:0','-map','0:a:0','-progress','pipe:1','-nostats','-f','null','-'],capture_output=True,text=True,check=True)
        frames=[int(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('frame=')][-1]
        if frames!=minutes*60*24:raise RuntimeError(f'Frame count mismatch: {frames}')
        seeks=[max(0,minutes*60-3)]+([4294,4296] if minutes>=90 else [])
        for stamp in seeks:
            subprocess.run([seek_decoder,'-v','error','-xerror','-nostdin','-ss',str(stamp),'-i',str(output),
                '-t','1','-map','0:v:0','-map','0:a:0','-f','null','-'],check=True,capture_output=True)
        row.update(frames=frames,decodeAndSeekSeconds=time.monotonic()-start,seekSeconds=seeks)
    start=time.monotonic();row.update(audit_audio(output,minutes))
    row.update(bytes=output.stat().st_size,audioAuditSeconds=time.monotonic()-start,verified=True)
    report.append(row);print(json.dumps(row),flush=True)
    (destination/('audio-results.json' if audio_only else 'results.json')).write_text(json.dumps(report,indent=2)+'\n')
