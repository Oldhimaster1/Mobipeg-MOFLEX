import {test,expect} from '@playwright/test';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
let work,input,motionInput;
test.beforeAll(()=>{
 work=mkdtempSync(join(tmpdir(),'mobipeg-browser-framing-'));input=join(work,'source.mp4');
 execFileSync(resolve('native/local/bin/ffmpeg'),['-v','error','-f','lavfi','-i','color=red:s=200x224:r=30:d=2','-f','lavfi','-i','color=blue:s=200x224:r=30:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-filter_complex','[0:v][1:v]hstack[v]','-map','[v]','-map','2:a','-c:v','mpeg4','-q:v','3','-c:a','aac',input]);
 motionInput=join(work,'motion.mkv');
 execFileSync(resolve('native/local/bin/ffmpeg'),['-v','error','-f','lavfi','-i','testsrc2=s=160x144:r=24:d=3',
   '-f','lavfi','-i','color=blue:s=160x144:r=24:d=3','-filter_complex','[0:v][1:v]hstack',
   '-c:v','ffv1',motionInput]);
});
test.afterAll(()=>{if(work)rmSync(work,{recursive:true,force:true});});
for(const engine of ['scalar','simd'])test(`${engine}: motion preview changes frames in sync and preserves eye selection`,async({page})=>{
 await page.goto('/');
 await page.locator('#file').setInputFiles(motionInput);
 await page.locator('#engine').evaluate(el=>el.closest('details').open=true);
 await page.locator('#engine').selectOption(engine);
 await page.locator('input[name=mode][value=full-sbs]').check();
 await page.locator('#resolution').selectOption('256x144');
 await page.locator('#speed').selectOption('fast');
 await page.locator('#preset').selectOption('small');
 await page.locator('#sampleMotion').check();
 await page.locator('#makeSample').click();
 await expect(page.locator('#sampleStatus')).toContainText('30 preview frames',{timeout:60000});
 const sample=async id=>page.locator(id).evaluate(canvas=>canvas.toDataURL());
 const first=await Promise.all([sample('#originalFrame'),sample('#decodedFrame')]);
 await page.locator('#sampleSeek').fill('12');
 const later=await Promise.all([sample('#originalFrame'),sample('#decodedFrame')]);
 expect(later[0]).not.toBe(first[0]);expect(later[1]).not.toBe(first[1]);
 await page.locator('#sampleEye').selectOption('1');
 for(const id of ['#originalFrame','#decodedFrame']){
   const pixel=await page.locator(id).evaluate(c=>Array.from(c.getContext('2d').getImageData(c.width/2,c.height/2,1,1).data));
   expect(pixel[2]).toBeGreaterThan(180);expect(pixel[0]).toBeLessThan(60);
 }
 await page.locator('#samplePlay').click();
 await expect.poll(async()=>await page.locator('#sampleSeek').inputValue()).not.toBe('12');
 await page.locator('#samplePlay').click();
 await page.locator('#sampleStart').fill('0.5');
 await expect(page.locator('#sampleResult')).toBeHidden();
});
for(const engine of ['scalar','simd'])test(`${engine}: actual stereo preview, per-eye crop and new preset conversion`,async({page},testInfo)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.locator('#file').setInputFiles(input);
 await page.locator('#engine').evaluate(el=>el.closest('details').open=true);
 await page.locator('#engine').selectOption(engine);
 await page.locator('input[name=mode][value=half-sbs]').check();
 await page.locator('#resolution').selectOption('352x240');await page.locator('#fps').selectOption('15');
 await page.locator('.framing > summary').click();await page.locator('#fit').selectOption('fill');await page.locator('#aspect').selectOption('16/9');await page.locator('#speed').selectOption('fast');await page.locator('#crop-left').fill('16');
 await page.locator('#sampleStart').fill('0.5');await page.locator('#makeSample').click();await page.locator('#cancelSample').click();
 await expect(page.locator('#makeSample')).toBeEnabled();await expect(page.locator('#sampleStatus')).toHaveText('Preview cancelled.');
 await page.locator('#makeSample').click();
 await expect(page.locator('#sampleResult')).toBeVisible({timeout:90000});
 await expect(page.locator('#sampleStatus')).toContainText('352 × 240 per eye');
 const pixel=()=>page.locator('#decodedFrame').evaluate(c=>Array.from(c.getContext('2d').getImageData(176,120,1,1).data));
 let p=await pixel();expect(p[0]).toBeGreaterThan(180);expect(p[2]).toBeLessThan(60);
 await page.locator('#sampleEye').selectOption('1');p=await pixel();expect(p[2]).toBeGreaterThan(180);expect(p[0]).toBeLessThan(60);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.locator('#convert').click();await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:90000});
 await expect(page.locator('#resultmeta')).toContainText('60 coded frames');
 const wait=page.waitForEvent('download');await page.locator('#download').click();const download=await wait;
 const output=testInfo.outputPath('cropped.moflex');await download.saveAs(output);
 execFileSync(resolve('native/local/bin/ffmpeg'),['-v','error','-xerror','-i',output,'-f','null','-']);
 await page.locator('#crop-left').fill('32');await expect(page.locator('#sampleResult')).toBeHidden();
 await page.locator('#resetCrop').click();await expect(page.locator('#crop-left')).toHaveValue('0');await expect(page.locator('#fit')).toHaveValue('fit');
 expect(errors).toEqual([]);
});
