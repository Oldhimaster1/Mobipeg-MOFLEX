// Optional multi-gigabyte file-backed hashing benchmark. No media is needed.
// node --expose-gc scripts/stress-cia-hash.mjs [bytes] [--wasm]
import {openAsBlob,createReadStream} from 'node:fs';
import {mkdtemp,open,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {sha256Blob} from '../cia-sha256.mjs';
const bytes=Number(process.argv[2]||2*1024**3+17);
const wasm=process.argv.includes('--wasm');
const hash=wasm?(await import('../cia-sha256-wasm.mjs')).sha256BlobWasm:sha256Blob;
const module=wasm?await WebAssembly.compile(await readFile(new URL('../cia-sha256-core.wasm',import.meta.url))):null;
if(!Number.isSafeInteger(bytes)||bytes<64)throw Error('Specify an integer byte count of at least 64.');
const work=await mkdtemp(join(tmpdir(),'mobipeg-hash-stress-'));
try{
  const path=join(work,'synthetic.bin'),handle=await open(path,'w');
  try{
    await handle.truncate(bytes);
    for(const offset of [0,Math.floor(bytes/2),bytes-32])await handle.write(Buffer.from('MobiPEG synthetic stress marker!!'),0,32,offset);
  }finally{await handle.close();}
  const independent=createHash('sha256');
  for await(const chunk of createReadStream(path))independent.update(chunk);
  const expected=independent.digest('hex');
  globalThis.gc?.();
  const baseline=process.memoryUsage().rss;let peak=baseline,maxRead=0,reads=0;
  const timer=setInterval(()=>{peak=Math.max(peak,process.memoryUsage().rss);},50);
  const source=await openAsBlob(path);
  const bounded={size:source.size,slice(start,end){maxRead=Math.max(maxRead,Math.min(end,bytes)-start);reads++;return source.slice(start,end);}};
  const started=performance.now();let digest;
  try{digest=Buffer.from(await hash(bounded,module)).toString('hex');}
  finally{clearInterval(timer);}
  peak=Math.max(peak,process.memoryUsage().rss);
  if(digest!==expected)throw Error('Hash mismatch against independent Node crypto stream.');
  if(maxRead>1024**2)throw Error('Hash read exceeded 1 MiB.');
  const seconds=(performance.now()-started)/1000;
  console.log(JSON.stringify({engine:wasm?'wasm':'javascript',bytes,seconds,MiBPerSecond:bytes/1024**2/seconds,reads,maxRead,baselineRSS:baseline,peakRSS:peak,sha256:digest,verified:true},null,2));
}finally{await rm(work,{recursive:true,force:true});}
