#!/usr/bin/env python3
"""Full-frame, both-eye MobiPEG V8 quality audit vs same normalized Avatar input."""
import csv,json,math,hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFont
from skimage.metrics import structural_similarity as ssim
R=Path('/mnt/data');D=R/'MobiPEG_V8_Research';N=4826;W,H=400,224;PIX=W*H;FB=PIX*3//2
paths={'Source':R/'MobiPEG_V5_RateControl/tests/avatar_eyes_24fps.yuv','Official Nintendo':R/'MobiPEG_V5_RateControl/tests/full_decoded_official.yuv','MobiPEG V7':R/'MobiPEG_V7_Engineering/bench/V7_decoded_400x224_eyes.yuv','MobiPEG V8':D/'V8_full_decoded.yuv'}
raw={k:np.memmap(v,dtype='u1',mode='r').reshape(N,FB) for k,v in paths.items()}
cutpairs=json.loads((R/'MobiPEG_V7_Engineering/bench/scenes.json').read_text())['cuts'];cutframes={j for c in cutpairs for j in range(2*c,min(N,2*c+12))}
# independent of optimization cost approximations; actual full output decoded and compared
sample={j for k in range(0,N,12) for j in (k,k+1) if j<N}
sample.update(range(min(N,4)));sample.update(cutframes)
score={name:dict(count=0,ysq=0.,usq=0.,vsq=0.,left_sq=0.,right_sq=0.,left_count=0,right_count=0,ssims=[],ssim_l=[],ssim_r=[],edge_error=0.,edge_count=0,cut_errors=[],worstframe=[],persecond=defaultdict(list),bias=0.) for name in paths if name!='Source'}
rows=[]
font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';font=ImageFont.truetype(font_path,14)
# Evaluate samples after confirmed scene changes rather than randomly cherry-picked frames
frame_ids=[2*int(c)+e for c in (646,1019,1228,1702,1906,2068) for e in (0,1)]
frame_ids=[x for x in frame_ids if x<N]
cols=['Source','Official Nintendo','MobiPEG V7','MobiPEG V8']
chart=Image.new('RGB',(4*(W+10)+20,len(frame_ids)*(H+40)+65),'#131923');drawer=ImageDraw.Draw(chart)
for ci,name in enumerate(cols):drawer.text((15+ci*(W+10),12),name,font=font,fill='white')
for start in range(0,N,48):
 end=min(start+48,N);a=raw['Source'][start:end]
 Y=a[:,:PIX].astype(np.int16);U=a[:,PIX:PIX+PIX//4].astype(np.int16);V=a[:,PIX+PIX//4:].astype(np.int16)
 yy=Y.reshape(-1,H,W)
 grad=(np.abs(np.diff(yy,axis=2,prepend=yy[:,:,:1]))>24)|(np.abs(np.diff(yy,axis=1,prepend=yy[:,:1,:]))>24)
 for name in cols[1:]:
  b=raw[name][start:end];difY=(Y-b[:,:PIX].astype(np.int16)).astype(np.float32)
  fm=(difY**2).mean(axis=1);s=score[name]
  s['ysq']+=float((difY**2).sum());s['usq']+=float(((U-b[:,PIX:PIX+PIX//4].astype(np.int16))**2).sum());s['vsq']+=float(((V-b[:,PIX+PIX//4:].astype(np.int16))**2).sum())
  s['count']+=len(fm);s['left_sq']+=float(fm[(start+np.arange(len(fm)))%2==0].sum());s['right_sq']+=float(fm[(start+np.arange(len(fm)))%2==1].sum());s['left_count']+=sum((start+np.arange(len(fm)))%2==0);s['right_count']+=sum((start+np.arange(len(fm)))%2==1)
  sq=difY.reshape(-1,H,W)**2;s['edge_error']+=float(sq[grad].sum());s['edge_count']+=int(np.count_nonzero(grad))
  s['worstframe'].extend(fm.tolist());s['bias']+=float(difY.sum())
  for j,mse in enumerate(fm):
   idx=start+j;s['persecond'][idx//48].append(float(mse))
   if idx in cutframes:s['cut_errors'].append(float(mse))
   if idx in sample:
    ai=yy[j].astype(np.uint8);bi=b[j,:PIX].reshape(H,W)
    ss=float(ssim(ai,bi,data_range=255));s['ssims'].append(ss);s['ssim_l' if idx%2==0 else 'ssim_r'].append(ss)
# Chart RGB frames from original reconstructed YUV
for row,idx in enumerate(frame_ids):
 sec=idx/48
 drawer.text((15,52+row*(H+40)),f'{sec:.3f}s  {"Left" if idx%2==0 else "Right"} eye — scene cut',font=font,fill='#ccd9e6')
 for ci,name in enumerate(cols):
  pixels=np.asarray(raw[name][idx]).reshape(H*3//2,W)
  pic=cv2.cvtColor(pixels,cv2.COLOR_YUV2RGB_I420)
  chart.paste(Image.fromarray(pic), (15+ci*(W+10),75+row*(H+40)))
chart.save(D/'Avatar_V8_Official_V7_V8_SceneCuts.png',optimize=True)
summary={}
for name,s in score.items():
 y=s['ysq']/(s['count']*PIX);u=s['usq']/(s['count']*PIX//4);v=s['vsq']/(s['count']*PIX//4)
 psnr=lambda mse:10*math.log10(65025/max(1e-10,mse))
 fr=np.array(s['worstframe']);p05=np.percentile(10*np.log10(65025/np.maximum(fr,1e-8)),5)
 summary[name]={'PSNR_Y_dB':psnr(y),'PSNR_U_dB':psnr(u),'PSNR_V_dB':psnr(v),'SSIM_both_eyes_sampled':float(np.mean(s['ssims'])),'SSIM_left':float(np.mean(s['ssim_l'])),'SSIM_right':float(np.mean(s['ssim_r'])),'source_edge_MSE':s['edge_error']/max(1,s['edge_count']),'worst12p5_frame_MSE':float(np.sort(fr)[-max(1,N//8):].mean()),'p05_frame_PSNR_dB':float(p05),'post_cut_MSE':float(np.mean(s['cut_errors'])),'Y_offset_mean':s['bias']/(s['count']*PIX),'eye_frames':s['count']}
 print(name,json.dumps(summary[name],indent=2),flush=True)
for sec in range(math.ceil(N/48)):
 row={'second':sec}
 for name,s in score.items():
  dat=s['persecond'].get(sec)
  row[name+'_Y_MSE']=float(np.mean(dat)) if dat else None
 rows.append(row)
with open(D/'V8_Per_Second_Error.csv','w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
(D/'V8_Quality_Summary.json').write_text(json.dumps(summary,indent=2))
# Charts
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,ax=plt.subplots(figsize=(13,5))
for name,s in score.items():ax.plot([r['second'] for r in rows],[r[name+'_Y_MSE'] for r in rows],label=name,alpha=.84)
ax.set_title('Avatar stereoscopic frame reconstruction error against one normalized source')
ax.set_xlabel('Trailer time (seconds)');ax.set_ylabel('Luma mean-squared error (lower is better)');ax.set_ylim(0,250);ax.grid(alpha=.15);ax.legend();fig.tight_layout();fig.savefig(D/'MSE_by_Second_V7_V8_Nintendo.png',dpi=140)
print('SAVED',D/'V8_Quality_Summary.json',flush=True)
