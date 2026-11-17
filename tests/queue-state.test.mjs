import test from 'node:test';
import assert from 'node:assert/strict';
import {QUEUE_STORAGE_KEY,serializeQueue,restoreQueue,relinkQueue,sameSource,sourceIdentity,saveQueue,loadQueue,clearSavedQueue} from '../queue-state.mjs';
const file={name:'episode.mkv',size:123456,lastModified:1780000000000,type:'video/x-matroska'},
  settings={mode:'2d',fps:'24',workers:2,advanced:null};
const validate=s=>{if(s?.mode!=='2d')throw Error('Bad settings');return s;};
test('serialize preserves settings but not file data',()=>{
  const json=serializeQueue([{file,settings,status:'encoding',duration:63.2,audio:true}]);
  const restored=restoreQueue(json,validate)[0];
  assert.equal(restored.file,null);assert.equal(restored.status,'needs-file');
  assert.deepEqual(restored.source,file);assert.deepEqual(restored.settings,settings);
});
test('relink matches name size and modification time',()=>{
  const arr=restoreQueue(serializeQueue([{file,settings,status:'pending'}]),validate);
  assert.equal(sameSource(file,{...file,size:123457}),false);
  assert.equal(sameSource(file,{...file,lastModified:1780000000001}),false);
  assert.equal(relinkQueue(arr,[{...file,size:123457}]).linked.length,0);
  assert.equal(relinkQueue(arr,[file]).linked.length,1);
  assert.equal(arr[0].status,'pending');assert.equal(arr[0].file,file);
});
test('finished records stay finished and cannot be relinked automatically',()=>{
  const arr=restoreQueue(serializeQueue([{file,settings,status:'done'}]),validate);
  assert.equal(arr[0].status,'done');assert.equal(relinkQueue(arr,[file]).linked.length,0);
});
test('unmatched files remain available for fresh queue entries',()=>{
  const arr=restoreQueue(serializeQueue([{file,settings,status:'pending'}]),validate);
  const other={...file,name:'other.mkv'};
  assert.deepEqual(relinkQueue(arr,[other]).unmatched,[other]);
});
test('storage API persists and clears local manifest',()=>{
  const m=new Map(),s={setItem:(k,v)=>m.set(k,v),getItem:k=>m.get(k)??null,removeItem:k=>m.delete(k)};
  saveQueue([{file,settings,status:'encoding'}],s);
  assert.ok(m.has(QUEUE_STORAGE_KEY));assert.equal(loadQueue(validate,s)[0].status,'needs-file');
  clearSavedQueue(s);assert.equal(loadQueue(validate,s).length,0);
});
test('bad manifests and invalid settings fail validation',()=>{
  assert.throws(()=>restoreQueue('{bad json',validate));
  assert.throws(()=>restoreQueue(JSON.stringify({version:2,items:[]}),validate));
  assert.throws(()=>restoreQueue(JSON.stringify({version:1,items:[{source:{name:'bad',size:-1}}]}),validate));
  assert.throws(()=>restoreQueue(serializeQueue([{file,settings:{mode:'bad'},status:'pending'}]),validate),/Bad settings/);
  assert.throws(()=>serializeQueue(Array.from({length:201},()=>({file,settings,status:'pending'}))));
});
test('source identity is read from the original file metadata',()=>assert.deepEqual(sourceIdentity(file),file));
