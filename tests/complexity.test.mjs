import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {measureComplexity,validComplexity} from '../complexity.mjs';
import {allocateMovieBudget,remainingMovieBudgets} from '../movie.mjs';
const clips=Array.from({length:4},(_,index)=>({index,start:index*6,seconds:6,codedFrames:144}));
test('actual texture and interframe motion agree with the native implementation',()=>{
 const still=new Uint8Array(64*36*4).fill(100),motion=Uint8Array.from(still,(_,i)=>Math.floor(i/(64*36))%2?200:20);
 const a=measureComplexity(still),b=measureComplexity(motion);
 assert.equal(a.motion,0);assert.ok(b.motion>.5);assert.ok(b.score>a.score);
 const native=JSON.parse(execFileSync('python3',['-c',"import json,sys;sys.path.insert(0,'native');from scene_complexity import measure_complexity;print(json.dumps(measure_complexity(sys.stdin.buffer.read())))"],{input:motion}));
 assert.deepEqual(native,b);
 assert.throws(()=>measureComplexity(new Uint8Array(17)),/Incomplete/);
 assert.equal(measureComplexity(still.subarray(0,64*36)).motion,0);
});
test('complexity budgets preserve exact hard blocks and audio floors',()=>{
 const caps=allocateMovieBudget(clips,4*1024**2,[.025,.5,.025,.5],49500);
 assert.equal(caps.reduce((a,b)=>a+b,0),4*1024**2);
 assert.ok(caps[1]>caps[0]*2);assert.ok(caps.every(n=>n%4096===0&&n>6*49500));
 assert.throws(()=>allocateMovieBudget(clips,8192,[1,2,3,4],49500),/too small/);
 assert.throws(()=>allocateMovieBudget(clips,4e6,[1,NaN,2,3]),/complexity/);
});
test('redistribution spends committed bytes and protects concurrent reservations',()=>{
 const target=4*1024**2,segments=[];
 const initial=remainingMovieBudgets(clips,target,segments);
 const active={0:initial[0],1:initial[1]};
 segments[0]={file:{size:8192}};
 const caps=remainingMovieBudgets(clips,target,segments,active);
 assert.ok(caps[2]>initial[2]);assert.equal(caps[1],undefined);
 assert.equal(8192+active[1]+caps[2]+caps[3],target);
});
test('cached samples must match the actual schedule and valid measurements',()=>{
 const row={...clips[0],...measureComplexity(new Uint8Array(64*36*4))};
 assert.ok(validComplexity({version:1,clips:[row]},[clips[0]]));
 assert.equal(validComplexity({version:1,clips:[{...row,score:NaN}]},[clips[0]]),false);
});
test('portable isolated entry point can import its bundled local modules',()=>{
 const help=execFileSync('python3',['-I','native/MobiPEG_Studio_V15.py','--help'],{encoding:'utf8'});
 assert.match(help,/--workers/);assert.match(help,/--budget-mode/);assert.match(help,/--max-size-mb/);
});
test('short final ranges sample before EOF and tolerate an audio-only tail',async()=>{
 const {analyzeComplexity}=await import('../complexity.mjs');
 const schedule=[{start:0,seconds:30},{start:30,seconds:1/24}],times=[];
 const measured=await analyzeComplexity(new Blob(),schedule,async args=>{
  times.push(Number(args[args.indexOf('-ss')+1]));
  return {blob:new Blob([times.length<=2?new Uint8Array(64*36*4):new Uint8Array()])};
 });
 assert.ok(times.every(t=>t<=30+1/24-.5+1e-7));
 assert.equal(measured.clips[1].samples,0);
 assert.equal(measured.clips[1].score,.025);
});

test('unknown allocation modes fail before encoding',async()=>{const {validate}=await import('../core.mjs');assert.throws(()=>validate({budgetMode:'invalid'}),/allocation mode/);});
