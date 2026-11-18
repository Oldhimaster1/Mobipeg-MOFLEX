import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseMoflexVideoDescriptor,displayedCodedFrame,classifyStereoPixels} from '../dist/player-core.mjs';

test('MOFLEX file picker does not restrict native file selection by MIME type',()=>{
  for(const page of ['../player.html','../dist/player.html']){
    const html=readFileSync(new URL(page,import.meta.url),'utf8');
    const input=html.match(/<input\s+id="movieFile"[^>]*>/)?.[0];
    assert.ok(input,`${page} must expose a MOFLEX picker`);
    assert.match(input,/type="file"/);
    assert.doesNotMatch(input,/\baccept\s*=/i,'file types are checked after selection');
  }
});

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
  const meta=parseMoflexVideoDescriptor(descriptor(1,30,1));
  assert.equal(meta.eyes,2);assert.equal(meta.codedFPS,60);assert.equal(meta.leftFirst,true);
  assert.equal(displayedCodedFrame(10,2,0),20);
  assert.equal(displayedCodedFrame(10,2,1),21);
  const reversed=parseMoflexVideoDescriptor(descriptor(0,30,1));
  assert.equal(reversed.leftFirst,false);
  assert.equal(displayedCodedFrame(10,2,0,reversed.packing,reversed.leftFirst),21);
  assert.equal(displayedCodedFrame(10,2,1,reversed.packing,reversed.leftFirst),20);
  assert.throws(()=>displayedCodedFrame(-1,2,0));
  assert.throws(()=>displayedCodedFrame(0,2,2));
});

test('packed stereo layouts and invalid geometry are handled safely',()=>{
  assert.equal(parseMoflexVideoDescriptor(descriptor(3)).packing,'top-bottom');
  assert.equal(parseMoflexVideoDescriptor(descriptor(3)).leftFirst,false);
  assert.equal(parseMoflexVideoDescriptor(descriptor(4)).packing,'side-by-side');
  assert.throws(()=>parseMoflexVideoDescriptor(descriptor(7)),/Unsupported/);
  assert.throws(()=>parseMoflexVideoDescriptor(new Uint8Array([3,2,0,0])),/Unsupported/);
});

test('pixel sampling distinguishes duplicated and differing eyes',()=>{
  const meta={width:2,height:1,packing:'side-by-side',eyes:2};
  assert.equal(classifyStereoPixels(Uint8Array.from([20,20,20,255,20,20,20,255]).buffer,meta,1).kind,'duplicated-eyes');
  assert.equal(classifyStereoPixels(Uint8Array.from([0,0,0,255,255,255,255,255]).buffer,meta,1).kind,'genuine-3d');
});
