import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {deflateRawSync} from 'node:zlib';
import {assembleVidInjectorStarter,readVidInjectorZip,fetchVidInjectorFile} from '../cia-vidinjector-template.mjs';
import {inspectCia} from '../cia-packager.mjs';

// Synthetic fixtures only. No third-party player files are stored in this repository.
const sha=bytes=>createHash('sha256').update(bytes).digest();
const align=(n,b=64)=>Math.ceil(n/b)*b;
const p32=(b,o,n)=>b.writeUInt32LE(n,o);
const p64=(b,o,n)=>b.writeBigUInt64LE(BigInt(n),o);
function base(){
  const header=Buffer.alloc(0x2020),cert=Buffer.alloc(2560),ticket=Buffer.alloc(848),tmd=Buffer.alloc(2868);
  p32(header,0,header.length);p32(header,8,cert.length);p32(header,12,ticket.length);p32(header,16,tmd.length);
  ticket.writeUInt32BE(0x10004);tmd.writeUInt32BE(0x10004);
  const sig=0x140,record=sig+0x9c4,id=0x000400000C100000n;
  ticket.writeBigUInt64BE(id,sig+0x9c);tmd.writeBigUInt64BE(id,sig+0x4c);tmd.writeUInt16BE(1,sig+0x9e);
  const ncch=Buffer.alloc(512),exheader=Buffer.alloc(2048),gap=Buffer.alloc(8192);
  ncch.write('NCCH',256);ncch[0x18f]=4;p32(ncch,0x180,1024);p64(ncch,0x118,id);
  const eh=Buffer.alloc(512),parts=[];let position=0;
  for(const [i,name,body] of [
    [0,'.code',Buffer.alloc(24000,4)],
    [1,'banner',Buffer.concat([Buffer.from('CBMD'),Buffer.alloc(117036)])],
    [2,'icon',Buffer.concat([Buffer.from('SMDH'),Buffer.alloc(14012)])]
  ]){
    eh.write(name,i*16);p32(eh,i*16+8,position);p32(eh,i*16+12,body.length);
    sha(body).copy(eh,512-(i+1)*32);
    parts.push(body,Buffer.alloc(align(body.length,512)-body.length));position+=align(body.length,512);
  }
  const exefs=Buffer.concat([eh,...parts]),start=512+2048+gap.length;
  p32(ncch,0x1a0,start/512);p32(ncch,0x1a4,exefs.length/512);p32(ncch,0x1a8,1);
  sha(exheader.subarray(0,1024)).copy(ncch,0x160);sha(exefs.subarray(0,512)).copy(ncch,0x1c0);
  p32(ncch,0x104,(start+exefs.length)/512);
  const content=Buffer.concat([ncch,exheader,gap,exefs]);
  tmd.writeBigUInt64BE(BigInt(content.length),record+8);sha(content).copy(tmd,record+16);
  p64(header,24,align(content.length));
  return new Blob([header,Buffer.alloc(align(header.length)-header.length),cert,ticket,Buffer.alloc(align(ticket.length)-ticket.length),tmd,Buffer.alloc(align(tmd.length)-tmd.length),content]);
}
function zip(records){
  const local=[],central=[];let at=0,cs=0;
  for(const [name,body] of records){
    const text=Buffer.from(name),data=Buffer.from(body),packed=deflateRawSync(data);
    const lh=Buffer.alloc(30),ch=Buffer.alloc(46);
    p32(lh,0,0x04034b50);lh.writeUInt16LE(20,4);lh.writeUInt16LE(8,8);
    p32(lh,18,packed.length);p32(lh,22,data.length);lh.writeUInt16LE(text.length,26);
    p32(ch,0,0x02014b50);ch.writeUInt16LE(20,4);ch.writeUInt16LE(20,6);ch.writeUInt16LE(8,10);
    p32(ch,20,packed.length);p32(ch,24,data.length);ch.writeUInt16LE(text.length,28);p32(ch,42,at);
    local.push(lh,text,packed);central.push(ch,text);
    at+=lh.length+text.length+packed.length;cs+=ch.length+text.length;
  }
  const e=Buffer.alloc(22);p32(e,0,0x06054b50);e.writeUInt16LE(records.length,8);e.writeUInt16LE(records.length,10);p32(e,12,cs);p32(e,16,at);
  return new Blob([...local,...central,e]);
}
const resources=()=>zip([
  ['exefs/.code',Buffer.alloc(20000,0x53)],
  ['exheader.bin',Buffer.alloc(2048)],
  ...Array.from({length:15},(_,i)=>['romfs/layout/file'+i+'.arc.l',Buffer.from('layout '+i)])
]);
test('on-demand VidInjector starter contains a real populated ExeFS directory',async()=>{
  const output=await assembleVidInjectorStarter(base(),resources(),new Blob([Buffer.alloc(32)]));
  const parsed=await inspectCia(output);
  const ncch=new DataView(parsed.ncch.buffer),offset=ncch.getUint32(0x1a0,true)*512;
  const exefs=Buffer.from(await parsed.content.slice(offset,offset+512).arrayBuffer());
  const names=[];
  for(let i=0;i<10;i++)if(exefs.readUInt32LE(i*16+12))
    names.push(exefs.subarray(i*16,i*16+8).toString().replace(/\0.*$/s,''));
  assert.deepEqual(names,['.code','banner','icon']);
  assert.equal(exefs.readUInt32LE(12),20000);
  const start=512+exefs.readUInt32LE(8),code=Buffer.from(await parsed.content.slice(offset+start,offset+start+20000).arrayBuffer());
  assert.deepEqual(code,Buffer.alloc(20000,0x53));
  assert.equal(ncch.getBigUint64(0x118,true),0x000400000C100000n);
  const rom=ncch.getUint32(0x1b0,true)*512,magic=await parsed.content.slice(rom,rom+4).text();
  assert.equal(magic,'IVFC');
});
test('ZIP input validation rejects unsafe paths, duplicate files and incomplete archives',async()=>{
  for(const input of [
    new Blob(['not zip']),
    zip([['romfs/../secret.txt','bad']]),
    zip([['exefs/.code','one'],['exefs/.code','two'],['exheader.bin',Buffer.alloc(2048)]]),
    zip([['romfs/a.txt','missing executable']])
  ])await assert.rejects(()=>readVidInjectorZip(input));
});
test('mismatched ZIP size metadata cannot trigger unlimited inflation',async()=>{
  const original=zip([['exefs/.code',Buffer.alloc(20000,0x61)],['exheader.bin',Buffer.alloc(2048)]]);
  const corrupted=Buffer.from(await original.arrayBuffer());
  let changed=false;
  for(let i=0;i<corrupted.length-46;i++){
    if(corrupted.readUInt32LE(i)!==0x02014b50)continue;
    if(corrupted.subarray(i+46,i+46+11).toString()!=='exefs/.code')continue;
    corrupted.writeUInt32LE(16,i+24);
    changed=true;break;
  }
  assert.ok(changed);
  await assert.rejects(()=>readVidInjectorZip(new Blob([corrupted])),/exceeds declared size|Corrupted|ZIP/);
});
test('only pinned upstream files are requested and browser credentials are omitted',async()=>{
  const seen=[];
  const response=await fetchVidInjectorFile('arrays/bimgheader.bin',{request:async(url,opts)=>{
    seen.push([url,opts]);return {ok:true,type:'basic',headers:new Headers(),blob:async()=>new Blob([Buffer.alloc(32)])};
  }});
  assert.equal(response.size,32);
  assert.match(seen[0][0],/\/FoofooTheGuy\/VidInjector9000\/[0-9a-f]{40}\//);
  assert.equal(seen[0][1].credentials,'omit');
  await assert.rejects(()=>fetchVidInjectorFile('../other',{request:async()=>{throw Error('not called');}}));
});
