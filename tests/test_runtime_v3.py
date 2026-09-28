"""Local software contracts only. Synthetic pixels are not a ceramic benchmark."""
import asyncio
import base64
import io
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cizheng import schemas as S
from cizheng.agent import Engine, VISION_SYSTEM
from cizheng.api import create_app
from cizheng.review_client import ReviewService, StepFunClient, prepare_review, suggested_packet
from cizheng.skill_runtime import SkillRuntime
from cizheng.store import Problem, Store, uid
from cizheng.visual_tools import derivative, region_to_display
from test_closed_loop import ScriptedModel, add_photo, add_ref, create_case, run_case


def skill_dir(tmp_path, metadata=''):
    root=tmp_path/'skills'; directory=root/'example-skill'; directory.mkdir(parents=True)
    (directory/'SKILL.md').write_text('---\nname: example-skill\ndescription: >-\n  First line\n  second line.\n'+metadata+'---\nRead references/method.md when needed.\n')
    (directory/'references').mkdir();(directory/'references/method.md').write_text('Original method')
    return root, directory


def test_yaml_multiline_and_whole_bundle_versions(tmp_path):
    root, directory=skill_dir(tmp_path)
    runtime=SkillRuntime(root); first=runtime.catalog()['example-skill']
    assert first['description']=='First line second line.'
    assert runtime.read_resource('example-skill','references/method.md',first['sha256'])['text']=='Original method'
    (directory/'references/method.md').write_text('A different method')
    assert runtime.catalog()['example-skill']['sha256']!=first['sha256']
    with pytest.raises(ValueError,match='版本变化'):
        runtime.read_resource('example-skill','references/method.md',first['sha256'])


@pytest.mark.parametrize('path',['../private.md','/etc/hosts','references/../../private.md','references\\method.md'])
def test_resource_paths_stay_in_manifest(tmp_path,path):
    root,_=skill_dir(tmp_path); runtime=SkillRuntime(root)
    with pytest.raises(ValueError):runtime.read_resource('example-skill',path,runtime.catalog()['example-skill']['sha256'])


@pytest.mark.parametrize('metadata',['metadata: null\n','metadata: [one]\n','metadata:\n  version: 3\n'])
def test_invalid_metadata_is_diagnosed(tmp_path,metadata):
    root,_=skill_dir(tmp_path,metadata)
    with pytest.raises(ValueError,match='metadata'):SkillRuntime(root).catalog()


def test_resource_bytes_are_checked_after_scan(tmp_path,monkeypatch):
    root,directory=skill_dir(tmp_path); runtime=SkillRuntime(root); old=runtime.catalog()
    def raced_scan():
        (directory/'references/method.md').write_text('Changed during read')
        return old
    monkeypatch.setattr(runtime,'catalog',raced_scan)
    with pytest.raises(ValueError,match='读取期间版本变化'):
        runtime.read_resource('example-skill','references/method.md',old['example-skill']['sha256'])


def test_symlink_resources_are_not_loaded(tmp_path):
    root,directory=skill_dir(tmp_path); external=tmp_path/'external';external.write_text('outside')
    (directory/'references/link.md').symlink_to(external)
    with pytest.raises(ValueError,match='符号链接'):SkillRuntime(root).catalog()


@pytest.mark.parametrize('orientation',[1,2,3,4,5,6,7,8])
def test_exif_mapping_and_region_keeps_original(orientation):
    im=Image.new('RGB',(80,120),'white');exif=im.getexif();exif[274]=orientation
    stream=io.BytesIO();im.save(stream,format='JPEG',exif=exif)
    raw=stream.getvalue();data,meta=derivative(raw,'test',[.25,.25,.75,.75])
    assert meta['display_width']==(120 if orientation>=5 else 80)
    assert meta['display_height']==(80 if orientation>=5 else 120)
    assert meta['display_region']==[.25,.25,.75,.75]
    assert meta['original_width']==80 and meta['original_height']==120
    assert raw==stream.getvalue() and data!=raw
    a,b,c,d,e,f=meta['display_to_file_normalized']
    assert 0<=a*.3+b*.7+c<=1 and 0<=d*.3+e*.7+f<=1
    assert region_to_display([0,0,1,1],meta['display_region'])==meta['display_region']


def active_run(store):
    case=add_photo(store,create_case(store)); engine=Engine(store,ScriptedModel())
    rid=store.start_run(case['id'],{'request_id':uid('req'),'expected_case_revision':case['revision'],'mode':'skills'},engine.versions())['run_id']
    store.update_run(rid,lambda r:r.update(state='running',started_at=time.time()))
    return case,engine,rid


def test_region_observation_uses_display_coordinates(tmp_path):
    store=Store(tmp_path);case,engine,rid=active_run(store)
    result=asyncio.run(engine.tool(rid,'inspect_region',S.InspectRegion(media_id=case['media'][0]['id'],region=[.25,.25,.75,.75],question='SYNTHETIC PROTOCOL ONLY')))
    observation=result['observations'][0];assert observation['region']==[.25,.25,.75,.75]
    assert observation['coordinate_space']=='exif-corrected-original-normalized'
    assert store.blob(observation['artifact_id'])[0]=='image/jpeg'


def test_failed_vision_preserves_actual_input_provenance(tmp_path):
    class Broken(ScriptedModel):
        async def complete(self,messages,timeout):raise TimeoutError('SYNTHETIC failure')
    store=Store(tmp_path);case,engine,rid=active_run(store);engine.model=Broken()
    with pytest.raises(TimeoutError):
        asyncio.run(engine.tool(rid,'inspect_region',S.InspectRegion(media_id=case['media'][0]['id'],region=[.25,.25,.75,.75],question='test')))
    run=store.read('run',rid);assert len(run['derivatives'])==1
    assert any(e['type']=='vision_input' for e in run['events'])
    assert store.blob(run['derivatives'][0]['artifact_id'])[1]
    assert run['observations']==[] and run['model_calls']==1


def test_main_planner_gets_actual_pixels(tmp_path):
    class Capture(ScriptedModel):
        def __init__(self):self.main_image_calls=0
        async def complete(self,messages,timeout):
            if messages[0]['content']!=VISION_SYSTEM:
                self.main_image_calls+=int(any(isinstance(m['content'],list) and
                    any(p.get('type')=='image_url' for p in m['content']) for m in messages))
            return await super().complete(messages,timeout)
    store=Store(tmp_path);case=add_photo(store,create_case(store));model=Capture();run=run_case(store,case,model)
    assert run['state']=='waiting_evidence' and model.main_image_calls>0
    assert any(e.get('purpose')=='action' and e['image_count']>0 for e in run['events'] if e['type']=='model')


class CriticFixture:
    configured=True
    def __init__(self):self.calls=0;self.inputs=[]
    def identity(self):return {'provider':'SYNTHETIC-TEST-ONLY','model':'text-contract'}
    async def review(self,payload,timeout):
        self.calls+=1;self.inputs.append(payload)
        return {'issues':[{'claim_dimension':'general','concern':'合成测试，无真实研判','reference_ids':[]}],
                'suggested_evidence':'测试补证','limitations':['未查看原图，合成测试']},{'total_tokens':83}


def review_case(tmp_path):
    store=Store(tmp_path);case=add_photo(store,create_case(store));add_ref(store);run=run_case(store,case)
    case=store.read('case',case['id']);body=suggested_packet(store,case['id']);body.pop('notice')
    body.update(request_id=uid('req'),expected_case_revision=case['revision'],permission='public',approval_basis='SYNTHETIC public test')
    body=S.ReviewPacketIn.model_validate(body).model_dump()
    return store,case,run,body


def test_text_packet_once_budget_and_exact_field_whitelist(tmp_path):
    store,case,run,body=review_case(tmp_path);packet=prepare_review(store,case['id'],body)
    client=CriticFixture();service=ReviewService(store,client);request={'request_id':uid('req'),'packet_hash':packet['packet_hash']}
    result=asyncio.run(service.execute(packet['id'],request));assert result['state']=='succeeded'
    assert asyncio.run(service.execute(packet['id'],request))['id']==result['id'] and client.calls==1
    assert set(client.inputs[0])=={'question','claims','observations','references'}
    ep=store.read('episode',case['episode_id']);assert ep['model_calls']==run['model_calls']+1
    second=prepare_review(store,case['id'],dict(body,request_id=uid('req')))
    with pytest.raises(Problem,match='一次文字审查'):
        asyncio.run(service.execute(second['id'],dict(request,request_id=uid('req'))))


@pytest.mark.parametrize('bad',['data:image/png;base64,AAAA','/api/artifacts/media_private','https://example.org/private.jpg'])
def test_reject_encoded_or_accessible_image_text(tmp_path,bad):
    store,case,_,body=review_case(tmp_path);body['question']=bad
    with pytest.raises(Problem,match='图像|图片'):prepare_review(store,case['id'],body)
    assert store.listing('text_review')==[]


def test_external_cost_retained_on_invalid_response(tmp_path,monkeypatch):
    store,case,_,body=review_case(tmp_path);packet=prepare_review(store,case['id'],body)
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY','synthetic-test-key')
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':'invalid JSON'}}],'usage':{'total_tokens':83}}))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    service=ReviewService(store,StepFunClient())
    result=asyncio.run(service.execute(packet['id'],{'request_id':uid('req'),'packet_hash':packet['packet_hash']}))
    assert result['state']=='failed' and result['usage']['total_tokens']==83
    assert result['result'] is None


def test_stale_approved_packet_never_sent(tmp_path):
    store,case,_,body=review_case(tmp_path);packet=prepare_review(store,case['id'],body)
    add_photo(store,case,'red');client=CriticFixture()
    with pytest.raises(Problem,match='更新'):
        asyncio.run(ReviewService(store,client).execute(packet['id'],{'request_id':uid('req'),'packet_hash':packet['packet_hash']}))
    assert client.calls==0


def test_local_region_endpoint_no_inference_or_case_revision_change(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        headers={'X-Cizheng-Token':client.get('/api/status').json()['session_token']}
        case=add_photo(app.state.store,create_case(app.state.store))
        result=client.post('/api/cases/'+case['id']+'/regions',headers=headers,json={
            'request_id':uid('req'),'expected_case_revision':case['revision'],'media_id':case['media'][0]['id'],
            'region':[.25,.25,.75,.75]})
        assert result.status_code==200,result.text
        assert client.get('/api/artifacts/'+result.json()['artifact_id']).status_code==200
        assert app.state.store.read('case',case['id'])['revision']==case['revision']
        assert app.state.store.listing('run')==[]
        assert all(s['available'] for s in client.get('/api/skills').json())
