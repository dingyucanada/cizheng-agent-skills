"""Corruption failures must reject reports before decoding; synthetic only."""
import base64
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from cizheng.api import create_app
from cizheng.store import uid


@pytest.mark.parametrize('route', ['dossier', 'handoff'])
@pytest.mark.parametrize('corruption', ['bytes', 'valid_different_pixels', 'mime', 'missing'])
def test_original_integrity_rejected_before_report_decode(tmp_path, route, corruption, monkeypatch):
    monkeypatch.delenv('CIZHENG_MODEL_URL',raising=False)
    monkeypatch.delenv('CIZHENG_MODEL',raising=False)
    app=create_app(tmp_path)
    with TestClient(app,raise_server_exceptions=False) as client:
        headers={'X-Cizheng-Token':client.get('/api/status').json()['session_token']}
        case=client.post('/api/cases',headers=headers,json={'request_id':uid('req'),
            'title':'Synthetic corruption protocol','question':'Engineering only'}).json()
        buffer=io.BytesIO();Image.new('RGB',(50,50),'blue').save(buffer,format='PNG')
        response=client.post('/api/cases/'+case['id']+'/evidence',headers=headers,json={
            'request_id':uid('req'),'expected_case_revision':1,'filename':'protocol.png',
            'image_base64':base64.b64encode(buffer.getvalue()).decode(),'view':'synthetic','edit_declaration':'test'})
        assert response.status_code==200,response.text
        case=response.json()['case']; identifier=case['media'][0]['id']
        with app.state.store.tx() as db:
            if corruption=='bytes':db.execute('UPDATE blobs SET bytes=? WHERE id=?',(b'corrupted image',identifier))
            elif corruption=='valid_different_pixels':
                changed=io.BytesIO();Image.new('RGB',(50,50),'red').save(changed,format='PNG')
                db.execute('UPDATE blobs SET bytes=? WHERE id=?',(changed.getvalue(),identifier))
            elif corruption=='mime':db.execute('UPDATE blobs SET mime=? WHERE id=?',('image/jpeg',identifier))
            else:db.execute('DELETE FROM blobs WHERE id=?',(identifier,))
            count=db.execute('SELECT count(*) FROM blobs').fetchone()[0]
        response=client.post('/api/cases/'+case['id']+'/'+route,headers=headers,json={
            'request_id':uid('req'),'expected_case_revision':case['revision']})
        assert response.status_code==409,response.text
        assert '原文件' in response.json()['detail']
        with app.state.store.tx() as db:assert db.execute('SELECT count(*) FROM blobs').fetchone()[0]==count
        assert app.state.store.read('case',case['id'])['revision']==case['revision']
