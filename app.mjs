import{validate,rate,PRESETS}from'./core.mjs?v=20261116d';
import{createMovieJob,appendMovieSegment,assembleMovie,cleanupMovieJob,getCodedRate,nextMovieClip}from'./movie.mjs?v=20261116d';
const $=id=>document.getElementById(id),form=$('settings');let file=null,worker=null,previewURL=null,outputURL=null,started=0,stageStarted=0,ticker=null,report=null,wake=null,busy=false,runToken=0,stallMonitor=null,movieJob=null,completedMovieJob=null;
const time=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
function log(s){$('logs').textContent=($('logs').textContent+'\n'+s).slice(-16000);}
function settings(){const d=new FormData(form);return validate({mode:d.get('mode'),engine:d.get('engine')||'auto',preset:d.get('preset'),resolution:d.get('resolution'),fps:d.get('fps'),filter:d.get('filter'),motion:d.get('motion'),q:d.get('q')===''?null:Number(d.get('q')),audioTrack:Number(d.get('audioTrack')||0),maxMB:d.get('maxMB')===''?null:Number(d.get('maxMB'))});}
function select(f){if(busy||!f)return;file=f;if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(f);$('preview').src=previewURL;$('empty').hidden=true;$('selected').hidden=false;$('drop').classList.add('has-video');$('replace').hidden=false;$('filename').textContent=f.name;$('audioTrack').replaceChildren(new Option('0 — First audio track','0'));$('filesize').textContent=(f.size/1e6).toFixed(2)+' MB';$('filemeta').textContent='Preview unavailable? The encoder can still inspect this file.';$('convert').disabled=false;}
$('preview').onloadedmetadata=()=>{if(navigator.storage?.getDirectory&&$('preview').duration>180)$('longMovie').checked=true;$('filemeta').textContent=`${$('preview').videoWidth} × ${$('preview').videoHeight} · ${time($('preview').duration)}`;};$('file').onchange=e=>select(e.target.files[0]);$('replace').onclick=()=>$('file').click();for(const type of ['dragenter','dragover'])$('drop').addEventListener(type,e=>{e.preventDefault();if(!busy)$('drop').classList.add('over');});for(const type of ['dragleave','drop'])$('drop').addEventListener(type,e=>{e.preventDefault();$('drop').classList.remove('over');if(type==='drop')select(e.dataTransfer.files[0]);});
form.onchange=()=>{const stereo=new FormData(form).get('mode')!=='2d';$('modehint').textContent=stereo?`True 3D · layout 0 · ${ (rate($('fps').value)*2).toFixed(3).replace(/\.000$/,'')} coded eye frames/sec`:'Standard 2D · MOFLEX layout 6';};$('reset').onclick=()=>{if(!busy){form.reset();form.dispatchEvent(new Event('change'));}};
function lock(v){busy=v;for(const el of form.elements)el.disabled=v;$('convert').disabled=v||!file;$('reset').disabled=v;$('replace').disabled=v;$('file').disabled=v;}
function finish(){runToken++;worker?.terminate();worker=null;clearInterval(ticker);clearInterval(stallMonitor);stallMonitor=null;lock(false);$('cancel').hidden=true;wake?.release().catch(()=>{});wake=null;if(movieJob){const saved=movieJob;movieJob=null;const keep=!!outputURL;if(keep){completedMovieJob=saved;$('clearMovieData').hidden=false;}cleanupMovieJob(saved,keep).catch(e=>log('Local cleanup warning: '+e.message));}}
function fail(message){$('stage').textContent='Conversion stopped';$('error').hidden=false;$('error').textContent=message;log(message);$('progress').value=0;finish();}
$('cancel').onclick=()=>{fail('Cancelled. Your original file is untouched.');};
$('clearMovieData').onclick=async()=>{
  if(busy||!completedMovieJob)return;
  if(!confirm('Delete the temporary on-device movie copy? Download the .moflex first; this cannot be undone.'))return;
  const saved=completedMovieJob;completedMovieJob=null;
  try{await cleanupMovieJob(saved,false);$('clearMovieData').hidden=true;log('Temporary movie storage removed.');}
  catch(e){log('Could not clear local storage: '+e.message);}
};
form.onsubmit=async e=>{e.preventDefault();if(!file||busy)return;let s;try{s=settings();}catch(e){alert(e.message);return;}const movieMode=$('longMovie').checked;s.movieAudio=movieMode;if(movieMode&&s.maxMB!==null){alert('Movie mode currently requires No limit for maximum size. The short chapters are combined into one final MOFLEX.');return;}if(movieMode&&!navigator.storage?.getDirectory){alert('Long-movie mode requires on-device private file storage (OPFS), which is unavailable in this browser.');return;}if(file.size>512*1024*1024&&!confirm('This is a large input. Browser memory may be insufficient, especially on mobile. Continue?'))return;lock(true);const token=++runToken;if(outputURL){URL.revokeObjectURL(outputURL);outputURL=null;}if(completedMovieJob){const old=completedMovieJob;completedMovieJob=null;$('clearMovieData').hidden=true;cleanupMovieJob(old,false).catch(e=>log('Old movie cleanup warning: '+e.message));}$('job').hidden=false;$('result').hidden=true;$('error').hidden=true;$('cancel').hidden=false;$('stage').textContent='Loading native WASM encoder…';$('joblabel').textContent='CONVERSION';$('logs').textContent='MobiPEG V15 · fixed layout-0 source\nNo media upload. WebAssembly · FFmpeg scheduler threads, single codec thread.';$('memory').textContent='';$('eta').textContent='Estimating time…';$('progress').removeAttribute('value');started=stageStarted=performance.now();ticker=setInterval(()=>$('elapsed').textContent=time((performance.now()-started)/1000)+' elapsed',1000);$('job').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});try{const requestedWake=await navigator.wakeLock?.request('screen');if(token!==runToken){requestedWake?.release().catch(()=>{});return;}wake=requestedWake;}catch{}if(token!==runToken)return;
let candidate=null;
let movieDuration=0,movieAudio=false,movieFrames=0,movieParts=0;
const movieFPS=getCodedRate(s);
const beginMoviePart=async()=>{
  if(token!==runToken)return;
  const clip=nextMovieClip(movieFrames,movieDuration,movieFPS,30);
  if(clip){
    if(movieParts>Math.ceil(movieDuration/20)+4)throw Error('Movie timeline did not advance; conversion stopped to avoid repeated chapters.');
    movieParts++;
    $('joblabel').textContent='LONG MOVIE · CHAPTER '+movieParts;
    log('Encoding chapter '+movieParts+' starting '+time(clip.start)+', length '+time(clip.seconds)+'.');
    switchWorker('segment',{type:'segment',file,settings:s,clip});
    return;
  }
  expectMovieParts();
  $('joblabel').textContent='LONG MOVIE · ASSEMBLING';
  $('stage').textContent='Building complete movie and seek index';
  $('eta').textContent='Writing one MOFLEX to local storage…';
  $('progress').value=0;
  const merged=await assembleMovie(movieJob,s,v=>{
    if(token!==runToken)return;
    $('stage').textContent='Assembling movie · chapter '+v.chapter+'/'+v.chapters;
    $('progress').value=v.total?v.written/v.total:0;
  },()=>token!==runToken);
  if(token!==runToken)return;
  candidate={blob:merged.file,frames:merged.frames,seconds:merged.seconds,audio:movieAudio,q:s.q??PRESETS[s.preset].q,attempts:movieParts,chapters:movieParts,durationFieldSaturated:merged.durationFieldSaturated};
  log('One indexed MOFLEX assembled: '+(merged.file.size/1e6).toFixed(2)+' MB, '+merged.frames+' frames.');
  if(merged.durationFieldSaturated)log('Warning: movie exceeds the legacy 32-bit duration field (71m35s); timestamps and frame index use wider fields. Physical 3DS playback and seeking must be tested.');
  switchWorker('verify',{type:'verify',kind:'video',blob:merged.file,frames:merged.frames,seconds:merged.seconds,settings:s});
};
const expectMovieParts=()=>{if(!movieParts||!movieFrames)throw Error('No movie chapters were encoded.');};
const continueMovie=()=>beginMoviePart().catch(e=>{if(token===runToken)fail(e.message||String(e));});
let currentWorkerType='convert',lastActivity=performance.now(),idleWarningShown=false;
stallMonitor=setInterval(()=>{
  if(token!==runToken||!worker)return;
  const idle=performance.now()-lastActivity;
  if(currentWorkerType==='verify'&&candidate&&idle>90000){
    publishCandidate(false,'Verification worker stopped responding for over 90 seconds.');
  }else if((currentWorkerType==='convert'||currentWorkerType==='segment')&&idle>120000&&!idleWarningShown){
    idleWarningShown=true;
    $('eta').textContent='No encoder updates for 2 minutes. It may be stalled.';
    log('Warning: encoder worker has been silent for 2 minutes; you may cancel if necessary.');
  }
},5000);
const oom=message=>/out of memory|memory access out of bounds|allocation failed|cannot allocate|failed to grow memory/i.test(String(message));
const publishCandidate=(verified,reason='')=>{
  if(!candidate)return fail('The encoded MOFLEX is no longer available.');
  const d=candidate;
  report={encoder:'MobiPEG V15 layout-0 WASM',input:{name:file.name,bytes:file.size},settings:s,output:{bytes:d.blob.size,q:d.q,codedFrames:d.frames,seconds:d.seconds,audio:d.audio,attempts:d.attempts,chapters:d.chapters??1,durationFieldSaturated:!!d.durationFieldSaturated},verified,verificationFailure:verified?null:reason,elapsedSeconds:(performance.now()-started)/1000,userAgent:navigator.userAgent};
  outputURL=URL.createObjectURL(d.blob);
  $('download').href=outputURL;
  $('download').download=file.name.replace(/\.[^.]+$/,'')+'_MobiPEG_V15_'+s.mode+(verified?'':'_UNVERIFIED')+'.moflex';
  $('download').textContent=verified?'Download verified .moflex':'Download unverified .moflex';
  $('stage').textContent=verified?'Your MOFLEX is ready.':'MOFLEX encoded; verification incomplete';
  $('joblabel').textContent=verified?'COMPLETE · DECODE VERIFIED':'ENCODE COMPLETE · NOT FULLY VERIFIED';
  $('progress').value=1;
  $('eta').textContent=verified?'All checks passed':'Verification not completed';
  $('error').hidden=verified;
  if(!verified)$('error').textContent=oom(reason)?'The output was encoded, but verification ran out of browser memory. This file has NOT passed full decoding checks.':'The output was encoded, but the verifier stopped responding. This file has NOT passed full decoding checks. Inspect it before trusting or sharing it.';
  $('result').hidden=false;
  $('resultmeta').textContent=`${(d.blob.size/1e6).toFixed(2)} MB · ${d.frames.toLocaleString()} coded frames · Q${d.q} · ${d.audio?'ADPCM audio':'No audio'} · ${time(d.seconds)}${d.durationFieldSaturated?' · 3DS >71 min seek behavior unverified':''}${verified?'':' · UNVERIFIED'}`;
  log(verified?'Complete video'+(d.audio?' + audio':'')+' decode passed. Physical 3DS playback is not certified by this check.':'Verification incomplete: '+reason+'; candidate offered as UNVERIFIED.');
  candidate=null;
  finish();
};
const startWorker=(type,payload)=>{
  if(token!==runToken)return;
  currentWorkerType=type;lastActivity=performance.now();idleWarningShown=false;const w=new Worker('worker.js?v=20261116d');worker=w;
  w.onerror=e=>{
    if(token!==runToken||worker!==w)return;
    const message=`Encoder worker failed: ${e.message||'unknown error'}`;
    if(candidate&&type==='verify'&&oom(message))publishCandidate(false,message);else fail(message);
  };
  w.onmessage=async({data:d})=>{
    if(token!==runToken||worker!==w)return;
    lastActivity=performance.now();
    if(d.type==='status'){
      $('stage').textContent=d.stage;stageStarted=performance.now();$('eta').textContent='Estimating stage time…';
      if(d.fraction===null)$('progress').removeAttribute('value');else $('progress').value=d.fraction;
      log(d.stage);
    }else if(d.type==='progress'){
      if(Number.isFinite(d.fraction))$('progress').value=d.fraction;
      const elapsed=(performance.now()-stageStarted)/1000;
      $('eta').textContent=d.fraction>.02&&elapsed>2?`~${time(elapsed*(1-d.fraction)/d.fraction)} left in stage`:'Estimating stage time…';
    }else if(d.type==='memory'){
      $('memory').textContent=`Last completed WASM stage: ${d.stage||'unknown'} · heap ${(d.bytes/1048576).toFixed(0)} MiB`;
    }else if(d.type==='log')log(d.line);
    else if(d.type==='error'){
      if(candidate&&type==='verify'&&oom(d.message))publishCandidate(false,d.message);
      else fail(d.message);
     }else if(d.type==='inspected'){
       worker?.terminate();worker=null;
       movieDuration=d.media.duration;movieAudio=d.media.audio;movieJob.audio=movieAudio;
       log('Movie duration '+time(movieDuration)+'; audio '+(movieAudio?'included':'not present')+'.');
       continueMovie();
     }else if(d.type==='segment'){
       worker?.terminate();worker=null;
       try{
         await appendMovieSegment(movieJob,d.blob,d.frames);
         if(token!==runToken)return;
         movieFrames+=d.frames;
         log('Chapter '+movieParts+' saved to local storage: '+(d.blob.size/1e6).toFixed(2)+' MB, '+d.frames+' frames.');
         continueMovie();
       }catch(err){if(token===runToken)fail('Could not save movie chapter: '+(err.message||String(err))+'. Check free device storage.');}
     }else if(d.type==='candidate'){
      candidate=d;
      log('Candidate safely retained; releasing encoding worker before verification.');
      switchWorker('verify',{type:'verify',kind:'video',blob:d.blob,frames:d.frames,seconds:d.seconds,settings:s});
    }else if(d.type==='verified'){
      if(d.kind==='video'&&candidate?.audio){
        log('Video decoded successfully; releasing video verifier before audio verification.');
        switchWorker('verify',{type:'verify',kind:'audio',blob:candidate.blob,frames:candidate.frames,seconds:candidate.seconds,settings:s});
      }else publishCandidate(true);
    }
  };
  w.postMessage(payload);
};
const switchWorker=(type,payload)=>{
  worker?.terminate();worker=null;
  // Allow Safari to reclaim the previous WASM instance and its pthread pool.
  setTimeout(()=>{if(token===runToken)startWorker(type,payload);},300);
};
if(movieMode){
   try{movieJob=await createMovieJob();if(token===runToken)startWorker('inspect',{type:'inspect',file,settings:s});else cleanupMovieJob(movieJob,false).catch(()=>{});}
   catch(err){if(token===runToken)fail('Cannot start long movie: '+(err.message||String(err)));}
 }else startWorker('convert',{type:'convert',file,settings:s});
};
$('report').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='MobiPEG-conversion-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);};
window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});document.addEventListener('visibilitychange',()=>{if(busy&&document.hidden)log('Tab backgrounded: this browser may pause or terminate conversion. Keep the tab visible.');});

$('inspectAudio').onclick=()=>{
  if(!file||busy)return;
  const selected=file,w=new Worker('worker.js?v=20261116d');
  $('inspectAudio').disabled=true;
  const end=()=>{w.terminate();$('inspectAudio').disabled=false;};
  w.onerror=e=>{log('Audio inspection failed: '+e.message);end();};
  w.onmessage=({data:d})=>{
    if(d.type==='error'){log(d.message);end();}
    if(d.type==='inspected'){
      if(file===selected){
        $('audioTrack').replaceChildren(...(d.tracks.length?d.tracks.map(t=>new Option(t.label,String(t.index))):[new Option('No audio','0')]));
      }
      end();
    }
  };
  w.postMessage({type:'inspect',file:selected,settings:settings()});
};
