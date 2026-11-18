import {sha256BlobWasm} from './cia-sha256-wasm.mjs?v=20261118h';
// Incremental SHA-256 for Blob contents. Each read is bounded to 1 MiB.
const constants = [];
const initial = [];
for (let candidate = 2; constants.length < 64; candidate++) {
  let prime = true;
  for (let divisor = 2; divisor * divisor <= candidate; divisor++)
    if (candidate % divisor === 0) {
      prime = false;
      break;
    }
  if (prime) {
    if (initial.length < 8)
      initial.push(((Math.sqrt(candidate) % 1) * 0x100000000) >>> 0);
    constants.push(((Math.cbrt(candidate) % 1) * 0x100000000) >>> 0);
  }
}
const rotate = (x, n) => (x >>> n) | (x << (32 - n));
export async function sha256BlobJS(blob) {
  const state = initial.slice(),
    words = new Uint32Array(64);
  function compress(bytes, offset) {
    const input = new DataView(bytes.buffer, bytes.byteOffset + offset, 64);
    for (let i = 0; i < 16; i++) words[i] = input.getUint32(i * 4, false);
    for (let i = 16; i < 64; i++) {
      const a = words[i - 15],
        b = words[i - 2];
      words[i] =
        (words[i - 16] +
          (rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3)) +
          words[i - 7] +
          (rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10))) >>>
        0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let i = 0; i < 64; i++) {
      const first =
        (h +
          (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) +
          ((e & f) ^ (~e & g)) +
          constants[i] +
          words[i]) >>>
        0;
      const second =
        ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) +
          ((a & b) ^ (a & c) ^ (b & c))) >>>
        0;
      h = g;
      g = f;
      f = e;
      e = (d + first) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (first + second) >>> 0;
    }
    for (const [i, value] of [a, b, c, d, e, f, g, h].entries())
      state[i] = (state[i] + value) >>> 0;
  }
  let tail = new Uint8Array();
  for (let offset = 0; offset < blob.size; offset += 1048576) {
    const bytes = new Uint8Array(
      await blob.slice(offset, offset + 1048576).arrayBuffer(),
    );
    const end = bytes.length - (bytes.length % 64);
    for (let p = 0; p < end; p += 64) compress(bytes, p);
    tail = bytes.slice(end);
  }
  const padding = new Uint8Array(tail.length < 56 ? 64 : 128);
  padding.set(tail);
  padding[tail.length] = 128;
  new DataView(padding.buffer).setBigUint64(
    padding.length - 8,
    BigInt(blob.size) * 8n,
    false,
  );
  for (let p = 0; p < padding.length; p += 64) compress(padding, p);
  const result = new Uint8Array(32),
    output = new DataView(result.buffer);
  for (let i = 0; i < 8; i++) output.setUint32(i * 4, state[i], false);
  return result;
}

let modulePromise;
async function loadCore(){
  if(!modulePromise)modulePromise=(async()=>{
    try{
      const response=await fetch(new URL('./cia-sha256-core.wasm?v=20261118h',import.meta.url));
      if(!response.ok)return null;
      return await WebAssembly.compile(await response.arrayBuffer());
    }catch{return null;}
  })();
  return modulePromise;
}
export async function sha256Blob(blob){
  const module=await loadCore();
  return module?sha256BlobWasm(blob,module):sha256BlobJS(blob);
}
