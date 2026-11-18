import rows from './translations.mjs?v=20261117e';
import queueRows from './queue-translations.mjs?v=20261117f';
import studioRows from './studio-translations.mjs?v=20261118u';
export const LANGUAGES=['en','es','fr','de','pt','ja','ko','zh-Hans'];
const entries=new Map([...rows,...queueRows,...studioRows].map(row=>[row[0],row]));
const KEY='mobipeg-interface-language';
let language='en';
export function normalizeLanguage(value){
 const code=String(value??'').toLowerCase();
 if(/^zh(?:$|-cn$|-sg$|-hans(?:-|$))/.test(code))return 'zh-Hans';
 const base=code.split('-')[0];return LANGUAGES.includes(base)?base:'en';
}
export function translateText(text,locale=language){
 const index=LANGUAGES.indexOf(locale);if(index<=0)return text;
 const lookup=key=>entries.get(key)?.[index]??key;
 const raw=String(text),value=raw.trim();let result=lookup(value);
 if(result===value){
  if(value.endsWith('…'))result=lookup(value.slice(0,-1))+'…';
  if(/^(\d+x\d+|\d+(?:\.\d+)? fps) · experimental$/.test(value))result=value.replace('experimental',lookup('experimental'));
  else if(/^\d+:\d+ elapsed$/.test(value))result=value.replace('elapsed',lookup('elapsed'));
  else if(/^~\d+:\d+ left in stage$/.test(value))result=value.replace('left in stage',lookup('left in stage'));
  else if(/^True 3D · layout [01] · /.test(value))result=value.replace(/True 3D · layout [01]/,key=>lookup(key)).replace('coded eye frames/sec',lookup('coded eye frames/sec'));
  else if(/^\d+ × \d+ per eye · /.test(value))result=value.replace('per eye',lookup('per eye')).replace('real MobiClip frame. Not a complete-file or hardware verification.',lookup('real MobiClip frame. Not a complete-file or hardware verification.'));
  else if(/^\d+ \/ \d+ logical cores$/.test(value))result=value.replace('logical cores',lookup('logical cores'));
  else if(/^Encoding(?: · .*| · Q\d+)$/.test(value))result=value.replace(/^Encoding/,lookup('Encoding'));
  else if(/^LONG MOVIE · CHAPTER \d+$/.test(value))result=value.replace('LONG MOVIE · CHAPTER',lookup('LONG MOVIE · CHAPTER'));
  else if(/^Assembling movie · chapter \d+\/\d+$/.test(value))result=value.replace('Assembling movie · chapter',lookup('Assembling movie · chapter'));
  else if(/^\d.* MB · .* coded frames · Q/.test(value)){result=value;for(const key of ['coded frames','FastAudio audio','ADPCM audio','No audio','3DS >71 min seek behavior unverified','UNVERIFIED'])result=result.replace(key,lookup(key));}
  else if(value.startsWith('Preview failed:'))result=value.replace('Preview failed:',lookup('Preview failed:'));
 }
 return raw.slice(0,raw.indexOf(value))+result+raw.slice(raw.indexOf(value)+value.length);
}
export function initLanguage(doc=document,env=globalThis){
 let preferred;try{preferred=env.localStorage.getItem(KEY);}catch{}
 language=normalizeLanguage(preferred||env.navigator.language);
 const select=doc.getElementById('interfaceLanguage'),originals=new WeakMap(),attributes=new WeakMap();
 const excluded='script,style,pre,code,noscript,#filename,#filesize,#audioTrack,#interfaceLanguage';
 function textNode(node){
  if(!node.parentElement||node.parentElement.closest(excluded))return;
  const previous=originals.get(node),original=previous&&node.data===previous.rendered?previous.original:node.data;
  const rendered=translateText(original);originals.set(node,{original,rendered});
  if(node.data!==rendered)node.data=rendered;
 }
 function apply(root){
  if(root.nodeType===3)return textNode(root);
  if(root.nodeType!==1||root.closest(excluded))return;
  const walker=doc.createTreeWalker(root,4);let node;
  while(node=walker.nextNode())textNode(node);
  for(const el of [root,...root.querySelectorAll('[aria-label],[placeholder],[title]')]){
   if(el.closest('#filename,#audioTrack'))continue;
   let memo=attributes.get(el);if(!memo){memo=new Map();attributes.set(el,memo);}
   for(const name of ['aria-label','placeholder','title'])if(el.hasAttribute(name)){
    const value=el.getAttribute(name),old=memo.get(name),original=old&&value===old.rendered?old.original:value,rendered=translateText(original);
    memo.set(name,{original,rendered});if(value!==rendered)el.setAttribute(name,rendered);
   }
  }
 }
 const setLanguage=value=>{
  language=normalizeLanguage(value);doc.documentElement.lang=language;select.value=language;
  try{env.localStorage.setItem(KEY,language);}catch{}
  apply(doc.body);
 };
 select.addEventListener('change',()=>setLanguage(select.value));
 setLanguage(language);
 // Translate only changed nodes, not the entire interface on each progress tick.
 const observer=new MutationObserver(records=>{
  for(const record of records){
   if(record.type==='characterData')textNode(record.target);
   else for(const node of record.addedNodes)if(node.isConnected)apply(node);
  }
 });
 observer.observe(doc.body,{subtree:true,childList:true,characterData:true});
 return {setLanguage,disconnect:()=>observer.disconnect()};
}
