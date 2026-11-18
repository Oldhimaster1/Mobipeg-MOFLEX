import test from 'node:test';
import assert from 'node:assert/strict';
import {parseCiaProject,resolveCiaProjectFiles} from '../cia-project-import.mjs';
const source={version:1,title:'Season',long_title:'Season One',publisher:'Studio',id:'C1234',movies:[{file:'b.moflex',title:'Second',banner:'b.bimg'},{file:'a.moflex',title:'First'}],icon:'icon.png',browser:{split:true,bannerAudio:'tone.wav'}};
test('project reopen preserves native long title, order and browser audio/split settings',()=>{
 const project=parseCiaProject(JSON.stringify(source));
 assert.equal(project.long_title,'Season One');
 const files=['a.moflex','tone.wav','b.bimg','ICON.PNG','b.moflex'].map(name=>({name}));
 const resolved=resolveCiaProjectFiles(project,files);
 assert.deepEqual(resolved.movies.map(m=>m.file.name),['b.moflex','a.moflex']);
 assert.equal(resolved.movies[0].bannerFile.name,'b.bimg');
 assert.equal(resolved.bannerAudio.name,'tone.wav');assert.equal(project.browser.split,true);
});
test('project reopen rejects unsafe/versioned/oversized inputs and missing or ambiguous files',()=>{
 assert.throws(()=>parseCiaProject(JSON.stringify({...source,version:2})),/version/);
 assert.throws(()=>parseCiaProject(' '.repeat(1024*1024+1)),/1 MiB/);
 assert.throws(()=>parseCiaProject(JSON.stringify({...source,browser:{bannerAudio:'../tone.wav'}})),/safe name/);
 const project=parseCiaProject(JSON.stringify(source));
 assert.throws(()=>resolveCiaProjectFiles(project,[]),/b.moflex.*b.bimg.*a.moflex.*icon.png.*tone.wav/);
 assert.throws(()=>resolveCiaProjectFiles(project,[{name:'A.moflex'},{name:'a.moflex'}]),/Ambiguous/);
});
