import test from 'node:test';
import assert from 'node:assert/strict';
import {validate,encodeArgs,encodeClipArgs,audioArgs,audioClipArgs,environment,filters} from '../dist/core.mjs';
const defaults={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:null,maxMB:null};
const advanced={me:'dia',subme:2,gop:24,skip:0,refine:1,penalty:24,diagonal:0,scaler:'bicubic',inputRange:'auto',lumaSpatial:0.7,chromaSpatial:1.1,lumaTemporal:1,chromaTemporal:1,volume:-6,highpass:80,lowpass:16000};
test('disabled or blank advanced parameters preserve all profile arguments',()=>{
 for(const a of [null,{}]){
  const s={...defaults,advanced:a};
  assert.deepEqual(encodeArgs(s,30),encodeArgs(defaults,30));
  assert.deepEqual(environment(s),environment(defaults));
  assert.deepEqual(audioArgs(s,2),audioArgs(defaults,2));
 }
});
test('advanced codec controls map to actual FFmpeg arguments and native environment',()=>{
 const s={...defaults,advanced},args=encodeArgs(s,30);
 assert.equal(args[args.indexOf('-me_method')+1],'dia');assert.equal(args[args.indexOf('-g')+1],'24');
 assert.deepEqual(environment(s),{MOBI_SUBME:'2',MOBI_SKIP:'0',MOBI_V11_MV_REFINE:'1',MOBI_V11_MV_PENALTY:'24',MOBI_V11_MV_DIAGONAL:'0'});
 assert.match(filters(s)[1],/flags=bicubic/);assert.match(filters(s)[1],/hqdn3d=0.7:1.1:1:1/);
 const audio=audioArgs(s,2);assert.equal(audio[audio.indexOf('-af')+1],'highpass=f=80,lowpass=f=16000,volume=-6dB,aresample=48000:async=0:first_pts=0,apad,atrim=end_sample=96000,asetpts=N/SR/TB');
});
test('malformed, unsafe or unsupported advanced parameters fail validation',()=>{
 for(const advanced of [[],true,'raw',{subme:1},{subme:10},{subme:2.5},{skip:-1},{gop:1},{gop:601},{volume:NaN},{volume:13},{refine:'1'},{refine:2},{diagonal:2},{penalty:1025},{lumaSpatial:Infinity},{me:'hex -i bad'},{scaler:'scale=800:480'},{inputRange:'full'},{ar:22050},{rawArgs:'-c:v h264'},{highpass:1000,lowpass:1000}]){
  assert.throws(()=>validate({...defaults,advanced}));
 }
});
test('advanced overrides retain stereo mapping, movie alignment and output codec',()=>{
 const s={...defaults,mode:'half-sbs',fps:'24000/1001',movieAudio:true,advanced};
 const args=encodeClipArgs(s,30,60.06,30.03),audio=audioClipArgs(s,60.06,30.03);
 assert.equal(args[args.indexOf('-frames:v')+1],'1440');
 assert.equal(args[args.indexOf('-mo_layout')+1],'0');
 assert.equal(args[args.indexOf('-c:v')+1],'mobiclip');
 assert.equal(args[args.indexOf('-r')+1],'48000/1001');
 assert.equal(audio[audio.indexOf('-ar')+1],'48000');
 assert.equal(audio[audio.indexOf('-mo_audio')+1],'adpcm');
 assert.equal(audio[audio.indexOf('-t')+1],'30.03000000');
 assert.match(filters(s)[1],/setpts=2\*N\+1/);
});
