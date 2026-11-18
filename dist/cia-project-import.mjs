import {createCiaProject,safeCiaFileName} from './cia-project.mjs?v=20261118g';

// Reopening deliberately requires local files again: JSON never contains media.
export function parseCiaProject(text){
  if(typeof text!=='string'||text.length>1024*1024)throw Error('Project JSON exceeds 1 MiB.');
  const input=JSON.parse(text);
  if(!input||input.version!==1)throw Error('Unsupported CIA project version.');
  const project=createCiaProject({...input,longTitle:input.long_title});
  const browser=input.browser??{};
  if(browser.bannerAudio)project.browser={bannerAudio:safeCiaFileName(browser.bannerAudio)};
  if(browser.split===true)project.browser={...project.browser,split:true};
  return project;
}

export function resolveCiaProjectFiles(project,files){
  const index=new Map();
  for(const file of files){
    const key=file.name.toLowerCase();
    if(index.has(key))throw Error('Ambiguous local filename: '+file.name);
    index.set(key,file);
  }
  const required=[...project.movies.flatMap(m=>[m.file,m.banner]),project.icon,project.banner,project.browser?.bannerAudio].filter(Boolean);
  const missing=[...new Set(required.filter(name=>!index.has(name.toLowerCase())))];
  if(missing.length)throw Error('Select the missing project files: '+missing.join(', '));
  const get=name=>name?index.get(name.toLowerCase()):undefined;
  return {movies:project.movies.map(movie=>({file:get(movie.file),bannerFile:get(movie.banner)})),
    icon:get(project.icon),banner:get(project.banner),bannerAudio:get(project.browser?.bannerAudio)};
}
