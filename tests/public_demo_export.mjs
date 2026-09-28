// Exercise the rendered application in jsdom. Downloads are captured as real Blobs,
// not browser download-manager events; actual browser interaction is checked separately.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {JSDOM} from 'jsdom';

const site=new URL('../site/',import.meta.url);
const html=await readFile(new URL('demo.html',site),'utf8');
const data=JSON.parse(await readFile(new URL('data/demo-cases.json',site),'utf8'));
const nativeTimer=globalThis.setTimeout;
let fixtureID=0;

async function fixture(caseID='met-48607') {
  const id=++fixtureID;
  const dom=new JSDOM(html,{url:`http://localhost/cizheng-agent-skills/demo.html?case=${caseID}`,pretendToBeVisual:true});
  for(const key of ['window','document','history','location','localStorage','FormData'])globalThis[key]=dom.window[key];
  dom.window.scrollTo=()=>{};dom.window.HTMLElement.prototype.scrollIntoView=()=>{};
  dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new dom.window.Event('close'));};
  const assets=[],downloads=[],urls=new Map(),timers=new Set();
  const previousURL={create:URL.createObjectURL,revoke:URL.revokeObjectURL};
  URL.createObjectURL=blob=>{const url=`blob:http://localhost/export-${id}-${urls.size}`;urls.set(url,blob);return url;};
  URL.revokeObjectURL=url=>urls.delete(url);
  dom.window.HTMLAnchorElement.prototype.click=function(){
    assert.ok(urls.has(this.href),'download points to a real generated Blob');
    downloads.push({name:this.download,blob:urls.get(this.href)});
  };
  globalThis.fetch=async path=>{
    if(String(path).startsWith('assets/'))assets.push(String(path));
    return new Response(await readFile(new URL(path,site)),{status:200});
  };
  globalThis.setTimeout=(callback,delay,...args)=>{
    const timer=nativeTimer(()=>{timers.delete(timer);callback(...args);},delay);
    timer.unref();timers.add(timer);return timer;
  };
  await import(new URL(`demo.js?export-fixture=${id}`,site));
  const $=selector=>dom.window.document.querySelector(selector);
  const click=async selector=>{
    const element=$(selector);assert.ok(element,`missing control ${selector}`);
    element.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true,cancelable:true}));await Promise.resolve();
  };
  const fill=(selector,value)=>{
    const element=$(selector);assert.ok(element,`missing field ${selector}`);element.value=String(value);
    element.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  };
  const submit=selector=>{
    const form=$(selector);assert.equal(form.checkValidity(),true);
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
  };
  const storageText=()=>dom.window.localStorage.getItem('cizheng-guided-v1:'+caseID);
  const stored=()=>JSON.parse(storageText());
  const stage=()=>$('.stage-nav [aria-current="step"]').dataset.stage;
  // Editor stages do not expose download buttons. A view-local test control invokes
  // their shared delegated export route without pretending it is part of the UI.
  const sharedExport=async format=>{
    let button=$(`[data-export="${format}"]`);
    if(!button){button=dom.window.document.createElement('button');button.type='button';button.dataset.export=format;$('#app').append(button);}
    await click(`[data-export="${format}"]`);
  };
  const finished=async expected=>{
    const deadline=Date.now()+3000;
    while(Date.now()<deadline){
      if(downloads.length===expected && !dom.window.document.querySelector('[data-export]:disabled'))return downloads.at(-1);
      if($('#toast').textContent.includes('导出失败') || $('#toast').textContent.includes('导出已中止'))throw new Error($('#toast').textContent);
      await new Promise(resolve=>nativeTimer(resolve,5));
    }
    throw new Error(`export did not finish: ${$('#toast').textContent}`);
  };
  const close=()=>{for(const timer of timers)clearTimeout(timer);URL.createObjectURL=previousURL.create;URL.revokeObjectURL=previousURL.revoke;globalThis.setTimeout=nativeTimer;dom.window.close();};
  return {dom,$,click,fill,submit,storageText,stored,stage,sharedExport,finished,assets,downloads,close};
}

function checkBlocked(ui,form,label,before) {
  assert.equal(ui.$(`#${form.id}`),form,'blocking an export never replaces the current form');
  assert.equal(ui.stage(),before.stage);assert.equal(ui.$('#case-switch').value,before.caseID);
  assert.equal(ui.dom.window.location.href,before.href);
  assert.equal(ui.storageText(),before.storage,'blocking an export neither saves input nor invents a review');
  assert.equal(ui.assets.length,before.assets,'no image is loaded before the save-first check');
  assert.equal(ui.downloads.length,before.downloads,'no partial file is downloaded');
  assert.equal(ui.$('#unsaved-dialog').open,false,'export is blocked, with no offer to discard input');
  assert.equal(ui.dom.window.document.querySelector('[data-export]:disabled'),null,'blocking never enters the busy rendering state');
  assert.match(ui.$('#toast').textContent,/请先保存后导出/);assert.ok(ui.$('#toast').textContent.includes(label));
  assert.equal(ui.$('#toast').getAttribute('role'),'status');
}
function context(ui){return {stage:ui.stage(),caseID:ui.$('#case-switch').value,href:ui.dom.window.location.href,storage:ui.storageText(),assets:ui.assets.length,downloads:ui.downloads.length};}

test('jsdom: unsaved review blocks real JSON/HTML/ZIP controls in all three cases and preserves entered text',async()=>{
  for(const pack of data.cases){
    const ui=await fixture(pack.id);
    try {
      await ui.click('[data-stage="5"]');
      ui.fill('#review-name','尚未保存的填写者');ui.fill('#review-notes','补充依据还没有整理好，这段复核不能自动保存。');
      ui.$('#review-notes').focus();const form=ui.$('#review-form'),before=context(ui);
      for(const format of ['json','html','zip']){
        await ui.click(`[data-export="${format}"]`);checkBlocked(ui,form,'复核意见',before);
        assert.equal(ui.$('#review-name').value,'尚未保存的填写者');assert.equal(ui.$('#review-notes').value,'补充依据还没有整理好，这段复核不能自动保存。');
        assert.equal(ui.dom.window.document.activeElement,ui.$('#review-notes'),'the export warning preserves the current editing focus');
        assert.match(ui.$('.review-state').textContent,/尚未记录人工复核/);
      }
    } finally {ui.close();}
  }
});

test('jsdom shared route: dirty catalogue and supplementary work notes remain intact until both are explicitly saved',async()=>{
  const ui=await fixture();
  try {
    await ui.click('[data-stage="4"]');await ui.click('[data-supplement]');await ui.click('[data-stage="0"]');
    ui.fill('#field-object_name',' 使用者保存的编目名称 ');ui.fill('#user-notes',' 新纳入补充件后的工作备注，尚未提交。 ');
    const catalogue=ui.$('#catalogue-form'),notes=ui.$('#notes-form'),before=context(ui),active=ui.stored().active_supplements;
    for(const format of ['json','html','zip']){
      await ui.sharedExport(format);checkBlocked(ui,catalogue,'编目、工作备注',before);
      assert.equal(ui.$('#notes-form'),notes);assert.equal(ui.$('#field-object_name').value,' 使用者保存的编目名称 ');
      assert.equal(ui.$('#user-notes').value,' 新纳入补充件后的工作备注，尚未提交。 ');
      assert.deepEqual(ui.stored().active_supplements,active);
    }
    ui.submit('#catalogue-form');const stillDirty=ui.$('#notes-form'),afterCatalogue=context(ui);
    await ui.sharedExport('json');checkBlocked(ui,stillDirty,'工作备注',afterCatalogue);
    assert.ok(!ui.$('#toast').textContent.includes('编目'),'the message names only the remaining unsaved form');
    assert.equal(ui.$('#user-notes').value,' 新纳入补充件后的工作备注，尚未提交。 ');
    ui.submit('#notes-form');const saved=ui.storageText();await ui.sharedExport('json');await ui.finished(1);
    const report=JSON.parse(await ui.downloads[0].blob.text());
    assert.equal(report.catalogue.object_name,'使用者保存的编目名称');assert.equal(report.user_notes,'新纳入补充件后的工作备注，尚未提交。');
    assert.deepEqual(report.active_supplements,active);assert.equal(report.human_review.status,'not_reviewed');
    assert.equal(report.ai_inference_performed,false);assert.equal(ui.storageText(),saved,'exporting never adds another edit revision');
  } finally {ui.close();}
});

test('jsdom shared route: an unsaved observation revision cannot disappear into an exported old record',async()=>{
  const ui=await fixture();
  try {
    await ui.click('[data-stage="1"]');ui.fill('#observation-title','使用者原观察');ui.fill('#observation-text','已经明确保存的观察。');ui.submit('#observation-form');
    const original=ui.stored().observations.find(observation=>observation.origin==='browser_user');
    await ui.click(`[data-edit-observation="${original.id}"]`);ui.fill('#observation-text','未保存的新解释，需要先核对资料。');ui.fill('#observation-form [name="x"]',35);
    const form=ui.$('#observation-form'),before=context(ui);
    for(const format of ['json','html','zip']){
      await ui.sharedExport(format);checkBlocked(ui,form,'观察',before);
      assert.equal(ui.$('#observation-text').value,'未保存的新解释，需要先核对资料。');assert.equal(ui.$('#observation-form [name="x"]').value,'35');
      assert.equal(ui.stored().observations.find(observation=>observation.id===original.id).text,original.text);
    }
    ui.submit('#observation-form');const saved=ui.storageText();await ui.sharedExport('json');await ui.finished(1);
    const report=JSON.parse(await ui.downloads[0].blob.text()),revised=report.observations.find(observation=>observation.id===original.id);
    assert.equal(revised.text,'未保存的新解释，需要先核对资料。');assert.equal(revised.region.x,.35);assert.equal(revised.origin,'browser_user');
    assert.ok(report.history.some(entry=>entry.snapshot.observations.some(observation=>observation.id===original.id && observation.text===original.text)),'old actual observation remains in its edit history');
    assert.equal(report.human_review.status,'not_reviewed');assert.equal(ui.storageText(),saved);
  } finally {ui.close();}
});

test('jsdom: an unsubmitted review treatment is blocked, while restoring its default allows export without a fake review',async()=>{
  const ui=await fixture();
  try {
    await ui.click('[data-stage="5"]');ui.fill('#review-status','needs_more_evidence');const form=ui.$('#review-form'),before=context(ui);
    await ui.click('[data-export="json"]');checkBlocked(ui,form,'复核意见',before);
    assert.equal(ui.$('#review-status').value,'needs_more_evidence');assert.equal(ui.stored(),null);
    ui.fill('#review-status','reviewed');await ui.click('[data-export="json"]');await ui.finished(1);
    const report=JSON.parse(await ui.downloads[0].blob.text());
    assert.equal(report.human_review.status,'not_reviewed');assert.equal(report.human_review.name,'');assert.equal(report.human_review.notes,'');
    assert.equal(report.human_review.verified_identity,false);assert.equal(ui.stored(),null);
  } finally {ui.close();}
});

test('jsdom: untouched not_reviewed and stale review forms export their actual stored states in all three cases',async()=>{
  for(const pack of data.cases){
    const ui=await fixture(pack.id);
    try {
      await ui.click('[data-stage="5"]');assert.equal(ui.$('#review-status').value,'reviewed');
      await ui.click('[data-export="json"]');await ui.finished(1);
      const unreviewed=JSON.parse(await ui.downloads[0].blob.text());assert.equal(unreviewed.human_review.status,'not_reviewed');assert.equal(ui.stored(),null);
      ui.fill('#review-name','填写过意见的教学使用者');ui.fill('#review-notes','旧版意见，不代表专家签署。');ui.submit('#review-form');
      await ui.click('[data-stage="0"]');ui.fill('#user-notes','新的资料备注使原复核需要更新。');ui.submit('#notes-form');
      assert.equal(ui.stored().review.status,'stale');await ui.click('[data-stage="5"]');assert.equal(ui.$('#review-status').value,'reviewed');
      const saved=ui.storageText();await ui.click('[data-export="json"]');await ui.finished(2);
      const stale=JSON.parse(await ui.downloads[1].blob.text());assert.equal(stale.human_review.status,'stale');assert.equal(stale.human_review.verified_identity,false);
      assert.equal(stale.human_review.notes,'旧版意见，不代表专家签署。');assert.equal(stale.ai_inference_performed,false);assert.equal(ui.storageText(),saved);
    } finally {ui.close();}
  }
});

const inspectZip=String.raw`
import hashlib,io,json,sys,zipfile
with zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())) as bundle:
    assert bundle.testzip() is None
    manifest=json.loads(bundle.read('manifest.json'))
    for item in manifest['files']:
        raw=bundle.read(item['path'])
        assert len(raw)==item['bytes']
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
    report=json.loads(bundle.read('report.json'))
    assert manifest['ai_inference_performed'] is False
    assert report['ai_inference_performed'] is False
    assert 'ai_inference_performed = false' in bundle.read('report.html').decode('utf-8')
    print(json.dumps({'report':report,'file_count':len(manifest['files']),'images':len([name for name in bundle.namelist() if name.startswith('images/')])},ensure_ascii=False))
`;

test('jsdom download capture: explicitly saved reviews produce usable JSON, embedded HTML and independently SHA-verified ZIP for all cases',async()=>{
  for(const pack of data.cases){
    const ui=await fixture(pack.id);
    try {
      await ui.click('[data-stage="5"]');ui.fill('#review-name','教学使用者');ui.fill('#review-notes','公开资料已核对；未作实物鉴定，仍须补充底足与修复记录。');ui.submit('#review-form');
      const saved=ui.storageText(),stored=ui.stored();
      for(const format of ['json','html','zip']){
        // Each click must produce its own Blob, rather than treating the prior
        // format's download as completion of an asynchronous image export.
        const expected={json:1,html:2,zip:3}[format];
        await ui.click(`[data-export="${format}"]`);await ui.finished(expected);
        assert.equal(ui.storageText(),saved);assert.equal(ui.stage(),'5');assert.equal(ui.$('#case-switch').value,pack.id);
        assert.equal(ui.$('#review-name').value,'教学使用者');assert.equal(ui.$('#review-notes').value,stored.review.notes);
      }
      assert.deepEqual(ui.downloads.map(item=>item.name),['json','html','zip'].map(format=>`cizheng-${pack.id}-r${stored.revision}.${format}`));
      const report=JSON.parse(await ui.downloads[0].blob.text());assert.equal(report.case_id,pack.id);assert.equal(report.human_review.status,'reviewed');
      assert.equal(report.human_review.name,'教学使用者');assert.equal(report.human_review.notes,stored.review.notes);assert.equal(report.human_review.verified_identity,false);assert.equal(report.ai_inference_performed,false);
      const htmlText=await ui.downloads[1].blob.text();assert.ok(htmlText.includes('ai_inference_performed = false'));assert.ok(htmlText.includes('教学使用者'));
      // Region previews intentionally repeat a source image. Check their decoded
      // byte hashes rather than incorrectly requiring one img element per photo.
      const imageHashes=new Set(Array.from(htmlText.matchAll(/src="data:image\/jpeg;base64,([^"]+)"/g),match=>createHash('sha256').update(Buffer.from(match[1],'base64')).digest('hex')));
      assert.deepEqual([...imageHashes].sort(),pack.images.map(image=>image.sha256).sort(),'HTML embeds every unchanged original image for offline reading');
      const result=spawnSync('python3',['-c',inspectZip],{input:Buffer.from(await ui.downloads[2].blob.arrayBuffer()),encoding:'utf8',timeout:10000,maxBuffer:4*1024*1024,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
      assert.equal(result.status,0,result.stderr || String(result.error));const zip=JSON.parse(result.stdout);
      assert.equal(zip.report.case_id,pack.id);assert.equal(zip.report.revision,stored.revision);assert.deepEqual(zip.report.human_review,report.human_review);
      assert.equal(zip.images,pack.images.length);assert.ok(zip.file_count>10);assert.deepEqual(zip.report.history,report.history);
    } finally {ui.close();}
  }
});
