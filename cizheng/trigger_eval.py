"""Description-only natural routing test, separate from mandatory workflow validation."""
import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from .agent import LocalModel, parse_json, ROOT
from .skill_runtime import SkillRuntime

SYSTEM='''你是技能目录路由器。只根据用户任务、提供的上下文和技能描述判断本轮应发现/加载哪些技能。
不执行任务，不伪装看图，不读取技能正文。只返回JSON {"selected_skills":["技能名"],"reason":"简短适用理由"}。
无适用技能返回空列表；修订任务必须有已存在父意见的上下文，不强制每个任务加载技能。'''


def contexts(item):
    # Declared test context, not hidden answer labels and not a visual assessment.
    revision=item['id'] in ('trigger-03','trigger-04','trigger-19')
    return {'images_available':item['requires_real_images'],'prior_assessment_available':revision,
            'new_evidence_or_correction':revision,'scope':'routing only; no image observations provided'}


async def evaluate(cases,model):
    if not model.configured:raise ValueError('模型未配置；自然触发评测未执行。')
    catalog=SkillRuntime(ROOT/'skills').catalog()
    descriptions=[{k:s[k] for k in ('name','description','compatibility')} for s in catalog.values()]
    result={'scope':'description-only routing; excludes workflow enforcement, visual ability and expertise',
        'model':model.identity(),'system_hash':hashlib.sha256(SYSTEM.encode()).hexdigest(),
        'skill_bundle_hashes':{n:s['sha256'] for n,s in catalog.items()},'expected_labels_in_model_input':False,
        'trials':[],'exact_matches':0,'failed_trials':0,'human_review_required':True}
    for item in cases:
        payload={'task':item['prompt'],'context':contexts(item),'catalog':descriptions}
        start=time.perf_counter();usage={};selected=[];error=None
        try:
            raw,usage=await model.complete([{'role':'system','content':SYSTEM},
                {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],60)
            value=parse_json(raw)
            if set(value)!={'selected_skills','reason'} or not isinstance(value['selected_skills'],list) or not isinstance(value['reason'],str):
                raise ValueError('无效路由结构')
            selected=value['selected_skills']
            if any(not isinstance(n,str) or n not in catalog for n in selected) or len(selected)!=len(set(selected)):
                raise ValueError('未知或重复技能')
        except Exception as exc:
            usage=getattr(exc,'usage',usage);raw=None;error=type(exc).__name__
        exact=error is None and set(selected)==set(item['expected_skills'])
        result['exact_matches']+=int(exact);result['failed_trials']+=int(error is not None)
        result['trials'].append({'id':item['id'],'task':item['prompt'],'context':contexts(item),
            'selected':selected,'expected':item['expected_skills'],'exact_match':exact,'error':error,
            'response':raw,'seconds':round(time.perf_counter()-start,4),'usage':usage})
    result['denominator']=len(cases);return result


def main():
    p=argparse.ArgumentParser(description='自然触发20例，默认只校验目录和输入，不调用模型')
    p.add_argument('--cases',type=Path,default=ROOT/'evals/trigger-cases.json');p.add_argument('--output',required=True,type=Path)
    p.add_argument('--run',action='store_true');a=p.parse_args()
    try:
        cases=json.loads(a.cases.read_text())['cases'];catalog=SkillRuntime(ROOT/'skills').catalog()
        if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('触发用例不能为空或重复')
        for c in cases:
            if not set(c['expected_skills'])<=set(catalog):raise ValueError('预期技能不存在')
        value=asyncio.run(evaluate(cases,LocalModel())) if a.run else {
            'state':'prepared_not_run','case_count':len(cases),'model_calls':0,'expected_labels_in_model_input':False,
            'scope':'description-only routing; not workflow success or ceramic accuracy'}
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    except (ValueError,OSError,KeyError,TypeError) as exc:p.exit(2,str(exc)+'\n')
    print('自然触发准备完成；只有 --run 才调用模型。')


if __name__=='__main__':main()
