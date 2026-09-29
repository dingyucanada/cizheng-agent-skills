import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';

// Reproducible authoring. Supply absolute runtime/source/workspace paths locally.
// No account configuration, original private images, or model weights are read.
const source = path.resolve(process.env.PITCH_SOURCE ?? '.');
const workspace = path.resolve(process.env.PITCH_WORKSPACE ?? 'pitch-private-build');
const skill = process.env.PRESENTATIONS_SKILL_DIR;
const python = process.env.RUNTIME_PYTHON;
if (!path.isAbsolute(skill ?? '') || !path.isAbsolute(python ?? '')) {
  throw new Error('PRESENTATIONS_SKILL_DIR and RUNTIME_PYTHON must be absolute local runtime paths');
}
const revision = process.env.PITCH_REVISION ?? 'r1';
const build = path.join(workspace, 'build');
const output = path.join(workspace, 'output');
const renderDir = path.join(build, `render-${revision}`);
const finalPath = path.join(output, `cizheng-pitch-v09-${revision}.pptx`);
await Promise.all([build, output, renderDir].map(p => fs.mkdir(p, { recursive: true })));

const family = 'Hiragino Sans GB';
const serif = 'Songti SC';
const C = {
  navy: '#132D49', blue: '#245B88', ink: '#1C334B', muted: '#5E7181',
  paper: '#FAFCFD', white: '#FFFFFF', pale: '#EEF4F8', line: '#C7D5E0',
  gold: '#AE8B4A', goldPale: '#F6F1E7', paleText: '#C7D6E2'
};
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
p.theme.colorScheme = {
  name: '瓷证',
  themeColors: {
    accent1: C.blue, accent2: C.navy, accent3: C.gold, accent4: C.muted,
    accent5: C.line, accent6: C.paleText, bg1: C.white, bg2: C.paper,
    tx1: C.ink, tx2: C.muted, dk1: '#000000', dk2: C.navy,
    lt1: C.white, lt2: C.pale, hlink: C.paleText, folHlink: C.paleText
  }
};
const editorial = [];
const sourceBase = 'https://github.com/dingyucanada/cizheng-agent-skills/blob/main/';
const siteBase = 'https://dingyucanada.github.io/cizheng-agent-skills/';

function text(s, value, x, y, w, h, size = 29, color = C.ink, bold = false, typeface = family, extra = {}) {
  const sh = s.shapes.add({ geometry: 'textbox', name: String(value).slice(0, 44),
    position: { left: x, top: y, width: w, height: h }, fill: 'none', line: { fill: 'none', width: 0 } });
  sh.text = value;
  sh.text.style = { typeface, fontSize: size, color, bold, alignment: 'left', verticalAlignment: 'top',
    autoFit: 'none', insets: { top: 0, left: 0, right: 0, bottom: 0 }, ...extra };
  return sh;
}
function rule(s, x, y, w, color = C.line, weight = 1) {
  return s.shapes.add({ geometry: 'line', position: { left: x, top: y, width: w, height: 0 },
    fill: 'none', line: { fill: color, width: weight } });
}
function slide(title = '', dark = false) {
  const s = p.slides.add();
  s.background.fill = dark ? C.navy : C.paper;
  if (title) text(s, title, 64, 48, 1152, 74, 44, dark ? C.white : C.navy, true);
  return s;
}
function page(s, n, dark = false) {
  text(s, String(n).padStart(2, '0'), 1168, 674, 48, 28, 20, dark ? C.paleText : C.muted, false, family, { alignment: 'right' });
}
function note(s, n, title, speaking, sources) {
  const entry = { slide: n, title, speaking, sources };
  editorial.push(entry);
  s.speakerNotes.textFrame.setText(`${speaking}\n\n来源和范围\n${sources.join('\n')}`);
}
async function image(s, relative, x, y, w, h, fit = 'contain', alt = '', crop) {
  const bytes = await fs.readFile(path.join(source, relative));
  return s.images.add({ blob: new Uint8Array(bytes), contentType: relative.endsWith('.png') ? 'image/png' : 'image/jpeg',
    alt, fit, position: { left: x, top: y, width: w, height: h }, ...(crop ? { crop } : {}) });
}
function node(s, title, body, x, y, w, h, { fill = C.white, color = C.navy, border = C.blue, size = 24, titleSize = 26 } = {}) {
  const sh = s.shapes.add({ geometry: 'rect', name: title, position: { left: x, top: y, width: w, height: h },
    fill, line: { fill: border, width: 1.4 } });
  sh.text = [
    { runs: [{ run: title, textStyle: { bold: true, fontSize: `${titleSize}px`, color } }], spaceAfter: 550 },
    ...body.split('\n').map(line => ({ runs: [{ run: line }] }))
  ];
  sh.text.style = { typeface: family, fontSize: size, color, autoFit: 'none', verticalAlignment: 'middle',
    insets: { top: 12, bottom: 12, left: 14, right: 14 }, alignment: 'left' };
  return sh;
}
function connect(s, a, b, from = 'right', to = 'left', dashed = false, both = false) {
  const line = s.shapes.connect(a, b, { kind: 'elbow', fromSide: from, toSide: to,
    line: { fill: C.blue, width: 2, style: dashed ? 'dashed' : 'solid' },
    tail: { type: 'triangle', width: 'sm', length: 'sm' },
    ...(both ? { head: { type: 'triangle', width: 'sm', length: 'sm' } } : {}) });
  // Keep native connectors above the architecture's boundary fill.
  line.bringToFront();
  return line;
}
function table(s, values, x, y, w, h, widths, rowHeights, fontSize = 25) {
  const t = s.tables.add({ rows: values.length, columns: values[0].length, left: x, top: y, width: w, height: h,
    columnWidths: widths, values });
  t.styleOptions = { headerRow: true, bandedRows: false };
  t.borders.assign({ style: 'solid', fill: C.line, width: 0.7 });
  for (let r = 0; r < values.length; r++) {
    t.rows[r].height = rowHeights[r];
    for (let c = 0; c < values[0].length; c++) {
      const cell = t.getCell(r, c);
      cell.fill = r === 0 ? C.navy : C.white;
      cell.text.style = { typeface: family, fontSize, color: r === 0 ? C.white : C.ink, bold: r === 0,
        autoFit: 'none', verticalAlignment: 'middle', insets: { top: 9, bottom: 9, left: 14, right: 14 } };
    }
  }
  return t;
}

// 1. Minimal cover with one licensed, real object photograph.
{
  const s = slide('', true);
  await image(s, 'site/assets/met-48607.jpg', 768, 0, 512, 720, 'cover', 'Met馆藏18.61.4，山水纹花觚公开图');
  text(s, '瓷证', 70, 148, 632, 123, 96, C.white, true, serif);
  text(s, '陶瓷证据研究 Agent', 74, 310, 634, 63, 42, C.white);
  text(s, '原件、观察和资料依据\n保存在一份可继续复核的案卷中', 74, 410, 622, 108, 29, C.paleText);
  text(s, '个人参赛作品  ·  2026.09', 74, 638, 620, 35, 23, C.paleText);
  note(s, 1, '瓷证', '瓷证面向陶瓷研究材料的整理、补证和交接。AI负责观察和证据整理，专业人员负责复核。器物为公开已知身份教学材料，不代表项目完成了独立鉴定。', [
    '图像：The Metropolitan Museum of Art，18.61.4，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/48607',
    `${sourceBase}examples/public-demo/sources.json`, `${sourceBase}docs/product-and-architecture.md`
  ]);
}

// 2. Pain points use a flat editorial layout and a distinct licensed photograph.
{
  const s = slide('专业复核先要找回证据');
  await image(s, 'site/assets/met-51185.jpg', 770, 180, 432, 394, 'contain', 'Met馆藏79.2.1202a,b，青花镂空茶壶公开图');
  const rows = [
    ['材料分散', '照片、来源记录和描述难以逐条对应'],
    ['理由难回查', '一句归属意见需要具体观察和资料段落'],
    ['补证缺少顺序', '下一张照片应回应当前证据缺口']
  ];
  rows.forEach(([h, b], i) => {
    const y = 185 + i * 139;
    text(s, h, 66, y, 650, 45, 33, C.navy, true);
    text(s, b, 66, y + 58, 660, 58, 28, C.muted);
    if (i < 2) rule(s, 66, y + 120, 640);
  });
  text(s, '交付目标：一条可回到原图、原文件和出处的研究路径', 66, 623, 1110, 41, 27, C.blue, true);
  page(s, 2);
  note(s, 2, '专业复核先要找回证据', '这里描述的是产品解决的工作问题，不是市场规模调查。收藏档案、博物馆编目和图录准备都需要把描述和依据对应。系统组织研究路径，不能凭照片替代实物检测。', [
    `${sourceBase}docs/product-and-architecture.md`, `${sourceBase}docs/professional-research.md`,
    '图像：The Metropolitan Museum of Art，79.2.1202a,b，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/51185'
  ]);
}

// 3. A real workbench screenshot. The source screenshot is not recreated.
{
  const s = slide('一份案卷承接整段研究工作');
  text(s, '原图定位、资料阅读和待补证，直接对应到同一件器物', 66, 132, 1140, 46, 29, C.muted);
  await image(s, 'site/assets/workbench-v06.jpg', 66, 198, 904, 442, 'contain', '瓷证真实本地工作台，图像区域和证据检查器',
    { left: 0.166, top: 0.083, right: 0, bottom: 0 });
  text(s, '原件', 1010, 221, 200, 40, 30, C.navy, true);
  text(s, 'SHA 和来源\n保留原始字节', 1010, 274, 198, 84, 25, C.muted);
  text(s, '观察', 1010, 390, 200, 40, 30, C.navy, true);
  text(s, '区域有位置\n理由可回查', 1010, 443, 200, 84, 25, C.muted);
  text(s, '版本', 1010, 559, 200, 40, 30, C.navy, true);
  text(s, '补证后保留历史', 1010, 610, 210, 41, 25, C.muted);
  page(s, 3);
  note(s, 3, '一份案卷承接整段研究工作', '截图来自真实本地专业工作台的公开教学案。选区、图像操作、来源记录和离线交接可以在不调用模型时使用。截图中的馆方资料和人工教学观察不等同实际模型报告。原件、人工记录、固定资料版本、Agent运行和复核各有版本，材料更新后旧复核显示过期。', [
    `${sourceBase}site/assets/workbench-v06.jpg`, `${sourceBase}docs/user-guide.md`, `${sourceBase}docs/product-and-architecture.md`
  ]);
}

// 4. Editable business workflow anchored to the saved public double-image case.
{
  const s = slide('真实案卷的审查和修订闭环');
  text(s, '公开双图案卷已经保存初稿、文字审查、本地回查和导出', 66, 132, 1135, 43, 29, C.muted);
  const xs = [66, 298, 530, 762, 994];
  const stages = [
    ['原件和资料', '双图进入本地\n固定正文和回执'],
    ['本地研究', '可定位观察\n分项理由和缺口'],
    ['文字审查', 'StepFun\n只接批准文字'],
    ['复看和修订', '回查原图\n逐项回应问题'],
    ['交接案卷', '报告和原件\n保留两版历史']
  ];
  const ns = stages.map(([h,b], i) => node(s, h, b, xs[i], 236, 212, 153));
  ns.slice(0,-1).forEach((n,i) => connect(s,n,ns[i+1]));
  text(s, '审查提出的问题', 66, 459, 540, 44, 31, C.navy, true);
  text(s, '“风格主张无具体特征比对依据”', 66, 519, 552, 84, 27, C.muted);
  text(s, '修订保留的状态', 686, 459, 530, 44, 31, C.navy, true);
  text(s, '制作时期、窑口和风格仍为证据不足\n待补证问题和原初稿继续可回查', 686, 519, 531, 92, 27, C.muted);
  text(s, '本例仍有资料对应和论据支持问题，独立专家评价列入下一阶段', 66, 643, 1118, 30, 22, C.muted);
  page(s, 4);
  note(s, 4, '真实案卷的审查和修订闭环', '这页以真实保存记录说明业务链路。主视觉模型处理公开Met48607两图，StepFun step-3.7-flash只接批准的四字段文字包，没有原图或图像访问地址。两版NAT引用核查及JSON、Markdown、HTML导出有实际记录。专业问题仍待解决：初稿把同器Met18.61.4资料写为不适用本件，修订删除该句，时期和风格支持理由仍需专业复核，三项审查问题均保留未解决。流程完成不能作为鉴定准确率或Skills因果效果。', [
    `${sourceBase}verification/nvidia/v07-workflows/round-12/workflow-summary.json`,
    `${sourceBase}verification/nvidia/v07-workflows/round-12/quality-limitations-audit.json`,
    `${sourceBase}verification/nvidia/v07-workflows/round-12/text-review/executed.json`,
    `${siteBase}assets/cizheng-ai-replay-v07.mp4`
  ]);
}

// 5. Seven actual method packages and an editable progressive-loading diagram.
{
  const s = slide('Agent Skills 把方法写成执行步骤');
  text(s, '7 个自研领域方法包', 66, 156, 535, 45, 32, C.navy, true);
  const methods = [
    ['任务和补拍路由', '确认任务和缺失部位'],
    ['陶瓷编目研究', '分开观察、记载和主张'],
    ['青花比较研究', '记录反例和竞争解释'],
    ['状况竞争解释', '提出可检查的假说'],
    ['来源经历核查', '核对事件和本件凭据'],
    ['文字凭据核查', '分列相符、冲突和缺失'],
    ['补证和版本修订', '解释新证据改变了什么']
  ];
  methods.forEach(([h,b],i) => {
    const y=224+i*55;
    text(s,h,66,y,270,40,26,C.navy,true);
    text(s,b,350,y,256,40,25,C.muted);
  });
  const a=node(s,'发现描述','先选适用方法',660,181,170,111,{fill:C.pale,size:23,titleSize:26});
  const b=node(s,'读取正文','执行研究步骤',848,181,170,111,{fill:C.pale,size:23,titleSize:26});
  const c=node(s,'按需资源','参考和检查',1036,181,170,111,{fill:C.pale,size:23,titleSize:26});
  connect(s,a,b);connect(s,b,c);
  const blocks=[
    ['版本可回放','整包 SHA 固定实际采用的方法和资源'],
    ['权限由宿主执行','注册工具、真实读回执和累计预算共同约束'],
    ['意见对应证据','本轮观察编号和实际阅读段落绑定']
  ];
  blocks.forEach(([h,b],i)=>{const y=343+i*99;text(s,h,660,y,548,40,29,C.navy,true);text(s,b,660,y+46,548,44,25,C.muted);});
  text(s, '领域包由项目开发，专业方法效果将在同模型、同预算评测中验证', 66, 646, 1120, 31, 22, C.muted);
  page(s,5);
  note(s,5,'Agent Skills 把方法写成执行步骤','七包均为真实自研文件包，按description、SKILL正文和资源渐进加载，每包有适用范围和限制。整包SHA不是专家认可或NVIDIA Verified认证。宿主限制工具权限、实际读取和进入成功主动作的材料、累计模型和工具预算。真实运行还有可选协调器材料准备，协调器加载和模型自然触发分别记录；本页不把协调器行为当作Skills自然触发或专业提升。',[
    ...['ceramic-route','ceramic-research-record','bluewhite-attribution-test','condition-hypothesis-test','provenance-evidence-audit','documentary-evidence-audit','evidence-revise'].map(k=>`${sourceBase}skills/${k}/SKILL.md`),
    `${sourceBase}cizheng/skill_runtime.py`,`${sourceBase}docs/controlled-workflow.md`, 'NVIDIA Agent Skills平台参考：https://docs.nvidia.com/skills'
  ]);
}

// 6. Explicitly requested editable architecture. No flattened diagram artwork.
{
  const s=slide('本地证据和受控模型协作');
  text(s,'原图和案卷留在 Spark，外部审查只使用批准文字',66,130,1150,44,29,C.muted);
  s.shapes.add({geometry:'rect',name:'本地工作台和DGX Spark边界',position:{left:286,top:193,width:930,height:405},fill:C.pale,line:{fill:C.line,width:1.2}});
  text(s,'本地专业工作台和 DGX Spark',312,209,856,38,27,C.navy,true);
  const inp=node(s,'采集和资料','原图和许可文字\n网页和本机桥接',64,272,190,125,{size:23,titleSize:25});
  const store=node(s,'版本化案卷','原件 SHA 和来源\n固定资料版本',312,272,256,125);
  const host=node(s,'研究 Agent 宿主','注册工具和预算\n本轮输入资格',628,272,256,125);
  const report=node(s,'复核和证据报告','支持、矛盾和缺口\n修订 / 离线交接',944,272,244,125);
  const knowledge=node(s,'固定知识和引用','实际正文读回执\nNAT 核对版本和段落',312,457,256,121,{size:23,titleSize:25});
  const local=node(s,'方法和视觉核查','7 Skills / 8B 主流程\n35B / 27B 候选',628,457,256,121,{size:23,titleSize:25});
  node(s,'独立已部署服务','NIM 和 TRT-LLM\nEmbedding + cuVS',944,457,244,121,{size:22,titleSize:24,fill:C.goldPale,border:C.gold});
  const critic=node(s,'可选文字审查','StepFun\nstep-3.7-flash',64,457,190,121,{size:23,titleSize:25});
  connect(s,inp,store);connect(s,store,host);connect(s,host,report);
  connect(s,knowledge,store,'top','bottom');connect(s,local,host,'top','bottom');
  connect(s,store,critic,'left','right',true,true);
  text(s,'批准文字和审查结果',64,616,400,37,23,C.blue);
  text(s,'主服务保持 8B，较大模型经受控核查后再考虑切换',511,616,704,41,23,C.muted);
  page(s,6);
  note(s,6,'本地证据和受控模型协作','架构是原生可编辑对象和连接线。本地案卷使用SQLite保存原件、版本和回执，主视觉为Spark Qwen3-VL-8B。35B和27B通过独立双图案卷验证而非默认切换，较大模型不自动证明更高准确率。27B公开原始权重和进程的绑定仍待核验。NAT经正式插件核查引用身份，不证明引用对专业结论的支持。StepFun只接明确批准的公开或脱敏文字。本轮NIM纯文本Qwen3-4B BF16为实际独立服务；TRT文字和官方Embedding+cuVS亦独立验收，主业务未自动切换。采集桥接是文件协议，不代表眼镜、手持仪器或桌面箱已完成厂商SDK和物理验收。',[
    `${sourceBase}docs/product-and-architecture.md`,`${sourceBase}docs/nvidia-integration.md`,`${sourceBase}docs/spark-models-and-reasoning-v10.md`,`${sourceBase}docs/device-capture.md`
  ]);
}

// 7. Actual deployment roles, including the completed independent visual candidates.
{
  const s=slide('Spark 本地部署和模型分工');
  text(s,'原件和资料版本固定，模型变更通过受控核查保留记录',66,132,1140,44,29,C.muted);
  table(s,[
    ['工作','实际实现','接入位置'],
    ['案卷主视觉','Qwen3-VL-8B\nPyTorch / BF16 / CUDA','多图和区域研究主流程'],
    ['较大视觉模型','35B / 27B 视觉候选\nNIM（SGLang 后端）','已完成独立案卷核查\n主服务保持 8B'],
    ['领域方法和引用','7 个 Agent Skills\nNeMo Agent Toolkit','方法执行和引用身份核查'],
    ['本地文字推理','NIM / Qwen3-4B\nTensorRT-LLM / Qwen3-4B','已部署独立文字端点'],
    ['语义资料检索','官方 Embedding 1B v2\ncuVS CUDA 索引','独立检索已实测\n主案卷仍使用 SQLite']
  ],66,189,1148,441,[240,469,439],[51,78,78,78,78,78],24);
  text(s,'候选均未设为默认，27B 原始权重和进程的关联待补验',66,650,1090,31,24,C.blue);
  page(s,7);
  note(s,7,'Spark 本地部署和模型分工','8B主视觉继续承担案卷业务。Qwen3.6-35B-A3B-NVFP4经原厂NIM的SGLang后端完成独立双图案卷流程，GPU有限采样可回查，运行后停止。35B使用Marlin NVFP4 W4A16路径，不声称完整NVFP4硬件加速。Qwen3.8-27B完成另一条独立双图案卷流程，公开工作流的原始weights_revision仍为unverified，不能证明固定原始权重和实际进程绑定。较大模型均未默认替换8B，也没有证明更高专业准确率。4B NIM和TensorRT-LLM为独立文字端点，TRT使用PyTorch backend，没有序列化engine。Embedding为开放官方1B v2加cuVS，不是Embedding NIM或完整Retriever SDK。主业务资料仍使用SQLite。这里记录部署和业务位置，不将单次延迟当作整案加速。',[
    `${sourceBase}docs/spark-models-and-reasoning-v10.md`,`${sourceBase}docs/nim-v09-update.md`,
    `${sourceBase}verification/nvidia/tensorrt-llm-v08/README.md`,`${sourceBase}integrations/nvidia_retriever/README-open-service.md`,`${sourceBase}docs/spark-validation.md`
  ]);
}

// 8. A real risk workbench crop and the complete editable six-dimension weights.
{
  const s=slide('六维矛盾筛查：先安排复核工作');
  text(s,'本地规则比较已保存记载，每个提示都给出下一项补证',66,131,1140,46,29,C.muted);
  await image(s,'site/assets/risk-workbench-v09.png',66,198,748,310,'contain','真实六维筛查界面，协议演示数字',
    {left:0.1667,top:0.119,right:0.1944,bottom:0.575});
  const weights=[20,15,15,20,15,15];
  if(weights.reduce((a,b)=>a+b,0)!==100) throw new Error('Six dimension weights must sum to 100');
  const t=table(s,[['维度','权重'],['制作时期','20'],['窑口归属','15'],['装饰风格','15'],['来源对应','20'],['状况和修复','15'],['采集完整性','15'],['合计','100']],858,198,348,372,[238,110],[44,46,46,46,46,46,46,52],24);
  t.getCell(7,0).text.style={typeface:family,fontSize:24,color:C.navy,bold:true};t.getCell(7,1).text.style={typeface:family,fontSize:24,color:C.navy,bold:true};
  text(s,'矛盾＝冲突权重',66,532,748,39,28,C.navy,true);
  text(s,'复核优先＝冲突权重 + 0.5 × 未知权重',66,577,748,39,28,C.ink);
  text(s,'覆盖＝已评价权重 / 100\n未知状态单列',858,592,348,70,23,C.muted);
  text(s,'指数用于工作排序，非真品率或置信度。图中高度矛盾来自明确标记的合成协议练习',66,644,1140,31,21,C.muted);
  page(s,8);
  note(s,8,'六维矛盾筛查：先安排复核工作','筛查是已实现的独立CPU规则功能，不调用视觉模型或StepFun。结构化记载绑定本件凭据SHA和定位，自动比较年份/高度区间、同编号体系的本件编号、来源事件先后。每维只计一次，固定总权重100。矛盾指数为冲突权重，所有未知时不可评价；复核优先为冲突权重加0.5倍未知权重；覆盖为已评价权重除100。截图只用于演示软件协议，两份300–301和350–351毫米高度是合成数字，不是馆藏实测或照片测量。权重和模型依据尚未完成专家标签校准。',[
    `${sourceBase}docs/risk-triage.md`,`${sourceBase}cizheng/risk_triage.py`,`${sourceBase}site/assets/risk-workbench-v09.png`,`${siteBase}triage.html`
  ]);
}

// 9. Real same-object second image, editable collection loop and explicit maturity.
{
  const s=slide('证据缺口决定下一项拍摄');
  await image(s,'site/assets/met-48607-view2.jpg',66,163,346,430,'contain','Met馆藏18.61.4，另一面整体公开图');
  text(s,'两张整体图还留下什么？',473,171,738,46,33,C.navy,true);
  text(s,'底足、款识和修复细节需要对应照片或实物检查',473,229,738,77,28,C.muted);
  const a=node(s,'本轮证据缺口','缺失部位和原因',473,351,221,117,{fill:C.pale,size:24,titleSize:25});
  const b=node(s,'下一项补拍','视角、条件和尺度',728,351,221,117,{fill:C.pale,size:24,titleSize:25});
  const c=node(s,'新原件和版本','回查发生的变化',983,351,221,117,{fill:C.pale,size:24,titleSize:25});
  connect(s,a,b);connect(s,b,c);
  text(s,'已实现',473,520,162,42,28,C.blue,true);
  text(s,'采集桥接、原件 SHA、设备声明和归档回执\n公开图的真实 HTTP 往返核验保持原字节一致',644,520,560,83,25,C.muted);
  text(s,'受控光线、多视角、色卡和比例尺进入后续采集研究。眼镜 SDK、桌面箱和标定仍待开发',66,636,1140,41,22,C.muted);
  page(s,9);
  note(s,9,'证据缺口决定下一项拍摄','整体照片能支持部分可见形态，但不能补造底足、款识或修复细节。本页的拍摄循环是产品逻辑，也是可编辑流程。现已实现统一本机multipart会话协议、客户端、SHA校验、原始blob、设备声明、时间/单位和归档回执，并通过真实本机HTTP上传下载保持公共图片原字节SHA。设备身份、相机时钟和传感器尚未厂商认证或实物标定。智能眼镜、专业手持和桌面箱先导出文件到本机桥接；厂商SDK、直接拍摄控制和箱式硬件为未来研究，当前不具备材料检测或物理鉴定能力。',[
    `${sourceBase}docs/device-capture.md`,`${sourceBase}scripts/device-capture-client.py`,`${sourceBase}docs/risk-triage.md`,
    '图像：The Metropolitan Museum of Art，18.61.4，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/48607'
  ]);
}

// 10. Proposed adoption remains a plan, with concrete case-level outputs.
{
  const s=slide('专业试用的交付和采用方式');
  text(s,'从一件器物的材料整理开始，验证交接是否真正可用',66,132,1140,46,29,C.muted);
  table(s,[
    ['工作入口','交付的案卷材料','拟议试用起点'],
    ['博物馆编目','原图、区域观察\n固定文献和修订档案','先整理一件器物材料'],
    ['收藏档案','来源事件和对应凭据\n跨时间状况记录','先核对一条来源链'],
    ['拍卖图录准备','归属措辞、状况记录\n待补证和离线交接包','先复核一份描述']
  ],66,217,1148,349,[249,551,348],[52,99,99,99],27);
  text(s,'商业验证计划',66,607,320,43,29,C.navy,true);
  text(s,'以整理时间、疑点遗漏和复核可用性评价试用，探索本地部署和服务订阅',348,607,866,67,25,C.muted);
  page(s,10);
  note(s,10,'专业试用的交付和采用方式','三种入口已经以公共教学案演示材料工作，不代表真实机构委托或合作。当前为个人作品和单人受控试用。拟议试用从小范围案卷材料整理开始，以材料整理时间、关键疑点遗漏、专家复核可用性评估产品价值。商业模式是后续探索，不虚构客户、收入、团队或已签合作。多用户权限、可信专家签署、合规审计和灾备仍需产品化。',[
    `${sourceBase}README.md`,`${sourceBase}docs/product-and-architecture.md`,`${sourceBase}examples/public-demo/professional-cases.json`
  ]);
}

// 11. An editable research route shows the missing professional validation positively.
{
  const s=slide('专家反馈驱动方法和模型改进');
  text(s,'下一阶段先验证观察、引用和理由，再决定训练和产品化',66,132,1140,47,29,C.muted);
  const a=node(s,'授权专家样本','照片和对象身份固定\n专家标签首轮隔离',66,226,349,147,{size:26,titleSize:29});
  const b=node(s,'独立评测','同模型、资料和预算\n有 / 无 Skills 和盲评',465,226,349,147,{size:26,titleSize:29});
  const c=node(s,'审核和保留集回归','修改方法和模型版本\n记录失败和退步',864,226,349,147,{size:26,titleSize:29});
  connect(s,a,b);connect(s,b,c);
  rule(s,66,431,1147);
  text(s,'研究方向',66,474,273,44,32,C.navy,true);
  text(s,'受控采集和多时相档案\n将专业反馈转成有许可、可审阅的离线材料',348,470,865,97,27,C.muted);
  text(s,'机构协作和后训练',66,591,273,46,29,C.navy,true);
  text(s,'探索 NVFLARE 联合训练和 NeMo RL，验证后再发布版本',348,591,865,62,26,C.muted);
  text(s,'当前尚未完成独立专家样本评价和真品概率校准',66,650,1115,29,22,C.muted);
  page(s,11);
  note(s,11,'专家反馈驱动方法和模型改进','这是下一阶段研究路线，不是已取得的专家成绩。样本应取得授权并按器物分割，专家标签和首轮证据分开，避免同器照片泄漏到训练和测试两侧。专家分别评价图像观察、区域定位、资料引用、理由、补证和拒绝判断。固定模型、资料和预算后比较有/无Skills，保留失败并在独立保留样本上回归。NVFLARE联合训练和NeMo RL后训练是未来研究，没有联合训练网络、自动在线学习或专业准确率。',[
    `${sourceBase}docs/expert-validation-intake.md`,`${sourceBase}docs/training-implementation.md`,`${sourceBase}evals/PROTOCOL.md`
  ]);
}

// 12. Three source-backed public collection checks with real, licensed photographs.
{
  const s=slide('公开馆藏个案：逐条核对观察和理由');
  text(s,'先看照片，再加入同件馆藏记载，检查理由如何变化',66,130,1145,45,29,C.muted);
  const cases=[
    ['pc01','“射手”纹青花储水器','2021.321a, b','装饰风格和制作地\n需要分别判断','854455'],
    ['pc02','仿古铜器形彩瓷瓶','14.40.396','缺少外底或足内图\n不能推断实物无款','42239'],
    ['pc03','龙泉青釉碗','17.57.1','修补外观和工艺名称\n需要分层核查','48450']
  ];
  for(let i=0;i<cases.length;i++){
    const [id,title,accession,lesson,objectId]=cases[i];const x=66+i*389;
    await image(s,`site/assets/public-collection-check/${id}-view-01.jpg`,x,186,354,272,'contain',`Met ${accession} 公开原图`);
    text(s,title,x,479,358,42,27,C.navy,true);
    text(s,`Met ${accession}`,x,526,355,32,21,C.muted);
    text(s,lesson,x,576,355,78,25,C.blue,true);
  }
  text(s,'照片和馆方记载均可回查。公开资料个案核查已完成，真人专家验证列入后续工作',66,663,1138,29,21,C.muted);
  page(s,12);
  note(s,12,'公开馆藏个案：逐条核对观察和理由','三件器物各两张Met CC0照片，保存了九次真实Spark流程。阶段A不向模型提供本件馆方年代和窑口，普通提示和Skills使用同模型、同预算；全部A结束后，阶段B再加入同件固定馆藏文字。四轮保存意见并等待补证，五轮停止，全部原件和模型原文保留，不能把停止写成成功报告。储水器由荷兰设计师Pronk设计不等同荷兰制作，彩瓷瓶没有外底或足内视角不能推出实物无款，青釉碗黄色修补外观不能单凭照片确定金缮工艺。碗的阶段B有一条来源语境引用，但底款建议和理由仍需专业评价。另有一次实际StepFun公开文字审查，属于AI反证而非专家意见。此页是公开馆藏资料的个案核查，不是独立专家鉴定或行业准确率。',[
    `${siteBase}public-collection-check.html`,`${sourceBase}docs/public-collection-case-check-20260929.md`,`${sourceBase}verification/public-collection-20260929/index.json`,
    ...cases.map(([,title,accession,,id])=>`图像：The Metropolitan Museum of Art，${title}，${accession}，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/${id}`)
  ]);
}

// 13. A concise close with a distinct licensed photograph and stable entry links.
{
  const s=slide('',true);
  await image(s,'site/assets/met-50839.jpg',0,0,575,720,'cover','Met馆藏61.200.30，五彩耕织图瓶公开图');
  text(s,'瓷证',647,136,554,105,76,C.white,true,serif);
  text(s,'可以继续复核的陶瓷案卷',649,279,562,68,37,C.white,true);
  text(s,'原图出处可追溯\n判断理由可核查\n下一项补证有明确方向',649,384,557,148,29,C.paleText);
  const links=[['完整图文报告书',`${siteBase}report.html`],['公开馆藏个案核查',`${siteBase}public-collection-check.html`],['公开源码和部署证据','https://github.com/dingyucanada/cizheng-agent-skills']];
  links.forEach(([label,uri],i)=>{const sh=text(s,label,649,576+i*37,555,34,23,C.paleText);sh.text.get(label).link={uri,isExternal:true};});
  note(s,13,'瓷证','个人参赛作品。完整报告呈现产品、实际模型记录和部署证据。公开教学体验无需上传，不调用私有模型。公开仓库保留自研方法包、代码和脱敏部署记录。来源机构和NVIDIA不代表对本项目的背书或专业鉴定认证。',[
    `${siteBase}report.html`,`${siteBase}demo.html`,'https://github.com/dingyucanada/cizheng-agent-skills',
    '图像：The Metropolitan Museum of Art，61.200.30，Public Domain / CC0。https://www.metmuseum.org/art/collection/search/50839'
  ]);
}

if(p.slides.items.length !== 13) throw new Error('The pitch must have 13 total slides');
await fs.writeFile(path.join(build,`notes-${revision}.json`),JSON.stringify(editorial,null,2)+'\n');
await fs.writeFile(path.join(build,`presentation-${revision}.json`),JSON.stringify(p.toProto()));
const candidate=path.join(build,`candidate-${revision}.pptx`);
await (await PresentationFile.exportPptx(p)).save(candidate);
const { finalizePresentation }=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({
  workspaceDir:workspace,candidatePath:candidate,finalPath,pythonExecutable:python,
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',
    '--require-native-table-slide','7','--require-native-table-slide','8','--require-native-table-slide','10'],
  explicitTotalSlideCount:13,requiredNativeTableOwnerSlides:[7,8,10],requiredNativeChartOwnerSlides:[],
  tableArithmeticContracts:[{slide:8,table:1,label_column:0,total_row:7,value_columns:[1],component_rows:[1,2,3,4,5,6]}],
  fontPolicy:{basis:'design',families:[family,serif]},verifyArtifactToolImport:true,
  receiptPath:path.join(build,`validation-${revision}.json`)
});
const final=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<final.slides.items.length;i++){
  const s=final.slides.items[i];
  const blob=await final.export({slide:s,format:'png',scale:1.5});
  await fs.writeFile(path.join(renderDir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
  const layout=await s.export({format:'layout'});
  await fs.writeFile(path.join(renderDir,`slide-${String(i+1).padStart(2,'0')}.layout.json`),await layout.text());
}
const montage=await final.export({format:'webp',montage:{columns:3,slideWidth:640,padding:20,gap:20,background:'#DDE6ED'},scale:1});
await fs.writeFile(path.join(build,`montage-${revision}.webp`),new Uint8Array(await montage.arrayBuffer()));
const snapshot=await final.inspect({kind:'slide,textbox,shape,image,table,chart,notes',maxChars:1000000});
await fs.writeFile(path.join(build,`snapshot-${revision}.ndjson`),snapshot.ndjson);
console.log(JSON.stringify({finalPath,renderDir,slideCount:final.slides.items.length,result}));
