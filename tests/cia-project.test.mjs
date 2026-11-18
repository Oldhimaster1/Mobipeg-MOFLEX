import test from 'node:test';
import assert from 'node:assert/strict';
import {ciaTitleID,createCiaProject,ciaSizeEstimate} from '../cia-project.mjs';
const project={title:'Demo',publisher:'Maker',id:'C1234',
  movies:[{file:'A.moflex',title:'Part 1'},{file:'B.moflex',title:'Part 2'}],
  icon:'cover.png',banner:'banner.bnr'};
test('CIA project is a valid native JSON schema with ordered episodes',()=>{
  const result=createCiaProject(project);
  assert.equal(result.version,1);assert.equal(result.movies[1].title,'Part 2');
  assert.equal(result.icon,'cover.png');assert.equal(result.id,'C1234');
  assert.match(ciaTitleID('C1234'),/^00040000[0-9A-F]{8}$/);
});
test('rejects duplicate, traversal, invalid title IDs and overlong text',()=>{
  assert.throws(()=>createCiaProject({...project,id:'B0000'}),/Title ID/);
  assert.throws(()=>createCiaProject({...project,id:'C1234',reservedTitleIds:['C1234']}),/already/);
  assert.throws(()=>createCiaProject({...project,movies:[{file:'../bad.moflex'}]}),/safe name/);
  assert.throws(()=>createCiaProject({...project,movies:[{file:'A.moflex'},{file:'a.moflex'}]}),/Duplicate/);
  assert.throws(()=>createCiaProject({...project,title:'X'.repeat(64)}),/63/);
});
test('FAT32 estimate checks raw payload size and leaves packager headroom',()=>{
  assert.equal(ciaSizeEstimate([{size:100},{size:200}]).headroom,0xffffffff-300);
  assert.throws(()=>ciaSizeEstimate([{size:0xffffffff}]),/FAT32/);
});
test('CIA estimates reject invalid individual sizes before summing',()=>{
  for(const files of [null,[{}],[{size:'100'}],[{size:-1},{size:101}],[{size:0.5},{size:0.5}]])
    assert.throws(()=>ciaSizeEstimate(files),/Invalid video sizes/);
});

test('collection splitting preserves order and protects title ID range',async()=>{
  const {planCiaParts,FAT32_CIA}=await import('../cia-project.mjs');
  const budget=FAT32_CIA-64*1024*1024-100;
  assert.deepEqual(planCiaParts([budget-1,2,3],100,'C1234',true),[[0],[1,2]]);
  assert.throws(()=>planCiaParts([budget,1],100,'C1234'),/Enable splitting/);
  assert.throws(()=>planCiaParts([budget+1],100,'C1234',true),/One movie/);
  assert.throws(()=>planCiaParts([budget,1],100,'EFFFF',true),/title IDs/);
});

test('player-facing localized title and publisher follow edited project metadata',async()=>{
  const {updateCiaLocaleSettings}=await import('../cia-project.mjs');
  const source='# アプリ名（ロングネーム）\r\n# JP:\r\nOld title\r\n\r\n# EN:\r\nOld title\r\n# 動画の数\r\n2\r\n# 動画パブリッシャー名\r\n# EN:\r\nOld publisher\r\n# WEBブラウザ用のURL\r\n# EN:\r\nnone\r\n';
  const updated=updateCiaLocaleSettings(source,{title:'New, title',publisher:'New publisher'});
  assert.equal(updated.includes('Old title'),false);assert.equal(updated.includes('Old publisher'),false);
  assert.match(updated,/# EN:\r\nNew\\x2C title/);assert.match(updated,/# EN:\r\nNew publisher/);assert.match(updated,/# 動画の数\r\n2/);assert.match(updated,/# EN:\r\nnone/);
});
