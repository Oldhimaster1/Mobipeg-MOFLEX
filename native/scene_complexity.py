"""The same bounded source-luma sampler and weights as complexity.mjs."""
import math,subprocess

def measure_complexity(data,width=64,height=36):
 area=width*height;frames=len(data)//area
 if frames<1 or frames>8 or len(data)%area:raise ValueError('Incomplete scene-analysis sample')
 spatial=temporal=edges=0
 for f in range(frames):
  for y in range(height):
   for x in range(width):
    i=f*area+y*width+x
    if x:spatial+=abs(data[i]-data[i-1]);edges+=1
    if y:spatial+=abs(data[i]-data[i-width]);edges+=1
    if f:temporal+=abs(data[i]-data[i-area])
 texture=spatial/(edges*255);motion=temporal/((frames-1)*area*255) if frames>1 else 0
 return dict(texture=texture,motion=motion,score=.025+texture+2*motion)

def analyze_complexity(encoder,source,ranges,callback):
 rows=[]
 end=ranges[-1][0]+ranges[-1][1]
 for index,(start,seconds,frames) in enumerate(ranges):
  samples=[]
  for fraction in (1/3,2/3):
   stamp=max(0,min(start+max(0,seconds-.5)*fraction,end-.5))
   data=subprocess.check_output([encoder,'-v','error','-nostdin','-threads','1','-filter_threads','1','-filter_complex_threads','1','-ss',f'{stamp:.8f}','-i',str(source),
    '-map','0:v:0','-an','-vf','fps=8,scale=64:36:flags=area,format=gray','-frames:v','4','-c:v','rawvideo','-threads','1','-f','rawvideo','pipe:1'])
   if data:samples.append(measure_complexity(data))
  texture=sum(x['texture'] for x in samples)/(len(samples) or 1);motion=sum(x['motion'] for x in samples)/(len(samples) or 1)
  rows.append(dict(start=start,seconds=seconds,samples=len(samples),texture=texture,motion=motion,score=.025+texture+2*motion))
  callback(f'Analyzing scene texture and motion: {index+1}/{len(ranges)}')
 return dict(version=1,clips=rows)
