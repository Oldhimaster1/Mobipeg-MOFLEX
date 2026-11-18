import {expect,test} from '@playwright/test';
import {execFileSync} from 'node:child_process';
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

test('offline cache runs a real conversion and opens the player',async({page,context},testInfo)=>{
  await page.goto('/');
  await page.locator('#offlineSetup').click();
  await expect(page.locator('#offlineStatus')).toContainText('Ready offline',{timeout:90000});
  await context.setOffline(true);
  try{
    await page.reload();
    expect(await page.evaluate(()=>crossOriginIsolated)).toBe(true);
    await page.locator('#file').setInputFiles(source);
    await page.locator('#workers').fill('1');
    await page.locator('#resolution').selectOption('256x144');
    await page.locator('#speed').selectOption('fast');
    await page.locator('#convert').click();
    await expect(page.locator('#stage')).toHaveText('Your MOFLEX is ready.',{timeout:90000});
    await page.goto('/player.html');
    await page.locator('#movieFile').setInputFiles(movie);
    await expect(page.locator('#play')).toBeEnabled();
    await page.locator('#play').click();
    await expect(page.locator('#playerStatus')).toContainText('Playing locally',{timeout:30000});
  }finally{await context.setOffline(false);}
});

test('queue saves and continues automatically, with downloads still available after reload',async({page})=>{
  await page.goto('/');
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

test('browser can list and safely delete an abandoned OPFS checkpoint',async({page})=>{
  await page.goto('/');
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
