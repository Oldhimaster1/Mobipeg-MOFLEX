import { makeEpisodeArtwork } from "./cia-artwork.mjs";
const view = (b) => new DataView(b.buffer, b.byteOffset, b.byteLength);
const u32 = (b, o) => view(b).getUint32(o, true);
const put = (b, o, n) => view(b).setUint32(o, n, true);
export function decompressLz11(input) {
  if (input.length < 4 || input[0] !== 0x11)
    throw Error("Banner model is not LZ11");
  const size = u32(input, 0) >>> 8;
  if (!size || size > 8 * 1024 * 1024)
    throw Error("Unsupported banner model size");
  const output = new Uint8Array(size);
  let p = 4,
    out = 0;
  const byte = () => {
    if (p >= input.length) throw Error("Truncated LZ11 model");
    return input[p++];
  };
  while (out < size) {
    const flags = byte();
    for (let bit = 7; bit >= 0 && out < size; bit--) {
      if (!(flags & (1 << bit))) {
        output[out++] = byte();
        continue;
      }
      const first = byte(),
        type = first >>> 4;
      let length, distance;
      if (type === 0) {
        const second = byte(),
          third = byte();
        length = ((first & 15) << 4) + (second >>> 4) + 17;
        distance = ((second & 15) << 8) + third + 1;
      } else if (type === 1) {
        const second = byte(),
          third = byte(),
          fourth = byte();
        length = ((first & 15) << 12) + (second << 4) + (third >>> 4) + 273;
        distance = ((third & 15) << 8) + fourth + 1;
      } else {
        length = type + 1;
        distance = ((first & 15) << 8) + byte() + 1;
      }
      if (distance > out || out + length > size)
        throw Error("Invalid LZ11 back reference");
      for (let i = 0; i < length; i++) {
        output[out] = output[out - distance];
        out++;
      }
    }
  }
  return output;
}
export function literalLz11(bytes) {
  if (!bytes.length || bytes.length > 0xffffff)
    throw Error("Invalid LZ11 size");
  const output = new Uint8Array(4 + bytes.length + Math.ceil(bytes.length / 8));
  put(output, 0, (bytes.length << 8) | 0x11);
  let position = 4;
  for (let offset = 0; offset < bytes.length; offset += 8) {
    output[position++] = 0;
    const group = bytes.subarray(offset, offset + 8);
    output.set(group, position);
    position += group.length;
  }
  return output;
}
export function bannerTextureRanges(model) {
  if (new TextDecoder().decode(model.subarray(0, 4)) !== "CGFX")
    throw Error("Invalid banner CGFX");
  const header = view(model).getUint16(6, true),
    count = u32(model, 16),
    ranges = [];
  if (count > 64) throw Error("Invalid banner dictionary count");
  for (let n = 0; n < count; n++) {
    const pointer = header + 12 + n * 8;
    if (pointer + 4 > model.length) throw Error("Invalid CGFX dictionary");
    const relative = u32(model, pointer);
    if (!relative) continue;
    const dict = pointer + relative;
    const entries = u32(model, dict + 8);
    if (entries > 4096) throw Error("Invalid banner dictionary");
    for (let i = 0; i < entries; i++) {
      const ref = dict + 0x28 + i * 16;
      const object = ref + u32(model, ref);
      if (object + 0x4c > model.length) throw Error("Invalid CGFX object");
      if (
        u32(model, object + 0x18) !== 128 ||
        u32(model, object + 0x1c) !== 256 ||
        u32(model, object + 0x34) !== 3 ||
        u32(model, object + 0x44) !== 65536
      )
        continue;
      const start = object + 0x48 + u32(model, object + 0x48);
      if (start + 65536 > model.length) throw Error("Invalid CGFX texture");
      ranges.push(start);
    }
  }
  return [...new Set(ranges)];
}
export async function makeHomeBanner(image, original) {
  if (
    original.length < 136 ||
    new TextDecoder().decode(original.subarray(0, 4)) !== "CBMD"
  )
    throw Error("Invalid template banner");
  const texture = new Uint8Array(
    await (await makeEpisodeArtwork(image, new Blob([new Uint8Array(65568)])))
      .slice(32)
      .arrayBuffer(),
  );
  const header = original.slice(0, 136),
    parts = [header];
  let size = 136,
    changed = 0;
  for (let i = 0; i < 14; i++) {
    const start = u32(original, 8 + i * 4);
    if (!start) continue;
    const later = [];
    for (let j = 0; j < 14; j++) {
      const other = u32(original, 8 + j * 4);
      if (other > start) later.push(other);
    }
    const audio = u32(original, 132);
    if (audio > start) later.push(audio);
    const end = Math.min(original.length, ...later),
      model = decompressLz11(original.subarray(start, end));
    const ranges = bannerTextureRanges(model);
    if (ranges.length > 1)
      throw Error("Banner has multiple matching textures; use a prepared CBMD");
    for (const offset of ranges) {
      model.set(texture, offset);
      changed++;
    }
    const compressed = literalLz11(model);
    put(header, 8 + i * 4, size);
    parts.push(compressed);
    size += compressed.length;
  }
  if (!changed)
    throw Error(
      "Template banner has no supported 256×128 RGB565 image texture",
    );
  const pad = (16 - (size % 16)) % 16;
  parts.push(new Uint8Array(pad));
  size += pad;
  const audio = u32(original, 132);
  put(header, 132, audio ? size : 0);
  if (audio) {
    if (audio < 136 || audio >= original.length)
      throw Error("Invalid template banner audio");
    parts.push(original.subarray(audio));
  }
  return new Uint8Array(await new Blob(parts).arrayBuffer());
}
