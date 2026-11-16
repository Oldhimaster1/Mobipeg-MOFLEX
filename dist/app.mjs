import{validate,rate}from'./core.mjs';
const $=id=>document.getElementById(id),form=$('settings');let file=null,worker=null,previewURL=null,outputURL=null,started=0,stageStarted=0,ticker=null,report=null,wake=null,busy=false,runToken=0;
const time=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
function log(s){$('logs').textContent=($('logs').textContent+'\n'+s).slice(-16000);}
function settings(){const d=new FormData(form);return validate({mode:d.get('mode'),engine:d.get('engine')||'auto',preset:d.get('preset'),resolution:d.get('resolution'),fps:d.get('fps'),filter:d.get('filter'),motion:d.get('motion'),q:d.get('q')===''?null:Number(d.get('q')),maxMB:d.get('maxMB')===''?null:Number(d.get('maxMB'))});}
function select(f){if(busy||!f)return;file=f;if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(f);$('preview').src=previewURL;$('empty').hidden=true;$('selected').hidden=false;$('drop').classList.add('has-video');$('replace').hidden=false;$('filename').textContent=f.name;$('filesize').textContent=(f.size/1e6).toFixed(2)+' MB';$('filemeta').textContent='Preview unavailable? The encoder can still inspect this file.';$('convert').disabled=false;}
$('preview').onloadedmetadata=()=>{$('filemeta').textContent=`${$('preview').videoWidth} × ${$('preview').videoHeight} · ${time($('preview').duration)}`;};$('file').onchange=e=>select(e.target.files[0]);$('replace').onclick=()=>$('file').click();for(const type of ['dragenter','dragover'])$('drop').addEventListener(type,e=>{e.preventDefault();if(!busy)$('drop').classList.add('over');});for(const type of ['dragleave','drop'])$('drop').addEventListener(type,e=>{e.preventDefault();$('drop').classList.remove('over');if(type==='drop')select(e.dataTransfer.files[0]);});
form.onchange=()=>{const stereo=new FormData(form).get('mode')!=='2d';$('modehint').textContent=stereo?`True 3D · layout 0 · ${ (rate($('fps').value)*2).toFixed(3).replace(/\.000$/,'')} coded eye frames/sec`:'Standard 2D · MOFLEX layout 6';};$('reset').onclick=()=>{if(!busy){form.reset();form.dispatchEvent(new Event('change'));}};
function lock(v){busy=v;for(const el of form.elements)el.disabled=v;$('convert').disabled=v||!file;$('reset').disabled=v;$('replace').disabled=v;$('file').disabled=v;}
function finish(){runToken++;worker?.terminate();worker=null;clearInterval(ticker);lock(false);$('cancel').hidden=true;wake?.release().catch(()=>{});wake=null;}
function fail(message){$('stage').textContent='Conversion stopped';$('error').hidden=false;$('error').textContent=message;log(message);$('progress').value=0;finish();}
$('cancel').onclick=()=>{fail('Cancelled. Your original file is untouched.');};
form.onsubmit=async e=>{e.preventDefault();if(!file||busy)return;let s;try{s=settings();}catch(e){alert(e.message);return;}if(file.size>512*1024*1024&&!confirm('This is a large input. Browser memory may be insufficient, especially on mobile. Continue?'))return;lock(true);const token=++runToken;if(outputURL){URL.revokeObjectURL(outputURL);outputURL=null;}$('job').hidden=false;$('result').hidden=true;$('error').hidden=true;$('cancel').hidden=false;$('stage').textContent='Loading native WASM encoder…';$('joblabel').textContent='CONVERSION';$('logs').textContent='MobiPEG V15 · fixed layout-0 source\nNo media upload. WebAssembly · FFmpeg scheduler threads, single codec thread.';$('memory').textContent='';$('eta').textContent='Estimating time…';$('progress').removeAttribute('value');started=stageStarted=performance.now();ticker=setInterval(()=>$('elapsed').textContent=time((performance.now()-started)/1000)+' elapsed',1000);$('job').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});try{const requestedWake=await navigator.wakeLock?.request('screen');if(token!==runToken){requestedWake?.release().catch(()=>{});return;}wake=requestedWake;}catch{}if(token!==runToken)return;
let candidate=null;
const oom=message=>/out of memory|memory access out of bounds|allocation failed|cannot allocate|failed to grow memory/i.test(String(message));
const publishCandidate=(verified,reason='')=>{
  if(!candidate)return fail('The encoded MOFLEX is no longer available.');
  const d=candidate;
  report={encoder:'MobiPEG V15 layout-0 WASM',input:{name:file.name,bytes:file.size},settings:s,output:{bytes:d.blob.size,q:d.q,codedFrames:d.frames,seconds:d.seconds,audio:d.audio,attempts:d.attempts},verified,verificationFailure:verified?null:reason,elapsedSeconds:(performance.now()-started)/1000,userAgent:navigator.userAgent};
  outputURL=URL.createObjectURL(d.blob);
  $('download').href=outputURL;
  $('download').download=file.name.replace(/\.[^.]+$/,'')+'_MobiPEG_V15_'+s.mode+(verified?'':'_UNVERIFIED')+'.moflex';
  $('download').textContent=verified?'Download verified .moflex':'Download unverified .moflex';
  $('stage').textContent=verified?'Your MOFLEX is ready.':'MOFLEX encoded; verification incomplete';
  $('joblabel').textContent=verified?'COMPLETE · DECODE VERIFIED':'ENCODE COMPLETE · NOT FULLY VERIFIED';
  $('progress').value=1;
  $('eta').textContent=verified?'All checks passed':'Verification not completed';
  $('error').hidden=verified;
  if(!verified)$('error').textContent='The output was encoded, but verification could not finish because browser memory ran out. This download has NOT passed full decoding checks. Check it before trusting or sharing it.';
  $('result').hidden=false;
  $('resultmeta').textContent=`${(d.blob.size/1e6).toFixed(2)} MB · ${d.frames.toLocaleString()} coded frames · Q${d.q} · ${d.audio?'ADPCM audio':'No audio'} · ${time(d.seconds)}${verified?'':' · UNVERIFIED'}`;
  log(verified?'Complete video'+(d.audio?' + audio':'')+' decode passed. Physical 3DS playback is not certified by this check.':'Verification incomplete: '+reason+'; candidate offered as UNVERIFIED.');
  candidate=null;
  finish();
};
const startWorker=(type,payload)=>{
  if(token!==runToken)return;
  const w=new Worker('worker.js');worker=w;
  w.onerror=e=>{
    if(token!==runToken||worker!==w)return;
    const message=`Encoder worker failed: ${e.message||'unknown error'}`;
    if(candidate&&type==='verify'&&oom(message))publishCandidate(false,message);else fail(message);
  };
  w.onmessage=({data:d})=>{
    if(token!==runToken||worker!==w)return;
    if(d.type==='status'){
      $('stage').textContent=d.stage;stageStarted=performance.now();$('eta').textContent='Estimating stage time…';
      if(d.fraction===null)$('progress').removeAttribute('value');else $('progress').value=d.fraction;
      log(d.stage);
    }else if(d.type==='progress'){
      $('progress').value=d.fraction;
      const elapsed=(performance.now()-stageStarted)/1000;
      $('eta').textContent=d.fraction>.02&&elapsed>2?`~${time(elapsed*(1-d.fraction)/d.fraction)} left in stage`:'Estimating stage time…';
    }else if(d.type==='memory'){
      $('memory').textContent=`Last completed WASM stage: ${d.stage||'unknown'} · heap ${(d.bytes/1048576).toFixed(0)} MiB`;
    }else if(d.type==='log')log(d.line);
    else if(d.type==='error'){
      if(candidate&&type==='verify'&&oom(d.message))publishCandidate(false,d.message);
      else fail(d.message);
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
startWorker('convert',{type:'convert',file,settings:s});
};
$('report').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='MobiPEG-conversion-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);};
window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});document.addEventListener('visibilitychange',()=>{if(busy&&document.hidden)log('Tab backgrounded: this browser may pause or terminate conversion. Keep the tab visible.');});
