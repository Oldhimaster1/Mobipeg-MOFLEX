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
