"""Real FastAPI handoff contracts using SYNTHETIC data and no model/network.

The imported workbench forbids production models, StepFun, external HTTP and
socket/download calls. ZIPs are downloaded from the local ASGI test client.
"""
import hashlib
import io
import json
import zipfile

from test_pro_workflow import (workbench, mutation, new_case, source_body,
    save_source, bind_source, revise_source, synthetic_photo)
from test_business_records import attachment, event


def attach_txt(client, headers, case, raw=b'SYNTHETIC original TXT\r\n'):
    response = client.post('/api/cases/'+case['id']+'/evidence-documents',
        headers=headers, json=attachment(case, raw))
    assert response.status_code == 201, response.text
    return response.json()['case'], response.json()['document']


def handoff(client, headers, case, body=None):
    response = client.post('/api/cases/'+case['id']+'/handoff', headers=headers,
                           json=body or mutation(case))
    assert response.status_code == 200, response.text
    result = response.json()
    download = client.get(result['artifacts'][0]['url'])
    assert download.status_code == 200, download.text
    assert download.headers['content-type'].startswith('application/zip')
    assert download.headers['content-disposition'].startswith('attachment;')
    assert hashlib.sha256(download.content).hexdigest() == result['archive_sha256']
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    assert archive.testzip() is None, 'Every ZIP member must pass its stored CRC'
    manifest = json.loads(archive.read('manifest.json'))
    assert set(archive.namelist()) == {row['path'] for row in manifest['files']} | {'manifest.json'}
    assert result['file_count'] == len(archive.namelist())
    for row in manifest['files']:
        raw = archive.read(row['path'])
        assert len(raw) == row['bytes']
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    return result, archive, manifest, download.content


def blob_count(store):
    with store.tx() as db:
        return db.execute('SELECT count(*) FROM blobs').fetchone()[0]


def test_handoff_crc_manifest_exact_originals_and_no_unrelated_private_kb(workbench):
    app, client, headers, scheduled = workbench
    case = synthetic_photo(client, headers, new_case(client, headers), number=31)
    raw_txt = '\ufeffSYNTHETIC 中文原件\r\n第二行。\n'.encode('utf-8')
    case, document = attach_txt(client, headers, case, raw_txt)
    linked = save_source(client, headers)
    case = bind_source(client, headers, case, linked)
    private = 'SYNTHETIC-UNRELATED-PRIVATE-KB-MUST-NOT-EXPORT'
    unrelated = save_source(client, headers, source_body(title='无关合成私有资料',
        source_url='https://example.invalid/private-unrelated', text=private))
    result, archive, manifest, raw_zip = handoff(client, headers, case)
    image = case['media'][0]
    assert archive.read('original-images/'+image['id']+'.png') == app.state.store.blob(image['id'])[1]
    assert archive.read('original-documents/'+document['artifact_id']+'.txt') == raw_txt
    assert manifest['bundle_sha256'] == result['bundle_sha256']
    assert manifest['model_inference_included'] is manifest['expert_reviewed'] is False
    contents = b'\n'.join(archive.read(path) for path in archive.namelist())
    assert private.encode() not in contents
    assert unrelated['document_id'].encode() not in contents
    assert 'knowledge/'+linked['document_id']+'-r1.json' in archive.namelist()
    assert not scheduled


def test_handoff_retains_cited_r1_paragraph_after_explicit_rebind_to_r2(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers, source_body(
        text='SYNTHETIC-R1-CITED\n\nSYNTHETIC-R1-UNCITED'))
    case = bind_source(client, headers, case, first)
    chunk = app.state.knowledge.source(first['document_id'], 1)['chunks'][0]
    evidence = {'kind':'knowledge', 'document_id':first['document_id'], 'revision':1,
        'chunk_id':chunk['chunk_id'], 'document_sha256':first['document_sha256'],
        'chunk_sha256':chunk['chunk_sha256'], 'locator':chunk['locator']}
    response = client.post('/api/cases/'+case['id']+'/provenance-events', headers=headers,
                           json=event(case, status='documented', evidence=[evidence]))
    assert response.status_code == 201, response.text
    case = response.json()['case']
    second = revise_source(client, headers, first, text='SYNTHETIC-R2-CURRENT')
    case = bind_source(client, headers, case, second)
    result, archive, manifest, raw = handoff(client, headers, case)
    r1 = json.loads(archive.read('knowledge/'+first['document_id']+'-r1.json'))
    r2 = json.loads(archive.read('knowledge/'+first['document_id']+'-r2.json'))
    assert r1['source']['document_sha256'] == first['document_sha256']
    assert r1['chunks'] == [chunk], 'Historical export must preserve only the actual cited paragraph'
    assert r1['history_scope']
    assert r2['source']['document_sha256'] == second['document_sha256']
    assert r2['chunks'][0]['text'] == 'SYNTHETIC-R2-CURRENT'
    bundle = json.loads(archive.read('preparation.json'))
    assert bundle['case']['knowledge_links'][0]['document_revision'] == 2
    assert bundle['case']['provenance_events'][0]['evidence'][0]['revision'] == 1
    assert not scheduled


def test_handoff_refuses_tampered_attachment_blob_without_creating_artifact(workbench):
    app, client, headers, scheduled = workbench
    case, document = attach_txt(client, headers, new_case(client, headers))
    with app.state.store.tx() as db:
        db.execute('UPDATE blobs SET bytes=? WHERE id=?', (b'SYNTHETIC tampered bytes', document['artifact_id']))
    before = blob_count(app.state.store)
    response = client.post('/api/cases/'+case['id']+'/handoff', headers=headers, json=mutation(case))
    assert response.status_code == 409, response.text
    assert blob_count(app.state.store) == before
    assert client.get('/api/cases/'+case['id']).json()['case']['revision'] == case['revision']
    assert not scheduled


def test_handoff_size_limit_returns_413_without_artifact_or_blob_write(workbench, monkeypatch):
    import cizheng.handoff as module
    app, client, headers, scheduled = workbench
    case, document = attach_txt(client, headers, new_case(client, headers))
    before = blob_count(app.state.store)
    monkeypatch.setattr(module, 'MAX_HANDOFF_BYTES', 100)
    response = client.post('/api/cases/'+case['id']+'/handoff', headers=headers, json=mutation(case))
    assert response.status_code == 413, response.text
    assert blob_count(app.state.store) == before
    assert client.get('/api/cases/'+case['id']).json()['case']['revision'] == case['revision']
    assert not scheduled


def test_handoff_archive_sha_stable_when_live_kb_head_changes_without_rebind(workbench):
    app, client, headers, scheduled = workbench
    case = new_case(client, headers)
    first = save_source(client, headers)
    case = bind_source(client, headers, case, first)
    before, before_zip, _, before_raw = handoff(client, headers, case)
    second = revise_source(client, headers, first)
    assert second['revision'] == 2
    current = client.get('/api/cases/'+case['id']).json()['case']
    after, after_zip, _, after_raw = handoff(client, headers, current)
    assert before['archive_sha256'] == after['archive_sha256']
    assert before['bundle_sha256'] == after['bundle_sha256']
    assert before_raw == after_raw
    assert json.loads(after_zip.read('knowledge/'+first['document_id']+'-r1.json'))['source']['revision'] == 1
    assert 'knowledge/'+first['document_id']+'-r2.json' not in after_zip.namelist()
    assert not scheduled


def test_handoff_stale_revision_request_conflict_and_exact_replay(workbench):
    app, client, headers, scheduled = workbench
    stale_case = new_case(client, headers)
    case, _ = attach_txt(client, headers, stale_case)
    stale = client.post('/api/cases/'+case['id']+'/handoff', headers=headers, json=mutation(stale_case))
    assert stale.status_code == 409, stale.text
    body = mutation(case)
    result, archive, manifest, raw = handoff(client, headers, case, body)
    before = blob_count(app.state.store)
    replay = client.post('/api/cases/'+case['id']+'/handoff', headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == result
    assert blob_count(app.state.store) == before
    conflict = client.post('/api/cases/'+case['id']+'/handoff', headers=headers,
                           json=body | {'expected_case_revision':case['revision']+1})
    assert conflict.status_code == 409, conflict.text
    assert blob_count(app.state.store) == before
    assert not scheduled
