import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { sha256Blob } from "../cia-sha256.mjs";
test("bounded CIA hashing agrees with independent SHA-256 at padding and read boundaries", async () => {
  for (const size of [0, 3, 55, 56, 63, 64, 65, 1048575, 1048576, 1048577]) {
    const bytes = new Uint8Array(size);
    for (let i = 0; i < size; i++) bytes[i] = i % 251;
    assert.equal(
      Buffer.from(await sha256Blob(new Blob([bytes]))).toString("hex"),
      createHash("sha256").update(bytes).digest("hex"),
    );
  }
});

test('fixed-memory WASM hashing matches crypto for padding, chunks and concurrent calls',async()=>{
  const {readFile}=await import('node:fs/promises');
  const {sha256BlobWasm}=await import('../cia-sha256-wasm.mjs');
  const module=await WebAssembly.compile(await readFile(new URL('../cia-sha256-core.wasm',import.meta.url)));
  assert.deepEqual(WebAssembly.Module.imports(module),[]);
  const core=await WebAssembly.instantiate(module);
  assert.equal(core.exports.memory.buffer.byteLength,2*1024**2);
  assert.throws(()=>core.exports.memory.grow(1),RangeError);
  await Promise.all([0,3,55,56,63,64,65,1048575,1048576,1048577,2097217].map(async size=>{
    const bytes=new Uint8Array(size);for(let i=0;i<size;i++)bytes[i]=i%251;
    assert.equal(Buffer.from(await sha256BlobWasm(new Blob([bytes]),module)).toString('hex'),createHash('sha256').update(bytes).digest('hex'));
  }));
});
