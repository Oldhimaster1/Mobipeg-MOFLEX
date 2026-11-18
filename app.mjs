import{initLanguage,translateText}from'./i18n.mjs?v=20261117f';
import{createUsage}from'./usage.mjs?v=20261117a';
import{validate,rate,PRESETS,ADVANCED_NUMBERS,ADVANCED_ENUMS,encodeArgs,encodeClipArgs,audioArgs,environment}from'./core.mjs?v=20261118f';
import{allocateMovieBudget,createMovieJob,appendMovieSegment,assembleMovie,cleanupMovieJob,getCodedRate,nextMovieClip,planMovieClips,loadMovieSegment}from'./movie.mjs?v=20261118f';
import{openCheckpoint,setCheckpointMedia,restoreCheckpoints,persistRange,closeCheckpoint}from'./checkpoints.mjs?v=20261118f';
import{estimateConversion,totalEstimate,formatBytes,FAT32_LIMIT,FAT32_MESSAGE,fitsFat32,fat32Estimate}from'./queue.mjs?v=20261117v';
import{runParallelMovie,planBalancedMovieClips}from'./parallel.mjs?v=20261118g';
import{batchStorage,saveBatchFile}from'./batch-output.mjs?v=20261117s';
import{loadQueue,saveQueue,clearSavedQueue,relinkQueue,sourceIdentity}from'./queue-state.mjs?v=20261117y';
import{listSavedMovieJobs,removeSavedMovieJob}from'./checkpoint-manager.mjs?v=20261117x';
const $=id=>document.getElementById(id),form=$('settings');let file=null,worker=null,previewURL=null,outputURL=null,started=0,stageStarted=0,ticker=null,report=null,wake=null,busy=false,runToken=0,stallMonitor=null,movieJob=null,completedMovieJob=null,sampleWorker=null,sampleToken=0,sampleData=null,audioInspector=null,parallelAbort=null;
let queue=[],activeQueueId=null,queueRunning=false,queueCurrent=null,queueDownloaded=false,originStorage=null,nextQueueId=1,restoringSettings=false;
let queueRestored=false,queueRestoreError=false;
function persistQueue(){
  if(!queueRestored||queueRestoreError)return;
  try{saveQueue(queue);}catch(error){
    console.warn('Cannot save browser queue:',error);
    const notice=document.getElementById('queueRestoreStatus');
    if(notice)notice.textContent='Queue storage is unavailable. Jobs may be lost if this tab closes.';
  }
}
// Hardware concurrency is a *logical* upper bound, not a RAM guarantee.
// Phones default to one encoder to avoid exhausting their browser process.
const coreMax=Math.max(1,Math.floor(Number(navigator.hardwareConcurrency)||1));
const workerField=document.createElement('div');workerField.className='field workers-field';
workerField.innerHTML='<label for="workers">Parallel movie encoders: <strong id="workerValue"></strong></label><input id="workers" name="workers" type="range" min="1" step="1"><p class="hint">Balanced timeline ranges, not source chapters. More than one worker also enables parallel encoding for short videos. Each worker uses extra RAM and temporary local storage; phones start at one.</p>';
const workerSlider=workerField.querySelector('input');workerSlider.max=String(coreMax);
workerSlider.value=String(/iPhone|iPad|iPod|Android|Mobile/i.test(navigator.userAgent)?1:Math.min(2,coreMax));
workerSlider.defaultValue=workerSlider.value;
workerField.querySelector('#workerValue').textContent=workerSlider.value+' / '+coreMax+' logical cores';
$('longMovie').closest('.field').after(workerField);
const audioCodecField=document.createElement('div');audioCodecField.className='field';audioCodecField.innerHTML='<label for="audioCodec">MOFLEX audio codec</label><select id="audioCodec" name="audioCodec"><option value="adpcm">ADPCM — verified compatibility</option><option value="fastaudio">FastAudio — smaller, experimental on 3DS</option></select><p class="hint">FastAudio takes less space. Use ADPCM for the tested 3DS audio format.</p>';$('audioTrack').closest('.field').after(audioCodecField);
const audioOffsetField=document.createElement('div');
audioOffsetField.className='field';
audioOffsetField.innerHTML='<label for="audioOffsetMs">Audio offset (ms)</label><input id="audioOffsetMs" name="audioOffsetMs" type="number" min="-30000" max="30000" step="1" value="0"><p class="hint">Positive values delay audio. Negative values start it earlier.</p>';
audioCodecField.after(audioOffsetField);
const normalizationField=document.createElement('label');
normalizationField.className='hint';
normalizationField.innerHTML='<input id="normalizeAudio" name="normalizeAudio" type="checkbox"> Normalize audio peak';
audioOffsetField.after(normalizationField);
const hdrField=document.createElement('div');hdrField.className='field';
hdrField.innerHTML='<label for="hdrMode">HDR to SDR</label><select id="hdrMode" name="hdrMode"><option value="auto">Automatic — PQ / HLG to SDR</option><option value="off">Off — no color conversion</option><option value="mobius">Mobius — preserve shadows</option><option value="hable">Hable — cinematic highlights</option><option value="reinhard">Reinhard — soft highlights</option></select><label for="hdrTransfer">Source transfer</label><select id="hdrTransfer" name="hdrTransfer"><option value="auto">Detect PQ / HLG from metadata</option><option value="pq">PQ / HDR10 — force</option><option value="hlg">HLG — force</option></select><p class="hint">BT.2020 to BT.709 conversion uses a locally generated color LUT. Tagged HDR is detected automatically; untagged HDR can be specified manually. SDR files are unchanged.</p>';
normalizationField.after(hdrField);
const timeline=document.createElement('div');timeline.id='parallelTimeline';timeline.className='parallel-timeline';timeline.hidden=true;timeline.setAttribute('aria-label','Parallel encoder timelines');
$('progress').after(timeline);
const playerLink=document.createElement('a');playerLink.href='player.html?v=20261117s';playerLink.className='secondary';playerLink.textContent='Open MOFLEX player ↗';playerLink.style.marginTop='1rem';
$('result').append(playerLink);
const navPlayer=document.createElement('a');navPlayer.href='player.html?v=20261117s';navPlayer.textContent='MOFLEX Player ↗';
document.querySelector('.header-right')?.append(navPlayer);
const navCIA=document.createElement('a');navCIA.href='cia.html';navCIA.textContent='CIA project builder ↗';document.querySelector('.header-right')?.append(navCIA);
const renderWorkerCount=()=>{workerField.querySelector('#workerValue').textContent=workerSlider.value+' / '+coreMax+' logical cores';};
workerSlider.addEventListener('input',renderWorkerCount);
function renderParallelProgress(update){
  if(update.log){log(update.log);return;}
  if(!update.fractions)return;
  if(timeline.children.length!==update.workers){
    timeline.replaceChildren(...Array.from({length:update.workers},(_,i)=>{
      const shard=document.createElement('span');shard.className='parallel-shard';shard.title=`Encoder ${i+1}`;
      const fill=document.createElement('i');shard.append(fill);return shard;
    }));
  }
  timeline.hidden=false;
  [...timeline.children].forEach((item,i)=>{item.firstChild.style.width=(100*update.fractions[i]).toFixed(1)+'%';item.setAttribute('aria-label',`Worker ${i+1}: ${Math.round(100*update.fractions[i])}%`);});
  $('progress').value=update.overall;
  $('stage').textContent=`Parallel encoding · ${update.workers} workers · ${update.clips} timeline ranges`;
  $('eta').textContent=`${Math.round(update.overall*100)}% of movie encoded · assembling and verification follow`;
}
const usage=createUsage();
const usageOptOut=$('usageOptOut');
usageOptOut.checked=!usage.enabled();
usageOptOut.disabled=usage.privacySignal();
usageOptOut.onchange=()=>usage.setEnabled(!usageOptOut.checked);
// Give visitors time to use the footer opt-out before the initial view report.
setTimeout(()=>usage.view(),3000);
const time=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
function log(s){$('logs').textContent=($('logs').textContent+'\n'+s).slice(-16000);}
function readAdvanced(data){
  if(!data.has('advancedEnabled'))return null;
  return Object.fromEntries([...Object.keys(ADVANCED_NUMBERS),...Object.keys(ADVANCED_ENUMS)]
    .map(k=>[k,data.get('adv-'+k)]).filter(([,v])=>v!==null&&v!=='')
    .map(([k,v])=>[k,Object.hasOwn(ADVANCED_NUMBERS,k)?Number(v):v]));
}
function advancedPreview(){
  const enabled=$('advancedEnabled').checked;
  $('advancedControls').hidden=!enabled;
  for(const el of $('advancedControls').querySelectorAll('input,select'))el.disabled=busy||!enabled;
  if(!enabled||busy)return;
  try{
    const s=settings();s.movieAudio=$('longMovie').checked;
    const q=s.q??PRESETS[s.preset].q;
    const seconds=s.movieAudio?nextMovieClip(0,Number.isFinite($('preview').duration)?$('preview').duration:30,getCodedRate(s),30).seconds:Number.isFinite($('preview').duration)?$('preview').duration:1;
    const args=s.movieAudio?encodeClipArgs(s,q,0,seconds):encodeArgs(s,q);
    const quote=v=>"'"+String(v).replaceAll("'","'\\''")+"'";
    $('advancedCommand').textContent=Object.entries(environment(s)).map(([k,v])=>k+'='+v).join(' ')+'\nffmpeg '+args.map(quote).join(' ')+
      '\n\nffmpeg '+audioArgs(s,seconds).map(quote).join(' ')+
      '\n\n'+(s.movieAudio?'First timeline range; repeated with aligned seeks. ':'')+'Audio invocation runs only when an audio stream exists. Duration uses source metadata (1 s placeholder before a file is selected). Size-limited trials may change Q.';
  }catch(e){$('advancedCommand').textContent=e.message;}
}
function settings(){const d=new FormData(form),audioOffsetMs=Number(d.get('audioOffsetMs')||0);return validate({mode:d.get('mode'),hdrMode:d.get('hdrMode')||'auto',hdrTransfer:d.get('hdrTransfer')||'auto',engine:d.get('engine')||'auto',preset:d.get('preset'),resolution:d.get('resolution'),fps:d.get('fps'),filter:d.get('filter'),motion:d.get('motion'),q:d.get('q')===''?null:Number(d.get('q')),audioTrack:Number(d.get('audioTrack')||0),...(d.has('normalizeAudio')?{normalizeAudio:true}:{}),...(audioOffsetMs?{audioOffsetMs}:{}),audioCodec:d.get('audioCodec')||'adpcm',maxMB:d.get('maxMB')===''?null:Number(d.get('maxMB')),speed:d.get('speed')||'original',workers:Number(d.get('workers')||1),advanced:readAdvanced(d),crop:{fit:d.get('fit'),aspect:d.get('aspect')||'source',...Object.fromEntries(['left','right','top','bottom'].map(k=>[k,Number(d.get('crop-'+k))]))}});}
function snapshotSettings(){const value=structuredClone(settings());value.movieAudio=$('longMovie').checked;return value;}
function applySettings(value){
  restoringSettings=true;
  const set=(name,value)=>{const control=form.elements.namedItem(name);if(!control)return;if(control instanceof RadioNodeList){for(const el of control)el.checked=el.value===String(value);}else control.value=value??'';};
  for(const key of ['mode','hdrMode','hdrTransfer','engine','preset','resolution','fps','filter','motion','q','audioTrack','audioCodec','audioOffsetMs','maxMB','speed','workers'])set(key,key==='audioOffsetMs'?value[key]??0:value[key]);renderWorkerCount();
  $('normalizeAudio').checked=!!value.normalizeAudio;
  set('longMovie',value.movieAudio?'on':'');$('longMovie').checked=!!value.movieAudio;
  set('fit',value.crop?.fit??'fit');set('aspect',value.crop?.aspect??'source');for(const edge of ['left','right','top','bottom'])set('crop-'+edge,value.crop?.[edge]??0);
  $('advancedEnabled').checked=value.advanced!==null;
  for(const key of [...Object.keys(ADVANCED_NUMBERS),...Object.keys(ADVANCED_ENUMS)])set('adv-'+key,value.advanced?.[key]??'');
  restoringSettings=false;form.dispatchEvent(new Event('change'));
}
function select(f,item=null){
  if(busy||!f)return;invalidateSample();file=f;activeQueueId=item?.id??activeQueueId;
  $('audioTrack').replaceChildren(new Option('0 — First audio track','0'));if(item?.settings.audioTrack>0)$('audioTrack').append(new Option(`${item.settings.audioTrack} — Saved audio track`,String(item.settings.audioTrack)));if(item)applySettings(item.settings);
  $('sampleStatus').textContent='Generate a preview to see the current settings.';$('makeSample').disabled=false;$('samplePosition').disabled=false;$('sampleStart').value='0';
  if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(f);$('preview').src=previewURL;$('empty').hidden=true;$('selected').hidden=false;$('drop').classList.add('has-video');$('replace').hidden=false;$('filename').textContent=f.name;$('filesize').textContent=(f.size/1e6).toFixed(2)+' MB';$('filemeta').textContent='Preview unavailable? The encoder can still inspect this file.';$('convert').disabled=false;renderQueue();
}
$('preview').onloadedmetadata=()=>{const item=queue.find(x=>x.id===activeQueueId);if(item){item.duration=$('preview').duration;item.audio=true;if(navigator.storage?.getDirectory&&item.duration>180&&!item.settings.movieAudio){item.settings.movieAudio=true;$('longMovie').checked=true;}refreshEstimates();}$('filemeta').textContent=`${$('preview').videoWidth} × ${$('preview').videoHeight} · ${time($('preview').duration)}`;advancedPreview();};
$('file').onchange=e=>{addFiles(e.target.files);e.target.value='';};$('replace').onclick=()=>$('file').click();for(const type of ['dragenter','dragover'])$('drop').addEventListener(type,e=>{e.preventDefault();if(!busy)$('drop').classList.add('over');});for(const type of ['dragleave','drop'])$('drop').addEventListener(type,e=>{e.preventDefault();$('drop').classList.remove('over');if(type==='drop')addFiles(e.dataTransfer.files);});
form.oninput=()=>{advancedPreview();invalidateSample();saveActiveSettings();};
form.onchange=()=>{renderWorkerCount();advancedPreview();invalidateSample();saveActiveSettings();const stereo=new FormData(form).get('mode')!=='2d';$('modehint').textContent=stereo?`True 3D · layout 0 · ${ (rate($('fps').value)*2).toFixed(3).replace(/\.000$/,'')} coded eye frames/sec`:'Standard 2D · MOFLEX layout 6';};$('reset').onclick=()=>{if(!busy){form.reset();form.dispatchEvent(new Event('change'));}};
function saveActiveSettings(){
  if(restoringSettings||busy)return;const item=queue.find(x=>x.id===activeQueueId);if(!item)return;
  try{item.settings=snapshotSettings();refreshEstimates();}catch{}
}
function addFiles(files){
  if(busy)return;
  let initial;try{initial=snapshotSettings();}catch(e){showAlert(e.message);return;}
  const {linked,unmatched}=relinkQueue(queue,Array.from(files));
  const added=[...linked];
  for(const selected of unmatched){
    if(!selected||queue.some(item=>item.file===selected))continue;
    const item={id:nextQueueId++,file:selected,source:sourceIdentity(selected),
      settings:structuredClone(initial),duration:null,audio:true,status:'pending',estimate:null};
    queue.push(item);added.push(item);probeBrowserMetadata(item);
  }
  if(!added.length)return;
  $('queuePanel').hidden=false;select(added[0].file,added[0]);
  if(linked.length)$('queueRestoreStatus').textContent=
    'Restored '+linked.length+' video'+(linked.length===1?'':'s')+' with their saved settings.';
  refreshStorage();renderQueue();
}
let batchDestination=null,batchSaving=false;
const folderInput=document.createElement('input');
folderInput.type='file';folderInput.webkitdirectory=true;folderInput.multiple=true;folderInput.hidden=true;
folderInput.onchange=()=>{
  addFiles(Array.from(folderInput.files).filter(file=>file.type.startsWith('video/')||
    /\.(mp4|mkv|mov|webm|avi|m4v|moflex|mpeg|mpg|mts|m2ts)$/i.test(file.name)));
  folderInput.value='';
};
const folderButton=document.createElement('button');
folderButton.type='button';folderButton.className='text-button';folderButton.textContent='Add a folder';
folderButton.onclick=()=>{if(!busy&&!queueRunning)folderInput.click();};
$('replace').before(folderButton,folderInput);
const batchControls=document.createElement('div');
batchControls.innerHTML='<div class="queue-actions"><button id="batchFolder" type="button" class="text-button">Save to a folder</button><button id="batchPrivate" type="button" class="text-button">Save in this browser</button><button id="batchManual" type="button" class="text-button" hidden>Use manual downloads</button></div><p id="batchSaveStatus" class="hint" role="status"></p>';
$('startQueue').parentElement.before(batchControls);
const queueRecovery=document.createElement('div');
queueRecovery.className='queue-recovery';
queueRecovery.innerHTML='<p id="queueRestoreStatus" class="hint" role="status"></p><button type="button" id="reselectQueueSources" class="text-button" hidden>Reselect original videos</button><button type="button" id="discardSavedQueue" class="text-button" hidden>Discard unreadable saved queue</button>';
batchControls.after(queueRecovery);
const relinkInput=document.createElement('input');
relinkInput.type='file';relinkInput.multiple=true;relinkInput.hidden=true;
relinkInput.accept='video/*,.mkv,.avi,.mov,.webm,.m4v,.moflex';
relinkInput.onchange=()=>{addFiles(relinkInput.files);relinkInput.value='';};
queueRecovery.after(relinkInput);
$('reselectQueueSources').onclick=()=>{if(!busy&&!queueRunning)relinkInput.click();};
$('discardSavedQueue').onclick=()=>{
  if(busy||queueRunning||!queueRestoreError)return;
  if(!askConfirm('Discard the unreadable saved queue data? This cannot be undone. Video files are not affected.'))return;
  try{
    clearSavedQueue();queueRestoreError=false;$('discardSavedQueue').hidden=true;
    $('queueRestoreStatus').textContent='Old queue data cleared. New and current jobs can now be saved.';
    persistQueue();
  }catch(error){$('queueRestoreStatus').textContent='Could not clear the saved queue: '+(error.message||String(error));}
};
$('batchFolder').hidden=typeof window.showDirectoryPicker!=='function';
$('batchPrivate').hidden=!navigator.storage?.getDirectory;
const savedPanel=document.createElement('section');
savedPanel.className='card';savedPanel.hidden=true;
savedPanel.innerHTML='<h2>Saved queue files</h2><p class="hint">Download or delete files saved in this browser. Keep any copies you want before clearing site storage.</p><ul id="savedBatchFiles"></ul>';
$('queuePanel').after(savedPanel);
const savedJobsPanel=document.createElement('section');
savedJobsPanel.id='savedJobsPanel';savedJobsPanel.className='card';
savedJobsPanel.hidden=!navigator.storage?.getDirectory;
savedJobsPanel.innerHTML='<h2>Saved movie recoveries</h2><p class="hint">Interrupted long movies can reuse verified ranges after you reselect the same original video and settings. These files are private to this browser; clearing site storage can remove them.</p><button type="button" class="text-button" id="refreshSavedJobs">Check saved recoveries</button><p id="savedJobsStatus" class="hint" role="status"></p><ul id="savedJobsList"></ul>';
savedPanel.after(savedJobsPanel);
async function refreshSavedJobs(){
  if(savedJobsPanel.hidden)return;
  $('refreshSavedJobs').disabled=true;
  $('savedJobsStatus').textContent='Checking private movie storage…';
  try{
    const jobs=await listSavedMovieJobs();
    const list=$('savedJobsList');list.replaceChildren();
    for(const job of jobs){
      const row=document.createElement('li'),description=document.createElement('span');
      description.textContent=job.damaged
        ?'Damaged recovery · '+job.name+' · '+formatBytes(job.storedBytes)+' stored · '+job.problem+'. Cannot resume this job.'
        :job.name+' · '+job.ranges+' saved range records · '+formatBytes(job.storedBytes)+' stored';
      const remove=rowButton(job.damaged?'Delete damaged recovery':'Delete saved ranges',async()=>{
        if(!askConfirm('Delete all saved recovery data for '+job.name+'? Completed movie downloads are not affected.'))return;
        try{await removeSavedMovieJob(job.id);await refreshSavedJobs();}
        catch(error){$('savedJobsStatus').textContent=error.message||String(error);}
      });
      row.append(description,' ',remove);list.append(row);
    }
    const damaged=jobs.filter(job=>job.damaged).length,healthy=jobs.length-damaged;
    $('savedJobsStatus').textContent=jobs.length
      ?healthy+' recoverable job'+(healthy===1?'':'s')+', '+damaged+' damaged. Healthy jobs can resume with their original video and settings; damaged jobs can be deleted to reclaim space.'
      :'No unfinished movie recoveries found.';
  }catch(error){$('savedJobsStatus').textContent='Cannot inspect saved movies: '+(error.message||String(error));}
  finally{$('refreshSavedJobs').disabled=false;}
}
$('refreshSavedJobs').onclick=refreshSavedJobs;

async function refreshSavedBatch(){
  if(!navigator.storage?.getDirectory)return;
  try{
    const directory=await batchStorage();
    const list=$('savedBatchFiles');
    list.replaceChildren();
    for await(const [name,file] of directory.entries()){
      if(file.kind!=='file'||!name.endsWith('.moflex'))continue;
      const row=document.createElement('li');
      const download=rowButton('Download',async()=>{
        try{
          const url=URL.createObjectURL(await file.getFile()),link=document.createElement('a');
          link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
        }catch(error){showAlert(error.message);}
      });
      const remove=rowButton('Delete',async()=>{
        if(askConfirm('Delete the saved copy of '+name+'?')){
          try{await directory.removeEntry(name);await refreshSavedBatch();}
          catch(error){showAlert(error.message);}
        }
      });
      row.append(name,' ',download,' ',remove);
      list.append(row);
    }
    savedPanel.hidden=!list.children.length;
  }catch(error){if(error.name!=='NotFoundError')console.warn(error.message);}
}
function chooseBatchDestination(destination){
  batchDestination=destination;
  $('batchManual').hidden=!destination;
  $('batchSaveStatus').textContent=destination
    ? 'Verified outputs will save automatically to '+(destination.private?'this browser':destination.directory.name)+'.'
    : '';
}
$('batchFolder').onclick=async()=>{
  if(busy||queueRunning)return;
  try{chooseBatchDestination({directory:await window.showDirectoryPicker({mode:'readwrite'}),private:false});}
  catch(error){if(error.name!=='AbortError')$('batchSaveStatus').textContent=error.message;}
};
$('batchPrivate').onclick=async()=>{
  if(busy||queueRunning)return;
  try{chooseBatchDestination({directory:await batchStorage(true),private:true});await refreshSavedBatch();}
  catch(error){$('batchSaveStatus').textContent=error.message;}
};
$('batchManual').onclick=()=>{if(!busy&&!queueRunning)chooseBatchDestination(null);};
refreshSavedBatch();
function probeBrowserMetadata(item){
  const video=document.createElement('video'),url=URL.createObjectURL(item.file);video.preload='metadata';video.muted=true;
  const done=duration=>{URL.revokeObjectURL(url);video.removeAttribute('src');if(Number.isFinite(duration)&&duration>0)item.duration=duration;refreshEstimates();};
  video.onloadedmetadata=()=>done(video.duration);video.onerror=()=>done(null);video.src=url;
}
function rowButton(label,action,disabled=false){const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=label;button.disabled=disabled;button.onclick=event=>{event.stopPropagation();action();};return button;}
function renderQueue(){
  $('queuePanel').hidden=!queue.length&&!queueRestoreError;const list=$('queueList');list.replaceChildren();
  queue.forEach((item,index)=>{
    const row=document.createElement('li');row.className='queue-item'+(item.id===activeQueueId?' active':'')+(item===queueCurrent?' current':'');
    const selectButton=document.createElement('button');selectButton.type='button';selectButton.className='queue-select';selectButton.disabled=busy||queueRunning;
    selectButton.onclick=()=>{if(!item.file){relinkInput.click();return;}saveActiveSettings();select(item.file,item);};
    const name=document.createElement('strong');name.textContent=item.source?.name??item.file?.name??'Video';
    const meta=document.createElement('span'),duration=item.duration?time(item.duration):'duration unavailable';
    const estimate=item.estimate?.known?`${formatBytes(item.estimate.minimum)}–${formatBytes(item.estimate.maximum)}`:'estimate pending';
    meta.textContent=`${duration} · ${estimate} · ${item.status==='needs-file'?'reselect original video':item.status}`;
    selectButton.append(name,meta);
    const actions=document.createElement('div');actions.className='queue-item-actions';
    actions.append(rowButton('↑',()=>moveQueue(index,-1),busy||queueRunning||index===0),
      rowButton('↓',()=>moveQueue(index,1),busy||queueRunning||index===queue.length-1),
      rowButton('Remove',()=>removeQueue(item),busy||queueRunning));
    if(['failed','cancelled','done'].includes(item.status))
      actions.append(rowButton('Retry',()=>{item.status=item.file?'pending':'needs-file';renderQueue();},busy||queueRunning));
    row.append(selectButton,actions);list.append(row);
  });
  $('startQueue').disabled=busy||queueRunning||!queue.some(item=>item.status==='pending'&&item.file);
  $('clearQueue').disabled=busy||queueRunning;
  for(const id of ['batchFolder','batchPrivate','batchManual'])$(id).disabled=busy||queueRunning;
  folderButton.disabled=busy||queueRunning;
  $('reselectQueueSources').hidden=!queue.some(item=>item.status==='needs-file');
  $('reselectQueueSources').disabled=busy||queueRunning;
  if(!queue.length&&!queueRestoreError)$('queueRestoreStatus').textContent='';
  persistQueue();
}
function moveQueue(index,offset){const target=index+offset;if(target<0||target>=queue.length)return;[queue[index],queue[target]]=[queue[target],queue[index]];renderQueue();}
function removeQueue(item){
  queue=queue.filter(value=>value!==item);if(item.id===activeQueueId){const next=queue[0];activeQueueId=null;if(next)select(next.file,next);else clearSelectedFile();}refreshEstimates();renderQueue();
}
function clearSelectedFile(){file=null;if(previewURL)URL.revokeObjectURL(previewURL);previewURL=null;$('preview').removeAttribute('src');$('empty').hidden=false;$('selected').hidden=true;$('drop').classList.remove('has-video');$('replace').hidden=true;$('convert').disabled=true;invalidateSample();}
$('clearQueue').onclick=()=>{if(busy||queueRunning)return;queue=[];activeQueueId=null;clearSelectedFile();renderQueue();refreshEstimates();};
async function refreshStorage(){try{originStorage=await navigator.storage?.estimate?.()??null;}catch{originStorage=null;}refreshEstimates();}
function refreshEstimates(){
  for(const item of queue)item.estimate=estimateConversion({fileBytes:item.file?.size??item.source.size,duration:item.duration,settings:{...item.settings,movieAudio:item.settings.movieAudio||item.settings.workers>1},audio:item.audio});
  const totals=totalEstimate(queue),free=originStorage?.quota&&Number.isFinite(originStorage.usage)?Math.max(0,originStorage.quota-originStorage.usage):null;
  const output=totals.known?`${formatBytes(totals.minimum)}–${formatBytes(totals.maximum)}`:'waiting for durations';
  $('estimateSummary').textContent=`${queue.length} video${queue.length===1?'':'s'} · ${formatBytes(totals.inputBytes)} input · ${output} estimated output · ${totals.known?'up to '+formatBytes(totals.peakTemporary)+' temporary disk per item':'temporary disk unknown'} · rough peak RAM ${totals.known?formatBytes(totals.peakMemory):'unknown'} · ${free===null?'browser storage unavailable':formatBytes(free)+' browser storage free'}`+(totals.unknown?` · ${totals.unknown} duration${totals.unknown===1?'':'s'} unavailable`:'');
  const largest=queue.filter(item=>item.estimate?.known).reduce((max,item)=>Math.max(max,item.estimate.maximum),0);
  $('estimateSummary').textContent+=' · FAT32 limit '+FAT32_LIMIT.toLocaleString()+' bytes per file'+(largest?' · '+fat32Estimate({maximum:largest}):'');
  const ratio=free&&totals.peakTemporary?Math.min(1,totals.peakTemporary/free):0;$('estimateMeter').style.width=(ratio*100).toFixed(1)+'%';$('estimateMeter').classList.toggle('warning',ratio>.8);renderQueue();
}
function beginNextQueuedItem(){
  const next=queue.find(item=>item.status==='pending'&&item.file);
  if(!next){queueRunning=false;queueCurrent=null;$('queueNext').hidden=true;$('startQueue').hidden=false;
    $('stage').textContent=queue.some(item=>item.status==='needs-file')
      ?'Queue paused — reselect the remaining source videos':'Queue complete';
    renderQueue();return;}
  queueCurrent=next;next.status='encoding';queueDownloaded=false;select(next.file,next);renderQueue();form.requestSubmit();
}
function stopQueueBeforeEncoding(){if(!queueRunning||!queueCurrent)return;if(queueCurrent.status==='encoding')queueCurrent.status='pending';queueCurrent=null;queueRunning=false;$('startQueue').hidden=false;$('queueNext').hidden=true;renderQueue();}
$('startQueue').onclick=()=>{if(busy||queueRunning)return;saveActiveSettings();queueRunning=true;$('startQueue').hidden=true;beginNextQueuedItem();};
$('download').addEventListener('click',()=>{if(queueRunning&&!batchSaving&&queueCurrent?.status==='ready'){queueDownloaded=true;$('queueNext').disabled=false;$('queueNext').textContent='Release storage & continue';}});
$('queueNext').onclick=async()=>{
  if(!queueRunning||!queueCurrent||batchSaving||queueCurrent.status==='ready'&&!queueDownloaded)return;
  if(outputURL){URL.revokeObjectURL(outputURL);outputURL=null;}$('result').hidden=true;
  if(completedMovieJob){const saved=completedMovieJob;completedMovieJob=null;$('clearMovieData').hidden=true;try{await cleanupMovieJob(saved,false);}catch(e){log('Queue cleanup warning: '+e.message);}}
  if(queueCurrent.status==='ready')queueCurrent.status='done';queueCurrent=null;$('queueNext').hidden=true;$('queueNext').disabled=true;beginNextQueuedItem();
};
function lock(v){busy=v;if(v)pauseSample();$('sampleMotion').disabled=v;$('samplePlay').disabled=v;$('sampleSeek').disabled=v;if(v&&audioInspector){audioInspector.terminate();audioInspector=null;}for(const el of form.elements)el.disabled=v;$('convert').disabled=v||!file;$('reset').disabled=v;$('replace').disabled=v;$('file').disabled=v;$('makeSample').disabled=v||!file;$('samplePosition').disabled=v||!file;$('sampleStart').disabled=v;advancedPreview();renderQueue();}
function finish(verified=false){
  runToken++;
  parallelAbort?.abort();parallelAbort=null;
  worker?.terminate();worker=null;
  clearInterval(ticker);clearInterval(stallMonitor);stallMonitor=null;
  lock(false);
  $('cancel').hidden=true;
  wake?.release().catch(()=>{});wake=null;
  if(!movieJob)return;
  const saved=movieJob;
  movieJob=null;
  const keep=!!outputURL;
  if(keep){completedMovieJob=saved;$('clearMovieData').hidden=false;}
  const cleanup=saved.manifest
    ? closeCheckpoint(saved,verified).finally(()=>cleanupMovieJob(saved,keep))
    : cleanupMovieJob(saved,keep);
  cleanup.catch(e=>log('Local cleanup warning: '+e.message));
}
function fail(message){$('stage').textContent='Conversion stopped';$('error').hidden=false;$('error').textContent=message;log(message);$('progress').value=0;if(queueRunning&&queueCurrent?.status==='encoding')queueCurrent.status='failed';finish();if(queueRunning&&queueCurrent){$('queueNext').hidden=false;$('queueNext').disabled=false;$('queueNext').textContent='Skip item & continue';renderQueue();}}
$('cancel').onclick=()=>{if(queueRunning&&queueCurrent)queueCurrent.status='cancelled';fail(movieJob?.manifest?'Paused. Select the same source and settings and convert again to resume.':'Cancelled. Your original file is untouched.');};
$('clearMovieData').onclick=async()=>{
  if(busy||!completedMovieJob)return;
  if(!askConfirm('Delete the temporary on-device movie copy? Download the .moflex first; this cannot be undone.'))return;
  const saved=completedMovieJob;completedMovieJob=null;
  try{await cleanupMovieJob(saved,false);$('clearMovieData').hidden=true;log('Temporary movie storage removed.');}
  catch(e){log('Could not clear local storage: '+e.message);}
};
form.onsubmit=async e=>{e.preventDefault();if(!file||busy)return;let s;try{s=settings();}catch(e){showAlert(e.message);stopQueueBeforeEncoding();return;}const movieMode=$('longMovie').checked||s.workers>1;s.movieAudio=movieMode;if(movieMode&&!navigator.storage?.getDirectory){showAlert('Parallel encoding requires on-device private file storage (OPFS), which is unavailable in this browser.');stopQueueBeforeEncoding();return;}const item=queue.find(value=>value.id===activeQueueId),free=originStorage?.quota&&Number.isFinite(originStorage.usage)?originStorage.quota-originStorage.usage:null;if(item?.estimate?.maximum>FAT32_LIMIT&&!askConfirm(fat32Estimate(item.estimate)+' Increase compression, lower resolution or frame rate, or split the movie. Continue with these settings?')){stopQueueBeforeEncoding();return;}if(movieMode&&item?.estimate?.known&&free!==null&&item.estimate.temporaryBytes>free&&!askConfirm('The estimated temporary storage exceeds the browser storage currently available. Continue anyway?')){stopQueueBeforeEncoding();return;}if(movieMode&&s.workers>1&&/iPhone|iPad|iPod|Android|Mobile/i.test(navigator.userAgent)&&!askConfirm(`${s.workers} concurrent native WASM encoders may exhaust mobile browser memory and terminate this tab. Use one worker for reliability. Continue with ${s.workers}?`)){stopQueueBeforeEncoding();return;}if(file.size>512*1024*1024&&!askConfirm('This is a large input. Browser memory may be insufficient, especially on mobile. Continue?')){stopQueueBeforeEncoding();return;}lock(true);const token=++runToken;if(outputURL){URL.revokeObjectURL(outputURL);outputURL=null;}if(completedMovieJob){const old=completedMovieJob;completedMovieJob=null;$('clearMovieData').hidden=true;cleanupMovieJob(old,false).catch(e=>log('Old movie cleanup warning: '+e.message));}$('job').hidden=false;$('result').hidden=true;$('error').hidden=true;$('cancel').hidden=false;$('cancel').textContent='Cancel';timeline.hidden=true;timeline.replaceChildren();$('stage').textContent='Loading native WASM encoder…';$('joblabel').textContent=queueRunning?`QUEUE · ${queue.indexOf(queueCurrent)+1}/${queue.length}`:'CONVERSION';$('logs').textContent='MobiPEG V15 · fixed layout-0 source\nNo media upload. WebAssembly · independent timeline encoders when enabled.';$('memory').textContent='';$('eta').textContent='Estimating time…';$('progress').removeAttribute('value');started=stageStarted=performance.now();ticker=setInterval(()=>$('elapsed').textContent=time((performance.now()-started)/1000)+' elapsed',1000);$('job').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});try{const requestedWake=await navigator.wakeLock?.request('screen');if(token!==runToken){requestedWake?.release().catch(()=>{});return;}wake=requestedWake;}catch{}if(token!==runToken)return;
let candidate=null;
let movieDuration=0,movieAudio=false,movieFrames=0,movieParts=0,rangeBudgets=null,peakGain=0;
const movieFPS=getCodedRate(s);
const joinMovie=async()=>{
  if(token!==runToken)return;
  expectMovieParts();
  $('joblabel').textContent='LONG MOVIE · ASSEMBLING';
  $('stage').textContent='Building complete movie and seek index';
  $('eta').textContent='Writing one MOFLEX to local storage…';
  timeline.hidden=true;$('progress').value=0;
  const merged=await assembleMovie(movieJob,s,v=>{
    if(token!==runToken)return;
    $('stage').textContent='Assembling movie · part '+v.chapter+'/'+v.chapters;
    $('progress').value=v.total?v.written/v.total:0;
  },()=>token!==runToken);
  if(token!==runToken)return;
  candidate={blob:merged.file,frames:merged.frames,seconds:merged.seconds,audio:movieAudio,audioCodec:movieAudio?s.audioCodec:null,q:s.maxMB===null?s.q??PRESETS[s.preset].q:null,attempts:movieParts,chapters:movieParts,durationFieldSaturated:merged.durationFieldSaturated};
  log('One indexed MOFLEX assembled: '+(merged.file.size/1e6).toFixed(2)+' MB, '+merged.frames+' frames.');
  if(merged.durationFieldSaturated)log('Warning: movie exceeds the legacy 32-bit duration field (71m35s); timestamps and frame index use wider fields. Physical 3DS playback and seeking must be tested.');
  switchWorker('verify',{type:'verify',kind:'video',blob:merged.file,frames:merged.frames,seconds:merged.seconds,settings:s});
};
const beginMoviePart=async()=>{
  if(token!==runToken)return;
  let clip=nextMovieClip(movieFrames,movieDuration,movieFPS,30);
  while(clip&&movieJob.segments[movieParts]){
    const part=movieJob.segments[movieParts++];
    movieFrames+=part.frames;
    const expected=Math.round(clip.seconds*rate(s.fps))*(s.mode==='2d'?1:2);
    if(part.frames<expected)movieDuration=movieFrames*movieFPS.den/movieFPS.num;
    clip=nextMovieClip(movieFrames,movieDuration,movieFPS,30);
  }
  if(clip){
    if(movieParts>Math.ceil(movieDuration/20)+4)throw Error('Movie timeline did not advance; conversion stopped to avoid repeated chapters.');
    movieParts++;
    $('joblabel').textContent='LONG MOVIE · RANGE '+movieParts;
    log('Encoding range '+movieParts+' starting '+time(clip.start)+', length '+time(clip.seconds)+'.');
    switchWorker('segment',{type:'segment',file,settings:s,clip,media:{duration:movieDuration,audio:movieAudio,peakGain},verifyRange:!!movieJob.manifest,rangeBudget:rangeBudgets?.[movieParts-1]});
    return;
  }
  movieJob.segments.length=movieParts;
  await joinMovie();
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
  if(!fitsFat32(d.blob.size))return fail(FAT32_MESSAGE);
  report={encoder:'MobiPEG V15 layout-0 WASM',input:{name:file.name,bytes:file.size},settings:s,output:{bytes:d.blob.size,q:d.q,codedFrames:d.frames,seconds:d.seconds,audio:d.audio,audioCodec:d.audioCodec??null,attempts:d.attempts,chapters:d.chapters??1,durationFieldSaturated:!!d.durationFieldSaturated},verified,verificationFailure:verified?null:reason,elapsedSeconds:(performance.now()-started)/1000,userAgent:navigator.userAgent};
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
  $('resultmeta').textContent=`${(d.blob.size/1e6).toFixed(2)} MB · ${d.frames.toLocaleString()} coded frames · ${d.q===null?'Adaptive quantizer':`Q${d.q}`} · ${d.audio?(d.audioCodec==='fastaudio'?'FastAudio':'ADPCM audio'):'No audio'} · ${time(d.seconds)}${d.durationFieldSaturated?' · 3DS >71 min seek behavior unverified':''}${verified?'':' · UNVERIFIED'}`;
  log(verified?'Complete video'+(d.audio?' + audio':'')+' decode passed. Physical 3DS playback is not certified by this check.':'Verification incomplete: '+reason+'; candidate offered as UNVERIFIED.');
  if(verified)usage.conversion(d.seconds,file.size,d.blob.size);
  candidate=null;
  finish(verified);
  if(queueRunning&&queueCurrent){queueCurrent.status='ready';$('clearMovieData').hidden=true;$('queueNext').hidden=false;$('queueNext').disabled=true;$('queueNext').textContent='Download the result to continue';renderQueue();}
  if(verified&&queueRunning&&queueCurrent&&batchDestination){
    const destination=batchDestination;
    batchSaving=true;
    $('stage').textContent='Saving verified output…';
    saveBatchFile(destination.directory,$('download').download,d.blob).then(async name=>{
      $('batchSaveStatus').textContent='Saved '+name;
      batchSaving=false;
      queueDownloaded=true;
      if(destination.private)refreshSavedBatch();
      await $('queueNext').onclick();
    }).catch(error=>{
      batchSaving=false;
      $('stage').textContent='Your MOFLEX is ready.';
      $('batchSaveStatus').textContent='Automatic save failed. Download this result to continue. '+error.message;
    });
  }
};
const startWorker=(type,payload)=>{
  if(token!==runToken)return;
  currentWorkerType=type;lastActivity=performance.now();idleWarningShown=false;const w=new Worker('worker.js?v=20261118g');worker=w;
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
       if(!item?.estimate?.known){
         const estimate=estimateConversion({fileBytes:file.size,duration:d.media.duration,settings:s,audio:d.media.audio});
         if(estimate.maximum>FAT32_LIMIT&&!askConfirm(fat32Estimate(estimate)+' Continue with these settings?')){
           stopQueueBeforeEncoding();
           fail('Conversion cancelled. Choose settings with a smaller estimated output.');
           return;
         }
       }
       if(!movieMode){
         currentWorkerType='convert';
         w.postMessage({type:'convert',file,settings:s,media:d.media});
         return;
       }
       worker?.terminate();worker=null;
       movieDuration=d.media.duration;movieAudio=d.media.audio;movieJob.audio=movieAudio;
       peakGain=d.media.peakGain??0;
       log('Movie duration '+time(movieDuration)+'; audio '+(movieAudio?'included':'not present')+'.');
       const job=movieJob;
       try{
         const clips=s.workers>1?planBalancedMovieClips(movieDuration,s,s.workers):planMovieClips(movieDuration,s);
         if(s.maxMB!==null){
           rangeBudgets=allocateMovieBudget(clips,Math.floor(s.maxMB*1e6));
           log('Maximum output size: '+formatBytes(s.maxMB*1e6)+'. Range budgets include audio and indexing.');
         }
         if(job.manifest){
           $('stage').textContent='Checking saved movie ranges…';
           await setCheckpointMedia(job,d.media);
           await restoreCheckpoints(job,clips,(index,frames)=>loadMovieSegment(job,index,frames),()=>token!==runToken);
           if(token!==runToken)return;
           const restored=job.segments.filter(Boolean).length;
           if(restored)log(`Resuming with ${restored} verified saved ranges.`);
         }
       }catch(error){if(token===runToken)fail(error.message);return;}
       if(s.workers>1){
         currentWorkerType='segment';parallelAbort=new AbortController();
         $('joblabel').textContent=$('longMovie').checked?'LONG MOVIE · PARALLEL':'PARALLEL ENCODING';
         log('Starting '+s.workers+' independent encoding lanes. These are timeline ranges, not source chapters.');
         runParallelMovie({file,settings:s,media:{duration:movieDuration,audio:movieAudio,peakGain},job:movieJob,
           workers:s.workers,signal:parallelAbort.signal,onUpdate:update=>{
             if(token===runToken)renderParallelProgress(update);
           }}).then(result=>{
             if(token!==runToken)return;
             movieParts=result.parts;movieFrames=result.frames;
             log('All '+movieParts+' parallel timeline parts saved; starting ordered assembly.');
             return joinMovie();
           }).catch(error=>{if(token===runToken)fail('Parallel movie conversion stopped: '+(error.message||String(error)));});
       }else continueMovie();
     }else if(d.type==='segment'){
       worker?.terminate();worker=null;
       if(d.empty){
         if(!movieFrames)return fail('No video frames could be decoded.');
         movieParts--;movieDuration=movieFrames*movieFPS.den/movieFPS.num;
         log('Video ended before the container audio; assembling the complete video.');
         continueMovie();return;
       }
       try{
         const job=movieJob,index=movieParts-1;
         if(job.manifest){
           await persistRange(job,index,payload.clip,async()=>{
             await appendMovieSegment(job,d.blob,d.frames,index);
             return job.segments[index];
           });
         }else await appendMovieSegment(job,d.blob,d.frames);
         if(token!==runToken)return;
         movieFrames+=d.frames;
         const expected=Math.round(payload.clip.seconds*rate(s.fps))*(s.mode==='2d'?1:2);
         if(d.frames<expected)movieDuration=movieFrames*movieFPS.den/movieFPS.num;
         log('Range '+movieParts+' saved to local storage: '+(d.blob.size/1e6).toFixed(2)+' MB, '+d.frames+' frames.');
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
   try{
     $('stage').textContent='Checking source file for saved ranges…';
     const job=navigator.locks&&crypto.subtle
       ? await openCheckpoint(file,s,{storage:navigator.storage,locks:navigator.locks,cancelled:()=>token!==runToken})
       : await createMovieJob();
     if(token===runToken){
       movieJob=job;
       if(job.manifest){$('cancel').textContent='Pause conversion';}
       else log('Saved range recovery is unavailable in this browser.');
       const savedGain=job.manifest?.media?.peakGain;
       startWorker('inspect',{type:'inspect',file,settings:s,measureAudio:true,cachedPeakGain:Number.isFinite(savedGain)?savedGain:undefined});
     }else if(job.manifest)await closeCheckpoint(job,false);
     else await cleanupMovieJob(job,false);
   }
   catch(err){if(token===runToken)fail('Cannot start long movie: '+(err.message||String(err)));}
 }else if(s.normalizeAudio||!item?.estimate?.known)startWorker('inspect',{type:'inspect',file,settings:s,measureAudio:true});
 else startWorker('convert',{type:'convert',file,settings:s});
};
$('report').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='MobiPEG-conversion-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);};
window.addEventListener('beforeunload',e=>{if(busy||queueRunning){e.preventDefault();e.returnValue='';}});document.addEventListener('visibilitychange',()=>{if(busy&&document.hidden)log('Tab backgrounded: this browser may pause or terminate conversion. Keep the tab visible.');});

$('inspectAudio').onclick=()=>{
  if(!file||busy)return;
  let s;try{s=settings();}catch(e){log(e.message);return;}
  const selected=file,w=new Worker('worker.js?v=20261118g');audioInspector=w;
  $('inspectAudio').disabled=true;
  const end=()=>{w.terminate();if(audioInspector===w)audioInspector=null;$('inspectAudio').disabled=busy;};
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
  w.postMessage({type:'inspect',file:selected,settings:s});
};

advancedPreview();

const sampleMode=document.createElement('label');
document.querySelector('.output-preview > .hint').textContent=
  'Compare the framed source with the MobiClip result at your chosen timestamp. Motion previews are silent. A size limit may change the final quantizer.';
sampleMode.className='hint';
sampleMode.innerHTML='<input id="sampleMotion" type="checkbox"> Motion preview (up to 2.5 seconds)';
$('makeSample').before(sampleMode);
const playback=document.createElement('div');
playback.className='sample-controls';
playback.hidden=true;
playback.innerHTML='<button id="samplePlay" class="text-button" type="button">Play preview</button><input id="sampleSeek" type="range" min="0" value="0" step="1" aria-label="Preview position">';
$('sampleResult').prepend(playback);
let sampleAnimation=0,sampleFrame=0;
function pauseSample(){
  cancelAnimationFrame(sampleAnimation);
  sampleAnimation=0;
  $('samplePlay').textContent='Play preview';
}
function invalidateSample(){pauseSample();sampleFrame=0;sampleData=null;playback.hidden=true;for(const id of ['originalFrame','decodedFrame']){$(id).width=0;$(id).height=0;}$('sampleResult').hidden=true;$('sampleStatus').textContent=file?'Settings changed. Generate a preview to see the result.':'Choose a video to preview your settings.';}
function endSample(){sampleWorker?.terminate();sampleWorker=null;$('cancelSample').hidden=true;lock(false);}
function drawSample(){
  if(!sampleData)return;const d=sampleData,bytes=d.width*d.height*4,eye=d.eyes===1?0:Number($('sampleEye').value);
  const offset=(sampleFrame*d.eyes+eye)*bytes;
  for(const [id,data]of [['originalFrame',d.original],['decodedFrame',d.decoded]]){
    const canvas=$(id);
    if(canvas.width!==d.width)canvas.width=d.width;
    if(canvas.height!==d.height)canvas.height=d.height;
    canvas.getContext('2d').putImageData(new ImageData(data.subarray(offset,offset+bytes),d.width,d.height),0,0);
  }
}
$('sampleMotion').onchange=invalidateSample;
$('sampleSeek').oninput=()=>{
  pauseSample();
  sampleFrame=Number($('sampleSeek').value);
  drawSample();
};
$('samplePlay').onclick=()=>{
  if(busy)return;
  if(sampleAnimation){pauseSample();return;}
  if(!(sampleData?.frames>1))return;
  const offset=sampleFrame,startedAt=performance.now();
  $('samplePlay').textContent='Pause preview';
  const tick=now=>{
    const frame=(offset+Math.floor((now-startedAt)*sampleData.previewFPS/1000))%sampleData.frames;
    if(frame!==sampleFrame){sampleFrame=frame;$('sampleSeek').value=String(frame);drawSample();}
    sampleAnimation=requestAnimationFrame(tick);
  };
  sampleAnimation=requestAnimationFrame(tick);
};
$('sampleEye').onchange=drawSample;
$('sampleStart').oninput=invalidateSample;
$('samplePosition').onclick=()=>{if(!busy){$('sampleStart').value=Number.isFinite($('preview').currentTime)?$('preview').currentTime.toFixed(3):'0';invalidateSample();}};
$('resetCrop').onclick=()=>{if(busy)return;$('fit').value='fit';$('aspect').value='source';for(const k of ['left','right','top','bottom'])$('crop-'+k).value='0';form.dispatchEvent(new Event('change'));};
$('cancelSample').onclick=()=>{sampleToken++;endSample();$('sampleStatus').textContent='Preview cancelled.';};
$('makeSample').onclick=()=>{
  if(!file||busy)return;let s,start;
  try{s=settings();start=Number($('sampleStart').value);if(!Number.isFinite(start)||start<0||Number.isFinite($('preview').duration)&&start>=$('preview').duration)throw Error('Choose a preview position within the video.');}
  catch(e){$('sampleStatus').textContent=e.message;return;}
  const motion=$('sampleMotion').checked;
  invalidateSample();lock(true);const token=++sampleToken;let w;
  try{w=new Worker('worker.js?v=20261118g');sampleWorker=w;}catch(e){$('sampleStatus').textContent='Preview failed: '+e.message;endSample();return;}
  $('cancelSample').hidden=false;$('sampleStatus').textContent='Loading preview encoder…';
  w.onerror=e=>{if(token===sampleToken){$('sampleStatus').textContent='Preview failed: '+e.message;endSample();}};
  w.onmessage=async({data:d})=>{
    if(token!==sampleToken||sampleWorker!==w)return;
    if(d.type==='status')$('sampleStatus').textContent=d.stage+'…';
    else if(d.type==='error'){$('sampleStatus').textContent='Preview failed: '+d.message;endSample();}
    else if(d.type==='preview'){
      try{
        const [original,decoded]=await Promise.all([d.original.arrayBuffer(),d.decoded.arrayBuffer()]);
        if(token!==sampleToken||sampleWorker!==w)return;
        sampleData={...d,original:new Uint8ClampedArray(original),decoded:new Uint8ClampedArray(decoded)};
        playback.hidden=!(d.frames>1);
        $('sampleSeek').max=String(Math.max(0,(d.frames??1)-1));
        $('sampleSeek').value='0';
        $('sampleEye').value='0';$('sampleEyeLabel').hidden=d.eyes===1;$('sampleResult').hidden=false;drawSample();
        $('sampleStatus').textContent=motion
          ? `${d.frames} preview frames · Q${d.q} · ${start.toFixed(3)} s · Silent motion comparison`
          : `${d.width} × ${d.height} per eye · Q${d.q} · ${start.toFixed(3)} s · real MobiClip frame. Not a complete-file or hardware verification.`;
      }catch(e){$('sampleStatus').textContent='Preview failed: '+e.message;}
      finally{if(token===sampleToken)endSample();}
    }
  };
  w.postMessage({type:'preview',file,settings:s,start,motion});
};

initLanguage();
refreshSavedJobs();
try{
  const restored=loadQueue(validate);
  if(restored.length){
    queue=restored.map((entry,index)=>({...entry,id:index+1}));
    nextQueueId=queue.length+1;
    $('queueRestoreStatus').textContent='Saved queue restored. Reselect original videos to resume unfinished jobs; source videos were not stored.';
    refreshEstimates();
  }
}catch(error){
  queueRestoreError=true;$('discardSavedQueue').hidden=false;
  $('queueRestoreStatus').textContent='Saved queue could not be restored. Its data has been kept in this browser; new queue changes cannot be saved until you discard it. '+(error.message||String(error));
  console.warn('Batch queue restore failed:',error);
}
queueRestored=true;
renderQueue();

function showAlert(message){alert(translateText(message));}
function askConfirm(message){return confirm(translateText(message));}
