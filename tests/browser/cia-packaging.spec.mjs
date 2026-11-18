import {readFileSync,createReadStream,statSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const fileHash=async path=>{const hash=createHash('sha256');for await(const bytes of createReadStream(path))hash.update(bytes);return hash.digest('hex');};
import {join} from 'node:path';
import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
const template = process.env.MOBIPEG_TEST_CIA_TEMPLATE;
const movies = JSON.parse(process.env.MOBIPEG_TEST_CIA_MOVIES || "[]");
for(const count of [1,2,5,10,20,27])test("browser builds a collection of "+count+" episodes", async ({
  page,browser,
}, testInfo) => {
  test.skip(
    !template || movies.length<count,
    "Provide a local compatible CIA template and its movie inputs",
  );
  test.setTimeout(Number(process.env.MOBIPEG_TEST_CIA_TIMEOUT||180000));
  await page.goto("/cia.html");
  await page.locator("#ciaFiles").setInputFiles(movies.slice(0,count));
  await expect(page.locator("#ciaEpisodes > li")).toHaveCount(count);
  for(let i=0;i<count;i++)await page.getByRole('textbox',{name:'Episode '+(i+1)+' title',exact:true}).fill('Episode '+i);
  if(process.env.MOBIPEG_TEST_CIA_ARTWORK){
    await page.locator('#ciaIcon').setInputFiles(process.env.MOBIPEG_TEST_CIA_ARTWORK);
    await page.locator('#ciaBanner').setInputFiles(process.env.MOBIPEG_TEST_CIA_ARTWORK);
    if(process.env.MOBIPEG_TEST_CIA_WAV)await page.locator('#ciaBannerAudio').setInputFiles(process.env.MOBIPEG_TEST_CIA_WAV);
    await page.getByLabel('Episode 1 banner',{exact:true}).setInputFiles(process.env.MOBIPEG_TEST_CIA_ARTWORK);
  }
  await page.locator("#ciaTemplate").setInputFiles(template);
  await page.locator("#ciaTitle").fill("Browser integration");
  await page.locator("#ciaPublisher").fill("Local test");
  await page.locator("#ciaId").fill("C2468");
  let stored=await page.locator("#ciaStage").isEnabled();
  if(stored&&process.env.MOBIPEG_TEST_CIA_PROFILE){
    const capacity=await page.evaluate(async()=>{const e=await navigator.storage.estimate();return e.quota-e.usage;});
    if(capacity<movies.slice(0,count).reduce((n,path)=>n+statSync(path).size,0)+statSync(template).size+64*1024**2)stored=false;
  }
  if(stored)await page.locator("#ciaStage").check();
  let peakRSS=0,timer,session;
  if(process.env.MOBIPEG_TEST_CIA_PROFILE&&browser.browserType().name()==='chromium'){
    session=await browser.newBrowserCDPSession();
    timer=setInterval(async()=>{
      try{
        const {processInfo}=await session.send('SystemInfo.getProcessInfo');
        let rss=0;for(const process of processInfo){try{rss+=Number(/VmRSS:\s+(\d+)/.exec(readFileSync('/proc/'+process.id+'/status','utf8'))?.[1]||0)*1024;}catch{}}
        peakRSS=Math.max(peakRSS,rss);
      }catch{}
    },1000);timer.unref();
  }
  const started=performance.now();
  const download = page.waitForEvent("download");
  await page.locator("#ciaBuild").click();
  const file = await download,
    path = testInfo.outputPath("browser.cia");
  try{await file.saveAs(path);}finally{clearInterval(timer);await session?.detach();}
  if(process.env.MOBIPEG_TEST_CIA_PROFILE){
    const report={episodes:count,bytes:statSync(path).size,seconds:(performance.now()-started)/1000,peakAggregateBrowserRSS:peakRSS,persistenceRequested:stored};
    writeFileSync(testInfo.outputPath('memory.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }
  const result = JSON.parse(
    execFileSync("python3", ["native/cia_builder.py", "verify", path], {
      encoding: "utf8",
    }),
  );
  expect(result.title_id).toBe("000400000C246800");
  if(process.env.MOBIPEG_CIA_BACKEND){
    const extracted=testInfo.outputPath('extracted');
    execFileSync(process.env.MOBIPEG_CIA_BACKEND,['-ec',path,extracted]);
    for(let i=0;i<count;i++){const actual=join(extracted,'romfs/movie/movie_'+i+'.moflex');expect(statSync(actual).size).toBe(statSync(movies[i]).size);expect(await fileHash(actual)).toBe(await fileHash(movies[i]));}
    const rows=readFileSync(join(extracted,'romfs/movie/movie_title.csv')).toString('utf16le').replace(/^\ufeff/,'').trim().split(/\r?\n/).slice(1);
    if(process.env.MOBIPEG_TEST_CIA_ARTWORK){
      const icon=readFileSync(join(extracted,'exefs/icon.bin'));
      const thumbnail=readFileSync(join(extracted,'romfs/movie/movie_0.bimg'));
      expect(icon.readUInt16LE(0x2040)).toBeGreaterThanOrEqual(0xf000);
      expect(thumbnail.readUInt16LE(32)).toBeGreaterThanOrEqual(0xf000);
      const preview=testInfo.outputPath('banner-preview.png');
      execFileSync(process.env.MOBIPEG_CIA_BACKEND,['-gp',join(extracted,'parameters.vi9p'),'1',preview]);
      const rgb=execFileSync('ffmpeg',['-v','error','-i',preview,'-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','pipe:1']);
      expect(rgb[0]).toBeGreaterThan(200);expect(rgb[1]).toBeLessThan(30);expect(rgb[2]).toBeLessThan(30);
      if(process.env.MOBIPEG_TEST_CIA_WAV){const banner=readFileSync(join(extracted,'exefs/banner.bin')),offset=banner.readUInt32LE(132);expect(banner.subarray(offset,offset+4).toString()).toBe('CWAV');}

    }
    expect(rows).toEqual(Array.from({length:count},(_,i)=>Array(12).fill('Episode '+i).join(',')));
  }
  await expect(page.locator("#ciaStatus")).toContainText(
    "content hash verified",
  );
  if(!stored)return; // OPFS is absent or the optional benchmark exceeds its available quota.
  await page.reload();
  await expect(page.locator("#ciaSaved")).toContainText("Download movie-");
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#ciaSaved').getByRole('button',{name:'Delete',exact:true}).click();
  await expect(page.locator('#ciaSaved button')).toHaveCount(0);
});
