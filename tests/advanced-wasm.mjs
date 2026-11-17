// Small real-codec regression; generated media lives outside the repository.
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {convert} from '../dist/core.mjs';
const work=mkdtempSync(join(tmpdir(),'mobipeg-advanced-'));
const ff=resolve('native/local/bin/ffmpeg');
try {
 const input=join(work,'source.mkv');
 execFileSync(ff,['-v','error','-f','lavfi','-i','testsrc2=s=400x224:r=24:d=0.5','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=0.5','-c:v','ffv1','-c:a','pcm_s16le',input]);
 const source=new Blob([readFileSync(input)]);
 for(const engine of ['engine','engine-simd'])for(const mode of ['2d','full-sbs','half-sbs']){
  let serial=0;
  const run=async(args,files={},output=null,env={},allowFailure=false)=>{
   const prefix=join(work,engine+'-'+mode+'-'+serial++),paths={};
   for(const [name,blob]of Object.entries(files)){const path=prefix+'-'+name;writeFileSync(path,Buffer.from(await blob.arrayBuffer()));paths[name]=path;}
   const spec={args,files:paths,env,output,allowFailure,result:prefix+'.json',destination:prefix+'.moflex'};
   writeFileSync(prefix+'-spec.json',JSON.stringify(spec));
   execFileSync(process.execPath,['tests/wasm-command.cjs',prefix+'-spec.json'],{env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist',engine)},maxBuffer:2*1024*1024});
   return {...JSON.parse(readFileSync(spec.result)),blob:output?new Blob([readFileSync(spec.destination)]):null};
  };
  const result=await convert({source,settings:{mode,preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:null,maxMB:null,movieAudio:true,
   advanced:{me:'dia',subme:2,skip:0,refine:1,penalty:24,diagonal:0,gop:24,scaler:'bicubic',inputRange:'auto',lumaSpatial:0.7,chromaSpatial:1.1,lumaTemporal:1,chromaTemporal:1,volume:-6,highpass:80,lowpass:16000}},run,clip:{start:0,seconds:0.5}});
  assert.equal(result.frames,mode==='2d'?12:24);assert.equal(result.seconds,0.5);
  const output=join(work,engine+'-'+mode+'.moflex');writeFileSync(output,Buffer.from(await result.blob.arrayBuffer()));
  execFileSync(ff,['-v','error','-xerror','-i',output,'-f','null','-']);
  console.log(`${engine} ${mode}: advanced controls, video/audio decode, frames and duration passed`);
 }
}finally{rmSync(work,{recursive:true,force:true});}
