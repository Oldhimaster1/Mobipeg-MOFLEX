import {languageHeader, metadataSection, readSuperMoflex, writeSuperMoflex} from './super-moflex.mjs?v=20261117r';
import {shiftSubtitleTiming} from './subtitle-timing.mjs?v=20261117t';

const fields={title:'Movie or series title',year:'Release year',genres:'Genres',category:'Category',
  runtime:'Runtime (minutes)',date:'Release date',desc:'Movie or episode synopsis',showdesc:'Series synopsis',
  season:'Season number',episode:'Episode number',episode_title:'Episode title'};
const byId=id=>document.getElementById(id);

async function posterBody(file){
  const image=await createImageBitmap(file);
  const canvas=document.createElement('canvas');
  canvas.width=132;canvas.height=188;
  const context=canvas.getContext('2d');
  context.drawImage(image,0,0,132,188);
  image.close();
  const rgba=context.getImageData(0,0,132,188).data;
  const result=new DataView(new ArrayBuffer(4+132*188*2));
  result.setUint16(0,132,true);result.setUint16(2,188,true);
  for(let i=0;i<rgba.length;i+=4)
    result.setUint16(4+i/2,((rgba[i]>>3)<<11)|((rgba[i+1]>>2)<<5)|(rgba[i+2]>>3),true);
  return new Blob([result.buffer]);
}

async function alternateBody(file, language, duration, update){
  const samples=Math.ceil(duration*48000/256)*256;
  if(samples/256*264>128*1048576)throw Error('The alternate track is too large for browser editing. Use the desktop editor for this movie.');
  const header=new DataView(new ArrayBuffer(12));
  header.setUint32(0,48000,true);header.setUint16(4,2,true);header.setUint16(6,256,true);
  new Uint8Array(header.buffer,8).set(languageHeader(language));
  const parts=[header.buffer];
  const worker=new Worker('player-worker.js?v=20261118w');
  try{
    for(let at=0;at<samples;at+=1048576){
      update('Encoding alternate audio… '+Math.floor(100*at/samples)+'%');
      const count=Math.min(1048576,samples-at);
      const buffer=await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>reject(Error('The alternate audio encoder stopped responding.')),120000);
        worker.onerror=event=>{
          clearTimeout(timer);
          reject(Error(event.message||'Alternate audio worker failed'));
        };
        worker.onmessage=({data})=>{
          clearTimeout(timer);
          if(data.type==='error')reject(Error(data.message));
          else resolve(data.buffer);
        };
        worker.postMessage({type:'trailerAudio',file,start:at/48000,samples:count,request:at});
      });
      parts.push(new Blob([buffer]));
    }
    return new Blob(parts);
  }finally{worker.terminate();}
}

export function openTrailerEditor(file, original, duration){
  const form=byId('trailerForm'), controls=byId('metadataFields'), existing=byId('existingSubtitles');
  form.reset();
  controls.replaceChildren();
  for(const [key,name] of Object.entries(fields)){
    const label=document.createElement('label');
    const input=document.createElement(key==='desc'||key==='showdesc'?'textarea':'input');
    input.name=key;
    input.value=original.metadata[key]??'';
    label.append(name,input);
    controls.append(label);
  }
  const toRemove=new Set(),existingEdits=[];
  existing.replaceChildren();
  for(const track of original.subtitles){
    const removeLabel=document.createElement('label'),check=document.createElement('input');
    check.type='checkbox';
    check.onchange=()=>check.checked?toRemove.add(track.section):toRemove.delete(track.section);
    removeLabel.append(check,' Remove '+track.language+' subtitles');
    const languageLabel=document.createElement('label'),language=document.createElement('input');
    language.maxLength=3;language.required=true;language.value=track.language||'SUB';
    languageLabel.append('Subtitle language',language);
    const offsetLabel=document.createElement('label'),offset=document.createElement('input');
    offset.type='number';offset.min='-300000';offset.max='300000';offset.step='1';offset.value='0';
    offsetLabel.append('Timing offset (ms)',offset);
    existing.append(removeLabel,languageLabel,offsetLabel);
    existingEdits.push({track,language,offset});
  }
  byId('trailerMainLanguage').value=original.primaryLanguage??'';
  byId('removeAltAudio').hidden=!original.alternateAudio;
  byId('removePoster').hidden=!original.poster;
  byId('trailerEditor').hidden=false;
  const subtitleFiles=byId('newSubtitles'), list=byId('newSubtitleLanguages');
  let tracks=[];
  list.replaceChildren();
  subtitleFiles.onchange=()=>{
    tracks=[];
    list.replaceChildren();
    for(const subtitle of subtitleFiles.files){
      const label=document.createElement('label'), input=document.createElement('input');
      input.required=true;input.maxLength=3;
      input.value=/\.([a-z]{2,3})\.(srt|ass|ssa)$/i.exec(subtitle.name)?.[1]?.toUpperCase()??'SUB';
      label.append(subtitle.name+' language',input);
      const offsetLabel=document.createElement('label'),offset=document.createElement('input');
      offset.type='number';offset.min='-300000';offset.max='300000';offset.step='1';offset.value='0';
      offsetLabel.append('Timing offset (ms)',offset);
      list.append(label,offsetLabel);
      tracks.push({file:subtitle,language:input,offset});
    }
  };
  const status=byId('trailerStatus');
  status.textContent='';
  form.onsubmit=async event=>{
    event.preventDefault();
    if(!form.reportValidity())return;
    const remove=new Set(toRemove), additions=[];
    const removeTags=tags=>original.sections.filter(section=>tags.includes(section.tag)).forEach(section=>remove.add(section));
    const update=text=>{status.textContent=text;};
    const values=new FormData(form);
    const poster=byId('newPoster').files[0], alternate=byId('newAltAudio').files[0];
    const mainLanguage=byId('trailerMainLanguage').value.trim();
    const langs=tracks.map(track=>[track.file,track.language.value,Number(track.offset.value)]);
    const save=byId('writeTrailer');
    save.disabled=true;
    byId('movieFile').disabled=true;
    try{
      const metadata={...original.metadata};
      for(const key of Object.keys(fields)){
        const value=String(values.get(key)??'').trim().replace(/\r?\n/g,' ');
        if(value)metadata[key]=value;else delete metadata[key];
      }
      removeTags(['NFO0','LNG0']);
      for(const {track,language,offset} of existingEdits){
        if(remove.has(track.section))continue;
        const label=language.value.trim(),milliseconds=Number(offset.value);
        languageHeader(label);
        if(label.toUpperCase()===track.language.toUpperCase()&&!milliseconds)continue;
        remove.add(track.section);
        additions.push({tag:'SUB1',body:new Blob([
          languageHeader(label),shiftSubtitleTiming(await track.text.text(),milliseconds)])});
      }
      if(Object.keys(metadata).length)additions.push({tag:'NFO0',body:new Blob([metadataSection(metadata)])});
      if(mainLanguage)additions.push({tag:'LNG0',body:new Blob([languageHeader(mainLanguage)])});
      for(const [subtitle,language,offset] of langs){
        if(!/\.(srt|ass|ssa)$/i.test(subtitle.name)||!subtitle.size||subtitle.size>1048576)
          throw Error('Choose a nonempty SRT, ASS or SSA file under 1 MiB.');
        const text=shiftSubtitleTiming(await subtitle.text(),offset);
        additions.push({tag:'SUB1',body:new Blob([languageHeader(language),text])});
      }
      if(poster||values.has('removePoster'))removeTags(['ART5']);
      if(poster)additions.push({tag:'ART5',body:await posterBody(poster)});
      if(alternate||values.has('removeAltAudio'))removeTags(['AUD0','AUD1']);
      if(alternate)additions.push({tag:'AUD1',body:await alternateBody(alternate,
        String(values.get('alternateLanguage')??'').trim(),duration,update)});
      const result=writeSuperMoflex(original,additions,remove);
      await readSuperMoflex(result);
      const url=URL.createObjectURL(result), link=document.createElement('a');
      link.href=url;link.download=file.name.replace(/\.moflex$/i,'')+'-edited.moflex';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      update('Edited file ready. The original movie stream was preserved.');
    }catch(error){update(error.message||String(error));}
    finally{save.disabled=false;byId('movieFile').disabled=false;}
  };
}
