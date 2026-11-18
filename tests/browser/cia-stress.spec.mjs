import {test,expect} from '@playwright/test';
import {createReadStream,linkSync,mkdirSync,statSync,readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {join} from 'node:path';
const digest=async path=>{const hash=createHash('sha256');for await(const bytes of createReadStream(path))hash.update(bytes);return hash.digest('hex');};

test('real oversized collection splits into verified FAT32 CIAs and survives reload',async({playwright},testInfo)=>{
  const movie=process.env.MOBIPEG_TEST_CIA_STRESS_MOVIE,template=process.env.MOBIPEG_TEST_CIA_TEMPLATE;
  test.skip(!movie||!template,'Supply a real long MOFLEX and a compatible collection template.');
  const size=statSync(movie).size;
  expect(size*6).toBeGreaterThan(0xffffffff);
  expect(size*5+statSync(template).size+64*1024**2).toBeLessThan(0xffffffff);
  const inputDir=testInfo.outputPath('inputs');mkdirSync(inputDir,{recursive:true});
  const files=Array.from({length:6},(_,i)=>{const path=join(inputDir,'Episode '+(i+1)+'.moflex');linkSync(movie,path);return path;});
  const original=await digest(movie);
  // Persistent Chromium uses real disk-backed OPFS rather than the smaller
  // incognito quota used by the ordinary Playwright page fixture.
  const context=await playwright.chromium.launchPersistentContext(testInfo.outputPath('profile'),{headless:true});
  try{
  const page=await context.newPage();
  await page.goto('/cia.html');await page.locator('#ciaFiles').setInputFiles(files);
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(6);
  await page.locator('#ciaTitle').fill('Large split collection');
  await page.locator('#ciaPublisher').fill('Local synthetic test');
  await page.locator('#ciaId').fill('C3000');
  await page.locator('#ciaTemplate').setInputFiles(template);
  await page.locator('#ciaSplit').check();await page.locator('#ciaStage').check();
  const downloads=[];page.on('download',file=>downloads.push(file));
  const started=performance.now();await page.locator('#ciaBuild').click();
  await expect(page.locator('#ciaStatus')).toContainText('CIA built and content hash verified',{timeout:1100000});
  expect(downloads).toHaveLength(2);
  for(const [part,file] of downloads.entries()){
    const output=testInfo.outputPath('part-'+part+'.cia');await file.saveAs(output);
    expect(statSync(output).size).toBeLessThanOrEqual(0xffffffff);
    const verified=JSON.parse(execFileSync('python3',['native/cia_builder.py','verify',output],{encoding:'utf8'}));
    expect(verified.title_id).toBe(part===0?'000400000C300000':'000400000C300100');
    if(process.env.MOBIPEG_CIA_BACKEND){
      const extracted=testInfo.outputPath('extracted-'+part);
      execFileSync(process.env.MOBIPEG_CIA_BACKEND,['-ec',output,extracted]);
      for(let i=0;i<(part===0?5:1);i++)expect(await digest(join(extracted,'romfs/movie/movie_'+i+'.moflex'))).toBe(original);
      const titles=readFileSync(join(extracted,'romfs/movie/movie_title.csv')).toString('utf16le').replace(/^\ufeff/,'').trim().split(/\r?\n/).slice(1);
      expect(titles).toEqual(Array.from({length:part===0?5:1},(_,i)=>Array(12).fill('Episode '+(part===0?i+1:6)).join(',')));
    }
  }
  console.log(JSON.stringify({episodes:6,parts:2,inputBytes:size*6,buildAndVerificationSeconds:(performance.now()-started)/1000}));
  await page.reload();await expect(page.locator('#ciaSaved').getByRole('button',{name:/^Download /})).toHaveCount(2);
  }finally{await context.close();}
});
