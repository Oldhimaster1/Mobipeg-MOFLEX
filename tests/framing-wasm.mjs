// Real preview pixel decoding plus cropped conversion at new rates/resolutions.
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {previewFrame,convert,rate} from '../dist/core.mjs';
const work=mkdtempSync(join(tmpdir(),'mobipeg-framing-')),ff=resolve('native/local/bin/ffmpeg');
try{
 const input=join(work,'source.mkv');
 execFileSync(ff,['-v','error','-f','lavfi','-i','color=red:s=400x480:r=60:d=2','-f','lavfi','-i','color=blue:s=400x480:r=60:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-filter_complex','[0:v][1:v]hstack,setsar=4/3[v]','-map','[v]','-map','2:a','-c:v','ffv1','-c:a','pcm_s16le',input]);
 const source=new Blob([readFileSync(input)]);
 const cases=[['engine','2d','352x240','15','fit','16/9'],['engine','full-sbs','400x192','60000/1001','fill','4/3'],['engine','half-sbs','256x144','12','stretch','9/16'],['engine-simd','2d','640x368','48','fill','21/9'],['engine-simd','full-sbs','320x192','50','fit','1/1'],['engine-simd','half-sbs','800x480','60','fill','16/10']];
 for(const [engine,mode,resolution,fps,fit,aspect]of cases){
  let serial=0;
  const run=async(args,files={},output=null,env={},allowFailure=false)=>{
   const prefix=join(work,engine+'-'+mode+'-'+serial++),paths={};
   for(const [name,blob]of Object.entries(files)){const path=prefix+'-'+name;writeFileSync(path,Buffer.from(await blob.arrayBuffer()));paths[name]=path;}
   const spec={args,files:paths,env,output,allowFailure,result:prefix+'.json',destination:prefix+'.bin'};
   writeFileSync(prefix+'-spec.json',JSON.stringify(spec));
   execFileSync(process.execPath,['tests/wasm-command.cjs',prefix+'-spec.json'],{env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist',engine)},maxBuffer:2*1024*1024});
   return {...JSON.parse(readFileSync(spec.result)),blob:output?new Blob([readFileSync(spec.destination)]):null};
  };
  const settings={speed:'fast',mode,resolution,fps,preset:'balanced',filter:'detail',motion:'off',q:null,maxMB:null,movieAudio:true,crop:{fit,aspect,left:16,right:32,top:8,bottom:16}};
  const sample=await previewFrame({settings,source,start:0.5,run});
  assert.equal(sample.eyes,mode==='2d'?1:2);
  const original=new Uint8Array(await sample.original.arrayBuffer()),decoded=new Uint8Array(await sample.decoded.arrayBuffer()),pixels=sample.width*sample.height;
  assert.equal(original.length,pixels*4*sample.eyes);assert.equal(decoded.length,original.length);
  for(let eye=0;eye<sample.eyes;eye++){
   const at=(eye*pixels+Math.floor(sample.height/2)*sample.width+Math.floor(sample.width/2))*4;
   assert.equal(original[at+3],255);assert.equal(decoded[at+3],255);
   if(sample.eyes===2){const channel=eye===0?0:2;assert.ok(original[at+channel]>200);assert.ok(decoded[at+channel]>180,'Encoded preview keeps the correct eye color');}
  }
  const result=await convert({source,settings,run,clip:{start:0.5,seconds:0.5},media:{duration:2,audio:true}});
  assert.equal(result.frames,Math.round(0.5*rate(fps))*(mode==='2d'?1:2));
  const output=join(work,engine+'-'+mode+'.moflex');writeFileSync(output,Buffer.from(await result.blob.arrayBuffer()));
  execFileSync(ff,['-v','error','-xerror','-i',output,'-f','null','-']);
  console.log(`${engine} ${mode} ${resolution} ${fps} ${fit} ${aspect} fast: real preview pixels and complete video/audio decoding passed`);
 }
}finally{rmSync(work,{recursive:true,force:true});}
