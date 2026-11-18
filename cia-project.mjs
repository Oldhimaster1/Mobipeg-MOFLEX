// Browser/native shared CIA project schema. This file does not produce a CIA.
export const MAX_CIA_MOVIES=27;
export const FAT32_CIA=0xffffffff;
export function ciaTitleID(code){
  if(typeof code!=='string'||! /^[c-e][0-9a-f]{4}$/i.test(code))
    throw Error('Title ID must be five hexadecimal digits from C0000 through EFFFF.');
  return '00040000'+((parseInt(code,16)*256)>>>0).toString(16).padStart(8,'0').toUpperCase();
}
export function safeCiaFileName(name){
  if(typeof name!=='string'||!name||name==='.'||name==='..'||name.length>200||
    /[\\/:*?"<>|\x00-\x1f]/.test(name)||/^\s|\s$/.test(name))
    throw Error('Every file must have a safe name without folders, slashes or control characters.');
  return name;
}
function title(value,label,max){
  if(typeof value!=='string'||!value.trim()||value.length>256||
    Array.from(value).some(ch=>ch.codePointAt(0)<32)||
    new TextEncoder().encode(value).byteLength>512||
    [...value].length>max)
    throw Error(label+' must contain 1–'+max+' characters on one line.');
  // Match the native project's UTF-16 code unit requirement.
  if(value.length>max)throw Error(label+' is too long for the 3DS title field.');
  return value.trim();
}
export function createCiaProject({title:projectTitle,longTitle='',publisher='MobiPEG',
    id,movies,icon=null,banner=null,reservedTitleIds=[]}){
  if(!Array.isArray(movies)||movies.length<1||movies.length>MAX_CIA_MOVIES)
    throw Error('Choose 1–27 MOFLEX movies or episodes.');
  const identifier=String(id??'').toUpperCase();
  const fullId=ciaTitleID(identifier);
  if(reservedTitleIds.some(x=>String(x).toUpperCase()===identifier||String(x).toUpperCase()===fullId))
    throw Error('This title ID is already in use.');
  const used=new Set(),list=[];
  for(const movie of movies){
    if(!movie||typeof movie!=='object')throw Error('Invalid movie entry.');
    const path=safeCiaFileName(movie.file);
    if(!/\.moflex$/i.test(path))throw Error('CIA movie inputs must be .moflex files.');
    if(used.has(path.toLowerCase()))throw Error('Duplicate movie filename: '+path);
    used.add(path.toLowerCase());
    list.push({file:path,...(movie.title?{title:title(movie.title,'Episode title',127)}:{}),...(movie.banner?{banner:safeCiaFileName(movie.banner)}:{})});
  }
  const data={version:1,title:title(projectTitle,'CIA title',63),
    publisher:title(publisher,'Publisher',63),id:identifier,movies:list};
  if(longTitle)data.long_title=title(longTitle,'Long title',127);
  for(const [key,value] of [['icon',icon],['banner',banner]])if(value){
    const name=safeCiaFileName(value);
    if(!/\.(png|bmp|bnr|smdh)$/i.test(name))
      throw Error('Unsupported '+key+' file format.');
    data[key]=name;
  }
  return data;
}
export function ciaSizeEstimate(files){
  if(!Array.isArray(files))throw Error('Invalid video sizes.');
  const bytes=files.reduce((n,item)=>{
    if(!Number.isSafeInteger(item?.size)||item.size<0)throw Error('Invalid video sizes.');
    return n+item.size;
  },0);
  if(!Number.isSafeInteger(bytes)||bytes<0)throw Error('Invalid video sizes.');
  if(bytes>=FAT32_CIA)throw Error('MOFLEX payloads alone exceed the FAT32 limit. Split into multiple CIAs.');
  return {bytes,headroom:FAT32_CIA-bytes,needsPackingOverhead:true};
}
