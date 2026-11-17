import test from 'node:test';
import assert from 'node:assert/strict';
import {estimateConversion,totalEstimate,formatBytes} from '../dist/queue.mjs';

const settings={mode:'2d',resolution:'400x224',fps:'24',preset:'quality',q:null,movieAudio:false};

test('estimate is a bounded range and scales with duration, pixels, eyes and quantizer',()=>{
  const base=estimateConversion({fileBytes:1_000_000,duration:60,settings,audio:true});
  assert.equal(base.known,true);assert.ok(base.minimum>0);assert.ok(base.maximum>base.minimum);assert.equal(base.temporaryBytes,base.maximum);
  const longer=estimateConversion({fileBytes:1_000_000,duration:120,settings,audio:true});
  assert.equal(longer.minimum,base.minimum*2);assert.equal(longer.maximum,base.maximum*2);
  const stereo=estimateConversion({fileBytes:1_000_000,duration:60,settings:{...settings,mode:'full-sbs'},audio:true});
  assert.ok(stereo.maximum>base.maximum);
  const best=estimateConversion({fileBytes:1_000_000,duration:60,settings:{...settings,preset:'best'},audio:true});
  assert.ok(best.maximum>base.maximum);
});

test('long movie estimate accounts for segments plus final assembly',()=>{
  const short=estimateConversion({fileBytes:1_000_000,duration:600,settings,audio:true});
  const movie=estimateConversion({fileBytes:1_000_000,duration:600,settings:{...settings,movieAudio:true},audio:true});
  assert.ok(movie.temporaryBytes>movie.maximum*2);assert.ok(movie.temporaryBytes>short.temporaryBytes);
});

test('unknown durations remain visible without inventing output bytes',()=>{
  assert.deepEqual(estimateConversion({fileBytes:1234,duration:null,settings,audio:true}),{known:false,inputBytes:1234});
  assert.throws(()=>estimateConversion({fileBytes:0,duration:1,settings,audio:true}));
});

test('queue totals sum outputs but use peak per-item temporary storage',()=>{
  const a={file:{size:100},estimate:{known:true,minimum:10,maximum:20,temporaryBytes:40}};
  const b={file:{size:200},estimate:{known:true,minimum:30,maximum:50,temporaryBytes:60}};
  const c={file:{size:300},estimate:{known:false}};
  assert.deepEqual(totalEstimate([a,b,c]),{known:2,unknown:1,inputBytes:600,minimum:40,maximum:70,peakTemporary:60});
});

test('byte formatting stays readable across units',()=>{
  assert.equal(formatBytes(999),'999 B');assert.equal(formatBytes(1500),'1.5 KB');assert.equal(formatBytes(2_000_000),'2.00 MB');assert.equal(formatBytes(3_000_000_000),'3.00 GB');assert.equal(formatBytes(NaN),'Unavailable');
});
