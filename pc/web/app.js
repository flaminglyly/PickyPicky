const $=id=>document.getElementById(id);
let result, cooldownUntil=0;
let episodePage=1,episodeResultId=null;
const EPISODES_PER_PAGE=10;
const busy={download:false,search:false,merge:false};
let booting=true,downloadTask=null;
function updateCooldown(){const seconds=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000));$("cooldown").textContent=seconds?`限流冷却：还需等待 ${seconds} 秒。到期后由你手动重试，不会自动请求。`:"";for(const id of ["parse","resolve","download","resolve-download","search-drama","search-more"])$(id).disabled=booting||busy[id.startsWith('search')?'search':'download']||seconds>0;}
setInterval(updateCooldown,1000);
async function request(path,data){const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':document.querySelector('meta[name=local-token]').content},body:JSON.stringify(data)});const value=await response.json();if(!response.ok){const error=Error(value.error);error.status=response.status;if(response.status===429){cooldownUntil=Date.now()+(value.retryAfter||300)*1000;updateCooldown();}throw error;}return value;}
function status(message){$('status').textContent=message;}
const laneStatus={download:'status',search:'search-status',merge:'local-status'};
const taskDialogs=[];
const notifiedTasks=new Set();
const taskDialog=document.createElement('dialog');
taskDialog.className='task-dialog';
const dialogTitle=document.createElement('h2'),dialogMessage=document.createElement('p'),dialogClose=document.createElement('button');
dialogTitle.id='task-dialog-title';taskDialog.setAttribute('aria-labelledby',dialogTitle.id);
dialogMessage.id='task-dialog-message';taskDialog.setAttribute('aria-describedby',dialogMessage.id);
dialogClose.textContent='知道了';dialogClose.onclick=()=>taskDialog.close();
taskDialog.append(dialogTitle,dialogMessage,dialogClose);document.body.append(taskDialog);
function showNextTaskDialog(){
 if(taskDialog.open||!taskDialogs.length)return;
 const next=taskDialogs.shift();dialogTitle.textContent=next.title;dialogMessage.textContent=next.message;
 taskDialog.dataset.state=next.state;taskDialog.showModal();dialogClose.focus();
}
taskDialog.addEventListener('close',()=>showNextTaskDialog());
function setTaskState(lane,state){
 const element=$(laneStatus[lane]);if(element){element.dataset.taskState=state;element.setAttribute('aria-live','polite');}
}
function notifyTask(job,popup=true){
 if(job.action==='local-folder')return;
 const value=job.value||{};
 const interrupted=job.state==='failed'||job.cancelRequested||/队列已停止|失败 [1-9]/.test(value.message||'');
 const state=interrupted?'problem':'success';setTaskState(job.lane,state);
 if(!popup||notifiedTasks.has(job.id))return;
 notifiedTasks.add(job.id);
 const name={search:'剧名搜索',parse:'目录解析',batch:'解析下载',merge:'视频合并','local-merge':'视频合并'}[job.action]||'任务';
 taskDialogs.push({state,title:name+(interrupted?' · 需要注意':' · 已完成'),message:job.error||value.message||(value.path?`已保存：${value.path}`:'任务已正常完成。')});
 showNextTaskDialog();
}
const topTaskProgress={search:null,download:null,merge:null};
function renderTaskSummary(){
 const box=$('task-summary');box.dataset.taskState=Object.values(busy).some(Boolean)?'running':'idle';
 box.replaceChildren();
 for(const [lane,name] of Object.entries({search:'剧名搜索',download:'解析下载',merge:'视频合并'})){
  const row=document.createElement('span');row.className='task-summary-row';
  const title=document.createElement('strong');title.textContent=name+'：';row.append(title);
  const info=topTaskProgress[lane];
  const detail=document.createElement('span');
  detail.textContent=busy[lane]?(info?.message||'正在准备任务…'):'空闲';row.append(detail);
  if(busy[lane]&&info?.title){const drama=document.createElement('small');drama.textContent='《'+info.title+'》';row.append(drama);}
  if(busy[lane]&&Number.isFinite(info?.percent)){
   const bar=document.createElement('progress');bar.max=100;bar.value=Math.max(0,Math.min(100,info.percent));bar.setAttribute('aria-label',name+'当前阶段进度');
   const text=document.createElement('small');text.textContent=`当前阶段 ${bar.value}%`;row.append(bar,text);
  }
  box.append(row);
 }
}
function lock(value,lane='download'){
 if(value&&!busy[lane])topTaskProgress[lane]=null;
 busy[lane]=value;
 if(value)setTaskState(lane,'running');
 else if($(laneStatus[lane])?.dataset.taskState==='running')setTaskState(lane,'idle');
 const controls={download:['parse','resolve','download','resolve-download','all','all-page','provider','share'],search:['search-drama','search-more','search-keyword'],merge:['merge','choose-folder','append-files','local-sort','local-merge','compare-files','merge-mode','output-name','local-select-all','local-clear']};
 for(const [group,ids] of Object.entries(controls))for(const id of ids)$(id).disabled=booting||busy[group];
 for(const check of document.querySelectorAll('#episodes input'))check.disabled=booting||busy.download;
 for(const button of document.querySelectorAll('[data-load-catalog]'))button.disabled=booting||busy.download;
 renderTaskSummary();
 updateCooldown();
 updateLocalSelection();
}
const taskActions=new Set(['search','parse','batch','merge','local-folder','local-merge']);
const taskLane=action=>action==='search'?'search':['merge','local-folder','local-merge'].includes(action)?'merge':'download';
function taskProgress(job){
 const progress=job.progress||{};
 const defaultMessage={search:'正在查询剧名搜索结果…',parse:'正在解析分享链接与剧集目录…',batch:'正在准备剧集队列…',merge:'正在准备合并…','local-merge':'正在准备合并…','local-folder':'等待选择本地视频文件…'};
 topTaskProgress[job.lane]={message:job.state==='running'?(progress.message||defaultMessage[job.action]||'运行中…'):(job.error||job.value?.message||'已完成'),percent:progress.percent,title:progress.result?.title};
 renderTaskSummary();
 if(job.lane==='merge'&&['merge','local-merge'].includes(job.action)){
  const p=job.progress||{};$('merge-progress-box').hidden=false;
  if(p.message)$('local-status').textContent=p.message;
  if(job.state==='running'&&typeof p.percent==='number'){$('merge-progress').value=p.percent;$('merge-progress-text').textContent=` ${p.percent}%`;}
  else if(job.state==='running'){$('merge-progress').removeAttribute('value');$('merge-progress-text').textContent=' 正在准备…';}
  else {$('merge-progress').value=job.state==='done'?100:(p.percent||0);$('merge-progress-text').textContent=job.state==='done'?' 已完成':' 已中断';}
 }
 if(job.action==='batch'){
  downloadTask=job.id;
  if(job.progress?.result){result=job.progress.result;render();}
  if(job.progress?.message)status(job.progress.message);
 }
}
async function followTask(job,popup=true){
 const messageId=job.lane==='merge'?'local-status':job.lane==='search'?'search-status':'status';
 if(job.state==='running'&&job.action!=='batch')$(messageId).textContent='后台任务运行中，可切换页面或使用其他功能…';
 while(job.state==='running'){
  taskProgress(job);
  await new Promise(resolve=>setTimeout(resolve,1000));
  try{job=await request('task',{id:job.id});}
  catch(error){if(error.status)throw error;$(messageId).textContent='暂时无法连接本地服务，正在重新连接后台任务…';topTaskProgress[job.lane]={message:'连接中断，正在重新连接；进度暂未更新'};renderTaskSummary();}
 }
 taskProgress(job);
 if(job.retryAfter)cooldownUntil=Date.now()+job.retryAfter*1000;
 notifyTask(job,popup);
 if(job.state==='failed')throw Error(job.error);
 return job.value;
}
async function api(path,data){
 if(!taskActions.has(path))return request(path,data);
 return followTask(await request('task-start',{action:path,data}));
}

function updateEpisodePager(){
 const total=result.episodes.length,pages=Math.max(1,Math.ceil(total/EPISODES_PER_PAGE));
 const selected=result.episodes.filter(e=>e.selected).length;
 $('episode-page-info').textContent=`第 ${episodePage} / ${pages} 页 · 共 ${total} 集 · 已选 ${selected} 集（含其他页）`;
 $('episode-prev').disabled=episodePage===1;
 $('episode-next').disabled=episodePage===pages;
 $('episode-page').replaceChildren();
 for(let page=1;page<=pages;page++){const option=document.createElement('option');option.value=page;option.textContent=`第 ${page} 页`;option.selected=page===episodePage;$('episode-page').append(option);}
 $('all').checked=total>0&&selected===total;
 $('all').indeterminate=selected>0&&selected<total;
 const current=result.episodes.slice((episodePage-1)*EPISODES_PER_PAGE,episodePage*EPISODES_PER_PAGE);
 const checked=current.filter(e=>e.selected).length;
 $('all-page').checked=current.length>0&&checked===current.length;
 $('all-page').indeterminate=checked>0&&checked<current.length;

}
function changeEpisodePage(page){if(!result)return;episodePage=page;render();}
$('episode-prev').onclick=()=>changeEpisodePage(episodePage-1);
$('episode-next').onclick=()=>changeEpisodePage(episodePage+1);
$('episode-page').onchange=()=>changeEpisodePage(Number($('episode-page').value));
function render(){
 if(episodeResultId!==result.id){episodePage=1;episodeResultId=result.id;}
 episodePage=Math.max(1,Math.min(episodePage,Math.max(1,Math.ceil(result.episodes.length/EPISODES_PER_PAGE))));
 updateEpisodePager();
 $('episode-download-hint').hidden=true;
 $('result').hidden=false;$('title').textContent=result.title;
 $('summary').textContent=`页面标注 ${result.count??'未知'} 集 · 已获得 ${result.episodes.length} 个剧集 ID${result.downloadDirectory?' · 下载目录：'+result.downloadDirectory:''}`;
 $('notice').textContent=result.notice;$('episodes').replaceChildren();
 for(const e of result.episodes.slice((episodePage-1)*EPISODES_PER_PAGE,episodePage*EPISODES_PER_PAGE)){const label=document.createElement('label');label.className='episode';const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.dataset.id=e.id;checkbox.checked=e.selected||false;checkbox.disabled=busy.download;
 checkbox.onchange=()=>{e.selected=checkbox.checked;updateEpisodePager();};const name=document.createTextNode(` 第 ${e.number} 集`);const detail=document.createElement('small');detail.textContent=`ID ${e.id}`;
 const state=document.createElement('small');state.textContent=e.error||e.saved||(e.video?(e.video.kind==='app'?`App 资源 · ${e.video.codec||'自动编码'} · 下载处理后校验`:e.video.kind==='preview'?'分享预览':e.video.kind==='direct'?`${e.video.source==='web-public'?'官网公开 MP4':'兼容 MP4'} · ${e.video.duration??'未知'} 秒 · 下载后校验`:e.video.kind==='encrypted'?`加密 DASH · ${e.video.duration??'未知'} 秒 · 暂不支持下载`:'视频完整性未知'):'尚未解析播放地址');if(e.video?.note)state.textContent+=' · '+e.video.note;if(e.error)state.className='error';label.append(checkbox,name,detail,state);$('episodes').append(label);}
}
$('parse').onclick=async()=>{if(booting||busy.download||Date.now()<cooldownUntil)return;lock(true);status('正在解析页面及剧集目录…');try{result=await api('parse',{share:$('share').value});render();status('解析完成。请选择需要验证的剧集。');}catch(e){status(e.message);}finally{lock(false);}};
$('all-page').onchange=()=>{if(!result||booting||busy.download)return;for(const e of result.episodes.slice((episodePage-1)*EPISODES_PER_PAGE,episodePage*EPISODES_PER_PAGE))e.selected=$('all-page').checked;render();};
$('all').onchange=()=>{if(!result)return;for(const e of result.episodes)e.selected=$('all').checked;render();};
$('cancel').onclick=async()=>{if(!downloadTask)return;try{await request('task-cancel',{id:downloadTask});status('将在当前请求结束后停止队列。');}catch(error){status(error.message);}};
async function queue(type){
 if(booting||busy.download||!result||Date.now()<cooldownUntil)return;
 const ids=result.episodes.filter(e=>e.selected).map(e=>e.id);
 if(!ids.length){status('请先选择剧集。');return;}
 lock(true);status('正在提交后台队列…');
 try{
  const data=await api('batch',{resultId:result.id,episodeIds:ids,type,provider:$('provider').value});
  result=data.result;render();status(data.message);
  if(data.retryAfter)cooldownUntil=Date.now()+data.retryAfter*1000;
 }catch(error){status(error.message);}finally{downloadTask=null;lock(false);}
}
$('resolve').onclick=()=>queue('resolve');
$('download').onclick=()=>queue('download');
$('resolve-download').onclick=()=>queue('resolve-download');

api("status",{}).then(state=>{cooldownUntil=Date.now()+state.retryAfter*1000;updateCooldown();}).catch(error=>status(error.message));

$("provider").onchange=()=>status("已切换方案，请重新解析所选剧集；已保存的文件会保留。");

$('merge').onclick=async()=>{
 if(booting||busy.merge)return;
 if(!result){$('local-status').textContent='请先在红果视频下载中解析目录并选择剧集。';return;}
 const selected=result.episodes.filter(e=>e.selected);
 if(selected.length<2){$('local-status').textContent='请至少选择两集已下载且编号连续的剧集。';return;}
 lock(true,'merge');$('local-status').textContent='正在按集号无损合并并校验文件，请等待…';
 try{
  const data=await api('merge',{resultId:result.id,episodeIds:selected.map(e=>e.id)});
  $('local-status').textContent=(`合并完成 · 第 ${data.episodes[0]}—${data.episodes.at(-1)} 集 · ${data.duration.toFixed(3)} 秒 · 已保存：${data.path}`);
 }catch(error){$('local-status').textContent=error.message;}finally{lock(false,'merge');refreshMergeHistory();}
};

let localLibrary=null,localFiles=[],customOutputName=false;
const nameOrder=new Intl.Collator('zh-CN',{numeric:true,sensitivity:'base'});
function updateLocalSelection(){
 const count=localFiles.filter(f=>f.selected).length;
 $('local-selection').textContent=`已选择 ${count} / ${localFiles.length} 个文件（至少选择 2 个）`;
 $('local-merge').disabled=booting||busy.merge||count<2;
 const first=localFiles.find(f=>f.selected);
 $('merge-destination').textContent=first?.sourceFolder?'合并结果保存到：'+first.sourceFolder:'合并结果保存到第一个勾选视频所在目录。';
}
for(const [id,selected] of [['local-select-all',true],['local-clear',false]])$(id).onclick=()=>{if(booting||busy.merge)return;for(const file of localFiles)file.selected=selected;renderLocalFiles();};
function renderLocalFiles(){
 updateLocalSelection();
 $('local-files').replaceChildren();
 localFiles.forEach((file,index)=>{
  const row=document.createElement('div');row.className='local-file';
  const label=document.createElement('label'),check=document.createElement('input');
  check.type='checkbox';check.checked=file.selected;check.disabled=busy.merge;
  check.onchange=()=>{file.selected=check.checked;updateLocalSelection();};
  label.append(check,document.createTextNode(` ${file.name} · ${(file.bytes/1048576).toFixed(1)} MB${file.sourceFolder?' · '+file.sourceFolder:''}`));row.append(label);
  const actions=document.createElement('div');actions.className='local-file-actions';
  for(const [text,target] of [['移到顶端',0],['上移',index-1],['下移',index+1],['移到末端',localFiles.length-1]]){
   const button=document.createElement('button');button.className='secondary';button.textContent=text;
   button.disabled=booting||busy.merge||target===index||target<0||target>=localFiles.length;
   button.onclick=()=>{
    if(booting||busy.merge)return;
    localFiles.splice(target,0,localFiles.splice(index,1)[0]);
    renderLocalFiles();
    $('local-files').children[target]?.scrollIntoView({block:'nearest'});
   };actions.append(button);
  }
  row.append(actions);
  $('local-files').append(row);
 });
}
async function chooseLocalFiles(append=false){
 if(booting||busy.merge)return;lock(true,'merge');renderLocalFiles();$('local-status').textContent='请在系统弹窗中选择需要合并的视频，支持 Command 多选、Shift 连选…';
 try{
  const data=await api('local-folder',append&&localLibrary?{libraryId:localLibrary}:{});
  if(data.cancelled){$('local-status').textContent='已取消选择。';return;}
  localLibrary=data.libraryId;
  const added=data.files.filter(f=>!append||!localFiles.some(old=>old.id===f.id)).map(f=>({...f,selected:true})).sort((a,b)=>nameOrder.compare(a.name,b.name));
  localFiles=append?[...localFiles,...added]:added;
  if(!append)customOutputName=false;
  const stamp=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date()).replace(/[-: ]/g,'').replace(/^(\d{8})(\d{6})$/,'$1-$2');
  if(!append)$('output-name').value=`${data.folderName}-${stamp}.mp4`;
  $('local-folder-name').textContent=`合并列表 · ${localFiles.length} 个 MP4`;
  $('local-status').textContent='已加入所选视频，重复文件自动跳过。可继续追加其他目录的视频并调整顺序。';
 }catch(error){$('local-status').textContent=error.message;}finally{lock(false,'merge');renderLocalFiles();refreshMergeHistory();}
}
$('choose-folder').onclick=()=>chooseLocalFiles();
$('append-files').onclick=()=>chooseLocalFiles(true);
$('local-sort').onclick=()=>{if(booting||busy.merge)return;localFiles.sort((a,b)=>nameOrder.compare(a.name,b.name));renderLocalFiles();};
let comparedSelection='';
const comparisonKey=()=>JSON.stringify([localLibrary,localFiles.filter(f=>f.selected).map(f=>f.id)]);
async function compareSelected(){
 const key=comparisonKey();
 const result=await api('local-compare',{libraryId:localLibrary,fileIds:localFiles.filter(f=>f.selected).map(f=>f.id)});
 const box=$('merge-comparison');box.replaceChildren();
 const summary=document.createElement('p');
 summary.textContent=`参考文件：${result.reference} · ${result.majorityCount}/${result.total} 个文件格式相同。${result.tied?'最大组数量并列，采用列表中最先出现的组。':''}`;
 box.append(summary);
 const details=document.createElement('pre');details.style.whiteSpace='pre-wrap';details.textContent=Object.entries(result.target).map(([k,v])=>`${k}: ${v}`).join(' · ');box.append(details);
 for(const file of result.files.filter(f=>f.different)){
  const item=document.createElement('p');item.textContent=`第 ${file.index} 项 ${file.name}：`+file.differences.map(d=>`${d.field}：${d.value??'未标明'} → ${d.target??'未标明'}`).join('；');box.append(item);
 }
 if(!result.files.some(f=>f.different)){const item=document.createElement('p');item.textContent='所选文件主要格式一致，策略 1 将保留源编码。';box.append(item);}
 comparedSelection=key;
 $('local-status').textContent='比较完成。请查看差异并选择合并策略，再点击合并。';
}
$('compare-files').onclick=async()=>{if(booting||busy.merge)return;lock(true,'merge');try{await compareSelected();}catch(e){$('local-status').textContent=e.message;}finally{lock(false,'merge');renderLocalFiles();}};
$('local-merge').onclick=async()=>{
 if(booting||busy.merge)return;
 const ids=localFiles.filter(f=>f.selected).map(f=>f.id);
 if(ids.length<2){$('local-status').textContent='请至少勾选两个 MP4 文件。';return;}
 lock(true,'merge');renderLocalFiles();$('local-status').textContent=$('merge-mode').value==='stream-copy'?'正在按列表顺序无损合并并完整校验，请等待…':$('merge-mode').value==='majority'?'正在处理差异文件并合并，随后完整校验，请等待…':'正在统一编码并兼容合并，随后完整校验；耗时与总时长相关，请等待…';
 try{
  if(comparedSelection!==comparisonKey()){await compareSelected();return;}
  const data=await api('local-merge',{libraryId:localLibrary,fileIds:ids,mode:$('merge-mode').value,outputName:customOutputName?$('output-name').value:null});
  $('output-name').value=data.path.split('/').at(-1);
  await refreshMergeHistory();
  $('local-status').textContent=`合并成功 · ${data.count} 个文件 · ${data.duration.toFixed(3)} 秒 · 已保存：${data.path}`;
 }catch(error){$('local-status').textContent=error.message;}finally{lock(false,'merge');renderLocalFiles();refreshMergeHistory();}
};

$('output-name').oninput=()=>{customOutputName=true;};
async function refreshMergeHistory(){
 try{
  const {records}=await api('merge-history',{});
  $('merge-history').replaceChildren();
  $('history-status').textContent=records.length?'最近 100 条记录 · 时间为北京时间，重启后保留。':'暂无合并记录。';
  for(const item of records){
   const entry=document.createElement('article');entry.className='history-item';
   const title=document.createElement('strong');title.textContent=item.path?.split('/').at(-1)||'合并失败';
   const detail=document.createElement('p');detail.textContent=`${item.createdAt.replace('T',' ')} · ${item.sources.length?item.sources.length+' 个文件':'历史文件（原始顺序未记录）'} · ${item.status==='success'?(item.exists?'已保存':'文件已移动或删除'):'失败 · '+item.errorType}`;
   const path=document.createElement('p');path.textContent=item.path||'';
   const sources=document.createElement('details'),summary=document.createElement('summary');summary.textContent=item.sources.length?'查看源文件顺序':'旧文件没有源文件顺序记录';sources.append(summary);
   const list=document.createElement('ol');for(const name of item.sources){const li=document.createElement('li');li.textContent=name;list.append(li);}sources.append(list);
   entry.append(title,detail,path,sources);$('merge-history').append(entry);
  }
 }catch(error){$('history-status').textContent=error.message;}
}
$('refresh-history').onclick=refreshMergeHistory;
refreshMergeHistory();

function routePage(){
 const hash=location.hash;
 const page=hash==='#versions'?'versions':(['#local-merge-section','#merge-history-section','#merge'].includes(hash)?'merge':'download');
 for(const name of ['download','merge','versions'])$(name+'-page').hidden=name!==page;
 for(const name of ['download','merge']){
  const link=$('nav-'+name);link.classList.toggle('active',name===page);
  if(name===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
 }
 for(const [id,selected] of [['subnav-local',hash!=='#merge-history-section'],['subnav-history',hash==='#merge-history-section']]){
  $(id).classList.toggle('active',page==='merge'&&selected);
  if(page==='merge'&&selected)$(id).setAttribute('aria-current','location');else $(id).removeAttribute('aria-current');
 }
 const downloadLinks=[['subnav-search','#drama-search'],['subnav-share','#share-search'],['subnav-episodes','#episode-download']];
 for(const [id,target] of downloadLinks){
  const selected=page==='download'&&(hash===target||((!hash||hash==='#download')&&target==='#drama-search'));
  $(id).classList.toggle('active',selected);
  if(selected)$(id).setAttribute('aria-current','location');else $(id).removeAttribute('aria-current');
 }
 if(page==='download'&&downloadLinks.some(([,target])=>target===hash))$(hash.slice(1)).scrollIntoView();
 if(page==='merge'&&hash==='#merge-history-section')$('merge-history-section').scrollIntoView();
}
window.addEventListener('hashchange',routePage);routePage();
async function loadVersions(){
 try{
  const response=await fetch('/versions.json');if(!response.ok)throw Error('无法读取版本说明。');
  const data=await response.json();
  $('version-link').textContent=`v${data.version} · 版本说明`;
  for(const release of data.releases){
   const article=document.createElement('article');article.className='release-item';
   const heading=document.createElement('h3');heading.textContent=`v${release.version} · ${release.title}`;
   const date=document.createElement('p');date.textContent=release.date;article.append(heading,date);
   if(release.note){const note=document.createElement('p');note.textContent=release.note;article.append(note);}
   const list=document.createElement('ul');for(const change of release.changes){const item=document.createElement('li');item.textContent=change;list.append(item);}article.append(list);$('version-list').append(article);
  }
 }catch(error){$('version-list').textContent=error.message;}
}
loadVersions();

let searchKeyword='',searchPage=0,searchItems=[],searchDisplayPage=1;
function renderSearchResults(){
 searchItems.sort((a,b)=>(b.matchScore??0)-(a.matchScore??0));
 const pages=Math.max(1,Math.ceil(searchItems.length/3));
 searchDisplayPage=Math.max(1,Math.min(searchDisplayPage,pages));
 $('search-prev').disabled=searchDisplayPage===1;
 $('search-next').disabled=searchDisplayPage===pages;
 $('search-page-info').textContent=`第 ${searchDisplayPage} / ${pages} 页 · 已找到 ${searchItems.length} 条相关结果 · 每页 3 条`;
 $('search-results').replaceChildren();
 for(const item of searchItems.slice((searchDisplayPage-1)*3,searchDisplayPage*3)){

  const card=document.createElement('article');card.className='search-card';
  const poster=document.createElement('div');poster.className='search-poster';
  const missing=document.createElement('span');missing.textContent='海报暂不可用';poster.append(missing);
  if(item.poster){const img=document.createElement('img');img.src=item.poster;img.alt=item.title+' 海报';img.loading='lazy';img.referrerPolicy='no-referrer';img.onload=()=>{missing.hidden=true;};img.onerror=()=>{img.remove();missing.hidden=false;};poster.append(img);}
  const body=document.createElement('div');body.className='search-card-body';
  const title=document.createElement('h3');title.textContent=item.title;
  const count=document.createElement('p');count.textContent=item.episodeCount?`共 ${item.episodeCount} 集`:'集数以目录为准';
  const intro=document.createElement('p');intro.className='search-intro';intro.textContent=item.description;
  const link=document.createElement('a');link.href=item.shareLink;link.textContent='打开官网剧集页面';link.target='_blank';link.rel='noopener noreferrer';
  const actions=document.createElement('div');actions.className='toolbar';
  const copy=document.createElement('button');copy.className='secondary';copy.textContent='复制官网链接';copy.onclick=async()=>{try{await navigator.clipboard.writeText(item.shareLink);$('search-status').textContent='已复制：'+item.shareLink;}catch{$('search-status').textContent='请复制链接：'+item.shareLink;}};
  const use=document.createElement('button');use.textContent='载入剧集目录';use.dataset.loadCatalog='';use.disabled=busy.download;
  use.onclick=async()=>{
   if(booting||busy.download||Date.now()<cooldownUntil)return;
   lock(true);$('share').value=item.shareLink;status('正在读取官网剧集目录…');
   try{result=await api('parse',{share:item.shareLink});render();status(`已载入《${result.title}》的 ${result.episodes.length} 集目录。`);$('result').scrollIntoView();}
   catch(error){status(error.message);}finally{lock(false);}
  };
  actions.append(copy,use);body.append(title,count,intro,link,actions);card.append(poster,body);$('search-results').append(card);
 }
}
async function searchDrama(more=false){
 if(booting||busy.search||Date.now()<cooldownUntil)return;
 const keyword=more?searchKeyword:$('search-keyword').value.trim();
 if(!keyword){$('search-status').textContent='请输入短剧名称。';return;}
 $('official-search').href='https://hongguoduanju.com/search/'+encodeURIComponent(keyword);
 lock(true,'search');$('search-status').textContent='正在查询红果官网…';
 try{
  const data=await api('search',{keyword,page:more?searchPage+1:1});
  searchKeyword=keyword;searchPage=data.page;
  searchItems=more?[...searchItems,...data.items.filter(item=>!searchItems.some(old=>old.seriesId===item.seriesId))]:data.items;
  if(!more)searchDisplayPage=1;
  renderSearchResults();$('search-more').hidden=!data.hasMore;
  $('search-status').textContent=searchItems.length?`已找到 ${searchItems.length} 条相关结果 · 已加载结果按匹配度排序，请核对海报和剧名。`:'暂未找到相关结果，请尝试缩短剧名或换用关键词。';
 }catch(error){$('search-status').textContent=error.message;}finally{lock(false,'search');}
}
$('search-prev').onclick=()=>{searchDisplayPage--;renderSearchResults();};
$('search-next').onclick=()=>{searchDisplayPage++;renderSearchResults();};
$('search-drama').onclick=()=>searchDrama();$('search-more').onclick=()=>searchDrama(true);
$('search-keyword').addEventListener('keydown',event=>{if(event.key==='Enter')searchDrama();});

async function restoreTasks(){
 try{
  const state=await request('tasks',{});
  for(const job of state.tasks){
   const lane=job.lane;lock(true,lane);
   // Each lane recovers independently; a long merge must not block search recovery.
   (async()=>{
    try{
     const data=await followTask(job,job.state==='running');
     if(job.action==='batch'){result=data.result;render();status(data.message);if(data.retryAfter)cooldownUntil=Date.now()+data.retryAfter*1000;}
     else if(job.action==='parse'){result=data;render();status('已恢复剧集目录。');}
     else if(job.action==='search'){
      searchKeyword=data.keyword;searchPage=data.page;searchItems=data.items;
      $('search-keyword').value=searchKeyword;renderSearchResults();$('search-more').hidden=!data.hasMore;
      $('search-status').textContent=`已恢复 ${searchItems.length} 条搜索结果。`;
     }else if(job.action==='local-folder'&&!data.cancelled){
      localLibrary=data.libraryId;localFiles=data.files.map(f=>({...f,selected:data.selectionMode==='files'})).sort((a,b)=>nameOrder.compare(a.name,b.name));
      $('local-folder-name').textContent=`合并列表 · ${localFiles.length} 个 MP4`;
      $('local-status').textContent='已恢复所选视频，请确认文件和合并顺序。';
     }else if(['merge','local-merge'].includes(job.action)){
      $('local-status').textContent=`合并完成 · ${data.duration.toFixed(3)} 秒 · 已保存：${data.path}`;refreshMergeHistory();
     }
    }catch(error){$(lane==='merge'?'local-status':lane==='search'?'search-status':'status').textContent=error.message;}
    finally{if(lane==='download')downloadTask=null;lock(false,lane);renderLocalFiles();}
   })();
  }
 }catch(error){status(error.message);}
 finally{booting=false;lock(busy.download);renderLocalFiles();}
}
lock(false);restoreTasks();
