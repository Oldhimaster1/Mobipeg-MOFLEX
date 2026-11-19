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
  await page.locator('#ciaId').fill(initial);
  await expect(page.locator('#ciaIdCollision')).toContainText('generated in this browser before');
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
  await page.locator('#ciaArtworkZoom').evaluate(el=>{el.value='150';el.dispatchEvent(new Event('input',{bubbles:true}));});
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
  await page.locator('#ciaArtworkAspect').selectOption('square');
  await page.locator('#ciaArtworkApply').click();
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  const banner=await page.locator('#ciaBanner').evaluate(async el=>{
    const f=el.files[0],im=await createImageBitmap(f);
    const result={name:f.name,width:im.width,height:im.height,type:f.type};
    im.close();return result;
  });
  expect(banner).toEqual({name:'mobipeg-banner.png',width:200,height:120,type:'image/png'});
  const packed=await page.locator('#ciaIcon').evaluate(async el=>{
    const {makeSmdhArtwork}=await import('/cia-artwork.mjs');
    const original=new Uint8Array(0x36c0);
    original.set([83,77,68,72]);
    const encoded=await makeSmdhArtwork(el.files[0],original);
    return {size:encoded.byteLength,magic:String.fromCharCode(...encoded.slice(0,4)),
      hasTexture:encoded.slice(0x24c0).some(byte=>byte!==0)};
  });
  expect(packed).toEqual({size:0x36c0,magic:'SMDH',hasTexture:true});
  const episodeTexture=await page.locator('#ciaBanner').evaluate(async el=>{
    const {makeEpisodeArtwork}=await import('/cia-artwork.mjs');
    const original=new Blob([new Uint8Array(0x10020)]);
    const packed=await makeEpisodeArtwork(el.files[0],original);
    return {bytes:packed.size,payload:packed.size-32};
  });
  expect(episodeTexture).toEqual({bytes:0x10020,payload:65536});
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
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  await expect(page.locator('#ciaLiveEpisodes li').first().locator('img')).toBeVisible();
  const dimensions=await page.locator('#ciaEpisodes > li').first().getByLabel('Episode 1 banner').evaluate(async el=>{
    const bitmap=await createImageBitmap(el.files[0]),out=[bitmap.width,bitmap.height];
    bitmap.close();return out;
  });
  expect(dimensions).toEqual([200,120]);
});

// Control completion order explicitly: timers alone cannot reliably reproduce races.
async function delayArtwork(page, operation) {
  await page.evaluate(operation => {
    window.artworkJobs = [];
    window.closedArtworkBitmaps = 0;
    if (operation === 'decode') {
      const decode = window.createImageBitmap.bind(window);
      window.createImageBitmap = (...args) => new Promise((resolve, reject) => {
        window.artworkJobs.push(async (fail = false) => {
          if (fail) { reject(Error('Test decode failure')); return; }
          const bitmap = await decode(...args);
          const close = bitmap.close.bind(bitmap);
          bitmap.close = () => { window.closedArtworkBitmaps++; close(); };
          resolve(bitmap);
        });
      });
    } else {
      const toBlob = HTMLCanvasElement.prototype.toBlob;
      HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {
        toBlob.call(this, blob => {
          window.artworkJobs.push((fail = false) => callback(fail ? null : blob));
        }, ...args);
      };
    }
  }, operation);
}
async function finishArtwork(page, index, fail = false) {
  await expect.poll(() => page.evaluate(() => window.artworkJobs.length)).toBeGreaterThan(index);
  await page.evaluate(async ({index, fail}) => { await window.artworkJobs[index](fail); }, {index, fail});
}
async function chooseArtwork(page) {
  await page.goto('/cia.html');
  await page.locator('#ciaIcon').setInputFiles({name:'original-icon.png',mimeType:'image/png',buffer:png(80,100)});
  await page.locator('#ciaBanner').setInputFiles({name:'original-banner.png',mimeType:'image/png',buffer:png(400,200)});
}

test('artwork editor opens immediately and blocks edits until delayed decoding finishes', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'decode');
  await page.locator('#ciaEditIcon').click();
  await expect(page.locator('#ciaArtworkDialog')).toBeVisible();
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Loading image…');
  for (const id of ['Apply','Fit','Aspect','Zoom','X','Y'])
    await expect(page.locator('#ciaArtwork' + id)).toBeDisabled();
  await expect(page.locator('#ciaArtworkCancel')).toBeEnabled();
  await finishArtwork(page, 0);
  await expect(page.locator('#ciaArtworkApply')).toBeEnabled();
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Ready to edit.');
  await page.locator('#ciaArtworkApply').click();
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  expect(await page.locator('#ciaIcon').evaluate(el => el.files[0].name)).toBe('mobipeg-icon.png');
  expect(await page.evaluate(() => window.closedArtworkBitmaps)).toBe(1);
});

test('cancelled and outdated image decoding cannot reopen or replace the current editor', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'decode');
  await page.locator('#ciaEditIcon').click();
  await page.locator('#ciaArtworkCancel').click();
  await page.locator('#ciaEditBanner').click();
  await finishArtwork(page, 1);
  await expect(page.locator('#ciaArtworkApply')).toBeEnabled();
  await finishArtwork(page, 0);
  await expect(page.locator('#ciaArtworkHeading')).toHaveText('Edit HOME Menu banner');
  expect(await page.locator('#ciaArtworkCanvas').evaluate(el => [el.width,el.height])).toEqual([200,120]);
  expect(await page.evaluate(() => window.closedArtworkBitmaps)).toBe(1);
  await page.keyboard.press('Escape');
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  await page.locator('#ciaEditIcon').click();
  await page.keyboard.press('Escape');
  await finishArtwork(page, 2);
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  expect(await page.locator('#ciaIcon').evaluate(el => el.files[0].name)).toBe('original-icon.png');
  expect(await page.evaluate(() => window.closedArtworkBitmaps)).toBe(3);
});

test('cancelled PNG export cannot apply artwork or unlock a newer saving session', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'export');
  await page.locator('#ciaEditIcon').click();
  await page.locator('#ciaArtworkApply').click();
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Saving artwork…');
  await expect(page.locator('#ciaArtworkZoom')).toBeDisabled();
  await page.locator('#ciaArtworkCancel').click();
  await page.locator('#ciaEditBanner').click();
  await page.locator('#ciaArtworkApply').click();
  await finishArtwork(page, 0);
  await expect(page.locator('#ciaArtworkApply')).toBeDisabled();
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Saving artwork…');
  expect(await page.locator('#ciaIcon').evaluate(el => el.files[0].name)).toBe('original-icon.png');
  await finishArtwork(page, 1);
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  expect(await page.locator('#ciaBanner').evaluate(el => el.files[0].name)).toBe('mobipeg-banner.png');
});

test('PNG export failure allows retry and stale failure cannot change a newer editor', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'export');
  await page.locator('#ciaEditIcon').click();
  await page.locator('#ciaArtworkApply').click();
  await finishArtwork(page, 0, true);
  await expect(page.locator('#ciaArtworkStatus')).toContainText('Could not save artwork');
  await expect(page.locator('#ciaArtworkApply')).toBeEnabled();
  await page.locator('#ciaArtworkApply').click();
  await page.locator('#ciaArtworkCancel').click();
  await page.locator('#ciaEditBanner').click();
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Ready to edit.');
  await finishArtwork(page, 1, true);
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Ready to edit.');
  await page.locator('#ciaArtworkApply').click();
  await finishArtwork(page, 2);
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
});

test('decode failure and pagehide leave no live artwork session', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'decode');
  await page.locator('#ciaEditIcon').click();
  await finishArtwork(page, 0, true);
  await expect(page.locator('#ciaArtworkStatus')).toContainText('Could not open this image');
  await expect(page.locator('#ciaArtworkApply')).toBeDisabled();
  await page.locator('#ciaArtworkCancel').click();
  await page.locator('#ciaEditIcon').click();
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
  await finishArtwork(page, 1);
  await expect(page.locator('#ciaArtworkDialog')).not.toBeVisible();
  expect(await page.locator('#ciaIcon').evaluate(el => el.files[0].name)).toBe('original-icon.png');
  expect(await page.evaluate(() => window.closedArtworkBitmaps)).toBe(1);
});

test('new editor session supersedes pending decoding without requiring a close event', async ({page}) => {
  await chooseArtwork(page);
  await delayArtwork(page, 'decode');
  await page.locator('#ciaEditIcon').click();
  // Simulate another application action selecting different artwork while decoding.
  await page.locator('#ciaEditBanner').evaluate(el => el.click());
  await finishArtwork(page, 1);
  await finishArtwork(page, 0);
  await expect(page.locator('#ciaArtworkHeading')).toHaveText('Edit HOME Menu banner');
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Ready to edit.');
  expect(await page.evaluate(() => window.closedArtworkBitmaps)).toBe(1);
  await page.locator('#ciaEditIcon').evaluate(el => el.click());
  await page.locator('#ciaEditBanner').evaluate(el => el.click());
  await finishArtwork(page, 2, true);
  await expect(page.locator('#ciaArtworkStatus')).toHaveText('Loading image…');
  await expect(page.locator('#ciaArtworkApply')).toBeDisabled();
  await finishArtwork(page, 3);
  await expect(page.locator('#ciaArtworkApply')).toBeEnabled();
});
