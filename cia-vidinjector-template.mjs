// On-demand, local VidInjector starter generation. No player binaries are shipped by MobiPEG.
// The upstream binaries may have separate copyright restrictions. See docs before distribution.
import {rebuildRomfsMetadata} from './cia-romfs.mjs';
import {buildRomfs,inspectCia} from './cia-packager.mjs';
import {sha256Blob} from './cia-sha256.mjs';

export const VIDINJECTOR_REVISION='7eb44d5fb712cdd8a8a34981c2bfaefba8f29b64';
const root='https://raw.githubusercontent.com/FoofooTheGuy/VidInjector9000/'+VIDINJECTOR_REVISION+'/VidInjector9002-CLI/assets/';
const encoder=new TextEncoder(),decoder=new TextDecoder(),limit=8*1024*1024;
const align=(n,b=64)=>Math.ceil(n/b)*b;
const dv=a=>new DataView(a.buffer,a.byteOffset,a.byteLength);
const r16=(a,p)=>dv(a).getUint16(p,true),r32=(a,p)=>dv(a).getUint32(p,true);
const r64=(a,p,le=true)=>dv(a).getBigUint64(p,le);
const w32=(a,p,n)=>dv(a).setUint32(p,n,true);
const w64=(a,p,n,le=true)=>dv(a).setBigUint64(p,BigInt(n),le);
const buf=async b=>new Uint8Array(await b.arrayBuffer());
const hash=async b=>sha256Blob(b instanceof Blob?b:new Blob([b]));
const pad=(b,k=64)=>new Blob([b,new Uint8Array(align(b.size,k)-b.size)]);
const equal=(a,b)=>a.length===b.length&&a.every((v,i)=>v===b[i]);
const text=a=>decoder.decode(a).replace(/\0.*$/s,'');
const utf16=s=>{const b=new Uint8Array(s.length*2);for(let i=0;i<s.length;i++)dv(b).setUint16(i*2,s.charCodeAt(i),true);return b;};
const csv=s=>new Blob([new Uint8Array([255,254]),utf16(s)]);
const signature=a=>{const n=dv(a).getUint32(0,false)-0x10000,v=[0x240,0x140,0x80,0x240,0x140,0x80][n];if(!v)throw Error('Unsupported CIA signature');return v;};
const range=async(b,o,n)=>{if(o<0||n<0||o+n>b.size||!Number.isSafeInteger(o+n))throw Error('Truncated player file');return buf(b.slice(o,o+n));};
export async function fetchVidInjectorFile(path,{request=fetch}={}){
  if(!['files/base.cia','files/vector/multi.zip','arrays/bimgheader.bin'].includes(path))throw Error('Unknown VidInjector resource');
  const response=await request(root+path,{mode:'cors',credentials:'omit',redirect:'error'});
  if(!response.ok||response.type==='opaque')throw Error('Cannot retrieve VidInjector resource: '+path);
  if(Number(response.headers.get('content-length'))>limit)throw Error('Unexpected player download size');
  const blob=await response.blob();if(!blob.size||blob.size>limit)throw Error('Invalid player resource size');
  return blob;
}
// ZIP central-directory reader. Rejects encrypted, oversized and unsafe members.
export async function readVidInjectorZip(zip){
  if(zip.size>limit)throw Error('VidInjector ZIP too large');
  const data=await buf(zip),v=dv(data),found=new Map();
  let end=-1;
  for(let i=data.length-22;i>=Math.max(0,data.length-65557);i--)if(v.getUint32(i,true)===0x06054b50){end=i;break;}
  if(end<0)throw Error('Invalid VidInjector ZIP');
  const count=r16(data,end+10),size=r32(data,end+12),start=r32(data,end+16);
  if(count>200||r16(data,end+8)!==count||start+size>end)throw Error('Invalid player ZIP directory');
  let p=start,total=0;
  for(let j=0;j<count;j++){
    if(p+46>data.length||r32(data,p)!==0x02014b50)throw Error('Damaged player ZIP index');
    const flags=r16(data,p+8),method=r16(data,p+10),packed=r32(data,p+20),unpacked=r32(data,p+24);
    const nl=r16(data,p+28),xl=r16(data,p+30),cl=r16(data,p+32),local=r32(data,p+42);
    if(p+46+nl+xl+cl>data.length)throw Error('Truncated player ZIP directory');
    const name=decoder.decode(data.subarray(p+46,p+46+nl));p+=46+nl+xl+cl;
    if(name.endsWith('/'))continue;
    if(!/^(?:exefs\/\.code|exheader\.bin|romfs\/[a-zA-Z0-9_.\/-]+)$/.test(name)||name.split('/').includes('..')||name.includes('//'))throw Error('Unsafe ZIP member');
    if(flags&1||![0,8].includes(method)||unpacked>3*1024*1024||(total+=unpacked)>limit)throw Error('Unsupported ZIP member');
    if(local+30>data.length||r32(data,local)!==0x04034b50)throw Error('Broken player ZIP member');
    const offset=local+30+r16(data,local+26)+r16(data,local+28);
    if(offset+packed>data.length)throw Error('Truncated player ZIP member');
    const compressed=data.subarray(offset,offset+packed);
    let inflated;
    if(method===0)inflated=compressed;
    else{
      if(typeof DecompressionStream!=='function')throw Error('This browser cannot unpack VidInjector resources');
      inflated=new Uint8Array(await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
    }
    if(inflated.length!==unpacked||found.has(name))throw Error('Corrupted or duplicate player file');
    found.set(name,new Blob([inflated]));
  }
  if(p!==start+size||!found.has('exefs/.code')||found.get('exheader.bin')?.size!==2048)throw Error('Incomplete player archive');
  return found;
}
const locales=['JP','EN','FR','GE','IT','SP','CN','KO','DU','PO','RU','TW'];
const entries=(heading,value)=>'# '+heading+'\r\n'+locales.map(l=>'# '+l+':\r\n'+value+'\r\n\r\n').join('');
function settings(){
  return entries('おしらせURL','none')+entries('アプリ名（ロングネーム）','Movie')+
    '# 拡張セーブデータのID（16進数）\r\nC1000\r\n\r\n# NADLタスクのID\r\nnone\r\n\r\n'+
    '# タスクの実行間隔（h）（10進数）\r\n0\r\n\r\n# タスクの実行回数（10進数）\r\n0\r\n\r\n'+
    '# おしらせのあり、なし\r\nfalse\r\n\r\n# 早送り、巻戻しボタンのあり、なし\r\ntrue\r\n\r\n'+
    '# 優しさ演出のあり、なし\r\nfalse\r\n\r\n# 動画の数\r\n1\r\n\r\n'+
    entries('動画パブリッシャー名','MobiPEG')+entries('WEBブラウザ用のURL','');
}
async function exeFiles(exe){
  const header=await range(exe,0,512),files=[];
  for(let i=0;i<10;i++){
    const p=i*16,size=r32(header,p+12),offset=r32(header,p+8);
    if(!size)continue;
    const name=text(header.slice(p,p+8));
    if(!['.code','banner','icon'].includes(name)||size>2*1024*1024)throw Error('Unexpected base ExeFS resource');
    files.push({name,blob:exe.slice(512+offset,512+offset+size)});
  }
  if(!files.some(f=>f.name==='banner')||!files.some(f=>f.name==='icon'))throw Error('Base CIA has no artwork');
  return files;
}
async function makeExefs(entries){
  const header=new Uint8Array(512),parts=[new Blob([header])];let off=0;
  for(let i=0;i<entries.length;i++){
    const {name,blob}=entries[i];
    header.set(encoder.encode(name),i*16);w32(header,i*16+8,off);w32(header,i*16+12,blob.size);
    header.set(await hash(blob),512-(i+1)*32);
    const part=pad(blob,512);parts.push(part);off+=part.size;
  }
  return new Blob(parts);
}
export async function assembleVidInjectorStarter(base,zip,bimg,{onProgress=()=>{}}={}){
  if(base.size>limit||bimg.size!==32)throw Error('Invalid player starter assets');
  const files=await readVidInjectorZip(zip);
  onProgress('Preparing the VidInjector player');
  const header=await range(base,0,0x2020);
  if(r32(header,0)!==0x2020)throw Error('Unsupported base CIA header');
  const cs=r32(header,8),ts=r32(header,12),ms=r32(header,16);
  const certPos=align(0x2020),ticketPos=certPos+align(cs),tmdPos=ticketPos+align(ts),contentPos=tmdPos+align(ms);
  const tmd=await range(base,tmdPos,ms),ticket=await range(base,ticketPos,ts);
  const s=signature(tmd),record=s+0x9c4;
  if(dv(tmd).getUint16(s+0x9e,false)!==1||record+48>tmd.length)throw Error('Unsupported base CIA content list');
  const contentLength=Number(r64(tmd,record+8,false)),content=base.slice(contentPos,contentPos+contentLength);
  if(content.size!==contentLength||!equal(await hash(content),tmd.subarray(record+16,record+48)))throw Error('Base CIA content hash mismatch');
  const ncch=await range(content,0,512);
  if(text(ncch.slice(256,260))!=='NCCH'||!(ncch[0x18f]&4)||r32(ncch,0x1b4))throw Error('Invalid decrypted player base');
  const oldExeOffset=r32(ncch,0x1a0)*512,oldExeSize=r32(ncch,0x1a4)*512;
  if(!oldExeOffset||!oldExeSize||oldExeOffset+oldExeSize>content.size)throw Error('Base CIA has no ExeFS');
  const oldEntries=await exeFiles(content.slice(oldExeOffset,oldExeOffset+oldExeSize));
  const code=files.get('exefs/.code');
  if(code.size<4096||code.size>2*1024*1024)throw Error('Invalid VidInjector executable');
  const exefs=await makeExefs([{name:'.code',blob:code},...oldEntries.filter(f=>f.name!=='.code')]);
  const romFiles=[];
  for(const [path,blob] of files)if(path.startsWith('romfs/'))romFiles.push({path:'/'+path.slice(6),blob});
  if(romFiles.length<10)throw Error('Missing player resources');
  romFiles.push(
    {path:'/movie/movie_0.moflex',blob:new Blob([new Uint8Array([0x4c,0x32,0xaa,0xab])])},
    {path:'/movie/movie_title.csv',blob:csv('#JP,#EN,#FR,#GE,#IT,#SP,#CH,#KO,#DU,#PO,#RU,#TW\r\n'+Array(12).fill('Movie').join(',')+'\r\n')},
    {path:'/movie/movie_0.bimg',blob:new Blob([bimg,new Uint8Array(65536)])},
    {path:'/settings/settingsTL.csv',blob:csv(settings())},
    {path:'/settings/movie_bnrname.csv',blob:csv('1\r\nmovie_0.bimg\r\n')},
    {path:'/settings/information_buttons.csv',blob:new Blob([new Uint8Array([255,254])])}
  );
  const romfs=await buildRomfs(rebuildRomfsMetadata(romFiles));
  const prefix=await range(content,0,oldExeOffset);
  prefix.set(await buf(files.get('exheader.bin')),512);
  const id=0x000400000C100000n;
  w64(prefix,0x108,id);w64(prefix,0x118,id);
  w64(prefix,512+0x200,id);w64(prefix,512+0x600,id);
  w32(prefix,512+0x1c9,0xC1000);
  prefix.set(await hash(prefix.slice(512,512+r32(ncch,0x180))),0x160);
  w32(prefix,0x1a4,exefs.size/512);w32(prefix,0x1a8,1);
  const romOffset=oldExeOffset+exefs.size;
  w32(prefix,0x1b0,romOffset/512);w32(prefix,0x1b4,align(romfs.size,512)/512);w32(prefix,0x1b8,1);
  w32(prefix,0x104,(romOffset+align(romfs.size,512))/512);
  prefix.set(await hash(exefs.slice(0,512)),0x1c0);
  prefix.set(await hash(romfs.slice(0,512)),0x1e0);
  const rebuilt=new Blob([prefix,exefs,pad(romfs,512)]);
  w64(tmd,s+0x4c,id,false);w64(tmd,record+8,rebuilt.size,false);
  tmd.set(await hash(rebuilt),record+16);
  for(let i=0;i<64;i++){
    const p=s+0xc4+i*36,start=dv(tmd).getUint16(p,false),count=dv(tmd).getUint16(p+2,false);
    if(count)tmd.set(await hash(tmd.slice(record+start*48,record+(start+count)*48)),p+4);
  }
  tmd.set(await hash(tmd.slice(s+0xc4,s+0x9c4)),s+0xa4);
  w64(ticket,signature(ticket)+0x9c,id,false);
  w32(header,20,0);w64(header,24,align(rebuilt.size));
  const result=new Blob([pad(new Blob([header])),pad(base.slice(certPos,certPos+cs)),pad(new Blob([ticket])),pad(new Blob([tmd])),pad(rebuilt)]);
  await inspectCia(result);
  onProgress('Starter CIA verified');
  return result;
}
export async function loadVidInjectorStarter({request=fetch,onProgress=()=>{}}={}){
  onProgress('Downloading the VidInjector player from its original source');
  const resources=await Promise.all(['files/base.cia','files/vector/multi.zip','arrays/bimgheader.bin'].map(path=>fetchVidInjectorFile(path,{request})));
  return assembleVidInjectorStarter(...resources,{onProgress});
}
