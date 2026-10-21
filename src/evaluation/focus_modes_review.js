// Advice controls never read or write human selection checkboxes.
const adviceModes=['safe','assist','relaxed'];
const defaultMode=document.querySelector('#default-mode');
const modeSections=[...document.querySelectorAll('section')];
function modeSelection(section){
 const override=section.querySelector('.group-mode').value;
 return {mode:override==='inherit'?defaultMode.value:override, mode_override:override};
}
function modePreferences(){return {default_mode:defaultMode.value,mode_version:'focus-advice-v1'};}
function refreshModes(){
 for(const section of modeSections){
  const mode=modeSelection(section).mode;
  const data=modeData[section.dataset.group], result=data.modes[mode];
  const names=keys=>keys.map(k=>data.names[k]).join('、');
  let text=mode==='assist'?'辅助比较：仅供人工选择，不自动推荐。':
   mode==='relaxed'?'宽松推荐（实验）：请人工复核。':'稳妥推荐：保留尺寸检查。';
  if(result.scale_guard_triggered)text+='\n主体尺寸或姿态差异较大，排序可能不可靠。';
  const keys=mode==='assist'?result.ranked:result.recommended;
  text+='\n'+(mode==='assist'?'候选顺序：':'推荐：')+(names(keys)||'暂无，请人工查看');
  if(result.tie_sets.length)text+='\n分数接近：'+result.tie_sets.map(names).join('；');
  if(result.unranked.length)text+='\n未排序：'+names(result.unranked);
  text+='\n相对排序不代表已经合焦；人工选择不会被覆盖。';
  section.querySelector('.mode-result').textContent=text;
 }
}
function prepareModeImport(data){
 const selected=data.default_mode??'safe';
 if(!adviceModes.includes(selected) || (data.mode_version && data.mode_version!=='focus-advice-v1'))
  throw Error('模式设置无效');
 const choices=new Map();
 for(const group of data.groups){
  const override=group.mode_override??(group.mode??'inherit');
  if(!['inherit',...adviceModes].includes(override))throw Error('分组模式无效');
  const effective=override==='inherit'?selected:override;
  if(group.mode!==undefined && group.mode!==effective)throw Error('模式记录不一致');
  choices.set(group.group_id,override);
 }
 return ()=>{
  defaultMode.value=selected;
  modeSections.forEach(s=>s.querySelector('.group-mode').value=choices.get(s.dataset.group)??'inherit');
  refreshModes();
 };
}
defaultMode.addEventListener('change',refreshModes);
modeSections.forEach(s=>s.querySelector('.group-mode').addEventListener('change',refreshModes));
refreshModes();
