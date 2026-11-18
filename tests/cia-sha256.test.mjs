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
