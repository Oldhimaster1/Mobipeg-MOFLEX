import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {deflateRawSync} from 'node:zlib';
import {assembleVidInjectorStarter} from '../cia-vidinjector-template.mjs';
import {inspectCia} from '../cia-packager.mjs';

// Synthetic Nintendo-format containers only. This never bundles a third-party executable.
const sha=v=>createHash('sha256').update(v).digest();
const a=(n,b=64)=>Math.ceil(n/b)*b;
const p32=(b,o,n)=>b.writeUInt32LE(n,o);
const p64=(b,o,n)=>b.writeBigUInt64LE(BigInt(n),o);
function base(){
 const hdr=Buffer.alloc(0x2020),cert=Buffer.alloc(2560),ticket=Buffer.alloc(848),tmd=Buffer.alloc(2868);
 p32(hdr,0,0x2020);p32(hdr,8,cert.length);p32(hdr,12,ticket.length);p32(hdr,16,tmd.length);
 ticket.writeUInt32BE(0x10004,0);tmd.writeUInt32BE(0x10004,0);
 const s=0x140,record=s+0x9c4,id=0x000400000C100000n;
 tmd.writeUInt16BE(1,s+0x9e);ticket.writeBigUInt64BE(id,s+0x9c);tmd.writeBigUInt64BE(id,s+0x4c);
 const head=Buffer.alloc(512),exheader=Buffer.alloc(2048),empty=Buffer.alloc(8192);
 head.write('NCCH',256);head[0x18f]=4;p32(head,0x180,1024);p64(head,0x118,id);
 const exHeader=Buffer.alloc(512),parts=[];let pos=0;
 for(const [i,name,bytes] of [[0,'.code',Buffer.alloc(24000,4)],[1,'banner',Buffer.concat([Buffer.from('CBMD'),Buffer.alloc(117036)])],[2,'icon',Buffer.concat([Buffer.from('SMDH'),Buffer.alloc(14012)])]]){
  exHeader.write(name,i*16);p32(exHeader,i*16+8,pos);p32(exHeader,i*16+12,bytes.length);
  sha(bytes).copy(exHeader,512-(i+1)*32);parts.push(bytes,Buffer.alloc(a(bytes.length,512)-bytes.length));pos+=a(bytes.length,512);
 }
 const exefs=Buffer.concat([exHeader,...parts]),exeOff=head.length+exheader.length+empty.length;
 p32(head,0x1a0,exeOff/512);p32(head,0x1a4,exefs.length/512);p32(head,0x1a8,1);
 sha(exheader.subarray(0,1024)).copy(head,0x160);sha(exefs.subarray(0,512)).copy(head,0x1c0);
 const content=Buffer.concat([head,exheader,empty,exefs]);p32(head,0x104,content.length/512);
 tmd.writeBigUInt64BE(BigInt(content.length),record+8);sha(content).copy(tmd,record+16);p64(hdr,24,a(content.length));
 return new Blob([hdr,Buffer.alloc(a(hdr.length)-hdr.length),cert,ticket,Buffer.alloc(a(ticket.length)-ticket.length),tmd,Buffer.alloc(a(tmd.length)-tmd.length),content]);
}
function zip(){
 const records=[['exefs/.code',Buffer.alloc(20000,1)],['exheader.bin',Buffer.alloc(2048,2)],...Array.from({length:15},(_,i)=>['romfs/layout/file'+i+'.arc.l',Buffer.from('layout '+i)])];
 const local=[],central=[];let off=0,cent=0;
 for(const [name,body] of records){const nam=Buffer.from(name),src=Buffer.from(body),packed=deflateRawSync(src),lh=Buffer.alloc(30),ch=Buffer.alloc(46);
  p32(lh,0,0x04034b50);lh.writeUInt16LE(20,4);lh.writeUInt16LE(8,8);p32(lh,18,packed.length);p32(lh,22,src.length);lh.writeUInt16LE(nam.length,26);
  p32(ch,0,0x02014b50);ch.writeUInt16LE(20,4);ch.writeUInt16LE(20,6);ch.writeUInt16LE(8,10);p32(ch,20,packed.length);p32(ch,24,src.length);ch.writeUInt16LE(nam.length,28);p32(ch,42,off);
  local.push(lh,nam,packed);central.push(ch,nam);off+=lh.length+nam.length+packed.length;cent+=ch.length+nam.length;
 }
 const end=Buffer.alloc(22);p32(end,0,0x06054b50);end.writeUInt16LE(records.length,8);end.writeUInt16LE(records.length,10);p32(end,12,cent);p32(end,16,off);
 return new Blob([...local,...central,end]);
}
test('assembles a CIA with valid NCCH, ExeFS, RomFS and content hashes from synthetic assets',async()=>{
 const source=base(),archive=zip(),bimg=new Blob([Buffer.from('AAAAAAAAAQAAAAAAAwAAAAABgAABAgAAEAAAAAAAAAA=','base64')]);
 assert.equal(bimg.size,32);
 const progress=[],output=await assembleVidInjectorStarter(source,archive,bimg,{onProgress:x=>progress.push(x)});
 const parsed=await inspectCia(output);
 assert.ok(output.size>source.size);
 assert.ok(progress.at(-1)?.toLowerCase().includes('verified'));
 const head=new DataView(parsed.ncch.buffer),offset=head.getUint32(0x1b0,true)*512;
 const romfs=new Uint8Array(await parsed.content.slice(offset,offset+4096).arrayBuffer());
 assert.equal(new TextDecoder().decode(romfs.subarray(0,4)),'IVFC');
 assert.equal(head.getBigUint64(0x118,true),0x000400000C100000n);
 const tampered=new Uint8Array(await output.arrayBuffer());tampered[tampered.length-600]^=1;
 await assert.rejects(()=>inspectCia(new Blob([tampered])),/hash/i);
});
