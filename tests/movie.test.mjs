import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createFront, inspectMovieSegment, assembleMovie,
  getCodedRate, nextMovieClip,
} from '../dist/movie.mjs';
import {FAT32_LIMIT, fitsFat32, fat32Estimate} from '../dist/queue.mjs';

const BLOCK=4096;
const descriptors=Uint8Array.from([
  3,13,0,0,0,30,0,1,1,144,0,240,1,1,6,
  4,2,1,0,0,0
]);
function putSync(block,ts){
  const dv=new DataView(block.buffer,block.byteOffset,block.byteLength);
  let check=0xaaaa;
  for(let i=0n;i<64n;i+=16n)check^=Number((ts>>i)&0xffffn);
  dv.setUint16(0,0x4c32);
  dv.setUint16(2,check);
  dv.setBigUint64(4,ts);
  dv.setUint16(12,BLOCK-1);
  block.set(descriptors,14);
}
function segment(count=1,frames=count*30){
  const entries=Array.from({length:count},(_,i)=>({
    frame:BigInt(i*30),time:BigInt(1+i*1000000),offset:0n
  }));
  let front=createFront(descriptors,1,entries,frames,BigInt(frames)*1000000n/30n);
  entries.forEach((e,i)=>{e.offset=BigInt(front.length+i*BLOCK);});
  front=createFront(descriptors,1,entries,frames,BigInt(frames)*1000000n/30n);
  const media=new Uint8Array(count*BLOCK);
  for(let i=0;i<count;i++){
    const block=media.subarray(i*BLOCK,(i+1)*BLOCK);
    putSync(block,entries[i].time);
    block[14+descriptors.length]=((3+i)&63)<<2;
  }
  return new Blob([front,media]);
}
class MemoryFileHandle{
  constructor(){this.blob=new Blob([]);}
  async getFile(){return this.blob;}
  async createWritable(){
    const chunks=[],self=this;
    return{
      async write(data){chunks.push(data);},
      async close(){self.blob=new Blob(chunks);},
      async abort(){chunks.length=0;},
    };
  }
}
test('seek table parses a complete indexed MOFLEX segment',async()=>{
  const info=await inspectMovieSegment(segment(1),30);
  assert.equal(info.frontSize,BLOCK);
  assert.equal(info.entries[0].offset,BigInt(BLOCK));
});
test('FAT32 checks the exact per-file boundary and distinguishes a risky estimate',()=>{
  assert.equal(fitsFat32(FAT32_LIMIT),true);
  assert.equal(fitsFat32(FAT32_LIMIT+1),false);
  assert.match(fat32Estimate({maximum:FAT32_LIMIT+1000}),/exceeds.*1.0 KB/);
  assert.match(fat32Estimate({maximum:FAT32_LIMIT}),/0 B.*headroom/);
});
test('assembly rejects missing segments and corrupt media counters',async()=>{
  const output=new MemoryFileHandle();
  const job={segments:[, {file:segment(),frames:30}],work:{async getFileHandle(){return output;}}};
  const settings={mode:'2d',fps:'30'};
  await assert.rejects(assembleMovie(job,settings),/missing encoded segment/);
  const bytes=new Uint8Array(await segment(2).arrayBuffer());
  bytes[2*BLOCK+14+descriptors.length]=15<<2;
  job.segments=[{file:new Blob([bytes]),frames:60}];
  await assert.rejects(assembleMovie(job,settings),/continuity counter/);
  assert.equal((await output.getFile()).size,0);
});
test('seek table may occupy several 4096-byte front blocks',async()=>{
  const info=await inspectMovieSegment(segment(230),6900);
  assert.ok(info.frontSize>BLOCK);
  assert.equal(info.entries.length,230);
});
test('movie assembly updates global frame indices, offsets, clocks',async()=>{
  const a=segment(),b=segment();
  const output=new MemoryFileHandle();
  const job={
    segments:[{file:a,frames:30},{file:b,frames:30}],
    work:{async getFileHandle(){return output;}},
    outputName:'movie.moflex',
    audio:false,
  };
  const result=await assembleMovie(job,{mode:'2d',fps:'30'});
  assert.equal(result.frames,60);
  assert.equal(result.seconds,2);
  const parsed=await inspectMovieSegment(result.file,60);
  assert.equal(parsed.entries.length,2);
  assert.equal(parsed.entries[1].frame,30n);
  assert.equal(parsed.entries[1].time,1000001n);
  assert.equal(parsed.entries[1].offset,BigInt(parsed.frontSize+BLOCK));
});
test('movie clips use coded FPS including stereo eye doubling',()=>{
  const s=getCodedRate({mode:'full-sbs',fps:'24000/1001'});
  assert.deepEqual(s,{num:48000,den:1001});
  const clip=nextMovieClip(48000,3600,s,180);
  assert.ok(clip.start>1000&&clip.start<1002);
  assert.ok(clip.seconds<=180&&clip.seconds>170);
  assert.equal(clip.seconds*48000%256,0);
  assert.equal(nextMovieClip(9000,300,{num:30,den:1}),null);
});

test('chapter boundaries align ADPCM samples and full stereo pairs at every rate',()=>{
 for(const mode of ['2d','full-sbs','half-sbs'])for(const fps of ['24','25','30','24000/1001','30000/1001']){
  const coded=getCodedRate({mode,fps}),clip=nextMovieClip(0,7200,coded);
  const frames=Math.round(clip.seconds*coded.num/coded.den);
  assert.ok(clip.seconds<=30&&clip.seconds>20);
  assert.ok(Math.abs(clip.seconds*48000/256-Math.round(clip.seconds*48000/256))<1e-8);
  if(mode!=='2d')assert.equal(frames%2,0);
 }
});
test('long movie duration saturates without wrapping its 64-bit seek times',async()=>{
 const joined=await assembleMovie({segments:Array.from({length:73},()=>({file:segment(60,1800),frames:1800})),work:{async getFileHandle(){return new MemoryFileHandle();}},outputName:'movie',audio:false},{mode:'2d',fps:'30'});
 assert.equal(joined.durationFieldSaturated,true);
 const parsed=await inspectMovieSegment(joined.file,131400);
 assert.ok(parsed.entries.at(-1).time>0xffffffffn);
 assert.equal(parsed.durationUs,0xffffffff);
});
