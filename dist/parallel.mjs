import {appendMovieSegment, planMovieClips} from './movie.mjs';

// The input need not contain chapters: equal-sized *timeline shards* each
// encode short, independently seekable clips. A fresh WASM worker is used for
// each clip so native codec state and memory are released between clips.
export async function runParallelMovie({file, settings, media, job, workers, onUpdate=()=>{},
  signal, createWorker=()=>new Worker('worker.js?v=20261117g'), save=appendMovieSegment}) {
  const clips=planMovieClips(media.duration,settings);
  const count=Math.min(Math.max(1,Math.floor(workers)),clips.length);
  const live=new Set();
  const stopper=new AbortController();
  const progress=Array.from({length:count},()=>0);
  const notify=()=>onUpdate({fractions:[...progress], overall:progress.reduce((a,b)=>a+b,0)/count,
    workers:count, clips:clips.length});
  const aborted=()=>signal?.aborted||stopper.signal.aborted;
  const abort=()=>{stopper.abort();for(const w of live)w.terminate();};
  signal?.addEventListener('abort',abort,{once:true});
  async function encode(clip, slot){
    if(aborted())throw Error('Cancelled');
    let w;
    try{
      w=createWorker();live.add(w);
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
            progress[slot]=Math.max(progress[slot],(clip.shardIndex+Math.min(.95,Math.max(0,d.fraction)))/clip.shardLength);
            notify();
          }else if(d.type==='log'&&/error|failed/i.test(d.line))onUpdate({log:d.line});
        };
        try{w.postMessage({type:'segment',file,settings,clip:{start:clip.start,seconds:clip.seconds},media});}
        catch(e){done(e);}
      });
    }finally{if(w){w.terminate();live.delete(w);}}
  }
  try{
    notify();
    const chunks=Array.from({length:count},(_,i)=>{
      const start=Math.floor(i*clips.length/count),end=Math.floor((i+1)*clips.length/count);
      return clips.slice(start,end).map((clip,j)=>({...clip,shardIndex:j,shardLength:end-start}));
    });
    const jobs=chunks.map(async(chunk,slot)=>{
      for(const clip of chunk){
        const d=await encode(clip,slot);
        if(aborted())throw Error('Cancelled');
        if(d.empty){
          if(clip.index!==clips.length-1)throw Error('Input video ended before the scheduled timeline; try one worker.');
        }else{
          if(!(d.frames>0)||d.frames>clip.codedFrames+2)throw Error('Encoder returned an unexpected frame count');
          if(d.frames!==clip.codedFrames&&clip.index!==clips.length-1)
            throw Error('Input video ended before the scheduled timeline; try one worker.');
          await save(job,d.blob,d.frames,clip.index);
          if(aborted())throw Error('Cancelled');
        }
        progress[slot]=(clip.shardIndex+1)/clip.shardLength;
        notify();
      }
    });
    const results=await Promise.allSettled(jobs.map(p=>p.catch(error=>{abort();throw error;})));
    const failure=results.find(r=>r.status==='rejected'&&r.reason?.message!=='Cancelled')??results.find(r=>r.status==='rejected');
    if(failure)throw failure.reason;
    const parts=job.segments.filter(Boolean).length;
    if(!parts||job.segments.some(x=>!x))throw Error('One or more encoded timeline parts are missing.');
    return {parts,frames:job.segments.reduce((sum,x)=>sum+x.frames,0),workers:count};
  }finally{abort();signal?.removeEventListener('abort',abort);}
}
