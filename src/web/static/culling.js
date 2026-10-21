'use strict';
const $=s=>document.querySelector(s);
let snapshot=null, loading=false, defaultDirty=false, adviceUpdates=[];
const unsaved=new Set();
const modes={safe:'稳妥推荐',assist:'辅助比较',relaxed:'宽松推荐（实验）'};
const states={completed:'已完成',failed:'有失败',stopped:'已停止',interrupted:'上次中断',running:'处理中',pending:'等待中'};
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function options(select,values){select.replaceChildren();for(const [value,text] of values){const o=el('option',text);o.value=value;select.append(o);}}
async function api(url,body){const r=await fetch('/api/culling'+url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败，请检查参数');return d;}
async function act(fn){try{await fn();}catch(e){$('#message').textContent=e.message;}}
async function refresh(){if(loading)return;loading=true;try{
 const d=await api('/status');
 if(!$('#source').options.length)options($('#source'),d.sources.map(s=>[s.id,s.path]));
 if(!defaultDirty)$('#default-mode').value=d.default_mode;
 $('#start').disabled=d.current.running;$('#stop').disabled=!d.current.running;
 const active=d.jobs[0];$('#progress').textContent=(d.current.error?d.current.error+'\n':'')+(d.current.running?'任务处理中，可停止。\n':'')+(active?`${states[active.status]||active.status} · 已处理 ${Object.entries(active.counts).filter(([k])=>['completed','failed','skipped'].includes(k)).reduce((n,[,v])=>n+v,0)} 张`+(active.error?'\n'+active.error:''):'暂无选片任务');
 const selected=$('#history').value;options($('#history'),d.jobs.filter(j=>j.snapshot_id).map(j=>[j.snapshot_id,`${j.created_at.slice(0,19)} · ${states[j.status]||j.status}`]));
 if([...$('#history').options].some(o=>o.value===selected))$('#history').value=selected;
 }finally{loading=false;}}
function media(version,crop=false){return `/api/culling/snapshots/${encodeURIComponent(snapshot.id)}/media/${encodeURIComponent(version)}?crop=${crop}`;}
function render(){
 adviceUpdates=[];unsaved.clear();
 const host=$('#results');host.replaceChildren();const report=snapshot.report;
 host.append(el('p',report.input_set_complete?'本次输入已处理完毕。':'这是一份部分结果，请查看任务失败或停止原因。'));
 host.append(el('p',`缓存命中 ${report.cache_hits??0} 张，新计算 ${report.computed??0} 张。`));
 for(const [number,group] of report.groups.entries()){
  const section=el('section');section.className='panel';section.append(el('h2',`第 ${number+1} 组 · ${group.version_ids.length} 张`));
  const mode=el('select');options(mode,[['','跟随默认'],...Object.entries(modes)]);mode.value=snapshot.modes[group.group_id].override??'';
  const caption=el('label','本组模式 ');caption.append(mode);section.append(caption);
  const advice=el('pre');section.append(advice);
  function updateAdvice(){const effective=mode.value||snapshot.modes[group.group_id].default;const r=group.ranking_modes[effective];const names=keys=>keys.map(k=>report.items[k].filename).join('、');
   advice.textContent=modes[effective]+(effective==='relaxed'?'：实验结果，请复核。':'')+'\n'+(effective==='assist'?'候选顺序：':'推荐：')+(names(effective==='assist'?r.ranked:r.recommended)||'暂无，请人工检查')+(r.scale_guard_triggered?'\n主体大小或姿态差异较大，排序可能不可靠。':'')+(r.tie_sets.length?'\n分数接近：'+r.tie_sets.map(names).join('；'):'')+(r.unranked.length?'\n未排序：'+names(r.unranked):'')+'\n相对排序不代表已合焦。';}
  adviceUpdates.push(updateAdvice);updateAdvice();let savedMode=mode.value;mode.onchange=()=>act(async()=>{mode.disabled=true;try{snapshot.modes[group.group_id]=await api(`/snapshots/${snapshot.id}/groups/${group.group_id}/mode`,{mode:mode.value||null});savedMode=mode.value;updateAdvice();$('#message').textContent='本组模式已保存，人工选择未改变。';}catch(e){mode.value=savedMode;throw e;}finally{mode.disabled=false;}});
  const comparable=group.version_ids.filter(k=>report.items[k].evidence.bounds);
  if(comparable.length){
   const details=el('details'),summary=el('summary','并排比较主体原像素');details.append(summary);
   const zoom=el('select');options(zoom,[['0.5','50%'],['1','100%'],['2','200%']]);zoom.value='1';zoom.setAttribute('aria-label','主体缩放');details.append(zoom,el('span',' 100% 显示原像素；可分别滚动定位鸟眼。'));
   const pair=el('div');pair.className='pair';const images=[];
   for(let i=0;i<2;i++){const side=el('div'),pick=el('select');options(pick,comparable.map(k=>[k,report.items[k].filename]));pick.selectedIndex=Math.min(i,comparable.length-1);pick.setAttribute('aria-label',i===0?'左侧照片':'右侧照片');
    const view=el('div');view.className='viewport';const image=el('img');image.alt='主体原像素';images.push(image);
    image.onload=()=>{image.style.width=image.naturalWidth*Number(zoom.value)+'px';};image.onerror=()=>{$('#message').textContent='主体图片不可用或内容已变化，请重新分析。';};
    const load=()=>{image.src=media(snapshot.version_map[pick.value],true);};pick.onchange=load;details.addEventListener('toggle',()=>{if(details.open&&!image.src)load();});
    view.append(image);side.append(pick,view);pair.append(side);}
   zoom.onchange=()=>images.forEach(im=>im.style.width=im.naturalWidth*Number(zoom.value)+'px');details.append(pair);section.append(details);
  }
  const grid=el('div');grid.className='photos';
  for(const key of group.version_ids){const item=report.items[key],version=snapshot.version_map[key],decision=snapshot.decisions[version];const card=el('article');card.className='photo';
   const image=el('img');image.loading='lazy';image.alt=item.filename;image.src=media(version);image.onerror=()=>{image.alt='照片不可用或已变化，请重新分析';};
   const select=el('select');options(select,[['undecided','待定'],['keep','保留'],['reject','拒绝（仅标记）']]);select.value=decision?.decision??'undecided';select.setAttribute('aria-label',item.filename+' 人工决定');
   const note=el('textarea');note.placeholder='备注（可选）';note.setAttribute('aria-label',item.filename+' 备注');note.maxLength=4000;note.value=decision?.note??'';
   const save=el('button','保存人工标记'),feedback=el('span',decision?' 已保存':' 尚未标记');
   select.onchange=note.oninput=()=>{unsaved.add(version);feedback.textContent=' 尚未保存';};
   save.onclick=()=>act(async()=>{save.disabled=select.disabled=note.disabled=true;try{snapshot.decisions[version]=await api(`/snapshots/${snapshot.id}/decisions/${version}`,{decision:select.value,note:note.value});unsaved.delete(version);feedback.textContent=' 已保存';}finally{save.disabled=select.disabled=note.disabled=false;}});
   card.append(el('h3',item.filename),image,el('p',item.evidence.status==='review'?'当前无法可靠评分，请人工查看。':''),select,note,save,feedback);grid.append(card);
  }section.append(grid);host.append(section);
 }
}
$('#start').onclick=()=>act(async()=>{await api('/start',{source:Number($('#source').value),relative:$('#relative').value,gap:Number($('#gap').value),span:Number($('#span').value)});$('#message').textContent='已提交选片任务。';await refresh();});
$('#stop').onclick=()=>act(async()=>{await api('/stop',{});$('#message').textContent='已请求停止，等待当前照片处理完毕。';});
$('#default-mode').onchange=()=>{defaultDirty=true;};
$('#save-default').onclick=()=>act(async()=>{const mode=$('#default-mode').value;$('#default-mode').disabled=$('#save-default').disabled=true;try{await api('/default-mode',{mode});defaultDirty=false;if(snapshot){Object.values(snapshot.modes).forEach(m=>m.default=mode);adviceUpdates.forEach(f=>f());}$('#message').textContent='默认模式已保存，跟随默认的组已更新，人工选择不变。';await refresh();}finally{$('#default-mode').disabled=$('#save-default').disabled=false;}});
$('#open').onclick=()=>act(async()=>{if(!$('#history').value)return;if(unsaved.size&&!confirm('有尚未保存的人工标记，仍要打开另一份结果吗？'))return;snapshot=await api('/snapshots/'+$('#history').value);render();});
window.addEventListener('beforeunload',event=>{if(unsaved.size){event.preventDefault();event.returnValue='';}});
act(refresh);setInterval(()=>act(refresh),3000);
