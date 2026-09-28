"""Reproducible photo-report indicators, calculated from one immutable run.

Capture coverage measures operator labels, never authenticity or image content.
No model self-confidence, router probability, or heuristic is converted to truth.
"""
from collections import Counter

CAPTURE_LABELS = {
    'unknown': '未标记', 'overall': '器身全貌', 'base': '底足与露胎',
    'mouth': '口沿与内壁', 'glaze': '釉面细节', 'decoration': '纹饰细节',
    'inscription': '款识与题铭', 'condition': '损伤与修复细节',
}
# A general collection guide, not a validated specialist diagnostic checklist.
GUIDE_ROLES = ('overall', 'base', 'mouth', 'glaze', 'decoration')
METHOD_VERSION = 'photo-evidence-coverage-v1'


def photo_report(run):
    snapshot = run.get('snapshot', {})
    if run.get('research_task', snapshot.get('research_task')) == 'documentary_audit':
        return {'schema_version': 1, 'method_version': METHOD_VERSION,
                'status': 'not_applicable', 'reason': '本轮只核查文字，没有视觉研判。'}
    media = snapshot.get('media', [])
    ids = {item['id'] for item in media}
    observations = run.get('observations', [])
    # An observation belongs to this run only; reference photos cannot increase
    # the object's observation coverage. A label alone is not an observation.
    located = [o for o in observations if o.get('media_id') in ids]
    observed = {o['media_id'] for o in located}
    declared = {m.get('capture_role', 'unknown') for m in media}
    covered = [role for role in GUIDE_ROLES if role in declared]
    missing = [role for role in GUIDE_ROLES if role not in declared]
    assessment = run.get('assessment') or {}
    status_counts = Counter(c.get('status', 'insufficient') for c in assessment.get('claims', []))
    by_id = {o['id']: o for o in observations}
    claims = []
    for claim in assessment.get('claims', []):
        claims.append({key: claim.get(key) for key in ('dimension', 'candidate', 'status', 'reasoning_summary')} | {
            'support_details': [by_id[i] for i in claim.get('support', []) if i in by_id],
            'conflict_details': [by_id[i] for i in claim.get('conflict', []) if i in by_id],
            'unresolved_observation_ids': [i for i in claim.get('support', []) + claim.get('conflict', []) if i not in by_id],
        })
    formed = bool(assessment) and run.get('state') in ('ready', 'waiting_evidence')
    return {
        'schema_version': 1, 'method_version': METHOD_VERSION,
        'run_id': run.get('id'), 'input_hash': run.get('input_hash'),
        'case_revision': run.get('case_revision'),
        'status': 'report_formed' if formed else 'incomplete_run',
        'capture_coverage': {
            'label': '采集覆盖指数（上传者标记）', 'value': len(covered) * 100 // len(GUIDE_ROLES),
            'numerator': len(covered), 'denominator': len(GUIDE_ROLES),
            'unit': 'points_out_of_100', 'covered_roles': covered, 'missing_roles': missing,
            'guide': [{'role': r, 'label': CAPTURE_LABELS[r]} for r in GUIDE_ROLES],
            'view_verified': False,
            'meaning': '五类通用拍摄视角中已标记的类别数 ÷ 5 × 100。只统计本轮选图；同类重复不加分。',
            'limitations': ['视角是上传者声明，未认证画面、清晰度或器物同一性。',
                           '通用采集提示可按器型调整；满分不表示证据足以断代，也不表示真品。'],
        },
        'photo_observation_coverage': {
            'observed_count': len(observed), 'selected_count': len(ids),
            'unobserved_media_ids': sorted(ids - observed),
            'meaning': '本轮有模型区域观察记录的器物照片数；不表示观察正确或关键细节已覆盖。',
        },
        'photos': [{'media_id': m['id'], 'filename': m.get('filename', ''),
                    'sha256': m.get('sha256'), 'declared_view': m.get('view', ''),
                    'capture_role': m.get('capture_role', 'unknown'), 'view_verified': False,
                    'observations': [o for o in located if o['media_id'] == m['id']]} for m in media],
        'claims': claims, 'claim_status_counts': dict(status_counts),
        'condition_hypotheses': assessment.get('condition_hypotheses', []),
        'authenticity_probability': {
            'value': None, 'status': 'not_calibrated', 'unit': 'probability',
            'target_attribution': snapshot.get('target_attribution', '未指定'),
            'calibration_version': None, 'calibration_dataset': None,
            'reason': '尚无该归属范围内、独立专家真值与留出测试支持的概率校准，不能给出可信真品率。',
            'required_evidence': ['明确年代/窑口/原作等判定目标和适用器型。',
                                  '包含高仿、残损与修复的专家真值样本；按器物和来源分组隔离训练、校准及测试。',
                                  '留出集校准误差、Brier分数、样本覆盖及拒判规则；必要时实物与检测证据。'],
            'router_probabilities_used': False,
        },
        'notice': '采集指数、观察数量、模型意见均不是真品概率。具体理由需逐项回查照片与资料。',
    }
