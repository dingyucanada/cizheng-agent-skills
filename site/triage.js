'use strict';
(()=>{
 const dimensions=[['period','制作时期',20],['kiln','窑口归属',15],['style','装饰风格',15],['provenance','来源对应',20],['condition','状况与修复',15],['capture','采集完整性',15]];
 const ids=['height-a-min','height-a-max','height-b-min','height-b-max','production-min','production-max','event-year'];
 const byId=id=>document.getElementById(id);
 const number=id=>{const s=byId(id).value.trim();if(!s)return null;const x=Number(s);return Number.isFinite(x)&&x>=Number(byId(id).min)&&x<=Number(byId(id).max)?x:null;};
 const node=(tag,text,cl)=>{const e=document.createElement(tag);if(text)e.textContent=text;if(cl)e.className=cl;return e;};
 function update(){
  const v=ids.map(number),alerts=[],conflicts=new Set(),invalid=[];
  for(let i=0;i<6;i+=2){if(v[i]!==null&&v[i+1]!==null&&v[i]>v[i+1])invalid.push(i<4?'高度区间起值不能大于止值。':'制作区间起年不能晚于止年。');}
  if(v.slice(0,4).every(x=>x!==null)&&v[0]<=v[1]&&v[2]<=v[3]&&Math.max(v[0],v[2])>Math.min(v[1],v[3])){
   conflicts.add('capture');alerts.push(['尺寸记载需要核对',`A：${v[0]}–${v[1]} mm，B：${v[2]}–${v[3]} mm，区间不相交。核对单位、量测位置以及是否同一件器物；不能据此直接判断赝品。`]);
  }
  if(v.slice(4).every(x=>x!==null)&&v[4]<=v[5]&&v[6]<v[4]){
   conflicts.add('provenance');alerts.push(['来源事件早于登记制作区间',`事件年份 ${v[6]} 早于制作区间 ${v[4]}–${v[5]}。回查日期原件与器物对应，保留可能的记载错误或错配解释。`]);
  }
  const weight=dimensions.filter(d=>conflicts.has(d[0])).reduce((s,d)=>s+d[2],0),unknown=100-weight;
  byId('priority').textContent=String(weight+unknown/2);byId('conflict').textContent=weight?String(weight):'未评';byId('coverage').textContent=weight+'%';
  byId('input-status').textContent=invalid.length?[...new Set(invalid)].join(' '):'改动仅在本浏览器计算，不保存或上传。';
  const a=byId('alerts');a.replaceChildren();for(const [title,detail]of alerts){const e=node('article');e.append(node('h3',title),node('p',detail));a.append(e);}
  if(!alerts.length){const e=node('article');e.append(node('h3','当前记载未触发这两条冲突规则'),node('p','其余专业材料尚未评价。指数 50 表示待补材料，不能当作 50% 真品率；没有冲突记录也不能当作已确认相符。'));a.append(e);}
  const list=byId('dimensions');list.replaceChildren();for(const [id,title,w]of dimensions){const li=node('li');li.append(node('strong',`${title} · 权重 ${w}`),node('span',conflicts.has(id)?'矛盾待复核':'未知 / 待补证'),node('small',conflicts.has(id)?'规则定位到上方具体记载；复核后可在专业案卷中保留修订。':'没有本次可核对的专业结论；未知项不作为低风险证明。'));list.append(li);}
 }
 const presets={height:[300,301,350,351,null,null,null],date:[null,null,null,null,1820,1840,1700],combined:[300,301,350,351,1820,1840,1700],unknown:[null,null,null,null,null,null,null]};
 function preset(key){ids.forEach((id,i)=>{byId(id).value=presets[key][i]??'';});document.querySelectorAll('[data-preset]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.preset===key)));update();}
 document.querySelectorAll('[data-preset]').forEach(b=>b.addEventListener('click',()=>preset(b.dataset.preset)));ids.forEach(id=>byId(id).addEventListener('input',()=>{document.querySelectorAll('[data-preset]').forEach(b=>b.setAttribute('aria-pressed','false'));update();}));byId('reset').addEventListener('click',()=>preset('height'));update();
})();
