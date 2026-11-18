// Current deployable assets, independent of historical private fixture paths.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const hash=b=>createHash('sha256').update(b).digest('hex');
const read=p=>readFileSync(p);
const version=/const VERSION = '([^']+)'/.exec(read('isolation-sw.js').toString())[1];
assert.deepEqual(read('isolation-sw.js'),read('dist/isolation-sw.js'));
for(const root of ['','dist/']){
 const manifest=JSON.parse(read(root+'offline-assets.json'));
 assert.equal(manifest.version,version);
 for(const [name,expected] of Object.entries(manifest.files))assert.equal(hash(read(root+name)),expected,root+name);
 for(const engine of ['engine','engine-simd'])assert.equal(read(root+engine+'/mobipeg.wasm').subarray(0,4).toString('hex'),'0061736d');
}
const manifest=JSON.parse(read('dist/offline-assets.json'));
for(const name of Object.keys(manifest.files)){
 // Root uses a deliberate deployment translation re-export, cached transitively.
 if(name==='queue-translations.mjs'){
  assert.equal(read(name).toString(),"export {default} from './dist/queue-translations.mjs';\n");
 }else assert.deepEqual(read(name),read('dist/'+name),name);
}
for(const [path,expected] of Object.entries(JSON.parse(read('dist/engine/provenance.json')).hashes))assert.equal(hash(read(path)),expected,path);
assert.deepEqual(read('engine/provenance.json'),read('dist/engine/provenance.json'));
for(const name of ['worker.js','player-worker.js'])assert.equal(/const ENGINE_RELEASE = '([^']+)'/.exec(read(name).toString())[1],version,name+' release');
for(const name of ['app.mjs','parallel.mjs','player.mjs','trailer-editor.mjs'])for(const match of read(name).toString().matchAll(/(?:player-)?worker\.js\?v=([A-Za-z0-9]+)/g))assert.equal(match[1],version,name+' worker URL');
assert.equal(read('.nojekyll').length,0);
console.log(`Web release ${version}: source/deployment parity, offline hashes, real scalar/SIMD modules and provenance passed.`);
if(process.argv[2]){
 const base=new URL(process.argv[2]);
 const deployed=JSON.parse(read('offline-assets.json'));
 for(const [name,expected] of Object.entries(deployed.files)){
  const response=await fetch(new URL(name+'?release='+version,base),{cache:'no-store'});
  assert.equal(response.status,200,name);
  assert.equal(hash(Buffer.from(await response.arrayBuffer())),expected,'live '+name);
  if(name.endsWith('.wasm'))assert.match(response.headers.get('content-type'),/application\/wasm/,name);
 }
 const live=await fetch(new URL('offline-assets.json?release='+version,base),{cache:'no-store'});
 assert.deepEqual(await live.json(),JSON.parse(read('offline-assets.json')));
 const sw=await fetch(new URL('isolation-sw.js?release='+version,base),{cache:'no-store'});
 assert.equal(hash(Buffer.from(await sw.arrayBuffer())),hash(read('isolation-sw.js')));
 console.log(`Live Pages: all ${Object.keys(deployed.files).length} assets, offline manifest, service worker and WASM MIME types match this release.`);
}
