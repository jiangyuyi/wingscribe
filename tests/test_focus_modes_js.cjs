const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../src/evaluation/focus_modes_review.js'),'utf8');
function setup(){
 const control=value=>({value,listeners:{},addEventListener(k,f){this.listeners[k]=f;}});
 const global=control('safe');
 const sections=['g1','g2'].map(key=>{
  const selector=control('inherit'), output={textContent:''};
  return {dataset:{group:key},selector,output,humanBest:['a'],
   querySelector(s){if(s==='.group-mode')return selector;if(s==='.mode-result')return output;throw Error('Unexpected access to human choices');}};
 });
 const modeData=Object.fromEntries(sections.map(s=>[s.dataset.group,{names:{a:'A.jpg',b:'B.jpg'},modes:
  Object.fromEntries(['safe','assist','relaxed'].map(mode=>[mode,{ranked:['a'],recommended:mode==='relaxed'?['a']:[],
  scale_guard_triggered:true,tie_sets:[],unranked:['b']}]))}]));
 const context={document:{querySelector(){return global;},querySelectorAll(){return sections;}},modeData};
 vm.createContext(context);vm.runInContext(source,context);
 return {global,sections,context};
}
test('global changes respect group override and never touch human labels',()=>{
 const e=setup();e.sections[0].selector.value='assist';e.sections[0].selector.listeners.change();
 e.global.value='relaxed';e.global.listeners.change();
 assert.match(e.sections[0].output.textContent,/候选顺序：A.jpg/);
 assert.match(e.sections[1].output.textContent,/推荐：A.jpg/);
 assert.match(e.sections[1].output.textContent,/可能不可靠/);
 e.sections[0].selector.value='inherit';e.sections[0].selector.listeners.change();
 assert.match(e.sections[0].output.textContent,/宽松推荐/);
 assert.deepEqual(e.sections[0].humanBest,['a']);
});
test('preferences round trip and inconsistent import is rejected before mutation',()=>{
 const e=setup();
 const data={default_mode:'relaxed',mode_version:'focus-advice-v1',groups:[
  {group_id:'g1',mode:'assist',mode_override:'assist'},{group_id:'g2',mode:'relaxed',mode_override:'inherit'}]};
 e.context.prepareModeImport(data)();
 assert.equal(e.context.modeSelection(e.sections[0]).mode,'assist');
 assert.equal(e.context.modePreferences().default_mode,'relaxed');
 assert.throws(()=>e.context.prepareModeImport({...data,groups:[{group_id:'g1',mode:'safe',mode_override:'assist'}]}));
 assert.equal(e.global.value,'relaxed');assert.equal(e.sections[0].selector.value,'assist');
 e.context.prepareModeImport({groups:[{group_id:'g1'}]})();
 assert.equal(e.global.value,'safe');assert.equal(e.sections[0].selector.value,'inherit');
});
