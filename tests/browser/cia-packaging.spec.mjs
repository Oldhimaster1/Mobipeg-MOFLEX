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
  await page.locator("#ciaTemplate").setInputFiles(template);
  await page.locator("#ciaTitle").fill("Browser integration");
  await page.locator("#ciaPublisher").fill("Local test");
  await page.locator("#ciaId").fill("C2468");
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
    expect(rows).toEqual(Array.from({length:count},(_,i)=>Array(12).fill('Episode '+i).join(',')));
  }
  await expect(page.locator("#ciaStatus")).toContainText(
    "content hash verified",
  );
});
