const { test } = require('node:test');
const assert = require('node:assert/strict');
const { GraphModel } = require('../../src/fravenir/admin/static/graph-view.js');
const model = new GraphModel({
  nodes: [
    {data:{id:'ep_1',type:'episode',kind:'facts',importance:3,label:'省略',search_text:'はじめに '.repeat(30)+'ＰｒｉｎｔＳｗｉｆｔ 静かな世界'}},
    {data:{id:'ep_2',type:'episode',kind:'state',importance:1,label:'child'}},
    {data:{id:'th_1',type:'thread',label:'thread'}},
    {data:{id:'po_1',type:'post',label:'evidence'}},
    {data:{id:'en_1',type:'entity',label:'isolated'}},
  ],
  edges: [
    {data:{id:'rel_1',source:'ep_2',target:'ep_1',type:'relation',predicate:'part_of'}},
    {data:{id:'rel_2',source:'ep_1',target:'th_1',type:'relation',predicate:'derived_from'}},
    {data:{id:'rel_3',source:'th_1',target:'po_1',type:'relation',predicate:'contains'}},
  ],
});
const filters = {type:{episode:true,entity:true,relation:true},kind:{facts:true,state:true},importance:1,degree:0};
test('matches full Japanese text and normalized identifiers beyond the truncated label', () => {
  assert.deepEqual(model.matches(model.nodes,'PrintSwift 静かな世界').map(n=>n.id), ['ep_1']);
  assert.equal(model.matches(model.nodes,'does not exist').length, 0);
  assert.equal(model.matches(model.nodes,'  ').length, 0);
});
test('preserves direction, path length and edge identity', () => {
  const p = model.project(filters);
  assert.deepEqual(model.neighborhood(p,['ep_1'],1,'incoming').nodes.map(n=>n.id),['ep_1','ep_2']);
  assert.deepEqual(model.neighborhood(p,['ep_1'],1,'outgoing').nodes.map(n=>n.id),['ep_1','th_1']);
  assert.deepEqual(model.neighborhood(p,['ep_1'],2,'outgoing').edges.map(e=>e.id),['rel_2','rel_3']);
  assert.equal(model.neighborhood(p,['ep_1'],0).nodes.length,1);
});
test('type, kind, importance, relation predicates and degree share the same projection', () => {
  assert.equal(model.project({...filters,type:{...filters.type,thread:false}}).edges.length,1);
  assert.equal(model.project({...filters,kind:{facts:true,state:false}}).nodes.length,4);
  assert.equal(model.project({...filters,importance:2}).nodes.length,4);
  assert.deepEqual(model.project(filters,'part_of').edges.map(e=>e.id),['rel_1']);
  assert.deepEqual(model.project({...filters,degree:2}).nodes.map(n=>n.id),['ep_1','th_1']);
  assert.equal(model.project({...filters,type:{relation:false}}).edges.length,0);
});
test('filtered nodes cannot bridge a neighborhood and unknown seeds add no nodes', () => {
  const p=model.project({...filters,type:{thread:false}});
  assert.deepEqual(model.neighborhood(p,['ep_1'],3,'outgoing').nodes.map(n=>n.id),['ep_1']);
  assert.equal(model.neighborhood(p,['missing'],2).nodes.length,0);
});
