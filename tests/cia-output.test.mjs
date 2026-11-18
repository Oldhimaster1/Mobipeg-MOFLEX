import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareCiaDownload} from '../cia-output.mjs';

test('CIA quota preflight keeps verified output available for download',async()=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  let opened=false;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{storage:{
    estimate:async()=>({quota:100,usage:90}),getDirectory:async()=>{opened=true;throw Error('Unexpected write');}
  }}});
  try{
    const blob=new Blob([new Uint8Array(11)]),result=await prepareCiaDownload(blob,true);
    assert.equal(result.file,blob);assert.match(result.warning,/Not enough browser storage/);assert.equal(opened,false);
    assert.deepEqual(await prepareCiaDownload(blob,false),{file:blob});
  }finally{Object.defineProperty(globalThis,'navigator',original);}
});

test('CIA interrupted write is removed and does not lose the verified download',async()=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  let removed=false;
  const directory={getFileHandle:async()=>({createWritable:async()=>new WritableStream({
    write(){throw new DOMException('Storage is full','QuotaExceededError');}
  })}),removeEntry:async()=>{removed=true;}};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{storage:{getDirectory:async()=>({getDirectoryHandle:async()=>directory})}}});
  try{
    const blob=new Blob(['verified CIA']),result=await prepareCiaDownload(blob,true);
    assert.equal(result.file,blob);assert.match(result.warning,/Storage is full/);assert.equal(removed,true);
  }finally{Object.defineProperty(globalThis,'navigator',original);}
});
