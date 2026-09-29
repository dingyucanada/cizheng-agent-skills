import fs from 'node:fs/promises';
import path from 'node:path';
import {createCanvas,loadImage} from '@napi-rs/canvas';
const base=path.dirname(new URL(import.meta.url).pathname),version=process.argv[2]||'v1';
const planFile=await fs.access(path.join(base,`scene-plan-${version}.json`)).then(()=>`scene-plan-${version}.json`).catch(()=>'scene-plan.json');
const plan=JSON.parse(await fs.readFile(path.join(base,planFile),'utf8'));
const out=path.join(base,version,'scenes');await fs.mkdir(out,{recursive:true});
const images={};for(const n of ['met-48607.jpg','met-48607-view2.jpg','met-51185.jpg','met-50839.jpg','demo-observation-desktop.png','demo-evidence-desktop.png','demo-skills-desktop.png','demo-revision-desktop.png','demo-export-desktop.png','desktop-risk.png'])images[n]=await loadImage(await fs.readFile(path.join(base,'materials',n)));
const C={navy:'#102A3D',blue:'#22577C',paper:'#F5F3EA',white:'#FFFFFF',gold:'#C7A977',gray:'#B8C7CF',ink:'#173147'};
let ctx;
function rect(x,y,w,h,color){ctx.fillStyle=color;ctx.fillRect(x,y,w,h);}
function line(x,y,x2,y2,color=C.gold,width=2){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x2,y2);ctx.stroke();}
function text(s,x,y,size=38,color=C.white,weight='400',serif=false){ctx.fillStyle=color;ctx.font=`${weight} ${size}px "${serif?'Songti SC':'Hiragino Sans GB'}"`;ctx.fillText(s,x,y);}
function lines(arr,x,y,size=76,color=C.white,step=108,serif=false){arr.forEach((s,i)=>text(s,x,y+i*step,size,color,'600',serif));}
function wrap(s,max=21){const a=[...s],rows=[];while(a.length){let n=Math.min(max,a.length);if(a.length>n&&'，。；：、？！）'.includes(a[n]))n++;rows.push(a.splice(0,n).join(''));}return rows;}
function picture(n,x,y,w,h,mode='contain',crop=null){const im=images[n];let sx=0,sy=0,sw=im.width,sh=im.height;if(crop){[sx,sy,sw,sh]=crop.map((v,i)=>v*(i%2?im.height:im.width));}if(mode==='cover'){const r=Math.max(w/sw,h/sh);const pw=w/r,ph=h/r;sx+=(sw-pw)/2;sy+=(sh-ph)/2;sw=pw;sh=ph;}else{const r=Math.min(w/sw,h/sh);const dw=sw*r,dh=sh*r;x+=(w-dw)/2;y+=(h-dh)/2;w=dw;h=dh;}ctx.save();ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();ctx.drawImage(im,sx,sy,sw,sh,x,y,w,h);ctx.restore();}
function footer(s,dark=true){rect(0,936,1920,144,C.navy);line(94,918,1826,918,dark?'#405A6B':'#CBD2D6',1);text(s,96,900,23,dark?C.gray:'#617381');}
function arrow(x,y,w,color=C.gold){line(x,y,x+w,y,color,3);line(x+w-14,y-9,x+w,y,color,3);line(x+w-14,y+9,x+w,y,color,3);}
const boundaries=[];
for(let i=0;i<plan.scenes.length;i++){
 const s=structuredClone(plan.scenes[i]);
 if(version!=='v1'){const titles={workbench:['原图在左。','研究意见在旁。'],read:['找到资料，','读到原段落。'],export:['导出案卷，','继续核查。']};if(titles[s.id])s.title=titles[s.id];}
 const c=createCanvas(1920,1080);ctx=c.getContext('2d');
 const paper=['gallery','source','review','ending'].includes(s.kind);rect(0,0,1920,1080,paper?C.paper:C.navy);const fg=paper?C.ink:C.white,muted=paper?'#617381':C.gray;
 text('瓷证',96,77,32,fg,'600',true);text('原图 · 原文 · 原版本',194,75,23,muted);text(s.eyebrow,96,153,27,C.gold,'500');
 if(version!=='v1')text('从材料出发，向证据回去。',1435,75,25,muted);
 let boundary='公开馆藏图作场景示意 · 剪辑讲解，非连续推理录像 · 合成旁白';
 if(s.kind==='hero'){
  picture(s.photo,1050,123,770,780,'contain');line(976,148,976,838,'#456376',1);lines(s.title,96,386,91,fg,136,true);lines(wrap(s.detail,22),102,728,32,muted,54);
  if(i===17){text('dingyucanada.github.io/cizheng-agent-skills/',102,832,25,C.gold);boundary='公开馆藏 / 教学界面 / 真实记录重建 · 非连续录屏 · 本机合成语音，非真人讲解';}
 }else if(s.kind==='gallery'){
  lines(s.title,96,255,65,fg,86,true);const names=['met-48607.jpg','met-51185.jpg','met-50839.jpg'];const labels=['编目与归属研究','状况与修复观察','来源文件核查'];
  for(let j=0;j<3;j++){const x=96+j*585;rect(x,398,540,388,'#E9E7DF');picture(names[j],x+15,410,510,370);text(labels[j],x,848,31,fg,'500');}
 }else if(s.kind==='screen'){
  let titleSize=version!=='v1'?57:54;
  if(version!=='v1'){ctx.font=`600 ${titleSize}px \"Songti SC\"`;const widest=Math.max(...s.title.map(t=>ctx.measureText(t).width));if(widest>428)titleSize=Math.floor(titleSize*428/widest);}
  lines(s.title,96,326,titleSize,fg,88,true);lines(wrap(s.detail,13),100,642,28,muted,49);
  rect(563,217,1260,636,'#D8D7CF');const crop=(version!=='v1'?({read:[.38,.52,.595,.465],skills:[.66,.54,.31,.458],revision:[.17,.27,.805,.55],export:[.625,.205,.343,.585]}[s.id]):null)||[0.16,0.10,0.82,0.79];
  picture(s.screen,571,224,1244,622,'contain',crop);
  text('实际教学界面',583,199,24,C.gold);boundary='实际 Chrome 教学截图 · 固定教学材料，未在这些画面调用模型 · 合成旁白';
  if(version!=='v1'&&s.id==='export'){text('原图  +  原文  +  方法  +  报告  +  清单',96,819,25,C.gold);}
 }else if(s.kind==='duo'){
  lines(s.title,96,288,72,fg,100,true);lines(wrap(s.detail,15),98,656,29,muted,50);rect(708,202,529,650,'#ECEAE1');rect(1273,202,529,650,'#ECEAE1');picture('met-48607.jpg',715,215,515,626);picture('met-48607-view2.jpg',1280,215,515,626);text('正面原图',720,875,23,muted);text('另一面原图',1280,875,23,muted);
  if(s.id==='supplement')boundary='补证对象与建议展示；未展示已完成仪器检测 · 公开馆藏 CC0 · 合成旁白';
 }else if(s.kind==='source'){
  lines(s.title,96,296,82,fg,112,true);lines(wrap(s.detail,24),99,753,29,muted,53);
  rect(1080,245,702,463,'#FFFFFF');text('固定来源 · 原创馆藏摘要',1117,299,28,C.blue,'500');line(1117,331,1740,331,'#CED6DC',1);lines(['Met 馆藏编号 18.61.4','康熙早期 / 景德镇 / 釉下钴蓝'],1117,403,35,C.ink,75);text('对象身份先对齐，再讨论适用范围',1117,650,26,C.blue);
  boundary='公开馆藏身份与项目原资料摘要 · 示例画面，不构成未知器物鉴定 · 合成旁白';
 }else if(s.kind==='method'){
  lines(s.title,96,285,73,fg,105,true);const a=[['青花归属','读取特征与参照','指出证据缺口'],['状况假设','观察材料痕迹','区分现象与成因'],['来源审查','定位原文件','约束措辞与责任']];
  a.forEach((row,j)=>{const x=102+j*583;line(x,606,x+480,606,C.gold,2);text(row[0],x,665,41,C.white,'600');text(row[1],x,727,29,C.gray);text(row[2],x,781,29,C.gray);});boundary='自研 Skills 方法展示；未宣称 NVIDIA 认证或专业收益已验证 · 合成旁白';
 }else if(s.kind==='risk'){
  lines(s.title,96,301,65,fg,103,true);lines(wrap(s.detail,13),100,650,28,muted,49);
  text('实际规则筛查界面 · 协议演示数据',574,198,24,C.gold);
  rect(563,216,1260,312,'#D8D7CF');picture(s.screen,572,222,1242,300,'contain',[.1674,.2336,.6215,.18]);
  rect(563,559,609,290,'#D8D7CF');picture(s.screen,570,565,595,278,'contain',[.167,.436,.306,.164]);
  rect(1214,559,609,290,'#D8D7CF');picture(s.screen,1221,565,595,278,'contain',[.484,.824,.306,.17]);
  text('时期 · 窑口 · 风格 · 来源 · 状况 · 采集',578,874,25,C.gray);
  boundary='实际规则截图 · 非真品率 / AI置信度 · 协议演示非实物量测 · 内容与专业判断未验 · 合成旁白';
 }else if(s.kind==='critic'){
  lines(s.title,96,279,78,fg,111,true);const q=[['制作时期','对应引用是否充分？'],['窑口','款识与胎体证据在哪里？'],['风格','具体特征怎样比对？']];
  q.forEach((a,j)=>{const y=580+j*104;line(100,y+34,1798,y+34,'#365366',1);text(a[0],104,y,34,C.gold,'500');text(a[1],440,y,36,C.white);});boundary='根据真实文字审查记录摘要制作 · 只传批准文字，无原图 · 非连续录屏 · 合成旁白';
 }else if(s.kind==='review'){
  lines(s.title,96,293,88,fg,116,true);rect(1105,221,651,527,'#FFFFFF');text('材料复核',1144,288,39,C.ink,'600');line(1144,320,1718,320,'#D2D9DE',1);const a=['这条依据是否支持这个意见？','记录对应哪一版材料？','还有什么，需要进一步核查？'];a.forEach((x,j)=>text(x,1144,400+j*90,31,C.ink));lines(wrap(s.detail,27),98,805,28,muted,48);boundary='复核角色与问题示意；未声称专家或客户实际使用 · 现系统不提供可信专家签署 · 合成旁白';
 }else if(s.kind==='architecture'){
  lines(s.title,96,290,84,fg,111,true);
  const a=[{x:96,t:'原始照片',d:'本地文件与案卷'},{x:686,t:'DGX Spark',d:'本地视觉研究'},{x:1275,t:'外部文字反证',d:'预览并批准后发送'}];
  a.forEach((r,j)=>{line(r.x,570,r.x+489,570,C.gold,2);text(r.t,r.x,638,42,C.white,'600');text(r.d,r.x,707,29,C.gray);if(j<2)arrow(r.x+493,642,72);});text('人工复核，再决定结论与下一步',96,834,37,C.gold);boundary='系统结构概念示意，未展示设备实拍；未公开原图不会进入外部文字审查 · 合成旁白';
 }else if(s.kind==='deployment-nim'){
  lines(s.title,96,279,78,fg,110,true);
  text('原图观察与案卷主线继续运行',100,478,29,C.gold);
  const a=[['标准模型接口','NVIDIA NIM','统一模型调用方式'],['独立文字推理','TensorRT-LLM','文字推理与GPU执行'],['独立资料检索','NVIDIA Embedding + cuVS','查找固定资料候选']];
  a.forEach((r,j)=>{const x=98+j*590;line(x,569,x+487,569,C.gold,2);text(r[0],x,642,43,C.white,'600');text(r[1],x,712,j===2?28:31,C.gray);text(r[2],x,785,29,C.gray);});
  boundary=s.release_stage==='verified'?'三项独立服务已核验，尚未切换整案主流程 · 开放Embedding服务不是Embedding NIM · 合成旁白':'第15场设计草稿 · 标准接口已ready，真实POST与CUDA验收待确认 · 未切换整案主流程';
 }else if(s.kind==='deployment'){
  lines(s.title,96,279,78,fg,110,true);const a=[['视觉与案卷','原本地视觉与 SQLite 主流程继续运行'],['文字服务','TensorRT-LLM 独立文字接口已实测'],['资料检索','官方开放 embedding + cuVS 独立 GPU 服务已实测']];
  a.forEach((r,j)=>{const y=570+j*102;text(r[0],99,y,34,C.gold,'600');text(r[1],416,y,32,C.white);line(98,y+37,1790,y+37,'#365366',1);});boundary='新增独立服务未切换整案主流程；非 Embedding NIM，未宣称整案加速或专业收益 · 合成旁白';
 }else if(s.kind==='record'){
  lines(s.title,96,278,79,fg,112,true);const a=[['初稿','原图观察与固定资料'],['文字反证',['v3','v4'].includes(version)?'时期 · 窑口 · 风格':'制作时期 · 窑口 · 风格疑点'],['修订',['v3','v4'].includes(version)?'观察与理由一并保留':'重读照片，疑点继续保留']];
  a.forEach((r,j)=>{const x=96+j*590;line(x,574,x+481,574,C.gold,2);text(r[0],x,648,43,C.white,'600');lines(wrap(r[1],13),x,726,29,C.gray,49);if(j<2)arrow(x+478,647,89);});boundary=['v3','v4'].includes(version)?'真实保存记录摘要 · 非连续录屏 · 已知公开馆藏案例，专业来源支持仍待复核 · 合成旁白':'根据真实保存记录重建，非连续录屏 · 已知公开馆藏非盲测 · 专业质量与专家验证待验';
 }else if(s.kind==='ending'){
  lines(s.title,96,314,93,fg,136,true);line(97,631,1798,631,'#BDC7CF',1);text('有许可的专家材料',100,708,36,C.ink);text('独立样本与盲测',698,708,36,C.ink);text('同预算方法对照',1277,708,36,C.ink);text('当前不声称专业准确率或 Skills 收益已验证',99,819,28,muted);boundary='后续研究计划；专家材料尚未导入，本片不含独立专家验收 · 合成旁白';
 }
 footer(boundary,!paper);boundaries.push({id:s.id,permanent_notice:boundary});
 await fs.writeFile(path.join(out,`${String(i+1).padStart(2,'0')}-${s.id}.png`),c.toBuffer('image/png'));
}
await fs.writeFile(path.join(base,version,'scene-boundaries.json'),JSON.stringify(boundaries,null,2));console.log(`Rendered${plan.scenes.length} ${version} scenes`);
