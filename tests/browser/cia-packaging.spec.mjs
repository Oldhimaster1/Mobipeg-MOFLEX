import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
const template = process.env.MOBIPEG_TEST_CIA_TEMPLATE;
const movies = JSON.parse(process.env.MOBIPEG_TEST_CIA_MOVIES || "[]");
for(const count of [1,2,5,10,20,27])test("browser builds a collection of "+count+" episodes", async ({
  page,
}, testInfo) => {
  test.skip(
    !template || movies.length<count,
    "Provide a local compatible CIA template and its movie inputs",
  );
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
  await page.locator("#ciaStage").check();
  const download = page.waitForEvent("download");
  await page.locator("#ciaBuild").click();
  const file = await download,
    path = testInfo.outputPath("browser.cia");
  await file.saveAs(path);
  const result = JSON.parse(
    execFileSync("python3", ["native/cia_builder.py", "verify", path], {
      encoding: "utf8",
    }),
  );
  expect(result.title_id).toBe("000400000C246800");
  if(process.env.MOBIPEG_CIA_BACKEND){
    const extracted=testInfo.outputPath('extracted');
    execFileSync(process.env.MOBIPEG_CIA_BACKEND,['-ec',path,extracted]);
    for(let i=0;i<count;i++)expect(readFileSync(join(extracted,'romfs/movie/movie_'+i+'.moflex'))).toEqual(readFileSync(movies[i]));
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
  await page.reload();
  await expect(page.locator("#ciaSaved")).toContainText("Download movie-");
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#ciaSaved').getByRole('button',{name:'Delete',exact:true}).click();
  await expect(page.locator('#ciaSaved button')).toHaveCount(0);
});
