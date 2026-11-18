import test from 'node:test';
import assert from 'node:assert/strict';
import {wasmRuntimeOptions} from '../wasm-runtime.mjs';
test('WebKit reserves its shared working heap before pthread initialization',()=>{
  const options=wasmRuntimeOptions('Mozilla/5.0 AppleWebKit/605.1.15 Version/26.0 Safari/605.1.15');
  assert.ok(options.wasmMemory.buffer instanceof SharedArrayBuffer);
  assert.equal(options.wasmMemory.buffer.byteLength,128*1024*1024);
  assert.deepEqual(wasmRuntimeOptions('Mozilla/5.0 AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36'),{});
  assert.deepEqual(wasmRuntimeOptions('Firefox/140.0'),{});
});
