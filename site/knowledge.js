(() => {
  'use strict';
  const list = document.querySelector('#sources'), count = document.querySelector('#count');
  const query = document.querySelector('#query'), institution = document.querySelector('#institution');
  let sources = [];
  const element = (tag, text, className) => {
    const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
    if (className) el.className = className; return el;
  };
  function render() {
    const needle = query.value.trim().toLocaleLowerCase('zh-CN');
    const filtered = sources.filter(s => (!institution.value || s.institution === institution.value) &&
      (!needle || [s.title, s.text, s.institution, s.scope, s.locator].join(' ').toLocaleLowerCase('zh-CN').includes(needle)));
    list.replaceChildren(); count.textContent = `显示 ${filtered.length} / ${sources.length} 条原创摘要 · 待专家审核 · 无模型推理`;
    if (!filtered.length) { list.append(element('p', '未找到匹配的摘要。试试器类、款识、旧补或来源机构。', 'empty')); return; }
    for (const s of filtered) {
      const card = element('article', undefined, 'source-card');
      card.append(element('h2', s.title));
      const meta = element('div', undefined, 'source-meta');
      meta.append(element('span', s.institution), element('span', s.year), element('span', '项目原创 · 待专家审核')); card.append(meta);
      card.append(element('p', s.text, 'source-text'));
      const link = element('a', '打开一手来源 ↗');
      try { const url = new URL(s.source_url); if (!['https:', 'http:'].includes(url.protocol)) throw new Error('scheme'); link.href = url.href; } catch { link.removeAttribute('href'); }
      link.rel = 'noopener'; card.append(link);
      const details = element('details'); details.append(element('summary', '查看定位、权利与使用局限'));
      details.append(element('p', '资料定位：' + s.locator), element('p', '适用范围：' + s.scope), element('p', '权利：' + s.rights_note));
      const limits = element('ul'); for (const limit of s.limitations || []) limits.append(element('li', limit)); details.append(limits);
      details.append(element('p', '摘要 SHA256：' + s.text_sha256)); card.append(details); list.append(card);
    }
  }
  query.addEventListener('input', render); institution.addEventListener('change', render);
  document.querySelector('form').addEventListener('submit', event => event.preventDefault());
  fetch('data/knowledge.json').then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(data => {
    sources = data.sources;
    for (const name of [...new Set(sources.map(s => s.institution))]) { const option = element('option', name); option.value = name; institution.append(option); }
    render();
  }).catch(() => { count.textContent = '摘要未能加载'; list.append(element('p', '请刷新页面，或从 GitHub 仓库阅读 knowledge/seeds.json。', 'page-error')); });
})();
