import test from 'node:test';
import assert from 'node:assert/strict';

const implementations=await Promise.all([
  import('../subtitle-timing.mjs'),
  import('../dist/subtitle-timing.mjs'),
]);
for(const [index,{shiftSubtitleTiming:shift}] of implementations.entries()){
  const name=index?'deployed':'source';
  test(name+' subtitle offset preserves SRT cue text, millisecond precision and Windows line breaks',()=>{
    const source='1\r\n00:00:00,400 --> 00:00:01,500\r\nHello\r\n\r\n2\r\n00:00:02,000 --> 00:00:03,500\r\nNext';
    const positive=shift(source,250);
    assert.match(positive,/00:00:00,650 --> 00:00:01,750/);
    assert.match(positive,/\r\n\r\n2\r\n00:00:02,250 --> 00:00:03,750/);
    assert.equal(shift(source,0),source);
    const negative=shift(source,-2000);
    assert.doesNotMatch(negative,/Hello/);
    assert.match(negative,/00:00:00,000 --> 00:00:01,500/);
  });
  test(name+' ASS/SSA dialogue offsets keep styles, comma-separated text and centiseconds',()=>{
    const ass='[Script Info]\nTitle: Original\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.25,0:00:01.50,Default,Hello, world';
    const result=shift(ass,1250);
    assert.match(result,/Title: Original/);
    assert.match(result,/Dialogue: 0,0:00:01.50,0:00:02.75,Default,Hello, world/);
    assert.match(shift(ass,-500),/Dialogue: 0,0:00:00.00,0:00:01.00,Default,Hello, world/);
  });
  test(name+' validates the offset and does not write negative or expired cues',()=>{
    const srt='1\n00:00:00,000 --> 00:00:00,300\nHi';
    assert.throws(()=>shift(srt,-500),/No subtitle cues remain/);
    assert.throws(()=>shift(srt,300001),/between -300000 and 300000/);
    assert.throws(()=>shift(srt,1.5),/integer/);
    assert.throws(()=>shift('1\nnot a timestamp --> nope\nHi',100),/Invalid SRT timing/);
  });
}
