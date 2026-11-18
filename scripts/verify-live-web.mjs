// Real Pages test. Fixtures and downloaded outputs stay outside the repository.
import {createRequire} from 'node:module';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const require=createRequire(new URL('../tests/browser/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const phase=process.argv[2];
if(!['before','after'].includes(phase))throw Error('Use before or after; set MOBIPEG_LIVE_WORK outside the checkout.');
const work=process.env.MOBIPEG_LIVE_WORK;
if(!work||resolve(work).startsWith(resolve('.')+'/'))throw Error('Choose an external test directory');
mkdirSync(work,{recursive:true});
const url='https://oldhimaster1.github.io/Mobipeg-MOFLEX/';
const version=/const VERSION = '([^']+)'/.exec(readFileSync('isolation-sw.js','utf8'))[1];
let context=await chromium.launchPersistentContext(resolve(work,'profile'),{headless:true,acceptDownloads:true,...(process.env.MOBIPEG_TEST_IGNORE_HTTPS_ERRORS==='1'?{ignoreHTTPSErrors:true,args:['--ignore-certificate-errors']}: {})});
await context.addInitScript(()=>{try{localStorage.setItem('mobipeg-usage-opt-out','1');}catch{}});
let page=context.pages()[0]||await context.newPage();
const evidence={phase,checkedAt:new Date().toISOString(),url,testProxyTLSBypass:process.env.MOBIPEG_TEST_IGNORE_HTTPS_ERRORS==='1'};
const checks=[],engineRequests=[];
context.on('request',r=>{if(r.serviceWorker())return;if(/\/engine(?:-simd)?\/mobipeg\.(?:js|wasm)/.test(r.url()))engineRequests.push(r.url());});
try{
 await page.goto(url,{waitUntil:'domcontentloaded'});
 await expect(page.locator('#offlineSetup')).toBeVisible({timeout:60000});
 await expect.poll(()=>page.evaluate(()=>crossOriginIsolated),{timeout:30000}).toBe(true);
 if(phase==='after'){
  await page.evaluate(async()=>{const r=await navigator.serviceWorker.getRegistration();await r.update();});
  // Existing tabs retain their old active worker until closed. Allow the normal
  // lifecycle to activate the prepared update without deleting user caches.
  await expect.poll(()=>page.evaluate(async expected=>{
   const r=await navigator.serviceWorker.getRegistration();
   return !!r.waiting || (!r.installing && (await (await fetch('offline-assets.json')).json()).version===expected);
  },version),{timeout:120000}).toBe(true);
  await page.waitForTimeout(3000);
  for(const tab of context.pages())await tab.close();
  page=await context.newPage();await page.goto(url,{waitUntil:'domcontentloaded'});
  await expect(page.locator('#budgetMode')).toBeAttached({timeout:60000});
 }
 if(await page.locator('#offlineSetup').isEnabled())await page.locator('#offlineSetup').click();
 await expect(page.locator('#offlineStatus')).toContainText('Ready offline',{timeout:120000});
 evidence.caches=await page.evaluate(()=>caches.keys());
 if(phase==='before'){
  evidence.manifest=await page.evaluate(async()=>{const r=await fetch('offline-assets.json',{cache:'no-store'});return (await r.json()).version;});
 }else{
  await expect.poll(()=>page.evaluate(()=>caches.keys()),{timeout:60000}).toEqual([`mobipeg-offline-/Mobipeg-MOFLEX/-${version}`]);
  expect(await page.locator('#budgetMode').inputValue()).toBe('scene');
  checks.push('prior offline cache replaced by release cache through service-worker lifecycle');
  for(const engine of ['scalar','simd']){
   await page.goto(url);await expect(page.locator('#convert')).toBeVisible();
   await page.locator('#file').setInputFiles(process.env.MOBIPEG_LIVE_SOURCE);
   await page.locator('#engine').evaluate(el=>el.closest('details').open=true);
   await page.locator('#engine').selectOption(engine);
   await page.locator('#workers').fill('1');
   await page.locator('#resolution').selectOption('256x144');
   await page.locator('#speed').selectOption('fast');
   await page.locator('#convert').click();
   await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:180000});
   const download=page.waitForEvent('download');await page.locator('#download').click();
   const path=resolve(work,engine+'.moflex');await (await download).saveAs(path);
   execFileSync('native/local/bin/ffmpeg',['-v','error','-xerror','-i',path,'-f','null','-']);
   checks.push(engine+' live conversion, download and independent full decoding');
  }
  await page.goto(url+'player.html');
  await page.locator('#movieFile').setInputFiles(resolve(work,'simd.moflex'));
  await expect(page.locator('#play')).toBeEnabled({timeout:30000});
  await page.locator('#play').click();
  await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:60000});
  await page.screenshot({path:resolve(work,'live-player.png')});
  checks.push('live player launches converted movie');
  await page.goto(url+'cia.html');
  await page.locator('#ciaFiles').setInputFiles(JSON.parse(process.env.MOBIPEG_LIVE_MOVIES));
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(2);
  await page.locator('#ciaTitle').fill('Live release test');
  await page.locator('#ciaPublisher').fill('Local test');
  await page.locator('#ciaId').fill('C4567');
  await page.locator('#ciaTemplate').setInputFiles(process.env.MOBIPEG_TEST_CIA_TEMPLATE);
  const pending=page.waitForEvent('download');await page.locator('#ciaBuild').click();
  const cia=resolve(work,'live.cia');await (await pending).saveAs(cia);
  evidence.cia=JSON.parse(execFileSync('python3',['native/cia_builder.py','verify',cia],{encoding:'utf8'}));
  await page.screenshot({path:resolve(work,'live-cia.png')});
  checks.push('live two-episode CIA generation, download and independent native verification');
  expect(engineRequests.length).toBeGreaterThan(0);
  for(const request of engineRequests)expect(new URL(request).searchParams.get('v')).toBe(version);
  evidence.engineReleaseRequests=engineRequests.length;
  await context.close();
  // Playwright's page offline flag does not reliably block service-worker
  // networking. Restart the same profile behind an unreachable proxy instead.
  context=await chromium.launchPersistentContext(resolve(work,'profile'),{headless:true,acceptDownloads:true,
    proxy:{server:'http://127.0.0.1:9'},ignoreHTTPSErrors:process.env.MOBIPEG_TEST_IGNORE_HTTPS_ERRORS==='1',
    ...(process.env.MOBIPEG_TEST_IGNORE_HTTPS_ERRORS==='1'?{args:['--ignore-certificate-errors']}:{} )});
  await context.addInitScript(()=>{try{localStorage.setItem('mobipeg-usage-opt-out','1');}catch{}});
  page=context.pages()[0]||await context.newPage();await page.goto(url);
  await expect(page.locator('#convert')).toBeVisible();
  expect(await page.evaluate(()=>crossOriginIsolated)).toBe(true);
  expect(await page.evaluate(async()=>{try{await fetch('never-cached-network-probe-'+Date.now());return false;}catch{return true;}})).toBe(true);
  await page.locator('#file').setInputFiles(process.env.MOBIPEG_LIVE_SOURCE);
  await page.locator('#workers').fill('1');await page.locator('#resolution').selectOption('256x144');
  await page.locator('#speed').selectOption('fast');await page.locator('#convert').click();
  await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:180000});
  await page.goto(url+'cia.html');await expect(page.locator('#ciaBuild')).toBeVisible();
  checks.push('offline reload, isolation, real conversion and CIA editor availability');
 }
 evidence.checks=checks;evidence.passed=true;
 writeFileSync(resolve(work,phase+'.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence));
}finally{await context.close();}
