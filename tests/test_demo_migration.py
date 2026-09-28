"""Teaching import retains identity and operator edits across schema upgrade."""
import json
from cizheng.agent import ROOT
from cizheng.demo import import_professional_demos
from cizheng.schemas import NewCase
from cizheng.store import Store, uid


def test_teaching_import_reuses_pre_task_schema_request_without_overwriting(tmp_path):
    item=json.loads((ROOT/'examples/public-demo/professional-cases.json').read_text())['objects'][0]
    body=NewCase(request_id='professional-demo-'+item['object_id'],
        title='公开教学 · '+item['catalogue']['object_name'],workflow=item['workflow'],catalogue=item['catalogue'],
        question='整理公开图像与馆藏资料，明确观察范围、资料限制及下一项必要补证。',
        target_attribution='已知馆藏资料，仅作教学；不是独立鉴定结论',
        source_declaration='公开教学样例，非盲测、非真实委托。'+item['object_url']+
            '；原机构资料与本项目记录分别呈现，未取得实物。').model_dump(exclude={'research_task'})
    store=Store(tmp_path); old=store.create_case(body)
    store.update_catalogue(old['id'],{'request_id':uid('req'),'expected_case_revision':old['revision'],
        'workflow':'collection','catalogue':dict(old['catalogue'],dimensions='Operator synthetic change to keep')})
    first=import_professional_demos(tmp_path); second=import_professional_demos(tmp_path)
    assert first==second
    assert len(store.listing('case'))==3
    current=store.read('case',old['id'])
    assert current['catalogue']['dimensions']=='Operator synthetic change to keep'
    assert current['workflow']=='collection'
    assert current['knowledge_links']
    assert current['research_task']=='visual_research'
    assert all(case['model_calls']==0 and case['assessment'] is None for case in first['cases'])
