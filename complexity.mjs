// Source-luma measurements, not file-size or duration proxies. At most four
// 64x36 gray frames per sample; no movie-sized analysis buffer.
export function measureComplexity(bytes,width=64,height=36){
  const area=width*height,frames=bytes.length/area;
  if(!Number.isInteger(frames)||frames<1||frames>8)throw Error('Incomplete scene-analysis sample');
  let spatial=0,temporal=0,edges=0;
  for(let f=0;f<frames;f++)for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const i=f*area+y*width+x;
    if(x){spatial+=Math.abs(bytes[i]-bytes[i-1]);edges++;}
    if(y){spatial+=Math.abs(bytes[i]-bytes[i-width]);edges++;}
    if(f)temporal+=Math.abs(bytes[i]-bytes[i-area]);
  }
  const texture=spatial/(edges*255),motion=frames>1?temporal/((frames-1)*area*255):0;
  return {texture,motion,score:.025+texture+2*motion};
}
export function validComplexity(analysis,clips){
  return analysis?.version===1&&Array.isArray(analysis.clips)&&analysis.clips.length===clips.length&&
    analysis.clips.every((row,i)=>row&&Number.isFinite(row.start)&&Number.isFinite(row.seconds)&&['texture','motion'].every(k=>Number.isFinite(row[k])&&row[k]>=0&&row[k]<=1)&&
      Number.isFinite(row.score)&&Math.abs(row.score-(.025+row.texture+2*row.motion))<1e-9&&
      Math.abs(row.start-clips[i].start)<1e-6&&Math.abs(row.seconds-clips[i].seconds)<1e-6);
}
export async function analyzeComplexity(source,clips,run,notify=()=>{}){
  const measured=[];
  const end=clips.at(-1).start+clips.at(-1).seconds;
  for(const [index,clip] of clips.entries()){
    const samples=[];
    for(const fraction of [1/3,2/3]){
      const start=Math.max(0,Math.min(clip.start+Math.max(0,clip.seconds-.5)*fraction,end-.5));
      const result=await run(['-hide_banner','-nostdin','-v','error','-threads','1','-filter_threads','1','-filter_complex_threads','1','-ss',start.toFixed(8),'-i','/input/source',
        '-map','0:v:0','-an','-vf','fps=8,scale=64:36:flags=area,format=gray','-frames:v','4',
        '-c:v','rawvideo','-threads','1','-f','rawvideo','/complexity.gray'],{source},'/complexity.gray');
      const bytes=new Uint8Array(await result.blob.arrayBuffer());
      if(bytes.length)samples.push(measureComplexity(bytes));
    }
    const texture=samples.reduce((sum,sample)=>sum+sample.texture,0)/(samples.length||1),motion=samples.reduce((sum,sample)=>sum+sample.motion,0)/(samples.length||1);
    measured.push({start:clip.start,seconds:clip.seconds,samples:samples.length,texture,motion,score:.025+texture+2*motion});
    notify({stage:'Analyzing scene texture and motion · '+(index+1)+'/'+clips.length,fraction:(index+1)/clips.length});
  }
  return {version:1,clips:measured};
}
export const audioBudgetRate=codec=>codec==='fastaudio'?15000:49500;
