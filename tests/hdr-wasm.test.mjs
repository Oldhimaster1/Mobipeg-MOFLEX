import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync,statSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {createHdrLut} from '../dist/hdr-lut.mjs';
import {encodeArgs,environment,filters,parseProbe} from '../dist/core.mjs';

// A genuine PQ/HLG tagged 10-bit synthetic source, encoded with the exact
// checked-in WASM MobiClip codec, then decoded using an independent WASM run.
// No untracked patched native FFmpeg build is required.
for(const [transfer,tag] of [['pq','smpte2084'],['hlg','arib-std-b67']]){
 test('WASM '+transfer+' HDR -> SDR -> valid decoded MobiClip MOFLEX',()=>{
   const dir=mkdtempSync(join(tmpdir(),'mobipeg-hdr-lut-'));
   try{
     const source=join(dir,'source.mkv'),lut=join(dir,'hdr.cube'),
       movie=join(dir,'movie.moflex');
     execFileSync('ffmpeg',['-nostdin','-hide_banner','-v','error','-y',
       '-f','lavfi','-i','testsrc2=s=320x240:r=24:d=1',
       '-vf','format=yuv420p10le,setparams=color_primaries=bt2020:color_trc='+tag+
         ':colorspace=bt2020nc','-c:v','ffv1','-pix_fmt','yuv420p10le',
       '-color_primaries','bt2020','-color_trc',tag,'-colorspace','bt2020nc',source],
       {timeout:30000});
     writeFileSync(lut,createHdrLut(transfer,'mobius'));
     const settings={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'320x240',
       motion:'auto',speed:'original',q:null,maxMB:null,hdrMode:'auto',hdrTransfer:'auto'};
     assert.match(filters(settings,transfer)[1],/lut3d=file=\/input\/hdr.cube/);
     const run=(name,args,inputs,outPath,destination)=>{
       const spec={args,files:inputs,env:environment(settings),output:outPath,destination,
         result:join(dir,name+'-results.json')};
       const path=join(dir,name+'-command.json');
       writeFileSync(path,JSON.stringify(spec));
       execFileSync(process.execPath,['tests/wasm-command.cjs',path],
         {timeout:180000,maxBuffer:4*1048576,env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist/engine')}});
       const result=JSON.parse(readFileSync(spec.result,'utf8'));
       assert.equal(result.code,0,result.log.slice(-1200));
       return result;
     };
     const result=run('encode',encodeArgs(settings,30,'/input/source','/video.moflex',transfer),
       {source,'hdr.cube':lut},'/video.moflex',movie);
     assert.ok(statSync(movie).size>=8192&&statSync(movie).size%4096===0);
     assert.ok(result.frames>=24,'Expected all 24 video frames');
     const decoded=run('decode',['-hide_banner','-nostdin','-v','error','-xerror','-i',
       '/input/movie','-map','0:v:0','-progress','pipe:1','-f','null','-'],
       {movie},null,null);
     assert.equal(decoded.frames,24,'Decoded frame count changed');
   }finally{rmSync(dir,{recursive:true,force:true});}
 });
}
