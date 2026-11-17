// Local-only, versioned queue manifest; never stores source video contents.
export const QUEUE_STORAGE_KEY='mobipeg-batch-queue-v1';
const VERSION=1,MAX_ITEMS=200;
function validSource(s){
  if(!s||typeof s!=='object'||Array.isArray(s)||typeof s.name!=='string'||!s.name||
    s.name.length>512||!Number.isSafeInteger(s.size)||s.size<0||
    !Number.isSafeInteger(s.lastModified)||s.lastModified<0)return null;
  return {name:s.name,size:s.size,lastModified:s.lastModified,
    type:typeof s.type==='string'?s.type.slice(0,128):''};
}
export function sourceIdentity(f){
  return validSource({name:f?.name,size:f?.size,lastModified:f?.lastModified??0,type:f?.type??''});
}
export function sameSource(expected,file){
  const a=validSource(expected),b=sourceIdentity(file);
  return !!a&&!!b&&a.name===b.name&&a.size===b.size&&
    (!a.lastModified||!b.lastModified||a.lastModified===b.lastModified);
}
export function serializeQueue(items){
  if(!Array.isArray(items)||items.length>MAX_ITEMS)throw Error('Queue is too large to save.');
  const entries=items.map(item=>{
    const source=validSource(item.source??sourceIdentity(item.file));
    if(!source)throw Error('Cannot save a queue item without valid source details.');
    return {source,settings:structuredClone(item.settings),
      duration:Number.isFinite(item.duration)&&item.duration>0?item.duration:null,
      audio:item.audio!==false,status:item.status==='done'?'done':'needs-file'};
  });
  return JSON.stringify({version:VERSION,items:entries});
}
export function restoreQueue(raw,validateSettings){
  if(!raw)return [];
  const m=JSON.parse(raw);
  if(!m||m.version!==VERSION||!Array.isArray(m.items)||m.items.length>MAX_ITEMS)
    throw Error('Unsupported or invalid saved queue.');
  return m.items.map(entry=>{
    if(!entry||typeof entry!=='object'||!validSource(entry.source))
      throw Error('Saved queue contains invalid source information.');
    return {source:validSource(entry.source),settings:validateSettings(structuredClone(entry.settings)),
      duration:Number.isFinite(entry.duration)&&entry.duration>0?entry.duration:null,
      audio:entry.audio!==false,status:entry.status==='done'?'done':'needs-file',file:null,estimate:null};
  });
}
export function relinkQueue(items,files){
  const linked=[],unmatched=[];
  for(const file of files){
    const item=items.find(entry=>entry.status==='needs-file'&&!entry.file&&sameSource(entry.source,file));
    if(!item){unmatched.push(file);continue;}
    item.file=file;item.status='pending';linked.push(item);
  }
  return {linked,unmatched};
}
export function saveQueue(items,storage=globalThis.localStorage){
  storage.setItem(QUEUE_STORAGE_KEY,serializeQueue(items));
}
export function loadQueue(validateSettings,storage=globalThis.localStorage){
  return restoreQueue(storage.getItem(QUEUE_STORAGE_KEY),validateSettings);
}
export function clearSavedQueue(storage=globalThis.localStorage){
  storage.removeItem(QUEUE_STORAGE_KEY);
}
