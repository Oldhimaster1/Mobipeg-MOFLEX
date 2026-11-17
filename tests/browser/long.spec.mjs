import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {join,resolve} from 'node:path';
import {mkdtempSync,readFileSync,rmSync,statSync} from 'node:fs';
import {tmpdir} from 'node:os';
const fixture=process.env.MOBIPEG_BROWSER_FIXTURE;
for(const workers of [1,2])test(`whole-movie size target with ${workers} workers`,async({page},testInfo)=>{
 const work=mkdtempSync(join(tmpdir(),'mobipeg-target-'));
 const ff=resolve('native/local/bin/ffmpeg');
 try{
   const source=join(work,'source.mkv');
   execFileSync(ff,['-v','error','-f','lavfi','-i','testsrc2=s=320x240:r=24:d=9',
     '-f','lavfi','-i','sine=f=880:r=48000:d=9','-c:v','ffv1','-c:a','pcm_s16le',source]);
   await page.goto('/');
   await page.locator('#file').setInputFiles(source);
   await page.locator('#longMovie').check();
   await page.locator('#workers').fill(String(workers));
   await page.locator('#resolution').selectOption('320x240');
   await page.locator('#preset').selectOption('balanced');
   await page.locator('#speed').selectOption('fast');
   await page.locator('#maxMB').evaluate(el=>el.closest('details').open=true);
   await page.locator('#maxMB').fill('0.85');
   await page.locator('#convert').click();
   await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:120000});
   await expect(page.locator('#resultmeta')).toContainText('216 coded frames');
   const pending=page.waitForEvent('download');
   await page.locator('#download').click();
   const output=testInfo.outputPath('target.moflex');
   await (await pending).saveAs(output);
   expect(statSync(output).size).toBeLessThanOrEqual(850000);
   execFileSync(ff,['-v','error','-xerror','-i',output,'-map','0:v:0','-map','0:a:0','-f','null','-']);
 }finally{rmSync(work,{recursive:true,force:true});}
});
test('OPFS recovery ignores a damaged range and protects a job open in another tab',async({page})=>{
 await page.goto('/');
 const result=await page.evaluate(async()=>{
   const {openCheckpoint,setCheckpointMedia,persistRange,restoreCheckpoints,closeCheckpoint}=
     await import('/checkpoints.mjs');
   const source=new File(['source video'],'source.mkv');
   const settings={preset:'small',workers:2};
   const options={storage:navigator.storage,locks:navigator.locks,cancelled:()=>false};
   let job=await openCheckpoint(source,settings,options);
   let locked=false;
   try{await openCheckpoint(source,settings,options);}catch(error){locked=/already being converted/.test(error.message);}
   await setCheckpointMedia(job,{duration:10,audio:true});
   const clips=[0,1,2].map(index=>({index,start:index*3,seconds:3,codedFrames:72}));
   const partName=index=>'test-part-'+index;
   for(const clip of clips){
     await persistRange(job,clip.index,clip,async()=>{
       const handle=await job.work.getFileHandle(partName(clip.index),{create:true});
       const writable=await handle.createWritable();
       await writable.write('data');
       await writable.close();
       return {file:await handle.getFile(),frames:72};
     });
   }
   const damaged=await (await job.work.getFileHandle(partName(1))).createWritable();
   await damaged.write('xxxx');
   await damaged.close();
   await job.work.removeEntry(partName(2));
   await closeCheckpoint(job,false);
   job=await openCheckpoint(source,settings,options);
   await restoreCheckpoints(job,clips,async(index,frames)=>({
     file:await (await job.work.getFileHandle(partName(index))).getFile(),frames,
   }));
   const restored=job.segments.flatMap((part,index)=>part?[index]:[]);
   const originalId=job.id;
   await closeCheckpoint(job,false);
   const changed=await openCheckpoint(new File(['changed data'],'source.mkv'),settings,options);
   const differentSource=changed.id!==originalId;
   await closeCheckpoint(changed,false);
   return {locked,restored,differentSource};
 });
 expect(result).toEqual({locked:true,restored:[0],differentSource:true});
});
for(const engine of ['scalar','simd'])test(`${engine}: real segmented OPFS movie, language selection and download`,async({page},testInfo)=>{
 test.skip(!fixture,'Generate a 65-second red/blue stereo clip with two labeled audio tracks');
 const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
 await page.goto('/');
 const selectSettings=async()=>{
 await page.locator('#file').setInputFiles(fixture);
 await page.locator('#engine').evaluate(el=>el.closest('details').open=true);
 await page.locator('#engine').selectOption(engine);
 await page.locator('#inspectAudio').click();
 await expect(page.locator('#audioTrack option')).toHaveCount(2,{timeout:30000});
 await expect(page.locator('#audioTrack option').nth(1)).toContainText('jpn');
 await page.locator('#audioTrack').selectOption('1');
 await page.locator('input[name=mode][value=half-sbs]').check();
 await page.locator('#longMovie').check();await page.locator('#speed').selectOption('fast');
 await page.locator('#workers').fill(engine==='scalar'?'1':'2');
 };
 await selectSettings();
 await page.locator('#convert').click();
 if(engine==='scalar'){
   await expect(page.locator('#logs')).toContainText('Range 1 saved to local storage',{timeout:100000});
   page.once('dialog',dialog=>dialog.accept());
   await page.reload({timeout:30000});
   await selectSettings();
   await page.locator('#convert').click();
   await expect(page.locator('#logs')).toContainText('Resuming with 1 verified saved ranges.',{timeout:30000});
   await expect(page.locator('#logs')).not.toContainText('Encoding range 1 starting');
 }
 await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:210000});
 await expect(page.locator('#resultmeta')).toContainText('3,120 coded frames');
 const downloaded=page.waitForEvent('download');await page.locator('#download').click();
 const file=await downloaded,path=testInfo.outputPath('verified.moflex');await file.saveAs(path);
 const ff=resolve('native/local/bin/ffmpeg');
 const audio=execFileSync(ff,['-v','error','-xerror','-i',path,'-map','0:a:0','-ac','1','-ar','48000','-f','s16le','-'],{maxBuffer:10*1024*1024});
 expect(Math.abs(audio.length/2-65*48000)).toBeLessThanOrEqual(256);
 const energy=hz=>{let re=0,im=0;for(let p=4800;p<43200;p+=4){const v=audio.readInt16LE(p*2),phase=2*Math.PI*hz*p/48000;re+=v*Math.cos(phase);im+=v*Math.sin(phase);}return re*re+im*im;};
 expect(energy(880)).toBeGreaterThan(energy(440)*100);
 const download=page.waitForEvent('download');await page.locator('#report').click();
 const report=await download;const reportPath=testInfo.outputPath('report.json');await report.saveAs(reportPath);
 const result=JSON.parse(readFileSync(reportPath));expect(result.verified).toBe(true);expect(result.settings.speed).toBe('fast');expect(result.output.chapters).toBe(engine==='scalar'?3:4);
 // Cleanup must release the completed on-device movie too.
 page.once('dialog',dialog=>dialog.accept());await page.locator('#clearMovieData').click();
 await expect(page.locator('#clearMovieData')).toBeHidden();
 const jobs=await page.evaluate(async()=>{const root=await navigator.storage.getDirectory();const d=await root.getDirectoryHandle('mobipeg-long-movies');return Array.fromAsync(d.keys());});
 expect(jobs).toEqual([]);expect(pageErrors).toEqual([]);
});
