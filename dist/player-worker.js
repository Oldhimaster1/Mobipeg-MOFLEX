/* Bounded decoded chunks: the source is mounted as a Blob, never copied in full. */
let compiled=null,boot=null;
async function initialize(){
  if(boot)return boot;
  boot=(async()=>{
    if(!self.crossOriginIsolated)throw Error('The MOFLEX decoder needs the included COOP/COEP isolation headers.');
    importScripts('engine/mobipeg.js');
    const response=await fetch('engine/mobipeg.wasm');
    if(!response.ok)throw Error('Cannot load the MobiClip decoder');
    compiled=await WebAssembly.compile(await response.arrayBuffer());
  })();
  return boot;
}
async function run(args,file,output,allowFailure=false){
  let m,logs=[];
  try{
    m=await createMobiPEG({noInitialRun:true,mainScriptUrlOrBlob:new URL('engine/mobipeg.js',self.location.href).href,
      print:v=>logs.push(v),printErr:v=>logs.push(v),
      instantiateWasm:(imports,done)=>{WebAssembly.instantiate(compiled,imports).then(i=>done(i,compiled));return {};}});
    m.FS.mkdir('/input');m.FS.mount(m.FS.filesystems.WORKERFS,{blobs:[{name:'movie',data:file}]},'/input');
    let exit=0;
    try{exit=m.callMain(args)??0;}catch(e){if(typeof e.status==='number')exit=e.status;else throw e;}
    if(exit&&!allowFailure)throw Error('MobiClip decode failed: '+logs.slice(-10).join('\n'));
    let bytes=null;
    if(exit===0&&output)bytes=m.FS.readFile(output);
    return {exit,bytes,logs};
  }finally{if(m){try{m.FS.unmount('/input');}catch{}m.PThread?.terminateAllThreads();}}
}
self.onmessage=async({data})=>{
  try{
    if(data.type!=='decode')return;
    await initialize();
    const {file,start,frames,width,height,seconds,audio}=data;
    if(!file||!Number.isFinite(start)||start<0||!Number.isInteger(frames)||frames<1||frames>48||
       !Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||
       width*height*frames*4>64*1048576)throw Error('Invalid decode chunk dimensions');
    const seek=start.toFixed(7),duration=seconds.toFixed(7);
    const video=await run(['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
      '-map','0:v:0','-frames:v',String(frames),'-pix_fmt','rgba',
      '-f','rawvideo','/video.rgba'],file,'/video.rgba');
    const frameBytes=width*height*4;
    if(!video.bytes?.length||video.bytes.length%frameBytes!==0)throw Error('Decoder returned an incomplete or empty frame batch');
    const videoBuffer=video.bytes.buffer.slice(video.bytes.byteOffset,video.bytes.byteOffset+video.bytes.byteLength);
    let pcmBuffer=null;
    if(audio){
      const result=await run(['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
        '-t',duration,'-map','0:a:0','-ac','2','-ar','48000','-c:a','pcm_s16le',
        '-f','s16le','/audio.raw'],file,'/audio.raw',true);
      if(!result.exit&&result.bytes?.length)pcmBuffer=result.bytes.buffer.slice(result.bytes.byteOffset,result.bytes.byteOffset+result.bytes.byteLength);
    }
    const transfer=[videoBuffer];if(pcmBuffer)transfer.push(pcmBuffer);
    postMessage({type:'decoded',request:data.request,startFrame:data.startFrame,video:videoBuffer,pcm:pcmBuffer,
      frames:videoBuffer.byteLength/frameBytes,width,height},transfer);
  }catch(e){postMessage({type:'error',request:data.request,message:e?.message||String(e)});}
};
