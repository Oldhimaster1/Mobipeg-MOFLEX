/* Bounded decoded chunks: the source is mounted as a Blob, never copied in full. */
let compiled=null,boot=null,engineDir='engine',runtimeOptions;
async function initialize(preferred='auto'){
  if(!['auto','scalar','simd'].includes(preferred))throw Error('Unknown decoder engine');
  if(boot)return boot;
  boot=(async()=>{
    if(!self.crossOriginIsolated)throw Error('The MOFLEX decoder needs the included COOP/COEP isolation headers.');
    ({wasmRuntimeOptions:runtimeOptions}=await import('./wasm-runtime.mjs?v=20261118i'));
    const simd=WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,10,9,1,7,0,65,0,253,15,26,11]));
    if(preferred==='simd'&&!simd)throw Error('WASM SIMD is unavailable');
    engineDir=simd&&preferred!=='scalar'?'engine-simd':'engine';
    importScripts(engineDir+'/mobipeg.js');
    const response=await fetch(engineDir+'/mobipeg.wasm');
    if(!response.ok)throw Error('Cannot load the MobiClip decoder');
    compiled=await WebAssembly.compile(await response.arrayBuffer());
  })();
  return boot;
}
async function run(args,file,outputs,allowFailure=false,extra=[],extraThreads=0){
  let m,logs=[];
  try{
    m=await createMobiPEG({...runtimeOptions(undefined,extraThreads>4?256:128),noInitialRun:true,mainScriptUrlOrBlob:new URL(engineDir+'/mobipeg.js',self.location.href).href,
      print:v=>logs.push(v),printErr:v=>logs.push(v),
      instantiateWasm:(imports,done)=>{WebAssembly.instantiate(compiled,imports).then(i=>done(i,compiled));return {};}});
    // Multi-output FFmpeg commands need more scheduler threads than an
    // ordinary encode. Warm them before synchronous callMain, while this
    // worker can still receive the Emscripten thread initialization messages.
    if(extraThreads){
      const pool=m.PThread, ready=[];
      for(let index=0;index<extraThreads;index++){
        pool.allocateUnusedWorker();
        ready.push(pool.loadWasmModuleToWorker(pool.unusedWorkers.at(-1)));
      }
      await Promise.all(ready);
    }
    m.FS.mkdir('/input');m.FS.mount(m.FS.filesystems.WORKERFS,{blobs:[{name:'movie',data:file},...extra]},'/input');
    let exit=0;
    const command=['-threads','1','-filter_threads','1','-filter_complex_threads','1',...args];
    try{exit=m.callMain(command)??0;}catch(e){if(typeof e.status==='number')exit=e.status;else throw e;}
    if(exit&&!allowFailure)throw Error('MobiClip decode failed: '+logs.slice(-10).join('\n'));
    const bytes={};
    if(exit===0)for(const path of outputs){try{bytes[path]=m.FS.readFile(path);}catch{}}
    return {exit,bytes,logs};
  }finally{if(m){try{m.FS.unmount('/input');}catch{}m.PThread?.terminateAllThreads();}}
}
self.onmessage=async({data})=>{
  try{
    if(data.type==='warm'){await initialize(data.engine??'auto');postMessage({type:'ready',request:data.request});return;}
    if(data.type==='trailerAudio'){
      await initialize();
      const {file,start,samples}=data;
      if(!file||!Number.isSafeInteger(samples)||samples<256||samples>1048576||samples%256||
         !Number.isFinite(start)||start<0)throw Error('Invalid alternate audio range');
      const output='/trailer.adpcm';
      const args=['-hide_banner','-nostdin','-v','error','-ss',start.toFixed(8),'-i','/input/movie',
        '-map','0:a:0','-ac','2','-ar','48000','-af',
        `aresample=48000:async=0:first_pts=0,apad,atrim=end_sample=${samples},asetnsamples=n=256:p=1`,
        '-t',(samples/48000).toFixed(8),'-threads','1','-c:a','adpcm_ima_moflex','-f','data',output];
      const audio=(await run(args,file,[output])).bytes[output];
      if(audio?.byteLength!==samples/256*264)throw Error('Alternate audio encoded to an unexpected length');
      const buffer=audio.buffer.slice(audio.byteOffset,audio.byteOffset+audio.byteLength);
      postMessage({type:'trailerAudio',request:data.request,buffer},[buffer]);
      return;
    }
    if(data.type==='export'){
      await initialize();
      const {file,layout,mode,format,displayFPS,duration,audioChoice='primary',alternate,subtitles=[]}=data;
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
        [left,right]=(layout<2?layout===1:layout%2===0)?[first,second]:[second,first];
        vf=selected==='right'?right:selected==='left'||selected==='2d'?left:`split=2[l0][r0];[l0]${left}[l];[r0]${right}[r];[l][r]hstack=inputs=2`;
      }
      if(!Number.isFinite(duration)||duration<=0||!['primary','alternate','all','none'].includes(audioChoice)||
          subtitles.length>16)throw Error('Invalid export duration or track selection');
      if(format==='mkv'&&subtitles.length>4)throw Error('Browser MKV export supports up to four subtitle tracks. Use desktop export to keep all tracks.');
      const output='/export.'+format,args=['-hide_banner','-nostdin','-v','error','-xerror','-i','/input/movie'];
      const extras=[],maps=['-map','0:v:0'];
      if(audioChoice==='all'||audioChoice==='primary')maps.push('-map','0:a:0?');
      if(audioChoice==='all'||audioChoice==='alternate'){
        if(!alternate)throw Error('There is no alternate audio track to export');
        const {alternateWav}=await import('./super-moflex.mjs?v=20261117r');
        extras.push({name:'alternate.wav',data:await alternateWav(alternate,duration)});
        args.push('-i','/input/alternate.wav');
        maps.push('-map',extras.length+':a:0');
      }
      if(format==='mkv'){
        for(const [index,track] of subtitles.entries()){
          const snippet=await track.text.slice(0,512).text();
          const suffix=/\[Script Info\]|\[Events\]/i.test(snippet)?'ass':'srt';
          const name='subtitle-'+index+'.'+suffix;
          extras.push({name,data:track.text});
          args.push('-i','/input/'+name);
          maps.push('-map',extras.length+':s:0');
        }
      }
      if(vf)args.push('-vf',vf);
      args.push(...maps,'-threads','1','-c:v','mpeg4','-q:v','3','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-af','aresample=async=0:first_pts=0',
        '-t',duration.toFixed(9));
      if(format==='mkv'&&subtitles.length){
        args.push('-c:s','srt');
        for(const [index,track] of subtitles.entries())
          args.push('-metadata:s:s:'+index,'language='+(track.language||'und').toLowerCase());
      }
      if(format==='mp4')args.push('-movflags','+faststart');
      args.push(output);
      const result=await run(args,file,[output],false,extras,4+extras.length*3);const bytes=result.bytes[output];if(!bytes?.length)throw Error('Export produced no video');
      const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);postMessage({type:'exported',request:data.request,buffer,format},[buffer]);return;
    }
    if(data.type!=='decode')return;
    await initialize();
    const {file,start,frames,width,height,seconds,audio,alternate}=data;
    if(!file||!Number.isFinite(start)||start<0||!Number.isInteger(frames)||frames<1||frames>48||
       !Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||
       width*height*frames*4>64*1048576)throw Error('Invalid decode chunk dimensions');
    const seek=start.toFixed(7),duration=seconds.toFixed(7);
    const videoArgs=['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
      '-map','0:v:0','-frames:v',String(frames),'-pix_fmt','rgba','-threads','1','-f','rawvideo','/video.rgba'];
    const audioArgs=['-map','0:a:0','-t',duration,'-ac','2','-ar','48000','-c:a','pcm_s16le',
      '-f','s16le','/audio.raw'];
    // Decode both outputs after one seek whenever possible. Keep the separate
    // decode path as a fallback for silent or unusually muxed MOFLEX files.
    let pixels=null,sound=null,missingAudio=false;
    if(audio&&!alternate){
      const together=await run([...videoArgs,...audioArgs],file,['/video.rgba','/audio.raw'],true,[],4);
      if(!together.exit){pixels=together.bytes['/video.rgba'];sound=together.bytes['/audio.raw'];}
      else missingAudio=together.logs.some(x=>/stream map.*matches no streams|does not contain any stream/i.test(x));
    }
    if(!pixels)pixels=(await run(videoArgs,file,['/video.rgba'])).bytes['/video.rgba'];
    const frameBytes=width*height*4;
    if(!pixels?.length||pixels.length%frameBytes!==0)
      throw Error('Decoder returned an incomplete or empty frame batch');
    const videoBuffer=pixels.buffer.slice(pixels.byteOffset,pixels.byteOffset+pixels.byteLength);
    let pcmBuffer=null;
    if(audio&&!alternate&&!sound&&!missingAudio){
      const result=await run(['-hide_banner','-nostdin','-v','error','-ss',seek,'-i','/input/movie',
        ...audioArgs],file,['/audio.raw'],true);
      if(!result.exit)sound=result.bytes['/audio.raw'];
    }
    if(sound?.length)pcmBuffer=sound.buffer.slice(sound.byteOffset,sound.byteOffset+sound.byteLength);
    if(alternate){
      const {readAlternateAudio}=await import('./super-moflex.mjs?v=20261117r');
      pcmBuffer=await readAlternateAudio(alternate,start,videoBuffer.byteLength/frameBytes*seconds/frames);
    }
    const transfer=[videoBuffer];if(pcmBuffer)transfer.push(pcmBuffer);
    postMessage({type:'decoded',request:data.request,startFrame:data.startFrame,video:videoBuffer,pcm:pcmBuffer,
      frames:videoBuffer.byteLength/frameBytes,requestedFrames:frames,audioRate:alternate?.rate??48000,width,height},transfer);
  }catch(e){postMessage({type:'error',request:data.request,message:e?.message||String(e)});}
};
