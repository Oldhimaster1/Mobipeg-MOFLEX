// Reproducible small-fixture measurement, not a full-movie speed claim.
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync,spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {encodeArgs,environment,filters} from '../dist/core.mjs';
const ff=resolve('native/local/bin/ffmpeg'),work=mkdtempSync(join(tmpdir(),'mobipeg-speed-'));
try{
 const source=join(work,'source.mkv'),reference=join(work,'reference.yuv');
 execFileSync(ff,['-v','error','-f','lavfi','-i','testsrc2=s=1280x720:r=24:d=3','-c:v','ffv1','-threads','2',source]);
 const settings={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:30,maxMB:null};
 execFileSync(ff,['-v','error','-i',source,...filters(settings),'-an','-pix_fmt','yuv420p','-c:v','rawvideo','-threads','1','-f','rawvideo',reference]);
 const rows=[];
 for(const engine of ['engine','engine-simd'])for(let repeat=0;repeat<3;repeat++)for(const speed of (repeat%2?['fast','original']:['original','fast'])){
  const prefix=join(work,engine+'-'+repeat+'-'+speed),output=prefix+'.moflex';
  const s={...settings,speed},spec={args:encodeArgs(s,30),files:{source},output:'/video.moflex',destination:output,result:prefix+'.json',env:environment(s)};
  writeFileSync(prefix+'-spec.json',JSON.stringify(spec));
  execFileSync(process.execPath,['tests/wasm-command.cjs',prefix+'-spec.json'],{env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist',engine)},maxBuffer:2e6});
  const data=JSON.parse(readFileSync(spec.result));assert.equal(data.frames,72);assert.equal(data.code,0);
  execFileSync(ff,['-v','error','-xerror','-i',output,'-f','null','-']);
  const ps=spawnSync(ff,['-hide_banner','-i',output,'-f','rawvideo','-pixel_format','yuv420p','-video_size','400x224','-framerate','24','-i',reference,'-filter_complex','[0:v][1:v]psnr','-an','-f','null','-'],{encoding:'utf8'});assert.equal(ps.status,0);
  const psnr=Number(/average:([\d.]+)/.exec(ps.stderr)?.[1]);assert.ok(Number.isFinite(psnr));
  const row={engine,speed,repeat,encodeSeconds:data.elapsed,frames:data.frames,bytes:readFileSync(output).length,psnrDB:psnr,completeDecode:true};rows.push(row);console.log(JSON.stringify(row));
 }
 const median=a=>a.toSorted((x,y)=>x-y)[Math.floor(a.length/2)];
 const summary=['engine','engine-simd'].map(engine=>{
  const before=rows.filter(r=>r.engine===engine&&r.speed==='original'),after=rows.filter(r=>r.engine===engine&&r.speed==='fast');
  const original=median(before.map(r=>r.encodeSeconds)),fast=median(after.map(r=>r.encodeSeconds));
  return {engine,originalMedianSeconds:original,fastMedianSeconds:fast,speedup:original/fast,originalPSNR:before[0].psnrDB,fastPSNR:after[0].psnrDB};
 });
 const report={fixture:'Generated 3-second 1280x720 testsrc2 at 24 fps; encoded at 400x224, Q30, 2D',metric:'FFmpeg call time inside WASM; excludes module loading, source generation, audio and final verification',limitations:'Synthetic chart, three repetitions per setting. Actual movies, source codecs and devices will differ. Fast changes pixels and compression; original remains default.',rows,summary};
 if(process.argv[2])writeFileSync(process.argv[2],JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(summary));
}finally{rmSync(work,{recursive:true,force:true});}
