const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../src/web/static/culling.js'),'utf8');

function setup(){
 const nodes=new Map();
 const node=()=>({value:'',disabled:false,options:[],textContent:'',
  replaceChildren(){this.options=[];},append(...children){this.options.push(...children);}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
 const calls=[];let serial=0;
 const env={document:{querySelector:get,createElement:node},window:{addEventListener(){}},
  setInterval(){},crypto:{randomUUID:()=>`key-${++serial}`},
  fetch:async()=>({ok:true,json:async()=>({sources:[],default_mode:'safe',current:{running:false},jobs:[]})})};
 vm.createContext(env);vm.runInContext(code,env);
 env.testApi=async(url,body)=>{calls.push({url,body});return {};};
 vm.runInContext("api=(url,body)=>testApi(url,body);render=()=>{};snapshot={id:'old',report:{}};",env);
 return {env,get,calls,run:expression=>vm.runInContext(expression,env)};
}

test('pending review work blocks concurrent navigation and releases on failure',async()=>{
 const e=setup();let release;
 e.env.wait=()=>new Promise(resolve=>{release=resolve;});
 const active=e.run('withReview(async()=>{await wait();throw Error("failed");})');
 assert.equal(e.get('#results').inert,true);
 await assert.rejects(e.run('withReview(async()=>{})'),/稍候/);
 release();await assert.rejects(active,/failed/);
 assert.equal(e.get('#results').inert,false);
 assert.equal(e.get('#open').disabled,false);
});

test('unsaved human edits block regroup before sending a request',async()=>{
 const e=setup();e.run("unsaved.add('bird')");
 await assert.rejects(e.run("submitRegroup('split',['g'],['a'])"),/先保存/);
 assert.equal(e.calls.length,0);assert.equal(e.run('snapshot.id'),'old');
});

test('network retry keeps request identity and old view until both reads succeed',async()=>{
 const e=setup();let fail=true;
 e.env.testApi=async(url,body)=>{
  e.calls.push({url,body});
  if(url.endsWith('/regroup')){if(fail)throw Error('network');return {snapshot_id:'new'};}
  if(url.endsWith('/history'))return [{id:'old',action:'analysis'},{id:'new',action:'split',parent_snapshot_id:'old'}];
  return {id:'new',report:{revision:{parent_snapshot_id:'old'}}};
 };
 await assert.rejects(e.run("submitRegroup('split',['g'],['a'])"),/network/);
 assert.equal(e.run('snapshot.id'),'old');fail=false;
 await e.run("submitRegroup('split',['g'],['a'])");
 const posts=e.calls.filter(c=>c.body);assert.equal(posts[0].body.request_key,posts[1].body.request_key);
 assert.equal(e.run('snapshot.id'),'new');assert.equal(e.get('#revisions').value,'new');
 assert.match(e.get('#revision-current').textContent,/版本 2.*基于版本 1/);
 assert.equal(e.get('#parent-revision').disabled,false);
});

test('history load failure leaves existing result and unsaved edits intact',async()=>{
 const e=setup();e.run("unsaved.add('bird')");
 e.env.testApi=async url=>{if(url.endsWith('/history'))throw Error('history unavailable');return {id:'new'};};
 await assert.rejects(e.run("withReview(()=>openSnapshot('new'))"),/history unavailable/);
 assert.equal(e.run('snapshot.id'),'old');assert.equal(e.run('unsaved.has("bird")'),true);
});

test('subject selection retries the same key and preserves explicit index zero',async()=>{
 const e=setup();let fail=true;
 e.env.testApi=async(url,body)=>{
  e.calls.push({url,body});
  if(url.endsWith('/subject')){if(fail)throw Error('network');return {snapshot_id:'child'};}
  if(url.endsWith('/history'))return [{id:'old',action:'analysis'},{id:'child',action:'subject',parent_snapshot_id:'old'}];
  return {id:'child',report:{revision:{parent_snapshot_id:'old'}}};
 };
 await assert.rejects(e.run("submitSubject('bird',0)"),/network/);
 fail=false;await e.run("submitSubject('bird',0)");
 const posts=e.calls.filter(c=>c.body);
 assert.equal(posts[0].body.detection_index,0);
 assert.equal(posts[0].body.request_key,posts[1].body.request_key);
 assert.match(e.get('#revision-current').textContent,/主体改选/);
});

test('subject edits respect unsaved manual choices',async()=>{
 const e=setup();e.run("unsaved.add('bird')");
 await assert.rejects(e.run("submitSubject('bird',null)"),/先保存/);
 assert.equal(e.calls.length,0);
});
