"""Material workplan and analysis preflight must agree on readable text."""
import pytest
from fastapi.testclient import TestClient
from cizheng.api import create_app
from cizheng.pro_workflow import preparation_bundle
from cizheng.store import Store
from test_documentary_audit import new_case, attach, kb, mutation


@pytest.mark.parametrize('material,ready', [('empty',False),('pdf',False),('txt',True),('knowledge',True)])
def test_workplan_readability_matches_preflight_and_preparation(tmp_path, material, ready):
    store=Store(tmp_path);case=new_case(store)
    if material in ('txt','pdf'):
        case,_=attach(store,case,suffix=material)
    elif material=='knowledge':
        _,source=kb(store,'SYNTHETIC current fixed source','本案许可正文，非专业结论。')
        case=store.link_document(case['id'],mutation(case)|{'document_id':source['document_id'],
            'document_revision':1,'document_sha256':source['document_sha256']})
    app=create_app(tmp_path)
    with TestClient(app) as client:
        preflight=client.get('/api/cases/'+case['id']+'/preflight').json()
        workplan=client.get('/api/cases/'+case['id']+'/workplan').json()
        document_task=next(t for t in workplan['tasks'] if t['id']=='documents')
        assert document_task['state']==('recorded' if ready else 'missing')
        assert (preflight['next_step']=='ready_for_analysis') is ready
        sources=app.state.knowledge.snapshot(bindings=case['knowledge_links'])['sources']
        preparation=preparation_bundle(case,sources)
        assert next(t for t in preparation['workplan']['tasks'] if t['id']=='documents')['state']==document_task['state']
