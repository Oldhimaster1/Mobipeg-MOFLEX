import {allocateMovieBudget, appendMovieSegment, getCodedRate} from './movie.mjs?v=20261118f';
import {persistRange} from './checkpoints.mjs?v=20261118f';

// Balanced, frame-aligned timeline parts require no source chapters.
// A bounded worker pool reuses compiled WASM and recycles memory every four parts.
export function planBalancedMovieClips(seconds, settings, wanted=1) {
  if(!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid duration');
  const fps=getCodedRate(settings),eyes=settings.mode==='2d'?1:2;
  const gcd=(a,b)=>b?gcd(b,a%b):a;
  const raw=256*fps.num/gcd(48000*fps.den,256*fps.num);
  const quantum=raw/gcd(raw,eyes)*eyes;
  const lanes=Math.min(Math.max(1,Math.floor(wanted)),Math.max(1,Math.floor(seconds/4)));
  const frames=Math.floor(seconds*fps.num/(fps.den*eyes)+1e-7)*eyes;
  if(frames<eyes)throw Error('No complete video frame');
  const units=Math.floor(frames/quantum);
  const desired=Math.max(lanes,Math.ceil(seconds/(29*lanes))*lanes);
  const count=Math.min(desired,Math.max(1,units));
  const each=Math.floor(units/count),extra=units%count;
  let at=0;const clips=[];
  for(let i=0;i<count;i++){
    const n=(each+(i<extra?1:0))*quantum+(i===count-1?frames%quantum:0);
    if(n<eyes||n%eyes)throw Error('Incomplete stereo pair');
    clips.push({index:i,start:at*fps.den/fps.num,seconds:n*fps.den/fps.num,codedFrames:n});
    at+=n;
  }
  return clips;
}
export async function runParallelMovie({file, settings, media, job, workers, onUpdate=()=>{},
  signal, createWorker=()=>new Worker('worker.js?v=20261118f'), save=appendMovieSegment}) {
  const clips=planBalancedMovieClips(media.duration,settings,workers);
  const budgets=settings.maxMB==null?null:allocateMovieBudget(clips,Math.floor(settings.maxMB*1e6));
  const count=Math.min(Math.max(1,Math.floor(workers)),clips.length);
  const live=new Set();
  const stopper=new AbortController();
  const progress=Array.from({length:count},()=>0);
  const active=Array.from({length:count},()=>null);
  const pending=clips.filter(clip=>!job.segments[clip.index]);
  const totalFrames=clips.reduce((sum,clip)=>sum+clip.codedFrames,0);
  let completed=totalFrames-pending.reduce((sum,clip)=>sum+clip.codedFrames,0);
  let next=0;
  const notify=()=>{
    const inProgress=active.reduce((sum,clip,slot)=>sum+(clip?clip.codedFrames*progress[slot]:0),0);
    onUpdate({fractions:[...progress],overall:(completed+inProgress)/totalFrames,
      workers:count,clips:clips.length});
  };
  const aborted=()=>signal?.aborted||stopper.signal.aborted;
  const abort=()=>{stopper.abort();for(const w of live)w.terminate();};
  signal?.addEventListener('abort',abort,{once:true});
  async function encode(clip, slot, w){
    if(aborted())throw Error('Cancelled');
    return await new Promise((resolve,reject)=>{
        let settled=false;
        const cancel=()=>done(Error('Cancelled'));
        const done=(error,result)=>{if(settled)return;settled=true;signal?.removeEventListener('abort',cancel);stopper.signal.removeEventListener('abort',cancel);error?reject(error):resolve(result);};
        signal?.addEventListener('abort',cancel,{once:true});
        stopper.signal.addEventListener('abort',cancel,{once:true});
        w.onerror=e=>done(Error(`Worker ${slot+1}: ${e.message||'execution failed'}`));
        w.onmessage=({data:d})=>{
          if(aborted()){cancel();return;}
          if(d.type==='error')done(Error(`Worker ${slot+1}: ${d.message}`));
          else if(d.type==='segment')done(null,d);
          else if(d.type==='progress'&&Number.isFinite(d.fraction)){
            // The audio stage can reset its local fraction; do not make the
            // total timeline jump backwards. Completion is authoritative.
            progress[slot]=Math.max(progress[slot],Math.min(.95,Math.max(0,d.fraction)));
            notify();
          }else if(d.type==='log'&&/error|failed/i.test(d.line))onUpdate({log:d.line});
        };
        try{w.postMessage({type:'segment',file,settings,clip:{start:clip.start,seconds:clip.seconds},media,verifyRange:!!job.manifest,rangeBudget:budgets?.[clip.index]});}
        catch(e){done(e);}
      });
  }
  try{
    notify();
    const jobs=Array.from({length:count},async(_,slot)=>{
      let w=null,used=0;
      try{while(next<pending.length){
        if(aborted())throw Error('Cancelled');
        const clip=pending[next++];
        active[slot]=clip;
        progress[slot]=0;
        notify();
        if(!w){w=createWorker();live.add(w);used=0;}
        const d=await encode(clip,slot,w);
        if(aborted())throw Error('Cancelled');
        if(d.empty){
          if(clip.index!==clips.length-1)throw Error('Input video ended before the scheduled timeline; try one worker.');
        }else{
          if(!(d.frames>0)||d.frames>clip.codedFrames+2)throw Error('Encoder returned an unexpected frame count');
          if(d.frames!==clip.codedFrames&&clip.index!==clips.length-1)
            throw Error('Input video ended before the scheduled timeline; try one worker.');
          if(job.manifest){
            await persistRange(job,clip.index,clip,async()=>{
              await save(job,d.blob,d.frames,clip.index);
              return job.segments[clip.index];
            });
          }else await save(job,d.blob,d.frames,clip.index);
          if(aborted())throw Error('Cancelled');
        }
        active[slot]=null;
        completed+=clip.codedFrames;
        progress[slot]=1;
        notify();
        if(++used>=4){w.terminate();live.delete(w);w=null;}
      }}finally{if(w){w.terminate();live.delete(w);}}
    });
    const results=await Promise.allSettled(jobs.map(p=>p.catch(error=>{abort();throw error;})));
    const failure=results.find(r=>r.status==='rejected'&&r.reason?.message!=='Cancelled')??results.find(r=>r.status==='rejected');
    if(failure)throw failure.reason;
    const parts=job.segments.filter(Boolean).length;
    if(!parts||Array.from(job.segments).some(x=>!x))throw Error('One or more encoded timeline parts are missing.');
    return {parts,frames:job.segments.reduce((sum,x)=>sum+x.frames,0),workers:count};
  }finally{abort();signal?.removeEventListener('abort',abort);}
}
