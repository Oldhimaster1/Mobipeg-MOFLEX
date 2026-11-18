const DIRECTORY = "mobipeg-cia-outputs";
export async function ciaOutputDirectory(create = false) {
  return (await navigator.storage.getDirectory()).getDirectoryHandle(
    DIRECTORY,
    { create },
  );
}
export async function stageCia(blob) {
  const estimate = await navigator.storage.estimate?.();
  if(Number.isFinite(estimate?.quota)&&Number.isFinite(estimate?.usage)&&
     estimate.quota-estimate.usage<blob.size)
    throw Error("Not enough browser storage for this CIA. Download it directly or free space.");
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

// A storage failure must never discard a successfully verified CIA.
export async function prepareCiaDownload(blob,save){
  if(!save)return {file:blob};
  try{return {file:await stageCia(blob)};}
  catch(error){return {file:blob,warning:'Browser copy was not saved: '+(error.message||String(error))};}
}
