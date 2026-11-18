// Keep the version tied to the bitstream and the range scheduling rules.
const VERSION = 1;
const ENCODER = 'v15-1e46f0db1a';
const CHUNK_BYTES = 8 * 1024 * 1024;
const manifestName = 'checkpoint.json';
const checkpointName = index => `range-${index}.json`;

function hex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

// Hash bounded chunks, then hash their concatenated SHA-256 digests.
export async function fileDigest(file, cancelled = () => false) {
  const hashes = new Uint8Array(Math.ceil(file.size / CHUNK_BYTES) * 32);
  for (let offset = 0, index = 0; offset < file.size; offset += CHUNK_BYTES, index++) {
    if (cancelled()) throw Error('Cancelled');
    const bytes = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
    hashes.set(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), index * 32);
  }
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', hashes)));
}

async function readRecord(dir, name) {
  try {
    const file = await (await dir.getFileHandle(name)).getFile();
    if (file.size > 1024 * 1024) return null;
    return JSON.parse(await file.text());
  } catch (error) {
    if (error.name === 'NotFoundError' || error instanceof SyntaxError) return null;
    throw error;
  }
}

async function writeRecord(dir, name, value) {
  const handle = await dir.getFileHandle(name, {create:true});
  const writer = await handle.createWritable();
  try {
    await writer.write(JSON.stringify(value));
    await writer.close();
  } catch (error) {
    await writer.abort().catch(() => {});
    throw error;
  }
}

async function holdLock(locks, id) {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let request;
  await new Promise((resolve, reject) => {
    request = locks.request(id, {ifAvailable:true}, async lock => {
      if (!lock) {
        reject(Error('This movie is already being converted in another tab.'));
        return;
      }
      resolve();
      await held;
    }).catch(reject);
  });
  return async () => {
    release();
    await request;
  };
}

export async function openCheckpoint(source, settings, {storage, locks, cancelled}) {
  const identity = {name:source.name, bytes:source.size, sha256:await fileDigest(source, cancelled)};
  if (cancelled()) throw Error('Cancelled');
  const config = {version:VERSION, encoder:(settings.mode==='2d'?ENCODER:ENCODER+'-stereo-layout1')+(settings.maxMB!=null&&settings.movieAudio?'-scene-v1':''), identity, settings};
  const key = new TextEncoder().encode(JSON.stringify(config));
  const id = 'resume-' + hex(new Uint8Array(await crypto.subtle.digest('SHA-256', key)));
  const release = await holdLock(locks, id);
  try {
    const root = await (await storage.getDirectory()).getDirectoryHandle('mobipeg-long-movies', {create:true});
    const work = await root.getDirectoryHandle(id, {create:true});
    let manifest = await readRecord(work, manifestName);
    if (!manifest || JSON.stringify(manifest.config) !== JSON.stringify(config) ||
        typeof manifest.generation !== 'string') {
      manifest = {config, generation:crypto.randomUUID(), media:null};
      await writeRecord(work, manifestName, manifest);
    }
    return {
      id, root, work, segments:[], manifest, release, writes:new Set(),
      outputName:`movie-${crypto.randomUUID()}.moflex`,
    };
  } catch (error) {
    await release();
    throw error;
  }
}

function track(job, pending) {
  job.writes.add(pending);
  return pending.finally(() => job.writes.delete(pending));
}

export function setCheckpointMedia(job, media) {
  job.manifest.media = media;
  return track(job, writeRecord(job.work, manifestName, job.manifest));
}

export function persistRange(job, index, clip, savePart) {
  return track(job, (async () => {
    const part = await savePart();
    const sha256 = await fileDigest(part.file);
    await writeRecord(job.work, checkpointName(index), {
      generation:job.manifest.generation, index, clip,
      frames:part.frames, bytes:part.file.size, sha256,
    });
    return part;
  })());
}

export async function restoreCheckpoints(job, clips, readPart, cancelled = () => false) {
  for (const clip of clips) {
    if (cancelled()) throw Error('Cancelled');
    const entry = await readRecord(job.work, checkpointName(clip.index));
    if (entry?.generation !== job.manifest.generation || entry.index !== clip.index ||
        entry.clip?.start !== clip.start || entry.clip?.seconds !== clip.seconds ||
        !Number.isSafeInteger(entry.frames) || entry.frames <= 0 || entry.frames > clip.codedFrames + 2) continue;
    try {
      const part = await readPart(clip.index, entry.frames);
      if (part.file.size === entry.bytes && await fileDigest(part.file, cancelled) === entry.sha256)
        job.segments[clip.index] = part;
    } catch (error) {
      if (error.name !== 'NotFoundError') throw error;
    }
  }
}

export async function closeCheckpoint(job, completed) {
  try {
    await Promise.allSettled(job.writes);
    if (completed) {
      await job.work.removeEntry(manifestName);
      for (const [index, part] of job.segments.entries()) {
        if (!part) continue;
        await job.work.removeEntry(checkpointName(index)).catch(() => {});
        await job.work.removeEntry(part.name).catch(() => {});
      }
    }
  } finally {
    await job.release();
  }
}

export async function pruneCheckpoint(job, locks = navigator.locks) {
  await locks.request(job.id, {ifAvailable:true}, async lock => {
    if (!lock) return;
    for await (const name of job.work.keys()) return;
    await job.root.removeEntry(job.id);
  });
}
