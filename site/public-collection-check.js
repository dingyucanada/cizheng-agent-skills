/* Read-only projection of a published public-collection check. No inference calls. */
(() => {
  'use strict';
  const DATA_URL = 'assets/public-collection-check-20260929.json';
  const $ = id => document.getElementById(id);
  const strings = value => typeof value === 'string' ? value : value == null ? '' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  const list = value => Array.isArray(value) ? value : [];
  const text = (tag, value, className) => { const el = document.createElement(tag); el.textContent = strings(value); if (className) el.className = className; return el; };
  const safeURL = (value, {localOnly = false} = {}) => {
    if (typeof value !== 'string' || !value.trim()) return null;
    try { const url = new URL(value, document.baseURI); if (!['http:', 'https:'].includes(url.protocol)) return null; if (localOnly && url.origin !== location.origin) return null; return url.href; } catch { return null; }
  };
  const link = (label, value) => { const url = safeURL(value); if (!url) return null; const a = text('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; };
  const map = (value, mapping) => mapping[value] || strings(value) || '未记录';
  const dimensionLabels = {period:'制作时期',kiln:'窑口归属',style:'装饰风格',observation:'照片观察',observations:'照片观察',citation:'引用依据',citations:'引用依据',reasoning:'判断理由',limitations:'研究局限',evidence_request:'补证建议'};
  const claimLabels = {supported:'模型认为有支持',conflicting:'发现矛盾',insufficient:'依据不足',out_of_scope:'超出范围'};
  const stateLabels = {waiting:'等待补证',waiting_evidence:'等待补证',waiting_for_evidence:'等待补证',awaiting_evidence:'等待补证',needs_evidence:'等待补证',ready:'已生成记录',completed:'已生成记录',complete:'已生成记录',success:'已生成记录',succeeded:'已生成记录',failed:'运行失败',error:'运行异常',running:'运行中',pending:'尚未完成',not_run:'尚未运行',needs_review:'等待复核',waiting_for_review:'等待复核'};
  const modeLabels = {plain:'普通提示',baseline:'普通提示',no_skills:'普通提示',skills:'Skills 流程',skill:'Skills 流程',with_skills:'Skills 流程'};
  const initialSelection = new URLSearchParams(location.search);
  let data, selected, stage = initialSelection.get('stage') === 'b' ? 'b' : 'a', selectedMode;

  function rows(container, entries) {
    const dl = document.createElement('dl');
    for (const [label, value] of entries) { const row = document.createElement('div'); row.append(text('dt', label), text('dd', strings(value) || '未记录')); dl.append(row); }
    container.append(dl); return dl;
  }
  function sectionHeading(container, number, label) { const row = text('div', '', 'section-label'); row.append(text('span', number), text('h3', label)); container.append(row); }
  function bulletBlock(container, title, values) {
    const items = list(values); if (!items.length) return;
    const block = text('section', '', 'detail-block'); block.append(text('h4', title)); const ul = document.createElement('ul'); for (const value of items) ul.append(text('li', value)); block.append(ul); container.append(block);
  }
  function showCase(caseID) {
    selected = list(data.cases).find(item => item.id === caseID); if (!selected) return;
    for (const button of $('case-list').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.caseId === caseID));
    $('workbench-placeholder')?.remove(); $('case-workbench').hidden = false;
    $('case-number').textContent = '个案 ' + String(list(data.cases).indexOf(selected) + 1).padStart(2, '0');
    $('case-title').textContent = strings(selected.title); $('case-accession').textContent = selected.accession ? '馆藏编号 ' + strings(selected.accession) : '馆藏编号未记录';
    const objectURL = safeURL(selected.object_url); $('object-link').hidden = !objectURL; if (objectURL) $('object-link').href = objectURL; else $('object-link').removeAttribute('href');
    $('photos').replaceChildren();
    list(selected.images).forEach((image, index) => {
      const figure = text('figure', '', 'photo-frame');
      const button = text('button', '', 'photo-button'); button.type = 'button'; button.setAttribute('aria-label', '放大照片 ' + (index + 1));
      const img = document.createElement('img'); const src = safeURL(image.src); img.alt = strings(image.alt) || '器物照片 ' + (index + 1); img.loading = 'eager'; if (src) img.src = src; img.addEventListener('error', () => { img.hidden = true; button.append(text('p', '照片未能载入；请查看官方馆藏原图。', 'empty-note')); }, {once:true});
      button.append(img); button.disabled = !src; button.addEventListener('click', () => { if (!src) return; $('dialog-photo').src = src; $('dialog-photo').alt = img.alt; $('dialog-caption').textContent = strings(image.alt) || '公开馆藏照片 ' + (index + 1); $('photo-dialog').showModal(); });
      const caption = document.createElement('figcaption'); const label = text('div', '', 'photo-caption'); label.append(text('span', '原图 ' + String(index + 1).padStart(2,'0')), text('span', strings(image.alt))); caption.append(label);
      if (image.sha256) { const details = document.createElement('details'); details.append(text('summary', '原图 SHA-256'), text('code', image.sha256)); caption.append(details); }
      figure.append(button, caption); $('photos').append(figure);
    });
    const reference = selected.museum_reference || {}; $('museum-reference').replaceChildren();
    rows($('museum-reference'), [['年代',reference.period],['日期',reference.date],['材质',reference.medium],['尺寸',reference.dimensions]]);
    if (reference.note) $('museum-reference').append(text('p', reference.note)); const sourceLink = link('查看官方原始记录 ↗', selected.object_url); if (sourceLink) $('museum-reference').append(sourceLink);
    $('case-review').replaceChildren();
    const reviews = list(selected.review); if (!reviews.length) $('case-review').append(text('p', '本件尚未写入资料核查记录。模型输出仍完整保留。', 'empty-note'));
    reviews.forEach(review => { const row = text('article', '', 'review-row'); const body = document.createElement('div'); body.append(text('strong', strings(review.verdict) || '尚未判定'), text('p', review.basis)); row.append(text('div', map(review.dimension, dimensionLabels), 'review-dimension'), body); $('case-review').append(row); });
    /* Reset answer disclosure on every new case; it is not a blind-sample guarantee. */
    for (const details of document.querySelectorAll('.source-details')) details.open = false;
    selectedMode = undefined; renderRuns();
  }
  function renderRuns() {
    const runs = list(stage === 'a' ? selected.stage_a : selected.stage_b);
    const validMode = runs.some(run => run.mode === selectedMode); if (!validMode) selectedMode = runs.find(run => run.assessment && typeof run.assessment === 'object')?.mode ?? runs[0]?.mode;
    const protocol = data.protocol || {};
    $('stage-description').textContent = strings(stage === 'a' ? protocol.stage_a_description : protocol.stage_b_description) || (stage === 'a' ? '首轮仅给照片，未提供本件馆藏归属；比较普通提示和 Skills 流程。' : '本阶段已向模型提供馆藏资料，观察引用和解释是否符合资料。');
    $('record-panel').setAttribute('aria-labelledby', 'tab-' + stage);
    document.querySelectorAll('.stage-tab').forEach(button => button.setAttribute('aria-selected', String(button.dataset.stage === stage)));
    $('mode-list').replaceChildren();
    runs.forEach(run => { const button = text('button', map(run.mode, modeLabels), 'mode-button'); button.type = 'button'; button.dataset.mode = strings(run.mode); button.setAttribute('aria-pressed', String(run.mode === selectedMode)); button.addEventListener('click', () => { selectedMode = run.mode; renderRuns(); }); $('mode-list').append(button); });
    $('run-meta').replaceChildren(); $('model-record').replaceChildren();
    const run = runs.find(item => item.mode === selectedMode);
    if (!run) { $('model-record').append(text('p', '本阶段尚未写入运行记录。没有完成的结果不会显示为成功。', 'empty-note')); return; }
    const state = strings(run.state); const isError = /failed|error/.test(state), waiting = /waiting|pending|evidence|running|review|not_run/.test(state);
    $('run-meta').append(text('span', map(state, stateLabels), 'state' + (isError ? ' error' : waiting ? ' warning' : '')));
    const meta = text('div', '', 'run-details'); if (typeof run.seconds === 'number' && Number.isFinite(run.seconds)) meta.append(text('span', '本次运行 ' + run.seconds.toFixed(1) + ' 秒'));
    const original = link('原始运行记录 ↗', run.original_record_url); if (original) meta.append(original); $('run-meta').append(meta);
    const container = $('model-record');
    if (run.error) container.append(text('p', '保留运行异常\n' + strings(run.error), 'failure-note'));
    sectionHeading(container, '01', '照片观察');
    const observations = list(run.observations); if (!observations.length) container.append(text('p', '本次没有形成可展示的照片观察。请结合状态和原始记录阅读。', 'empty-note'));
    const observationNumbers = new Map(observations.map((observation,index) => [strings(observation.id),index + 1]));
    const mediaLabels = run.media_labels && typeof run.media_labels === 'object' ? run.media_labels : {};
    observations.forEach((observation, index) => {
      const card = text('article', '', 'observation'); card.id = 'observation-' + (index + 1); const header = document.createElement('header'); header.append(text('strong', '观察' + String(index + 1).padStart(2,'0')), text('span', strings(mediaLabels[observation.media_id]) || (observation.media_id ? '原图标识待核对' : '原图未关联'))); card.append(header);
      const dl = rows(card, [['模型可见描述',observation.visible],['模型解释',observation.interpretation || '未提出解释'],['局限',observation.limitation || '未单独记录局限']]); dl.lastElementChild.classList.add('limitation'); const ids = text('details', '', 'raw-identifiers'); ids.append(text('summary','原始观察及照片标识'),text('code','观察：' + strings(observation.id) + '\n照片：' + strings(observation.media_id))); card.append(ids); container.append(card);
    });
    sectionHeading(container, '02', '判断理由');
    const assessment = run.assessment;
    if (!assessment || typeof assessment !== 'object') container.append(text('p', '本次未形成结构化研判。补证或运行异常会完整保留，不以资料答案补写模型结论。', 'empty-note'));
    else {
      if (assessment.basic_info) container.append(text('p', assessment.basic_info, 'assessment-intro'));
      list(assessment.claims).forEach(claim => { const card = text('article', '', 'claim'); const h = text('h4', map(claim.dimension, dimensionLabels)); h.append(text('span', map(claim.status, claimLabels))); card.append(h, text('p', '候选：' + (claim.candidate === 'insufficient' ? '依据不足' : strings(claim.candidate)), 'claim-candidate'), text('p', claim.reasoning_summary, 'reason')); for (const [label,ids] of [['支持观察',list(claim.support)],['矛盾观察',list(claim.conflict)]]) if (ids.length) { const basis = text('p',label + '：','claim-basis'); ids.forEach((id,index) => { if (index) basis.append(document.createTextNode('、')); const number = observationNumbers.get(strings(id)); if (number) { const a = text('a','观察' + String(number).padStart(2,'0')); a.href = '#observation-' + number; basis.append(a); } else basis.append(document.createTextNode('未匹配观察（原始标识见下载记录）')); }); card.append(basis); } container.append(card); });
      bulletBlock(container, '其他解释', assessment.alternatives); bulletBlock(container, '研究局限', assessment.limitations); bulletBlock(container, '状况假设', assessment.condition_hypotheses);
      if (assessment.reference_comparison) { const block = text('section', '', 'detail-block'); block.append(text('h4', '参照比较'), text('p', assessment.reference_comparison)); container.append(block); }
      if (assessment.revision_explanation) { const block = text('section', '', 'detail-block'); block.append(text('h4', '修订理由'), text('p', assessment.revision_explanation)); container.append(block); }
      const citations = list(assessment.knowledge_citations); const block = text('section', '', 'detail-block'); block.append(text('h4', '记录中的资料引用'));
      if (!citations.length) block.append(text('p', '本次未记录资料引用。不能据此声称判断已有文献支持。'));
      citations.forEach(citation => { const row = text('div', '', 'citation'); row.append(text('strong', strings(citation.document_id) + (citation.document_revision ? ' · 版本 ' + citation.document_revision : '')), text('p', citation.locator), text('p', '引用用途：' + map(citation.use, {method:'方法参考',comparison_context:'比较语境',source_context:'来源语境'})), text('p', citation.relevance)); if (citation.chunk_sha256) row.append(text('code', '资料片段 SHA-256：' + citation.chunk_sha256)); block.append(row); }); if (citations.length) block.append(text('p', '资料被引用，不代表已经证明本件的年代或窑口；应结合引用用途和具体判断理由核查。')); container.append(block);
    }
    const sourceContexts = list(run.source_contexts);
    if (sourceContexts.length) { const details = text('details', '', 'record-disclosure'); details.append(text('summary','实际读到的来源文字')); const body = text('div', '', 'details-body'); body.append(text('p','以下为实际 read_knowledge 回执中的来源文字。读取不等于该引用已被意见采纳；应分别检查保存意见中的引用和判断理由。')); sourceContexts.forEach(source => { const row = text('article', '', 'source-context'); row.append(text('h4', source.title || '来源片段'),text('p',source.locator),text('p',source.text,'source-text')); if (source.use) row.append(text('p','读取用途：' + map(source.use,{method:'方法参考',comparison_context:'比较语境',source_context:'来源语境',read_receipt_not_automatic_claim_support:'阅读回执，尚非意见引用'}))); if (source.chunk_sha256) row.append(text('code','资料片段 SHA-256：' + strings(source.chunk_sha256))); body.append(row); }); details.append(body); container.append(details); }
    const validationErrors = list(run.validation_errors);
    if (validationErrors.length) { const details = text('details', '', 'record-disclosure'); details.append(text('summary','停止或修正的原因')); const body = text('div', '', 'details-body'); body.append(text('p','以下记录未通过校验或触发修正的步骤。被拒绝的提交不视为成功意见；上方研判仅展示实际保存的 assessment，运行状态保持原样。')); validationErrors.forEach(error => { const row = text('article', '', 'source-context'); row.append(text('h4',strings(error.stage) || '校验步骤'),text('p',error.detail)); body.append(row); }); details.append(body); container.append(details); }
    const requests = Array.isArray(run.evidence_request) ? run.evidence_request : run.evidence_request ? [run.evidence_request] : [];
    requests.forEach(request => { const card = text('section', '', 'evidence-request'); card.append(text('h4', '下一步应补什么')); if (typeof request === 'object') rows(card, [['视角',request.view],['原因',request.reason],['区分目标',request.distinguishes],['拍摄建议',request.capture_instructions]]); else card.append(text('p', request)); container.append(card); });
  }
  $('tab-a').addEventListener('click', () => { if (!selected) return; stage = 'a'; selectedMode = undefined; renderRuns(); });
  $('tab-b').addEventListener('click', () => { if (!selected) return; stage = 'b'; selectedMode = undefined; renderRuns(); });
  document.querySelector('.stage-tabs').addEventListener('keydown', event => { if (!['ArrowLeft','ArrowRight'].includes(event.key) || !selected) return; event.preventDefault(); stage = stage === 'a' ? 'b' : 'a'; selectedMode = undefined; renderRuns(); $('tab-' + stage).focus(); });
  $('close-photo').addEventListener('click', () => $('photo-dialog').close());
  $('photo-dialog').addEventListener('click', event => { if (event.target === $('photo-dialog')) { const r = $('photo-dialog').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('photo-dialog').close(); } });
  fetch(DATA_URL, {credentials:'omit', cache:'no-cache'}).then(response => { if (!response.ok) throw new Error('HTTP ' + response.status); return response.json(); }).then(result => {
    if (!result || !list(result.cases).length) throw new Error('尚无公开个案记录'); data = result;
    const title = strings(data.title) || '公开馆藏个案核查';
    document.title = title + ' · 瓷证';
    const emphasis = title.lastIndexOf('个案核查');
    if (emphasis > 0 && emphasis + 4 === title.length) $('page-title').replaceChildren(document.createTextNode(title.slice(0, emphasis).trim()), document.createElement('br'), text('em', '个案核查'));
    else $('page-title').textContent = title;
    if (data.scope) $('scope-note').textContent = strings(data.scope);
    $('checked-at').textContent = data.checked_at ? '记录时间 ' + strings(data.checked_at) : '核查日期未记录';
    const protocol = data.protocol || {}; $('protocol-content').replaceChildren();
    for (const [label,value] of [['阶段 A',protocol.stage_a_description],['阶段 B',protocol.stage_b_description]]) if (value) { const p = text('p', label + '：' + strings(value)); $('protocol-content').append(p); }
    $('protocol-content').append(text('p', '阶段 A 的普通提示组和 Skills 组使用相同协调器预备、模型、工具权限、预算和结论合同；Skills 组额外读取方法包。没有参照时的欠证结论不等于专业准确率。'));
    $('protocol-content').append(text('p', '页面默认优先展示已有保存意见的运行，仅为阅读安排，不改变结果计数。失败或尚未形成意见的记录仍可切换查看。'));
    const limits = Array.isArray(protocol.limits) ? protocol.limits : protocol.limits ? [protocol.limits] : []; limits.forEach(value => $('protocol-content').append(text('p', value)));
    $('protocol-content').append(text('p', '公开资料核查不等于真人专家评阅。历史上是否存在训练数据曝光无法由本页面排除；不得把本轮个案推广为总体准确率或真品概率。'));
    $('case-list').replaceChildren();
    list(data.cases).forEach((item,index) => { const button = text('button', '', 'case-card'); button.type = 'button'; button.dataset.caseId = strings(item.id); button.setAttribute('aria-pressed','false'); const image = list(item.images)[0]; if (image) { const img = document.createElement('img'); const src = safeURL(image.src); if (src) img.src = src; img.alt = ''; img.loading = 'eager'; button.append(img); } const body = document.createElement('div'); body.append(text('span','CASE '+String(index+1).padStart(2,'0'),'case-kicker'),text('strong',item.title),text('small',item.accession ? '馆藏编号 '+strings(item.accession) : '公开馆藏个案')); button.append(body); button.addEventListener('click', () => showCase(item.id)); $('case-list').append(button); });
    $('load-status').textContent = '已载入公开原图和实际运行记录。选择个案后即可核查，无需上传材料。';
    const requestedCase = list(data.cases).find(item => strings(item.id) === initialSelection.get('case'));
    showCase(requestedCase ? requestedCase.id : data.cases[0].id);
  }).catch(error => { $('load-status').textContent = '公开核查记录暂未载入（' + strings(error.message) + '）。请稍后刷新，或先阅读项目报告。'; $('load-status').classList.add('error'); $('checked-at').textContent = '记录暂未载入'; });
})();
