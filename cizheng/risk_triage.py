"""Evidence-bound review ordering; deterministic arithmetic, never authenticity probability."""
import hashlib
import re
import time
from typing import Literal
from fastapi import APIRouter
from pydantic import Field, model_validator
from .schemas import Revised, Strict, reject_uncalibrated_probability
from .store import Problem, uid, digest

VERSION = 'review-priority-v1'
DIMENSIONS = {'period': ('制作时期', 20), 'kiln': ('窑口归属', 15),
              'style': ('装饰风格', 15), 'provenance': ('来源对应', 20),
              'condition': ('状况与修复', 15), 'capture': ('采集完整性', 15)}
NEXT = {'period': '提供带出处的年代参照及原始底足照片；区分款识年代与制作年代。',
        'kiln': '提供胎釉、底足细节与可定位的窑址或研究资料。',
        'style': '提供纹饰局部及带编号、同部位的可比较标本。',
        'provenance': '补齐编号、尺寸、照片对应及来源凭据页码。',
        'condition': '补拍损伤与修复部位，登记实物检查方法及限制。',
        'capture': '补充原始整体、底足、口沿照片及处理声明；标签仍待核实。'}
NOTICE = '复核优先指数是固定规则的工作排序，不是真品率、AI图概率或专家置信度；证据内容与专业判断均未校准。'


class RiskEvidence(Strict):
    kind: Literal['media', 'annotation', 'attachment', 'provenance', 'condition']
    id: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    locator: str = Field(min_length=1, max_length=500)


class RiskCheckIn(Revised):
    dimension: Literal['period', 'kiln', 'style', 'provenance', 'condition', 'capture']
    state: Literal['consistent', 'conflicting', 'unknown']
    reason: str = Field(min_length=1, max_length=2000)
    next_evidence: str = Field(min_length=1, max_length=1000)
    evidence: list[RiskEvidence] = Field(default_factory=list, max_length=10)
    supersedes: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def grounded(self):
        if self.state != 'unknown' and not self.evidence:
            raise ValueError('一致或冲突记录必须绑定本案已保存凭据；未知不构成低风险证明')
        if len({(e.kind, e.id) for e in self.evidence}) != len(self.evidence):
            raise ValueError('同一证据不得重复计数')
        reject_uncalibrated_probability(self.reason + self.next_evidence)
        return self



class RiskFactIn(Revised):
    field: Literal['production_year', 'provenance_event_year', 'height_mm', 'object_identifier']
    value_min: float | None = Field(default=None, allow_inf_nan=False, ge=-10000, le=100000)
    value_max: float | None = Field(default=None, allow_inf_nan=False, ge=-10000, le=100000)
    identifier: str = Field(default='', max_length=200)
    namespace: str = Field(default='', max_length=100)
    statement: str = Field(min_length=1, max_length=1000)
    evidence: list[RiskEvidence] = Field(min_length=1, max_length=10)
    supersedes: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def typed_value(self):
        if self.field == 'object_identifier':
            if not self.identifier.strip() or not self.namespace.strip() or self.value_min is not None or self.value_max is not None:
                raise ValueError('器物编号需要编号体系与明确值，不接受数值区间')
        elif (self.value_min is None or self.value_max is None or self.value_min > self.value_max or
              self.identifier or self.namespace or (self.field == 'height_mm' and self.value_min <= 0)):
            raise ValueError('数值记载须提供有序区间；高度统一为mm，年代为年份')
        if len({(e.kind,e.id) for e in self.evidence}) != len(self.evidence):
            raise ValueError('事实依据不可重复')
        reject_uncalibrated_probability(self.statement)
        return self


def material_context(case):
    return digest({k: case.get(k) for k in ('research_task', 'catalogue', 'media', 'annotations',
        'provenance_events', 'condition_checks', 'evidence_documents', 'knowledge_links',
        'analysis_media_ids', 'risk_facts', 'reference_basis_hash')})


def obvious_conflicts(case):
    facts = case.get('risk_facts', [])
    replaced = {f.get('supersedes') for f in facts if f.get('supersedes')}
    facts = [f for f in facts if f['id'] not in replaced]
    alerts = []
    rule_totals={}
    def add_alert(value):
        rule=value['rule'];rule_totals[rule]=rule_totals.get(rule,0)+1
        if sum(a['rule']==rule for a in alerts)<10:
            alerts.append(value)
    # Only statements explicitly recorded as about this object, with exact pinned evidence.
    for i,a in enumerate(facts):
        for b in facts[i+1:]:
            if a['field'] != b['field']:
                continue
            field = a['field']
            different = ((a['namespace'].strip().casefold() == b['namespace'].strip().casefold() and
                          a['identifier'].strip().casefold() != b['identifier'].strip().casefold())
                         if field == 'object_identifier' else
                         max(a['value_min'],b['value_min']) > min(a['value_max'],b['value_max']))
            if different:
                dim = {'production_year':'period','height_mm':'capture','object_identifier':'provenance',
                       'provenance_event_year':'provenance'}[field]
                # Different provenance events may naturally happen at different dates.
                if field == 'provenance_event_year':
                    continue
                add_alert({'dimension':dim,'rule':'same_property_disjoint_'+field,
                    'reason':'同一器物的'+{'production_year':'制作年代区间','height_mm':'高度记录（mm）',
                    'object_identifier':'同一编号体系记录'}[field]+'互不相容；先核查单位、测法和器物对应。',
                    'fact_ids':[a['id'],b['id']], 'evidence':a['evidence']+b['evidence']})
    production = [f for f in facts if f['field']=='production_year']
    events = [f for f in facts if f['field']=='provenance_event_year']
    replaced_events={e.get('supersedes') for e in case.get('provenance_events',[]) if e.get('supersedes')}
    for e in case.get('provenance_events', []):
        if e['id'] in replaced_events:
            continue
        if e.get('status') == 'documented' and re.fullmatch(r'[0-9]{4}',e.get('date_text','')):
            events.append({'id':e['id'],'value_min':float(e['date_text']),'value_max':float(e['date_text']),
                           'evidence':[{'kind':'provenance','id':e['id'],'sha256':digest(e),'locator':e['date_text']}]})
    for a in production:
        for e in events:
            if e['value_max'] < a['value_min']:
                add_alert({'dimension':'provenance','rule':'event_precedes_declared_production',
                    'reason':f"来源事件最晚年份{e['value_max']:g}早于登记制作区间最早年份{a['value_min']:g}；检查是不是另一件器物或错误日期。",
                    'fact_ids':[a['id'],e['id']],'evidence':a['evidence']+e['evidence']})
    return alerts,rule_totals


def evidence_choices(case):
    out = []
    for media in case['media']:
        out.append({'kind': 'media', 'id': media['id'], 'sha256': media['sha256'],
                    'label': media.get('view') or media['filename']})
    for field, kind in [('annotations', 'annotation'), ('evidence_documents', 'attachment'),
                        ('provenance_events', 'provenance'), ('condition_checks', 'condition')]:
        for value in case.get(field, []):
            out.append({'kind': kind, 'id': value['id'],
                        'sha256': value['sha256'] if kind == 'attachment' else digest(value),
                        'label': str(value.get('filename') or value.get('observation') or
                                     value.get('description') or value.get('area') or value['id'])[:180]})
    return out


def validate_evidence(store, db, case, refs):
    available = {(e['kind'], e['id']): e for e in evidence_choices(case)}
    for ref in refs:
        saved = available.get((ref['kind'], ref['id']))
        if not saved or saved['sha256'] != ref['sha256']:
            raise Problem(422, '风险依据必须属于本案且匹配固定内容哈希')
        if ref['kind'] in ('media', 'attachment'):
            entry = next(v for v in case['media' if ref['kind'] == 'media' else 'evidence_documents']
                         if v['id'] == ref['id'])
            blob_id = entry['id'] if ref['kind'] == 'media' else entry['artifact_id']
            row = db.execute('SELECT bytes FROM blobs WHERE id=?', (blob_id,)).fetchone()
            if not row or hashlib.sha256(row[0]).hexdigest() != ref['sha256']:
                raise Problem(409, '风险依据原文件校验失败')


def calculate(rows):
    """Fixed 100-point denominator prevents dilution by extra checks/unknown dimensions."""
    if {r['dimension'] for r in rows} != set(DIMENSIONS) or len(rows) != len(DIMENSIONS):
        raise ValueError('必须恰有六个固定维度，未知维度不得进入分母')
    if any(r['state'] not in ('consistent', 'conflicting', 'unknown') for r in rows):
        raise ValueError('未知状态')
    conflicts = sum(DIMENSIONS[r['dimension']][1] for r in rows if r['state'] == 'conflicting')
    gaps = sum(DIMENSIONS[r['dimension']][1] for r in rows if r['state'] == 'unknown')
    evaluated = 100 - gaps
    return {'conflict_index': conflicts if evaluated else None,
            'review_priority_index': conflicts + gaps / 2,
            'coverage_weight': evaluated, 'denominator_weight': 100,
            'conflict_weight': conflicts, 'gap_weight': gaps,
            'formula': '冲突指数=100×冲突权重/100（覆盖为0则不出数值）；复核优先指数=100×(冲突权重+0.5×未知权重)/100；覆盖=已评价权重/100',
            'weights': {d: value[1] for d, value in DIMENSIONS.items()},
            'range': [0, 100], 'calibrated': False, 'probability': False}


def triage(store, case, run=None):
    choices = evidence_choices(case)
    rows = {d: {'dimension': d, 'label': label, 'weight': weight, 'state': 'unknown',
                'reasons': ['尚无本维度可回查的评价。'], 'evidence': [], 'origin': 'missing',
                'next_evidence': NEXT[d]} for d, (label, weight) in DIMENSIONS.items()}
    # A review-only registration advances the case revision, but does not change
    # the materials. Preserve a previously current report's exact material basis
    # in the case, without rewriting the historical model record. Material edits
    # or a different run invalidate this bridge.
    basis = case.get('risk_model_basis', {})
    same_materials = (run and basis.get('run_id') == run.get('id') and
                      basis.get('run_case_revision') == run.get('case_revision') and
                      basis.get('bridge_case_revision') == case['revision'] and
                      basis.get('material_context_sha256') == material_context(case))
    usable = (run and run.get('case_id') == case['id'] and
              (run.get('case_revision') == case['revision'] or same_materials) and
              run.get('state') in ('ready', 'waiting_evidence'))
    if usable:
        allowed_media={m['id'] for m in case['media']}
        allowed_media.update(r['media']['id'] for r in run.get('reference_snapshot',[])
                             if r.get('permission')=='local_use_authorized' and r.get('media'))
        obs = {o['id']: o for o in run.get('observations', []) if o.get('media_id') in allowed_media}
        for claim in (run.get('assessment') or {}).get('claims', []):
            d = claim.get('dimension')
            if d not in ('period', 'kiln', 'style'):
                continue
            row = rows[d]
            ids = claim.get('conflict') if claim.get('status') == 'conflicting' else claim.get('support')
            valid = [i for i in (ids or []) if i in obs]
            state = claim.get('status')
            if state not in ('conflicting', 'supported') or not valid:
                continue
            # A contradiction dominates multiple candidates; never sum duplicate claims.
            if row['state'] == 'conflicting':
                continue
            row.update(state='conflicting' if state == 'conflicting' else 'consistent',
                       reasons=[claim['reasoning_summary']], origin='saved_model_opinion_unreviewed',
                       evidence=[{'kind': 'model_observation', 'id': i, 'run_id': run['id'],
                                  'media_id': obs[i]['media_id'], 'locator': str(obs[i]['region']),
                                  'sha256': digest(obs[i])} for i in valid])
    replaced_events = {e.get('supersedes') for e in case.get('provenance_events', []) if e.get('supersedes')}
    disputed = [e for e in case.get('provenance_events', [])
                if e['id'] not in replaced_events and e['status'] == 'disputed' and e.get('evidence')]
    if disputed:
        rows['provenance'].update(state='conflicting', origin='operator_disputed_record_unverified',
                                 reasons=[e['description'] for e in disputed],
                                 evidence=[{'kind': 'provenance', 'id': e['id'], 'sha256': digest(e),
                                            'locator': e['date_text']} for e in disputed])
    # Technical identity disagreement is an obvious contradiction, not a ceramic verdict.
    bad_files = []
    bad_refs = set()
    originals = [('media', m['id'], m['id'], m['sha256']) for m in case['media']]
    originals.extend(('attachment', e['id'], e['artifact_id'], e['sha256'])
                     for e in case.get('evidence_documents', []))
    for kind, record_id, blob_id, expected_sha in originals:
        try:
            _, raw = store.blob(blob_id)
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                bad_files.append(record_id)
                bad_refs.add((kind, record_id))
        except Problem:
            bad_files.append(record_id)
            bad_refs.add((kind, record_id))
    if bad_files:
        rows['capture'].update(state='conflicting', origin='file_identity_check',
                               reasons=['原始文件缺失或SHA256不一致：'+', '.join(bad_files)])
    if not bad_files:
        declared_roles={m.get('capture_role','unknown') for m in case['media']}
        missing=[label for role,label in [('overall','全貌'),('base','底足'),('mouth','口沿')] if role not in declared_roles]
        rows['capture']['reasons']=[f'档案原图{len(case["media"])}张；'+('尚缺视角声明：'+ '、'.join(missing)+'。' if missing else '已有全貌、底足、口沿声明。')+'视角标签与拍摄真实性未认证。']
    checks = case.get('risk_checks', [])
    replaced = {c.get('supersedes') for c in checks if c.get('supersedes')}
    check_basis = case.get('risk_check_basis', {})
    check_basis_current = (check_basis.get('bridge_case_revision') == case['revision'] and
                           check_basis.get('material_context_sha256') == material_context(case))
    current_check_ids = []
    for check in checks:
        if check['id'] in replaced:
            continue
        # Old operator assertions remain history, never silently recalculated on changed materials.
        if (not check_basis_current or
            check.get('material_epoch_id') != check_basis.get('epoch_id') or
            check.get('material_context_sha256') != material_context(case)):
            continue
        row = rows[check['dimension']]
        if any((e['kind'], e['id']) in bad_refs for e in check['evidence']):
            row['reasons'].append('此登记的原始凭据缺失或哈希不符，不采纳其已评价状态。')
            continue
        current_check_ids.append(check['id'])
        if row['state'] == 'conflicting' and check['state'] != 'conflicting':
            row['reasons'].append('仍有自动识别的冲突，不由一致声明消除。')
            continue
        row.update(state=check['state'], origin='operator_record_unverified',
                   reasons=[check['reason']], evidence=check['evidence'],
                   next_evidence=check['next_evidence'])
    alerts,alert_totals = obvious_conflicts(case)
    for alert in alerts:
        row = rows[alert['dimension']]
        if row['origin'] != 'deterministic_record_comparison':
            row.update(state='conflicting',origin='deterministic_record_comparison',
                       reasons=[] if row['state']=='unknown' else row['reasons'],evidence=row['evidence'])
        row['reasons'].append(alert['reason'])
        row['evidence'].extend(alert['evidence'])
    for row in rows.values():
        unique={}
        for e in row['evidence']:
            unique.setdefault((e['kind'],e['id'],e.get('sha256'),e.get('locator')),e)
        row['evidence']=list(unique.values())
    values = list(rows.values())
    return {'version': VERSION, 'case_id': case['id'], 'case_revision': case['revision'],
            'assessment_run_id': run['id'] if usable else None,
            'indices': calculate(values), 'dimensions': values,
            'priority_dimensions': [r['dimension'] for r in sorted(values, key=lambda r:
                (r['state'] == 'conflicting', r['state'] == 'unknown', r['weight']), reverse=True)
                if r['state'] != 'consistent'],
            'evidence_choices': choices, 'history': checks, 'current_material_check_ids': current_check_ids,
            'facts':case.get('risk_facts',[]),
            'automatic_alerts':alerts, 'automatic_alert_totals':alert_totals,
            'automatic_alert_display_limit_per_rule':10, 'material_context_sha256':material_context(case),
            'professional_quality_verified': False, 'expert_calibrated': False,
            'model_calls': 0, 'laya': {'enabled': False, 'state': 'disabled_pending_cpu_checkpoint_test',
                                     'scope': 'optional_text_shadow_only'}, 'notice': NOTICE}


def create_risk_router(store):
    router = APIRouter(prefix='/api/cases')

    @router.get('/{identifier}/risk-triage')
    def get_triage(identifier: str):
        case = store.read('case', identifier)
        run = store.read('run', case['current_run_id']) if case.get('current_run_id') else None
        return triage(store, case, run)

    @router.post('/{identifier}/risk-checks', status_code=201)
    def add_check(identifier: str, body: RiskCheckIn):
        data = body.model_dump()
        def add(db):
            case = store.checked_case(db, identifier, body.expected_case_revision)
            checks = case.setdefault('risk_checks', [])
            if len(checks) >= 100:
                raise Problem(413, '风险登记最多100条；请保留历史并另建后续案卷')
            if body.supersedes:
                previous = next((c for c in checks if c['id'] == body.supersedes), None)
                if not previous or previous['dimension'] != body.dimension:
                    raise Problem(422, '补正对象必须是本案同维度风险记录')
                if any(c.get('supersedes')==body.supersedes for c in checks):
                    raise Problem(409,'该风险记录已被补正，请选择最新记录')
            validate_evidence(store, db, case, data['evidence'])
            if case.get('current_run_id'):
                current = store.get(db, 'run', case['current_run_id'])
                if (current.get('case_id') == case['id'] and
                    current.get('case_revision') == case['revision'] and
                    current.get('state') in ('ready', 'waiting_evidence')):
                    case['risk_model_basis'] = {
                        'run_id': current['id'], 'run_case_revision': current['case_revision'],
                        'bridge_case_revision': case['revision'] + 1,
                        'material_context_sha256': material_context(case)}
                else:
                    basis = case.get('risk_model_basis', {})
                    if (basis.get('run_id') == current.get('id') and
                        basis.get('run_case_revision') == current.get('case_revision') and
                        basis.get('bridge_case_revision') == case['revision'] and
                        basis.get('material_context_sha256') == material_context(case)):
                        basis['bridge_case_revision'] = case['revision'] + 1
            check_basis = case.get('risk_check_basis', {})
            if (check_basis.get('bridge_case_revision') == case['revision'] and
                check_basis.get('material_context_sha256') == material_context(case)):
                check_basis['bridge_case_revision'] = case['revision'] + 1
            else:
                # A changed/restored registration must not reactivate old operator assertions.
                check_basis = {'epoch_id': uid('riskbasis'),
                    'bridge_case_revision': case['revision'] + 1,
                    'material_context_sha256': material_context(case)}
            case['risk_check_basis'] = check_basis
            check = {k: v for k, v in data.items() if k not in ('request_id', 'expected_case_revision')}
            check.update(id=uid('risk'), case_id=identifier, case_revision=case['revision']+1,
                         source_case_revision=case['revision'], recorded_at=time.time(),
                         actor='本地操作人（身份未认证）', identity_verified=False,
                         material_context_sha256=material_context(case),
                         material_epoch_id=check_basis['epoch_id'])
            checks.append(check)
            store.advance(db, case, 'risk_check', {'id': check['id'], 'dimension': body.dimension,
                                                'notice': NOTICE})
            return {'case': case, 'check': check}
        return store.mutate('risk-check:'+identifier, data, add)
    @router.post('/{identifier}/risk-facts', status_code=201)
    def add_fact(identifier: str, body: RiskFactIn):
        data = body.model_dump()
        def add(db):
            case = store.checked_case(db, identifier, body.expected_case_revision)
            facts = case.setdefault('risk_facts', [])
            if len(facts) >= 100:
                raise Problem(413, '结构化材料记载最多100条')
            if body.supersedes:
                old = next((f for f in facts if f['id']==body.supersedes),None)
                if not old or old['field']!=body.field:
                    raise Problem(422,'补正对象必须是本案同字段记载')
                if any(f.get('supersedes')==body.supersedes for f in facts):
                    raise Problem(409,'该材料记载已被补正，请选择最新记录')
            validate_evidence(store, db, case, data['evidence'])
            fact = {k:v for k,v in data.items() if k not in ('request_id','expected_case_revision')}
            fact.update(id=uid('riskfact'),case_id=identifier,case_revision=case['revision']+1,
                        origin='operator_transcribed_saved_evidence',verified=False,recorded_at=time.time())
            facts.append(fact)
            store.advance(db,case,'risk_fact',{'id':fact['id'],'field':body.field,'notice':NOTICE})
            return {'case':case,'fact':fact}
        return store.mutate('risk-fact:'+identifier,data,add)
    return router
