import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createState, updateState, applySupplement, findingsFor, buildReport, buildBundleEntries, reportHTML, restoreState} from '../site/demo-engine.js';
import {makeZip, crc32} from '../site/zip.js';

const site = new URL('../site/', import.meta.url);
const payload = JSON.parse(await readFile(new URL('data/demo-cases.json',site),'utf8'));
const skills = JSON.parse(await readFile(new URL('data/skills.json',site),'utf8')).skills;
const fixedTime = '2026-09-28T01:00:00.000Z';
const load = path => readFile(new URL(path,site));

test('published packs are three attributed cases with usable primary documents and located evidence', () => {
  assert.equal(payload.ai_inference_performed,false); assert.equal(payload.model_calls,0);
  assert.deepEqual(new Set(payload.cases.map(c=>c.role)),new Set(['museum','collection','auction']));
  assert.equal(skills.length,7);
  for (const pack of payload.cases) {
    assert.ok(pack.object_url.startsWith('https://www.metmuseum.org/art/collection/search/'));
    assert.equal(pack.expert_reviewed,false); assert.equal(pack.ai_inference_performed,false);
    assert.equal(pack.documents.length,3); assert.ok(pack.documents.every(d=>d.text.length>250));
    const findings = [...pack.findings,...pack.supplements.flatMap(s=>s.after_findings)];
    for (const f of findings) for (const citation of f.citations) {
      if (citation.kind==='document') {
        const doc = pack.documents.find(d=>d.id===citation.target_id); assert.ok(doc);
        const {start,end}=citation.locator; assert.ok(start>=0 && end>start && end<=doc.text.length);
        assert.ok(doc.text.slice(start,end).trim().length>0);
      } else {
        assert.equal(citation.kind,'image'); assert.ok(pack.images.some(i=>i.id===citation.target_id));
        const r=citation.region; assert.ok(r.x>=0 && r.y>=0 && r.width>0 && r.height>0 && r.x+r.width<=1 && r.y+r.height<=1);
      }
    }
  }
});

test('a saved review becomes stale after real edits, without losing its statement or historical snapshot', () => {
  const pack = payload.cases[0]; let state=createState(pack,fixedTime);
  state=updateState(state,{review:{status:'reviewed',name:'体验者',notes:'仅核查公开材料，未上手实物。',at:fixedTime}},'人工复核',fixedTime);
  const reviewedRevision=state.revision;
  state=updateState(state,{notes:'需要底足照片。'},'补充备注',fixedTime);
  assert.equal(state.review.status,'stale'); assert.equal(state.review.notes,'仅核查公开材料，未上手实物。');
  assert.equal(state.review.verified_identity,false);
  assert.equal(state.history.find(h=>h.snapshot.revision===reviewedRevision).snapshot.review.status,'reviewed');
  const report=buildReport(pack,state,fixedTime);
  assert.equal(report.user_notes,'需要底足照片。'); assert.equal(report.ai_inference_performed,false);
});

test('preloaded supplements are idempotent and distinguish their curated revisions from actual user history', () => {
  for (const pack of payload.cases) {
    const original=createState(pack,fixedTime), id=pack.supplements[0].id;
    const before=findingsFor(pack,original);
    const after=applySupplement(pack,original,id,fixedTime);
    assert.equal(after.revision,2); assert.equal(original.revision,1);
    assert.notDeepEqual(findingsFor(pack,after),before);
    assert.deepEqual(applySupplement(pack,after,id,fixedTime),after);
    assert.throws(()=>applySupplement(pack,after,'another-case'),/Unknown supplement/);
    assert.ok(findingsFor(pack,after).every(f=>f.origin==='project_curated_teaching' && f.ai_inference_performed===false));
    const restored=restoreState(pack,JSON.parse(JSON.stringify(after))); assert.equal(restored.case_id,pack.id);
    assert.equal(restoreState(payload.cases.find(c=>c.id!==pack.id),after).revision,1);
  }
});

test('all three exported ZIPs decode in the independent Python ZIP reader and match every byte digest', async () => {
  for (const pack of payload.cases) {
    let state=createState(pack,fixedTime);
    state=updateState(state,{notes:'本次实际修改的备注：底部证据仍缺失。'},'保存备注',fixedTime);
    const {entries}=await buildBundleEntries(pack,state,load,skills,fixedTime);
    const archive=makeZip(entries);
    const summary=JSON.parse(execFileSync('python3',['-c',`
import io,json,zipfile,hashlib,sys
z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))
assert z.testzip() is None
m=json.loads(z.read('manifest.json')); r=json.loads(z.read('report.json'))
assert m['ai_inference_performed'] is False and r['ai_inference_performed'] is False
assert r['user_notes']=='本次实际修改的备注：底部证据仍缺失。'
assert len(m['files'])+1==len(z.namelist())
for f in m['files']:
    raw=z.read(f['path']); assert len(raw)==f['bytes']; assert hashlib.sha256(raw).hexdigest()==f['sha256']
for d in r['documents']: assert z.read('documents/'+d['id']+'.txt').decode()==d['text']
assert 'ai_inference_performed = false' in z.read('report.html').decode()
assert sum(n.endswith('/SKILL.md') for n in z.namelist())==7
print(json.dumps({'case':r['case_id'],'files':len(z.namelist()),'images':len(r['images'])}))
`],{input:archive,encoding:'utf8'}));
    assert.equal(summary.case,pack.id); assert.equal(summary.images,pack.images.length); assert.ok(summary.files>=20);
  }
});

test('changed photo, document and method bytes cannot masquerade as original evidence in the bundle', async () => {
  const pack=payload.cases[0], state=createState(pack,fixedTime);
  await assert.rejects(buildBundleEntries(pack,state,async()=>new Uint8Array([1,2,3]),skills,fixedTime),/图像摘要不匹配/);
  const modified=structuredClone(pack); modified.documents[0].text+='未经登记的改动';
  await assert.rejects(buildBundleEntries(modified,state,load,skills,fixedTime),/资料摘要不匹配/);
  const badSkills=structuredClone(skills); badSkills[0].content+='未经登记的方法';
  await assert.rejects(buildBundleEntries(pack,state,load,badSkills,fixedTime),/Skill 原文摘要不匹配/);
});

test('a report treats visitor HTML as text and never turns it into an active script or injected image', () => {
  const pack=payload.cases[0]; let state=createState(pack,fixedTime);
  state=updateState(state,{notes:'<script>alert(1)</script><img src=x onerror=alert(1)>', catalogue:{...state.catalogue,object_name:'<svg onload=alert(1)>'}},'编辑',fixedTime);
  const html=reportHTML(buildReport(pack,state,fixedTime));
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;')); assert.ok(html.includes('&lt;svg onload=alert(1)&gt;'));
  assert.ok(!html.includes('<script>')); assert.ok(!html.includes('<img src=x')); assert.ok(html.includes('ai_inference_performed = false'));
});

test('ZIP uses standard CRC32, rejects traversal and cannot silently overwrite duplicate evidence', () => {
  assert.equal(crc32(new TextEncoder().encode('123456789')),0xcbf43926);
  for (const path of ['../secrets','a/../../x','/absolute','a\\bad','nul\0file']) assert.throws(()=>makeZip([{path,data:'x'}]),/safe relative path/);
  assert.throws(()=>makeZip([{path:'report.json',data:'1'},{path:'report.json',data:'2'}]),/Duplicate ZIP/);
});

test('public site generations are deterministic and primary photo attribution still matches project sources', () => {
  const root=fileURLToPath(new URL('../',import.meta.url));
  const result=execFileSync('python3',['scripts/build-public-site.py','--check'],{cwd:root,encoding:'utf8'});
  assert.ok(result.includes('"result": "pass"')); assert.ok(result.includes('"private_data_read": false'));
});
