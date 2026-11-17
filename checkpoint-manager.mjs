// List and delete abandoned OPFS checkpoints without reading video payload bytes.
const ROOT='mobipeg-long-movies',MAX_JOBS=200;
const isMissing=e=>e?.name==='NotFoundError';
export function validJobId(id){return typeof id==='string'&&/^resume-[a-f0-9]{64}$/.test(id);}
async function jobsDirectory(storage){
  try{return await (await storage.getDirectory()).getDirectoryHandle(ROOT);}
  catch(e){if(isMissing(e))return null;throw e;}
}
export async function listSavedMovieJobs(storage=globalThis.navigator?.storage){
  if(!storage?.getDirectory)throw Error('Private browser storage is unavailable.');
  const root=await jobsDirectory(storage);if(!root)return [];
  const jobs=[];
  for await(const [id,folder] of root.entries()){
    if(!validJobId(id)||folder.kind!=='directory')continue;
    if(jobs.length>=MAX_JOBS)break;
    try{
      const file=await (await folder.getFileHandle('checkpoint.json')).getFile();
      if(file.size>1024*1024)continue;
      const manifest=JSON.parse(await file.text()),identity=manifest?.config?.identity;
      if(!identity||typeof identity.name!=='string'||!identity.name||identity.name.length>512||
        !Number.isSafeInteger(identity.bytes)||identity.bytes<0)continue;
      let ranges=0,bytes=file.size;
      for await(const [name,part] of folder.entries()){
        if(name==='checkpoint.json'||part.kind!=='file')continue;
        const stat=await part.getFile();bytes+=stat.size;
        if(/^range-\d+\.json$/.test(name))ranges++;
      }
      jobs.push({id,name:identity.name,sourceBytes:identity.bytes,ranges,storedBytes:bytes,
        lastModified:file.lastModified,encoder:manifest.config.encoder||'Unknown'});
    }catch(e){if(!isMissing(e)&&!(e instanceof SyntaxError))throw e;}
  }
  return jobs.sort((a,b)=>b.lastModified-a.lastModified);
}
export async function removeSavedMovieJob(id,storage=globalThis.navigator?.storage,locks=globalThis.navigator?.locks){
  if(!validJobId(id))throw Error('Invalid saved movie identifier.');
  if(!storage?.getDirectory||!locks?.request)throw Error('Safe deletion requires browser storage and Web Locks.');
  const root=await jobsDirectory(storage);if(!root)return false;
  return locks.request(id,{ifAvailable:true},async lock=>{
    if(!lock)throw Error('This movie is open in another tab. Close the conversion before deleting it.');
    try{await root.removeEntry(id,{recursive:true});return true;}
    catch(e){if(isMissing(e))return false;throw e;}
  });
}
