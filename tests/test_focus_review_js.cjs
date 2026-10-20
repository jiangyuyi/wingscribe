// Pure DOM-contract tests; no browser, network or photo access.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/evaluation/focus_review.js'), 'utf8');

function control(extra={}) {
 const e={listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
 Object.defineProperties(e,Object.getOwnPropertyDescriptors(extra));
 return e;
}
function environment(){
 const picks=[0,1].map(()=>control({options:['a.png','b.png'],selectedIndex:0,
  get value(){return this.options[this.selectedIndex];}}));
 const images=[0,1].map(()=>({naturalWidth:1000,naturalHeight:800,style:{},
  set src(value){this.url=value;this.onload();}}));
 const views=images.map(im=>control({scrollLeft:0,scrollTop:0,clientWidth:400,clientHeight:300,
  get scrollWidth(){return Math.max(400,parseFloat(im.style.width)||1000);},
  get scrollHeight(){return Math.max(300,parseFloat(im.style.height)||800);},
  querySelector(){return im;}}));
 const zoom=control({value:'1'}),sync={checked:true},blink=control(),caption={textContent:''};
 const panel={querySelectorAll(s){return s==='.pick'?picks:views;},
  querySelector(s){return {'.zoom':zoom,'.sync':sync,'.blink':blink,'.blink-label':caption}[s];}};
 const grouping={value:'uncertain'},certainty={value:'uncertain'},reviewed={checked:false};
 const inputs=[{value:'a',checked:false},{value:'b',checked:false}];
 const section={dataset:{group:'g'},querySelectorAll(){return inputs;},
  querySelector(s){return {'.grouping':grouping,'.certainty':certainty,'.reviewed':reviewed}[s];}};
 const uploader=control(),message={textContent:''};
 const document={querySelectorAll(s){return s==='.compare'?[panel]:[section];},
  querySelector(s){return s==='#import-labels'?uploader:message;}};
 vm.runInNewContext(source,{document,reportId:'r',requestAnimationFrame:fn=>fn()});
 return {picks,images,views,zoom,sync,blink,caption,grouping,certainty,reviewed,inputs,uploader,message};
}

test('native pixels, shared zoom and A/B switching',()=>{
 const e=environment();
 assert.equal(e.images[0].url,'a.png');assert.equal(e.images[1].url,'b.png');
 assert.equal(e.images[0].style.width,'1000px');
 e.zoom.value='2';e.zoom.listeners.change();
 assert.equal(e.images[0].style.width,'2000px');
 assert.equal(e.images[1].style.width,'2000px');
 e.blink.listeners.click();assert.equal(e.images[0].url,'b.png');
 assert.match(e.caption.textContent,/B/);
 e.blink.listeners.click();assert.equal(e.images[0].url,'a.png');
});
test('synchronized relative position can be disabled',()=>{
 const e=environment();
 e.views[0].scrollLeft=250;e.views[0].scrollTop=200;e.views[0].listeners.scroll();
 assert.equal(e.views[1].scrollLeft,250);assert.equal(e.views[1].scrollTop,200);
 e.sync.checked=false;e.views[0].scrollLeft=100;e.views[0].listeners.scroll();
 assert.equal(e.views[1].scrollLeft,250);
});
async function upload(e,data){
 await e.uploader.listeners.change({target:{files:[{text:async()=>JSON.stringify(data)}]}});
}
test('import restores selections and certainty; bad report leaves state unchanged',async()=>{
 const e=environment();
 const groups=[{group_id:'g',reviewed:true,grouping:'correct',certainty:'tentative',best:['b']}];
 await upload(e,{report_id:'r',schema_version:2,groups});
 assert.equal(e.certainty.value,'tentative');assert.equal(e.inputs[1].checked,true);
 await upload(e,{report_id:'wrong',schema_version:2,groups:[]});
 assert.equal(e.inputs[1].checked,true);assert.match(e.message.textContent,/未导入/);
});
test('old labels do not silently become confident; import is atomic',async()=>{
 const e=environment();
 const group={group_id:'g',reviewed:true,grouping:'correct',best:['a']};
 await upload(e,{report_id:'r',groups:[group]});
 assert.equal(e.certainty.value,'uncertain');assert.equal(e.inputs[0].checked,true);
 await upload(e,{report_id:'r',schema_version:2,groups:[
  {...group,certainty:'confident',best:['b']},{...group,group_id:'other',certainty:'confident'}]});
 assert.equal(e.inputs[0].checked,true);assert.equal(e.inputs[1].checked,false);
});
