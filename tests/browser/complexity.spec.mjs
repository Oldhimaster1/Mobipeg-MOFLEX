import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
let folder,source;
test.beforeAll(()=>{
 folder=mkdtempSync(join(tmpdir(),'mobipeg-scene-browser-'));source=join(folder,'source.mkv');
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=gray:s=320x240:r=24:d=4','-f','lavfi','-i','testsrc2=s=320x240:r=24:d=4',
 '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0','-c:v','ffv1',source]);
});
test.afterAll(()=>rmSync(folder,{recursive:true,force:true}));
for(const engine of ['scalar','simd'])test('real source motion/texture analysis and cached recovery with '+engine,async({page})=>{
 await page.goto('/player.html');
 await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='source';document.body.append(input);});
 await page.locator('#source').setInputFiles(source);
 const result=await page.evaluate(async engine=>{
  const worker=new Worker('/worker.js?v=20261118i'),statuses=[];
  const call=cachedComplexity=>new Promise((resolve,reject)=>{
   worker.onerror=e=>reject(Error(e.message));worker.onmessage=({data})=>{
    if(data.type==='status')statuses.push(data.stage);
    if(data.type==='error')reject(Error(data.message));if(data.type==='inspected')resolve(data.media);
   };
   worker.postMessage({type:'inspect',file:document.getElementById('source').files[0],settings:{mode:'2d',fps:'24',workers:2,engine,maxMB:1,movieAudio:true},cachedComplexity});
  });
  try{const first=await call();const measured=statuses.splice(0);const cached=await call(first.complexity);return {first,cached,measured,statuses};}
  finally{worker.terminate();}
 },engine);
 expect(result.first.complexity.clips).toHaveLength(2);
 expect(result.first.complexity.clips[1].motion).toBeGreaterThan(result.first.complexity.clips[0].motion+.005);
 expect(result.cached.complexity).toEqual(result.first.complexity);
 expect(result.measured.filter(s=>s.startsWith('Analyzing scene'))).toHaveLength(2);
 expect(result.statuses.filter(s=>s.startsWith('Analyzing scene'))).toHaveLength(0);
});
