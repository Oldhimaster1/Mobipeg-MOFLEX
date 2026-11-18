import test from "node:test";
import assert from "node:assert/strict";
import { tileRgb565 } from "../cia-artwork.mjs";
test("3DS texture packing retains tile order, RGB565 and white alpha composition", () => {
  const pixels = new Uint8Array(16 * 8 * 4);
  for (let y = 0; y < 8; y++)
    for (let x = 0; x < 16; x++)
      pixels.set([x < 8 ? 255 : 0, y < 4 ? 0 : 255, 0, 255], (y * 16 + x) * 4);
  const result = tileRgb565(pixels, 16, 8),
    v = new DataView(result.buffer);
  assert.equal(v.getUint16(0, true), 0xf800);
  assert.equal(v.getUint16(32 * 2, true), 0xffe0);
  assert.equal(v.getUint16(64 * 2, true), 0);
  assert.equal(v.getUint16(96 * 2, true), 0x07e0);
  assert.equal(
    new DataView(tileRgb565(new Uint8Array(8 * 8 * 4), 8, 8).buffer).getUint16(
      0,
      true,
    ),
    0xffff,
  );
  assert.throws(() => tileRgb565(pixels, 15, 8), /dimensions/);
});
