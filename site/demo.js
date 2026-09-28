import {TEACHING_NOTICE,STORAGE_PREFIX,escapeHTML as e,safeURL,createState,restoreState,updateState,applySupplement,isAvailable,findingsFor,buildReport,reportHTML,buildBundleEntries,sha256} from './demo-engine.js';
import {makeZip} from './zip.js';
import {entryCaseID,caseURL} from './entry.js';

const $ = (selector) => document.querySelector(selector);
const app = $('#app');
const roleLabels = {museum:'博物馆',collection:'收藏者',auction:'拍卖行'};
const roleEnglish = {museum:'MUSEUM RESEARCH',collection:'COLLECTION RECORDS',auction:'CATALOGUE PREPARATION'};
const roleTasks = {museum:'建立可核对的编目与研究记录，留下照片不能支持的判断。',collection:'整理对象资料与观察，把来源记录和独立意见分开保存。',auction:'准备有出处的图录材料，明确描述、条件与证据缺口。'};
const stageNames = ['案卷与编目','图像与观察','资料与证据','方法与研究','补证与版本','复核与导出'];
const statusLabels = {supported:'有资料支撑',limited:'证据有限',contradictory:'材料存在矛盾',missing:'仍缺证据',consistent:'记录一致',conflicting:'记录冲突',needs_review:'待复核'};
const reviewLabels = {not_reviewed:'尚未记录人工复核',reviewed:'已记录使用者复核意见',needs_more_evidence:'使用者要求继续补证',stale:'案卷已改变，复核记录需更新'};
const skillLabels = {'ceramic-route':'预审与任务路由','ceramic-research-record':'陶瓷研究记录','bluewhite-attribution-test':'青花归属检验','condition-hypothesis-test':'状况假设核查','provenance-evidence-audit':'来源证据审计','documentary-evidence-audit':'文献证据核查','evidence-revise':'补证与修订'};
let cases = [], skills = [], current = null, state = null, stage = 0, selectedImage = '', selectedObservation = '', selectedDoc = '', selectedSkill = '', citationHighlight = null, highlightedSource = '', zoom = 1, drawMode = false, draftRegion = null, busy = false, snapshotFrom = null, snapshotTo = null, toastTimer;
let observationEditingID = null, observationDraft = null;

function clearObservationEditor() {
  observationEditingID=null; observationDraft=null; drawMode=false; draftRegion=null;
}
function captureObservationDraft() {
  const form=$('#observation-form'); if (!form || !current) return;
  const data=new FormData(form), bounds={};
  for (const key of ['x','y','width','height']) bounds[key]=String(data.get(key) ?? '');
  observationDraft={image_id:selectedImage,title:String(data.get('title') || ''),text:String(data.get('text') || ''),bounds};
}
function regionFromDraft() {
  if (!observationDraft) return null;
  const region={};
  for (const key of ['x','y','width','height']) {
    if (observationDraft.bounds[key]==='') return null;
    region[key]=Number(observationDraft.bounds[key])/100;
  }
  if (!Object.values(region).every(Number.isFinite) || region.x<0 || region.y<0 || region.width<=0 || region.height<=0 ||
      region.x+region.width>1.000001 || region.y+region.height>1.000001) return null;
  return region;
}
function refreshAnnotationDraft() {
  const layer=$('#annotation-layer');if (!layer) return;
  const observations=state.observations.filter(o=>o.image_id===selectedImage && o.region && !(o.id===observationEditingID && draftRegion));
  layer.innerHTML=observations.map(o=>rectSVG(o.region,o.id===selectedObservation)).join('')+(draftRegion?rectSVG(draftRegion,true):'');
}
function editObservation(id) {
  const observation=state.observations.find(o=>o.id===id && o.image_id===selectedImage && o.origin==='browser_user');
  if (!observation) return;
  observationEditingID=id; selectedObservation=id; drawMode=false; draftRegion=normalRegion(observation.region);
  observationDraft={image_id:selectedImage,title:observation.title || '',text:observation.text || '',
    bounds:Object.fromEntries(Object.entries(draftRegion).map(([key,value])=>[key,String(Math.round(value*100))]))};
  render(); $('#observation-title')?.focus();
}

function toast(message) {
  const box = $('#toast'); box.textContent = message; box.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(()=>box.classList.remove('show'),4500);
}
function save() {
  try { localStorage.setItem(STORAGE_PREFIX + current.id,JSON.stringify(state)); }
  catch { toast('浏览器不能保存本地记录；当前编辑仍可直接导出。'); }
}
function getStored(pack) {
  try { return restoreState(pack,JSON.parse(localStorage.getItem(STORAGE_PREFIX + pack.id) || 'null')); }
  catch { return createState(pack); }
}
function commit(patch,action) { state = updateState(state,patch,action); snapshotTo=null; save(); render(); }
function visibleImages() { return current.images.filter(i=>isAvailable(i,state)); }
function visibleDocuments() { return current.documents.filter(d=>isAvailable(d,state)); }
function objectURL() { return current.object_url || current.object?.url || ''; }
function accession() { return current.accession_number || current.object?.accession_number || state.catalogue.inventory_number || ''; }
function role() { return current.role || current.workflow; }
function attrs(condition) { return condition ? ' selected' : ''; }
function external(url,label) { return safeURL(url) ? `<a href="${e(safeURL(url))}" target="_blank" rel="noreferrer">${e(label)} <span aria-hidden="true">↗</span></a>` : e(label); }
function field(name,label,type='input',wide=false) {
  const value = e(state.catalogue[name] || '');
  return `<div class="field${wide?' wide':''}"><label for="field-${name}">${label}</label>${type==='textarea'?`<textarea id="field-${name}" name="${name}" maxlength="2500">${value}</textarea>`:`<input id="field-${name}" name="${name}" value="${value}" maxlength="500">`}</div>`;
}
function selectCase(id,withToast=false) {
  const pack = cases.find(c=>c.id===id); if (!pack) return;
  clearObservationEditor();
  current = pack; state = getStored(pack); stage = 0; selectedImage = visibleImages()[0]?.id || ''; selectedDoc = visibleDocuments()[0]?.id || ''; selectedSkill = skills[0]?.id || ''; selectedObservation = ''; citationHighlight = null; highlightedSource = ''; zoom = 1; snapshotFrom = null; snapshotTo = null;
  history.replaceState(null,'',caseURL(location.href, pack.id)); render();
  if (withToast) toast('已打开完整教学案卷，图片与资料已准备好。');
}
function setStage(next) {
  const target=Math.max(0,Math.min(stageNames.length-1,Number(next)));
  if (target!==stage) clearObservationEditor(); else captureObservationDraft();
  stage=target;
  render(); $('#main-content')?.focus({preventScroll:true}); window.scrollTo({top:0,behavior:'smooth'});
}
function chooser() {
  return `<main class="chooser" id="main-content" tabindex="-1"><div class="chooser-title"><div><span class="eyebrow">A COMPLETE DOSSIER, READY TO EXPLORE</span><h1>从一件器物，走完整条证据链。</h1><p>选择你的业务场景。每套案卷已准备好公开图像、定位资料、观察与研究示例；无需上传，也无需配置模型。</p></div><span class="vertical-note">观器 · 据证 · 留痕</span></div><div class="choice-grid">${cases.map((pack,index)=>`<article class="case-card"><div class="case-cover"><img src="${e(pack.images[0]?.file)}" alt="${e(pack.title)}的公开馆藏图像" loading="${index===0?'eager':'lazy'}"><span class="role-tag">${e(roleLabels[pack.role || pack.workflow])}场景</span></div><div class="case-card-body"><span class="eyebrow">${e(roleEnglish[pack.role || pack.workflow])}</span><h2>${e(pack.title)}</h2><p>${e(roleTasks[pack.role || pack.workflow])}</p><div class="case-materials"><span>${pack.images.length} 张公开图像</span><span>${pack.documents.length} 份预置资料</span><span>${pack.findings.length} 项研究示例</span></div><button class="button primary block" data-open-case="${e(pack.id)}">进入完整体验 <span aria-hidden="true">→</span></button></div></article>`).join('')}</div><div class="chooser-how"><div><h3>三分钟体验，所有材料都在案卷里</h3><p>先查看观察与资料，再打开方法包和研究示例；纳入预置补充件后比较版本，填写自己的复核意见，最后下载包含图像、原文和校验清单的案卷包。研究示例由项目人工编写，页面不会生成鉴定结论。</p></div><div class="process-inline">观察 → 据证 → 补证 → 复核 → 交接</div></div><p class="case-footnote">三套案卷均使用 The Metropolitan Museum of Art 已知身份的公开馆藏；是不同业务视角的教学材料，不代表馆方、真实收藏委托或实际拍卖项目。</p></main>`;
}
function render() {
  app.setAttribute('aria-busy','false');
  if (!current) { app.innerHTML=chooser(); return; }
  const stages=[catalogueView,imagesView,evidenceView,methodsView,versionsView,reviewView];
  const currentReview = reviewLabels[state.review.status] || reviewLabels.not_reviewed;
  app.innerHTML=`<div class="shell"><aside class="sidebar" aria-label="工作流程"><p class="sidebar-label">CURRENT TEACHING DOSSIER</p><label class="tiny" for="case-switch"><span class="sidebar-label">切换完整案卷</span></label><select id="case-switch" class="case-switch">${cases.map(pack=>`<option value="${e(pack.id)}"${attrs(pack.id===current.id)}>${e(roleLabels[pack.role || pack.workflow])} · ${e(pack.title)}</option>`).join('')}</select><p class="case-accession">MET ${e(accession())}<br>公开教学案卷 · 使用者编辑</p><nav class="stage-nav" aria-label="案卷步骤">${stageNames.map((name,index)=>`<button class="stage-button${stage===index?' active':''}" data-stage="${index}"${stage===index?' aria-current="step"':''}><span class="stage-number">0${index+1}</span>${name}</button>`).join('')}</nav><div class="sidebar-footer"><span class="eyebrow">BROWSER-LOCAL WORKSPACE</span><p>编辑保存在此浏览器。没有图像上传、文本外发或模型调用。</p><button data-reset>重置当前教学案卷</button><p><a href="#" data-show-chooser>返回场景选择</a></p></div></aside><main class="workspace main-focus" id="main-content" tabindex="-1"><div class="work-head"><div><span class="eyebrow">${e(roleEnglish[role()])} / GUIDED TEACHING</span><h1>${e(state.catalogue.object_name || current.title)}</h1><p>MET ${e(accession())} · ${e(roleLabels[role()])}业务视角 · 教学材料</p></div><div class="work-head-actions"><div class="case-state">真实编辑版本<span class="revision-num">r${state.revision}</span></div><button class="button text small" data-reset>重置当前案卷</button></div></div>${stages[stage]()}<footer class="work-footer"><span>${e(currentReview)}<br>编辑仅存于浏览器 · 未调用 AI 模型</span><div>${stage>0?`<button class="button small" data-stage="${stage-1}">← ${stageNames[stage-1]}</button>`:''} ${stage<5?`<button class="button primary small" data-stage="${stage+1}">${stageNames[stage+1]} →</button>`:''}</div></footer></main></div>`;
  if (stage===1) attachDrawing();
}
function heading(kicker,title,description) {return `<div class="stage-heading"><div><div class="stage-kicker">${kicker}</div><h2>${title}</h2><p>${description}</p></div></div>`;}
function catalogueView() {
  return `${heading('01 · DOSSIER & CATALOGUE','先建档，再讨论。','馆方记录、项目观察和使用者补充各有出处。可直接修改编目字段，保存后会产生新的真实编辑版本。')}<div class="three-metrics"><div class="metric"><strong>${visibleImages().length}<span>/ ${current.images.length} 张</span></strong>当前参与教学示例的图像</div><div class="metric"><strong>${visibleDocuments().length}<span>/ ${current.documents.length} 份</span></strong>可定位的预置资料</div><div class="metric"><strong>${skills.length}<span>个</span></strong>可展开阅读的真实 Skills</div></div><div class="two-column"><section class="panel"><div class="panel-title"><h3>编目记录</h3><small>从公开对象页面摘记</small></div><form id="catalogue-form"><div class="form-grid">${field('inventory_number','对象编号')}${field('object_type','器形（标明出处）')}${field('object_name','对象名称','input',true)}${field('material','材质与装饰（标明出处）','textarea',true)}${field('dimensions','尺寸及测量来源','input',true)}${field('requested_output','本次工作任务','textarea',true)}</div><div class="form-actions"><button class="button primary" type="submit">保存编目版本</button><span class="save-note">保存会留下时间与字段快照。</span></div></form></section><aside class="panel"><div class="object-summary"><img src="${e(current.images[0].file)}" alt="${e(current.title)}"><div><span class="eyebrow">PUBLIC COLLECTION</span><h3>已有出处的教学对象</h3><p>图像与身份信息来自公开馆藏，已有资料不等于本项目完成了独立鉴定。</p></div></div><div class="source-mini">The Metropolitan Museum of Art<br>${external(objectURL(),'打开原始馆藏页面')}<br>照片：Public Domain / CC0<br>公开教学案卷，不是实际委托。</div><ul class="scope-list">${(current.limits || []).slice(0,4).map(l=>`<li>${e(typeof l==='string'?l:l.text)}</li>`).join('')}</ul><div class="note-box">第一次体验可以直接继续，不必填写任何额外材料。试着把工作任务写得更具体，再保存一次。</div></aside></div><div class="activity-grid"><section class="panel"><div class="panel-title"><h3>来源记录</h3><small>已知信息与缺口分开</small></div>${(current.provenance || []).map(item=>`<div class="provenance-row"><strong>${e(item.title || ({publication:'公开资料记载',gap:'仍待核对的来源缺口',public_catalogue_record:'公开编目资料',project_retrieval:'项目资料核对记录',source_record:'公开来源记录',source_reading:'项目来源阅读记录'})[item.event_type] || item.event || item.event_type || '公开资料事件')}</strong><p>${e(item.text || item.description || item.note || '')}</p><p>${e(item.date_text || item.date || item.time || '')} ${item.source_url?external(item.source_url,'核对来源'):''}</p></div>`).join('') || '<p class="empty">没有提供对象交易链；不以公开馆藏身份补写收藏经历。</p>'}</section><section class="panel"><div class="panel-title"><h3>使用者工作备注</h3><small>真实可编辑</small></div><form id="notes-form"><div class="field"><label for="user-notes">下一步调查、客户问题或内部交接备注</label><textarea id="user-notes" name="notes" maxlength="5000" placeholder="例如：需要对象底足实拍，以及近期修复记录。">${e(state.notes)}</textarea></div><div class="form-actions"><button type="submit" class="button small">保存工作备注</button></div></form></section></div>`;
}
function normalRegion(region) {
  if (!region) return {x:0,y:0,width:1,height:1};
  return {x:Number(region.x)||0,y:Number(region.y)||0,width:Number(region.width ?? region.w)||0.2,height:Number(region.height ?? region.h)||0.2};
}
function rectSVG(region,selected=false) {const r=normalRegion(region); return `<rect x="${r.x*1000}" y="${r.y*1000}" width="${r.width*1000}" height="${r.height*1000}"${selected?' class="selected"':''}></rect>`;}
function imagesView() {
  const list=visibleImages(); if (!list.some(i=>i.id===selectedImage)) selectedImage=list[0]?.id;
  const image=list.find(i=>i.id===selectedImage); if (!image) return '<p class="empty">没有可见图像。</p>';
  const observations=state.observations.filter(o=>o.image_id===selectedImage);
  const region=draftRegion || {x:.1,y:.1,width:.3,height:.3};
  const draft=observationDraft?.image_id===selectedImage?observationDraft:null;
  const bounds=draft?.bounds || Object.fromEntries(Object.entries(region).map(([key,value])=>[key,String(Math.round(value*100))]));
  return `${heading('02 · VISUAL OBSERVATION','把观察固定在图像的具体位置。','选择观察条目可定位照片区域，也可以新增自己的区域记录。使用者观察可修订并保留历史，项目预置观察保持为教学原记录。')}
    <div class="image-layout"><section class="panel image-panel"><div class="image-toolbar"><span>${e(image.view)}</span>
      <div class="zoom-controls"><button class="icon-button" data-zoom="-0.25" aria-label="缩小图像">−</button><span>${Math.round(zoom*100)}%</span><button class="icon-button" data-zoom="0.25" aria-label="放大图像">＋</button><button class="button small" data-fit>适合</button></div></div>
      <div class="image-canvas"><div class="image-position" style="transform:scale(${zoom})"><img id="object-image" src="${e(image.file)}" alt="${e(image.view)}：${e(current.title)}" draggable="false">
      <svg id="annotation-layer" viewBox="0 0 1000 1000" preserveAspectRatio="none" class="${drawMode?'drawing':''}" aria-hidden="true">${observations.filter(o=>o.region && !(o.id===observationEditingID && draftRegion)).map(o=>rectSVG(o.region,o.id===selectedObservation)).join('')}${draftRegion?rectSVG(draftRegion,true):''}</svg></div></div>
      <div class="image-caption">归属：Met 公开馆藏 · CC0 图像 · 区域为归一化坐标，属于观察定位，不是模型热力图。</div>
      <div class="image-thumbnails">${list.map(i=>`<button class="thumbnail${i.id===selectedImage?' active':''}" data-image="${e(i.id)}"><img src="${e(i.file)}" alt=""><span>${e(i.view)}</span></button>`).join('')}${current.images.filter(i=>!isAvailable(i,state)).map(i=>`<div class="locked-evidence">${e(i.view)}<br><button class="button text small" data-stage="4">到补证步骤纳入 →</button></div>`).join('')}</div></section>
    <section class="panel"><div class="panel-title"><h3>定位观察</h3><small>${observations.length} 条</small></div>
      ${observations.map(o=>`<article class="observation-card"><button class="observation-title${selectedObservation===o.id?' selected':''}" data-observation="${e(o.id)}"><span aria-hidden="true">⌖</span>${e(o.title || '使用者观察')}</button><p>${e(o.text)}</p>
        <div class="origin-label">${o.origin==='browser_user'?'使用者添加 · 未经专家确认':'项目编写教学观察 · 未调用模型'}</div>
        ${o.origin==='browser_user'?`<button class="button text small" data-edit-observation="${e(o.id)}">修订这条观察</button>`:''}</article>`).join('')}
      <form id="observation-form" class="observation-add" data-editing-id="${e(observationEditingID || '')}"><h4>${observationEditingID?'修订你的观察':'添加你的观察'}</h4>
      ${observationEditingID?'<p class="tiny muted" style="margin-bottom:12px">保存后产生新的真实版本，原内容仍保留在历史快照中。</p>':''}
      <div class="field"><label for="observation-title">观察标题</label><input id="observation-title" name="title" maxlength="120" value="${e(draft?.title || '')}" placeholder="例如：口沿局部观察" required></div>
      <div class="region-fields">${[['x','X'],['y','Y'],['width','宽'],['height','高']].map(([key,label])=>`<label>${label} %<input name="${key}" type="number" min="${key==='width'||key==='height'?1:0}" max="100" step="1" value="${e(bounds[key])}" required aria-label="观察区域${label}百分比"></label>`).join('')}</div>
      <button type="button" class="button small" data-draw>${drawMode?'在照片上拖动框选…':'在照片上框选区域'}</button>
      <div class="field" style="margin-top:12px"><label for="observation-text">观察描述及限制</label><textarea id="observation-text" name="text" maxlength="2000" placeholder="描述可见现象，避免仅凭照片认定修复、年代或真伪。" required>${e(draft?.text || '')}</textarea></div>
      <div class="form-actions"><button type="submit" class="button small">${observationEditingID?'保存观察修订':'保存区域观察'}</button>${observationEditingID?'<button type="button" class="button text small" data-cancel-observation-edit>取消修订</button>':''}</div></form></section></div>`;
}
function documentLines(document) {
  let offset=0;
  return document.text.split('\n').map((line,index)=>{
    let body=e(line) || '&nbsp;';
    if (citationHighlight && citationHighlight.doc===document.id) {
      const {start,end}=citationHighlight;
      const a=Math.max(0,start-offset),b=Math.min(line.length,end-offset);
      if (b>a) body=e(line.slice(0,a))+`<mark>${e(line.slice(a,b))}</mark>`+e(line.slice(b));
    }
    offset+=line.length+1;
    return `<div class="document-line"><span class="line-number" aria-hidden="true">${String(index+1).padStart(2,'0')}</span><span>${body}</span></div>`;
  }).join('');
}
function evidenceView() {
  const docs=visibleDocuments(); if (!docs.some(d=>d.id===selectedDoc)) selectedDoc=docs[0]?.id;
  const document=docs.find(d=>d.id===selectedDoc);
  return `${heading('03 · LOCATABLE EVIDENCE','每条引用，都能回到原文。','这里提供项目编写的教学摘记与方法说明，并链接权威原始页面。资料权威性、对象同一性与判断支持程度需要分别核对。')}<div class="document-layout"><section class="panel"><div class="panel-title"><h3>预置资料</h3><small>原文可读</small></div><label class="field"><span class="tiny muted">筛选资料标题或内容</span><input class="search-input" id="document-search" type="search" placeholder="例如：釉、尺寸、底足"></label><div class="document-list" id="document-list">${docs.map(d=>`<button class="document-button${d.id===selectedDoc?' active':''}" data-document="${e(d.id)}" data-search="${e(d.title+' '+d.text)}"><strong>${e(d.title)}</strong><span>${e(d.kind || '项目原创教学资料')} · ${d.text.length} 字符</span></button>`).join('')}</div>${current.documents.filter(d=>!isAvailable(d,state)).map(d=>`<div class="locked-evidence" style="margin-top:12px">${e(d.title)}<br><button class="button text small" data-stage="4">纳入预置补充件 →</button></div>`).join('')}<div class="note-box">全部 TXT 已随案卷准备。标题搜索只筛选本案资料，不会访问外部站点。</div></section><section class="panel document-reader">${document?`<span class="eyebrow">PROJECT-AUTHORED TEACHING NOTE</span><h3>${e(document.title)}</h3><div class="document-meta">资料编号 ${e(document.id)} · UTF-8 TXT · 项目原创摘记，非授权转载的完整馆藏文章<br>${document.source_url?external(document.source_url,'核对资料引用的原始页面'):''}</div>${citationHighlight?.doc===document.id?`<div class="citation-banner">引用定位：字符 ${citationHighlight.start}–${citationHighlight.end}（0 基区间） · 高亮原文供你核对</div>`:''}<div class="document-lines">${documentLines(document)}</div>`:'<p class="empty">请选择一份资料。</p>'}</section></div><div class="source-grid">${(current.sources || []).map(s=>`<article class="source-card${highlightedSource===s.id?' highlight':''}" id="source-${e(s.id)}"><span class="eyebrow">${e(s.authority || 'SOURCE RECORD')}</span><h3>${e(s.title)}</h3><p>${e(s.summary || '')}</p><small>${e(s.license || '仅链接与项目原创摘要；不转载完整原文')}</small>${external(s.url,'访问权威原始页面')}</article>`).join('')}</div>`;
}
function citationChip(c,index,findingID) {
  const type={image:'图像区域',document:'资料原文',source:'来源页面'}[c.kind] || '证据';
  return `<button class="citation-chip" data-citation-finding="${e(findingID)}" data-citation-index="${index}">${e(type)} · ${e(c.target_id || c.ref_id || '')} ↗</button>`;
}
function findingCard(f) {
  return `<article class="finding-card"><div class="finding-heading"><h3>${e(f.title || f.claim)}</h3><span class="status-pill ${e(f.status)}">${e(statusLabels[f.status] || f.status)}</span></div><p>${e(f.text || f.detail)}</p><div class="citation-chips">${(f.citations || []).map((c,i)=>citationChip(c,i,f.id)).join('')}</div>${f.next_evidence?`<div class="finding-next">下一份证据：${e(f.next_evidence)}</div>`:''}<span class="finding-origin">项目人工编写教学示例 · ai_inference_performed=false · 不是动态模型结果</span></article>`;
}
function methodsView() {
  const selected=skills.find(s=>s.id===selectedSkill) || skills[0];
  return `${heading('04 · METHODS & RESEARCH EXAMPLES','把方法打开，把推断写清。','左侧展示预先编写的研究示例；点击证据标签回到具体图像或文字。右侧是仓库内实际交付的 Skill 原文，本页不执行模型推理。')}<div class="methods-layout"><section><div class="findings">${findingsFor(current,state).map(findingCard).join('')}</div><div class="note-box">“有资料支撑”表示该教学条目有可阅读的引用，不表示结论经过独立鉴定或概率校准。公开对象的已知身份不用于估计模型准确率。</div></section><aside class="panel"><div class="panel-title"><h3>可阅读的方法包</h3><small>${skills.length} 个 Skills</small></div><div class="skill-list">${skills.map(s=>`<button class="skill-button${s.id===selected?.id?' active':''}" data-skill="${e(s.id)}"><strong>${e(skillLabels[s.id] || s.name)}</strong><small>${e(s.id)}</small></button>`).join('')}</div>${selected?`<p class="tiny muted" style="margin-bottom:10px">先读任务边界与引用规则，再检查研究材料。</p><pre class="skill-reader" tabindex="0" aria-label="${e(selected.id)} Skill 原文">${e(selected.content || selected.body || '')}</pre><p class="skill-hash">SKILL.md SHA-256<br>${e(selected.sha256 || '见仓库与导出文件清单')}</p>${(selected.references || []).map((r,i)=>`<button class="reference-button" data-skill-reference="${i}">${e(r.path)} →</button>`).join('<br>')}`:'<p class="empty">方法包未加载；公开案卷仍可阅读与导出。</p>'}</aside></div>`;
}
function versionsView() {
  const supplements=current.supplements || [];
  const afterState={...state,active_supplements:supplements.map(s=>s.id)};
  const before=current.findings || [], after=findingsFor(current,afterState);
  return `${heading('05 · SUPPLEMENT & REVISION','补一份证据，看见依据如何变化。','补充件已预置在教学包中。纳入后更新的是项目编写的研究示例，不是重新运行模型；下方另行记录你的真实编辑快照。')}${supplements.map(s=>`<section class="supplement-card"><div class="supplement-icon" aria-hidden="true">＋</div><div><span class="eyebrow">PRELOADED TEACHING SUPPLEMENT</span><h3>${e(s.title)}</h3><p>${e(s.reason)}</p><p class="tiny">${e(s.change_note || '')}</p></div>${state.active_supplements.includes(s.id)?'<span class="status-pill supported">已纳入当前教学版本</span>':`<button class="button gold" data-supplement="${e(s.id)}">纳入预置补充件</button>`}</section>`).join('')}<div class="version-columns"><section class="panel version-panel"><span class="eyebrow">CURATED EXAMPLE · V1</span><h3>补证前的教学示例</h3><p class="version-label">使用初始材料 · 项目人工编写</p>${before.map(f=>`<article class="version-item"><strong>${e(f.title || f.claim)}</strong><p>${e(f.text || f.detail)}</p><span class="status-pill ${e(f.status)}">${e(statusLabels[f.status] || f.status)}</span></article>`).join('')}</section><section class="panel version-panel"><span class="eyebrow">CURATED EXAMPLE · V2</span><h3>纳入补充件后的示例</h3><p class="version-label">${state.active_supplements.length?'当前已纳入补充件':'可预览；尚未纳入你的当前案卷'} · 项目人工编写</p>${after.map(f=>`<article class="version-item${before.find(b=>b.id===f.id)?.text!==f.text?' changed':''}"><strong>${e(f.title || f.claim)}</strong><p>${e(f.text || f.detail)}</p><span class="status-pill ${e(f.status)}">${e(statusLabels[f.status] || f.status)}</span></article>`).join('')}</section></div><div class="activity-grid"><section class="panel"><div class="panel-title"><h3>你的真实编辑历史</h3><small>最多保留最近 20 次</small></div><ol class="timeline">${state.history.slice().reverse().map(h=>`<li><span class="version-dot">r${h.snapshot.revision}</span><div>${e(h.action)}<small>${e(formatTime(h.at))}</small></div></li>`).join('')}</ol></section><section class="panel"><div class="panel-title"><h3>比较两个实际快照</h3><small>浏览器记录</small></div>${snapshotsView()}</section></div>`;
}
function formatTime(value) {try{return new Date(value).toLocaleString('zh-CN',{hour12:false});}catch{return value;}}
function snapshotsView() {
  if(state.history.length<2) return '<p class="empty">先保存一次编目、观察或补证，便可比较真实编辑版本。</p>';
  if (!state.history.some(h=>h.snapshot.revision===snapshotFrom)) snapshotFrom=state.history[0].snapshot.revision;
  if (!state.history.some(h=>h.snapshot.revision===snapshotTo)) snapshotTo=state.history[state.history.length-1].snapshot.revision;
  const from=state.history.find(h=>h.snapshot.revision===snapshotFrom)?.snapshot;
  const to=state.history.find(h=>h.snapshot.revision===snapshotTo)?.snapshot;
  const options=(choice)=>state.history.map(h=>`<option value="${h.snapshot.revision}"${attrs(h.snapshot.revision===choice)}>r${h.snapshot.revision} · ${e(h.action)}</option>`).join('');
  const changes=[];
  for(const key of Object.keys({...from.catalogue,...to.catalogue})) if(from.catalogue[key]!==to.catalogue[key]) changes.push([({object_name:'名称',object_type:'器形',material:'材质',dimensions:'尺寸',requested_output:'研究任务',inventory_number:'编号'})[key] || key, `${from.catalogue[key] || '空'}\n↓\n${to.catalogue[key] || '空'}`]);
  if(from.observations.length!==to.observations.length)changes.push(['观察条目',`${from.observations.length} → ${to.observations.length}`]);
  for (const observation of to.observations) {
    const previous=from.observations.find(o=>o.id===observation.id);
    if (!previous || (previous.title===observation.title && previous.text===observation.text && JSON.stringify(previous.region)===JSON.stringify(observation.region))) continue;
    const describe=o=>`${o.title || '观察'}：${o.text}\n${o.region ? '区域：左距 '+Math.round(o.region.x*100)+'%，上距 '+Math.round(o.region.y*100)+'%，宽 '+Math.round(o.region.width*100)+'%，高 '+Math.round(o.region.height*100)+'%' : '未记录区域'}`;
    changes.push(['观察修订',`${describe(previous)}\n↓\n${describe(observation)}`]);
  }
  if(from.notes!==to.notes)changes.push(['工作备注',`${from.notes || '空'}\n↓\n${to.notes || '空'}`]);
  if(JSON.stringify(from.active_supplements)!==JSON.stringify(to.active_supplements))changes.push(['纳入补充件',`${from.active_supplements.length} → ${to.active_supplements.length}`]);
  if(JSON.stringify(from.review)!==JSON.stringify(to.review))changes.push(['复核状态',`${reviewLabels[from.review.status] || from.review.status} → ${reviewLabels[to.review.status] || to.review.status}`]);
  return `<div class="snapshot-controls"><label>比较起点<select id="snapshot-from" aria-label="比较起点">${options(snapshotFrom)}</select></label><label>比较终点<select id="snapshot-to" aria-label="比较终点">${options(snapshotTo)}</select></label></div><div id="snapshot-changes">${changes.length?changes.map(([key,value])=>`<div class="change-row"><strong>${e(key)}</strong><span>${e(value)}</span></div>`).join(''):'<p class="empty">这两个快照的记录内容一致。</p>'}</div>`;
}
function reviewView() {
  return `${heading('06 · HUMAN REVIEW & HANDOFF','复核留痕，然后把案卷带走。','填写自己的复核意见。导出包含公开原图、定位资料、方法包与真实编辑历史；每份报告都注明教学来源及未调用模型。')}<div class="review-layout"><section class="panel"><div class="panel-title"><h3>使用者人工复核记录</h3><small>身份未验证</small></div><div class="review-state ${e(state.review.status)}">${e(reviewLabels[state.review.status] || reviewLabels.not_reviewed)}${state.review.status==='stale'?'<br>上次记录仍保留，修改案卷后请再次复核。':''}</div><form id="review-form"><div class="form-grid"><div class="field wide"><label for="review-name">填写者称呼</label><input id="review-name" name="name" value="${e(state.review.name)}" maxlength="100" placeholder="你的称呼，不需要提供私人身份信息" required></div><div class="field wide"><label for="review-status">复核处理</label><select id="review-status" name="status"><option value="reviewed"${attrs(state.review.status==='reviewed')}>已核对教学资料，记录使用者意见</option><option value="needs_more_evidence"${attrs(state.review.status==='needs_more_evidence')}>继续补证，保留判断</option></select></div><div class="field wide"><label for="review-notes">复核意见与待补证</label><textarea id="review-notes" name="notes" maxlength="5000" placeholder="例如：尺寸沿用馆方公开记录，未实物测量。底足和修复记录仍应补齐，现阶段不作真伪结论。" required>${e(state.review.notes)}</textarea></div></div><div class="form-actions"><button class="button primary" type="submit">保存复核记录</button></div></form><div class="note-box">这是浏览器使用者自行填写的记录，不构成经过验证的文博专家签署。之后修改编目、观察、备注或补证，系统会标记此前复核需要更新。</div></section><aside class="panel"><div class="panel-title"><h3>真正可下载的完整案卷</h3><small>无需上传</small></div><div class="export-buttons"><button class="export-button" data-export="zip"${busy?' disabled':''}><span class="file-label">ZIP</span><span><strong>完整交接包</strong><small>原图 + 原文 + Skills + 报告 + SHA-256 清单</small></span><span class="download-icon" aria-hidden="true">↓</span></button><button class="export-button" data-export="html"${busy?' disabled':''}><span class="file-label">HTML</span><span><strong>可阅读报告</strong><small>图像内嵌，离线可读、可打印</small></span><span class="download-icon" aria-hidden="true">↓</span></button><button class="export-button" data-export="json"${busy?' disabled':''}><span class="file-label">JSON</span><span><strong>结构化案卷</strong><small>引用位置、记录、教学标记与编辑历史</small></span><span class="download-icon" aria-hidden="true">↓</span></button></div><ul class="readiness-list"><li><span class="ready-check">✓</span> ${current.images.length} 张公开原图全部随包交付</li><li><span class="ready-check">✓</span> ${current.documents.length} 份原创教学 TXT，含预置补充件</li><li><span class="ready-check">✓</span> ${skills.length} 个仓库方法包原文与参考文件</li><li><span class="ready-check">✓</span> 使用者编辑 r${state.revision} 与最近 ${state.history.length} 次快照</li><li><span class="ready-check">✓</span> ai_inference_performed = false</li></ul><p class="download-detail">文件摘要用于检查是否改变，不证明器物真伪、专家身份或判断正确。JSON 报告的图像引用可与 ZIP 内原图对应；HTML 单文件包含照片，可直接离线阅读。</p><p class="case-footnote">后台源码、真实模型接入与本地部署方式见 ${external('https://github.com/dingyucanada/cizheng-agent-skills','开源仓库')}。</p></aside></div>`;
}
function attachDrawing() {
  const layer=$('#annotation-layer'); if(!layer || !drawMode)return;
  let start=null;
  const point=(event)=>{const box=layer.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),y:Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))};};
  layer.addEventListener('pointerdown',event=>{if(event.button!==0)return;start=point(event);layer.setPointerCapture(event.pointerId);event.preventDefault();});
  layer.addEventListener('pointermove',event=>{
    if(!start)return;const end=point(event);draftRegion={x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(end.x-start.x),height:Math.abs(end.y-start.y)};
    let rect=layer.querySelector('[data-draft]');if(!rect){rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.dataset.draft='true';rect.setAttribute('class','selected');layer.append(rect);}
    for(const key of ['x','y','width','height'])rect.setAttribute(key,String(draftRegion[key]*1000));
  });
  layer.addEventListener('pointerup',event=>{
    if(!start)return;start=null;layer.releasePointerCapture(event.pointerId);
    if(!draftRegion || draftRegion.width<.01 || draftRegion.height<.01){draftRegion=null;toast('区域太小，请重新框选或填写区域百分比。');return;}
    captureObservationDraft();
    if(observationDraft) observationDraft.bounds=Object.fromEntries(Object.entries(draftRegion).map(([key,value])=>[key,String(Math.round(value*100))]));
    drawMode=false;render();toast('已定位区域，可填写观察描述后保存。');$('#observation-title')?.focus();
  });
  layer.addEventListener('pointercancel',()=>{start=null;drawMode=false;draftRegion=null;render();});
}
function followCitation(findingID,index) {
  const f=findingsFor(current,state).find(f=>f.id===findingID);
  const citation=f?.citations?.[Number(index)];if(!citation)return;
  clearObservationEditor();
  const target=citation.target_id || citation.ref_id;
  if(citation.kind==='image'){
    if(!visibleImages().some(i=>i.id===target)){toast('这项证据是预置补充件，请先纳入补证。');stage=4;render();return;}
    selectedImage=target;const observation=state.observations.find(o=>o.image_id===target && (!citation.region || JSON.stringify(o.region)===JSON.stringify(citation.region)));
    selectedObservation=observation?.id || ''; draftRegion=citation.region || null;zoom=1;stage=1;render();
  }else if(citation.kind==='document'){
    if(!visibleDocuments().some(d=>d.id===target)){toast('该资料是预置补充件，请先纳入补证。');stage=4;render();return;}
    selectedDoc=target;const document=current.documents.find(d=>d.id===target);let start=Number(citation.locator?.start ?? 0),end=Number(citation.locator?.end ?? document?.text.length ?? 0);
    start=Math.max(0,Math.min(document.text.length,start));end=Math.max(start,Math.min(document.text.length,end));
    citationHighlight={doc:target,start,end};stage=2;render();
  }else if(citation.kind==='source'){highlightedSource=target;stage=2;render();setTimeout(()=>document.getElementById('source-'+target)?.scrollIntoView({behavior:'smooth',block:'center'}),40);}
  $('#main-content')?.focus({preventScroll:true});
}
async function loadAsset(path) {
  if(!/^assets\/[a-zA-Z0-9._-]+$/.test(path))throw new Error('公开图像路径不合法。');
  const response=await fetch(path,{credentials:'same-origin'});if(!response.ok)throw new Error(`图像暂不可读取：${path}`);return new Uint8Array(await response.arrayBuffer());
}
function download(bytes,name,type) {
  const blob=new Blob([bytes],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}
function bytesBase64(bytes) {let text='';const chunk=32768;for(let i=0;i<bytes.length;i+=chunk)text+=String.fromCharCode(...bytes.subarray(i,i+chunk));return btoa(text);}
async function exportCase(format) {
  if(busy)return;busy=true;render();toast('正在核对并生成教学案卷…');
  try{
    const exportPack=current, exportState=state;
    const fileID=String(exportPack.id).replace(/[^a-zA-Z0-9_-]/g,'_');
    const report=buildReport(exportPack,exportState);
    if(format==='json')download(JSON.stringify(report,null,2),`cizheng-${fileID}-r${exportState.revision}.json`,'application/json;charset=utf-8');
    else if(format==='html'){
      const imageMap={};for(const image of exportPack.images){const bytes=await loadAsset(image.file);if(image.sha256 && await sha256(bytes)!==image.sha256)throw new Error('原图摘要校验失败，导出已中止。');imageMap[image.id]='data:image/jpeg;base64,'+bytesBase64(bytes);}
      download(reportHTML(report,imageMap),`cizheng-${fileID}-r${exportState.revision}.html`,'text/html;charset=utf-8');
    }else if(format==='zip'){
      const {entries}=await buildBundleEntries(exportPack,exportState,loadAsset,skills);
      download(makeZip(entries),`cizheng-${fileID}-r${exportState.revision}.zip`,'application/zip');
    }
    toast('教学案卷已生成，请查看浏览器下载记录。');
  }catch(error){toast(error.message || '导出失败，请稍后重试。');}
  finally{busy=false;render();}
}

app.addEventListener('click',event=>{
  const button=event.target.closest('button,a[data-show-chooser]');if(!button)return;
  if(button.dataset.openCase){selectCase(button.dataset.openCase,true);return;}
  if(button.hasAttribute('data-show-chooser')){event.preventDefault();clearObservationEditor();current=null;history.replaceState(null,'',location.pathname+location.search);render();return;}
  if(button.dataset.stage!==undefined){setStage(button.dataset.stage);return;}
  if(button.dataset.image){if(button.dataset.image!==selectedImage){clearObservationEditor();selectedObservation='';}else captureObservationDraft();selectedImage=button.dataset.image;zoom=1;render();return;}
  if(button.dataset.editObservation){editObservation(button.dataset.editObservation);return;}
  if(button.hasAttribute('data-cancel-observation-edit')){clearObservationEditor();render();toast('已取消修订。');return;}
  if(button.dataset.observation){captureObservationDraft();selectedObservation=button.dataset.observation;draftRegion=observationEditingID?regionFromDraft():null;render();return;}
  if(button.dataset.zoom){captureObservationDraft();zoom=Math.max(.5,Math.min(3,zoom+Number(button.dataset.zoom)));render();return;}
  if(button.hasAttribute('data-fit')){captureObservationDraft();zoom=1;render();return;}
  if(button.hasAttribute('data-draw')){captureObservationDraft();drawMode=!drawMode;zoom=1;render();if(drawMode)toast('在照片上拖动框选；也可直接填写区域百分比。');return;}
  if(button.dataset.document){selectedDoc=button.dataset.document;citationHighlight=null;render();return;}
  if(button.dataset.skill){selectedSkill=button.dataset.skill;render();return;}
  if(button.dataset.skillReference!==undefined){const s=skills.find(s=>s.id===selectedSkill) || skills[0];const r=s?.references?.[Number(button.dataset.skillReference)];if(r){$('.skill-reader').textContent=r.content || '';$('.skill-reader').setAttribute('aria-label',r.path+' 参考文件原文');$('.skill-hash').textContent=(r.path || '')+' SHA-256 '+(r.sha256 || '见导出清单');}return;}
  if(button.dataset.citationFinding){followCitation(button.dataset.citationFinding,button.dataset.citationIndex);return;}
  if(button.dataset.supplement){state=applySupplement(current,state,button.dataset.supplement);snapshotTo=null;save();render();toast('已纳入预置教学补充件，真实编辑历史新增一版。');return;}
  if(button.dataset.export){exportCase(button.dataset.export);return;}
  if(button.hasAttribute('data-reset')){if(confirm('重置当前教学案卷？本浏览器对它的编辑与复核记录将清除。已下载文件不会改变。')){clearObservationEditor();state=createState(current);save();selectedObservation='';selectedImage=visibleImages()[0]?.id || '';selectedDoc=visibleDocuments()[0]?.id || '';snapshotFrom=null;snapshotTo=null;render();toast('已恢复预置教学案卷。');}return;}
});
app.addEventListener('change',event=>{
  if(event.target.id==='case-switch')selectCase(event.target.value,true);
  else if(event.target.id==='snapshot-from'){snapshotFrom=Number(event.target.value);render();}
  else if(event.target.id==='snapshot-to'){snapshotTo=Number(event.target.value);render();}
});
app.addEventListener('input',event=>{
  if(event.target.closest('#observation-form')){captureObservationDraft();if(['x','y','width','height'].includes(event.target.name) && !drawMode){draftRegion=regionFromDraft();refreshAnnotationDraft();}}
  else if(event.target.id==='document-search'){const query=event.target.value.toLocaleLowerCase().trim();document.querySelectorAll('[data-search]').forEach(button=>button.hidden=!button.dataset.search.toLocaleLowerCase().includes(query));}
});
app.addEventListener('submit',event=>{
  event.preventDefault();const form=event.target;if(!form.reportValidity())return;const data=new FormData(form);
  if(form.id==='catalogue-form'){const catalogue={...state.catalogue};for(const key of ['inventory_number','object_name','object_type','material','dimensions','requested_output'])catalogue[key]=String(data.get(key) || '').trim();commit({catalogue},'保存使用者编目修改');toast('已保存编目，产生新的真实编辑版本。');}
  else if(form.id==='notes-form'){commit({notes:String(data.get('notes') || '').trim()},'保存使用者工作备注');toast('工作备注已保存。');}
  else if(form.id==='observation-form'){
    const region={};for(const key of ['x','y','width','height'])region[key]=Number(data.get(key))/100;
    if(!Object.values(region).every(Number.isFinite) || region.x<0 || region.y<0 || region.x+region.width>1.001 || region.y+region.height>1.001 || region.width<=0 || region.height<=0){toast('区域超过照片范围，请检查 X、Y、宽与高。');return;}
    const title=String(data.get('title') || '').trim(),text=String(data.get('text') || '').trim();
    if(!title || !text){toast('请填写观察标题与描述。');return;}
    if(observationEditingID){
      const original=state.observations.find(o=>o.id===observationEditingID && o.image_id===selectedImage && o.origin==='browser_user');
      if(!original){clearObservationEditor();render();toast('这条观察不能通过使用者编辑器修订。');return;}
      const observation={...original,title,text,region,updated_at:new Date().toISOString()};
      const observations=state.observations.map(o=>o.id===original.id?observation:o);
      selectedObservation=original.id;clearObservationEditor();commit({observations},'修订使用者定位观察');toast('已保存观察的新版本，先前内容保留在历史中。');
    }else{
      const id='user-observation-'+Date.now().toString(36);const observation={id,image_id:selectedImage,title,text,region,origin:'browser_user',ai_inference_performed:false};
      selectedObservation=id;clearObservationEditor();commit({observations:[...state.observations,observation]},'添加使用者定位观察');toast('区域观察已保存，保持为使用者记录。');
    }
  }else if(form.id==='review-form'){const review={status:String(data.get('status')),name:String(data.get('name')).trim(),notes:String(data.get('notes')).trim(),at:new Date().toISOString(),verified_identity:false};commit({review},'保存使用者人工复核记录');toast('已记录人工复核意见；身份未验证，非专家签署。');}
});
$('#scope-button').addEventListener('click',()=>$('#scope-dialog').showModal());
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>$('#scope-dialog').close()));

try{
  const [caseResponse,skillResponse]=await Promise.all([fetch('data/demo-cases.json'),fetch('data/skills.json')]);
  if(!caseResponse.ok || !skillResponse.ok)throw new Error('教学资料暂不可读取。请刷新页面，或从项目主页重新进入。');
  const caseData=await caseResponse.json(),skillData=await skillResponse.json();
  cases=caseData.cases || [];skills=Array.isArray(skillData)?skillData:skillData.skills || [];
  if(cases.length!==3 || cases.some(c=>!c.id || !c.images?.length || !c.documents?.length || !c.findings?.length))throw new Error('教学案卷数据不完整。');
  for(const pack of cases){pack.images=pack.images.map(i=>({...i,file:i.file.startsWith('assets/')?i.file:'assets/'+i.file}));pack.documents=pack.documents.map(d=>({...d,text:String(d.text || '')}));}
  const id=entryCaseID(location.href, cases.map(c=>c.id));if(id)selectCase(id);else render();
}catch(error){app.setAttribute('aria-busy','false');app.innerHTML=`<main id="main-content" class="panel error-screen"><span class="eyebrow">EXPERIENCE UNAVAILABLE</span><h1>完整教学案卷暂时无法打开</h1><p>${e(error.message)}</p><a class="button primary" href="demo.html">重新加载体验</a> <a class="button" href="./">回到项目主页</a></main>`;}
