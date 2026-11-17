import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMoflexVideoDescriptor,displayedCodedFrame} from '../dist/player-core.mjs';

const descriptor=(layout,numerator=24000,denominator=1001)=>Uint8Array.from([
  3,13,(numerator>>>24)&255,(numerator>>>16)&255,(numerator>>>8)&255,numerator&255,
  denominator>>>8,denominator&255,1,144,0,224,1,1,layout,4,2,1,0,0,0]);

test('player reads actual layout-6 dimensions and fractional frame rate',()=>{
  const meta=parseMoflexVideoDescriptor(descriptor(6));
  assert.equal(meta.width,400);assert.equal(meta.height,224);assert.equal(meta.eyes,1);
  assert.ok(Math.abs(meta.displayFPS-23.976)<.001);
  assert.equal(meta.codedFPS,meta.displayFPS);
});

test('player exposes real left/right alternating coded frames',()=>{
  const meta=parseMoflexVideoDescriptor(descriptor(0,30,1));
  assert.equal(meta.eyes,2);assert.equal(meta.codedFPS,60);
  assert.equal(displayedCodedFrame(10,2,0),20);
  assert.equal(displayedCodedFrame(10,2,1),21);
  assert.throws(()=>displayedCodedFrame(-1,2,0));
  assert.throws(()=>displayedCodedFrame(0,2,2));
});

test('unsupported layouts and invalid geometry fail safely',()=>{
  assert.throws(()=>parseMoflexVideoDescriptor(descriptor(3)),/Unsupported/);
  assert.throws(()=>parseMoflexVideoDescriptor(new Uint8Array([3,2,0,0])),/Unsupported/);
});
