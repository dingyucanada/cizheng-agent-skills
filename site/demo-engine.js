// The public workbench edits a teaching dossier. It never invokes a model.
export const TEACHING_NOTICE = '公开教学体验：图像来自公开馆藏，观察与研究示例由项目编写。本次未调用 AI 模型，不是独立鉴定、真实委托或专家签署。';
export const STORAGE_PREFIX = 'cizheng-guided-v1:';
const clone = (value) => JSON.parse(JSON.stringify(value));
export const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const safeURL = (value) => /^https?:\/\//i.test(String(value ?? '')) ? String(value) : '';

export function stateSnapshot(state) {
  return clone({revision: state.revision, updated_at: state.updated_at, catalogue: state.catalogue,
    observations: state.observations, notes: state.notes, active_supplements: state.active_supplements,
    curated_research_examples: state.curated_research_examples, review: state.review});
}

export function createState(casePack, now = new Date().toISOString()) {
  const state = {schema_version: 1, case_id: casePack.id, revision: 1, updated_at: now,
    catalogue: clone(casePack.catalogue || {}), observations: clone(casePack.observations || []), notes: '',
    active_supplements: [], curated_research_examples:findingsFor(casePack,{active_supplements:[]}),
    review: {status:'not_reviewed', name:'', notes:'', at:null, verified_identity:false}, history:[]};
  state.history.push({action:'打开预置教学案卷', at:now, snapshot:stateSnapshot(state)});
  return state;
}

export function restoreState(casePack, candidate) {
  if (!candidate || candidate.schema_version !== 1 || candidate.case_id !== casePack.id ||
      !candidate.catalogue || !Array.isArray(candidate.observations) || !Array.isArray(candidate.history) ||
      !Array.isArray(candidate.active_supplements) || !Number.isInteger(candidate.revision) || candidate.revision < 1) return createState(casePack);
  const state = clone(candidate);
  const supplementIDs = new Set((casePack.supplements || []).map(s => s.id));
  state.active_supplements = state.active_supplements.filter(id => supplementIDs.has(id));
  state.review = state.review || {status:'not_reviewed', name:'', notes:'', at:null};
  state.review.verified_identity = false;
  state.notes = String(state.notes || '');
  // Older browser records have no opinion snapshot. Do not rewrite their history.
  state.curated_research_examples = findingsFor(casePack,state);
  state.history = state.history.slice(-20);
  return state;
}

export function updateState(state, patch, action, now = new Date().toISOString()) {
  const updated = {...clone(state), ...clone(patch), revision:state.revision + 1, updated_at:now};
  if (!Object.hasOwn(patch, 'review') && ['reviewed','needs_more_evidence'].includes(updated.review?.status)) {
    updated.review = {...updated.review, status:'stale', stale_reason:'案卷已修改，请重新记录人工复核。'};
  }
  if (updated.review) updated.review.verified_identity = false;
  updated.history.push({action, at:now, snapshot:stateSnapshot(updated)});
  updated.history = updated.history.slice(-20);
  return updated;
}

export function applySupplement(casePack, state, id, now) {
  if (!(casePack.supplements || []).some(s => s.id === id)) throw new Error('Unknown supplement');
  if (state.active_supplements.includes(id)) return state;
  const active_supplements = [...state.active_supplements,id];
  return updateState(state, {active_supplements,
    curated_research_examples:findingsFor(casePack,{active_supplements})}, '纳入预置教学补充证据', now);
}

export function isAvailable(item, state) {
  return !item.supplement_id || state.active_supplements.includes(item.supplement_id);
}

export function findingsFor(casePack, state) {
  const findings = clone(casePack.findings || []);
  for (const supplement of casePack.supplements || []) {
    if (!state.active_supplements.includes(supplement.id)) continue;
    for (const finding of supplement.after_findings || []) {
      const index = findings.findIndex(f => f.id === finding.id);
      if (index < 0) findings.push(clone(finding)); else findings[index] = clone(finding);
    }
  }
  return findings.map(f => ({...f, origin:'project_curated_teaching', ai_inference_performed:false}));
}

function bindTeachingCitation(casePack,state,citation) {
  const target = citation.target_id || citation.ref_id;
  const bound = clone(citation);
  if (citation.kind === 'image') {
    const image = (casePack.images || []).find(i=>i.id===target);
    if (image) bound.target = {id:image.id,view:image.view,sha256:image.sha256,
      source_url:image.source_url,image_url:image.image_url,
      used_in_current_teaching_revision:isAvailable(image,state),
      coordinate_system:'normalized_region_on_entire_original_image',
      region:clone(citation.region || {x:0,y:0,width:1,height:1})};
  } else if (citation.kind === 'document') {
    const document = (casePack.documents || []).find(d=>d.id===target);
    if (document) {
      const start=Number(citation.locator?.start ?? 0),end=Number(citation.locator?.end ?? document.text.length);
      bound.target = {id:document.id,title:document.title,sha256:document.sha256,
        source_url:document.source_url,origin:'project_authored_teaching_document',
        used_in_current_teaching_revision:isAvailable(document,state),
        locator:{start,end,unit:'zero_based_javascript_character_interval'},
        excerpt:document.text.slice(start,end)};
    }
  } else if (citation.kind === 'source') {
    const source = (casePack.sources || []).find(s=>s.id===target);
    if (source) bound.target = {id:source.id,title:source.title,url:source.url,
      locator:source.locator,authority:source.authority,license:source.license};
  }
  return bound;
}

function bindTeachingFindings(casePack,state,findings) {
  return findings.map(f=>({...clone(f),origin:'project_curated_teaching',ai_inference_performed:false,
    citations:(f.citations || []).map(c=>bindTeachingCitation(casePack,state,c))}));
}

export function teachingOpinionVersions(casePack,state) {
  const supplements=casePack.supplements || [];
  const active=supplements.filter(s=>state.active_supplements.includes(s.id));
  const base = bindTeachingFindings(casePack,state,casePack.findings || []);
  const versions=[{id:'v1',label:'V1 · 初始预写教学意见',origin:'project_curated_teaching',
    ai_inference_performed:false,activated:true,current:active.length===0,
    supplement_id:null,relative_to:null,change_reason:'项目根据初始预置材料人工编写的教学意见；不是模型运行结果。',
    material_basis:{image_ids:(casePack.images || []).filter(i=>!i.supplement_id).map(i=>i.id),
      document_ids:(casePack.documents || []).filter(d=>!d.supplement_id).map(d=>d.id)},
    findings:base,changes:[]}];
  supplements.forEach((supplement,index)=>{
    const findings=bindTeachingFindings(casePack,state,findingsFor(casePack,{active_supplements:[supplement.id]}));
    const changes=findings.map(f=>{
      const before=base.find(b=>b.id===f.id);
      return {finding_id:f.id,title:f.title || f.claim,
        changed:JSON.stringify(before)!==JSON.stringify(f),
        before_text:before?.text || before?.detail || null,after_text:f.text || f.detail || '',
        before_status:before?.status || null,after_status:f.status,
        reason:supplement.change_note || supplement.reason || '项目人工编写的补证教学说明。'};
    });
    versions.push({id:`v${index+2}`,label:`V${index+2} · ${supplement.title}`,
      origin:'project_curated_teaching',ai_inference_performed:false,
      activated:state.active_supplements.includes(supplement.id),
      current:active.length===1 && active[0].id===supplement.id,
      supplement_id:supplement.id,relative_to:'v1',
      change_reason:supplement.change_note || supplement.reason || '项目人工编写的补证教学说明。',
      material_basis:{image_ids:(casePack.images || []).filter(i=>!i.supplement_id || i.supplement_id===supplement.id).map(i=>i.id),
        document_ids:(casePack.documents || []).filter(d=>!d.supplement_id || d.supplement_id===supplement.id).map(d=>d.id)},
      findings,changes});
  });
  return versions;
}

function handoffHistory(casePack,state) {
  return clone(state.history).map(entry=>{
    const snapshot=entry.snapshot;
    const wasStored=Array.isArray(snapshot.curated_research_examples);
    const active_supplements=Array.isArray(snapshot.active_supplements)?snapshot.active_supplements:[];
    const findings=wasStored?snapshot.curated_research_examples:findingsFor(casePack,{active_supplements});
    return {...entry,teaching_snapshot_origin:wasStored?'stored_precompiled_teaching_snapshot':'reconstructed_at_export_from_current_public_pack',
      teaching_snapshot_notice:wasStored?'当时保存的项目预写教学发现，非模型运行。':'旧浏览器快照未保存教学发现；此处按当时补证开关与当前公开包重建，不能视为当时原始意见。',
      snapshot:{...snapshot,curated_research_examples:bindTeachingFindings(casePack,{active_supplements},findings)}};
  });
}

export function buildReport(casePack, state, now = new Date().toISOString()) {
  return {
    schema_version:'cizheng.public-teaching-report.v1', mode:'guided_teaching', ai_inference_performed:false,
    notice:TEACHING_NOTICE, generated_at:now, case_id:casePack.id, title:casePack.title,
    workflow:casePack.role || casePack.workflow, revision:state.revision,
    object_source:{url:casePack.object_url || casePack.object?.url, accession_number:casePack.accession_number || casePack.object?.accession_number},
    catalogue:clone(state.catalogue), sources:clone(casePack.sources || []),
    images:(casePack.images || []).map(i => ({...clone(i), used_in_current_teaching_revision:isAvailable(i,state)})),
    documents:(casePack.documents || []).map(d => ({...clone(d), used_in_current_teaching_revision:isAvailable(d,state)})),
    observations:clone(state.observations),
    curated_research_examples:bindTeachingFindings(casePack,state,findingsFor(casePack,state)),
    teaching_opinion_versions:teachingOpinionVersions(casePack,state),
    teaching_opinion_history_notice:'所有 V1/V2 都是项目预先编写的教学材料；activated 只表示使用者是否纳入补充件。与浏览器真实编辑历史分开，不表示模型重跑或专家意见。',
    provenance:clone(casePack.provenance || []),
    active_supplements:clone(state.active_supplements),
    teaching_supplements:(casePack.supplements || []).map(s=>({id:s.id,title:s.title,reason:s.reason,change_note:s.change_note,activated:state.active_supplements.includes(s.id)})),
    user_notes:state.notes,
    human_review:{...clone(state.review), verified_identity:false, statement:'浏览器使用者自行填写的复核记录；未验证身份，不构成专家签署。'},
    limits:clone(casePack.limits || []), history:handoffHistory(casePack,state),
    integrity:{algorithm:'SHA-256', manifest:'manifest.json', statement:'摘要可核对文件是否改变；不证明内容真实、专家身份或鉴定正确。'}
  };
}

export async function sha256(bytes) {
  if (!globalThis.crypto?.subtle) throw new Error('浏览器不支持文件摘要，请使用 HTTPS 或 localhost 打开。');
  const data = typeof bytes === 'string' ? new TextEncoder().encode(bytes) : bytes;
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2,'0')).join('');
}

export async function buildBundleEntries(casePack, state, assetLoader, skills = [], now = new Date().toISOString()) {
  const report = buildReport(casePack,state,now);
  const entries = [];
  const imageLinks = {};
  for (const image of casePack.images || []) {
    const file = String(image.file || '').split('/').pop();
    if (!file || !/^[a-zA-Z0-9._-]+$/.test(file)) throw new Error('图像文件名不合法');
    const bytes = new Uint8Array(await assetLoader(image.file));
    const digest = await sha256(bytes);
    if (image.sha256 && image.sha256 !== digest) throw new Error(`图像摘要不匹配：${file}`);
    entries.push({path:`images/${file}`,data:bytes}); imageLinks[image.id] = `images/${file}`;
  }
  for (const document of casePack.documents || []) {
    const id = String(document.id || 'document');
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) throw new Error('资料编号不合法');
    const text = String(document.text || '');
    const digest = await sha256(text);
    if (document.sha256 && document.sha256 !== digest) throw new Error(`资料摘要不匹配：${id}`);
    entries.push({path:`documents/${id}.txt`,data:text});
  }
  for (const skill of skills) {
    const id = String(skill.id || '');
    if (!/^[a-z0-9_-]+$/.test(id)) throw new Error('Skill 编号不合法');
    const content = String(skill.content || skill.body || '');
    if (skill.sha256 && skill.sha256 !== await sha256(content)) throw new Error(`Skill 原文摘要不匹配：${id}`);
    entries.push({path:`skills/${id}/SKILL.md`,data:content});
    for (const reference of skill.references || []) {
      const path = String(reference.path || '').replace(/^\.\//,'');
      if (!path || path.startsWith('/') || path.includes('\\') || /(^|\/)\.\.(\/|$)/.test(path)) throw new Error('Skill 参考路径不合法');
      const content = String(reference.content || '');
      if (reference.sha256 && reference.sha256 !== await sha256(content)) throw new Error(`Skill 参考文件摘要不匹配：${id}/${path}`);
      entries.push({path:`skills/${id}/${path}`,data:content});
    }
  }
  entries.push({path:'report.json',data:JSON.stringify(report,null,2)});
  entries.push({path:'report.html',data:reportHTML(report,imageLinks)});
  entries.push({path:'README.txt',data:`瓷证公开教学案卷\n\n${TEACHING_NOTICE}\n\nai_inference_performed=false\n\n阅读 report.html 或 report.json。images/ 为公开馆藏图像；documents/ 为项目编写教学资料；skills/ 为本项目方法包原文。包括预置补充附件，是否纳入当前教学版本见报告标记。manifest.json 逐项列出文件字节数与 SHA-256，可验证文件是否改变，不能证明真实性、专家身份或鉴定正确。\n`});
  const files = [];
  for (const entry of entries) {
    const bytes = typeof entry.data === 'string' ? new TextEncoder().encode(entry.data) : entry.data;
    files.push({path:entry.path,bytes:bytes.length,sha256:await sha256(bytes)});
  }
  const manifest = {schema_version:'cizheng.public-teaching-bundle.v1',mode:'guided_teaching',ai_inference_performed:false,
    notice:TEACHING_NOTICE,case_id:casePack.id,revision:state.revision,generated_at:now,
    files,manifest_excludes_self:true,images_license:'Met public-domain / CC0; see report sources',
    integrity_statement:'SHA-256 verifies unchanged bytes. It does not authenticate the object, reviewer, evidence claim or attribution.'};
  entries.push({path:'manifest.json',data:JSON.stringify(manifest,null,2)});
  return {entries,report,manifest};
}

function checkedRegion(region) {
  if (!region) return null;
  const r={x:Number(region.x),y:Number(region.y),width:Number(region.width),height:Number(region.height)};
  if (!Object.values(r).every(Number.isFinite) || r.x<0 || r.y<0 || r.width<=0 || r.height<=0 ||
      r.x+r.width>1.000001 || r.y+r.height>1.000001) return null;
  return r;
}

export function reportHTML(report, images = {}) {
  const e=escapeHTML;
  const labels={museum:'博物馆 · 编目与研究',collection:'收藏者 · 资料核查',auction:'拍卖行 · 图录准备'};
  const sourceLink=(url,label)=>safeURL(url)?`<a href="${e(safeURL(url))}" rel="noreferrer">${e(label)}</a>`:e(label);
  const imageByID=new Map(report.images.map(i=>[i.id,i]));
  const documentByID=new Map(report.documents.map(d=>[d.id,d]));
  const sourceByID=new Map(report.sources.map(s=>[s.id,s]));
  const photoPath=(image)=>images[image.id] || `images/${String(image.file || '').split('/').pop()}`;
  const materialStatus=(material)=>material.used_in_current_teaching_revision?'已纳入当前教学版本':'预置补充附件；尚未用于当前教学意见';

  // The overlay fills the *actual image box*, not an object-fit letterbox.
  // JPEG bytes remain unchanged; coordinates are a separate, visible SVG layer.
  function imageRegion(citation,anchor) {
    const image=imageByID.get(citation.target_id || citation.ref_id);
    if (!image) return '<p class="meta">没有找到对应的公开图像，未绘制区域。</p>';
    const r=checkedRegion(citation.region);
    const numbers=r?`x=${r.x}, y=${r.y}, width=${r.width}, height=${r.height}`:'未提供有效区域；未绘制定位框';
    return `<figure class="citation-region" id="${e(anchor)}" data-image-reference="${e(image.id)}">
      <div class="citation-photo"><img src="${e(photoPath(image))}" alt="${e(image.view)}：${e(report.title)}">
      ${r?`<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label="观察定位框 ${e(numbers)}"
        data-region-citation="${e(anchor)}" data-image-id="${e(image.id)}" data-x="${r.x}" data-y="${r.y}" data-width="${r.width}" data-height="${r.height}">
        <rect x="${r.x*1000}" y="${r.y*1000}" width="${r.width*1000}" height="${r.height*1000}" fill="#a57d3230" stroke="#8f612b" stroke-width="4" vector-effect="non-scaling-stroke"></rect></svg>`:''}</div>
      <figcaption><strong>原图区域（归一化坐标）：${e(numbers)}</strong><br>
        ${e(image.view)} · ${e(materialStatus(image))}<br>
        定位框是独立覆盖层，未改动源 JPEG 像素；不是模型热力图。<br>
        <a href="#image-${e(image.id)}">回查原始图像与摘要</a> · ${sourceLink(image.source_url || report.object_source.url,'馆藏原始页面')}<br>
        <small>原图 SHA-256 ${e(image.sha256)}</small></figcaption></figure>`;
  }

  function citationHTML(citation,anchor) {
    const id=citation.target_id || citation.ref_id;
    if (citation.kind==='image') return `<li class="citation-item"><span class="meta">图像引用 ${e(id)}</span>${imageRegion(citation,anchor)}</li>`;
    if (citation.kind==='document') {
      const doc=documentByID.get(id);
      const start=Number(citation.locator?.start ?? 0),end=Number(citation.locator?.end ?? doc?.text.length ?? 0);
      return `<li class="citation-item" id="${e(anchor)}"><a href="#document-${e(id)}">${e(doc?.title || id)} · 字符 ${e(start)}–${e(end)}（0 基区间）</a>
        <blockquote class="quote" data-document-id="${e(id)}" data-start="${e(start)}" data-end="${e(end)}">${e(doc?.text.slice(start,end) || '未找到资料目标，无法核对原文。')}</blockquote>
        <p class="meta">${e(doc?materialStatus(doc):'目标缺失')}<br>资料 SHA-256 ${e(doc?.sha256 || '未知')}<br>${doc?.source_url?sourceLink(doc.source_url,'资料所引原始页面'):''}</p></li>`;
    }
    const source=sourceByID.get(id);
    return `<li class="citation-item" id="${e(anchor)}"><a href="#source-${e(id)}">${e(source?.title || id)}</a>
      <p class="meta">${e(source?.locator || '')} · ${e(source?.authority || '')}<br>${sourceLink(source?.url || '', '核对来源页面')}</p></li>`;
  }

  function findingHTML(f,prefix) {
    return `<article class="finding"><h4>${e(f.title || f.claim)}</h4><p>${e(f.text || f.detail)}</p>
      <p class="meta">项目人工编写教学示例 · ${e(f.status)} · ai_inference_performed=false</p>
      <ul class="citation-list">${(f.citations || []).map((c,index)=>citationHTML(c,`${prefix}-${f.id}-c${index}`)).join('')}</ul>
      ${f.next_evidence?`<p class="next-evidence">待补证：${e(f.next_evidence)}</p>`:''}</article>`;
  }

  const versions=report.teaching_opinion_versions || [];
  const versionHTML=versions.map(version=>`<section class="opinion-version" id="teaching-version-${e(version.id)}" data-teaching-version="${e(version.id)}" data-activated="${version.activated}" data-current="${version.current}">
    <h3>${e(version.label)}</h3><div class="version-notice">项目预先编写的教学意见 · 未运行模型<br>
      ${version.activated?'使用者已纳入该教学材料':'预览原文；补充件未激活，未用于当前教学意见'}${version.current?' · 当前教学意见':''}</div>
    <p><strong>编写／改变原因：</strong>${e(version.change_reason)}</p>
    <p class="meta">本预写版本参照的材料：图像 ${e(version.material_basis.image_ids.join(', '))}；资料 ${e(version.material_basis.document_ids.join(', '))}。
      这不表示未激活附件已被用于当前意见。</p>
    ${version.changes.some(c=>c.changed)?`<details class="change-summary" open><summary>对照 V1 的文字变化与原因</summary><ul>${version.changes.filter(c=>c.changed).map(c=>`<li><strong>${e(c.title)}</strong><p>V1：${e(c.before_text || '无此条目')}</p><p>${e(version.id.toUpperCase())}：${e(c.after_text)}</p><p class="meta">改变原因：${e(c.reason)}</p></li>`).join('')}</ul></details>`:''}
    ${version.findings.map(f=>findingHTML(f,`opinion-${version.id}`)).join('')}</section>`).join('');

  const historyHTML=report.history.map(h=>`<details class="history-entry"><summary>r${h.snapshot.revision} · ${e(h.action)} · ${e(h.at)}</summary>
    <p class="meta">${e(h.teaching_snapshot_notice || '真实浏览器编辑快照，与预写教学意见版本分开。')}</p>
    <p>当时纳入的补充件：${e((h.snapshot.active_supplements || []).join(', ') || '无')}</p>
    <p>当时的使用者备注：${e(h.snapshot.notes || '无')}</p>
    <p>当时复核状态：${e(h.snapshot.review?.status || '未复核')}。身份未验证。</p>
    ${(h.snapshot.curated_research_examples || []).map(f=>findingHTML(f,`history-r${h.snapshot.revision}`)).join('')}</details>`).join('');

  const rows=Object.entries(report.catalogue).map(([key,value])=>`<tr><th>${e(({inventory_number:'藏品编号',object_name:'名称',object_type:'器形',material:'材质与装饰',dimensions:'尺寸',requested_output:'研究任务'})[key] || key)}</th><td>${e(value)}</td></tr>`).join('');
  const figures=report.images.map(image=>`<figure id="image-${e(image.id)}"><img src="${e(photoPath(image))}" alt="${e(image.view)}"><figcaption>${e(image.view)} · ${e(materialStatus(image))}<br>
    <small>SHA-256 ${e(image.sha256)}</small><br>${sourceLink(image.source_url || report.object_source.url,'原始对象页面')}<br><small>${e(image.edit_declaration || '公开馆藏图像；本项目未改动源 JPEG 字节。')}</small></figcaption></figure>`).join('');
  const observations=report.observations.map((observation,index)=>`<article><h3>${e(observation.title || '观察')}</h3><p>${e(observation.text)}</p>
    <p class="meta">${observation.origin==='browser_user'?'使用者观察，未经专家确认':'项目编写教学观察'} · 未调用模型</p>
    ${imageRegion({target_id:observation.image_id,region:observation.region},`observation-${index}`)}</article>`).join('');
  const documents=report.documents.map(doc=>`<article id="document-${e(doc.id)}"><h3>${e(doc.title)}</h3><p class="meta">${e(doc.kind || '项目原创教学资料')} · ${e(doc.id)} · ${e(materialStatus(doc))}<br>SHA-256 ${e(doc.sha256 || '见 ZIP 清单')}</p>
    <pre>${e(doc.text)}</pre>${doc.source_url?sourceLink(doc.source_url,'资料引用的公开原始页面'):''}</article>`).join('');
  const sources=report.sources.map(source=>`<li id="source-${e(source.id)}">${sourceLink(source.url,source.title)}<br>${e(source.authority || '')} · ${e(source.license || '')}<br>
    定位：${e(source.locator || '见原始页面')}<br>${e(source.summary || '')}</li>`).join('');

  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${e(report.title)} · 瓷证教学案卷</title><style>
    body{font:16px/1.8 system-ui,sans-serif;background:#f4f1ea;color:#1b2f3f;margin:auto;max-width:1050px;padding:36px}
    h1,h2,h3,h4{font-family:Georgia,'Noto Serif SC',serif}h1{font-size:32px}h2{margin-top:42px;border-bottom:1px solid #cfc7b5;padding-bottom:10px}
    h3{font-size:23px}h4{font-size:20px;margin:0 0 12px}.notice,.version-notice{background:#f8eecd;border:1px solid #d7bf79;padding:16px}
    table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #ded9d0}th{width:140px}
    article{background:white;border:1px solid #e0dbd1;padding:18px;margin:14px 0}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}
    figure{margin:0}img{width:100%;max-height:480px;object-fit:contain;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit}
    .meta,small{font-size:13px;color:#586a78;overflow-wrap:anywhere}a{color:#245a76}li{margin:5px 0}.citation-list{padding-left:20px}
    .citation-item{padding:15px 0;border-top:1px dashed #d9d2c2}.citation-region{margin:12px 0}.citation-photo{position:relative;width:100%;max-width:430px}
    .citation-photo img{display:block;width:100%;height:auto;max-height:none}.citation-photo svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
    figcaption{font-size:13px;color:#5b635e;margin-top:8px;overflow-wrap:anywhere}.quote{white-space:pre-wrap;background:#f5f0e2;border-left:3px solid #ab8d52;padding:12px;margin:12px 0}
    .opinion-version{border:1px solid #c5b690;padding:22px;margin:24px 0;background:#fbf8f0}.change-summary,.history-entry{padding:15px;border:1px solid #ddd5c3;background:#f9f7f0;margin:15px 0}
    summary{cursor:pointer;font-weight:600}.next-evidence{border-top:1px solid #ddd3be;padding-top:12px}nav{display:flex;gap:15px;flex-wrap:wrap;font-size:13px;margin:20px 0}
    @media(max-width:600px){body{padding:18px;font-size:14px}h1{font-size:28px}.opinion-version{padding:15px}article{padding:14px}.citation-list{padding-left:15px}th{width:105px}}
    @media print{body{background:white;padding:0}.notice,.version-notice{background:white}article,.citation-region{break-inside:avoid}details>summary{list-style:none}}
    </style></head><body><p>瓷证 · 公开教学案卷</p><h1>${e(report.title)}</h1>
    <div class="notice">${e(report.notice)}<br><strong>ai_inference_performed = false</strong></div>
    <p>${e(labels[report.workflow] || report.workflow)} · 用户案卷版本 r${report.revision} · ${e(report.generated_at)}</p>
    <p>${sourceLink(report.object_source.url,'查看原始馆藏页面')} · 馆藏编号 ${e(report.object_source.accession_number)}</p>
    <nav aria-label="报告目录"><a href="#catalogue">编目</a><a href="#photos">原图</a><a href="#documents">资料原文</a><a href="#current-opinion">当前教学意见</a><a href="#opinion-versions">V1 / V2 原文</a><a href="#user-history">真实编辑历史</a></nav>
    <h2 id="catalogue">编目记录</h2><table>${rows}</table><h2 id="photos">公开原图与摘要</h2><div class="gallery">${figures}</div>
    <h2>观察记录与区域定位</h2>${observations}<h2 id="documents">定位资料原文</h2>${documents}
    <h2 id="current-opinion">当前纳入的预写教学意见</h2><p class="meta">以下意见来自项目预先编写的教学示例，只有已激活的补充件参与此部分。不是模型实时输出。</p>
    ${report.curated_research_examples.map(f=>findingHTML(f,'current')).join('')}
    <h2 id="opinion-versions">预写教学意见版本原文（V1 / V2）</h2><p>${e(report.teaching_opinion_history_notice || '所有意见均为项目预先编写的教学材料，与使用者真实编辑历史分开。')}</p>${versionHTML}
    <h2>来源清单</h2><ul>${sources}</ul><h2>公开来源记录与缺口</h2><ul>${(report.provenance || []).map(p=>`<li>${e(p.date_text || p.date || '')} · ${e(p.description || p.text || '')}<br><span class="meta">事件真实性与对象同一性未由本项目独立确认。</span></li>`).join('')}</ul>
    <h2>人工复核记录</h2><p>${e(report.human_review.statement)}</p><p>状态：${e(report.human_review.status)} · 填写者：${e(report.human_review.name || '未填写')}</p><pre>${e(report.human_review.notes || '尚未记录复核意见')}</pre>
    <h2>使用者备注</h2><pre>${e(report.user_notes || '无')}</pre><h2>边界与待办</h2><ul>${report.limits.map(l=>`<li>${e(typeof l==='string'?l:l.text || JSON.stringify(l))}</li>`).join('')}</ul>
    <h2 id="user-history">真实编辑历史（独立于预写意见版本）</h2><p class="meta">此处是浏览器内真实保存操作的快照；展开可复查当时的补证开关、记录与保存的教学发现。</p>${historyHTML}
    <p class="meta">${e(report.integrity.statement)}</p></body></html>`;
}
