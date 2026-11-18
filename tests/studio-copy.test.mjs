import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import rows from '../dist/studio-translations.mjs';
import {LANGUAGES,translateText} from '../dist/i18n.mjs';
test('new Studio strings resolve in every supported locale without changing technical values',()=>{
 const keys=new Set();
 for(const row of rows){assert.equal(row.length,LANGUAGES.length);assert.ok(!keys.has(row[0]));keys.add(row[0]);
  row.forEach((text,index)=>{assert.ok(typeof text==='string'&&text.trim());assert.equal(translateText(row[0],LANGUAGES[index]),text);});
 }
 for(const locale of LANGUAGES){assert.equal(translateText('MOBI_SUBME=2',locale),'MOBI_SUBME=2');assert.equal(translateText('2026.11.18u',locale),'2026.11.18u');}
 assert.match(translateText('True 3D · layout 1 · 48 coded eye frames/sec','es'),/^3D real · disposición 1/);
 assert.equal(translateText('2 / 4 logical cores','ja'),'2 / 4 論理コア');
});
test('published copy reflects recovery and supported audio without retired claims',()=>{
 const guide=readFileSync('dist/guide.html','utf8'),app=readFileSync('dist/app.mjs','utf8');
 for(const stale of ['Reloading the page clears the queue','there is no pause/resume or recovery after a refresh','44.1 kHz ADPCM'])assert.ok(!guide.includes(stale),stale);
 for(const feature of ['checksummed ranges','48 kHz','FastAudio','CIA Movie Builder','Scene-aware size allocation','HDR to SDR','Offline use and updates'])assert.ok(guide.includes(feature),feature);
 assert.ok(!app.includes('layout-0 WASM'));assert.ok(!app.includes('True 3D · layout 0'));
});
