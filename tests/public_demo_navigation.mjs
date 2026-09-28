// Real application dialog controls are exercised in jsdom, without native confirm answers.
// jsdom still does not verify browser layout, focus trapping or native beforeunload UI.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

const site=new URL('../site/',import.meta.url);
const html=await readFile(new URL('demo.html',site),'utf8');
const data=JSON.parse(await readFile(new URL('data/demo-cases.json',site),'utf8'));
const nativeTimer=globalThis.setTimeout;
let fixtureID=0;

async function fixture(caseID='met-48607') {
  const dom=new JSDOM(html,{url:`http://localhost/cizheng-agent-skills/demo.html?case=${caseID}`,pretendToBeVisual:true});
  for(const key of ['window','document','history','location','localStorage','FormData'])globalThis[key]=dom.window[key];
  dom.window.scrollTo=()=>{};dom.window.HTMLElement.prototype.scrollIntoView=()=>{};
  const dialogs=[];
  dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;dialogs.push(this.textContent);};
  dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new dom.window.Event('close'));};
  globalThis.fetch=async path=>new Response(await readFile(new URL(path,site)),{status:200});
  globalThis.setTimeout=(callback,delay,...args)=>{const timer=nativeTimer(callback,delay,...args);timer.unref();return timer;};
  await import(new URL(`demo.js?navigation-fixture=${++fixtureID}`,site));
  const $=selector=>dom.window.document.querySelector(selector);
  const click=async selector=>{const element=$(selector);assert.ok(element,`missing control ${selector}`);element.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true,cancelable:true}));await Promise.resolve();};
  const fill=(selector,value)=>{const element=$(selector);assert.ok(element);element.value=String(value);element.dispatchEvent(new dom.window.Event('input',{bubbles:true}));};
  const submit=selector=>{const form=$(selector);assert.equal(form.checkValidity(),true);form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));};
  const change=async(selector,value)=>{const element=$(selector);element.value=value;element.dispatchEvent(new dom.window.Event('change',{bubbles:true}));await Promise.resolve();};
  const stored=()=>JSON.parse(dom.window.localStorage.getItem('cizheng-guided-v1:'+caseID));
  const stage=()=>$('.stage-nav [aria-current="step"]').dataset.stage;
  const choose=async choice=>{
    assert.equal($('#unsaved-dialog').open,true,'navigation waits for a visible application dialog choice');
    await click(choice==='keep'?'#unsaved-dialog [data-keep-editing]':'#unsaved-dialog [data-discard-unsaved]');
    assert.equal($('#unsaved-dialog').open,false);
  };
  const escape=async()=>{
    assert.equal($('#unsaved-dialog').open,true);
    $('#unsaved-dialog').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    await Promise.resolve();assert.equal($('#unsaved-dialog').open,false);
  };
  return {dom,$,click,fill,submit,change,stored,stage,dialogs,choose,escape};
}

test('jsdom: dirty catalogue navigation cancels without losing input and only explicit confirm discards it',async()=>{
  const ui=await fixture();
  try {
    const original=ui.$('#field-object_name').value;
    await ui.click('[data-stage="2"]');await ui.click('[data-stage="0"]');assert.equal(ui.dialogs.length,0);
    ui.fill('#field-object_name','未保存的器物名称');const href=ui.dom.window.location.href;
    await ui.click('[data-stage="1"]');
    assert.equal(ui.stage(),'0');assert.equal(ui.$('#field-object_name').value,'未保存的器物名称');assert.equal(ui.dom.window.location.href,href);
    assert.equal(ui.stored(),null,'navigation protection does not auto-save');assert.ok(ui.dialogs.at(-1).includes('未保存的编目'));
    assert.equal(ui.$('#unsaved-dialog').parentElement,ui.dom.window.document.body);
    assert.equal(ui.$('#unsaved-dialog').getAttribute('aria-labelledby'),'unsaved-title');
    assert.equal(ui.dom.window.document.activeElement,ui.$('#unsaved-dialog [data-keep-editing]'));
    await ui.choose('keep');assert.equal(ui.$('#field-object_name').value,'未保存的器物名称');
    await ui.click('[data-stage="1"]');await ui.escape();assert.equal(ui.stage(),'0');assert.equal(ui.$('#field-object_name').value,'未保存的器物名称');
    await ui.click('[data-stage="1"]');assert.equal(ui.stage(),'0','dialog opening alone never discards the draft');await ui.choose('discard');assert.equal(ui.stage(),'1');
    await ui.click('[data-stage="0"]');assert.equal(ui.$('#field-object_name').value,original);
    assert.equal(ui.dialogs.length,3,'returning to an untouched form does not prompt again');
  } finally {ui.dom.window.close();}
});

test('jsdom: saving either catalogue or notes preserves the other draft, then saving both permits normal navigation',async()=>{
  const ui=await fixture();
  try {
    ui.fill('#field-object_name','已保存的编目');ui.fill('#user-notes','尚未保存的工作备注');ui.submit('#catalogue-form');
    assert.equal(ui.$('#user-notes').value,'尚未保存的工作备注');assert.equal(ui.stored().notes,'');assert.equal(ui.dialogs.length,0);
    await ui.click('[data-stage="1"]');assert.equal(ui.stage(),'0');assert.equal(ui.$('#user-notes').value,'尚未保存的工作备注');
    assert.ok(ui.dialogs.at(-1).includes('工作备注'));await ui.choose('keep');
    ui.submit('#notes-form');await ui.click('[data-stage="1"]');await ui.click('[data-stage="0"]');assert.equal(ui.dialogs.length,1);
    ui.fill('#field-object_name','第二次待保存编目');ui.fill('#user-notes','第二次已保存备注');ui.submit('#notes-form');
    assert.equal(ui.$('#field-object_name').value,'第二次待保存编目');assert.equal(ui.stored().catalogue.object_name,'已保存的编目');
    ui.submit('#catalogue-form');await ui.click('[data-stage="2"]');assert.equal(ui.stage(),'2');assert.equal(ui.dialogs.length,1);
    assert.equal(ui.stored().catalogue.object_name,'第二次待保存编目');assert.equal(ui.stored().notes,'第二次已保存备注');
  } finally {ui.dom.window.close();}
});

test('jsdom: unsaved observation protects image switches and a cancelled case selector restores its current value',async()=>{
  const ui=await fixture();
  try {
    await ui.click('[data-stage="4"]');await ui.click('[data-supplement]');await ui.click('[data-stage="1"]');
    ui.fill('#observation-title','未保存的定位观察');ui.fill('#observation-text','需要先保存这份观察。');ui.fill('#observation-form [name="x"]',25);
    const saved=ui.stored();await ui.click('[data-image="48607-image-2"]');
    assert.equal(ui.$('.thumbnail.active').dataset.image,'48607-image-1');assert.equal(ui.$('#observation-title').value,'未保存的定位观察');assert.deepEqual(ui.stored(),saved);
    await ui.choose('keep');await ui.click('[data-image="48607-image-2"]');await ui.choose('discard');assert.equal(ui.$('.thumbnail.active').dataset.image,'48607-image-2');assert.equal(ui.$('#observation-title').value,'');
    await ui.click('[data-image="48607-image-1"]');ui.fill('#observation-title','案件切换前的观察');ui.fill('#observation-text','取消切换应完整保留。');
    const href=ui.dom.window.location.href;await ui.change('#case-switch','met-51185');await ui.choose('keep');
    assert.equal(ui.$('#case-switch').value,'met-48607');assert.equal(ui.stage(),'1');assert.equal(ui.$('#observation-title').value,'案件切换前的观察');assert.equal(ui.dom.window.location.href,href);
    await ui.change('#case-switch','met-51185');await ui.choose('discard');assert.equal(ui.$('#case-switch').value,'met-51185');assert.equal(ui.stage(),'0');
    await ui.click('[data-stage="1"]');assert.equal(ui.$('#observation-title').value,'');
    assert.equal(ui.dialogs.length,4);
  } finally {ui.dom.window.close();}
});

test('jsdom: return to scene selection prompts on dirty input; a saved observation and unchanged edit form remain clean',async()=>{
  const ui=await fixture();
  try {
    ui.fill('#user-notes','返回场景前未保存的备注');const href=ui.dom.window.location.href;
    await ui.click('[data-show-chooser]');assert.equal(ui.stage(),'0');assert.equal(ui.$('#user-notes').value,'返回场景前未保存的备注');assert.equal(ui.dom.window.location.href,href);
    await ui.choose('keep');await ui.click('[data-show-chooser]');await ui.choose('discard');assert.equal(ui.dom.window.document.querySelectorAll('[data-open-case]').length,3);
    assert.equal(ui.dom.window.location.hash,'');assert.equal(new URL(ui.dom.window.location.href).searchParams.has('case'),false);
    await ui.click('[data-open-case="met-48607"]');await ui.click('[data-stage="1"]');
    ui.fill('#observation-title','已保存观察');ui.fill('#observation-text','现有图像的使用者记录。');ui.submit('#observation-form');
    const user=ui.stored().observations.find(o=>o.origin==='browser_user');const prompts=ui.dialogs.length;
    await ui.click('[data-stage="2"]');await ui.click('[data-stage="1"]');await ui.click(`[data-edit-observation="${user.id}"]`);await ui.click('[data-stage="5"]');
    assert.equal(ui.dialogs.length,prompts,'saved observation, untouched edit prefill and review defaults do not produce false warnings');
  } finally {ui.dom.window.close();}
});

test('jsdom: not_reviewed and stale review forms use their displayed defaults and navigate without false prompts',async()=>{
  for(const pack of data.cases){
    const ui=await fixture(pack.id);
    try {
      await ui.click('[data-stage="5"]');assert.equal(ui.$('#review-status').value,'reviewed');await ui.click('[data-stage="0"]');assert.equal(ui.dialogs.length,0);
      await ui.click('[data-stage="5"]');ui.fill('#review-name','教学使用者');ui.fill('#review-notes','已核对资料，仍不作真伪判断。');ui.submit('#review-form');
      await ui.click('[data-stage="0"]');ui.fill('#user-notes','保存后使旧复核过期。');ui.submit('#notes-form');assert.equal(ui.stored().review.status,'stale');
      await ui.click('[data-stage="5"]');assert.equal(ui.$('#review-status').value,'reviewed');await ui.click('[data-stage="2"]');assert.equal(ui.dialogs.length,0);
    } finally {ui.dom.window.close();}
  }
});

test('jsdom: a simulated located-evidence action uses the same unsaved guard before changing view or selection',async()=>{
  const ui=await fixture();
  try {
    ui.fill('#field-object_name','待保存的名称');
    // Reuse the public citation control contract to exercise this route from an editable context.
    const button=ui.dom.window.document.createElement('button');button.id='located-evidence-fixture';button.dataset.citationFinding=data.cases[0].findings[0].id;button.dataset.citationIndex='0';ui.$('#app').append(button);
    await ui.click('#located-evidence-fixture');assert.equal(ui.stage(),'0');assert.equal(ui.$('#field-object_name').value,'待保存的名称');assert.equal(ui.stored(),null);
    await ui.choose('keep');await ui.click('#located-evidence-fixture');await ui.choose('discard');assert.equal(ui.stage(),'2');assert.ok(ui.$('.citation-banner'));assert.ok(ui.$('.document-lines mark'));
    assert.equal(ui.dialogs.length,2);
  } finally {ui.dom.window.close();}
});

test('jsdom beforeunload fixture requests page-leave protection only for actually unsaved input',async()=>{
  const ui=await fixture();
  try {
    const leaving=()=>{const event=new ui.dom.window.Event('beforeunload',{cancelable:true});ui.dom.window.dispatchEvent(event);return event.defaultPrevented;};
    assert.equal(leaving(),false);ui.fill('#field-object_name','未保存名称');assert.equal(leaving(),true);
    ui.submit('#catalogue-form');assert.equal(leaving(),false);
    await ui.click('[data-stage="1"]');assert.equal(leaving(),false);ui.fill('#observation-title','未保存观察');assert.equal(leaving(),true);
    ui.fill('#observation-text','保存后可以正常离开。');ui.submit('#observation-form');assert.equal(leaving(),false);
    assert.equal(ui.dialogs.length,0,'beforeunload is a browser event and does not open another application dialog');
  } finally {ui.dom.window.close();}
});
