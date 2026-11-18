import test from "node:test";
import assert from "node:assert/strict";
import { decompressLz11, literalLz11 } from "../cia-banner.mjs";
import { wavToCwav } from "../cia-banner-audio.mjs";
test("LZ11 literal streams round-trip at flag boundaries and reject invalid references", () => {
  for (const size of [1, 7, 8, 9, 65536]) {
    const bytes = Uint8Array.from({ length: size }, (_, i) => i % 251);
    assert.deepEqual(decompressLz11(literalLz11(bytes)), bytes);
  }
  assert.throws(
    () => decompressLz11(new Uint8Array([17, 3, 0, 0, 128, 32, 0])),
    /reference/,
  );
  assert.throws(
    () => decompressLz11(new Uint8Array([17, 1, 0, 0])),
    /Truncated/,
  );
});
test("PCM16 stereo WAV is packed into sample-exact planar CWAV with bounded duration", () => {
  const wav = new Uint8Array(44 + 16),
    v = new DataView(wav.buffer),
    text = (o, s) => wav.set(new TextEncoder().encode(s), o);
  text(0, "RIFF");
  v.setUint32(4, wav.length - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 2, true);
  v.setUint32(24, 32000, true);
  v.setUint32(28, 128000, true);
  v.setUint16(32, 4, true);
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, 16, true);
  const samples = [100, -100, 200, -200, 300, -300, 400, -400];
  samples.forEach((sample, i) => v.setInt16(44 + i * 2, sample, true));
  const cwav = wavToCwav(wav),
    out = new DataView(cwav.buffer),
    info = out.getUint32(24, true),
    data = out.getUint32(36, true);
  assert.equal(new TextDecoder().decode(cwav.subarray(0, 4)), "CWAV");
  assert.equal(out.getUint32(info + 12, true), 32000);
  assert.equal(out.getUint32(info + 20, true), 4);
  assert.equal(out.getUint32(info + 28, true), 2);
  for (let channel = 0; channel < 2; channel++) {
    const entry = info + 28 + out.getUint32(info + 36 + channel * 8, true);
    const start = data + 8 + out.getUint32(entry + 4, true);
    for (let i = 0; i < 4; i++)
      assert.equal(out.getInt16(start + i * 2, true), samples[i * 2 + channel]);
  }
  v.setUint16(34, 24, true);
  assert.throws(() => wavToCwav(wav), /PCM16/);
});
