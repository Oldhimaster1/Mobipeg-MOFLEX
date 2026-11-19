// Regenerate both deployment manifests after editing any shipped web files.
import {createHash} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const common=['index.html','player.html','guide.html','cia.html','cia.mjs','cia-project.mjs','cia-project-import.mjs','cia-packager.mjs','cia-vidinjector-template.mjs','cia-design.mjs','cia-design.css','cia-sha256.mjs','cia-sha256-wasm.mjs','cia-sha256-core.wasm','cia-romfs.mjs','cia-artwork.mjs','cia-output.mjs','cia-banner.mjs','cia-banner-audio.mjs','hdr-lut.mjs','app.mjs','core.mjs','complexity.mjs','movie.mjs','parallel.mjs',
  'queue.mjs','checkpoints.mjs','checkpoint-manager.mjs','i18n.mjs','studio-translations.mjs','translations.mjs','queue-translations.mjs','usage.mjs',
  'worker.js','wasm-runtime.mjs','player-worker.js','player.mjs','player-core.mjs','super-moflex.mjs','trailer-editor.mjs','subtitle-timing.mjs',
  'batch-output.mjs','queue-state.mjs','style.css','player.css',
  'isolation.js','manifest.webmanifest','icon-192.png','icon-512.png','Aligned_Source_Native_WASM.png',
  'engine/mobipeg.js','engine/mobipeg.wasm','engine-simd/mobipeg.js','engine-simd/mobipeg.wasm'];
const worker=await readFile('isolation-sw.js','utf8');
const version=/const VERSION = '([^']+)'/.exec(worker)?.[1];
if(!version)throw Error('Missing offline release version');
for(const root of ['.','dist']){
  const page=join(root,'index.html'),html=await readFile(page,'utf8');
  if(!html.includes('id="studioRelease"'))throw Error('Missing Studio release label');
  const stamp=version.replace(/^(\d{4})(\d{2})(\d{2})(.*)$/,'$1.$2.$3$4');
  const updated=html.replace(/(<span id="studioRelease">)[^<]*(<\/span>)/,(_,start,end)=>start+stamp+end);
  if(updated!==html)await writeFile(page,updated);
  const paths=[...common,...(root==='.'?['dist/translations.mjs','dist/queue-translations.mjs']:[])];
  const files={};
  for(const name of paths)files[name]=createHash('sha256').update(await readFile(join(root,name))).digest('hex');
  await writeFile(join(root,'offline-assets.json'),JSON.stringify({version,files},null,2)+'\n');
}
