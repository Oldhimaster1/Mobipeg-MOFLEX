import test from 'node:test';
import assert from 'node:assert/strict';
import {planMovieClips} from '../dist/movie.mjs';
import {runParallelMovie} from '../dist/parallel.mjs';

const settings={mode:'2d',fps:'30'};

test('long movies are partitioned without source chapter information',()=>{
  const clips=planMovieClips(601,settings);
  assert.ok(clips.length>10);
  assert.equal(clips[0].index,0);
  clips.forEach((clip,index)=>{
    assert.equal(clip.index,index);
    assert.ok(clip.seconds>0 && clip.seconds<=30);
    if(index)assert.ok(Math.abs(clip.start-(clips[index-1].start+clips[index-1].seconds))<1e-6);
  });
  assert.ok(Math.abs(clips.at(-1).start+clips.at(-1).seconds-601)<.1);
});

test('fractional stereo timeline work maintains frame and audio alignment',()=>{
  for(const mode of ['full-sbs','half-sbs'])for(const fps of ['24000/1001','30000/1001']){
    const clips=planMovieClips(3600.033,{mode,fps});
    for(const clip of clips){
      assert.equal(clip.codedFrames%2,0);
      if(clip===clips.at(-1))continue;
      assert.ok(Math.abs(clip.seconds*48000/256-Math.round(clip.seconds*48000/256))<1e-6);
    }
  }
});

function fakeFactory({emptyLast=false,failAt=-1,created=[]}={}){
  return ()=>{
    const w={terminated:false,terminate(){this.terminated=true;},postMessage(message){
      const {clip}=message;
      const index=Math.round(clip.start/30);
      queueMicrotask(()=>{
        if(this.terminated)return;
        if(index===failAt)this.onmessage({data:{type:'error',message:'synthetic failure'}});
        else this.onmessage({data:{type:'segment',frames:Math.round(clip.seconds*30),
          ...(emptyLast&&index===3?{empty:true}:{blob:new Blob(['test'])})}});
      });
    }};
    created.push(w);return w;
  };
}

test('several independent worker lanes save by timeline index despite completion order',async()=>{
  const job={segments:[]},updates=[];
  const result=await runParallelMovie({file:new Blob(['input']),settings,media:{duration:121,audio:false},job,
    workers:3,createWorker:fakeFactory(),onUpdate:p=>updates.push(p),
    save:async(job,blob,frames,index)=>{
      await new Promise(r=>setTimeout(r,index===0?5:0));
      job.segments[index]={frames,file:blob};
    }});
  assert.equal(result.workers,3);
  assert.equal(result.parts,job.segments.length);
  assert.ok(updates.some(u=>u.fractions?.some(f=>f>0)));
  assert.equal(updates.at(-1).overall,1);
  assert.ok(job.segments.every(Boolean));
});

test('worker failure aborts conversion and releases all WASM workers',async()=>{
  const created=[];
  await assert.rejects(runParallelMovie({file:new Blob(['input']),settings,media:{duration:120,audio:false},job:{segments:[]},
    workers:2,createWorker:fakeFactory({failAt:0,created}),save:async()=>{}}),/synthetic failure/);
  assert.ok(created.every(w=>w.terminated));
});

test('cancel interrupts pending workers and leaves no encoder active',async()=>{
  const controller=new AbortController(),created=[];
  const task=runParallelMovie({file:new Blob(['input']),settings,media:{duration:120,audio:false},job:{segments:[]},
    workers:2,signal:controller.signal,createWorker:()=>{
      const w={terminate(){this.stopped=true;},postMessage(){}};created.push(w);return w;
    }});
  await new Promise(r=>setTimeout(r,0));controller.abort();
  await assert.rejects(task,/Cancelled/);
  assert.ok(created.every(w=>w.stopped));
});
