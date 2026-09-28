"""Optional local-only text routing experiment; never changes a case or action."""
import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

LAYA_SOURCE_COMMIT = '4066d5d5fbf08b66c6757ddeedbd797bd7655bc0'
QUESTIONS = {
    'next_step': {
        'type': 'choice',
        'instructions': '只根据已记录事实，建议研究流程下一步；未知不得补写。此问题不判断图像真伪、器物真伪或实际年代。',
        'criteria': {
            'continue_analysis': '已有可读材料，继续本地专业研究；不表示真品或放弃复核',
            'request_evidence': '关键材料缺失，先请求一项能区分解释的证据',
            'out_of_scope': '已观察的对象明确超出青花花觚专科，转人工或其他专科',
        },
    },
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def run_shadow(state, engine, checkpoint):
    """engine implements Laya Agent.system_one; tests use a labelled contract double."""
    if not isinstance(state, dict) or set(state) != {'facts', 'incumbent_next_step', 'review_required'}:
        raise ValueError('state requires exactly facts, incumbent_next_step, review_required')
    if not isinstance(state['facts'], dict) or not isinstance(state['incumbent_next_step'], str):
        raise ValueError('facts must be an object and incumbent_next_step a string')
    if type(state['review_required']) is not bool:
        raise ValueError('review_required must be a boolean')
    if state['incumbent_next_step'] not in QUESTIONS['next_step']['criteria']:
        raise ValueError('Map incumbent to the same three route labels before comparing')
    serialized = canonical(state)
    if len(serialized) > 3000:
        raise ValueError('Use compact measured facts, not raw images or full case histories')
    result = {'mode': 'shadow_only', 'authoritative_next_step': state['incumbent_next_step'],
              'review_required': state['review_required'], 'prediction': None,
              'state_sha256': hashlib.sha256(serialized.encode()).hexdigest(),
              'question_sha256': hashlib.sha256(canonical(QUESTIONS).encode()).hexdigest(),
              'checkpoint': checkpoint, 'laya_source_contract': LAYA_SOURCE_COMMIT,
              'calibrated_for_ceramics': False, 'error': None}
    start = time.perf_counter()
    try:
        raw = engine.system_one(state['facts'], QUESTIONS, lang='zh', max_len=1024, head_max_len=384)
        answer = raw['answers']['next_step']
        keys = set(QUESTIONS['next_step']['criteria'])
        probs = answer['probabilities']
        if answer.get('type') != 'choice' or answer['choice'] not in keys or set(probs) != keys:
            raise ValueError('Unexpected Laya response contract')
        numbers = list(probs.values()) + [answer['confidence'], answer['answer_confidence']]
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in numbers):
            raise ValueError('Invalid probability or confidence')
        if abs(sum(probs.values()) - 1) > .002:
            raise ValueError('Probabilities do not sum to one')
        if probs[answer['choice']] < max(probs.values()) - .0002:
            raise ValueError('Choice disagrees with probabilities')
        result['prediction'] = {k: answer[k] for k in ('choice', 'probabilities', 'confidence', 'answer_confidence')}
        result['disagrees'] = answer['choice'] != state['incumbent_next_step']
    except Exception as exc:
        result['error'] = type(exc).__name__
    result['elapsed_ms'] = round((time.perf_counter() - start) * 1000, 3)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='本地 Laya 影子实验；不写入案卷、不改变实际路由')
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--model-dir', required=True, type=Path)
    parser.add_argument('--device', default='cpu', choices=['cpu', 'cuda', 'mps'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    model_dir = args.model_dir.resolve(strict=True)
    if not model_dir.is_dir() or not (model_dir / 'config.json').is_file():
        parser.error('model-dir 必须是已准备好的本地 Laya checkpoint，含 config.json')
    if args.output.exists():
        parser.error('output 已存在，请使用新路径以保留实验记录')
    state = json.loads(args.state.read_text(encoding='utf-8'))
    # Set before importing Laya/transformers. This command never fetches a model.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from laya import Agent
    files = sorted(p for p in model_dir.rglob('*') if p.is_file())
    identity = {}
    for path in files:
        with path.open('rb') as stream:
            identity[str(path.relative_to(model_dir))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    with Agent(str(model_dir), device=args.device) as engine:
        result = run_shadow(state, engine, {'files_sha256': identity, 'device': args.device})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print('影子记录已保存；实际路由与复核要求未改变。')
    return 1 if result['error'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
