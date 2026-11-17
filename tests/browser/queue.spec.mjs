import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

test('queue preserves per-video settings and releases each result before continuing',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
    Object.defineProperty(navigator,'storage',{value:{estimate:async()=>({quota:2_000_000_000,usage:250_000_000}),getDirectory:undefined},configurable:true});
    window.workerMessages=[];
    window.Worker=class{
      constructor(){this.dead=false;}
      terminate(){this.dead=true;}
      postMessage(message){
        window.workerMessages.push(message);
        setTimeout(()=>{
          if(this.dead)return;
          if(message.type==='convert')this.onmessage?.({data:{type:'candidate',blob:new Blob(['moflex']),frames:24,seconds:1,audio:false,q:30,attempts:1}});
          else if(message.type==='verify')this.onmessage?.({data:{type:'verified',kind:message.kind}});
        },10);
      }
    };
  });
  await page.goto('/');
  await page.locator('#file').setInputFiles([
    {name:'episode-one.mp4',mimeType:'video/mp4',buffer:Buffer.from('first')},
    {name:'episode-two.mp4',mimeType:'video/mp4',buffer:Buffer.from('second')},
  ]);
  await expect(page.locator('.queue-item')).toHaveCount(2);
  await expect(page.locator('#queuePanel')).toBeVisible();

  // Each item retains the settings it had when last selected.
  await page.locator('#resolution').selectOption('400x192');
  await page.locator('.queue-item').nth(1).locator('.queue-select').click();
  await page.locator('#resolution').selectOption('320x240');
  await page.locator('.queue-item').nth(0).locator('.queue-select').click();
  await expect(page.locator('#resolution')).toHaveValue('400x192');
  await page.locator('.queue-item').nth(1).locator('.queue-select').click();
  await expect(page.locator('#resolution')).toHaveValue('320x240');
  await page.locator('.queue-item').nth(0).locator('.queue-select').click();

  await page.locator('#startQueue').click();
  await expect(page.locator('.queue-item').nth(0)).toContainText('ready',{timeout:10000});
  await expect(page.locator('#queueNext')).toBeDisabled();
  let wait=page.waitForEvent('download');await page.locator('#download').click();await wait;
  await expect(page.locator('#queueNext')).toBeEnabled();await page.locator('#queueNext').click();
  await expect(page.locator('.queue-item').nth(0)).toContainText('done');
  await expect(page.locator('.queue-item').nth(1)).toContainText('ready',{timeout:10000});
  wait=page.waitForEvent('download');await page.locator('#download').click();await wait;await page.locator('#queueNext').click();
  await expect(page.locator('#stage')).toHaveText('Queue complete');
  await expect(page.locator('.queue-item').nth(1)).toContainText('done');

  const settings=await page.evaluate(()=>window.workerMessages.filter(x=>x.type==='convert').map(x=>x.settings.resolution));
  expect(settings).toEqual(['400x192','320x240']);
  expect(errors).toEqual([]);
});

test('queue can reorder, remove, cancel and continue without encoding in parallel',async({page})=>{
  await page.addInitScript(()=>{
    window.activeWorkers=0;window.maxActiveWorkers=0;
    window.Worker=class{
      constructor(){this.dead=false;window.activeWorkers++;window.maxActiveWorkers=Math.max(window.maxActiveWorkers,window.activeWorkers);}
      terminate(){if(!this.dead){this.dead=true;window.activeWorkers--;}}
      postMessage(){}
    };
  });
  await page.goto('/');
  await page.locator('#file').setInputFiles([
    {name:'a.mp4',mimeType:'video/mp4',buffer:Buffer.from('a')},
    {name:'b.mp4',mimeType:'video/mp4',buffer:Buffer.from('b')},
    {name:'c.mp4',mimeType:'video/mp4',buffer:Buffer.from('c')},
  ]);
  await page.locator('.queue-item').nth(2).getByRole('button',{name:'↑'}).click();
  await expect(page.locator('.queue-item').nth(1)).toContainText('c.mp4');
  await page.locator('.queue-item').nth(2).getByRole('button',{name:'Remove'}).click();
  await expect(page.locator('.queue-item')).toHaveCount(2);
  await page.locator('#startQueue').click();await page.locator('#cancel').click();
  await expect(page.locator('.queue-item').nth(0)).toContainText('cancelled');
  await expect(page.locator('#queueNext')).toHaveText('Skip item & continue');await page.locator('#queueNext').click();
  await expect(page.locator('.queue-item').nth(1)).toContainText('encoding');
  expect(await page.evaluate(()=>window.maxActiveWorkers)).toBe(1);
  await page.locator('#cancel').click();await page.locator('#queueNext').click();
  await expect(page.locator('#stage')).toHaveText('Queue complete');
});

test('two real videos encode, verify and download serially',async({page},testInfo)=>{
  test.setTimeout(150000);
  const work=mkdtempSync(join(tmpdir(),'mobipeg-queue-'));
  const ffmpeg=resolve('native/local/bin/ffmpeg');
  const inputs=['red','blue'].map((color,index)=>{
    const path=join(work,`${color}.mp4`);
    execFileSync(ffmpeg,['-v','error','-f','lavfi','-i',`color=${color}:s=160x90:r=10:d=0.6`,'-f','lavfi','-i',`sine=frequency=${440+index*220}:sample_rate=44100:duration=0.6`,'-shortest','-c:v','mpeg4','-q:v','5','-c:a','aac',path]);
    return path;
  });
  await page.goto('/');
  await page.locator('#file').setInputFiles(inputs);
  await page.locator('#resolution').selectOption('256x144');
  await page.locator('#fps').selectOption('10');
  await page.locator('#preset').selectOption('small');
  await page.locator('#startQueue').click();
  for(let i=0;i<2;i++){
    await expect(page.locator('.queue-item').nth(i)).toContainText('ready',{timeout:120000});
    const pending=page.waitForEvent('download');
    await page.locator('#download').click();
    const download=await pending,output=testInfo.outputPath(`queue-${i}.moflex`);
    await download.saveAs(output);
    execFileSync(ffmpeg,['-v','error','-xerror','-i',output,'-f','null','-']);
    await page.locator('#queueNext').click();
  }
  await expect(page.locator('#stage')).toHaveText('Queue complete');
});
