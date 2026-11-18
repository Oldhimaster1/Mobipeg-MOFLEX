// One isolated fixed 2 MiB heap per hash; safe for concurrent CIA jobs.
export async function sha256BlobWasm(blob,module){
  const {exports:core}=await WebAssembly.instantiate(module);
  core.initialize();
  const memory=new Uint8Array(core.memory.buffer),pointer=core.data_address();
  let tail=new Uint8Array();
  for(let offset=0;offset<blob.size;offset+=1048576){
    const bytes=new Uint8Array(await blob.slice(offset,offset+1048576).arrayBuffer());
    const end=bytes.length-bytes.length%64;
    memory.set(bytes.subarray(0,end),pointer);core.compress(end/64);
    tail=bytes.slice(end);
  }
  const padding=new Uint8Array(tail.length<56?64:128);padding.set(tail);padding[tail.length]=128;
  new DataView(padding.buffer).setBigUint64(padding.length-8,BigInt(blob.size)*8n,false);
  memory.set(padding,pointer);core.compress(padding.length/64);
  const result=new Uint8Array(32),output=new DataView(result.buffer),state=new DataView(core.memory.buffer,core.state_address(),32);
  for(let i=0;i<8;i++)output.setUint32(i*4,state.getUint32(i*4,true),false);
  return result;
}
