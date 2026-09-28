import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {entryCaseID, caseURL} from '../site/entry.js';

const ids=['met-48607','met-51185','met-50839'];
test('each homepage scenario URL opens its selected dossier and refresh preserves the choice', async () => {
  const html=await readFile(new URL('../site/index.html',import.meta.url),'utf8');
  for (const id of ids) {
    assert.ok(html.includes(`href="demo.html?case=${id}"`));
    const entry=new URL(`demo.html?case=${id}`,'https://example.github.io/cizheng-agent-skills/');
    assert.equal(entryCaseID(entry.href,ids),id);
    const canonical=caseURL(entry.href,id);
    assert.ok(!canonical.includes('?case='));
    assert.equal(entryCaseID(new URL(canonical,entry).href,ids),id);
  }
  assert.equal(entryCaseID('https://example.test/demo.html?case=unknown#invalid',ids),null);
  assert.equal(entryCaseID('https://example.test/demo.html?case=met-48607#met-51185',ids),'met-51185');
  assert.equal(entryCaseID('https://example.test/demo.html?case=met-50839#%E0%A4%A',ids),'met-50839');
  const js=await readFile(new URL('../site/demo.js',import.meta.url),'utf8');
  assert.ok(js.includes('entryCaseID(location.href, cases.map(c=>c.id))'));
  assert.ok(html.includes('#本地专业工作台'));
});
