import {classifyStereoPixels,displayedCodedFrame,inspectPlayableMoflex} from './player-core.mjs';

const $=id=>document.getElementById(id);
const canvas=$('screen'),context=canvas.getContext('2d',{alpha:false});
const time=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
let file=null,metadata=null,decoder=null,serial=0,inFlight=false,nextFrame=0,buffer=[];
let playing=false,currentTime=0,clockStart=0,audioContext=null,audioBase=0,audioSources=[];
let lastFrame=-1,failed=false;
let stereoKind=null;
let exportURL=null;
const BATCH_FRAMES=48;
const status=s=>$('playerStatus').textContent=s;

function stopAudio(){
  for(const source of audioSources){try{source.stop();}catch{}}
  audioSources=[];
  for(const batch of buffer)batch.audioScheduled=false;
}
function pause(){
  if(playing){currentTime=Math.min(metadata?.duration??0,Math.max(0,(performance.now()-clockStart)/1000));}
  playing=false;stopAudio();$('play').disabled=!metadata;$('pause').disabled=true;
}
function resetDecoder(){
  serial++;decoder?.terminate();decoder=null;inFlight=false;buffer=[];lastFrame=-1;failed=false;
  if(!metadata)return;
  const incarnation=serial;
  decoder=new Worker('player-worker.js?v=20261117i');
  decoder.onerror=error=>{if(incarnation!==serial)return;inFlight=false;failed=true;pause();status('Decoder failed: '+(error.message||'unknown error'));};
  decoder.onmessage=({data:d})=>{
    if(incarnation!==serial||d.request!==incarnation)return;
    if(d.type==='ready')return;
    if(d.type==='exported'){
      if(exportURL)URL.revokeObjectURL(exportURL);exportURL=URL.createObjectURL(new Blob([d.buffer],{type:d.format==='mp4'?'video/mp4':'video/x-matroska'}));
      const a=document.createElement('a');a.href=exportURL;a.download=file.name.replace(/\.moflex$/i,'')+'.'+d.format;a.click();
      $('exportVideo').disabled=false;status('Converted video downloaded.');return;
    }
    inFlight=false;
    if(d.type==='error'){
      failed=true;pause();status('Cannot decode this MOFLEX: '+d.message);return;
    }
    if(d.type==='decoded'){
      if(d.frames<1||d.video.byteLength!==d.frames*metadata.width*metadata.height*4){
        failed=true;pause();status('Decoder produced invalid frames');return;
      }
      buffer.push({start:d.startFrame,count:d.frames,video:d.video,pcm:d.pcm,audioScheduled:false});
      if(!stereoKind&&metadata.eyes===2){stereoKind=classifyStereoPixels(d.video,metadata,d.frames);$('stereoInfo').textContent=stereoKind.kind==='duplicated-eyes'?'Stereo descriptor, but sampled eyes appear duplicated (heuristic).':'Sampled eyes differ: likely genuine stereoscopic video (heuristic).';}
      nextFrame=d.startFrame+d.frames;
      if(d.frames<BATCH_FRAMES&&nextFrame<metadata.frames){
        // Some valid movie endings are shorter than input metadata. Stop at
        // the last actual decoded frame rather than requesting it forever.
        metadata.frames=nextFrame;metadata.duration=nextFrame/metadata.codedFPS;
        $('duration').textContent=time(metadata.duration);$('seek').max=String(metadata.duration);
      }
      scheduleAudio();
      drawAt(currentTime);
      requestMore();
    }
  };
  decoder.postMessage({type:'warm',request:incarnation});
}
function startPosition(seconds){
  currentTime=Math.max(0,Math.min(seconds,Math.max(0,(metadata?.duration??0)-.001)));
  nextFrame=Math.floor(currentTime*metadata.displayFPS)*metadata.eyes;
  clockStart=performance.now()-currentTime*1000;
  stopAudio();resetDecoder();
  audioBase=(audioContext?.currentTime||0)-currentTime+.08;
  $('position').textContent=time(currentTime);$('seek').value=String(currentTime);
  status('Loading decoded frames…');requestMore();
}
function audibleBatch(batch){
  if(!audioContext||!playing||!batch.pcm||batch.audioScheduled)return;
  const pcm=new Int16Array(batch.pcm),samples=Math.floor(pcm.length/2);
  if(!samples)return;
  const sound=audioContext.createBuffer(2,samples,48000);
  const left=sound.getChannelData(0),right=sound.getChannelData(1);
  for(let i=0;i<samples;i++){left[i]=pcm[i*2]/32768;right[i]=pcm[i*2+1]/32768;}
  const source=audioContext.createBufferSource();source.buffer=sound;source.connect(audioContext.destination);
  const wanted=audioBase+batch.start/metadata.codedFPS;
  const offset=Math.max(0,audioContext.currentTime-wanted);
  if(offset<sound.duration){
    source.start(Math.max(audioContext.currentTime+.005,wanted),offset);
    audioSources.push(source);
    source.onended=()=>{audioSources=audioSources.filter(item=>item!==source);};
  }
  batch.audioScheduled=true;
}
function scheduleAudio(){for(const batch of buffer)audibleBatch(batch);}
function requestMore(){
  if(!metadata||!decoder||inFlight||failed||nextFrame>=metadata.frames)return;
  const displayed=Math.floor(currentTime*metadata.displayFPS)*metadata.eyes;
  if(nextFrame-displayed>=metadata.codedFPS*2.4)return;
  const safeFrames=Math.max(1,Math.floor(24*1048576/(metadata.width*metadata.height*4)));
  const frames=Math.min(BATCH_FRAMES,safeFrames,metadata.frames-nextFrame);
  if(frames<1)return;
  inFlight=true;
  decoder.postMessage({type:'decode',request:serial,file,startFrame:nextFrame,
    start:nextFrame/metadata.codedFPS,seconds:frames/metadata.codedFPS,
    frames,width:metadata.width,height:metadata.height,audio:true});
}
function drawAt(seconds){
  if(!metadata)return false;
  const displayFrame=Math.min(Math.floor(seconds*metadata.displayFPS),Math.floor((metadata.frames-1)/metadata.eyes));
  const eye=Number($('eye').value)||0;
  const index=displayedCodedFrame(displayFrame,metadata.eyes,eye,metadata.packing,metadata.leftFirst);
  const batch=buffer.find(item=>index>=item.start&&index<item.start+item.count);
  if(!batch)return false;
  if(lastFrame!==index){
    const pixels=metadata.width*metadata.height*4;
    const frame=new Uint8ClampedArray(batch.video,(index-batch.start)*pixels,pixels);
    const image=new ImageData(frame,metadata.width,metadata.height);
    const storedEye=metadata.leftFirst?eye:1-eye;
    if(metadata.packing==='side-by-side')context.putImageData(image,-storedEye*metadata.eyeWidth,0,storedEye*metadata.eyeWidth,0,metadata.eyeWidth,metadata.eyeHeight);
    else if(metadata.packing==='top-bottom')context.putImageData(image,0,-storedEye*metadata.eyeHeight,0,storedEye*metadata.eyeHeight,metadata.eyeWidth,metadata.eyeHeight);
    else context.putImageData(image,0,0);
    lastFrame=index;
  }
  buffer=buffer.filter(item=>item.start+item.count>index-metadata.codedFPS);
  return true;
}
function animate(){
  if(playing&&metadata){
    const target=(performance.now()-clockStart)/1000;
    if(target>=metadata.duration){pause();currentTime=metadata.duration;status('Playback complete.');}
    else if(drawAt(target)){
      currentTime=target;
      status('Playing locally · '+(metadata.eyes===2?'stereoscopic eye view':'2D'));
      scheduleAudio();
    }else{
      // Freeze the playback clock during decoder stalls. A green bar in the
      // encoder does not imply playback can decode faster than real time.
      clockStart=performance.now()-currentTime*1000;
      status('Buffering decoded frames…');
    }
    $('position').textContent=time(currentTime);$('seek').value=String(currentTime);
  }
  if(metadata&&!failed)requestMore();
  requestAnimationFrame(animate);
}
$('movieFile').onchange=async event=>{
  const selected=event.target.files?.[0];pause();metadata=null;file=null;stereoKind=null;$('stereoInfo').textContent='';resetDecoder();
  $('play').disabled=true;$('seek').disabled=true;$('eyeControl').hidden=true;$('playerInfo').textContent='';
  $('exportVideo').disabled=true;
  if(!selected)return;
  status('Checking the MOFLEX seek index and video descriptor…');
  try{
    const info=await inspectPlayableMoflex(selected);
    file=selected;metadata=info;currentTime=0;canvas.width=info.eyeWidth;canvas.height=info.eyeHeight;
    $('duration').textContent=time(info.duration);$('seek').max=String(info.duration);$('seek').value='0';
    $('seek').disabled=false;$('play').disabled=false;$('eyeControl').hidden=info.eyes===1;
    $('exportVideo').disabled=false;
    $('playerInfo').textContent=`${selected.name} · ${info.width}×${info.height} · ${info.displayFPS.toFixed(3)} fps · ${info.eyes===2?'Stereo layout '+info.layout+' ('+info.packing+')':'2D layout 6'} · ${(selected.size/1e6).toFixed(2)} MB`;
    startPosition(0);
  }catch(error){status('This file could not be opened: '+(error.message||String(error)));}
};
$('play').onclick=async()=>{
  if(!metadata)return;
  if(currentTime>=metadata.duration-.02)startPosition(0);
  try{
    audioContext??=new (window.AudioContext||window.webkitAudioContext)();
    await audioContext.resume();
  }catch{status('Audio unavailable; attempting video playback.');}
  playing=true;clockStart=performance.now()-currentTime*1000;
  audioBase=(audioContext?.currentTime||0)-currentTime+.08;
  scheduleAudio();$('play').disabled=true;$('pause').disabled=false;
};
$('pause').onclick=()=>{pause();status('Paused');};
$('eye').onchange=()=>{lastFrame=-1;drawAt(currentTime);};
$('seek').oninput=()=>{
  if(!metadata)return;
  const resume=playing;pause();startPosition(Number($('seek').value));
  if(resume){playing=true;clockStart=performance.now()-currentTime*1000;$('play').disabled=true;$('pause').disabled=false;}
};
$('exportVideo').onclick=()=>{
  if(!file||!metadata)return;pause();resetDecoder();$('exportVideo').disabled=true;status('Converting locally to standard video…');
  decoder.postMessage({type:'export',request:serial,file,layout:metadata.layout,displayFPS:metadata.displayFPS,mode:$('exportMode').value,format:$('exportFormat').value});
};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&playing){pause();status('Paused while tab is hidden.');}});
requestAnimationFrame(animate);
