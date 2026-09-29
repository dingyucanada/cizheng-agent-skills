import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

// Package reviewed, native Office exports. Inputs stay local; public files use relative paths.
const required = ['PITCH_FINAL_PPTX', 'PITCH_FINAL_PDF', 'PITCH_RENDER_DIR', 'PITCH_NOTES_JSON', 'PITCH_QA_JSON', 'PITCH_OVERLAY'];
for (const key of required) if (!process.env[key]) throw new Error(`Missing ${key}`);
const env = Object.fromEntries(required.map(key => [key, path.resolve(process.env[key])]));
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const authoring = path.resolve(process.env.PITCH_AUTHORING_SOURCE ?? path.join(scriptDir, 'build-pitch-v09.mjs'));
const overlay = env.PITCH_OVERLAY;
const assets = path.join(overlay, 'site/assets');
const frames = path.join(assets, 'cizheng-pitch-v09');
const docs = path.join(overlay, 'docs');
const scripts = path.join(overlay, 'scripts');
await Promise.all([assets, frames, docs, scripts].map(dir => fs.mkdir(dir, { recursive: true })));
const notes = JSON.parse(await fs.readFile(env.PITCH_NOTES_JSON, 'utf8'));
if (notes.length !== 12 || notes.some((n, i) => n.slide !== i + 1)) throw new Error('Expected 12 sequential speaker notes');

const hash = async filename => crypto.createHash('sha256').update(await fs.readFile(filename)).digest('hex');
const qa = JSON.parse(await fs.readFile(env.PITCH_QA_JSON, 'utf8'));
if (qa.status !== 'pass' || qa.pptx.sha256 !== await hash(env.PITCH_FINAL_PPTX) || qa.pdf.sha256 !== await hash(env.PITCH_FINAL_PDF)) {
  throw new Error('QA must be bound to the exact finalized PPTX and Office PDF');
}
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
function sourceItem(value) {
  const match = String(value).match(/https:\/\/[^\s]+$/);
  if (!match) return escape(value);
  const label = String(value).slice(0, match.index).trim();
  return `${label ? escape(label) + ' ' : ''}<a href="${escape(match[0])}" target="_blank" rel="noopener noreferrer">${escape(match[0])}</a>`;
}

await fs.copyFile(env.PITCH_FINAL_PPTX, path.join(assets, 'cizheng-pitch-v07.pptx'));
await fs.copyFile(env.PITCH_FINAL_PDF, path.join(assets, 'cizheng-pitch-v07.pdf'));
for (let i = 1; i <= 12; i++) {
  const filename = `slide-${String(i).padStart(2, '0')}.png`;
  await fs.copyFile(path.join(env.PITCH_RENDER_DIR, filename), path.join(frames, filename));
}
await fs.copyFile(authoring, path.join(scripts, 'build-pitch-v09.mjs'));
await fs.copyFile(fileURLToPath(import.meta.url), path.join(scripts, 'export-pitch-v09.mjs'));
await fs.copyFile(env.PITCH_QA_JSON, path.join(docs, 'pitch-v09-qa.json'));

const sections = notes.map(entry => {
  const number = String(entry.slide).padStart(2, '0');
  return `<section id="slide-${number}" aria-labelledby="title-${number}">
    <div class="caption"><span>${number} / 12</span><h2 id="title-${number}">${escape(entry.title)}</h2><a href="#top" aria-label="回到页首">回到页首 ↑</a></div>
    <a class="frame" href="cizheng-pitch-v09/slide-${number}.png" target="_blank" rel="noopener"><img src="cizheng-pitch-v09/slide-${number}.png" width="1920" height="1080" alt="第${entry.slide}页：${escape(entry.title)}" ${entry.slide > 1 ? 'loading="lazy"' : 'fetchpriority="high"'}></a>
    <details><summary>讲稿与来源</summary><p>${escape(entry.speaking)}</p><ul>${entry.sources.map(source => `<li>${sourceItem(source)}</li>`).join('')}</ul></details>
  </section>`;
}).join('\n');
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>瓷证 · 中文路演</title>
<style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#eef4f8;color:#1c334b;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.7}a{color:#245b88;text-underline-offset:3px}a:focus-visible,summary:focus-visible{outline:3px solid #ae8b4a;outline-offset:4px}header{background:#132d49;color:#fff;padding:36px max(24px,calc((100vw - 1180px)/2));border-bottom:4px solid #ae8b4a}header p{color:#c7d6e2;max-width:760px;margin:9px 0 20px}h1{font-size:32px;letter-spacing:.06em;line-height:1.35;margin:0}header nav{display:flex;flex-wrap:wrap;gap:12px 28px}header a{color:#fff}.index{max-width:1180px;margin:22px auto;padding:0 18px;display:flex;flex-wrap:wrap;gap:8px}.index a{background:#fff;border:1px solid #c7d5e0;text-decoration:none;padding:3px 11px;border-radius:3px}main{max-width:1220px;margin:0 auto;padding:0 18px 54px}section{margin:26px 0 40px;scroll-margin-top:16px}.caption{display:flex;align-items:baseline;gap:16px;margin-bottom:10px}.caption span{font-variant-numeric:tabular-nums;color:#5e7181;font-size:14px;white-space:nowrap}h2{font-size:21px;line-height:1.4;margin:0;font-weight:600;flex:1}.caption>a{font-size:13px;white-space:nowrap}.frame{display:block;background:#fff;box-shadow:0 5px 18px #132d4917;line-height:0}.frame img{display:block;width:100%;height:auto;aspect-ratio:16/9}details{margin-top:9px;padding:7px 14px;background:#fff;border:1px solid #dbe5ed;font-size:15px}summary{cursor:pointer;color:#245b88}details p{margin:12px 0}details ul{padding-left:22px}details li{overflow-wrap:anywhere;margin:5px 0}footer{max-width:1180px;margin:0 auto;padding:0 18px 38px;color:#5e7181;font-size:13px}@media(max-width:640px){header{padding:26px 18px}h1{font-size:27px}header p{font-size:15px}main{padding:0 10px 26px}.index{padding:0 10px;gap:6px}.index a{font-size:13px;padding:2px 8px}.caption{gap:10px;flex-wrap:wrap}h2{font-size:17px;flex-basis:calc(100% - 75px)}.caption>a{display:none}section{margin:22px 0}details{font-size:14px;padding:7px 10px}}@media print{header,.index,details,footer,.caption>a{display:none}body,main{margin:0;padding:0;background:#fff;max-width:none}section{break-after:page;margin:0}.caption{display:none}.frame{box-shadow:none}}
</style></head><body id="top">
<header><h1>瓷证 · 中文路演</h1><p>个人参赛作品。原件、观察、资料与待补证，保存在一份可继续复核的陶瓷案卷中。</p><nav aria-label="资料入口"><a href="cizheng-pitch-v07.pptx" download>下载可编辑 PPTX</a><a href="cizheng-pitch-v07.pdf" download>下载 PDF</a><a href="../report.html">图文报告书</a><a href="../demo.html">教学体验</a><a href="https://github.com/dingyucanada/cizheng-agent-skills" target="_blank" rel="noopener noreferrer">公开源码</a></nav></header>
<nav class="index" aria-label="幻灯片目录">${notes.map(entry => `<a href="#slide-${String(entry.slide).padStart(2,'0')}">${String(entry.slide).padStart(2,'0')}</a>`).join('')}</nav>
<main>${sections}</main><footer>12 页 · v0.9 · 2026.09。器物图像来自 The Metropolitan Museum of Art 的 Public Domain / CC0 公开馆藏；具体出处见每页讲稿。页面图像对应同一份 PPTX 经 Office 导出的 PDF。</footer>
</body></html>\n`;
await fs.writeFile(path.join(assets, 'cizheng-pitch-v07-preview.html'), html);
await fs.writeFile(path.join(docs, 'pitch-v09-notes.md'), `# 瓷证中文路演讲稿\n\n个人参赛作品，12 页，v0.9。\n\n${notes.map(entry => `## ${String(entry.slide).padStart(2,'0')} ${entry.title}\n\n${entry.speaking}\n\n来源：\n\n${entry.sources.map(source => `- ${source}`).join('\n')}`).join('\n\n')}\n`);
await fs.writeFile(path.join(docs, 'pitch-v09-build.md'), `# 瓷证路演 v0.9\n\n本目录的幻灯片为 12 页中文个人参赛作品，使用 \`@oai/artifact-tool\` JavaScript 创作。中文架构、业务链路、方法加载与研究路线均为原生可编辑文本、形状和连接线；第 7、8、10 页为原生表格。截图与馆藏照片为图像。\n\n稳定入口保留为 \`site/assets/cizheng-pitch-v07.pptx\`、\`site/assets/cizheng-pitch-v07.pdf\` 与 \`site/assets/cizheng-pitch-v07-preview.html\`。版本号不改变已提交的网址。\n\n## 复现\n\n准备 Node.js、\`@oai/artifact-tool\`、presentations 技能运行时、可用中文字体、LibreOffice 与 Poppler。将运行时绝对路径仅放入本机环境变量，不写入公开文件。源目录应包含公开仓库的 \`site/assets\` 输入素材。\n\n1. 设置 \`PITCH_SOURCE\`（源仓库）、\`PITCH_WORKSPACE\`（独立私有构建目录）、\`PITCH_REVISION\`（版本标签）、\`PRESENTATIONS_SKILL_DIR\`、\`RUNTIME_PYTHON\` 与 \`RUNTIME_NODE_MODULES\`，运行 \`scripts/build-pitch-v09.mjs\`。\n2. 用独立 LibreOffice 用户配置将最终 PPTX 转为 PDF。为中文字体设置本机 Fontconfig；不要将字体缓存、配置路径或运行时日志放入公开包。\n3. 用 \`pdftoppm -png -scale-to-x 1920 -scale-to-y 1080\` 渲染该 PDF 的每一页，文件前缀为 \`slide\`。逐页核对实际导出的文字、表格、连接线、图像和链接色。\n4. 设置 \`PITCH_FINAL_PPTX\`、\`PITCH_FINAL_PDF\`、\`PITCH_RENDER_DIR\`、\`PITCH_NOTES_JSON\`、\`PITCH_QA_JSON\`、\`PITCH_OVERLAY\` 与 \`PITCH_AUTHORING_SOURCE\`，运行 \`scripts/export-pitch-v09.mjs\`。该步骤只复制已核对的文件和真实 PDF 渲染图，不重新绘制页面。QA JSON 参照本目录记录格式，绑定实际成品的 SHA。\n\n## 素材与边界\n\n馆藏器物图像来自 Met Public Domain / CC0：18.61.4（48607，整体正面与另一面分别使用一次）、79.2.1202a,b（51185）、61.200.30（50839）。每张原图尽量只在一页使用，来源与 SHA 见清单。公开工作台截图来自项目已保存的软件界面；教学案与合成协议练习均在讲稿及相关页面明确标记。未复制参考演讲的图片、设备、专利或身份。\n\n主视觉仍为 Qwen3-VL-8B 与 SQLite 案卷资料路径；NIM、TensorRT-LLM 文字与 Embedding + cuVS 为独立已部署、实测服务。Agent Skills 方法效果、真品概率校准与独立专家评价列入发展计划。受控采集、眼镜 SDK、桌面箱、NVFLARE 与 NeMo RL 为后续研究。没有虚构团队、合作、专业准确率或厂商背书。\n\n## 验证范围\n\n最终 PPTX 的包完整性、布局几何、字体选择、12 页数量、最终文件回读、3 张原生表格及六维权重合计 100 已通过结构检查。实际 LibreOffice PDF 有 12 页，已全页渲染并逐页视觉核对；HTML 预览使用该 PDF 的 12 张图。此结果不等于在原生 Microsoft PowerPoint 中执行验证，也不证明专业鉴定准确率。\n`);

const inputSources = [
  {path:'site/assets/met-48607.jpg', sha256:'0cafb54b1f5edb156a96bd05a8c507bb500b76bb5f2a423778e306a27868febc', license:'Public Domain / CC0', source:'https://www.metmuseum.org/art/collection/search/48607', slide:1},
  {path:'site/assets/met-51185.jpg', sha256:'01401537e5591a07f4c5a6b3f24ae8c37def39d5e0dae71275c0edce6154839b', license:'Public Domain / CC0', source:'https://www.metmuseum.org/art/collection/search/51185', slide:2},
  {path:'site/assets/met-48607-view2.jpg', sha256:'383ae83bba805f8bc8e0b5a0eb7ec1e0fef705447a94e5e4fdb3bc3ca792964f', license:'Public Domain / CC0', source:'https://www.metmuseum.org/art/collection/search/48607', slide:9},
  {path:'site/assets/met-50839.jpg', sha256:'1cc100a71af987f0bcbb05633fafb719d212bc0e9112e8ba0c80756a11e65c8a', license:'Public Domain / CC0', source:'https://www.metmuseum.org/art/collection/search/50839', slide:12}
];
for (const [filename, slide, sha256] of [['workbench-v06.jpg',3,'3600a41a3426fff6ecd14d649ee8ee9bcee954c19abdffa064d209dafc4487da'],['risk-workbench-v09.png',8,'43e24595f2aa21f568852c1ceb256d8eb53c1b81800039207dbfb17831dad9bc']]) {
  inputSources.push({path:`site/assets/${filename}`, sha256, kind:'real_project_workbench_screenshot', source:`https://github.com/dingyucanada/cizheng-agent-skills/blob/main/site/assets/${filename}`, slide});
}
async function walk(dir) {
  const files = [];
  for (const entry of await fs.readdir(dir, {withFileTypes:true})) {
    const filename = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(filename));
    else if (entry.isFile()) files.push(filename);
  }
  return files;
}
const manifestPath = path.join(docs, 'pitch-v09-artifacts.json');
const files = (await walk(overlay)).filter(filename => filename !== manifestPath).sort();
const artifacts = [];
for (const filename of files) artifacts.push({path:path.relative(overlay,filename).split(path.sep).join('/'),bytes:(await fs.stat(filename)).size,sha256:await hash(filename)});
await fs.writeFile(manifestPath, JSON.stringify({
  schema:'cizheng-pitch-artifacts-v1',version:'0.9',language:'zh-CN',slide_count:12,
  rendering:{pdf_producer:'LibreOfficeDev 26.8.0.0.alpha0',source:'same finalized editable PPTX',preview_source:'actual exported PDF pages',width:1920,height:1080,reviewed_page_count:12},
  editable:{native_diagrams:true,native_table_slides:[7,8,10],notes:12},
  checks:{package_integrity:'pass',layout_geometry:'pass',declared_font_selection:'pass',final_pptx_import:'pass',six_dimension_weights_total:100,native_powerpoint_execution:false,professional_accuracy_claimed:false},
  input_sources:inputSources,artifacts,
  manifest_scope:'All overlay files except this self-referential manifest. Original source images are embedded in PPTX; not copied again into this overlay.'
},null,2)+'\n');
console.log(JSON.stringify({overlay_file_count:artifacts.length+1,pptx_sha256:await hash(path.join(assets,'cizheng-pitch-v07.pptx')),pdf_sha256:await hash(path.join(assets,'cizheng-pitch-v07.pdf')),preview_sha256:await hash(path.join(assets,'cizheng-pitch-v07-preview.html')),manifest_sha256:await hash(manifestPath)}));
