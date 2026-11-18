import {bannerWithWav} from './cia-banner-audio.mjs';
import {makeHomeBanner} from './cia-banner.mjs';
import {isArtworkImage,makeSmdhArtwork,makeEpisodeArtwork} from './cia-artwork.mjs';
import { rebuildRomfsMetadata } from "./cia-romfs.mjs";
import { sha256Blob } from "./cia-sha256.mjs?v=20261118h";
// Template-preserving CIA rebuild. No executable or template is distributed.
import { ciaTitleID, updateCiaLocaleSettings } from "./cia-project.mjs?v=20261118f";
const align = (n, b = 64) => Math.ceil(n / b) * b;
const view = (b) => new DataView(b.buffer, b.byteOffset, b.byteLength);
const u32 = (b, o) => view(b).getUint32(o, true);
const u64 = (b, o, le = true) => Number(view(b).getBigUint64(o, le));
const put32 = (b, o, n) => view(b).setUint32(o, n, true);
const put64 = (b, o, n, le = true) => view(b).setBigUint64(o, BigInt(n), le);
const read = async (b, o, n) => {
  if (o < 0 || n < 0 || o + n > b.size) throw Error("Truncated CIA section");
  return new Uint8Array(await b.slice(o, o + n).arrayBuffer());
};
const hash = async (b) =>
  b instanceof Blob
    ? sha256Blob(b)
    : new Uint8Array(await crypto.subtle.digest("SHA-256", b));
const equal = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const padded = (b, n = 64) =>
  new Blob([b, new Uint8Array(align(b.size, n) - b.size)]);
const text = (b, o, n) =>
  new TextDecoder().decode(b.subarray(o, o + n)).replace(/\0.*$/s, "");
const utf16 = (s) => {
  const b = new Uint8Array(s.length * 2);
  for (let i = 0; i < s.length; i++)
    view(b).setUint16(i * 2, s.charCodeAt(i), true);
  return b;
};
function sig(b) {
  const n = view(b).getUint32(0, false) - 0x10000;
  const size = [0x240, 0x140, 0x80, 0x240, 0x140, 0x80][n];
  if (!size) throw Error("Invalid signature type");
  return size;
}
export async function inspectCia(blob) {
  if (blob.size > 0xffffffff) throw Error("CIA exceeds FAT32");
  const header = await read(blob, 0, 0x2020);
  if (u32(header, 0) !== 0x2020) throw Error("Unsupported CIA header");
  const certSize = u32(header, 8),
    ticketSize = u32(header, 12),
    tmdSize = u32(header, 16);
  const ticketPos = align(0x2020) + align(certSize),
    tmdPos = ticketPos + align(ticketSize),
    contentPos = tmdPos + align(tmdSize);
  const tmd = await read(blob, tmdPos, tmdSize),
    ticket = await read(blob, ticketPos, ticketSize),
    s = sig(tmd);
  if (view(tmd).getUint16(s + 0x9e, false) !== 1)
    throw Error("Use a single-content decrypted player template");
  const record = s + 0x9c4,
    length = u64(tmd, record + 8, false);
  if (view(tmd).getUint16(record + 6, false) & 1)
    throw Error("Encrypted CIA templates are unsupported");
  if (u64(header, 24) !== align(length)) throw Error("Invalid content size");
  const content = blob.slice(contentPos, contentPos + length);
  if (contentPos + length > blob.size) throw Error("Truncated CIA content");
  if (
    content.size !== length ||
    !equal(await hash(content), tmd.subarray(record + 16, record + 48))
  )
    throw Error("CIA content hash mismatch");
  const ncch = await read(content, 0, 512);
  if (text(ncch, 256, 4) !== "NCCH" || !(ncch[0x18f] & 4))
    throw Error("A decrypted executable NCCH is required");
  if (!u32(ncch, 0x180) || !u32(ncch, 0x1a4) || !u32(ncch, 0x1b4))
    throw Error("Template has no executable player or movie filesystem");
  const title = view(tmd).getBigUint64(s + 0x4c, false);
  if (
    view(ticket).getBigUint64(sig(ticket) + 0x9c, false) !== title ||
    view(ncch).getBigUint64(0x118, true) !== title
  )
    throw Error("CIA title IDs disagree");
  for (const [offset, length, digest] of [
    [512, u32(ncch, 0x180), 0x160],
    [u32(ncch, 0x1a0) * 512, u32(ncch, 0x1a8) * 512, 0x1c0],
    [u32(ncch, 0x1b0) * 512, u32(ncch, 0x1b8) * 512, 0x1e0],
  ]) {
    if (
      offset + length > content.size ||
      !equal(
        await hash(content.slice(offset, offset + length)),
        ncch.subarray(digest, digest + 32),
      )
    )
      throw Error("NCCH section hash mismatch");
  }
  return {
    header,
    tmd,
    ticket,
    s,
    record,
    content,
    ncch,
    cert: blob.slice(align(0x2020), align(0x2020) + certSize),
  };
}
async function romfsFiles(content, ncch) {
  const romfs = content.slice(
    u32(ncch, 0x1b0) * 512,
    (u32(ncch, 0x1b0) + u32(ncch, 0x1b4)) * 512,
  );
  const ivfc = await read(romfs, 0, 96);
  if (text(ivfc, 0, 4) !== "IVFC") throw Error("Invalid RomFS");
  const base = align(96 + u32(ivfc, 8), 2 ** u32(ivfc, 0x4c));
  const h = await read(romfs, base, 40);
  if (u32(h, 0) !== 40) throw Error("Invalid RomFS metadata");
  const dataOffset = u32(h, 36);
  if (dataOffset > 16 * 1024 * 1024)
    throw Error("RomFS metadata exceeds the 16 MiB bound");
  const metadata = await read(romfs, base, dataOffset);
  const dm = u32(h, 12),
    fm = u32(h, 28),
    flen = u32(h, 32),
    files = [];
  const name = (o, n) =>
    new TextDecoder("utf-16le").decode(metadata.subarray(o, o + n));
  function dir(off) {
    if (off === 0) return "";
    if (off >= u32(h, 16)) throw Error("Invalid RomFS directory");
    return (
      dir(u32(metadata, dm + off)) +
      "/" +
      name(dm + off + 24, u32(metadata, dm + off + 20))
    );
  }
  for (let o = 0; o < flen; ) {
    const p = fm + o,
      n = u32(metadata, p + 28),
      path = dir(u32(metadata, p)) + "/" + name(p + 32, n);
    const offset = u64(metadata, p + 8),
      size = u64(metadata, p + 16);
    files.push({
      path,
      p,
      blob: romfs.slice(
        base + dataOffset + offset,
        base + dataOffset + offset + size,
      ),
    });
    o += align(32 + n, 4);
  }
  return { metadata, dataOffset, files };
}
async function hashBlocks(blob) {
  const hashes = new Uint8Array(Math.ceil(blob.size / 4096) * 32);
  for (let offset = 0; offset < blob.size; offset += 1048576) {
    const bytes = await read(
      blob,
      offset,
      Math.min(1048576, blob.size - offset),
    );
    for (let p = 0; p < bytes.length; p += 4096) {
      let block = bytes.subarray(p, p + 4096);
      if (block.length < 4096) {
        const padded = new Uint8Array(4096);
        padded.set(block);
        block = padded;
      }
      hashes.set(await hash(block), ((offset + p) / 4096) * 32);
    }
  }
  return new Blob([hashes]);
}
export async function buildRomfs(state) {
  const parts = [state.metadata];
  let offset = 0;
  for (const file of state.files) {
    offset = align(offset, 16);
    const previous =
      parts.reduce((n, b) => n + (b.size ?? b.byteLength), 0) -
      state.dataOffset;
    parts.push(new Uint8Array(offset - previous));
    put64(state.metadata, file.p + 8, offset);
    put64(state.metadata, file.p + 16, file.blob.size);
    parts.push(file.blob);
    offset += file.blob.size;
  }
  const data = new Blob(parts),
    l2 = await hashBlocks(data),
    l1 = await hashBlocks(l2),
    master = await hashBlocks(l1),
    header = new Uint8Array(96);
  header.set(new TextEncoder().encode("IVFC"));
  put32(header, 4, 0x10000);
  put32(header, 8, master.size);
  let logical = 0;
  for (const [i, level] of [l1, l2, data].entries()) {
    put64(header, 12 + i * 24, logical);
    put64(header, 20 + i * 24, level.size);
    put32(header, 28 + i * 24, 12);
    logical += align(level.size, 4096);
  }
  put32(header, 84, 0x5c);
  return new Blob([
    padded(new Blob([header, master]), 4096),
    padded(data, 4096),
    padded(l1, 4096),
    padded(l2, 4096),
  ]);
}
export async function buildCia({
  template,
  project,
  movies,
  icon = null,
  banner = null,
  bannerAudio = null,
  episodeBanners = [],
  onProgress = () => {},
}) {
  onProgress("Checking local player template");
  const t = await inspectCia(template);
  let state = await romfsFiles(t.content, t.ncch);
  const slots = state.files
    .filter((f) => /\/movie(?:_\d+)?\.moflex$/i.test(f.path))
    .sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true }));
  if (
    !Array.isArray(movies) ||
    movies.length < 1 ||
    movies.length > 27 ||
    project.movies.length !== movies.length
  )
    throw Error("Choose 1–27 matching movie entries");
  const settings = state.files.find(
    (f) => f.path === "/settings/settingsTL.csv",
  );
  const banners = state.files.find(
    (f) => f.path === "/settings/movie_bnrname.csv",
  );
  const decode = async (file) =>
    new TextDecoder("utf-16le").decode(await file.blob.arrayBuffer());
  const encode = (text) => new Blob([new Uint8Array([255, 254]), utf16(text)]);
  const settingsText = settings ? await decode(settings) : "";
  const collection =
    slots.some((f) => /movie_0\.moflex$/.test(f.path)) &&
    banners &&
    /# 動画の数\r?\n\d+/.test(settingsText);
  if (!collection && movies.length !== 1)
    throw Error("Multiple episodes require a collection-player template");
  if (!slots.length) throw Error("Template has no movie slots");
  const art = state.files.find((f) => /\/movie_0\.bimg$/.test(f.path));
  if (collection && !art)
    throw Error("Collection template has no episode thumbnail resource");
  state.files = state.files.filter(
    (f) => !slots.includes(f) && !/\/movie_\d+\.bimg$/.test(f.path),
  );
  for (let i = 0; i < movies.length; i++) {
    state.files.push({
      path: collection
        ? "/movie/movie_" + i + ".moflex"
        : "/movie/movie.moflex",
      blob: movies[i],
    });
    if (collection) {
      const thumbnail = isArtworkImage(episodeBanners[i]) ? await makeEpisodeArtwork(episodeBanners[i],art.blob) : episodeBanners[i] || art.blob;
      if (
        episodeBanners[i] &&
        (thumbnail.size !== art.blob.size ||
          !equal(await read(thumbnail, 0, 32), await read(art.blob, 0, 32)))
      )
        throw Error("Episode thumbnail must match the template BIMG format");
      state.files.push({
        path: "/movie/movie_" + i + ".bimg",
        blob: thumbnail,
      });
    }
  }
  if (collection) {
    settings.blob = encode(
      settingsText.replace(
        /(# 動画の数\r?\n)\d+/,
        (_, prefix) => prefix + movies.length,
      ),
    );
    banners.blob = encode(
      movies.length +
        "\r\n" +
        movies.map((_, i) => "movie_" + i + ".bimg").join("\r\n") +
        "\r\n",
    );
  }
  if (settings) {
    const value = updateCiaLocaleSettings(await decode(settings),project);
    settings.blob = encode(
      value.replace(
        /(# 拡張セーブデータのID（16進数）\r?\n)[^\r\n]+/,
        (_, prefix) => prefix + project.id,
      ),
    );
  }
  state = rebuildRomfsMetadata(state.files);
  const csv = state.files.find((f) => /\/movie_title\.csv$/.test(f.path));
  const escape = (s) => s.replace(/^#/, "\\x23").replaceAll(",", "\\x2C");
  csv.blob = new Blob([
    new Uint8Array([255, 254]),
    utf16(
      "#JP,#EN,#FR,#GE,#IT,#SP,#CH,#KO,#DU,#PO,#RU,#TW\r\n" +
        project.movies
          .map((m) =>
            Array(12)
              .fill(escape(m.title || m.file))
              .join(","),
          )
          .join("\r\n") +
        "\r\n",
    ),
  ]);
  onProgress("Building movie filesystem and integrity tree");
  const romfs = await buildRomfs(state);
  let romOffset = u32(t.ncch, 0x1b0) * 512;
  if (romOffset > 16 * 1024 * 1024)
    throw Error("Template executable exceeds the 16 MiB memory bound");
  let prefix = await read(t.content, 0, romOffset);
  const id = BigInt("0x" + ciaTitleID(project.id));
  put64(prefix, 0x108, id);
  put64(prefix, 0x118, id);
  // Both program-ID copies in the extended header must follow the NCCH ID.
  put64(prefix, 0x200 + 0x200, id);
  put64(prefix, 0x200 + 0x600, id);
  // VidInjector also stores the application unique ID in its extended header.
  put32(prefix, 0x200 + 0x1c9, Number(id >> 8n) & 0xfffff);
  prefix.set(
    await hash(prefix.subarray(0x200, 0x200 + u32(prefix, 0x180))),
    0x160,
  );
  const exOffset = u32(prefix, 0x1a0) * 512,
    exSize = u32(prefix, 0x1a4) * 512;
  const ex = prefix.subarray(exOffset, exOffset + exSize);
  let executable = false;
  for (let i = 0; i < 10; i++) {
    const o = i * 16,
      name = text(ex, o, 8),
      size = u32(ex, o + 12),
      start = 512 + u32(ex, o + 8);
    if (!size) continue;
    if (name === ".code") executable = true;
    if (name === "icon") {
      if (icon) {
        const replacement = isArtworkImage(icon) ? await makeSmdhArtwork(icon,ex.subarray(start,start+size)) : await read(icon, 0, icon.size);
        if (replacement.length !== size || text(replacement, 0, 4) !== "SMDH")
          throw Error("Custom icon must be a matching SMDH");
        ex.set(replacement, start);
      }
      if (text(ex, start, 4) !== "SMDH") throw Error("Unsupported player icon");
      for (let lang = 0; lang < 16; lang++)
        for (const [offset, value, max] of [
          [0, project.title, 64],
          [128, project.long_title || project.title, 128],
          [384, project.publisher, 64],
        ]) {
          const dst = ex.subarray(
            start + 8 + lang * 512 + offset,
            start + 8 + lang * 512 + offset + max * 2,
          );
          dst.fill(0);
          dst.set(utf16(value));
        }
      ex.set(await hash(ex.subarray(start, start + size)), 512 - (i + 1) * 32);
    }
  }
  if (!executable) throw Error("Player executable missing");
  if (banner || bannerAudio) {
    if(banner&&!isArtworkImage(banner)&&banner.size>16*1024*1024)throw Error('Prepared banner exceeds 16 MiB');
    const entries = [];
    for (let i = 0; i < 10; i++) {
      const o = i * 16,
        size = u32(ex, o + 12);
      if (size)
        entries.push({
          name: text(ex, o, 8),
          bytes: ex.slice(512 + u32(ex, o + 8), 512 + u32(ex, o + 8) + size),
        });
    }
    const entry = entries.find((e) => e.name === "banner");
    if (!entry) throw Error("Template has no banner slot");
    if(banner)entry.bytes = isArtworkImage(banner) ? await makeHomeBanner(banner,entry.bytes) : await read(banner, 0, banner.size);
    if(bannerAudio)entry.bytes=await bannerWithWav(entry.bytes,bannerAudio);
    if (entry.bytes.length < 0x84 || text(entry.bytes, 0, 4) !== "CBMD")
      throw Error("Supply a prepared banner binary with CBMD content");
    const eh = new Uint8Array(512),
      parts = [eh];
    let offset = 0;
    for (const [i, e] of entries.entries()) {
      eh.set(new TextEncoder().encode(e.name), i * 16);
      put32(eh, i * 16 + 8, offset);
      put32(eh, i * 16 + 12, e.bytes.length);
      eh.set(await hash(e.bytes), 512 - (i + 1) * 32);
      const part = padded(new Blob([e.bytes]), 512);
      parts.push(part);
      offset += part.size;
    }
    const rebuilt = new Blob(parts);
    prefix = new Uint8Array(
      await new Blob([prefix.subarray(0, exOffset), rebuilt]).arrayBuffer(),
    );
    romOffset = prefix.length;
    put32(prefix, 0x1a4, rebuilt.size / 512);
    put32(prefix, 0x1b0, romOffset / 512);
  }
  prefix.set(
    await hash(prefix.subarray(exOffset, exOffset + u32(prefix, 0x1a8) * 512)),
    0x1c0,
  );
  put32(prefix, 0x1b4, align(romfs.size, 512) / 512);
  put32(prefix, 0x104, (romOffset + align(romfs.size, 512)) / 512);
  prefix.set(await hash(romfs.slice(0, u32(prefix, 0x1b8) * 512)), 0x1e0);
  const content = new Blob([prefix, padded(romfs, 512)]);
  if (content.size > 0xffffffff - 65536)
    throw Error("Built content exceeds FAT32");
  onProgress("Hashing executable content and title metadata");
  put64(t.tmd, t.s + 0x4c, id, false);
  put64(t.tmd, t.record + 8, content.size, false);
  t.tmd.set(await hash(content), t.record + 16);
  // Content-info records hash their referenced content chunks, followed by the info table hash.
  for (let i = 0; i < 64; i++) {
    const p = t.s + 0xc4 + i * 36,
      start = view(t.tmd).getUint16(p, false),
      count = view(t.tmd).getUint16(p + 2, false);
    if (count)
      t.tmd.set(
        await hash(
          t.tmd.subarray(
            t.record + start * 48,
            t.record + (start + count) * 48,
          ),
        ),
        p + 4,
      );
  }
  t.tmd.set(await hash(t.tmd.subarray(t.s + 0xc4, t.s + 0x9c4)), t.s + 0xa4);
  put64(t.ticket, sig(t.ticket) + 0x9c, id, false);
  put32(t.header, 20, 0);
  put64(t.header, 24, align(content.size));
  const output = new Blob([
    padded(new Blob([t.header])),
    padded(t.cert),
    padded(new Blob([t.ticket])),
    padded(new Blob([t.tmd])),
    padded(content),
  ]);
  await inspectCia(output);
  onProgress("CIA content hash verified");
  return output;
}
