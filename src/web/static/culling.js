'use strict';
const $=s=>document.querySelector(s);
let snapshot=null, loading=false, defaultDirty=false, adviceUpdates=[];
const unsaved=new Set();
let reviewBusy=false, pendingRegroup=null, pendingSubject=null;
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
 host.append(el('p',report.revision?'这是人工修订；下方统计来自原分析。分组调整只重排建议，主体改选只重评分该照片。':'这是原始自动分组。'));
 host.append(el('p',`缓存命中 ${report.cache_hits??0} 张，新计算 ${report.computed??0} 张。`));
 const mergeSelection=new Set();
 const merge=el('button','合并所选组'),mergeCount=el('span',' 已选 0 组');merge.disabled=true;
 merge.onclick=()=>act(()=>submitRegroup('merge',[...mergeSelection],[]));
 host.append(merge,mergeCount,el('p','合并允许跨自动分组边界。来源组模式不一致时，新组跟随默认；原版本和人工标记保留。'));
 for(const [number,group] of report.groups.entries()){
  const section=el('section');section.className='panel';section.append(el('h2',`第 ${number+1} 组 · ${group.version_ids.length} 张`));
  const mergeBox=el('input');mergeBox.type='checkbox';
  const mergeLabel=el('label',`选择第 ${number+1} 组参与合并 `);mergeLabel.append(mergeBox);section.append(mergeLabel);
  mergeBox.onchange=()=>{if(mergeBox.checked)mergeSelection.add(group.group_id);else mergeSelection.delete(group.group_id);mergeCount.textContent=` 已选 ${mergeSelection.size} 组`;merge.disabled=mergeSelection.size<2;};
  const splitSelection=new Set(),split=el('button','将所选照片拆为新组'),splitCount=el('span',' 已选 0 张');split.disabled=true;
  split.onclick=()=>act(()=>submitRegroup('split',[group.group_id],[...splitSelection]));
  section.append(split,splitCount);
  const mode=el('select');options(mode,[['','跟随默认'],...Object.entries(modes)]);mode.value=snapshot.modes[group.group_id].override??'';
  const caption=el('label','本组模式 ');caption.append(mode);section.append(caption);
  const advice=el('pre');section.append(advice);
  function updateAdvice(){const effective=mode.value||snapshot.modes[group.group_id].default;const r=group.ranking_modes[effective];const names=keys=>keys.map(k=>report.items[k].filename).join('、');
   advice.textContent=modes[effective]+(effective==='relaxed'?'：实验结果，请复核。':'')+'\n'+(effective==='assist'?'候选顺序：':'推荐：')+(names(effective==='assist'?r.ranked:r.recommended)||'暂无，请人工检查')+(r.scale_guard_triggered?'\n主体大小或姿态差异较大，排序可能不可靠。':'')+(r.tie_sets.length?'\n分数接近：'+r.tie_sets.map(names).join('；'):'')+(r.unranked.length?'\n未排序：'+names(r.unranked):'')+'\n相对排序不代表已合焦。';}
  adviceUpdates.push(updateAdvice);updateAdvice();let savedMode=mode.value;mode.onchange=()=>act(()=>withReview(async()=>{mode.disabled=true;try{snapshot.modes[group.group_id]=await api(`/snapshots/${snapshot.id}/groups/${group.group_id}/mode`,{mode:mode.value||null});savedMode=mode.value;updateAdvice();$('#message').textContent='本组模式已保存，人工选择未改变。';}catch(e){mode.value=savedMode;throw e;}finally{mode.disabled=false;}}));
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
   const splitBox=el('input');splitBox.type='checkbox';
   const splitLabel=el('label',`选择 ${item.filename} 拆组 `);splitLabel.append(splitBox);card.append(splitLabel);
   splitBox.onchange=()=>{if(splitBox.checked)splitSelection.add(key);else splitSelection.delete(key);splitCount.textContent=` 已选 ${splitSelection.size}/${group.version_ids.length} 张`;split.disabled=!splitSelection.size||splitSelection.size===group.version_ids.length;};
   const image=el('img');image.loading='lazy';image.alt=item.filename;image.src=media(version);image.onerror=()=>{image.alt='照片不可用或已变化，请重新分析';};
   const select=el('select');options(select,[['undecided','待定'],['keep','保留'],['reject','拒绝（仅标记）']]);select.value=decision?.decision??'undecided';select.setAttribute('aria-label',item.filename+' 人工决定');
   const note=el('textarea');note.placeholder='备注（可选）';note.setAttribute('aria-label',item.filename+' 备注');note.maxLength=4000;note.value=decision?.note??'';
   const save=el('button','保存人工标记'),feedback=el('span',decision?' 已保存':' 尚未标记');
   select.onchange=note.oninput=()=>{unsaved.add(version);feedback.textContent=' 尚未保存';};
   save.onclick=()=>act(()=>withReview(async()=>{save.disabled=select.disabled=note.disabled=true;try{snapshot.decisions[version]=await api(`/snapshots/${snapshot.id}/decisions/${version}`,{decision:select.value,note:note.value});unsaved.delete(version);feedback.textContent=' 已保存';}finally{save.disabled=select.disabled=note.disabled=false;}}));
   const subjectPanel=el('details');subjectPanel.append(el('summary','查看／改选评分主体'));
   if(item.boxes?.length){
    const pick=el('select');pick.setAttribute('aria-label',item.filename+' 评分主体');
    options(pick,[['','自动选择最大主体'],...item.boxes.map((box,i)=>[String(i),`主体 ${i+1}`])]);
    pick.value=item.subject_override==null?'':String(item.subject_override);
    const current=el('p',`已保存：${item.subject_override==null?'自动选择':'手动选择'} · ${item.evidence.detection_index==null?'无有效主体':'主体 '+(item.evidence.detection_index+1)}`);
    const preview=el('img');preview.alt=item.filename+' 候选主体框';preview.style.maxHeight='none';
    const sid=snapshot.id;
    const load=()=>{preview.src=`/api/culling/snapshots/${sid}/subjects/${version}`+(pick.value===''?'':`?index=${pick.value}`);};
    pick.onchange=load;subjectPanel.addEventListener('toggle',()=>{if(subjectPanel.open&&!preview.src)load();});
    preview.onerror=()=>{$('#message').textContent='主体预览不可用，请检查来源或重新分析。';};
    const apply=el('button','应用主体并重新评分');apply.onclick=()=>act(()=>submitSubject(version,pick.value===''?null:Number(pick.value)));
    subjectPanel.append(current,pick,el('p','黄色为待选主体，蓝色为其他框；选择后点击应用才保存。'),preview,apply);
   }else{subjectPanel.append(el('p','未检测到有效候选主体，暂不能手动改选。'));}
   card.append(el('h3',item.filename),image,subjectPanel,el('p',item.evidence.status==='review'?'当前无法可靠评分，请人工查看。':''),select,note,save,feedback);grid.append(card);
  }section.append(grid);host.append(section);
 }
}
$('#start').onclick=()=>act(async()=>{await api('/start',{source:Number($('#source').value),relative:$('#relative').value,gap:Number($('#gap').value),span:Number($('#span').value)});$('#message').textContent='已提交选片任务。';await refresh();});
$('#stop').onclick=()=>act(async()=>{await api('/stop',{});$('#message').textContent='已请求停止，等待当前照片处理完毕。';});
$('#default-mode').onchange=()=>{defaultDirty=true;};
$('#save-default').onclick=()=>act(()=>withReview(async()=>{const mode=$('#default-mode').value;$('#default-mode').disabled=$('#save-default').disabled=true;try{await api('/default-mode',{mode});defaultDirty=false;if(snapshot){Object.values(snapshot.modes).forEach(m=>m.default=mode);adviceUpdates.forEach(f=>f());}$('#message').textContent='默认模式已保存，跟随默认的组已更新，人工选择不变。';await refresh();}finally{$('#default-mode').disabled=$('#save-default').disabled=false;}}));
async function withReview(fn){
 if(reviewBusy)throw Error('正在保存或打开结果，请稍候。');
 reviewBusy=true;$('#results').inert=true;
 const controls=['#open','#open-revision','#parent-revision','#save-default','#default-mode'];
 const previous=controls.map(id=>$(id).disabled);controls.forEach(id=>$(id).disabled=true);
 $('#quarantine-panel').inert=true;
 try{return await fn();}finally{reviewBusy=false;$('#results').inert=false;$('#quarantine-panel').inert=false;controls.forEach((id,i)=>$(id).disabled=previous[i]);$('#parent-revision').disabled=!snapshot?.report.revision;}
}
async function openSnapshot(id){
 const [next,history]=await Promise.all([api('/snapshots/'+id),api('/snapshots/'+id+'/history')]);
 snapshot=next;render();
 $('#quarantine-preview-result').replaceChildren();
 const numbers=new Map(history.map((entry,i)=>[entry.id,i+1]));
 const names={analysis:'原始分析',split:'拆组',merge:'合组',subject:'主体改选'};
 const label=entry=>`版本 ${numbers.get(entry.id)} · ${names[entry.action]||entry.action}`+(entry.parent_snapshot_id?` · 基于版本 ${numbers.get(entry.parent_snapshot_id)}`:'');
 options($('#revisions'),history.map(entry=>[entry.id,label(entry)]));$('#revisions').value=id;
 $('#revision-current').textContent='当前查看：'+label(history.find(entry=>entry.id===id));
 $('#revision-panel').hidden=false;
}
function requireSaved(){if(unsaved.size)throw Error('请先保存尚未保存的人工标记，再调整分组、主体或切换版本。');}
async function submitRegroup(action,groups,items){
 requireSaved();
 return withReview(async()=>{
  const signature=JSON.stringify([snapshot.id,action,[...groups].sort(),[...items].sort()]);
  if(pendingRegroup?.signature!==signature)pendingRegroup={signature,key:crypto.randomUUID()};
  const result=await api(`/snapshots/${snapshot.id}/regroup`,{request_key:pendingRegroup.key,action,group_ids:groups,item_keys:items});
  await openSnapshot(result.snapshot_id);pendingRegroup=null;
  $('#message').textContent='分组调整已保存为新版本，原版本和人工标记保留。';
 });
}
async function submitSubject(version,index){
 requireSaved();
 return withReview(async()=>{
  const signature=JSON.stringify([snapshot.id,version,index]);
  if(pendingSubject?.signature!==signature)pendingSubject={signature,key:crypto.randomUUID()};
  const result=await api(`/snapshots/${snapshot.id}/subject`,{request_key:pendingSubject.key,version_id:version,detection_index:index});
  await openSnapshot(result.snapshot_id);pendingSubject=null;
  $('#message').textContent='主体选择已保存为新版本；该张已重新评分，人工标记保留。';
 });
}
$('#open').onclick=()=>act(()=>withReview(async()=>{if(!$('#history').value)return;requireSaved();await openSnapshot($('#history').value);}));
$('#open-revision').onclick=()=>act(()=>withReview(async()=>{requireSaved();await openSnapshot($('#revisions').value);}));
$('#parent-revision').onclick=()=>act(()=>withReview(async()=>{requireSaved();const parent=snapshot?.report.revision?.parent_snapshot_id;if(parent)await openSnapshot(parent);}));
window.addEventListener('beforeunload',event=>{if(unsaved.size){event.preventDefault();event.returnValue='';}});
const quarantineStates={pending:'待执行',moving:'隔离中／待核对，可重试',quarantined:'已隔离',restoring:'恢复中／待核对，可重试',restored:'已恢复',failed:'失败'};
function showQuarantineResult(operation){
 const section=el('section');section.className='panel';
 section.append(el('h3',`操作 ${operation.plan.operation_id.slice(0,8)} · ${operation.created_at.slice(0,19)}`));
 const list=el('ul');
 for(const item of operation.plan.items){const status=operation.states[item.version_id];
  list.append(el('li',`${item.original_path} → ${item.destination_path}\n${quarantineStates[status.state]||status.state}${status.error?'：'+status.error:''}`));
 }section.append(list);
 const values=Object.values(operation.states).map(s=>s.state);
 if(values.some(s=>['pending','moving'].includes(s))){const retry=el('button','核对并重试未完成隔离');retry.onclick=()=>act(()=>confirmQuarantine(operation.plan));section.append(retry);}
 if(values.some(s=>['quarantined','restoring'].includes(s))){const restore=el('button','预览恢复清单');restore.onclick=()=>act(()=>previewRestore(operation.plan.operation_id));section.append(restore);}
 return section;
}
async function loadQuarantineHistory(){
 const operations=await api('/quarantine');
 $('#quarantine-operations').replaceChildren(...operations.map(showQuarantineResult));
 if(!operations.length)$('#quarantine-operations').append(el('p','暂无隔离操作。'));
}
async function previewQuarantine(){
 requireSaved();if(!snapshot)throw Error('请先打开需要复核的分析结果。');
 return withReview(async()=>{
  $('#message').textContent='正在核对拒绝原片的完整内容，NAS 来源可能需要一些时间……';
  const plan=await api(`/snapshots/${snapshot.id}/quarantine-preview`,{});
  const host=$('#quarantine-preview-result');host.replaceChildren();
  host.append(el('h3',`待隔离 ${plan.count} 张 · ${(plan.total_bytes/1024/1024).toFixed(1)} MB`));
  const list=el('ul');for(const item of plan.items)list.append(el('li',`${item.original_path||item.version_id} → ${item.destination_path||'无法确定'}${item.error?'；不能执行：'+item.error:''}`));host.append(list);
  host.append(el('p',plan.ready?'请核对上面的原路径与目标。确认后移动这些原片；不会处理保留和未决定照片。':'没有可执行清单，或存在需要解决的冲突。'));
  const button=el('button','确认隔离上述原片');button.disabled=!plan.ready;
  button.onclick=()=>act(()=>confirmQuarantine(plan));host.append(button);
  $('#message').textContent='预览已生成；尚未移动任何照片。';
 });
}
async function confirmQuarantine(plan){
 requireSaved();
 return withReview(async()=>{
  $('#message').textContent='正在核对并执行隔离，请等待逐项结果……';
  const operation=await api(`/snapshots/${plan.snapshot_id}/quarantine`,{operation_id:plan.operation_id,preview_hash:plan.preview_hash});
  $('#quarantine-preview-result').replaceChildren(showQuarantineResult(operation));
  $('#message').textContent='隔离执行结果已保存，请查看逐项状态；有错误的项目不会伪装成成功。';
  await loadQuarantineHistory();
 });
}
async function previewRestore(oid){
 requireSaved();return withReview(async()=>{
  $('#message').textContent='正在核对恢复路径与文件内容……';
  const plan=await api(`/quarantine/${oid}/restore-preview`,{}),host=$('#quarantine-preview-result');host.replaceChildren();
  host.append(el('h3',`待恢复 ${plan.items.length} 张`));
  const list=el('ul');for(const item of plan.items)list.append(el('li',`${item.quarantine_path} → ${item.original_path}${item.error?'；不能执行：'+item.error:''}`));host.append(list);
  const button=el('button','确认恢复到上述原路径');button.disabled=!plan.ready;button.onclick=()=>act(()=>confirmRestore(plan));host.append(button);
  $('#message').textContent='恢复预览已生成；尚未移动任何照片。';
 });
}
async function confirmRestore(plan){
 requireSaved();return withReview(async()=>{
  $('#message').textContent='正在执行恢复，请等待逐项结果……';
  const operation=await api(`/quarantine/${plan.operation_id}/restore`,{preview_hash:plan.preview_hash});
  $('#quarantine-preview-result').replaceChildren(showQuarantineResult(operation));
  $('#message').textContent='恢复执行结果已保存，请查看逐项状态。';await loadQuarantineHistory();
 });
}
$('#quarantine-preview').onclick=()=>act(previewQuarantine);
$('#quarantine-history').onclick=()=>act(()=>withReview(loadQuarantineHistory));
act(refresh);act(loadQuarantineHistory);setInterval(()=>act(refresh),3000);
