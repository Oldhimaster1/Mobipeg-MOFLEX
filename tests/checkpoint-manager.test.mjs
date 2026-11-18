import test from 'node:test';
import assert from 'node:assert/strict';
import {validJobId,listSavedMovieJobs,removeSavedMovieJob} from '../checkpoint-manager.mjs';
const ID='resume-'+'a'.repeat(64);
const missing=()=>Object.assign(new Error('Missing'),{name:'NotFoundError'});
function filesystem(){
  const manifest={config:{identity:{name:'episode.mp4',bytes:54321},encoder:'v15-1e46f0db1a'}};
  const file=(size,content='',modified=500)=>({kind:'file',getFile:async()=>({size,text:async()=>content,lastModified:modified})});
  const folder={kind:'directory',getFileHandle:async(name)=>{
    if(name!=='checkpoint.json')throw missing();return file(120,JSON.stringify(manifest),500);
  },async *entries(){yield ['checkpoint.json',file(120)];yield ['range-0.json',file(30)];yield ['part-0.moflex',file(1000)];}};
  const root={kind:'directory',removed:[],async *entries(){yield [ID,folder];yield ['not-a-job',folder];},
    removeEntry:async function(id,options){this.removed.push({id,options});}};
  const storage={getDirectory:async()=>({getDirectoryHandle:async name=>name==='mobipeg-long-movies'?root:Promise.reject(missing())})};
  const locks={request:async(id,options,fn)=>fn({name:id})};
  return {root,storage,locks};
}
test('lists checkpoints without opening movie content',async()=>{
  const jobs=await listSavedMovieJobs(filesystem().storage);
  assert.equal(jobs.length,1);assert.equal(jobs[0].name,'episode.mp4');
  assert.equal(jobs[0].ranges,1);assert.equal(jobs[0].storedBytes,1150);
});
test('deletion locks the exact checkpoint and removes only its directory',async()=>{
  const {storage,locks,root}=filesystem();
  assert.equal(await removeSavedMovieJob(ID,storage,locks),true);
  assert.deepEqual(root.removed,[{id:ID,options:{recursive:true}}]);
});
test('rejects invalid IDs, unsupported storage, and busy checkpoints',async()=>{
  const {storage,locks}=filesystem();
  assert.equal(validJobId(ID),true);assert.equal(validJobId('resume-../../'),false);
  await assert.rejects(()=>removeSavedMovieJob('bad',storage,locks),/Invalid saved/);
  await assert.rejects(()=>removeSavedMovieJob(ID,storage,{request:async(_id,_opt,fn)=>fn(null)}),/another tab/);
  await assert.rejects(()=>removeSavedMovieJob(ID,storage,{}),/Web Locks/);
});
test('missing checkpoint folder produces an empty list',async()=>{
  const storage={getDirectory:async()=>({getDirectoryHandle:async()=>Promise.reject(missing())})};
  assert.deepEqual(await listSavedMovieJobs(storage),[]);
});
test('damaged or missing manifests remain visible and deletable without reading video bytes',async()=>{
  const badId='resume-'+'b'.repeat(64),missingId='resume-'+'c'.repeat(64);
  const video={kind:'file',getFile:async()=>({size:2048})};
  const broken={kind:'directory',getFileHandle:async()=>({getFile:async()=>({
    size:12,lastModified:123,text:async()=>'{invalid json'
  })}),async *entries(){yield ['part-0.moflex',video];}};
  const noManifest={kind:'directory',getFileHandle:async()=>{throw missing();},
    async *entries(){yield ['part-0.moflex',video];}};
  const removed=[];
  const root={async *entries(){yield [badId,broken];yield [missingId,noManifest];},
    removeEntry:async(id,options)=>{removed.push({id,options});}};
  const storage={getDirectory:async()=>({getDirectoryHandle:async()=>root})};
  const jobs=await listSavedMovieJobs(storage);
  assert.equal(jobs.length,2);
  assert.equal(jobs[0].damaged,true);
  assert.match(jobs[0].problem,/damaged/);
  assert.equal(jobs[0].storedBytes,2060);
  assert.equal(jobs[1].damaged,true);
  assert.match(jobs[1].problem,/missing/);
  assert.equal(jobs[1].storedBytes,2048);
  await removeSavedMovieJob(badId,storage,{request:async(_id,_opts,fn)=>fn({})});
  assert.deepEqual(removed,[{id:badId,options:{recursive:true}}]);
});
