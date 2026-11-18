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
  const call=(cachedComplexity,budgetMode='scene')=>new Promise((resolve,reject)=>{
   worker.onerror=e=>reject(Error(e.message));worker.onmessage=({data})=>{
    if(data.type==='status')statuses.push(data.stage);
    if(data.type==='error')reject(Error(data.message));if(data.type==='inspected')resolve(data.media);
   };
   worker.postMessage({type:'inspect',file:document.getElementById('source').files[0],settings:{mode:'2d',fps:'24',workers:2,engine,maxMB:1,movieAudio:true,budgetMode},cachedComplexity});
  });
  try{const first=await call();const measured=statuses.splice(0);const cached=await call(first.complexity);const uniform=await call(undefined,'uniform');return {first,cached,uniform,measured,statuses};}
  finally{worker.terminate();}
 },engine);
 expect(result.first.complexity.clips).toHaveLength(2);
 expect(result.first.complexity.clips[1].motion).toBeGreaterThan(result.first.complexity.clips[0].motion+.005);
 expect(result.cached.complexity).toEqual(result.first.complexity);
 expect(result.uniform.complexity).toBeUndefined();
 expect(result.measured.filter(s=>s.startsWith('Analyzing scene'))).toHaveLength(2);
 expect(result.statuses.filter(s=>s.startsWith('Analyzing scene'))).toHaveLength(0);
});

test('uniform allocation is selectable and performs a real browser conversion',async({page},testInfo)=>{
 await page.goto('/');await page.locator('#file').setInputFiles(source);
 await page.locator('#longMovie').check();await page.locator('#workers').fill('2');
 await page.locator('#resolution').selectOption('320x240');await page.locator('#speed').selectOption('fast');
 await page.locator('#maxMB').evaluate(el=>el.closest('details').open=true);
 await page.locator('#maxMB').fill('0.8');await page.locator('#budgetMode').selectOption('uniform');
 await page.locator('#convert').click();
 await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:90000});
 await expect(page.locator('#logs')).not.toContainText('Analyzing scene');
 const pending=page.waitForEvent('download');await page.locator('#download').click();
 const output=testInfo.outputPath('uniform.moflex');await (await pending).saveAs(output);
 execFileSync('ffmpeg',['-v','error','-xerror','-i',output,'-f','null','-']);
});
