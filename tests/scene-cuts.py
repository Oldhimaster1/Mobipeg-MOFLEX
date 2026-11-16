import json,subprocess,re,math
from pathlib import Path
root=Path(__file__).resolve().parent.parent;ff=str(root/'native/local/bin/ffmpeg');rows=json.loads((root/'reports/quality-analysis.json').read_text());report=[]
for row in rows:
 if row['name'] not in ['anime-full','avatar-full-3d']:continue
 s=row['settings'];num,*den=s['fps'].split('/');fps=float(num)/(float(den[0]) if den else 1);coded=fps*(2 if s['mode']!='2d' else 1)
 p=subprocess.run([ff,'-hide_banner','-v','info','-i',row['input'],'-vf',f"fps={s['fps']},select=gt(scene\\,0.35),showinfo",'-an','-f','null','-'],capture_output=True,check=True,timeout=300)
 times=[float(t)for t in re.findall(r'pts_time:\s*([\d.]+)',p.stderr.decode(errors='replace'))];values={}
 for kind in ['native','wasm']:
  text=(root/'reports'/f'{row["name"]}-{kind}-source-psnr.txt').read_text();values[kind]={int(m[0]):float(m[1]) for m in re.findall(r'n:(\d+).*?psnr_avg:([\d.inf]+)',text)}
 cuts=[]
 for t in times:
  frame=round(t*coded)+1;window={kind:[values[kind].get(n,math.inf)for n in range(max(1,frame-2),frame+5)]for kind in values};delta=[b-a for a,b in zip(window['native'],window['wasm'])if math.isfinite(a)and math.isfinite(b)];cuts.append(dict(time=t,codedFrame=frame,minWasmMinusNativePSNR=min(delta)if delta else None,maxWasmMinusNativePSNR=max(delta)if delta else None))
 report.append(dict(name=row['name'],threshold=.35,sceneCuts=cuts));(root/'reports/scene-cuts.json').write_text(json.dumps(report,indent=2));print(row['name'],len(cuts),'cuts')
