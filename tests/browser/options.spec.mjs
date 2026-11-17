import {test,expect} from '@playwright/test';
import rows from '../../dist/translations.mjs';
const locales=['en','es','fr','de','pt','ja','ko','zh-Hans'];
test('eight local interface languages preserve controls, privacy preference and filenames',async({page})=>{
 const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto('/');await page.locator('#usageOptOut').check();
 await page.locator('.framing > summary').click();await page.locator('#fit').selectOption('fill');await page.locator('#aspect').selectOption('16/9');await page.locator('#speed').selectOption('fast');
 await page.locator('#file').setInputFiles({name:'Cancel',mimeType:'video/mp4',buffer:Buffer.from('form-only fixture')});
 for(const [index,locale]of locales.entries()){
  await page.locator('#interfaceLanguage').selectOption(locale);
  await expect(page.locator('html')).toHaveAttribute('lang',locale);
  await expect(page.locator('#convert span')).toHaveText(rows.find(r=>r[0]==='Convert to MOFLEX')[index]);
  await expect(page.locator('#fit')).toHaveValue('fill');await expect(page.locator('#aspect')).toHaveValue('16/9');await expect(page.locator('#speed')).toHaveValue('fast');
  await expect(page.locator('#usageOptOut')).toBeChecked();await expect(page.locator('#filename')).toHaveText('Cancel');
  for(const width of [390,768,1024,1280]){await page.setViewportSize({width,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);}
  await page.setViewportSize({width:390,height:844});
 }
 await page.locator('#interfaceLanguage').selectOption('es');
 await page.evaluate(()=>Object.defineProperty(document.getElementById('file').files[0],'size',{value:600*1024*1024}));
 let prompt='';page.once('dialog',async d=>{prompt=d.message();await d.dismiss();});
 await page.locator('#convert').click();expect(prompt).toContain('Es un archivo grande.');
 await page.evaluate(()=>document.getElementById('sampleStatus').textContent='Preview cancelled.');
 await expect(page.locator('#sampleStatus')).toHaveText('Vista previa cancelada.');
 await page.reload();await expect(page.locator('html')).toHaveAttribute('lang','es');await expect(page.locator('#usageOptOut')).toBeChecked();
 await page.locator('#interfaceLanguage').selectOption('en');await expect(page.locator('#convert span')).toHaveText('Convert to MOFLEX');
 expect(errors).toEqual([]);expect(requests.filter(url=>!url.startsWith('http://127.0.0.1:4173/')&&!url.startsWith('blob:'))).toEqual([]);
});
test('interface automatically follows a supported browser locale',async({browser})=>{
 const context=await browser.newContext({locale:'ja-JP'});try{
  const page=await context.newPage();await page.goto('http://127.0.0.1:4173/');
  await expect(page.locator('html')).toHaveAttribute('lang','ja');await expect(page.locator('#convert span')).toHaveText('MOFLEXに変換');
 }finally{await context.close();}
});
