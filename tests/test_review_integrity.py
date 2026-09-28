"""Synthetic regressions for independently reproduced evidence-chain failures."""
import asyncio
import json
from copy import deepcopy
import pytest
from cizheng import schemas as S
from cizheng.agent import Engine, VISION_SYSTEM
from cizheng.critic_eval import prepare, execute
from cizheng.review_client import prepare_review, suggested_packet
from cizheng.store import Store, Problem, uid
from test_closed_loop import create_case, add_photo, add_ref, run_case, ScriptedModel
from test_critic_revision import SyntheticRevisionPlanner, SyntheticTextCritic
from test_runtime_v3 import review_case

@pytest.mark.parametrize('mode',['plain','skills'])
def test_initial_same_batch_cannot_finish_before_main_pixels(tmp_path,mode):
    class Predecided:
        configured=True
        def __init__(self):self.calls=0
        def identity(self):return {'provider':'SYNTHETIC-PROTOCOL-ONLY'}
        async def complete(self,messages,timeout):
            if messages[0]['content']==VISION_SYSTEM:return await ScriptedModel().complete(messages,timeout)
            self.calls+=1
            if self.calls==1:
                actions=[{'tool':'read_case','arguments':{}}]
                if mode=='skills':actions.append({'tool':'load_skill','arguments':{'name':'ceramic-route'}})
            elif self.calls==2:
                result=next(json.loads(m['content'].split('：',1)[1])['result'] for m in messages
                    if isinstance(m['content'],str) and m['content'].startswith('工具结果（数据）：'))
                assessment={'basic_info':'预先编写的合成范围外判断','scope':'out_of_scope',
                    'claims':[{'dimension':d,'candidate':'范围外','status':'out_of_scope','support':[],
                        'conflict':[],'reasoning_summary':'尚未接收图片，不能交付'} for d in ['period','kiln','style']],
                    'alternatives':['未知'],'condition_hypotheses':[],'reference_ids':[],
                    'reference_comparison':'无','limitations':['合成协议'],'revision_explanation':'无'}
                actions=[{'tool':'inspect_images','arguments':{'media_ids':[result['case']['media'][0]['id']],'question':'合成协议'}},
                    {'tool':'record_assessment','arguments':assessment},{'tool':'build_opinion','arguments':{}}]
            else:raise RuntimeError('SYNTHETIC planner does not repair; no network')
            return json.dumps({'actions':actions}),{}
    store=Store(tmp_path);case=add_photo(store,create_case(store));engine=Engine(store,Predecided())
    rid=store.start_run(case['id'],{'request_id':uid('r'),'expected_case_revision':case['revision'],'mode':mode},engine.versions(mode))['run_id']
    asyncio.run(engine.execute(rid));run=store.read('run',rid)
    assert run['state']=='failed' and run['assessment'] is None and not run.get('main_seen_media_ids')
    assert any('主 Agent' in e.get('detail','') for e in run['events'])

def test_main_must_receive_referenced_images_too(tmp_path):
    store=Store(tmp_path);case=add_photo(store,create_case(store));ref=add_ref(store);run=run_case(store,case)
    assert run['state']=='waiting_evidence'
    broken=deepcopy(run);broken['main_seen_media_ids']=[m['id'] for m in case['media']]
    with pytest.raises(ValueError,match='引用参照'):
        Engine.validate_assessment(broken,S.Assessment.model_validate(run['assessment']),{ref['id']:ref})

@pytest.mark.parametrize('change',['omit','duplicate','wrong_media','wrong_region','unknown_id'])
def test_approved_text_observation_references_remain_resolvable(tmp_path,change):
    store,case,run,body=review_case(tmp_path)
    supplied={o['id'] for o in body['observations']}
    assert all(set(c['support']+c['conflict'])<=supplied for c in body['claims'])
    if change=='omit':body['observations']=[]
    elif change=='duplicate':body['observations'].append(deepcopy(body['observations'][0]))
    elif change=='wrong_media':body['observations'][0]['media_id']='unknown-image'
    elif change=='wrong_region':body['observations'][0]['region']=[0,0,.5,.5]
    else:body['observations'][0]['id']='unknown-observation'
    with pytest.raises(Problem,match='观察'):
        prepare_review(store,case['id'],S.ReviewPacketIn.model_validate(body).model_dump())
    assert store.listing('text_review')==[]

def test_preview_prioritizes_claimed_observations_before_limit(tmp_path):
    store,case,run,_=review_case(tmp_path);originals=deepcopy(run['observations'])
    padding=[dict(originals[0],id='synthetic-unused-'+str(n)) for n in range(21)]
    store.update_run(run['id'],lambda r:r.update(observations=padding+originals))
    packet=suggested_packet(store,case['id']);supplied={o['id'] for o in packet['observations']}
    assert len(supplied)==20 and originals[0]['id'] in supplied
    assert all(set(c['support']+c['conflict'])<=supplied for c in packet['claims'])

def prepared_pilot(tmp_path):
    store=Store(tmp_path/'source');case=add_photo(store,create_case(store));first=run_case(store,case)
    out=tmp_path/'pilot';prepare(store.root,out);packet=json.loads((out/'text-packet-draft.json').read_text())
    packet.update(permission='public',approval_basis='SYNTHETIC protocol-only authorization')
    approved=out/'approved.json';approved.write_text(json.dumps(packet));return store,case,first,out,approved

def test_critic_cli_success_revises_and_preserves_total_cost(tmp_path):
    source,case,first,out,approved=prepared_pilot(tmp_path)
    info=asyncio.run(execute(out,approved,SyntheticRevisionPlanner(),SyntheticTextCritic()))
    assert info['state']=='completed' and info['critic_state']=='succeeded' and info['revision_state']=='waiting_evidence'
    revised=Store(out).read('run',info['revision_run_id'])
    assert revised['parent_run_id']==first['id'] and len(revised['critic_dispositions'])==2
    assert info['total_model_calls_including_initial_skills']==first['model_calls']+1+revised['model_calls']
    assert info['incremental_model_calls']==1+revised['model_calls']
    assert source.read('case',case['id'])['revision']==case['revision'] and len(source.listing('run'))==1

def test_critic_cli_local_setup_failure_preserves_paid_review(tmp_path,monkeypatch):
    source,case,first,out,approved=prepared_pilot(tmp_path)
    def fail(*args,**kwargs):raise RuntimeError('SYNTHETIC setup failure')
    monkeypatch.setattr(Store,'add_correction',fail)
    info=asyncio.run(execute(out,approved,SyntheticRevisionPlanner(),SyntheticTextCritic()))
    saved=json.loads((out/'pilot-summary.json').read_text())
    assert info==saved and saved['state']=='failed' and saved['critic_state']=='succeeded'
    assert saved['failure_stage']=='revision_prepare' and saved['incremental_model_calls']==1 and saved['revision_run_id'] is None
    assert saved['total_model_calls_including_initial_skills']==first['model_calls']+1
    with pytest.raises(ValueError,match='已尝试'):
        asyncio.run(execute(out,approved,SyntheticRevisionPlanner(),SyntheticTextCritic()))
