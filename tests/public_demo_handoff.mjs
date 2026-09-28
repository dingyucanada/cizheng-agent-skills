import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {createState,applySupplement,updateState,buildReport,buildBundleEntries,reportHTML} from '../site/demo-engine.js';
import {makeZip} from '../site/zip.js';

const site=new URL('../site/',import.meta.url);
const cases=JSON.parse(await readFile(new URL('data/demo-cases.json',site),'utf8')).cases;
const skills=JSON.parse(await readFile(new URL('data/skills.json',site),'utf8')).skills;
const fixedTime='2026-09-28T01:00:00.000Z';
const load=path=>readFile(new URL(path,site));

function allCitationRegions(report) {
  const expected=[];
  for (const [index,observation] of report.observations.entries()) if (observation.region) {
    expected.push({anchor:`observation-${index}`,image_id:observation.image_id,region:observation.region});
  }
  function collect(findings,prefix) {
    for (const finding of findings) for (const [index,citation] of finding.citations.entries()) {
      if (citation.kind==='image' && citation.region) expected.push({anchor:`${prefix}-${finding.id}-c${index}`,image_id:citation.target_id,region:citation.region});
    }
  }
  collect(report.curated_research_examples,'current');
  for (const version of report.teaching_opinion_versions) collect(version.findings,`opinion-${version.id}`);
  for (const history of report.history) collect(history.snapshot.curated_research_examples,`history-r${history.snapshot.revision}`);
  return expected;
}

test('every case exports original V1 and each prewritten V2 before and after activation, retaining reasons and sources',()=>{
  for (const pack of cases) {
    const original=createState(pack,fixedTime);
    const before=buildReport(pack,original,fixedTime);
    assert.equal(before.teaching_opinion_versions.length,1+pack.supplements.length);
    const v1=before.teaching_opinion_versions[0],v2=before.teaching_opinion_versions[1];
    assert.equal(v1.id,'v1'); assert.equal(v1.current,true); assert.equal(v2.current,false); assert.equal(v2.activated,false);
    assert.deepEqual(v1.findings.map(f=>f.text),pack.findings.map(f=>f.text));
    assert.deepEqual(v2.findings.map(f=>f.text),pack.supplements[0].after_findings.map(f=>f.text));
    const changed=applySupplement(pack,original,pack.supplements[0].id,fixedTime);
    const after=buildReport(pack,changed,fixedTime);
    assert.equal(after.teaching_opinion_versions[0].current,false);
    assert.equal(after.teaching_opinion_versions[1].current,true);
    assert.equal(after.teaching_opinion_versions[1].activated,true);
    assert.deepEqual(after.teaching_opinion_versions[0].findings.map(f=>f.text),v1.findings.map(f=>f.text));
    assert.equal(after.teaching_opinion_versions[1].change_reason,pack.supplements[0].change_note);
    assert.ok(after.teaching_opinion_versions[1].changes.some(c=>c.changed && c.before_text!==c.after_text));
    for (const version of after.teaching_opinion_versions) {
      assert.equal(version.origin,'project_curated_teaching'); assert.equal(version.ai_inference_performed,false);
      for (const finding of version.findings) for (const citation of finding.citations) {
        assert.ok(citation.target,'each version citation resolves to its original evidence');
        if (citation.kind==='document') {
          const originalDoc=pack.documents.find(d=>d.id===citation.target_id);
          assert.equal(citation.target.sha256,originalDoc.sha256);
          assert.equal(citation.target.excerpt,originalDoc.text.slice(citation.locator.start,citation.locator.end));
          assert.equal(citation.target.source_url,originalDoc.source_url);
        } else if (citation.kind==='image') {
          const originalImage=pack.images.find(i=>i.id===citation.target_id);
          assert.equal(citation.target.sha256,originalImage.sha256);
          assert.deepEqual(citation.target.region,citation.region);
          assert.equal(citation.target.source_url,originalImage.source_url);
        }
      }
    }
  }
});

test('unactivated preview attachments are not silently promoted into the current opinion or its evidence',()=>{
  for (const pack of cases) {
    const report=buildReport(pack,createState(pack,fixedTime),fixedTime);
    assert.deepEqual(report.curated_research_examples.map(f=>f.text),pack.findings.map(f=>f.text));
    for (const image of report.images.filter(i=>i.supplement_id)) assert.equal(image.used_in_current_teaching_revision,false);
    for (const doc of report.documents.filter(d=>d.supplement_id)) assert.equal(doc.used_in_current_teaching_revision,false);
    const preview=report.teaching_opinion_versions[1];
    assert.equal(preview.activated,false); assert.equal(preview.current,false);
    for (const f of preview.findings) for (const c of f.citations) {
      const supplemental=[...report.images,...report.documents].find(item=>item.id===c.target_id)?.supplement_id;
      if (supplemental) assert.equal(c.target.used_in_current_teaching_revision,false);
    }
    const html=reportHTML(report);
    assert.ok(html.includes('data-teaching-version="v2" data-activated="false" data-current="false"'));
    assert.ok(html.includes('补充件未激活，未用于当前教学意见'));
  }
});

test('real saved snapshots retain then-current teaching findings; legacy reconstruction is explicitly labelled',()=>{
  for (const pack of cases) {
    let state=createState(pack,fixedTime);
    state=updateState(state,{notes:'使用者真实修改'},'保存备注',fixedTime);
    state=applySupplement(pack,state,pack.supplements[0].id,fixedTime);
    assert.deepEqual(state.history[0].snapshot.curated_research_examples.map(f=>f.text),pack.findings.map(f=>f.text));
    assert.deepEqual(state.history.at(-1).snapshot.curated_research_examples.map(f=>f.text),pack.supplements[0].after_findings.map(f=>f.text));
    const report=buildReport(pack,state,fixedTime);
    assert.ok(report.history.every(h=>h.teaching_snapshot_origin==='stored_precompiled_teaching_snapshot'));
    assert.equal(report.history[1].snapshot.notes,'使用者真实修改');
    const legacy=structuredClone(state);
    for (const entry of legacy.history) delete entry.snapshot.curated_research_examples;
    const reconstructed=buildReport(pack,legacy,fixedTime);
    assert.ok(reconstructed.history.every(h=>h.teaching_snapshot_origin==='reconstructed_at_export_from_current_public_pack'));
    assert.ok(reconstructed.history[0].teaching_snapshot_notice.includes('不能视为当时原始意见'));
    assert.deepEqual(reconstructed.history[0].snapshot.curated_research_examples.map(f=>f.text),pack.findings.map(f=>f.text));
    assert.equal(legacy.history[0].snapshot.curated_research_examples,undefined,'export does not rewrite old browser history');
  }
});

test('independent HTML parser verifies every original-image ROI, document quote and local report anchor for all cases',()=>{
  for (const pack of cases) {
    const state=applySupplement(pack,createState(pack,fixedTime),pack.supplements[0].id,fixedTime);
    const report=buildReport(pack,state,fixedTime);
    const html=reportHTML(report,Object.fromEntries(pack.images.map(i=>[i.id,'images/'+i.file.split('/').pop()])));
    const expected=allCitationRegions(report);
    const parsed=JSON.parse(execFileSync('python3',['-c',String.raw`
import json,sys,math
from html.parser import HTMLParser
p=json.load(sys.stdin)
class Review(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.ids=set();self.links=[];self.regions={};self.active_svg=None;self.quotes=[];self.active_quote=None
 def handle_starttag(self,tag,items):
  a=dict(items)
  if 'id' in a:
   assert a['id'] not in self.ids,'duplicate id '+a['id'];self.ids.add(a['id'])
  if tag=='a' and a.get('href','').startswith('#'):self.links.append(a['href'][1:])
  if tag=='svg':
   assert a.get('preserveaspectratio')=='none';assert a.get('viewbox')=='0 0 1000 1000';self.active_svg=a
  if tag=='rect':
   assert self.active_svg is not None
   anchor=self.active_svg['data-region-citation'];assert anchor not in self.regions
   self.regions[anchor]={'svg':self.active_svg,'rect':a}
  if tag=='blockquote':self.active_quote={'attrs':a,'text':''}
 def handle_data(self,text):
  if self.active_quote is not None:self.active_quote['text']+=text
 def handle_endtag(self,tag):
  if tag=='svg':self.active_svg=None
  if tag=='blockquote':self.quotes.append(self.active_quote);self.active_quote=None
r=Review();r.feed(p['html'])
assert all(target in r.ids for target in r.links),'unresolved local report anchor'
assert len(r.regions)==len(p['expected'])
for item in p['expected']:
 actual=r.regions[item['anchor']];assert actual['svg']['data-image-id']==item['image_id']
 for key in ['x','y','width','height']:
  assert math.isclose(float(actual['svg']['data-'+key]),item['region'][key],rel_tol=0,abs_tol=1e-10)
  assert math.isclose(float(actual['rect'][key]),1000*item['region'][key],rel_tol=0,abs_tol=1e-8)
docs={d['id']:d['text'] for d in p['documents']}
for q in r.quotes:
 a=q['attrs'];assert q['text']==docs[a['data-document-id']][int(a['data-start']):int(a['data-end'])]
assert '.citation-photo img{display:block;width:100%;height:auto;max-height:none}' in p['html']
assert 'ai_inference_performed = false' in p['html']
assert '项目预先编写的教学意见' in p['html']
print(json.dumps({'regions':len(r.regions),'quotes':len(r.quotes),'anchors':len(r.links)}))
`],{input:JSON.stringify({html,expected,documents:pack.documents}),encoding:'utf8'}));
    assert.equal(parsed.regions,expected.length); assert.ok(parsed.quotes>=10); assert.ok(parsed.anchors>=10);
    if (pack.id==='met-48607') {
      const second=expected.find(r=>r.anchor==='opinion-v2-f2-c1');
      assert.deepEqual(second.region,{x:.35,y:.4,width:.24,height:.32});
      assert.equal(second.image_id,'48607-image-2');
    }
  }
});

test('handoff ZIP preserves original JPEG bytes, V1/V2 histories and all SHA-256 manifests',async()=>{
  for (const pack of cases) {
    const state=applySupplement(pack,createState(pack,fixedTime),pack.supplements[0].id,fixedTime);
    const {entries}=await buildBundleEntries(pack,state,load,skills,fixedTime);
    const result=JSON.parse(execFileSync('python3',['-c',String.raw`
import io,json,zipfile,hashlib,sys
z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()));assert z.testzip() is None
m=json.loads(z.read('manifest.json'));r=json.loads(z.read('report.json'))
assert r['ai_inference_performed'] is False and m['ai_inference_performed'] is False
assert len(r['teaching_opinion_versions'])==2
assert r['teaching_opinion_versions'][0]['current'] is False
assert r['teaching_opinion_versions'][1]['activated'] is True
assert [f['text'] for f in r['history'][0]['snapshot']['curated_research_examples']] != [f['text'] for f in r['history'][-1]['snapshot']['curated_research_examples']]
for image in r['images']:
 path='images/'+image['file'].rsplit('/',1)[-1]
 assert hashlib.sha256(z.read(path)).hexdigest()==image['sha256']
for item in m['files']:
 raw=z.read(item['path']);assert len(raw)==item['bytes'];assert hashlib.sha256(raw).hexdigest()==item['sha256']
assert set(z.namelist())==set(f['path'] for f in m['files'])|{'manifest.json'}
assert 'V1 / V2' in z.read('report.html').decode()
print(json.dumps({'case_id':r['case_id'],'files':len(z.namelist())}))
`],{input:makeZip(entries),encoding:'utf8'}));
    assert.equal(result.case_id,pack.id); assert.ok(result.files>=20);
  }
});
