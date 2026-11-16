import subprocess,io,json,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(root/'native'));import MobiPEG_Studio_V15 as studio
ff=str(root/'native/local/bin/ffmpeg');rows={x['name']:x for x in json.loads((root/'reports/benchmarks.json').read_text())}
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15);small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12)
canvas=Image.new('RGB',(1256,964),'#f5f6f2');d=ImageDraw.Draw(canvas);d.text((22,18),'MobiPEG V15 • Aligned source / native / WebAssembly',font=font,fill='#192923')
for rowIndex,(name,t,eye) in enumerate([('anime-full',20,0),('avatar-full-3d',45,0),('avatar-full-3d',93,1)]):
 case=rows[name];s=case['settings'];fps=studio.rate_value(s['fps'])*(2 if s['mode']!='2d' else 1);n=round(t*fps)+eye
 vf,_=studio.video_filters(s['mode'],400,224,s['fps'],s['filter']);srcgraph=(f'[0:v]{vf[1]}[ref]' if s['mode']=='2d' else vf[1].replace('[vid]','[ref]'))+f';[ref]select=eq(n\\,{n})[frame]'
 y=60+rowIndex*300;d.text((22,y),f'{name} · {t}s'+(' · right eye' if eye else ''),font=small,fill='#52624f')
 for col,(label,args) in enumerate([('Aligned source',['-i',case['input'],'-filter_complex',srcgraph,'-map','[frame]']),('Native V15',['-i',case['native']['path'],'-vf',f'select=eq(n\\,{n})']),('WASM V15',['-i',case['wasm']['path'],'-vf',f'select=eq(n\\,{n})'])]):
  r=subprocess.run([ff,'-v','error','-filter_complex_threads','1','-filter_threads','1',*args,'-frames:v','1','-an','-c:v','rawvideo','-pix_fmt','rgb24','-threads','1','-f','rawvideo','-'],capture_output=True,timeout=180);
  if r.returncode:raise RuntimeError(r.stderr.decode())
  im=Image.frombytes('RGB',(400,224),r.stdout);x=22+col*412;d.text((x,y+23),label,font=small,fill='#326c4c');canvas.paste(im,(x,y+45))
out=root/'reports/Aligned_Source_Native_WASM.png';canvas.save(out);print(out)
