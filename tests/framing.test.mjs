import test from 'node:test';
import assert from 'node:assert/strict';
import {RATES,RESOLUTIONS,validate,filters,codedRate,encodeClipArgs,previewFrame,previewSourceArgs} from '../dist/core.mjs';
import {getCodedRate,nextMovieClip} from '../dist/movie.mjs';
const base={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:null,maxMB:null,hdrMode:'off'};
test('all new resolutions and rates validate and preserve whole stereo pairs',()=>{
 for(const resolution of RESOLUTIONS)for(const fps of RATES)for(const mode of ['2d','full-sbs','half-sbs']){
  const s={...base,resolution,fps,mode};assert.equal(validate(s),s);
  const [w,h]=resolution.split('x').map(Number);assert.equal(w%16,0);assert.equal(h%16,0);
  const args=encodeClipArgs(s,30,0,1);assert.equal(Number(args[args.indexOf('-frames:v')+1])%(mode==='2d'?1:2),0);
  if(mode!=='2d')assert.equal(Number(codedRate(s).split('/')[0])/Number(codedRate(s).split('/')[1]||1),2*Number(fps.split('/')[0])/Number(fps.split('/')[1]||1));
 }
});
test('every new rate retains ADPCM and stereo-pair chapter alignment',()=>{
 for(const fps of RATES)for(const mode of ['2d','full-sbs','half-sbs']){
  const s={...base,fps,mode},coded=getCodedRate(s),clip=nextMovieClip(0,7200,coded),frames=clip.seconds*coded.num/coded.den;
  assert.ok(clip.seconds<=30&&clip.seconds>20);assert.ok(Math.abs(frames-Math.round(frames))<1e-6);
  if(mode!=='2d')assert.equal(Math.round(frames)%2,0);
  const blocks=clip.seconds*48000/256;assert.ok(Math.abs(blocks-Math.round(blocks))<1e-6);
 }
});
test('manual crops precede per-eye scaling and preserve stereo timing',()=>{
 const crop={fit:'fill',left:16,right:32,top:8,bottom:10};
 for(const mode of ['2d','full-sbs','half-sbs']){
  const args=filters({...base,mode,crop}),f=args[1];assert.match(f,/crop=iw-48:ih-18:16:8/);
  assert.match(f,/force_original_aspect_ratio=increase/);assert.match(f,/crop=400:224:\(iw-ow\)\/2:\(ih-oh\)\/2/);
  if(mode!=='2d'){assert.equal(f.split('crop=iw-48').length-1,2);assert.match(f,/setpts=2\*N\+1/);}
  if(mode==='half-sbs')assert.match(f,/crop=iw-48:ih-18:16:8,setsar=sar\*2/);
 }
 assert.match(filters({...base,crop:{fit:'stretch'}})[1],/scale=400:224:reset_sar=1/);
 assert.doesNotMatch(filters({...base,crop:{fit:'stretch'}})[1],/pad=|force_original_aspect_ratio/);
 for(const crop of [null,{fit:'fit',left:0,right:0,top:0,bottom:0}])assert.deepEqual(filters({...base,crop}),filters(base));
});
test('invalid crop and preview timestamps are rejected',()=>{
 for(const crop of [[],true,{fit:'unknown'},{fit:'fit',left:1},{fit:'fit',top:-2},{fit:'fill',right:Infinity},{fit:'fit',left:'2'},{fit:'fit',bottom:16386},{fit:'fit',raw:'-i'}])assert.throws(()=>validate({...base,crop}));
 for(const start of [-1,NaN,Infinity])assert.throws(()=>previewSourceArgs(base,start));
});
test('preview encodes and decodes only the selected frame pair, with no audio or size trials',async()=>{
 for(const mode of ['2d','half-sbs']){
  const eyes=mode==='2d'?1:2,raw=new Blob([new Uint8Array(400*224*4*eyes)]),calls=[];
  const result=await previewFrame({settings:{...base,mode,maxMB:0.01},source:new Blob(['source']),start:30,run:async(args,files,out,env)=>{
   calls.push({args,files,out,env});return{frames:eyes,blob:out.endsWith('.rgba')?raw:new Blob(['moflex'])};
  }});
  assert.equal(calls.length,3);for(const call of [calls[0],calls[2]])assert.equal(call.args[call.args.lastIndexOf('-threads')+1],'1');assert.equal(calls[0].args[calls[0].args.indexOf('-ss')+1],'30.00000000');
  assert.equal(calls[1].args[calls[1].args.indexOf('-frames:v')+1],String(eyes));
  assert.equal(calls[2].files['preview.moflex'].size,6);assert.equal(result.eyes,eyes);
  assert.equal(result.original.size,400*224*4*eyes);
 }
});
test('preview rejects missing frames and unexpected decoded pixel buffers',async()=>{
 await assert.rejects(()=>previewFrame({settings:base,source:new Blob(),start:0,run:async()=>({frames:0,blob:new Blob()})}),/unavailable/);
 await assert.rejects(()=>previewFrame({settings:base,source:new Blob(),start:0,run:async()=>({frames:1,blob:new Blob(['bad'])})}),/frame size/);
});
