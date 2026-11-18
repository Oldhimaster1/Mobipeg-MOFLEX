const DIRECTORY = "mobipeg-cia-outputs";
export async function ciaOutputDirectory(create = false) {
  return (await navigator.storage.getDirectory()).getDirectoryHandle(
    DIRECTORY,
    { create },
  );
}
export async function stageCia(blob) {
  const directory = await ciaOutputDirectory(true);
  const name = "movie-" + crypto.randomUUID() + ".cia";
  const handle = await directory.getFileHandle(name, { create: true });
  let writable;
  try {
    writable = await handle.createWritable();
    await blob.stream().pipeTo(writable);
    const file = await handle.getFile();
    if (file.size !== blob.size) throw Error("Saved CIA size changed");
    return file;
  } catch (error) {
    await writable?.abort().catch(() => {});
    await directory.removeEntry(name).catch(() => {});
    throw error;
  }
}
