"""Explore perceptual/R-D tradeoffs using exact measured GOP candidates (no guessing)."""
from pathlib import Path
import json,sys,math
sys.path.insert(0,str(Path(__file__).parent))
from adaptive_stereo import SETTINGS, dp_allocate
p=Path('/mnt/data/MobiPEG_V5_RateControl/tests/adaptive');a=json.loads((p/'all_trials.json').read_text())
idx={(r['index'],r['option']):r for r in a}
groups=[[idx[(i,o[0])] for o in SETTINGS] for i in range(51)]
budget=15926292

def summ(sel):
 n=sum(r['coded_frames'] for r in sel)
 ym=sum(r['coded_frames']*r['mse_y'] for r in sel)/n
 ss=sum(r['coded_frames']*r['ssim_y'] for r in sel)/n
 return (sum(x['video_bytes'] for x in sel),10*math.log10(65025/ym),ss)
for w in [0,0.2,0.35,0.5,0.65,0.8,0.9,1]:
 # normalized dissimilarity metric 0..1 approx: MSE/100 SSIMloss/0.1
 temp=[[{**r,'cost':r['coded_frames']*((1-w)*r['mse_y']/50+w*(1-r['ssim_y'])*10)} for r in gr] for gr in groups]
 best=dp_allocate(temp,budget)
 b,ps,ss=summ(best)
 print(f'weight SSIM={w:.2f}: bytes {b:,}, psnr {ps:.4f}, SSIM {ss:.6f}, config:',{x:sum(r['option']==x for r in best) for x,_,_ in SETTINGS},flush=True)
