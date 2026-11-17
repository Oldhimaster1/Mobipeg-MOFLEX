// Regenerate both deployment manifests after editing any shipped web files.
import {createHash} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const common=['index.html','player.html','guide.html','app.mjs','core.mjs','movie.mjs','parallel.mjs',
  'queue.mjs','checkpoints.mjs','i18n.mjs','translations.mjs','queue-translations.mjs','usage.mjs',
  'worker.js','player-worker.js','player.mjs','player-core.mjs','super-moflex.mjs','trailer-editor.mjs',
  'batch-output.mjs','style.css','player.css',
  'isolation.js','manifest.webmanifest','icon-192.png','icon-512.png','Aligned_Source_Native_WASM.png',
  'engine/mobipeg.js','engine/mobipeg.wasm','engine-simd/mobipeg.js','engine-simd/mobipeg.wasm'];
const worker=await readFile('isolation-sw.js','utf8');
const version=/const VERSION = '([^']+)'/.exec(worker)?.[1];
if(!version)throw Error('Missing offline release version');
for(const root of ['.','dist']){
  const paths=[...common,...(root==='.'?['dist/translations.mjs','dist/queue-translations.mjs']:[])];
  const files={};
  for(const name of paths)files[name]=createHash('sha256').update(await readFile(join(root,name))).digest('hex');
  await writeFile(join(root,'offline-assets.json'),JSON.stringify({version,files},null,2)+'\n');
}
