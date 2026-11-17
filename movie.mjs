// Movie assembly for independent, seek-indexed MOFLEX segments.
// Works with the existing unmodified V15 WASM encoder, keeping each trial small.
// All temporary files and the final output stay in the browser's private storage.
const BLOCK = 4096;
const MAX_INDEX_ENTRIES = 50000;
const expect = (ok, reason) => { if (!ok) throw Error('Movie assembly: ' + reason); };
const u16 = (b, p) => (b[p] << 8) | b[p + 1];
const bytesEqual = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const view = b => new DataView(b.buffer, b.byteOffset, b.byteLength);
const toNumber = v => { expect(v <= BigInt(Number.MAX_SAFE_INTEGER), 'integer exceeds safe range'); return Number(v); };
const readFile = async (file, from, size) => new Uint8Array(await file.slice(from, from + size).arrayBuffer());

function syncHeader(block) {
  expect(block.length === BLOCK && u16(block, 0) === 0x4c32, 'missing 4C32 sync header');
  expect(u16(block, 12) === BLOCK - 1, 'unexpected MOFLEX block size');
  let p = 14;
  function varInt() {
    let v = 0, n = 0, b;
    do {
      expect(p < BLOCK && ++n <= 4, 'invalid descriptor length');
      b = block[p++];
      v = (v << 7) | (b & 127);
    } while (b & 128);
    return v;
  }
  let dataStream = -1, streams = 0;
  for (let count = 0; count < 16; count++) {
    const type = varInt(), length = varInt();
    if (type === 0) { expect(length === 0, 'malformed descriptor terminator'); break; }
    expect(p + length < BLOCK, 'descriptor outside block');
    if (type === 4) { expect(length === 2, 'unsupported data descriptor'); dataStream = block[p]; }
    if (type === 3) streams++;
    p += length;
    if (count === 15) throw Error('Too many MOFLEX descriptors');
  }
  expect(dataStream >= 0 && streams === 1, 'expected one MobiClip video and a seek-data stream');
  const stamp = view(block).getBigUint64(4, false);
  expect(u16(block, 2) === checksum(stamp), 'bad sync header checksum');
  return { flagAt: p, dataStream, descriptors: block.slice(14, p), stamp };
}
function ep(block, start) {
  let bit = start * 8;
  const next = () => { expect(bit < BLOCK * 8, 'truncated EP'); return (block[bit >> 3] >> (7 - (bit++ & 7))) & 1; };
  const read = n => { let value = 0; for (let i = 0; i < n; i++) value = (value * 2) + next(); return value; };
  let nr = 1;
  while (!next()) { nr++; expect(nr <= 5, 'invalid EP stream code'); }
  const stream = read(nr), end = next();
  if (end) read(32); // frame type, signed relative timestamp, 28-bit relative clock
  const length = read(13) + 1;
  const dataAt = Math.ceil(bit / 8);
  expect(dataAt + length <= BLOCK, 'EP payload extends outside block');
  return { stream, end:!!end, dataAt, length };
}
function bits(value, count, out) {
  for (let i = count - 1; i >= 0; i--) out.push((value >> i) & 1);
}
function makeEp(stream, end, size) {
  expect(size > 0 && size <= 8192, 'invalid EP payload length');
  const nr = stream <= 1 ? 1 : Math.floor(Math.log2(stream)) + 1;
  const b = Array(nr - 1).fill(0);
  b.push(1);
  bits(stream, nr, b);
  b.push(end ? 1 : 0);
  if (end) { b.push(1, 0, 0, 1); for (let i = 0; i < 28; i++) b.push(0); }
  bits(size - 1, 13, b);
  const result = new Uint8Array(Math.ceil(b.length / 8));
  b.forEach((v, i) => { if (v) result[i >> 3] |= 1 << (7 - (i & 7)); });
  return result;
}
function checksum(ts) {
  let sum = 0xaaaa;
  for (let i = 0n; i < 64n; i += 16n) sum ^= Number((ts >> i) & 0xffffn);
  return sum;
}
function setSyncHeader(block, stamp) {
  const dv = view(block);
  dv.setUint16(0, 0x4c32, false);
  dv.setUint16(2, checksum(stamp), false);
  dv.setBigUint64(4, stamp, false);
  dv.setUint16(12, BLOCK - 1, false);
}
export function createFront(desc, dataStream, entries, frameCount, durationUs) {
  const blob = new Uint8Array(16 + entries.length * 24);
  const dv = view(blob);
  dv.setUint32(0, entries.length, true);
  dv.setUint32(4, frameCount, true);
  dv.setUint32(8, Number(durationUs > 0xffffffffn ? 0xffffffffn : durationUs), true);
  dv.setUint32(12, 0, true);
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i], at = 16 + i * 24;
    dv.setBigUint64(at, e.frame, true);
    dv.setBigUint64(at + 8, e.time, true);
    dv.setBigUint64(at + 16, e.offset, true);
  }
  const blocks = [];
  let cursor = 0;
  while (cursor < blob.length) {
    const block = new Uint8Array(BLOCK);
    let pos = 0;
    if (!blocks.length) {
      setSyncHeader(block, 1n);
      block.set(desc, 14);
      pos = 14 + desc.length;
    }
    block[pos++] = 2 << 2; // index blocks use the native muxer's counter 2
    const remaining = blob.length - cursor;
    let header = makeEp(dataStream, true, remaining <= 8192 ? remaining : 8192);
    if (remaining + header.length <= BLOCK - pos) {
      block.set(header, pos); pos += header.length;
      block.set(blob.subarray(cursor), pos); cursor = blob.length;
    } else {
      const partialHeader = makeEp(dataStream, false, 1);
      const take = Math.min(remaining - 1, BLOCK - pos - partialHeader.length);
      expect(take > 0, 'front index packet cannot fit');
      header = makeEp(dataStream, false, take);
      block.set(header, pos); pos += header.length;
      block.set(blob.subarray(cursor, cursor + take), pos);
      cursor += take;
    }
    blocks.push(block);
    expect(blocks.length <= 1024, 'seek index too large');
  }
  const bytes = new Uint8Array(blocks.length * BLOCK);
  blocks.forEach((b, i) => bytes.set(b, i * BLOCK));
  return bytes;
}
export async function inspectMovieSegment(file, expectedFrames) {
  expect(file && file.size >= 2 * BLOCK && file.size % BLOCK === 0, 'segment has invalid length');
  const header = await readFile(file, 0, BLOCK);
  const meta = syncHeader(header);
  const indexData = [];
  let total = 0, done = false, blockNo = 0;
  while (!done) {
    expect(blockNo * BLOCK < file.size, 'unterminated front seek table');
    const block = blockNo === 0 ? header : await readFile(file, blockNo * BLOCK, BLOCK);
    const start = blockNo === 0 ? meta.flagAt : 0;
    expect((block[start] >> 2) === 2, 'index block has unexpected counter');
    const packet = ep(block, start + 1);
    expect(packet.stream === meta.dataStream, 'front packet is not seek-data');
    const piece = block.subarray(packet.dataAt, packet.dataAt + packet.length);
    indexData.push(piece); total += piece.length;
    done = packet.end;
    blockNo++;
    expect(blockNo <= 1024 && total <= 1024 * BLOCK, 'seek index is too large');
  }
  const frontSize = blockNo * BLOCK;
  const binary = new Uint8Array(total);
  let cursor = 0;
  for (const piece of indexData) { binary.set(piece, cursor); cursor += piece.length; }
  expect(total >= 16, 'missing seek header');
  const dv = view(binary), n = dv.getUint32(0, true), frames = dv.getUint32(4, true);
  expect(n > 0 && n <= MAX_INDEX_ENTRIES && total === 16 + n * 24, 'bad seek entry count');
  expect(!expectedFrames || frames === expectedFrames, 'seek count does not match encoded frames');
  const entries = [];
  for (let i = 0; i < n; i++) {
    const p = 16 + i * 24;
    const frame = dv.getBigUint64(p, true);
    const time = dv.getBigUint64(p + 8, true);
    const offset = dv.getBigUint64(p + 16, true);
    expect(offset >= BigInt(frontSize) && offset < BigInt(file.size) && offset % BigInt(BLOCK) === 0n, 'seek entry points outside media');
    if (i) expect(frame >= entries[i - 1].frame && time > entries[i - 1].time && offset > entries[i - 1].offset, 'seek entries are out of order');
    entries.push({ frame, time, offset });
  }
  expect(entries[0].offset === BigInt(frontSize), 'first media sync not at front boundary');
  const first = await readFile(file, frontSize, BLOCK);
  const med = syncHeader(first);
  expect(bytesEqual(med.descriptors, meta.descriptors), 'media descriptor differs from front');
  expect(med.stamp === entries[0].time, 'media clock differs from seek table');
  return { durationUs:dv.getUint32(8,true), file, frontSize, mediaSize:file.size - frontSize, frames, entries, descriptors:meta.descriptors, dataStream:meta.dataStream };
}
export function getCodedRate(settings) {
  const parts = String(settings.fps).split('/');
  const num = Number(parts[0]), den = Number(parts[1] || 1);
  expect(num > 0 && den > 0, 'invalid frame rate');
  return { num: settings.mode === '2d' ? num : num * 2, den };
}
export function nextMovieClip(frameCount, seconds, fps, targetSeconds = 30) {
  const duration = frameCount * fps.den / fps.num;
  const left = seconds - duration;
  if (left <= fps.den / (2 * fps.num)) return null;
  // Align chapter ends to both whole video pairs and 256-sample ADPCM blocks
  // at 48 kHz. Otherwise per-chapter audio padding accumulates over a movie.
  const gcd=(a,b)=>b?gcd(b,a%b):a;
  const quantum=256*fps.num/gcd(48000*fps.den,256*fps.num);
  const frames=Math.max(quantum,Math.floor(targetSeconds*fps.num/fps.den/quantum)*quantum);
  return { start: duration, seconds:Math.min(frames*fps.den/fps.num, left) };
}
// A clip is an encoder work unit, NOT a chapter in the source video.  This
// schedule is deterministic even if the input has no chapters or keyframes.
export function planMovieClips(seconds, settings, targetSeconds = 30) {
  expect(Number.isFinite(seconds) && seconds > 0, 'invalid movie duration');
  const fps = getCodedRate(settings);
  const eyes=settings.mode==='2d'?1:2;
  const result = [];
  let frames = 0;
  const limit = Math.ceil(seconds / 5) + 4;
  for (;;) {
    const clip = nextMovieClip(frames, seconds, fps, targetSeconds);
    if (!clip) break;
    // Stereo encoder gets one whole L/R pair per displayed frame. The tail
    // must never request an odd number of coded frames.
    const codedFrames = Math.round(clip.seconds * fps.num / fps.den /eyes)*eyes;
    if(codedFrames===0)break; // sub-half-frame trailer of a fractional movie
    expect(result.length < limit, 'movie work schedule did not advance');
    result.push({ ...clip, index:result.length, codedFrames });
    frames += codedFrames;
  }
  expect(result.length > 0, 'movie has no encodable frames');
  return result;
}
export async function createMovieJob() {
  expect(navigator.storage && typeof navigator.storage.getDirectory === 'function', 'on-device OPFS storage is unavailable in this browser');
  const root = await navigator.storage.getDirectory();
  const id = 'job-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  const dir = await root.getDirectoryHandle('mobipeg-long-movies', { create:true });
  const work = await dir.getDirectoryHandle(id, { create:true });
  return { root:dir, work, id, segments:[], outputName:'movie.moflex' };
}
export async function appendMovieSegment(job, blob, frameCount, index = job.segments.length) {
  expect(blob && blob.size && frameCount > 0, 'empty movie segment');
  expect(Number.isSafeInteger(index) && index >= 0 && index < MAX_INDEX_ENTRIES, 'invalid segment index');
  expect(!job.segments[index], 'segment index already saved');
  expect(job.segments.reduce((n,p)=>n+p.file.size,0)+blob.size<4292870144, 'movie is approaching the FAT32 4 GiB limit; use a smaller quality setting');
  const name = 'part-' + String(index).padStart(5, '0') + '.moflex';
  const handle = await job.work.getFileHandle(name, { create:true });
  const writable = await handle.createWritable();
  try { await writable.write(blob); await writable.close(); }
  catch (err) { await writable.abort().catch(() => {}); throw err; }
  const file = await handle.getFile();
  job.segments[index] = { name, file, frames:frameCount };
  return file;
}
export async function assembleMovie(job, settings, progress = () => {}, cancelled = () => false) {
  expect(job.segments.length > 0, 'no chapters to join');
  expect(job.segments.every(Boolean), 'missing encoded segment in movie timeline');
  const fps = getCodedRate(settings), parts = [];
  let count = 0, bytes = 0n, frames = 0n;
  for (const part of job.segments) {
    if (cancelled()) throw Error('Cancelled');
    const info = await inspectMovieSegment(part.file, part.frames);
    if (parts.length) expect(bytesEqual(info.descriptors, parts[0].descriptors) && info.dataStream === parts[0].dataStream, 'inconsistent chapter codecs');
    parts.push(info);
    count += info.entries.length;
    bytes += BigInt(info.mediaSize);
    frames += BigInt(info.frames);
    expect(count <= MAX_INDEX_ENTRIES && frames <= 0xffffffffn, 'movie exceeds seek-table capacity');
  }
  const entries = [];
  let mediaStart = 0n, frameStart = 0n;
  for (const part of parts) {
    part.timeOffset = frameStart * 1000000n * BigInt(fps.den) / BigInt(fps.num);
    part.frameOffset = frameStart;
    part.mediaStart = mediaStart;
    for (const e of part.entries) entries.push({
      frame:e.frame + frameStart,
      time:e.time + part.timeOffset,
      offset:mediaStart + e.offset - BigInt(part.frontSize),
    });
    mediaStart += BigInt(part.mediaSize);
    frameStart += BigInt(part.frames);
  }
  const durationUs = frames * 1000000n * BigInt(fps.den) / BigInt(fps.num);
  const desc = parts[0].descriptors, index = parts[0].dataStream;
  const placeholder = createFront(desc, index, entries, Number(frames), durationUs);
  const frontLength = BigInt(placeholder.byteLength);
  const front = createFront(desc, index, entries.map(e => ({...e, offset:e.offset + frontLength})), Number(frames), durationUs);
  expect(front.byteLength === placeholder.byteLength, 'seek front changed size');
  expect(frontLength + bytes < 4294967296n, 'final movie exceeds the FAT32 4 GiB file limit; choose a smaller quality setting or split the film');
  const estimate=await globalThis.navigator?.storage?.estimate?.();
  if(estimate?.quota&&Number.isFinite(estimate.usage))expect(estimate.quota-estimate.usage>Number(frontLength+bytes), 'not enough free browser storage to assemble the movie; free space and retry');
  const handle = await job.work.getFileHandle(job.outputName, { create:true });
  const writable = await handle.createWritable();
  try {
    await writable.write(front);
    let previousCounter = 2;
    let written = 0n;
    for (let chapter = 0; chapter < parts.length; chapter++) {
      const part = parts[chapter], seekOffsets = new Map(part.entries.map(e => [toNumber(e.offset - BigInt(part.frontSize)), e.time]));
      let shift = 0, first = true;
      for (let off = 0; off < part.mediaSize; off += 128 * BLOCK) {
        if (cancelled()) throw Error('Cancelled');
        const size = Math.min(128 * BLOCK, part.mediaSize - off);
        const chunk = await readFile(part.file, part.frontSize + off, size);
        expect(size % BLOCK === 0, 'incomplete MOFLEX media block');
        for (let local = 0; local < size; local += BLOCK) {
          const block = chunk.subarray(local, local + BLOCK);
          const absolute = off + local;
          const isSync = seekOffsets.has(absolute);
          const hdr = isSync ? syncHeader(block) : null;
          const flag = hdr ? hdr.flagAt : 0;
          const original = block[flag] >> 2;
          if (first) {
            expect(isSync, 'chapter lacks first sync');
            shift = (previousCounter + 1 - original + 64) % 64;
            first = false;
          }
          const patched = (original + shift) & 63;
          block[flag] = (patched << 2) | (block[flag] & 3);
          previousCounter = patched;
          if (isSync) {
            expect(seekOffsets.has(absolute), 'sync header missing from front index');
            expect(hdr.stamp === seekOffsets.get(absolute), 'sync clock differs from front index');
            setSyncHeader(block, hdr.stamp + part.timeOffset);
            seekOffsets.delete(absolute);
          }
        }
        written += BigInt(size);
        await writable.write(chunk);
        progress({ chapter:chapter + 1, chapters:parts.length, written:toNumber(written), total:toNumber(bytes) });
      }
      expect(seekOffsets.size === 0, 'seek table refers to a non-sync block');
    }
    await writable.close();
  } catch (err) {
    await writable.abort().catch(() => {});
    throw err;
  }
  const result = await handle.getFile();
  expect(result.size === Number(frontLength + bytes), 'final file size changed');
  return { file:result, frames:Number(frames), seconds:Number(frames) * fps.den / fps.num, audio:!!job.audio, chapters:parts.length, durationFieldSaturated:durationUs > 0xffffffffn };
}
export async function cleanupMovieJob(job, keepResult = false) {
  if (!job) return;
  for (const part of job.segments.filter(Boolean)) {
    try { await job.work.removeEntry(part.name); } catch {}
  }
  if (!keepResult) {
    try { await job.work.removeEntry(job.outputName); } catch {}
    try { await job.root.removeEntry(job.id, { recursive:true }); } catch {}
  }
}
