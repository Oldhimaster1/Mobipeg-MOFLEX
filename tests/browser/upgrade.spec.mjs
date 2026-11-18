import {expect,test} from '@playwright/test';
import {execFileSync,spawn} from 'node:child_process';
import {once} from 'node:events';
import {copyFileSync,mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

let work,source,movie;
test.beforeAll(()=>{
  work=mkdtempSync(join(tmpdir(),'mobipeg-upgrade-'));
  source=join(work,'source.mkv');movie=join(work,'source.moflex');
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=red:s=320x240:r=24:d=2',
    '-f','lavfi','-i','sine=f=880:r=48000:d=2','-c:v','ffv1','-c:a','pcm_s16le',source]);
  // Use the same checked-in WASM engine as the browser. A developer should not
  // need an untracked native/local/bin/ffmpeg build to run browser regressions.
  const run=(name,args,files,output,destination)=>{
    const spec={args,files,env:{MOBI_SUBME:'7',MOBI_SKIP:'0'},output,
      destination,result:join(work,name+'-result.json')};
    const manifest=join(work,name+'-command.json');
    writeFileSync(manifest,JSON.stringify(spec));
    execFileSync(process.execPath,['tests/wasm-command.cjs',manifest],{timeout:180000,
      env:{...process.env,MOBIPEG_ENGINE_DIR:resolve('dist/engine')},maxBuffer:2*1024*1024});
    const result=JSON.parse(readFileSync(spec.result));
    if(result.code!==0)throw Error('WASM fixture creation failed: '+result.log.slice(-1200));
  };
  const encoded=join(work,'video-only.moflex');
  run('encode',['-hide_banner','-nostdin','-v','error','-y','-i','/input/source',
    '-vf','fps=24,scale=320:240,format=yuv420p','-an','-c:v','mobiclip',
    '-mobiclip','1','-qp','12','-mobi_qyx','3','-preset','medium',
    '-me_method','hex','-g','48','-mo_layout','6','-f','moflex','/video.moflex'],
    {source},'/video.moflex',encoded);
  run('mux',['-hide_banner','-nostdin','-v','error','-y',
    '-i','/input/video','-i','/input/source','-map','0:v:0','-map','1:a:0',
    '-c:v','copy','-c:a','pcm_s16le','-ar','48000','-ac','2','-af','apad',
    '-mo_audio','fastaudio','-mo_layout','6','-t','2','-f','moflex','/movie.moflex'],
    {video:encoded,source},'/movie.moflex',movie);
});
test.afterAll(()=>{if(work)rmSync(work,{recursive:true,force:true});});

test('browser edits SUPER MOFLEX, plays subtitles and exports tracks to MKV',async({page},testInfo)=>{
  await page.goto('/player.html');
  await page.locator('#movieFile').setInputFiles(movie);
  await expect(page.locator('#play')).toBeEnabled();
  await page.locator('#trailerEditor > summary').click();
  await page.getByLabel('Movie or series title').fill('Browser trailer test');
  const subs=Buffer.from('1\n00:00:00,000 --> 00:00:01,700\nHello from SUPER MOFLEX\n');
  await page.locator('#newSubtitles').setInputFiles({name:'episode.eng.srt',mimeType:'text/plain',buffer:subs});
  await page.locator('#newAltAudio').setInputFiles(source);
  await page.getByLabel('Alternate audio language').fill('JPN');
  const pending=page.waitForEvent('download');
  await page.locator('#writeTrailer').click();
  await expect(page.locator('#trailerStatus')).toContainText('Edited file ready',{timeout:30000});
  const changed=testInfo.outputPath('edited.moflex');
  await (await pending).saveAs(changed);
  const plain=readFileSync(movie);
  expect(readFileSync(changed).subarray(0,plain.length)).toEqual(plain);
  await page.locator('#movieFile').setInputFiles(changed);
  await expect(page.locator('#playerInfo')).toContainText('Browser trailer test');
  await page.locator('#subtitleSelect').selectOption('0');
  await expect(page.locator('#subtitle')).toHaveText('Hello from SUPER MOFLEX');
  await page.locator('#audioSelect').selectOption('alternate');
  await page.locator('#play').click();
  await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:30000});
  await page.locator('#exportFormat').selectOption('mkv');
  await page.locator('#exportAudio').selectOption('all');
  const exporting=page.waitForEvent('download');
  await page.locator('#exportVideo').click();
  await expect(page.locator('#playerStatus')).toHaveText('Converted video downloaded.',{timeout:30000});
  const out=testInfo.outputPath('tracks.mkv');
  await (await exporting).saveAs(out);
  const streams=JSON.parse(execFileSync('ffprobe',['-v','error','-show_entries',
    'stream=codec_type','-of','json',out])).streams;
  expect(streams.map(track=>track.codec_type)).toEqual(['video','audio','audio','subtitle']);
});

test('offline cache runs a real conversion and opens the player',async({page},testInfo)=>{
  // Stop a separate real HTTP server. WebKit's automation offline toggle can
  // fail before consulting service workers, so it cannot prove offline caching.
  const server=spawn(process.execPath,['scripts/dev-server.mjs'],{env:{...process.env,PORT:'0'},stdio:['ignore','pipe','pipe']});
  let errors='';server.stderr.on('data',chunk=>errors+=chunk);
  try{
    const port=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Offline test server failed to start: '+errors)),10000);
      server.once('error',error=>{clearTimeout(timer);reject(error);});
      server.once('exit',()=>{clearTimeout(timer);reject(Error('Offline test server exited: '+errors));});
      let output='';server.stdout.on('data',chunk=>{
        output+=chunk;const match=/MobiPEG ready on (\d+)/.exec(output);
        if(match){clearTimeout(timer);resolve(Number(match[1]));}
      });
    });
    const origin='http://127.0.0.1:'+port;
    await page.goto(origin+'/');
    await page.locator('#offlineSetup').click();
    await expect(page.locator('#offlineStatus')).toContainText('Ready offline',{timeout:90000});
    const stopped=once(server,'exit');server.kill();await stopped;
    expect(await page.evaluate(async()=>{try{await fetch('/uncached-network-probe');return false;}catch{return true;}})).toBe(true);
    await page.reload();
    expect(await page.evaluate(()=>crossOriginIsolated)).toBe(true);
    await page.locator('#file').setInputFiles(source);
    await page.locator('#workers').fill('1');
    await page.locator('#resolution').selectOption('256x144');
    await page.locator('#speed').selectOption('fast');
    await page.locator('#convert').click();
    await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:90000});
    await page.goto(origin+'/player.html');
    await page.locator('#movieFile').setInputFiles(movie);
    await expect(page.locator('#play')).toBeEnabled();
    await page.locator('#play').click();
    await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:30000});
    await page.goto(origin+'/cia.html');
    await expect(page.locator('#ciaOpen')).toBeVisible();
    expect(await page.evaluate(async()=>{const response=await fetch('/cia-sha256-core.wasm');return response.ok;})).toBe(true);
    const template=process.env.MOBIPEG_TEST_CIA_TEMPLATE;
    if(template){
      await page.locator('#ciaFiles').setInputFiles(movie);
      await expect(page.locator('#ciaEpisodes > li')).toHaveCount(1);
      await page.locator('#ciaTitle').fill('Offline movie');
      await page.locator('#ciaPublisher').fill('Local test');
      await page.locator('#ciaId').fill('C3456');
      await page.locator('#ciaTemplate').setInputFiles(template);
      const download=page.waitForEvent('download');await page.locator('#ciaBuild').click();
      const output=testInfo.outputPath('offline.cia');await (await download).saveAs(output);
      const verified=JSON.parse(execFileSync('python3',['native/cia_builder.py','verify',output],{encoding:'utf8'}));
      expect(verified.title_id).toBe('000400000C345600');
    }
  }finally{if(server.exitCode===null)server.kill();}
});

test('queue saves and continues automatically, with downloads still available after reload',async({page})=>{
  await page.goto('/');
  test.skip(!await page.evaluate(()=>!!navigator.storage?.getDirectory),'This browser build has no OPFS API.');
  await page.locator('#workers').fill('1');
  await page.locator('#resolution').selectOption('256x144');
  await page.locator('#speed').selectOption('fast');
  const buffer=readFileSync(source);
  await page.locator('#file').setInputFiles(['a','b'].map(name=>({name:name+'.mkv',mimeType:'video/x-matroska',buffer})));
  await page.locator('#batchPrivate').click();
  await expect(page.locator('#batchSaveStatus')).toContainText('automatically');
  await page.locator('#startQueue').click();
  await expect(page.locator('#stage')).toHaveText('Queue complete',{timeout:120000});
  await expect(page.locator('#savedBatchFiles > li')).toHaveCount(2);
  await page.reload();
  await expect(page.locator('#savedBatchFiles > li')).toHaveCount(2);
  const download=page.waitForEvent('download');
  await page.locator('#savedBatchFiles button').first().click();
  expect((await download).suggestedFilename()).toMatch(/\.moflex$/);
});

test('browser restores pending queue order and individual settings after reload',async({page})=>{
  const first=join(work,'first.mkv'),second=join(work,'second.mkv');
  copyFileSync(source,first);copyFileSync(source,second);
  await page.goto('/');
  await page.locator('#file').setInputFiles([first,second]);
  await expect(page.locator('#queueList > li')).toHaveCount(2);
  await page.locator('#queueList > li').nth(0).locator('.queue-select').click();
  await page.locator('#preset').selectOption('small');
  await page.locator('#queueList > li').nth(1).locator('.queue-select').click();
  await page.locator('#preset').selectOption('best');
  await page.reload();
  await expect(page.locator('#queueList > li')).toHaveCount(2);
  await expect(page.locator('#startQueue')).toBeDisabled();
  await expect(page.locator('#reselectQueueSources')).toBeVisible();
  await page.locator('.queue-recovery + input[type=file]').setInputFiles([first,second]);
  await expect(page.locator('#startQueue')).toBeEnabled();
  await expect(page.locator('#reselectQueueSources')).toBeHidden();
  await page.locator('#queueList > li').nth(0).locator('.queue-select').click();
  await expect(page.locator('#preset')).toHaveValue('small');
  await page.locator('#queueList > li').nth(1).locator('.queue-select').click();
  await expect(page.locator('#preset')).toHaveValue('best');
});

test('browser preserves a damaged or future-version queue until explicit discard',async({page})=>{
  await page.goto('/');
  for(const raw of ['{invalid',JSON.stringify({version:99,items:[]})]){
    await page.evaluate(value=>localStorage.setItem('mobipeg-batch-queue-v1',value),raw);
    await page.reload();
    await expect(page.locator('#discardSavedQueue')).toBeVisible();
    await expect(page.locator('#queueRestoreStatus')).toContainText('has been kept');
    expect(await page.evaluate(()=>localStorage.getItem('mobipeg-batch-queue-v1'))).toBe(raw);
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('#discardSavedQueue').click();
    await expect(page.locator('#discardSavedQueue')).toBeHidden();
    const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('mobipeg-batch-queue-v1')));
    expect(saved).toEqual({version:1,items:[]});
  }
});

test('browser can list and safely delete an abandoned OPFS checkpoint',async({page})=>{
  await page.goto('/');
  test.skip(!await page.evaluate(()=>!!navigator.storage?.getDirectory),'This browser build has no OPFS API.');
  await page.evaluate(async()=>{
    const root=await (await navigator.storage.getDirectory()).getDirectoryHandle('mobipeg-long-movies',{create:true});
    const folder=await root.getDirectoryHandle('resume-'+'a'.repeat(64),{create:true});
    const handle=await folder.getFileHandle('checkpoint.json',{create:true});
    const writer=await handle.createWritable();
    await writer.write(JSON.stringify({config:{identity:{name:'recovery-test.mkv',bytes:12345},
      encoder:'v15-test'},generation:'test'}));
    await writer.close();
    const broken=await root.getDirectoryHandle('resume-'+'b'.repeat(64),{create:true});
    const brokenFile=await broken.getFileHandle('checkpoint.json',{create:true});
    const brokenWriter=await brokenFile.createWritable();
    await brokenWriter.write('{unfinished metadata');await brokenWriter.close();
  });
  await page.locator('#refreshSavedJobs').click();
  await expect(page.locator('#savedJobsList > li')).toHaveCount(2);
  await expect(page.locator('#savedJobsList')).toContainText('recovery-test.mkv');
  await expect(page.locator('#savedJobsList')).toContainText('Damaged recovery');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Delete damaged recovery'}).click();
  await expect(page.locator('#savedJobsList > li')).toHaveCount(1);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Delete saved ranges'}).click();
  await expect(page.locator('#savedJobsList > li')).toHaveCount(0);
});

test('browser CIA project editor exports a native-compatible ordered project',async({page},testInfo)=>{
  await page.goto('/cia.html');
  await page.locator('#ciaFiles').setInputFiles(movie);
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(1);
  await page.locator('#ciaTitle').fill('My Movie');
  await page.locator('#ciaPublisher').fill('Studio');
  await page.locator('#ciaId').fill('C1234');
  const output=page.waitForEvent('download');
  await page.locator('#ciaExport').click();
  const downloaded=await output;
  const saved=testInfo.outputPath('cia-project.json');
  await downloaded.saveAs(saved);
  const manifest=JSON.parse(readFileSync(saved,'utf8'));
  expect(manifest.version).toBe(1);
  expect(manifest.title).toBe('My Movie');
  expect(manifest.publisher).toBe('Studio');
  expect(manifest.id).toBe('C1234');
  expect(manifest.movies).toHaveLength(1);
  expect(manifest.movies[0].file).toBe('source.moflex');
});

test('browser HDR controls expose auto detection, manual PQ/HLG and tone-mapping modes',async({page})=>{
  await page.goto('/');
  await expect(page.locator('#hdrMode')).toHaveValue('auto');
  await expect(page.locator('#hdrTransfer')).toHaveValue('auto');
  await page.locator('#hdrMode').selectOption('hable');
  await page.locator('#hdrTransfer').selectOption('hlg');
  await expect(page.locator('#hdrMode')).toHaveValue('hable');
  await expect(page.locator('#hdrTransfer')).toHaveValue('hlg');
});

test('CIA project reopens ordered episodes and artwork without changing the editor on missing inputs',async({page})=>{
  await page.goto('/cia.html');
  const project={version:1,title:'Reopened season',long_title:'Season long title',publisher:'Local studio',id:'C4321',
    movies:[{file:'second.moflex',title:'Finale',banner:'cover.png'},{file:'first.moflex',title:'Pilot'}],
    icon:'cover.png',browser:{split:true,bannerAudio:'sound.wav'}};
  const json={name:'project.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(project))};
  await page.locator('#ciaProject').setInputFiles(json);
  await page.locator('#ciaOpen').click();
  await expect(page.locator('#ciaStatus')).toContainText('missing project files');
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(0);
  await page.locator('#ciaProjectFiles').setInputFiles([
    {name:'first.moflex',mimeType:'application/octet-stream',buffer:readFileSync(movie)},
    {name:'second.moflex',mimeType:'application/octet-stream',buffer:readFileSync(movie)},
    {name:'cover.png',mimeType:'image/png',buffer:Buffer.from('local artwork')},
    {name:'sound.wav',mimeType:'audio/wav',buffer:Buffer.from('local audio')},
  ]);
  await page.locator('#ciaOpen').click();
  await expect(page.locator('#ciaStatus')).toContainText('Project reopened');
  await expect(page.getByRole('textbox',{name:'Episode 1 title',exact:true})).toHaveValue('Finale');
  await expect(page.getByRole('textbox',{name:'Episode 2 title',exact:true})).toHaveValue('Pilot');
  await expect(page.locator('#ciaLongTitle')).toHaveValue('Season long title');
  await expect(page.locator('#ciaSplit')).toBeChecked();
  expect(await page.locator('#ciaIcon').evaluate(el=>el.files[0].name)).toBe('cover.png');
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#ciaExport').click();
  const download=await downloadPromise;
  const saved=JSON.parse(readFileSync(await download.path(),'utf8'));
  expect(saved).toEqual(project);
  // Failed reopening must preserve all previously restored edits and media.
  await page.locator('#ciaProjectFiles').setInputFiles([]);
  await page.locator('#ciaOpen').click();
  await expect(page.locator('#ciaStatus')).toContainText('missing project files');
  await expect(page.getByRole('textbox',{name:'Episode 1 title',exact:true})).toHaveValue('Finale');
});

for(const engine of ['scalar','simd'])test('real short conversion and playback with '+engine,async({page},testInfo)=>{
  const engineRequests=[];page.on('request',r=>{if(/\/engine(?:-simd)?\/mobipeg\.(?:js|wasm)/.test(r.url()))engineRequests.push(r.url());});
  await page.goto('/');
  await page.locator('#file').setInputFiles(source);
  await page.locator('#workers').fill('1');
  await page.locator('#resolution').selectOption('256x144');
  await page.locator('#speed').selectOption('fast');
  await page.locator('details').filter({has:page.locator('#engine')}).locator('summary').click();
  await page.locator('#engine').selectOption(engine);
  await page.locator('#convert').click();
  await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:90000});
  const download=page.waitForEvent('download');
  await page.locator('#download').click();
  const output=testInfo.outputPath(engine+'.moflex');await (await download).saveAs(output);
  const reportDownload=page.waitForEvent('download');await page.locator('#report').click();
  const reportPath=testInfo.outputPath(engine+'-report.json');await (await reportDownload).saveAs(reportPath);
  const report=JSON.parse(readFileSync(reportPath));expect(report.encoder).toBe('MobiPEG V15 WASM');expect(report.layout).toBe(6);
  execFileSync('ffmpeg',['-v','error','-xerror','-i',output,'-f','null','-'],{timeout:30000});
  await page.goto('/player.html');await page.locator('#movieFile').setInputFiles(output);
  await page.locator('#play').click();
  await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:30000});
  expect(engineRequests.some(url=>url.includes('.wasm?'))).toBe(true);
  for(const url of engineRequests)expect(new URL(url).searchParams.get('v')).toBe('20261118u');
});

test('CIA editor uses saved batch conversions directly from OPFS',async({page})=>{
  await page.goto('/cia.html');
  test.skip(!await page.evaluate(()=>!!navigator.storage?.getDirectory),'This browser build has no OPFS API.');
  await page.evaluate(async bytes=>{
    const {batchStorage,saveBatchFile}=await import('/batch-output.mjs');
    await saveBatchFile(await batchStorage(true),'Episode 2',new Blob([new Uint8Array(bytes)]));
    await saveBatchFile(await batchStorage(true),'Episode 10',new Blob([new Uint8Array(bytes)]));
  },[...readFileSync(movie)]);
  await page.locator('#ciaAddSaved').click();
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(2);
  await expect(page.getByRole('textbox',{name:'Episode 1 title',exact:true})).toHaveValue('Episode 2');
  await expect(page.getByRole('textbox',{name:'Episode 2 title',exact:true})).toHaveValue('Episode 10');
  await page.locator('#ciaAddSaved').click();
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(2);
  await expect(page.locator('#ciaStatus')).toContainText('Duplicate filename');
});

test('verified CIA remains downloadable when optional browser storage fails',async({page},testInfo)=>{
  const template=process.env.MOBIPEG_TEST_CIA_TEMPLATE;
  test.skip(!template,'Provide a compatible local CIA template.');
  await page.addInitScript(()=>{
    const storage=navigator.storage||{};
    if(!navigator.storage)Object.defineProperty(navigator,'storage',{value:storage});
    Object.defineProperty(storage,'estimate',{value:async()=>({quota:1024**3,usage:0})});
    Object.defineProperty(storage,'getDirectory',{value:async()=>({getDirectoryHandle:async()=>({
      async *entries(){},getFileHandle:async()=>({createWritable:async()=>{throw new DOMException('Storage is full','QuotaExceededError');}}),
      removeEntry:async()=>{window.partialCiaRemoved=true;}
    })})});
  });
  await page.goto('/cia.html');
  await page.locator('#ciaFiles').setInputFiles(movie);
  await expect(page.locator('#ciaEpisodes > li')).toHaveCount(1);
  await page.locator('#ciaTitle').fill('Storage recovery');
  await page.locator('#ciaPublisher').fill('Local test');
  await page.locator('#ciaId').fill('C2468');
  await page.locator('#ciaTemplate').setInputFiles(template);
  await page.locator('#ciaStage').check();
  const pending=page.waitForEvent('download');await page.locator('#ciaBuild').click();
  const output=testInfo.outputPath('recovered.cia');await (await pending).saveAs(output);
  const verified=JSON.parse(execFileSync('python3',['native/cia_builder.py','verify',output],{encoding:'utf8'}));
  expect(verified.title_id).toBe('000400000C246800');
  await expect(page.locator('#ciaStatus')).toContainText('Storage is full');
  await expect(page.locator('#ciaStatus')).toContainText('offered for download');
  expect(await page.evaluate(()=>window.partialCiaRemoved)).toBe(true);
});
