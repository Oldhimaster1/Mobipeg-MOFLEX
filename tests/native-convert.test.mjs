// End-to-end native regression using generated media only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

const ffmpeg=resolve('native/local/bin/ffmpeg');
const ffprobe=resolve('native/local/bin/ffprobe');
const studio=resolve('native/MobiPEG_Studio_V15.py');
const converter=resolve('native/moflex_convert.py');

function run(program,args,options={}){
  return execFileSync(program,args,{encoding:'utf8',maxBuffer:8*1024*1024,...options});
}

test('FastAudio stereo MOFLEX keeps its two-second timeline and exports both eyes',{timeout:240000},t=>{
  try{run(ffmpeg,['-version']);}catch{t.skip('Bundled native FFmpeg is not built');return;}
  const dir=mkdtempSync(join(tmpdir(),'mobipeg-native-convert-'));
  const source=join(dir,'stereo.mkv');
  const movie=join(dir,'stereo.moflex');
  const sbs=join(dir,'stereo.mp4');
  const left=join(dir,'left.mkv');
  run('ffmpeg',['-hide_banner','-v','error','-y',
    '-f','lavfi','-i','color=c=red:s=400x224:r=24:d=2',
    '-f','lavfi','-i','color=c=blue:s=400x224:r=24:d=2',
    '-f','lavfi','-i','sine=frequency=997:sample_rate=48000:duration=2',
    '-filter_complex','[0:v][1:v]hstack=inputs=2[v]','-map','[v]','-map','2:a',
    '-c:v','ffv1','-c:a','pcm_s16le',source]);
  run('python3',[studio,'-i',source,'-o',movie,'--mode','full-sbs',
    '--resolution','400x224','--fps','24','--audio-codec','fastaudio','--overwrite']);

  const info=JSON.parse(run('python3',[converter,movie,'--inspect']));
  assert.equal(info.layout,0);assert.equal(info.family,'interleaved');
  assert.equal(info.stereo,'genuine-3d');assert.equal(info.eyes,2);
  assert.ok(Math.abs(info.duration-2)<0.03,`unexpected duration ${info.duration}`);
  assert.equal(info.streams.find(s=>s.codec_type==='audio').codec_name,'fastaudio');

  run('python3',[converter,movie,'-o',sbs,'--mode','sbs']);
  run('python3',[converter,movie,'-o',left,'--mode','left']);
  const probe=path=>JSON.parse(run(ffprobe,['-v','error','-show_entries',
    'stream=codec_type,width,height,duration:format=duration','-of','json',path]));
  const sbsInfo=probe(sbs);const leftInfo=probe(left);
  const sbsVideo=sbsInfo.streams.find(s=>s.codec_type==='video');
  const leftVideo=leftInfo.streams.find(s=>s.codec_type==='video');
  assert.deepEqual([sbsVideo.width,sbsVideo.height],[800,224]);
  assert.deepEqual([leftVideo.width,leftVideo.height],[400,224]);
  assert.ok(sbsInfo.streams.some(s=>s.codec_type==='audio'));
  assert.ok(Number(sbsInfo.format.duration)>1.9);

  const pcm=run(ffmpeg,['-v','error','-i',movie,'-map','0:a:0','-f','s16le','pipe:1'],{encoding:null});
  assert.equal(pcm.length,2*48000*2*2,'two channels of 16-bit PCM for exactly two seconds');
  assert.ok(readFileSync(sbs).length>4096);
});
