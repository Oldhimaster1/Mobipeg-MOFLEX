import test from 'node:test';
import assert from 'node:assert/strict';
import {createHdrLut,hdrPixel,hdrTransferFromLog,selectedHdrTransfer,hdrFilter} from '../hdr-lut.mjs';
test('HDR metadata recognition',()=>{
  assert.equal(hdrTransferFromLog('Stream #0:0: Video: hevc, yuv420p10le(tv, bt2020nc/bt2020/smpte2084)'), 'pq');
  assert.equal(hdrTransferFromLog('Stream #0:0: Video: hevc, yuv420p10le(tv, bt2020nc/bt2020/arib-std-b67)'), 'hlg');
  assert.equal(hdrTransferFromLog('Stream #0:1: Audio: smpte2084'),null);
});
test('SDR passthrough and manual HDR override',()=>{
  assert.equal(selectedHdrTransfer({hdrTransfer:'pq'},{hdrMode:'off',hdrTransfer:'auto'}),null);
  assert.equal(selectedHdrTransfer({hdrTransfer:null},{hdrMode:'auto',hdrTransfer:'hlg'}),'hlg');
  assert.equal(selectedHdrTransfer({hdrTransfer:null},{hdrMode:'auto',hdrTransfer:'auto'}),null);
  assert.equal(hdrFilter({hdrMode:'auto'},null),'');
  assert.match(hdrFilter({hdrMode:'auto'},'pq'),/lut3d=/);
});
test('LUT entries are bounded and neutral for white/grey',()=>{
  for(const tr of ['pq','hlg'])for(const op of ['mobius','hable','reinhard']){
    for(const v of [0,.1,.5,.9,1]){
      const rgb=hdrPixel(v,v,v,tr,op);
      assert.ok(rgb.every(x=>Number.isFinite(x)&&x>=0&&x<=1));
      assert.ok(Math.max(...rgb)-Math.min(...rgb)<.0001);
    }
    assert.equal(createHdrLut(tr,op,9).trim().split('\n').length,4+9**3);
  }
});
test('invalid LUT settings are rejected',()=>{
  assert.throws(()=>createHdrLut('sdr','mobius'),/Unsupported/);
  assert.throws(()=>createHdrLut('pq','clip'),/Unsupported/);
  assert.throws(()=>createHdrLut('pq','mobius',1),/Invalid/);
});
