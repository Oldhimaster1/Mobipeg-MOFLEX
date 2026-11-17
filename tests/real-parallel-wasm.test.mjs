// End-to-end Node execution of the *real* WASM V15 codec with independent
// timeline work units. Browser/PWA and physical 3DS validation are separate.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {convert} from '../dist/core.mjs';
import {runParallelMovie} from '../dist/parallel.mjs';
import {assembleMovie,inspectMovieSegment} from '../dist/movie.mjs';

const execute=promisify(execFile);

test('real V15 two-worker no-chapters movie passes ordered join and video+audio decode',{timeout:300000},async t=>{
  try{execFileSync('ffmpeg',['-version'],{stdio:'ignore'});}catch{t.skip('System FFmpeg missing');return;}
  const temp=mkdtempSync(join(tmpdir(),'mobipeg-parallel-wasm-'));
  const path=join(temp,'source.mkv');
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y',
    '-f','lavfi','-i','color=c=green:s=160x128:r=15:d=65',
    '-f','lavfi','-i','sine=frequency=620:sample_rate=48000:duration=65',
    '-map','0:v','-map','1:a','-c:v','ffv1','-c:a','pcm_s16le',path]);
  const settings={mode:'2d',fps:'15',resolution:'256x192',preset:'small',q:36,
    filter:'detail',motion:'off',audioTrack:0,advanced:null,crop:{fit:'fit',aspect:'source',left:0,right:0,top:0,bottom:0},
    speed:'fast',engine:'scalar',maxMB:null,movieAudio:true,workers:2};
  const original=new Blob([readFileSync(path)]),job={segments:[]};
  let seq=0;
  async function run(args,files={},output=null,env={},allowFailure=false){
    const number=seq++,root=join(temp,'command-'+number);
    const inputs={};
    for(const [name,blob] of Object.entries(files)){
      const filename=root+'-'+name;
      writeFileSync(filename,Buffer.from(await blob.arrayBuffer()));
      inputs[name]=filename;
    }
    const spec={args,files:inputs,env,output,allowFailure,
      result:root+'.json',destination:root+'.bin'};
    const specPath=root+'-spec.json';writeFileSync(specPath,JSON.stringify(spec));
    try{await execute(process.execPath,['tests/wasm-command.cjs',specPath],{
      env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist/engine')},timeout:120000,maxBuffer:2*1048576});}
    catch(error){if(!allowFailure)throw Error('WASM command failed: '+(error.stderr||error.message));}
    const d=JSON.parse(readFileSync(spec.result));
    return {...d,blob:output&&d.code===0?new Blob([readFileSync(spec.destination)]):null};
  }
  const created=[];
  function createWorker(){
    const w={terminated:false,terminate(){this.terminated=true;},postMessage(data){
      convert({settings:data.settings,source:data.file,run,clip:data.clip,media:data.media,
        notify:status=>{if(!this.terminated)this.onmessage?.({data:{type:'status',...status}});},verify:false})
        .then(result=>{if(!this.terminated)this.onmessage?.({data:{type:'segment',...result}});})
        .catch(error=>{if(!this.terminated)this.onmessage?.({data:{type:'error',message:error.message}});});
    }};
    created.push(w);return w;
  }
  const progress=[];
  const done=await runParallelMovie({file:original,settings,
    media:{duration:65,audio:true},workers:2,job,createWorker,
    save:async(job,blob,frames,index)=>{job.segments[index]={file:blob,frames};},
    onUpdate:value=>{if(value.fractions)progress.push(value.overall);}});
  assert.equal(done.workers,2);
  assert.ok(done.parts>=3);
  assert.ok(created.every(w=>w.terminated));
  assert.equal(progress.at(-1),1);
  const handle={async createWritable(){const parts=[];return{
    write:async bytes=>parts.push(bytes),close:async()=>{handle.file=new Blob(parts);},abort:async()=>{}};},
    async getFile(){return this.file;}};
  const joined=await assembleMovie({segments:job.segments,work:{getFileHandle:async()=>handle},outputName:'movie.moflex',audio:true},settings);
  const checked=await inspectMovieSegment(joined.file,done.frames);
  assert.ok(checked.entries.length>=done.parts);
  assert.ok(joined.seconds>64);
  const final=join(temp,'movie.moflex');writeFileSync(final,Buffer.from(await joined.file.arrayBuffer()));
  for(const kind of ['v','a']){
    const result=await run(['-hide_banner','-nostdin','-v','error','-xerror',
      '-i','/input/movie','-map',`0:${kind}:0`,'-f','null','-'],{movie:joined.file});
    assert.equal(result.code,0,`${kind} full decode must pass`);
  }
  t.diagnostic(`Encoded ${done.parts} real work units on 2 lanes; ${done.frames} frames; ${joined.file.size} bytes; video/audio decode passed`);
});
