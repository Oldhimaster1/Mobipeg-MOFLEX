import test from 'node:test';
import assert from 'node:assert/strict';
import {createUsage} from '../dist/usage.mjs';
function fixture(extra={}) {
  const calls=[], values=new Map();
  const env={location:{origin:'https://oldhimaster1.github.io'},navigator:{},
    localStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},
    fetch:(url,options)=>{calls.push({url,options,body:JSON.parse(options.body)});return Promise.resolve({ok:true});},...extra};
  return {usage:createUsage(env),env,calls};
}
test('only aggregate fields leave the browser; no credentials or referrer',()=>{
 const {usage,calls}=fixture();usage.view();usage.view();usage.conversion(7200.4,20_000_000_000,400_000_000);
 assert.deepEqual(calls.map(x=>x.body),[{type:'view'},{type:'conversion',duration:7200,inputBytes:20_000_000_000,outputBytes:400_000_000}]);
 for(const c of calls){assert.equal(c.options.credentials,'omit');assert.equal(c.options.referrerPolicy,'no-referrer');assert.equal(c.url,'https://usage-stats.moflex.workers.dev/ingest');}
});
test('opt-out persists and suppresses both reports',()=>{
 const {usage,env,calls}=fixture();usage.setEnabled(false);usage.view();usage.conversion(1,1,1);assert.equal(calls.length,0);
 const next=createUsage(env);assert.equal(next.enabled(),false);next.setEnabled(true);next.view();assert.equal(calls.length,1);
});
test('browser privacy signals and local previews suppress all reports',()=>{
 for(const extra of [{navigator:{globalPrivacyControl:true}},{navigator:{doNotTrack:'1'}},{doNotTrack:'1'},{location:{origin:'http://localhost:4173'}}]){
  const {usage,calls}=fixture(extra);usage.setEnabled(true);usage.view();usage.conversion(1,1,1);assert.equal(calls.length,0);
 }
});
test('invalid statistics are dropped and unavailable storage/network never breaks conversion',async()=>{
 const {usage,calls}=fixture();for(const args of [[NaN,1,1],[0,1,1],[86401,1,1],[1,-1,1],[1,1,Infinity],[1,1,1.5]])usage.conversion(...args);assert.equal(calls.length,0);
 for(const fetch of [()=>{throw Error('offline');},()=>Promise.reject(Error('offline'))]){
  const f=fixture({fetch,localStorage:{getItem(){throw Error('blocked');},setItem(){throw Error('blocked');}}});
  assert.doesNotThrow(()=>{f.usage.view();f.usage.conversion(1,1,1);f.usage.setEnabled(false);});
 }
 await new Promise(resolve=>setImmediate(resolve));
});
