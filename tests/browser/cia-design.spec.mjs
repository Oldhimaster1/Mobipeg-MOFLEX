import {test,expect} from '@playwright/test';
import {deflateSync} from 'node:zlib';

const crc32=bytes=>{
  let crc=0xffffffff;
  for(const byte of bytes){
    crc^=byte;
    for(let i=0;i<8;i++)crc=crc&1?(crc>>>1)^0xedb88320:crc>>>1;
  }
  return (crc^0xffffffff)>>>0;
};
function png(width,height){
  const chunk=(name,body)=>{
    const kind=Buffer.from(name),length=Buffer.alloc(4),check=Buffer.alloc(4);
    length.writeUInt32BE(body.length);check.writeUInt32BE(crc32(Buffer.concat([kind,body])));
    return Buffer.concat([length,kind,body,check]);
  };
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(width,0);ihdr.writeUInt32BE(height,4);ihdr[8]=8;ihdr[9]=6;
  const row=Buffer.alloc(1+width*4);
  for(let x=0;x<width;x++){row[1+4*x]=220;row[1+4*x+1]=40;row[1+4*x+2]=40;row[1+4*x+3]=255;}
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',deflateSync(Buffer.concat(Array.from({length:height},()=>row)))),chunk('IEND',Buffer.alloc(0))]);
}

test('CIA Builder generates a local Title ID and updates the live preview',async({page})=>{
  await page.goto('/cia.html');
  await expect(page.locator('#ciaTitle')).toBeVisible();
  await expect(page.locator('#ciaBuild')).toBeVisible();
  await expect(page.locator('#ciaAdvanced')).not.toHaveAttribute('open','');
  const initial=await page.locator('#ciaId').inputValue();
  expect(initial).toMatch(/^[CDE][0-9A-F]{4}$/);
  await page.locator('#ciaTitle').fill('My Test Collection');
  await expect(page.locator('#ciaLiveTitle')).toHaveText('My Test Collection');
  await expect(page.locator('#ciaLiveId')).toHaveText(initial);
  await page.locator('#ciaAdvanced').evaluate(el=>el.open=true);
  await page.locator('#ciaNewId').click();
  const next=await page.locator('#ciaId').inputValue();
  expect(next).toMatch(/^[CDE][0-9A-F]{4}$/);
  expect(next).not.toBe(initial);
  await page.locator('#ciaId').fill('D1234');
  await expect(page.locator('#ciaLiveId')).toHaveText('D1234');
  await page.reload();
  expect(await page.locator('#ciaId').inputValue()).toMatch(/^[CDE][0-9A-F]{4}$/);
});

test('cover editor exports exact CIA icon and thumbnail dimensions',async({page})=>{
  await page.goto('/cia.html');
  await page.locator('#ciaIcon').setInputFiles({name:'icon.png',mimeType:'image/png',buffer:png(80,100)});
  await page.locator('#ciaBanner').setInputFiles({name:'banner.png',mimeType:'image/png',buffer:png(400,200)});
  await expect(page.locator('#ciaLiveIcon')).toBeVisible();
  await expect(page.locator('#ciaLiveBanner')).toBeVisible();
  await page.locator('#ciaEditIcon').click();
  await expect(page.locator('#ciaArtworkDialog')).toBeVisible();
  await page.locator('#ciaArtworkZoom').fill('150');
  await page.locator('#ciaArtworkX').fill('45');
  await page.locator('#ciaArtworkApply').click();
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  const icon=await page.locator('#ciaIcon').evaluate(async el=>{
    const f=el.files[0],im=await createImageBitmap(f);
    const result={name:f.name,width:im.width,height:im.height,type:f.type};
    im.close();return result;
  });
  expect(icon).toEqual({name:'mobipeg-icon.png',width:48,height:48,type:'image/png'});
  await page.locator('#ciaEditBanner').click();
  await page.locator('#ciaArtworkFit').selectOption('fit');
  await page.locator('#ciaArtworkApply').click();
  const banner=await page.locator('#ciaBanner').evaluate(async el=>{
    const f=el.files[0],im=await createImageBitmap(f);
    const result={name:f.name,width:im.width,height:im.height,type:f.type};
    im.close();return result;
  });
  expect(banner).toEqual({name:'mobipeg-banner.png',width:200,height:120,type:'image/png'});
  await expect(page.locator('#ciaLiveBanner')).toBeVisible();
});

test('mobile builder keeps controls, previews and editor within the viewport',async({page})=>{
  await page.setViewportSize({width:360,height:720});
  await page.goto('/cia.html');
  await expect(page.locator('#ciaLiveTitle')).toBeVisible();
  await expect(page.locator('#ciaBuild')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);
  await page.locator('#ciaIcon').setInputFiles({name:'icon.png',mimeType:'image/png',buffer:png(60,60)});
  await page.locator('#ciaEditIcon').click();
  await expect(page.locator('#ciaArtworkDialog')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);
  await page.locator('#ciaArtworkCancel').click();
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
});

const movies=JSON.parse(process.env.MOBIPEG_TEST_CIA_MOVIES||'[]');
test('episode titles, ordering and artwork immediately update the live list',async({page})=>{
  test.skip(movies.length<2,'Provide two real MOFLEX fixtures in MOBIPEG_TEST_CIA_MOVIES');
  await page.goto('/cia.html');
  await page.locator('#ciaFiles').setInputFiles(movies.slice(0,2));
  await expect(page.locator('#ciaLiveEpisodes li')).toHaveCount(2);
  await page.getByRole('textbox',{name:'Episode 2 title'}).fill('Changed episode');
  await expect(page.locator('#ciaLiveEpisodes li').nth(1)).toContainText('Changed episode');
  await page.locator('#ciaEpisodes > li').nth(1).getByRole('button',{name:'↑'}).click();
  await expect(page.locator('#ciaLiveEpisodes li').first()).toContainText('Changed episode');
  await page.locator('#ciaEpisodes > li').first().getByLabel('Episode 1 banner').setInputFiles({name:'episode.png',mimeType:'image/png',buffer:png(400,300)});
  await expect(page.locator('#ciaLiveEpisodes li').first().locator('img')).toBeVisible();
  await page.locator('#ciaEpisodes > li').first().getByRole('button',{name:'Crop artwork'}).click();
  await page.locator('#ciaArtworkApply').click();
  await expect(page.locator('#ciaLiveEpisodes li').first().locator('img')).toBeVisible();
  const dimensions=await page.locator('#ciaEpisodes > li').first().getByLabel('Episode 1 banner').evaluate(async el=>{
    const bitmap=await createImageBitmap(el.files[0]),out=[bitmap.width,bitmap.height];
    bitmap.close();return out;
  });
  expect(dimensions).toEqual([200,120]);
});
