import {test,expect} from '@playwright/test';
import rows from '../../dist/studio-translations.mjs';
const locales=['en','es','fr','de','pt','ja','ko','zh-Hans'];
const text=(key,index)=>rows.find(row=>row[0]===key)[index];
test('current Studio copy and new controls translate in all eight locales',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/');
 await page.locator('#budgetMode').evaluate(el=>el.closest('details').open=true);
 await expect(page.locator('#studioRelease')).toHaveText('2026.11.18v');
 await page.locator('input[name=mode][value=half-sbs]').check();
 for(const [index,locale]of locales.entries()){
  await page.locator('#interfaceLanguage').selectOption(locale);
  await expect(page.locator('h1')).toHaveText(text('Convert video for Nintendo 3DS',index));
  await expect(page.locator('#budgetMode option[value=scene]')).toHaveText(text('Scene-aware — texture and motion',index));
  await expect(page.locator('#budgetMode option[value=uniform]')).toHaveText(text('Uniform — previous time-based allocation',index));
  await expect(page.locator('#hdrMode option[value=auto]')).toHaveText(text('Automatic — PQ / HLG to SDR',index));
  await expect(page.locator('#audioCodec option[value=fastaudio]')).toHaveText(text('FastAudio — smaller, experimental on 3DS',index));
  await expect(page.locator('#modehint')).toContainText(text('True 3D · layout 1',index));
  expect(await page.locator('#preset').inputValue()).toBe('quality');
  expect(await page.locator('#budgetMode').inputValue()).toBe('scene');
  expect(await page.locator('#audioCodec').inputValue()).toBe('adpcm');
  expect(await page.locator('#studioRelease').textContent()).toBe('2026.11.18v');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 }
 await page.reload();await expect(page.locator('html')).toHaveAttribute('lang','zh-Hans');
 await expect(page.locator('h1')).toHaveText(text('Convert video for Nintendo 3DS',7));
});
test('Guide explains current queue recovery audio and browser features',async({page})=>{
 await page.goto('/guide.html');
 const guide=await page.locator('article').innerText();
 for(const stale of ['Reloading the page clears the queue','there is no pause/resume or recovery after a refresh','44.1 kHz ADPCM'])expect(guide).not.toContain(stale);
 for(const feature of ['checksummed ranges','48 kHz','FastAudio','CIA Movie Builder','Scene-aware size allocation','HDR to SDR','Offline use and updates','4,294,967,295'])expect(guide).toContain(feature);
 await expect(page.locator('a[href="cia.html"]')).toBeVisible();
 await expect(page.locator('a[href="player.html"]')).toBeVisible();
});
