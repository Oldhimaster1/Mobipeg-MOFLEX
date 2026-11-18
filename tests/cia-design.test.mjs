import test from 'node:test';
import assert from 'node:assert/strict';
import {randomCiaId,coverGeometry,drawCover,CIA_ID_MIN,CIA_ID_MAX} from '../cia-design.mjs';

const fixed = n => ({getRandomValues(words){words[0]=n;return words;}});
test('new CIA title IDs use secure random values and stay in the homebrew range',()=>{
  for(const sample of [0,1,0xff,0x12345678,0xffffffff]){
    const id=randomCiaId([],fixed(sample));
    assert.match(id,/^[CDE][0-9A-F]{4}$/);
    const num=parseInt(id,16);
    assert.ok(num>=CIA_ID_MIN&&num<=CIA_ID_MAX);
  }
});
test('generated IDs avoid known browser-local IDs',()=>{
  const first=randomCiaId([],fixed(0));
  assert.throws(()=>randomCiaId([first],fixed(0)),/unused/);
  const generator={index:0,getRandomValues(words){words[0]=this.index++;return words;}};
  assert.equal(randomCiaId([first],generator),randomCiaId([],fixed(1)));
});
test('title ID generation rejects unavailable randomness',()=>{
  assert.throws(()=>randomCiaId([],{}),/Secure random/);
});
test('cover cropping fills 200x120 with the source centered',()=>{
  const box=coverGeometry(400,400,200,120);
  assert.deepEqual(box,{dx:0,dy:-40,dw:200,dh:200});
  const left=coverGeometry(400,400,200,120,{y:-100});
  const right=coverGeometry(400,400,200,120,{y:100});
  assert.equal(left.dy,0);
  assert.equal(right.dy,-80);
});
test('fit mode preserves whole image and adds predictable borders',()=>{
  const box=coverGeometry(400,400,200,120,{fit:'fit'});
  assert.deepEqual(box,{dx:40,dy:0,dw:120,dh:120});
  const output=coverGeometry(200,120,200,120);
  assert.deepEqual(output,{dx:0,dy:0,dw:200,dh:120});
});
test('zoom and pan stay bounded and invalid geometry is rejected',()=>{
  assert.deepEqual(coverGeometry(200,120,200,120,{zoom:1000,x:1000,y:-1000}),{
    dx:-400,dy:0,dw:600,dh:360
  }); // y=-100 reveals the top edge; +100 reveals the bottom.
  assert.throws(()=>coverGeometry(0,120,200,120),/dimensions/);
  assert.throws(()=>coverGeometry(200,120,200,120,{fit:'stretch'}),/mode/);
});
test('drawCover uses the geometry that the PNG exporter will receive',()=>{
  const calls=[];
  const context={clearRect(...args){calls.push(['clear',...args]);},
    fillRect(...args){calls.push(['fill',...args]);},
    drawImage(...args){calls.push(['draw',...args]);},
    set fillStyle(value){calls.push(['fillStyle',value]);}};
  const image={width:100,height:60};
  drawCover(context,image,200,120);
  assert.deepEqual(calls.at(-1),['draw',image,0,0,200,120]);
  assert.equal(calls.some(row=>row[0]==='fill'),true);
});
