import test from 'node:test';
import assert from 'node:assert/strict';
import {deflateRawSync} from 'node:zlib';
import {readVidInjectorZip,fetchVidInjectorFile} from '../cia-vidinjector-template.mjs';

// Synthetic ZIPs only: no Nintendo executable or third-party player asset is bundled.
function makeZip(records){
 const local=[],central=[];let offset=0,totalCentral=0;
 for(const [name,body] of records){
  const nameBuf=Buffer.from(name),data=Buffer.from(body),packed=deflateRawSync(data);
  const lh=Buffer.alloc(30),ch=Buffer.alloc(46);
  lh.writeUInt32LE(0x04034b50,0);lh.writeUInt16LE(20,4);
  lh.writeUInt16LE(8,8);lh.writeUInt32LE(packed.length,18);lh.writeUInt32LE(data.length,22);lh.writeUInt16LE(nameBuf.length,26);
  ch.writeUInt32LE(0x02014b50,0);ch.writeUInt16LE(20,4);ch.writeUInt16LE(20,6);
  ch.writeUInt16LE(8,10);ch.writeUInt32LE(packed.length,20);ch.writeUInt32LE(data.length,24);
  ch.writeUInt16LE(nameBuf.length,28);ch.writeUInt32LE(offset,42);
  local.push(lh,nameBuf,packed);central.push(ch,nameBuf);
  offset+=lh.length+nameBuf.length+packed.length;totalCentral+=ch.length+nameBuf.length;
 }
 const end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50,0);
 end.writeUInt16LE(records.length,8);end.writeUInt16LE(records.length,10);
 end.writeUInt32LE(totalCentral,12);end.writeUInt32LE(offset,16);
 return new Blob([...local,...central,end]);
}
const good=()=>makeZip([['exefs/.code',Buffer.alloc(32000,1)],['exheader.bin',Buffer.alloc(2048,2)],['romfs/layout/UI.arc.l',Buffer.from('LAYOUT')]]);
test('extracts valid ZIP members without executing a player',async()=>{
 const entries=await readVidInjectorZip(good());
 assert.equal(entries.size,3);
 assert.equal(entries.get('exefs/.code').size,32000);
 assert.equal(entries.get('exheader.bin').size,2048);
 assert.equal(await entries.get('romfs/layout/UI.arc.l').text(),'LAYOUT');
});
test('rejects traversal, duplicate members, incomplete and invalid ZIPs',async()=>{
 for(const zip of [
  makeZip([['exefs/.code',Buffer.alloc(4096)],['exheader.bin',Buffer.alloc(2048)],['romfs/../secrets',Buffer.from('x')]]),
  makeZip([['exefs/.code',Buffer.alloc(4096)],['exefs/.code',Buffer.alloc(4096)],['exheader.bin',Buffer.alloc(2048)]]),
  makeZip([['romfs/settings/a.csv',Buffer.from('bad')]]),
  new Blob(['invalid zip'])
 ])await assert.rejects(()=>readVidInjectorZip(zip));
});
test('bounds ZIP memory and rejects arbitrary upstream file requests',async()=>{
 await assert.rejects(()=>readVidInjectorZip(makeZip([['exefs/.code',Buffer.alloc(4*1024*1024)]])));
 await assert.rejects(()=>fetchVidInjectorFile('../token',{request:async()=>{throw Error('must not request');}}),/(Unknown|Unsupported)/);
});
test('fetches only the pinned official VidInjector upstream resource',async()=>{
 const calls=[],resource=new Blob([Buffer.alloc(32,1)]);
 const mock=async(url,options)=>{
  calls.push({url,options});return {ok:true,type:'basic',headers:new Headers(),blob:async()=>resource};
 };
 const found=await fetchVidInjectorFile('arrays/bimgheader.bin',{request:mock});
 assert.equal(found.size,32);assert.equal(calls.length,1);
 assert.match(calls[0].url,/raw\.githubusercontent\.com\/FoofooTheGuy\/VidInjector9000\/[0-9a-f]{40}\/VidInjector9002-CLI\/assets\/arrays\/bimgheader\.bin$/);
 assert.equal(calls[0].options.credentials,'omit');
});
