import {test,expect} from '@playwright/test';
import {join} from 'node:path';
const folder=process.env.MOBIPEG_SEEK_FIXTURES;
for(const engine of ['scalar','simd'])for(const minutes of [30,60,90,120])test(`${engine} byte-exact indexed seeking throughout ${minutes} minutes`,async({page})=>{
 test.skip(!folder,'Supply generated long fixtures from stress-long-movie.py');
 await page.goto('/player.html');
 await page.evaluate(()=>{for(const id of ['longFixture','shortFixture']){const input=document.createElement('input');input.type='file';input.id=id;document.body.append(input);}});
 await page.locator('#longFixture').setInputFiles(join(folder,`movie-${minutes}min.moflex`));
 await page.locator('#shortFixture').setInputFiles(join(folder,'movie-5min.moflex'));
 const result=await page.evaluate(async({engine,minutes})=>{
  const worker=new Worker('player-worker.js?v=20261118i');let request=0;
  const call=data=>new Promise((resolve,reject)=>{worker.onmessage=({data})=>data.type==='error'?reject(Error(data.message)):resolve(data);worker.onerror=e=>reject(Error(e.message));worker.postMessage({...data,request:++request});});
  const started=performance.now();await call({type:'warm',engine});const warmSeconds=(performance.now()-started)/1000;
  const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');
  async function decode(file,start){
   const before=performance.now();const d=await call({type:'decode',file,start,startFrame:Math.round(start*24),frames:6,width:400,height:240,seconds:.25,audio:true});
   return {seconds:(performance.now()-before)/1000,frames:d.frames,video:await hash(d.video),audio:await hash(d.pcm)};
  }
  try{
   const rows=[];
   for(const fraction of [.1,.5,.95]){
    const start=minutes*60*fraction;
    const expected=await decode(document.getElementById('shortFixture').files[0],start%24+24);
    const actual=await decode(document.getElementById('longFixture').files[0],start);
    rows.push({...actual,start,equalVideo:actual.video===expected.video,equalAudio:actual.audio===expected.audio});
   }
   return {engine,minutes,warmSeconds,rows};
  }finally{worker.terminate();}
 },{engine,minutes});
 for(const row of result.rows){expect(row.frames).toBe(6);expect(row.equalVideo).toBe(true);expect(row.equalAudio).toBe(true);expect(row.seconds).toBeLessThan(15);}
 console.log(JSON.stringify(result));
});

test('actual player slider seeks into a two-hour file and resumes playback',async({page})=>{
 test.skip(!folder,'Supply generated long fixtures');
 await page.goto('/player.html');await page.locator('#movieFile').setInputFiles(join(folder,'movie-120min.moflex'));
 await expect(page.locator('#seek')).toBeEnabled();
 const started=Date.now();
 await page.locator('#seek').evaluate(el=>{el.value='6846';el.dispatchEvent(new Event('input',{bubbles:true}));});
 await page.locator('#play').click();
 await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:15000});
 const pixels=await page.locator('#screen').evaluate(el=>Array.from(el.getContext('2d').getImageData(20,20,1,1).data));
 expect(pixels[0]).toBeGreaterThan(180);expect(pixels[1]).toBeLessThan(60);
 console.log(JSON.stringify({actualInterfaceSeekSeconds:(Date.now()-started)/1000,targetSeconds:6846}));
 await page.locator('#pause').click();
 await expect(page.locator('#position')).toContainText('114:');
});

for(const engine of ['scalar','simd'])test('two-hour stereo seek keeps exact eye ordering and samples with '+engine,async({page})=>{
 const movie=process.env.MOBIPEG_STEREO_SEEK_FIXTURE,reference=process.env.MOBIPEG_STEREO_REFERENCE;
 test.skip(!movie||!reference,'Supply a repeated stereo movie and its short original');
 await page.goto('/player.html');await page.evaluate(()=>{for(const id of ['stereoLong','stereoRef']){const e=document.createElement('input');e.type='file';e.id=id;document.body.append(e);}});
 await page.locator('#stereoLong').setInputFiles(movie);await page.locator('#stereoRef').setInputFiles(reference);
 const result=await page.evaluate(async engine=>{
  const {inspectPlayableMoflex}=await import('/player-core.mjs'),file=document.getElementById('stereoLong').files[0],original=document.getElementById('stereoRef').files[0];
  const info=await inspectPlayableMoflex(file),refInfo=await inspectPlayableMoflex(original);
  const worker=new Worker('/player-worker.js?v=20261118i');
  const call=data=>new Promise((resolve,reject)=>{worker.onmessage=({data})=>data.type==='error'?reject(Error(data.message)):resolve(data);worker.onerror=e=>reject(Error(e.message));worker.postMessage(data);});
  const hash=async b=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b))).join(',');
  const decode=async(file,start)=>{const t=performance.now();const d=await call({type:'decode',file,start,startFrame:Math.round(start*info.codedFPS),frames:12,seconds:12/info.codedFPS,width:info.width,height:info.height,audio:true});return {seconds:(performance.now()-t)/1000,frames:d.frames,video:await hash(d.video),audio:await hash(d.pcm)};};
  try{await call({type:'warm',engine});const rows=[];for(const fraction of [.1,.5,.95]){const start=info.duration*fraction+.125;const a=await decode(file,start),b=await decode(original,start%refInfo.duration);rows.push({start,seconds:a.seconds,frames:a.frames,equalVideo:a.video===b.video,equalAudio:a.audio===b.audio});}return {engine,rows};}
  finally{worker.terminate();}
 },engine);
 for(const row of result.rows){expect(row.frames).toBe(12);expect(row.equalVideo).toBe(true);expect(row.equalAudio).toBe(true);expect(row.seconds).toBeLessThan(15);}
 console.log(JSON.stringify(result));
});
