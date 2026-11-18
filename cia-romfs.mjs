// Rebuild RomFS level-three directory, file and hash tables for a changed tree.
const align = (n) => Math.ceil(n / 4) * 4;
const put = (bytes, offset, value) =>
  new DataView(bytes.buffer).setUint32(offset, value, true);
const nameBytes = (name) => {
  const bytes = new Uint8Array(name.length * 2);
  for (let i = 0; i < name.length; i++)
    new DataView(bytes.buffer).setUint16(i * 2, name.charCodeAt(i), true);
  return bytes;
};
function bucket(name, parent, count) {
  let hash = (parent ^ 123456789) >>> 0;
  for (let i = 0; i < name.length; i++)
    hash = (((hash >>> 5) | (hash << 27)) ^ name.charCodeAt(i)) >>> 0;
  return hash % count;
}
export function rebuildRomfsMetadata(files) {
  const directories = [
    { path: "", name: "", parent: null, dirs: [], files: [], offset: 0 },
  ];
  const byPath = new Map([["", directories[0]]]);
  for (const file of files) {
    const segments = file.path.split("/").filter(Boolean);
    let parent = directories[0],
      path = "";
    for (const segment of segments.slice(0, -1)) {
      path += "/" + segment;
      if (!byPath.has(path)) {
        const directory = { path, name: segment, parent, dirs: [], files: [] };
        byPath.set(path, directory);
        directories.push(directory);
        parent.dirs.push(directory);
      }
      parent = byPath.get(path);
    }
    file.name = segments.at(-1);
    file.parent = parent;
    parent.files.push(file);
  }
  let dirSize = 0,
    fileSize = 0;
  for (const directory of directories) {
    directory.offset = dirSize;
    dirSize += align(24 + directory.name.length * 2);
  }
  for (const file of files) {
    file.offset = fileSize;
    fileSize += align(32 + file.name.length * 2);
  }
  const dirBuckets = Math.max(3, directories.length | 1),
    fileBuckets = Math.max(3, files.length | 1);
  const dh = 40,
    dm = dh + dirBuckets * 4,
    fh = dm + dirSize,
    fm = fh + fileBuckets * 4,
    dataOffset = Math.ceil((fm + fileSize) / 16) * 16;
  if (dataOffset > 16 * 1024 * 1024)
    throw Error("RomFS metadata exceeds 16 MiB");
  const metadata = new Uint8Array(dataOffset);
  for (const [offset, value] of [
    [0, 40],
    [4, dh],
    [8, dirBuckets * 4],
    [12, dm],
    [16, dirSize],
    [20, fh],
    [24, fileBuckets * 4],
    [28, fm],
    [32, fileSize],
    [36, dataOffset],
  ])
    put(metadata, offset, value);
  const dirHeads = new Uint32Array(dirBuckets).fill(0xffffffff),
    fileHeads = new Uint32Array(fileBuckets).fill(0xffffffff);
  for (const directory of directories) {
    const p = dm + directory.offset,
      parent = directory.parent?.offset ?? 0,
      siblings = directory.parent?.dirs ?? [],
      index = siblings.indexOf(directory);
    const hash = bucket(directory.name, parent, dirBuckets);
    for (const [offset, value] of [
      [0, parent],
      [4, siblings[index + 1]?.offset ?? 0xffffffff],
      [8, directory.dirs[0]?.offset ?? 0xffffffff],
      [12, directory.files[0]?.offset ?? 0xffffffff],
      [16, dirHeads[hash]],
      [20, directory.name.length * 2],
    ])
      put(metadata, p + offset, value);
    metadata.set(nameBytes(directory.name), p + 24);
    dirHeads[hash] = directory.offset;
  }
  for (const file of files) {
    const p = fm + file.offset,
      parent = file.parent.offset,
      siblings = file.parent.files,
      index = siblings.indexOf(file),
      hash = bucket(file.name, parent, fileBuckets);
    for (const [offset, value] of [
      [0, parent],
      [4, siblings[index + 1]?.offset ?? 0xffffffff],
      [24, fileHeads[hash]],
      [28, file.name.length * 2],
    ])
      put(metadata, p + offset, value);
    metadata.set(nameBytes(file.name), p + 32);
    fileHeads[hash] = file.offset;
    file.p = p;
  }
  dirHeads.forEach((head, index) => put(metadata, dh + index * 4, head));
  fileHeads.forEach((head, index) => put(metadata, fh + index * 4, head));
  return { metadata, dataOffset, files };
}
