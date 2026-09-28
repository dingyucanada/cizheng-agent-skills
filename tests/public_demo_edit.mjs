// These are jsdom interaction fixtures, not a real-browser layout or pointer test.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

const site=new URL('../site/',import.meta.url);
const html=await readFile(new URL('demo.html',site),'utf8');
const payload=JSON.parse(await readFile(new URL('data/demo-cases.json',site),'utf8'));
const nativeTimer=globalThis.setTimeout;
let fixtureID=0;

async function fixture(caseID) {
  const dom=new JSDOM(html,{url:`http://localhost/cizheng-agent-skills/demo.html?case=${caseID}`,pretendToBeVisual:true});
  for (const key of ['window','document','history','location','localStorage','FormData']) globalThis[key]=dom.window[key];
  globalThis.confirm=()=>true;
  dom.window.scrollTo=()=>{};
  dom.window.HTMLElement.prototype.scrollIntoView=()=>{};
  dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const fetched=[];
  globalThis.fetch=async path=>{
    fetched.push(String(path));
    return new Response(await readFile(new URL(path,site)),{status:200});
  };
  globalThis.setTimeout=(callback,delay,...args)=>{
    const timer=nativeTimer(callback,delay,...args);timer.unref();return timer;
  };
  await import(new URL(`demo.js?edit-fixture=${++fixtureID}`,site));
  const $=selector=>dom.window.document.querySelector(selector);
  const click=selector=>{
    const element=$(selector);assert.ok(element,`missing clickable ${selector}`);
    element.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true,cancelable:true}));
  };
  const fill=(selector,value)=>{
    const element=$(selector);assert.ok(element,`missing field ${selector}`);
    element.value=String(value);element.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  };
  const submit=selector=>{
    const form=$(selector);assert.ok(form);assert.equal(form.checkValidity(),true,'fixture uses valid visible form fields');
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
  };
  const stored=()=>JSON.parse(dom.window.localStorage.getItem('cizheng-guided-v1:'+caseID));
  const change=(selector,value)=>{
    const element=$(selector);element.value=String(value);element.dispatchEvent(new dom.window.Event('change',{bubbles:true}));
  };
  return {dom,$,click,fill,submit,stored,change,fetched};
}

function addObservation(ui,title='使用者初始观察',text='仅记录可见现象，尚未检查实物。') {
  ui.click('[data-stage="1"]');
  ui.fill('#observation-title',title);ui.fill('#observation-text',text);
  ui.fill('#observation-form [name="x"]',20);ui.fill('#observation-form [name="y"]',25);
  ui.fill('#observation-form [name="width"]',20);ui.fill('#observation-form [name="height"]',30);
  ui.submit('#observation-form');
  return ui.stored().observations.find(o=>o.origin==='browser_user');
}

for (const pack of payload.cases) test(`jsdom: ${pack.role} observation add → revise preserves ID/history and invalidates a saved review`,async()=>{
  const ui=await fixture(pack.id);
  try {
    const original=addObservation(ui),afterAdd=ui.stored();
    assert.equal(afterAdd.observations.filter(o=>o.origin==='browser_user').length,1);
    assert.equal(ui.dom.window.document.querySelectorAll('[data-edit-observation]').length,1);
    for (const preset of pack.observations) {
      const button=ui.$(`[data-observation="${preset.id}"]`);
      assert.equal(button.closest('.observation-card').querySelector('[data-edit-observation]'),null,'project presets have no edit action');
    }
    ui.click('[data-stage="5"]');ui.fill('#review-name','教学体验使用者');ui.fill('#review-notes','已核对公开教学材料，实物状况仍待补证。');ui.submit('#review-form');
    const beforeEdit=ui.stored();assert.equal(beforeEdit.review.status,'reviewed');
    ui.click('[data-stage="1"]');ui.click(`[data-edit-observation="${original.id}"]`);
    assert.equal(ui.$('#observation-form').dataset.editingId,original.id);
    assert.equal(ui.$('#observation-title').value,original.title);assert.equal(ui.$('#observation-text').value,original.text);
    assert.equal(ui.$('#observation-form [name="x"]').value,'20');
    assert.equal(ui.$('#observation-form [name="height"]').value,'30');
    ui.fill('#observation-title','使用者修订观察');ui.fill('#observation-text','补充区域限制：反光部位不能据此认定修复。');
    ui.fill('#observation-form [name="x"]',40);ui.fill('#observation-form [name="width"]',18);
    ui.submit('#observation-form');
    const updated=ui.stored(),revised=updated.observations.find(o=>o.id===original.id);
    assert.equal(updated.revision,beforeEdit.revision+1);assert.equal(updated.observations.length,afterAdd.observations.length);
    assert.equal(revised.title,'使用者修订观察');assert.equal(revised.region.x,.4);assert.equal(revised.region.width,.18);
    assert.equal(revised.origin,'browser_user');assert.equal(revised.ai_inference_performed,false);
    assert.equal(updated.review.status,'stale');assert.equal(updated.review.notes,beforeEdit.review.notes);
    const historical=updated.history.find(h=>h.snapshot.revision===afterAdd.revision).snapshot.observations.find(o=>o.id===original.id);
    assert.deepEqual(historical,original,'old observation body and coordinates remain in its real snapshot');
    assert.deepEqual(updated.observations.filter(o=>o.origin!=='browser_user'),pack.observations,'project presets stay unchanged');
    assert.equal(ui.$('#observation-form').dataset.editingId,'');
    ui.click('[data-stage="4"]');ui.change('#snapshot-from',afterAdd.revision);
    assert.ok(ui.$('#snapshot-changes').textContent.includes('观察修订'));
    assert.ok(ui.$('#snapshot-changes').textContent.includes(original.text));
    assert.ok(ui.$('#snapshot-changes').textContent.includes(revised.text));
    assert.ok(ui.$('#snapshot-changes').textContent.includes('18%'));
    assert.deepEqual(ui.fetched,['data/demo-cases.json','data/skills.json'],'editing never uploads or invokes a model');
  } finally {ui.dom.window.close();}
});

test('jsdom: cancellation and context changes discard only the uncommitted editor, while project observations cannot enter it',async()=>{
  const ui=await fixture('met-48607');
  try {
    const original=addObservation(ui),saved=ui.stored();
    ui.click(`[data-edit-observation="${original.id}"]`);ui.fill('#observation-title','不保存的标题');ui.click('[data-cancel-observation-edit]');
    assert.deepEqual(ui.stored(),saved);assert.equal(ui.$('#observation-form').dataset.editingId,'');assert.equal(ui.$('#observation-title').value,'');
    const injected=ui.dom.window.document.createElement('button');injected.dataset.editObservation=payload.cases[0].observations[0].id;ui.$('#app').append(injected);injected.click();
    assert.equal(ui.$('#observation-form').dataset.editingId,'','handler also refuses to edit project preset IDs');
    ui.click(`[data-edit-observation="${original.id}"]`);ui.fill('#observation-title','步骤切换前的草稿');ui.click('[data-stage="2"]');ui.click('[data-stage="1"]');
    assert.equal(ui.$('#observation-form').dataset.editingId,'');assert.equal(ui.$('#observation-title').value,'');assert.deepEqual(ui.stored(),saved);
    ui.click('[data-stage="4"]');ui.click('[data-supplement]');ui.click('[data-stage="1"]');
    ui.click(`[data-edit-observation="${original.id}"]`);ui.fill('#observation-title','图片切换前的草稿');ui.click('[data-image="48607-image-2"]');
    assert.equal(ui.$('#observation-form').dataset.editingId,'');assert.equal(ui.$('#observation-title').value,'');
    ui.click('[data-image="48607-image-1"]');ui.click(`[data-edit-observation="${original.id}"]`);ui.fill('#observation-title','案卷切换前的草稿');
    ui.change('#case-switch','met-51185');ui.click('[data-stage="1"]');assert.equal(ui.$('#observation-form').dataset.editingId,'');assert.equal(ui.$('#observation-title').value,'');
    ui.change('#case-switch','met-48607');ui.click('[data-stage="1"]');assert.equal(ui.$('#observation-form').dataset.editingId,'');assert.equal(ui.$('#observation-title').value,'');
    assert.equal(ui.stored().observations.find(o=>o.id===original.id).title,original.title);
  } finally {ui.dom.window.close();}
});

function dragFixture(ui) {
  const layer=ui.$('#annotation-layer');
  // jsdom has no physical layout or pointer capture; these bounds are explicit fixtures.
  layer.getBoundingClientRect=()=>({left:10,top:20,width:200,height:400,right:210,bottom:420});
  layer.setPointerCapture=()=>{};layer.releasePointerCapture=()=>{};
  for (const [type,x,y] of [['pointerdown',40,60],['pointermove',100,180],['pointerup',100,180]]) {
    const event=new ui.dom.window.MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y});
    Object.defineProperty(event,'pointerId',{value:1});layer.dispatchEvent(event);
  }
}

test('jsdom pointer fixture: drawing and zoom rerenders preserve new and revised observation text',async()=>{
  const ui=await fixture('met-48607');
  try {
    ui.click('[data-stage="1"]');ui.fill('#observation-title','绘图前已有标题');ui.fill('#observation-text','绘图前已有描述，区域需要定位。');
    ui.click('[data-zoom="0.25"]');assert.equal(ui.$('#observation-title').value,'绘图前已有标题');
    ui.click('[data-draw]');assert.equal(ui.$('#observation-text').value,'绘图前已有描述，区域需要定位。');
    dragFixture(ui);assert.equal(ui.$('#observation-title').value,'绘图前已有标题');assert.equal(ui.$('#observation-text').value,'绘图前已有描述，区域需要定位。');
    assert.equal(ui.$('#observation-form [name="x"]').value,'15');assert.equal(ui.$('#observation-form [name="y"]').value,'10');assert.equal(ui.$('#observation-form [name="width"]').value,'30');
    ui.submit('#observation-form');const observation=ui.stored().observations.find(o=>o.origin==='browser_user');
    ui.click(`[data-edit-observation="${observation.id}"]`);ui.fill('#observation-title','修订中绘图前的标题');ui.fill('#observation-text','修订输入不会因重新框选消失。');
    ui.click('[data-fit]');ui.click('[data-draw]');dragFixture(ui);
    assert.equal(ui.$('#observation-form').dataset.editingId,observation.id);assert.equal(ui.$('#observation-title').value,'修订中绘图前的标题');assert.equal(ui.$('#observation-text').value,'修订输入不会因重新框选消失。');
    ui.submit('#observation-form');assert.equal(ui.stored().observations.filter(o=>o.origin==='browser_user').length,1);
    assert.equal(ui.stored().observations.find(o=>o.id===observation.id).text,'修订输入不会因重新框选消失。');
  } finally {ui.dom.window.close();}
});

test('jsdom: jumping directly to export never marks unvisited earlier stages complete',async()=>{
  const ui=await fixture('met-50839');
  try {
    ui.click('[data-stage="5"]');
    assert.equal(ui.dom.window.document.querySelectorAll('.stage-nav .check').length,0);
    assert.equal(ui.dom.window.document.querySelectorAll('.stage-nav [aria-current="step"]').length,1);
    assert.equal(ui.$('.stage-nav [aria-current="step"]').dataset.stage,'5');
    assert.ok(!ui.$('.stage-nav').textContent.includes('✓'));
    assert.ok(!ui.$('.stage-nav').innerHTML.includes('已经过此步骤'));
  } finally {ui.dom.window.close();}
});
