// Offline comparison only. No network requests or photo mutations.
document.querySelectorAll('.compare').forEach(panel => {
 const picks=[...panel.querySelectorAll('.pick')];
 const views=[...panel.querySelectorAll('.viewport')];
 const images=views.map(v=>v.querySelector('img'));
 const zoom=panel.querySelector('.zoom'), sync=panel.querySelector('.sync');
 let showingB=false, syncing=false;
 const position=v=>[(v.scrollLeft+v.clientWidth/2)/Math.max(1,v.scrollWidth),
                     (v.scrollTop+v.clientHeight/2)/Math.max(1,v.scrollHeight)];
 function center(v,p){
  v.scrollLeft=p[0]*v.scrollWidth-v.clientWidth/2;
  v.scrollTop=p[1]*v.scrollHeight-v.clientHeight/2;
 }
 function size(i,p){
  images[i].style.width=(images[i].naturalWidth*Number(zoom.value))+'px';
  images[i].style.height=(images[i].naturalHeight*Number(zoom.value))+'px';
  center(views[i],p);
 }
 function load(i,url){
  const p=position(views[i]);
  images[i].onload=()=>size(i,p);
  images[i].src=url;
 }
 function reset(){
  showingB=false;panel.querySelector('.blink-label').textContent='';
  picks[0].selectedIndex=Math.max(0,picks[0].selectedIndex);
  load(0,picks[0].value);load(1,picks[1].value);
 }
 picks[1].selectedIndex=Math.min(1,picks[1].options.length-1);
 picks.forEach(p=>p.addEventListener('change',reset));
 zoom.addEventListener('change',()=>images.forEach((im,i)=>size(i,position(views[i]))));
 views.forEach((v,i)=>v.addEventListener('scroll',()=>{
  if(!sync.checked || syncing)return;
  syncing=true;center(views[1-i],position(v));
  requestAnimationFrame(()=>{syncing=false;});
 }));
 panel.querySelector('.blink').addEventListener('click',()=>{
  showingB=!showingB;load(0,picks[showingB?1:0].value);
  panel.querySelector('.blink-label').textContent='左侧当前：'+(showingB?'B':'A');
 });
 reset();
});
document.querySelector('#import-labels').addEventListener('change',async event=>{
 const message=document.querySelector('#message');
 try {
  const data=JSON.parse(await event.target.files[0].text());
  if(data.report_id!==reportId || ![1,2].includes(data.schema_version??1))throw Error('报告不匹配');
  const sections=[...document.querySelectorAll('section')], seen=new Set(), actions=[];
  for(const group of data.groups){
   const section=sections.find(s=>s.dataset.group===group.group_id);
   if(!section || seen.has(group.group_id))throw Error('分组不匹配');
   seen.add(group.group_id);
   const inputs=[...section.querySelectorAll('article input')];
   if(!Array.isArray(group.best) || new Set(group.best).size!==group.best.length ||
      group.best.some(k=>!inputs.some(i=>i.value===k)))throw Error('照片不匹配');
   const certainty=data.schema_version===2?group.certainty:'uncertain';
   if(!['correct','incorrect','uncertain'].includes(group.grouping) ||
      !['uncertain','similar','tentative','confident','none_acceptable'].includes(certainty) ||
      typeof group.reviewed!=='boolean')throw Error('标注内容无效');
   actions.push(()=>{section.querySelector('.grouping').value=group.grouping;
    section.querySelector('.certainty').value=certainty;
    section.querySelector('.reviewed').checked=group.reviewed;
    inputs.forEach(i=>i.checked=group.best.includes(i.value));});
  }
  actions.forEach(a=>a());message.textContent='已恢复标注。旧格式没有把握信息，请补选后再导出。';
 }catch(e){message.textContent='未导入：'+e.message;}
});
