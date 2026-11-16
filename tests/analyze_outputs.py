"""Independent decode, descriptor, quality, audio and seek checks using native FFmpeg."""
import json,subprocess,re,hashlib,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'native'))
import MobiPEG_Studio_V15 as studio
FF=str(ROOT/'native/local/bin/ffmpeg');FP=str(ROOT/'native/local/bin/ffprobe')

def call(args):
 r=subprocess.run([FF,'-hide_banner','-nostdin',*args],capture_output=True,timeout=600)
 if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace')[-2000:])
 return r

def descriptor(path):
 b=Path(path).read_bytes()[:256];i=b.find(bytes((3,13,0,0)))
 if i<0:raise ValueError('missing descriptor')
 d=b[i+4:i+15]
 return dict(layout=d[10],displayNumerator=int.from_bytes(d[:2],'big'),displayDenominator=int.from_bytes(d[2:4],'big'),width=int.from_bytes(d[4:6],'big'),height=int.from_bytes(d[6:8],'big'))

results=json.loads(Path(os.environ.get('MOBIPEG_BENCHMARKS',str(ROOT/'reports/benchmarks.json'))).read_text())
for case in results:
 if not case.get('pass'):continue
 s=case['settings'];w,h=map(int,s['resolution'].split('x'));vf,_=studio.video_filters(s['mode'],w,h,s['fps'],s['filter'])
 graph=(f'[0:v:0]{vf[1]}[ref]' if s['mode']=='2d' else vf[1].replace('[vid]','[ref]'))
 analysis={}
 for kind in ['native','wasm']:
  movie=case[kind]['path'];item={'descriptor':descriptor(movie)}
  for metric in ['psnr','ssim']:
   stats=ROOT/'reports'/f'{case["name"]}-{kind}-source-{metric}.txt'
   r=call(['-v','info','-i',case['input'],'-i',movie,'-filter_complex',graph+f';[ref][1:v:0]{metric}=stats_file={stats}[metric]','-map','[metric]','-an','-f','null','-'])
   log=r.stderr.decode(errors='replace')
   pattern=r'average:([\d.inf]+)' if metric=='psnr' else r'All:([\d.]+)'
   matches=re.findall(pattern,log);item[metric]=matches[-1] if matches else log[-500:]
  if case[kind]['audio']:
   pcm=call(['-v','error','-xerror','-i',movie,'-map','0:a:0','-ac','2','-ar','44100','-f','s16le','-']).stdout
   item['pcmSHA256']=hashlib.sha256(pcm).hexdigest();item['audioSeconds']=len(pcm)/4/44100;item['audioDurationErrorSeconds']=item['audioSeconds']-case[kind]['duration']
  seeks=[]
  for t in [0,.25,max(0,case[kind]['duration']-.25)]:
   r=call(['-v','error','-ss',str(t),'-i',movie,'-frames:v','1','-an','-f','framemd5','-'])
   seeks.append({'time':t,'decoded':any(x and not x.startswith('#') for x in r.stdout.decode().splitlines())})
  item['seeks']=seeks
  if case['name'].startswith('eyes-'):
   raw=call(['-v','error','-i',movie,'-frames:v','4','-pix_fmt','rgb24','-f','rawvideo','-']).stdout
   pixels=[]
   for i in range(4):
    off=(i*w*h+(h//2*w+w//2))*3;pixels.append(list(raw[off:off+3]))
   item['eyeCenterRGB']=pixels;item['eyeOrderPass']=all(p[0]>p[2]+80 if i%2==0 else p[2]>p[0]+80 for i,p in enumerate(pixels))
  analysis[kind]=item
 analysis['decodedAudioMatch']=analysis['native'].get('pcmSHA256')==analysis['wasm'].get('pcmSHA256');case['analysis']=analysis
 Path(os.environ.get('MOBIPEG_ANALYSIS',str(ROOT/'reports/quality-analysis.json'))).write_text(json.dumps(results,indent=2))
 print(case['name'],json.dumps(analysis))
