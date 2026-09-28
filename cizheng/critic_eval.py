"""Approved-text critic pilot derived from a skills trial. This is NOT a new A/B arm."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from . import schemas as S
from .agent import Engine, LocalModel
from .review_client import prepare_review, suggested_packet, ReviewService, StepFunClient
from .store import Store, uid, Problem


def prepare(source,output):
    source=Path(source);output=Path(output)
    if output.exists():raise ValueError('输出目录已存在，不能覆盖旧试验。')
    if not (source/'cizheng.sqlite3').is_file():raise ValueError('必须提供真实 skills 试验数据库目录。')
    with sqlite3.connect(f'file:{(source/"cizheng.sqlite3").resolve()}?mode=ro',uri=True) as db:
        rows=db.execute("SELECT data FROM records WHERE kind='case'").fetchall()
        if len(rows)!=1:raise ValueError('只允许独立单案试验库，不能复制日常工作库。')
        case=json.loads(rows[0][0])
        runs=[json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='run'")]
        if any(r['state'] in ('queued','running') for r in runs):raise ValueError('来源试验仍在运行。')
        run=next((r for r in runs if r['id']==case['current_run_id']),None)
        if not run or run['mode']!='skills' or run['state'] not in ('ready','waiting_evidence'):
            raise ValueError('来源必须已有真实完成的 skills 意见。')
        output.mkdir(parents=True)
        with sqlite3.connect(output/'cizheng.sqlite3') as target:db.backup(target)
    store=Store(output);draft=suggested_packet(store,case['id']);draft.pop('notice')
    draft.update(request_id=uid('approve'),expected_case_revision=case['revision'],permission='',approval_basis='')
    (output/'text-packet-draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2))
    info={'state':'awaiting_text_approval','case_id':case['id'],'baseline_run_id':run['id'],
        'baseline_input_hash':run['input_hash'],'source_database_sha256':hashlib.sha256((source/'cizheng.sqlite3').read_bytes()).hexdigest(),
        'design':'derived skills+critic pilot; inherits the initial skills result; NOT independent three-arm benchmark',
        'privacy':'inspect draft, remove private text, set permission and approval_basis before --run',
        'baseline_episode':store.read('episode',case['episode_id']),'model_calls_now':0}
    (output/'pilot-summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2));return info


async def execute(output,packet_path,model=None,client=None):
    output=Path(output);info=json.loads((output/'pilot-summary.json').read_text())
    if info['state']!='awaiting_text_approval':raise ValueError('本次试验已尝试执行；保留失败，不自动重试。')
    model=model or LocalModel();client=client or StepFunClient()
    if not model.configured or not client.configured:raise ValueError('本地视觉模型和 StepFun 文字服务必须同时配置。')
    body=S.ReviewPacketIn.model_validate_json(Path(packet_path).read_text()).model_dump()
    store=Store(output);case=store.read('case',info['case_id'])
    if body['assessment_run_id']!=info['baseline_run_id']:raise ValueError('批准包不对应固定的 skills 基线。')
    packet=prepare_review(store,case['id'],body)
    info.update(state='running',packet_hash=packet['packet_hash'],approval_file_sha256=hashlib.sha256(Path(packet_path).read_bytes()).hexdigest())
    (output/'pilot-summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    start=time.perf_counter()
    rid=None;reviewed=None;failure=None;stage='text_review'
    try:
        reviewed=await ReviewService(store,client).execute(packet['id'],{'request_id':uid('send'),'packet_hash':packet['packet_hash']})
        if reviewed['state']=='succeeded':
            stage='revision_prepare'
            case=store.add_correction(case['id'],{'request_id':uid('correction'),'expected_case_revision':case['revision'],
                'assessment_run_id':info['baseline_run_id'],'review_method':'image',
                'correction':'纳入已批准的文字反证审查，主 Agent 重新看图并逐项回应。',
                'basis':'文字审查 '+reviewed['id']+'；没有查看原图，不是专家结论。'},'试验操作者（身份未认证）')
            engine=Engine(store,model)
            rid=store.start_run(case['id'],{'request_id':uid('run'),'expected_case_revision':case['revision'],'mode':'skills'},engine.versions())['run_id']
            stage='revision_run'
            await engine.execute(rid)
    except Exception as exc:
        # Retain paid review and actual episode cost even if local revision setup fails.
        failure=exc.message if isinstance(exc,Problem) else '试验阶段失败：'+type(exc).__name__
    run=store.read('run',rid) if rid else None;episode=store.read('episode',case['episode_id'])
    info.update(state='completed' if not failure and run and run['state'] in ('ready','waiting_evidence') else 'failed',
        critic_state=reviewed['state'] if reviewed else store.read('text_review',packet['id'])['state'],
        revision_run_id=rid,revision_state=run['state'] if run else None,
        critic_error=reviewed.get('error') if reviewed else None,revision_error=run.get('error') if run else failure,
        failure_stage=stage if failure else None,pilot_error=failure,
        elapsed_incremental_seconds=round(time.perf_counter()-start,4),final_episode=episode,
        incremental_model_calls=episode['model_calls']-info['baseline_episode']['model_calls'],
        total_model_calls_including_initial_skills=episode['model_calls'],
        professional_gain='requires_blind_expert_review; not automatically measured')
    (output/'pilot-summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    (output/'expert-review-packet.json').write_text(json.dumps({'scope':'blind expert comparison of baseline and revision',
        'old_assessment':store.read('run',info['baseline_run_id'])['assessment'],
        'new_assessment':run.get('assessment') if run else None,'new_observations':run.get('observations') if run else [],
        'state':info['state'],'notice':'Images remain in local DB; IDs, not a standalone image-complete blind packet.'},ensure_ascii=False,indent=2))
    return info


def main():
    p=argparse.ArgumentParser(description='批准文字反证试验；准备阶段只复制独立单案本地数据库，不发送数据')
    p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--packet',type=Path);p.add_argument('--run',action='store_true');a=p.parse_args()
    try:
        if a.run:
            if not a.packet:raise ValueError('--run 须提供已审阅并填写许可的 --packet 文件')
            info=asyncio.run(execute(a.output,a.packet))
        else:
            if not a.source:raise ValueError('准备阶段须提供 --source 独立 skills 试验目录')
            info=prepare(a.source,a.output)
    except (ValueError,OSError,KeyError,Problem) as exc:p.exit(2,str(exc)+'\n')
    print(info['state'])


if __name__=='__main__':main()
