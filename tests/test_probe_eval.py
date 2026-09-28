import asyncio
import json
import pytest
from cizheng.model_probe import probe
from cizheng.trigger_eval import evaluate
from cizheng.agent import LocalModel, LocalModelFailure
from cizheng.critic_eval import prepare as critic_prepare, execute as critic_execute
from test_closed_loop import ScriptedModel, create_case, add_photo, run_case
from test_runtime_v3 import CriticFixture
from cizheng.store import Store


class ProbeFixture:
    configured=True
    def __init__(self):self.calls=0
    def identity(self):return {'provider':'SYNTHETIC-TEST-ONLY'}
    async def complete(self,messages,timeout):
        self.calls+=1
        values=[{'actions':[{'tool':'read_case','arguments':{}}]},{'color':'red'},{'colors':['red','blue']}]
        return json.dumps(values[self.calls-1]),{'total_tokens':7}


def test_real_probe_protocol_and_failure_inclusion():
    model=ProbeFixture();result=asyncio.run(probe(model))
    assert result['passed'] and model.calls==3 and result['ceramic_accuracy']=='not_measured'
    assert [t['image_count'] for t in result['checks']]==[0,1,2]
    with pytest.raises(ValueError,match='尚未配置'):asyncio.run(probe(LocalModel('','')))


def test_natural_routing_never_sends_expected_labels():
    class Routing:
        configured=True
        def identity(self):return {'provider':'SYNTHETIC-TEST-ONLY'}
        async def complete(self,messages,timeout):
            value=json.loads(messages[1]['content'])
            assert 'expected_skills' not in value and 'expected' not in value
            assert all('text' not in s for s in value['catalog'])
            return json.dumps({'selected_skills':[],'reason':'合成协议近邻负例'}),{}
    result=asyncio.run(evaluate([{'id':'trigger-06','prompt':'装修色彩方案','expected_skills':[], 'requires_real_images':False}],Routing()))
    assert result['exact_matches']==1 and result['expected_labels_in_model_input'] is False


def test_local_failure_retains_usage_and_generation_configuration(monkeypatch):
    import httpx
    monkeypatch.setenv('CIZHENG_DISABLE_THINKING','1');original=httpx.AsyncClient
    def response(request):
        assert json.loads(request.content)['chat_template_kwargs']=={'enable_thinking':False}
        return httpx.Response(200,json={'choices':[{'message':{'content':None}}],'usage':{'total_tokens':41}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(response),**kwargs))
    model=LocalModel('http://127.0.0.1:8000/v1','test')
    assert model.identity()['generation']['disable_thinking'] is True
    with pytest.raises(LocalModelFailure) as info:asyncio.run(model.complete([{'role':'user','content':'test'}],3))
    assert info.value.usage['total_tokens']==41


def test_critic_pilot_is_a_private_derived_copy_and_no_prepare_calls(tmp_path):
    store=Store(tmp_path/'source');case=add_photo(store,create_case(store));run_case(store,case,ScriptedModel())
    out=tmp_path/'pilot';info=critic_prepare(store.root,out)
    assert info['state']=='awaiting_text_approval' and info['model_calls_now']==0
    draft=json.loads((out/'text-packet-draft.json').read_text());assert draft['permission']==''
    assert Store(out).read('case',case['id'])['id']==case['id']
    with pytest.raises(ValueError,match='同时配置'):
        asyncio.run(critic_execute(out,out/'text-packet-draft.json',LocalModel('',''),CriticFixture()))
    assert json.loads((out/'pilot-summary.json').read_text())['state']=='awaiting_text_approval'
    with pytest.raises(ValueError,match='已存在'):critic_prepare(store.root,out)
