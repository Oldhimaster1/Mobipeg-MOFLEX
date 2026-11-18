import {stageCia,ciaOutputDirectory} from './cia-output.mjs?v=20261118e';
import {buildCia} from './cia-packager.mjs?v=20261118e';
import {createCiaProject,ciaSizeEstimate,MAX_CIA_MOVIES,planCiaParts} from './cia-project.mjs?v=20261118e';
import {readSuperMoflex} from './super-moflex.mjs?v=20261117r';
import {inspectPlayableMoflex} from './player-core.mjs?v=20261117s';

const $=id=>document.getElementById(id);
const episodes=[];
const bytes=n=>n<1e6?(n/1000).toFixed(1)+' KB':(n/1e6).toFixed(2)+' MB';
const setStatus=(message,error=false)=>{
  $('ciaStatus').textContent=message;
  $('ciaStatus').style.color=error?'#9a2c23':'';
};
function render(){
  const rows=$('ciaEpisodes');rows.replaceChildren();
  for(const [index,entry] of episodes.entries()){
    const row=document.createElement('li'),name=document.createElement('strong');
    name.textContent=entry.file.name;
    const details=document.createElement('p');details.className='hint';
    details.textContent=entry.info?entry.info.eyeWidth+' × '+entry.info.eyeHeight+
      ' per eye · '+entry.info.duration.toFixed(1)+' seconds · '+bytes(entry.mediaBytes)
      +(entry.hasExtras?' · SUPER MOFLEX extras stripped for CIA':''):'Inspecting…';
    const controls=document.createElement('div');controls.className='cia-episode-row';
    const label=document.createElement('label');label.textContent='Menu title ';
    const input=document.createElement('input');input.value=entry.title;input.maxLength=127;
    input.setAttribute('aria-label','Episode '+(index+1)+' title');
    input.addEventListener('input',()=>entry.title=input.value);
    label.append(input);controls.append(label);
    const bannerLabel=document.createElement('label');bannerLabel.textContent='Episode banner ';
    const banner=document.createElement('input');banner.type='file';banner.accept='.png,.bmp,.jpg,.jpeg,.bimg';
    banner.setAttribute('aria-label','Episode '+(index+1)+' banner');
    banner.onchange=()=>{entry.banner=banner.files[0]?.name??null;entry.bannerFile=banner.files[0]??null;};
    bannerLabel.append(banner);controls.append(bannerLabel);
    const btn=(name,action,disabled=false)=>{
      const b=document.createElement('button');b.type='button';b.className='text-button';
      b.textContent=name;b.disabled=disabled;b.onclick=action;controls.append(b);
    };
    btn('↑',()=>{[episodes[index-1],episodes[index]]=[episodes[index],episodes[index-1]];render();},index===0);
    btn('↓',()=>{[episodes[index],episodes[index+1]]=[episodes[index+1],episodes[index]];render();},index===episodes.length-1);
    btn('Remove',()=>{episodes.splice(index,1);render();});
    row.append(name,details,controls);rows.append(row);
  }
  try{
    if(episodes.length){
      const estimate=ciaSizeEstimate(episodes.map(x=>({size:x.mediaBytes})));
      $('ciaFilesStatus').textContent=episodes.length+' of '+MAX_CIA_MOVIES+
        ' movies · '+bytes(estimate.bytes)+' primary video payload. Packaging adds overhead.';
    }else $('ciaFilesStatus').textContent='Choose 1–27 MOFLEX files, then arrange their order.';
  }catch(e){$('ciaFilesStatus').textContent=e.message;}
}
$('ciaFiles').addEventListener('change',async e=>{
  const selected=[...e.target.files];e.target.value='';
  for(const file of selected){
    if(episodes.length>=MAX_CIA_MOVIES){setStatus('Maximum 27 movies per project.',true);break;}
    if(episodes.some(x=>x.file.name.toLowerCase()===file.name.toLowerCase())){
      setStatus('Duplicate filename: '+file.name,true);continue;
    }
    if(!/\.moflex$/i.test(file.name)){setStatus('Use a .moflex file: '+file.name,true);continue;}
    $('ciaFilesStatus').textContent='Inspecting '+file.name+' locally…';
    try{
      const trailer=await readSuperMoflex(file);
      const info=await inspectPlayableMoflex(trailer.media);
      const title=trailer.metadata?.title?.trim()||file.name.replace(/\.moflex$/i,'');
      episodes.push({file,info,mediaBytes:trailer.media.size,hasExtras:trailer.media.size!==file.size,title:title.slice(0,127)});
      if(!$('ciaTitle').value)$('ciaTitle').value=title.slice(0,63);
      setStatus('Video inspected. Arrange the list, then export the project.');
    }catch(error){setStatus('Could not inspect '+file.name+': '+(error.message||String(error)),true);}
    render();
  }
});
$('ciaForm').addEventListener('submit',event=>{
  event.preventDefault();
  try{
    const data=createCiaProject({title:$('ciaTitle').value,longTitle:$('ciaLongTitle').value,
      publisher:$('ciaPublisher').value,id:$('ciaId').value,
      movies:episodes.map(item=>({file:item.file.name,title:item.title,...(item.banner?{banner:item.banner}:{})})),
      icon:$('ciaIcon').files[0]?.name,banner:$('ciaBanner').files[0]?.name});
    ciaSizeEstimate(episodes.map(item=>({size:item.mediaBytes})));
    const content=new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'});
    const url=URL.createObjectURL(content);
    const link=document.createElement('a');link.href=url;link.download='project.json';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    setStatus('CIA project saved. Copy this JSON, the MOFLEX files and selected artwork into one folder to build a CIA.');
  }catch(error){setStatus(error.message||String(error),true);}
});
render();

$('ciaBuild').onclick=async()=>{
  const button=$('ciaBuild');button.disabled=true;
  try{
    const template=$('ciaTemplate').files[0];
    if(!template)throw Error('Select a local compatible player CIA template.');
    const icon=$('ciaIcon').files[0],banner=$('ciaBanner').files[0];
    if(icon&&!/\.(smdh|png|bmp|jpe?g)$/i.test(icon.name))throw Error('Choose a PNG, BMP, JPG or SMDH icon.');
    if(banner&&!/\.(bin|bnr|png|bmp|jpe?g)$/i.test(banner.name))throw Error('Choose a PNG, BMP, JPG or prepared banner.');
    if(episodes.some(e=>e.bannerFile&&!/\.(bimg|png|bmp|jpe?g)$/i.test(e.bannerFile.name)))throw Error('Choose a PNG, BMP, JPG or BIMG episode thumbnail.');
    const project=createCiaProject({title:$('ciaTitle').value,longTitle:$('ciaLongTitle').value,
      publisher:$('ciaPublisher').value,id:$('ciaId').value,
      movies:episodes.map(e=>({file:e.file.name,title:e.title}))});
    const movies=[];for(const episode of episodes)movies.push((await readSuperMoflex(episode.file)).media);
    const groups=planCiaParts(movies.map(movie=>movie.size),template.size,project.id,$('ciaSplit').checked);
    const firstId=parseInt(project.id,16);
    for(const [part,indices] of groups.entries()){
      const partProject={...project,id:(firstId+part).toString(16).toUpperCase(),movies:indices.map(i=>project.movies[i])};
      let result=await buildCia({template,project:partProject,movies:indices.map(i=>movies[i]),icon,banner,bannerAudio:$('ciaBannerAudio').files[0],episodeBanners:indices.map(i=>episodes[i].bannerFile),onProgress:message=>setStatus('Part '+(part+1)+' of '+groups.length+' · '+message)});
      if($('ciaStage').checked){setStatus('Saving CIA in private browser storage');result=await stageCia(result);await showSavedCias();}
      const url=URL.createObjectURL(result),link=document.createElement('a');link.href=url;link.download=groups.length>1?'collection-'+(part+1)+'.cia':'movie.cia';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
    }
    setStatus('CIA built and content hash verified. Installation and playback require console testing.');
  }catch(error){setStatus(error.message||String(error),true);}
  finally{button.disabled=false;}
};

async function showSavedCias(){
  const list=$('ciaSaved');list.replaceChildren();
  try{
    const directory=await ciaOutputDirectory();
    for await(const [name,handle] of directory.entries()){
      if(handle.kind!=='file'||!name.endsWith('.cia'))continue;
      const row=document.createElement('p'),download=document.createElement('button'),remove=document.createElement('button');
      download.type=remove.type='button';download.textContent='Download '+name;remove.textContent='Delete';
      download.onclick=async()=>{const url=URL.createObjectURL(await handle.getFile()),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);};
      remove.onclick=async()=>{if(confirm('Delete this browser-saved CIA?')){await directory.removeEntry(name);await showSavedCias();}};
      row.append(download,remove);list.append(row);
    }
  }catch(error){if(error.name!=='NotFoundError')list.textContent='Saved CIA storage is unavailable: '+error.message;}
}
$('ciaStage').disabled=!navigator.storage?.getDirectory;
showSavedCias();
