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
    let manifest=null,identity=null,problem='',meta=null;
    try{
      meta=await (await folder.getFileHandle('checkpoint.json')).getFile();
      if(meta.size>1024*1024)problem='Checkpoint metadata is too large';
      else{
        manifest=JSON.parse(await meta.text());identity=manifest?.config?.identity;
        if(!identity||typeof identity.name!=='string'||!identity.name||identity.name.length>512||
          !Number.isSafeInteger(identity.bytes)||identity.bytes<0){
          identity=null;problem='Checkpoint metadata is invalid';
        }
      }
    }catch(e){
      if(!isMissing(e)&&!(e instanceof SyntaxError))throw e;
      problem=isMissing(e)?'Checkpoint metadata is missing':'Checkpoint metadata is damaged';
    }
    let ranges=0,bytes=meta?.size??0;
    for await(const [name,part] of folder.entries()){
      if(name==='checkpoint.json'||part.kind!=='file')continue;
      try{
        const stat=await part.getFile();bytes+=stat.size;
        if(/^range-\d+\.json$/.test(name))ranges++;
      }catch(e){if(!isMissing(e))throw e;problem||='A saved range is missing';}
    }
    jobs.push({id,name:identity?.name??'Unknown source',sourceBytes:identity?.bytes??null,
      ranges,storedBytes:bytes,lastModified:meta?.lastModified??0,
      encoder:manifest?.config?.encoder||'Unknown',damaged:!!problem,problem});
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
