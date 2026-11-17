const STORE='mobipeg-completed-queue';

export async function batchStorage(create=false){
  const root=await navigator.storage.getDirectory();
  return root.getDirectoryHandle(STORE,{create});
}

function fileName(name){
  return name.replace(/[\/\\:*?"<>|\x00-\x1f]/g,'_').replace(/^\.+/,'').slice(0,160)||'movie';
}

export async function saveBatchFile(directory, name, blob){
  async function save(){
    const stem=fileName(name.replace(/\.moflex$/i,''));
    for(let number=1;number<=10000;number++){
      const file=stem+(number===1?'':'-'+number)+'.moflex';
      try{
        await directory.getFileHandle(file);
        continue;
      }catch(error){
        if(error.name==='TypeMismatchError')continue;
        if(error.name!=='NotFoundError')throw error;
      }
      const handle=await directory.getFileHandle(file,{create:true});
      let writable;
      try{
        writable=await handle.createWritable({mode:'exclusive'});
        await writable.write(blob);
        await writable.close();
        if((await handle.getFile()).size!==blob.size)throw Error('Saved file size changed unexpectedly.');
        return file;
      }catch(error){
        await writable?.abort().catch(()=>{});
        await directory.removeEntry(file).catch(()=>{});
        throw error;
      }
    }
    throw Error('Too many files use this name. Choose a different destination.');
  }
  return navigator.locks?.request?navigator.locks.request('mobipeg-batch-output',save):save();
}
