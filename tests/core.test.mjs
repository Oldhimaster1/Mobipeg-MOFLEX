import test from 'node:test';import assert from'node:assert/strict';import{execFileSync}from'node:child_process';import{PRESETS,FILTERS,RATES,RESOLUTIONS,validate,filters,codedRate,encodeArgs,audioArgs,environment,parseProbe,progressLine,convert,verifyCandidate}from'../dist/core.mjs';
const defaults={mode:'2d',preset:'quality',filter:'detail',fps:'24',resolution:'400x224',motion:'auto',q:null,maxMB:null};
for(const mode of ['2d','full-sbs','half-sbs'])for(const fps of RATES)for(const resolution of RESOLUTIONS)for(const filter of Object.keys(FILTERS))test(`native filter parity ${mode} ${fps} ${resolution} ${filter}`,()=>{const s={...defaults,mode,fps,resolution,filter};const[w,h]=resolution.split('x');const native=JSON.parse(execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,'native');import MobiPEG_Studio_V15 as m;print(json.dumps(m.video_filters('${mode}',${w},${h},'${fps}','${filter}')))`],{encoding:'utf8'}));assert.deepEqual(filters(s),native[0]);assert.equal(encodeArgs(s,30).at(-4),mode==='2d'?'6':'1');assert.equal(native[1],mode==='2d'?'6':'0');});
for(const q of Array.from({length:48},(_,i)=>i+12))test(`quantizer ${q}`,()=>{const a=encodeArgs({...defaults,q},q);assert.equal(12+6*Number(a[a.indexOf('-mobi_qyx')+1])+Number(a[a.indexOf('-qp')+1])%6,q);});
for(const preset of Object.keys(PRESETS))for(const motion of ['auto','on','off'])test(`motion ${preset} ${motion}`,()=>{const env=environment({...defaults,preset,motion});assert.equal(env.MOBI_V11_MV_REFINE,motion==='on'||motion==='auto'&&['best','quality'].includes(preset)?'1':'0');});
test('fractional stereo FPS and audio timing',()=>{assert.equal(codedRate({...defaults,mode:'half-sbs',fps:'24000/1001'}),'48000/1001');assert.ok(audioArgs({...defaults,mode:'full-sbs'},1.25).includes('1.25000000'));});
test('invalid settings rejected',()=>{for(const patch of [{fps:'60'},{q:11},{q:60},{q:NaN},{maxMB:NaN},{maxMB:-1},{mode:'auto'},{resolution:'800x480'}])assert.throws(()=>validate({...defaults,...patch}));});
test('probe and progress parsing',()=>{assert.deepEqual(parseProbe('Duration: 00:01:02.50\nVideo: h264\nAudio: aac'),{duration:62.5,audio:true});assert.throws(()=>parseProbe('Duration: N/A'));assert.deepEqual(progressLine('frame=  48'),{key:'frame',value:'48'});});
async function fake(sizes,s={}){let encodes=0;return convert({settings:{...defaults,...s},source:new Blob(['video']),run:async(args,files,output)=>{if(args.length===3)return{log:'Duration: 00:00:01.00\nVideo: h264'};if(output){const size=typeof sizes==='function'?sizes(Number(args[args.indexOf('-qp')+1]),encodes):sizes;encodes++;return {blob:new Blob([new Uint8Array(size)]),frames:24};}return{frames:24};}});}
test('no size limit is a single real candidate',async()=>assert.equal((await fake(8192)).attempts,1));
test('cap enforces actual finished bytes',async()=>{const r=await fake(8192,{maxMB:.01});assert.ok(r.blob.size<=10000);assert.equal(r.q,12);});
test('impossible cap fails instead of oversized download',async()=>assert.rejects(()=>fake(20000,{maxMB:.01}),/Cannot meet/));
test('stereo odd packet count rejected',async()=>{await assert.rejects(()=>convert({settings:{...defaults,mode:'full-sbs'},source:new Blob(),run:async(a,f,o)=>a.length===3?{log:'Duration: 00:00:01.00\nVideo: h264'}:{blob:new Blob(['x']),frames:47}}),/missing stereo eye/);});
test('verification mismatch rejected',async()=>{await assert.rejects(()=>convert({settings:defaults,source:new Blob(),run:async(a,f,o)=>a.length===3?{log:'Duration: 00:00:01.00\nVideo: h264'}:o?{blob:new Blob(['x']),frames:24}:{frames:23}}),/Decoded frame count/);});

test('half-SBS fitting uses display aspect ratio',()=>{assert.ok(filters({...defaults,mode:'half-sbs'})[1].includes('reset_sar=1'));assert.ok(!filters({...defaults,mode:'full-sbs'})[1].includes('reset_sar=1'));});

test('browser encoding can retain candidate without verification',async()=>{
  const stages=[];
  const result=await convert({settings:defaults,source:new Blob(['source']),verify:false,notify:x=>stages.push(x.stage),run:async(args,files,output)=>{
    if(args.length===3)return{log:'Duration: 00:00:01.00\nVideo: h264'};
    if(output)return{blob:new Blob(['encoded']),frames:24};
    throw Error('Unexpected verification before candidate delivery');
  }});
  assert.equal(result.blob.size,7);
  assert.equal(result.frames,24);
  assert.equal(stages.some(x=>x.startsWith('Verifying')),false);
});
test('split verification preserves strict video frame checks and audio decoding',async()=>{
  const blob=new Blob(['moflex']),seen=[];
  const run=async args=>{seen.push(args[args.indexOf('-map')+1]);return{frames:24};};
  await verifyCandidate({kind:'video',blob,frames:24,seconds:1,run});
  await verifyCandidate({kind:'audio',blob,frames:24,seconds:1,run});
  assert.deepEqual(seen,['0:v:0','0:a:0']);
  await assert.rejects(()=>verifyCandidate({kind:'video',blob,frames:24,seconds:1,run:async()=>({frames:23})}),/frame count/);
  await assert.rejects(()=>verifyCandidate({kind:'audio',blob,frames:24,seconds:1,run:async()=>{throw Error('Out of memory');}}),/Out of memory/);
});
