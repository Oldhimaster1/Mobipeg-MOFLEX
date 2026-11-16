"""Compare sought decoded frame pixels with linear decoding at the same time."""
import subprocess,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parent.parent;ff=str(root/'native/local/bin/ffmpeg')
rows=json.loads((root/'reports/benchmarks.json').read_text());results=[]
def raw(args):
 r=subprocess.run([ff,'-hide_banner','-nostdin','-v','error',*args,'-frames:v','1','-an','-pix_fmt','yuv420p','-f','rawvideo','-'],capture_output=True,timeout=180)
 if r.returncode:raise RuntimeError(r.stderr.decode()[-1500:])
 if not r.stdout:raise RuntimeError('No frame returned')
 return r.stdout
for row in rows:
 if row['name'] not in ['anime-full','avatar-full-3d','yip-full']:continue
 for kind in ['native','wasm']:
  p=row[kind]['path'];dur=row[kind]['duration']
  for t in [0.25,dur*.5,max(0,dur-0.25)]:
   # Explicit rounded microsecond request, matching FFmpeg's CLI time parser.
   t=round(t,6)
   sought=raw(['-ss',str(t),'-i',p]);linear=raw(['-i',p,'-vf',f"select=gte(t\\,{t})"])
   results.append(dict(name=row['name'],engine=kind,time=t,pass_=sought==linear,seekSHA256=hashlib.sha256(sought).hexdigest(),linearSHA256=hashlib.sha256(linear).hexdigest()))
   (root/'reports/seek-integrity.json').write_text(json.dumps(results,indent=2));print(results[-1])
if any(not x['pass_'] for x in results):raise SystemExit(1)
