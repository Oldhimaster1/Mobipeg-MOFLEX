#!/usr/bin/env python3
"""Assemble measured V8 quality-preserving 3DS interleaved stereo, verify video+ADPCM."""
from pathlib import Path
import json,hashlib,subprocess,collections,time,sys
D=Path('/mnt/data/MobiPEG_V8_Research')
sel=json.loads((D/'V8_PSY_SWEEP_11_selected.json').read_text());N=sum(z['coded_frames'] for z in sel)
assert N==4826 and sum(z['video_bytes'] for z in sel)<15810029
ff=Path('/mnt/data/MobiPEG_V7_Engineering/bench/ffmpeg_v7_lambda')
fp=Path('/mnt/data/MobiPEG_V7_Release/MobiPEG_Custom_V7/local/bin/ffprobe')
if not fp.exists():fp=Path('/usr/bin/ffprobe')
manifest=D/'V8_TextureGuard.ffconcat'
manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{Path(x['file']).resolve()}'\nduration {x['coded_frames']/48:.9f}\n" for x in sel))
audio=Path('/mnt/data/MobiPEG_V5_RateControl/tests/adaptive/audio_44100_stereo.pcm')
final=D/'Avatar_3D_MobiPEG_V8_TextureGuard.moflex'
cmd=[str(ff),'-nostdin','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(manifest),'-f','s16le','-ar','44100','-ac','2','-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le','-mo_audio','adpcm','-mo_layout','0','-mo_interleave_input_double_rate','1','-f','moflex',str(final)]
t0=time.monotonic();r=subprocess.run(cmd,capture_output=True,timeout=150)
if r.returncode:raise RuntimeError('mux failed: '+r.stderr.decode(errors='replace')[-1400:])
print('MUX',final,final.stat().st_size,'seconds',round(time.monotonic()-t0,1),flush=True)
packets=subprocess.run([str(fp),'-v','error','-show_packets','-show_entries','packet=stream_index,size','-of','csv=p=0',str(final)],capture_output=True,text=True,timeout=90)
if packets.returncode:raise RuntimeError('bad packet probe')
n=collections.Counter();b=collections.Counter()
for line in packets.stdout.splitlines():
 col=line.split(',')
 if len(col)>=2 and col[0].isdigit() and col[1].isdigit():n[int(col[0])]+=1;b[int(col[0])]+=int(col[1])
print('COUNTS',dict(n),'BYTES',dict(b),flush=True)
assert n[0]==N and n[2]==N,(n,N)
assert b[0]==sum(x['video_bytes'] for x in sel)
for mapspec in ['0:v:0','0:a:0']:
 cmd=['/usr/bin/ffmpeg','-hide_banner','-nostdin','-loglevel','error','-xerror','-i',str(final),'-map',mapspec,'-f','null','-']
 r=subprocess.run(cmd,capture_output=True,timeout=180)
 if r.returncode:raise RuntimeError(f'decode failed {mapspec}: '+r.stderr.decode(errors='replace')[-500:])
 print('FULL DECODE PASS',mapspec,flush=True)
report={'file':str(final),'size_bytes':final.stat().st_size,'nintendo_reference_bytes':20588544,'V7_bytes':20578304,'video_frames_coded':N,'stereo_pairs':N//2,'GOPs':len(sel),'source_eyes_per_second':24,'layout':0,'video_payload_bytes':b[0],'audio_payload_bytes':b[2],'codec':'MobiClip/MOFLEX','sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'software_decoding':'PASS','old3ds_hardware_playback':'UNTESTED'}
(D/'V8_VALIDATION.json').write_text(json.dumps(report,indent=2))
print('VERIFIED OUTPUT',json.dumps(report,indent=2),flush=True)
