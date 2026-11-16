// Real codec + file-backed assembly regression. All media is generated outside checkout.
// Usage: node tests/long-movie.mjs /tmp/mobipeg-long-results [5,10,30,60,90,120]
import {execFileSync,spawnSync} from 'node:child_process';
import {mkdirSync,readFileSync,writeFileSync,statSync,openSync,readSync,closeSync,createWriteStream} from 'node:fs';
import {resolve,join} from 'node:path';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import {assembleMovie,inspectMovieSegment,nextMovieClip,getCodedRate} from '../dist/movie.mjs';
const dir=resolve(process.argv[2]||'/tmp/mobipeg-long-results');mkdirSync(dir,{recursive:true});
const ff=resolve('native/local/bin/ffmpeg'),probe=resolve('native/local/bin/ffprobe');
function run(args){return execFileSync(ff,args.map(String),{maxBuffer:20*1024*1024});}
class DiskFile{
 constructor(path){this.path=path;this.size=statSync(path).size;}
 slice(from,to){return{arrayBuffer:async()=>{const b=Buffer.alloc(to-from),fd=openSync(this.path,'r');try{assert.equal(readSync(fd,b,0,b.length,from),b.length);}finally{closeSync(fd);}return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);}};}
}
function outputHandle(path){return{async getFile(){return new DiskFile(path);},async createWritable(){const stream=createWriteStream(path);return{async write(data){if(!stream.write(data))await once(stream,'drain');},async close(){stream.end();await once(stream,'finish');},async abort(){stream.destroy();}};}};}
const source=join(dir,'generated.mkv'),part=join(dir,'chapter.moflex');
const settings={mode:'2d',fps:'24'};
const clip=nextMovieClip(0,100,getCodedRate(settings),30);
// A repeating visual/audio signal; chapter duration is audio-block aligned.
run(['-v','error','-y','-f','lavfi','-i',`color=red:s=320x240:r=24:d=${clip.seconds}`,
 '-f','lavfi','-i',`sine=frequency=440:sample_rate=48000:duration=${clip.seconds}`,
 '-c:v','ffv1','-c:a','pcm_s16le',source]);
run(['-v','error','-y','-threads','1','-filter_threads','1','-i',source,'-map','0:v:0','-map','0:a:0',
 '-c:v','mobiclip','-mobiclip','1','-qp','12','-mobi_qyx','3','-g','48','-threads','1',
 '-c:a','pcm_s16le','-ar','48000','-ac','2','-mo_audio','adpcm','-mo_layout','6','-t',clip.seconds,'-f','moflex',part]);
const frames=Math.round(clip.seconds*24),file=new DiskFile(part);
await inspectMovieSegment(file,frames);
const results=[];
for(const minutes of (process.argv[3]||'5,10,30,60,90,120').split(',').map(Number)){
 const count=Math.ceil(minutes*60/clip.seconds),target=join(dir,`${minutes}min.moflex`),handle=outputHandle(target);
 const start=performance.now();
 const merged=await assembleMovie({segments:Array.from({length:count},()=>({file,frames})),audio:true,outputName:'movie.moflex',work:{async getFileHandle(){return handle;}}},settings);
 const parsed=await inspectMovieSegment(merged.file,count*frames);
 assert.equal(parsed.frames,count*frames);
 for(const kind of ['v','a']){
  const out=run(['-hide_banner','-v','error','-xerror','-i',target,'-map',`0:${kind}:0`,'-progress','pipe:1','-f','null','-']).toString();
  const time=Number([...out.matchAll(/out_time_us=(\d+)/g)].at(-1)?.[1])/1e6;
  assert.ok(Math.abs(time-merged.seconds)<0.006,`${kind} duration ${time} vs ${merged.seconds}`);
  if(kind==='v')assert.equal(Number([...out.matchAll(/frame=(\d+)/g)].at(-1)[1]),count*frames);
 }
 // Compare a seek near the end with a linear decode's last-frame hash.
 const last=Math.floor(merged.seconds-1);
 const seek=run(['-v','error','-ss',last,'-i',target,'-frames:v','1','-f','framemd5','-']).toString().trim().split('\n').at(-1).split(',').at(-1).trim();
 const reference=run(['-v','error','-ss',(last*24%frames)/24,'-i',part,'-frames:v','1','-f','framemd5','-']).toString().trim().split('\n').at(-1).split(',').at(-1).trim();
 assert.equal(seek,reference);
 const row={requestedMinutes:minutes,seconds:merged.seconds,frames:merged.frames,chapters:count,bytes:merged.file.size,durationFieldSaturated:merged.durationFieldSaturated,completeVideoDecode:true,completeAudioDecode:true,audioDriftUnderMilliseconds:6,lateSeekHashMatches:true,elapsedSeconds:(performance.now()-start)/1000};results.push(row);console.log(JSON.stringify(row));writeFileSync(join(dir,'results.json'),JSON.stringify(results,null,2));
}
