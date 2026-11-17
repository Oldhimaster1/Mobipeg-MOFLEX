// Real browser-binary decode of a synthetic MOFLEX: no user's media involved.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {inspectPlayableMoflex} from '../dist/player-core.mjs';

test('real WASM decoder returns RGBA frames from a seeked MobiClip movie',{timeout:240000},async t=>{
  try{execFileSync('ffmpeg',['-version'],{stdio:'ignore'});}catch{t.skip('System FFmpeg unavailable');return;}
  const tmp=mkdtempSync(join(tmpdir(),'mobipeg-player-'));
  const source=join(tmp,'color.mkv');
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
    'color=c=red:s=160x128:r=15:d=1.2','-f','lavfi','-i',
    'sine=frequency=440:sample_rate=48000:duration=1.2',
    '-map','0:v','-map','1:a','-c:v','ffv1','-c:a','pcm_s16le',source]);
  const engineDir=resolve('dist/engine');
  const encode={args:['-hide_banner','-nostdin','-v','error','-y','-i','/input/source',
    '-vf','fps=15,scale=160:128,format=yuv420p','-an','-c:v','mobiclip','-mobiclip','1',
    '-qp','12','-mobi_qyx','3','-preset','medium','-me_method','hex','-g','30',
    '-mo_layout','6','-f','moflex','/movie.moflex'],files:{source},
    env:{MOBI_SUBME:'7',MOBI_SKIP:'0'},output:'/movie.moflex',
    destination:join(tmp,'movie.moflex'),result:join(tmp,'encode.json')};
  const execute=spec=>{
    const name=join(tmp,'command.json');writeFileSync(name,JSON.stringify(spec));
    execFileSync(process.execPath,['tests/wasm-command.cjs',name],{
      env:{...process.env,MOBIPEG_ENGINE_DIR:engineDir},timeout:230000,maxBuffer:2*1024*1024});
    return JSON.parse(readFileSync(spec.result));
  };
  assert.equal(execute(encode).code,0);
  const withAudio={args:['-hide_banner','-nostdin','-v','error','-y','-i','/input/video',
    '-i','/input/source','-map','0:v:0','-map','1:a:0','-c:v','copy',
    '-c:a','pcm_s16le','-ar','48000','-ac','2','-af','apad',
    '-mo_audio','adpcm','-mo_layout','6','-t','1.2','-f','moflex','/withaudio.moflex'],
    files:{video:encode.destination,source},env:{},output:'/withaudio.moflex',
    destination:join(tmp,'withaudio.moflex'),result:join(tmp,'mux.json')};
  assert.equal(execute(withAudio).code,0);
  const movie=readFileSync(withAudio.destination);
  const info=await inspectPlayableMoflex(new Blob([movie]));
  assert.equal(info.width,160);assert.equal(info.height,128);assert.equal(info.eyes,1);
  assert.ok(info.frames>=15);assert.ok(info.duration>.8);
  const decode={args:['-hide_banner','-nostdin','-v','error','-ss','0.2','-i','/input/source',
    '-map','0:v:0','-frames:v','5','-pix_fmt','rgba',
    '-f','rawvideo','/video.rgba'],files:{source:withAudio.destination},env:{},
    output:'/video.rgba',destination:join(tmp,'video.rgba'),result:join(tmp,'decode.json')};
  assert.equal(execute(decode).code,0);
  const rgba=readFileSync(decode.destination);
  assert.ok(rgba.length>=160*128*4*4);
  assert.equal(rgba.length%(160*128*4),0);
  assert.ok(rgba[0]>rgba[1]*2&&rgba[0]>rgba[2]*2,'decoded source should be red');
  const audio={args:['-hide_banner','-nostdin','-v','error','-ss','0.2','-i','/input/source',
    '-t','0.2','-map','0:a:0','-ac','2','-ar','48000','-c:a','pcm_s16le',
    '-f','s16le','/audio.raw'],files:{source:withAudio.destination},env:{},
    output:'/audio.raw',destination:join(tmp,'audio.raw'),result:join(tmp,'audio.json')};
  assert.equal(execute(audio).code,0);
  assert.ok(readFileSync(audio.destination).length>10000,'audio must actually decode to PCM');
});
