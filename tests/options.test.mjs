import test from 'node:test';
import assert from 'node:assert/strict';
import {ASPECTS,validate,filters,environment,convert} from '../dist/core.mjs';
import {LANGUAGES,normalizeLanguage,translateText} from '../dist/i18n.mjs';
import rows from '../dist/translations.mjs';
const base={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:null,maxMB:null};
test('Fast changes only search effort; original and explicit advanced values are preserved',()=>{
 assert.deepEqual(environment({...base,speed:'original'}),environment(base));
 const fast=environment({...base,speed:'fast'}),original=environment(base);assert.equal(fast.MOBI_SUBME,'2');
 assert.deepEqual({...fast,MOBI_SUBME:original.MOBI_SUBME},original);
 assert.deepEqual(filters({...base,speed:'fast'}),filters(base));
 assert.equal(environment({...base,speed:'fast',advanced:{subme:7}}).MOBI_SUBME,'7');
 assert.throws(()=>validate({...base,speed:'turbo'}));
});
test('aspect crops are per-eye, centered, SAR-aware and applied after manual edges',()=>{
 for(const aspect of ASPECTS)for(const mode of ['2d','full-sbs','half-sbs']){
  const s={...base,mode,crop:{fit:'fit',aspect,left:16}};validate(s);const f=filters(s)[1];
  if(aspect==='source')assert.doesNotMatch(f,/trunc\(min/);
  else{
   assert.ok(f.includes(`ih*(${aspect})/sar`));assert.ok(f.includes(`iw*sar/(${aspect})`));
   assert.ok(f.indexOf('crop=iw-16')<f.indexOf("crop=w='"));
   if(mode==='half-sbs')assert.ok(f.indexOf('setsar=sar*2')<f.indexOf("crop=w='"));
   assert.equal(f.split("crop=w='").length-1,mode==='2d'?1:2);
  }
 }
 assert.deepEqual(filters({...base,crop:{fit:'fit',aspect:'source'}}),filters(base));
 assert.throws(()=>validate({...base,crop:{fit:'fit',aspect:'1/0'}}));
});
test('known movie metadata skips only the redundant inspection, not encoding or verification',async()=>{
 const calls=[];
 const result=await convert({source:new Blob(['source']),settings:base,clip:{start:30,seconds:1},media:{duration:120,audio:true},run:async(args,files,out)=>{
  calls.push({args,out});if(out)return {frames:24,blob:new Blob(['moflex'])};return {frames:24,seconds:1};
 }});
 assert.equal(result.q,30);assert.equal(result.audio,true);assert.equal(calls.length,4);
 assert.equal(calls.some(x=>x.args.length===3),false);assert.equal(calls.filter(x=>x.args.includes('null')).length,2);
 for(const media of [{duration:0,audio:true},{duration:Infinity,audio:false},{duration:1,audio:'yes'}])await assert.rejects(()=>convert({settings:base,source:new Blob(),clip:{start:0,seconds:1},media,run:()=>assert.fail('must reject before executing')}));
});
test('all interface languages have complete catalog rows and safe locale fallback',()=>{
 const seen=new Set();for(const row of rows){assert.equal(row.length,LANGUAGES.length);assert.equal(seen.has(row[0]),false);seen.add(row[0]);for(const text of row)assert.ok(typeof text==='string'&&text.length>0);}
 assert.equal(normalizeLanguage('es-MX'),'es');assert.equal(normalizeLanguage('pt-BR'),'pt');assert.equal(normalizeLanguage('zh-CN'),'zh-Hans');assert.equal(normalizeLanguage('zh-Hans-SG'),'zh-Hans');assert.equal(normalizeLanguage('zh-TW'),'en');assert.equal(normalizeLanguage('invalid'),'en');
 for(const lang of LANGUAGES){assert.ok(translateText('Convert to MOFLEX',lang).includes('MOFLEX'));assert.equal(translateText('MOBI_SUBME=2',lang),'MOBI_SUBME=2');}
 assert.equal(translateText('LONG MOVIE · CHAPTER 2','es'),'PELÍCULA LARGA · SEGMENTO 2');assert.equal(translateText('Assembling movie · chapter 3/3','ja'),'動画を結合中 · チャプター 3/3');assert.match(translateText('12.30 MB · 3,120 coded frames · Q30 · ADPCM audio · UNVERIFIED','es'),/fotogramas codificados.*SIN VERIFICAR/);assert.equal(translateText('   ','es'),'   ');
 assert.equal(translateText(' Cancel ','es'),' Cancelar ');assert.equal(translateText('Rendering framed source…','es'),'Generando imagen encuadrada…');assert.equal(translateText(' 0:10 elapsed','es'),' 0:10 transcurrido');
});
