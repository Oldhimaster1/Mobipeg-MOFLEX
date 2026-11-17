/* Bounded decoded chunks: the source is mounted as a Blob, never copied in full. */
let compiled=null,boot=null,engineDir='engine';
async function initialize(){
  if(boot)return boot;
  boot=(async()=>{
    if(!self.crossOriginIsolated)throw Error('The MOFLEX decoder needs the included COOP/COEP isolation headers.');
    const simd=WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,10,9,1,7,0,65,0,253,15,26,11]));
    engineDir=simd?'engine-simd':'engine';
    importScripts(engineDir+'/mobipeg.js');
    const response=await fetch(engineDir+'/mobipeg.wasm');
    if(!response.ok)throw Error('Cannot load the MobiClip decoder');
    compiled=await WebAssembly.compile(await response.arrayBuffer());
  })();
  return boot;
}
async function run(args,file,outputs,allowFailure=false){
  let m,logs=[];
  try{
    m=await createMobiPEG({noInitialRun:true,mainScriptUrlOrBlob:new URL(engineDir+'/mobipeg.js',self.location.href).href,
      print:v=>logs.push(v),printErr:v=>logs.push(v),
      instantiateWasm:(imports,done)=>{WebAssembly.instantiate(compiled,imports).then(i=>done(i,compiled));return {};}});
    m.FS.mkdir('/input');m.FS.mount(m.FS.filesystems.WORKERFS,{blobs:[{name:'movie',data:file}]},'/input');
    let exit=0;
    try{exit=m.callMain(args)??0;}catch(e){if(typeof e.status==='number')exit=e.status;else throw e;}
    if(exit&&!allowFailure)throw Error('MobiClip decode failed: '+logs.slice(-10).join('\n'));
    const bytes={};
    if(exit===0)for(const path of outputs){try{bytes[path]=m.FS.readFile(path);}catch{}}
    return {exit,bytes,logs};
  }finally{if(m){try{m.FS.unmount('/input');}catch{}m.PThread?.terminateAllThreads();}}
}
self.onmessage=async({data})=>{
  try{
    if(data.type==='warm'){await initialize();postMessage({type:'ready',request:data.request});return;}
    if(data.type==='export'){
      await initialize();
      const {file,layout,mode,format,displayFPS}=data;
      if(!file||file.size>768*1048576||!Number.isInteger(layout)||layout<0||layout>6||!['auto','2d','sbs','left','right'].includes(mode)||!['mp4','mkv'].includes(format))throw Error('Invalid or too-large browser export request');
      const stereo=layout!==6,selected=mode==='auto'?(stereo?'sbs':'2d'):mode;
      if(!stereo&&['sbs','right'].includes(selected))throw Error('The MOFLEX descriptor is 2D');
      let vf=null;
      if(stereo){
        let left,right;
        let first,second;
        if(layout<2){if(!(displayFPS>0))throw Error('Invalid stereo frame rate');first=`select='not(mod(n,2))',setpts=N/(${displayFPS}*TB)`;second=`select='mod(n,2)',setpts=N/(${displayFPS}*TB)`;}
        else if(layout<4){first='crop=iw:ih/2:0:0';second='crop=iw:ih/2:0:ih/2';}
        else {first='crop=iw/2:ih:0:0';second='crop=iw/2:ih:iw/2:0';}
        [left,right]=layout%2===0?[first,second]:[second,first];
        vf=selected==='right'?right:selected==='left'||selected==='2d'?left:`split=2[l0][r0];[l0]${left}[l];[r0]${right}[r];[l][r]hstack=inputs=2`;
      }
      const output='/export.'+format,args=['-hide_banner','-nostdin','-v','error','-i','/input/movie'];
      if(vf)args.push('-vf',vf);
      args.push('-map','0:v:0','-map','0:a:0?','-c:v','mpeg4','-q:v','3','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-af','aresample=async=0:first_pts=0','-shortest',...(format==='mp4'?['-movflags','+faststart']:[]),output);
      const result=await run(args,file,[output]);const bytes=result.bytes[output];if(!bytes?.length)throw Error('Export produced no video');
      const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);postMessage({type:'exported',request:data.request,buffer,format},[buffer]);return;
    }
    if(data.type!=='decode')return;
    await initialize();
    const {file,start,frames,width,height,seconds,audio}=data;
    if(!file||!Number.isFinite(start)||start<0||!Number.isInteger(frames)||frames<1||frames>48||
       !Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||
       width*height*frames*4>64*1048576)throw Error('Invalid decode chunk dimensions');
    const seek=start.toFixed(7),duration=seconds.toFixed(7);
    const videoArgs=['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
      '-map','0:v:0','-frames:v',String(frames),'-pix_fmt','rgba','-f','rawvideo','/video.rgba'];
    const audioArgs=['-map','0:a:0','-t',duration,'-ac','2','-ar','48000','-c:a','pcm_s16le',
      '-f','s16le','/audio.raw'];
    // Decode both outputs after one seek whenever possible. Keep the separate
    // decode path as a fallback for silent or unusually muxed MOFLEX files.
    let pixels=null,sound=null,missingAudio=false;
    if(audio){
      const together=await run([...videoArgs,...audioArgs],file,['/video.rgba','/audio.raw'],true);
      if(!together.exit){pixels=together.bytes['/video.rgba'];sound=together.bytes['/audio.raw'];}
      else missingAudio=together.logs.some(x=>/stream map.*matches no streams|does not contain any stream/i.test(x));
    }
    if(!pixels)pixels=(await run(videoArgs,file,['/video.rgba'])).bytes['/video.rgba'];
    const frameBytes=width*height*4;
    if(!pixels?.length||pixels.length%frameBytes!==0)
      throw Error('Decoder returned an incomplete or empty frame batch');
    const videoBuffer=pixels.buffer.slice(pixels.byteOffset,pixels.byteOffset+pixels.byteLength);
    let pcmBuffer=null;
    if(audio&&!sound&&!missingAudio){
      const result=await run(['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
        ...audioArgs],file,['/audio.raw'],true);
      if(!result.exit)sound=result.bytes['/audio.raw'];
    }
    if(sound?.length)pcmBuffer=sound.buffer.slice(sound.byteOffset,sound.byteOffset+sound.byteLength);
    const transfer=[videoBuffer];if(pcmBuffer)transfer.push(pcmBuffer);
    postMessage({type:'decoded',request:data.request,startFrame:data.startFrame,video:videoBuffer,pcm:pcmBuffer,
      frames:videoBuffer.byteLength/frameBytes,width,height},transfer);
  }catch(e){postMessage({type:'error',request:data.request,message:e?.message||String(e)});}
};
