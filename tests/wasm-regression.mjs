// End-to-end tests of the exact browser binaries under Node (not browser coverage).
import {mkdtempSync,writeFileSync,readFileSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {convert} from '../dist/core.mjs';
const work=mkdtempSync(join(tmpdir(),'mobipeg-wasm-regression-'));
const ff=resolve('native/local/bin/ffmpeg'),input=join(work,'source.mkv');
execFileSync(ff,['-v','error','-f','lavfi','-i','color=red:s=200x224:r=24:d=2',
 '-f','lavfi','-i','color=blue:s=200x224:r=24:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
 '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=2','-filter_complex','[0:v][1:v]hstack[v]',
 '-map','[v]','-map','2:a','-map','3:a','-metadata:s:a:0','language=eng','-metadata:s:a:1','language=jpn',
 '-c:v','ffv1','-c:a','pcm_s16le',input]);
const source=new Blob([readFileSync(input)]),results=[];
for(const engine of ['engine','engine-simd'])for(const mode of ['2d','full-sbs','half-sbs']){
 const engineDir=resolve('dist',engine);let serial=0;
 const run=async(args,files={},output=null,env={},allowFailure=false)=>{
  const prefix=join(work,engine+'-'+mode+'-'+serial++),paths={};
  for(const [name,blob]of Object.entries(files)){const path=prefix+'-'+name;writeFileSync(path,Buffer.from(await blob.arrayBuffer()));paths[name]=path;}
  const spec={args,files:paths,env,output,allowFailure,result:prefix+'.json',destination:prefix+'.moflex'};
  writeFileSync(prefix+'-spec.json',JSON.stringify(spec));
  execFileSync(process.execPath,['tests/wasm-command.cjs',prefix+'-spec.json'],{env:{...process.env,MOBIPEG_ENGINE_DIR:engineDir},maxBuffer:2*1024*1024});
  const info=JSON.parse(readFileSync(spec.result));return {...info,blob:output?new Blob([readFileSync(spec.destination)]):null};
 };
 const result=await convert({source,settings:{mode,preset:'balanced',filter:'detail',fps:'24',resolution:'400x224',motion:'off',q:null,maxMB:null,audioTrack:1,movieAudio:true},run,clip:{start:0,seconds:2}});
 assert.equal(result.frames,mode==='2d'?48:96);assert.equal(result.seconds,2);
 if(mode==='2d'){
  const empty=await convert({source,settings:{mode,preset:'balanced',filter:'detail',fps:'24',resolution:'400x224',motion:'off',q:null,maxMB:null},run,verify:false,clip:{start:2,seconds:1}});
  assert.equal(empty.empty,true,'A clean end of video must be distinguishable from an encoder error');
 }
 const path=join(work,`${engine}-${mode}-final.moflex`);writeFileSync(path,Buffer.from(await result.blob.arrayBuffer()));
 execFileSync(ff,['-v','error','-xerror','-i',path,'-f','null','-']);
 results.push({engine,mode,frames:result.frames,seconds:result.seconds,bytes:result.blob.size,completeDecode:true});
 console.log(JSON.stringify(results.at(-1)));
}
if(process.argv[2])writeFileSync(process.argv[2],JSON.stringify(results,null,2));
