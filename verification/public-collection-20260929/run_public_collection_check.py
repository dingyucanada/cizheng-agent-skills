"""New, isolated public-collection experiment; not expert validation.

Phase A: three neutral image-only cases, plain/skills, no references or RAG.
Phase B: one explicitly nonblind public-source-context workflow after phase A.
No Engine, schema, prompt, or existing business store is modified.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time


QUESTION_A = '记录这组照片的具体可见细节，分别说明时期、窑口、装饰风格的依据和关键补证。未展示部位不要补写；普通纹样不能作为确定断代依据。'
QUESTION_B = '记录这组照片的具体可见细节，分别说明时期、窑口、装饰风格的依据和关键补证。馆方文字记载另列来源上下文，引用本轮实际读到的段落；不要将馆藏记载当作照片独立判定。'
TARGET = '照片可支持的有限研究；未指定制作时期和窑口'
SOURCE_A = '公开机构图像；来源及馆藏归属首轮不提供给模型。'
SOURCE_B = '公开机构图像；本轮已提供官方记录，属于非盲来源文字核查。'
CONFIG = {'CIZHENG_GUIDED_WORKFLOW': '1', 'CIZHENG_COMPACT_ACTIONS': '1',
          'CIZHENG_STRUCTURED_OUTPUTS': '1', 'CIZHENG_DISABLE_THINKING': '0',
          'CIZHENG_PROMPT_PROFILE': 'source-r2'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def request_projection(value):
    """Exact text, ordered image byte hashes; never duplicate image Base64."""
    if isinstance(value, list):
        return [request_projection(item) for item in value]
    if isinstance(value, dict):
        return {key: request_projection(item) for key, item in value.items()}
    if isinstance(value, str) and value.startswith('data:image/'):
        prefix, encoded = value.split(',', 1)
        if not prefix.endswith(';base64'):
            raise ValueError('unsupported_image_data_url')
        raw = base64.b64decode(encoded, validate=True)
        return {'data_url_prefix': prefix, 'image_sha256': sha(raw),
                'image_bytes': len(raw), 'base64_omitted': True}
    return value


def configure():
    # Must precede importing cizheng.agent: its prompt profile is startup-only.
    for key, value in CONFIG.items():
        existing = os.environ.get(key)
        if existing is not None and existing != value:
            raise ValueError('fixed_experiment_config_conflict:' + key)
        os.environ[key] = value


def load_neutral_manifest(path):
    from cizheng.paired_eval import read_manifest, prepare
    manifest = read_manifest(path)
    if len(manifest['cases']) != 3 or manifest['references']:
        raise ValueError('phase_A_requires_three_independent_objects_and_empty_references')
    manifest = deepcopy(manifest)
    for case in manifest['cases']:
        case.update(question=QUESTION_A, target_attribution=TARGET, source_declaration=SOURCE_A)
        for index, image in enumerate(case['images'], 1):
            image['view'] = f'公开拍摄视角{index}；未验证拍摄部位'
            image['edit_declaration'] = '公开来源图片原始字节；显示派生由既有工具记录'
    return manifest, prepare(manifest)


def source_record(path):
    from cizheng.knowledge import KnowledgeDocumentIn, METADATA_FIELDS
    value = json.loads(path.read_text(encoding='utf-8'))
    if set(value) != {'source', 'chunks'}:
        raise ValueError('source_record_requires_only_source_and_chunks')
    metadata = value['source']
    if set(metadata) - set(METADATA_FIELDS):
        raise ValueError('source_record_unknown_metadata')
    if metadata.get('rights') != 'authorized_text' or not metadata.get('rights_note'):
        raise ValueError('source_text_requires_explicit_authorization_note')
    if not metadata.get('source_url') or not metadata.get('institution'):
        raise ValueError('source_record_requires_official_url_and_institution')
    KnowledgeDocumentIn.model_validate({**metadata, 'chunks': value['chunks']})
    return value


def recorder_class():
    from cizheng.agent import LocalModel
    from cizheng.store import digest

    class RecordedModel(LocalModel):
        def __init__(self, url, model):
            super().__init__(url, model)
            self.record_dir = None
            self.request_index = 0

        def bind(self, directory):
            self.record_dir = directory
            directory.mkdir(parents=True, exist_ok=False)
            self.request_index = 0

        async def complete(self, messages, timeout):
            self.request_index += 1
            record = {'request_index': self.request_index, 'messages_sha256': digest(messages),
                      'messages_projection': request_projection(messages), 'timeout_seconds': timeout,
                      'image_base64_preserved': False, 'model': self.identity(),
                      'full_http_payload_saved': False,
                      'payload_note': '记录送入既有 LocalModel 的精确消息投影及完整消息哈希；HTTP响应模式由固定源码构造。'}
            started = time.monotonic()
            try:
                text, usage = await super().complete(messages, timeout)
                record.update(response_text=text, response_sha256=sha(text.encode()),
                              usage=usage, succeeded=True)
                return text, usage
            except BaseException as exc:
                record.update(succeeded=False, error_type=type(exc).__name__,
                              usage=getattr(exc, 'usage', {}))
                raise
            finally:
                record['seconds'] = round(time.monotonic()-started, 6)
                write_new(self.record_dir/f'request-{self.request_index:02d}.json', record)

    return RecordedModel


async def execute(args, manifest, prepared, source=None):
    from cizheng import schemas as S
    from cizheng.agent import Engine
    from cizheng.claim_support_audit import audit_claim_support, review_template
    from cizheng.knowledge import KnowledgeStore, validate_snapshot
    from cizheng.store import Store, uid

    model = recorder_class()(args.model_url, args.model)
    if args.model != 'Qwen/Qwen3-VL-8B-Instruct':
        raise ValueError('this_frozen_experiment_requires_main_8B_model')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    summary = {**prepared, 'phase': args.phase, 'model_calls': 0, 'trials': [],
               'semantic_evaluation': 'requires_public_collection_case_review',
               'expert_validation': False, 'ceramic_accuracy': 'not_measured',
               'authenticity_probability': None, 'fixed_config': CONFIG,
               'budget_per_run': {'model_calls': 12, 'tool_calls': 20, 'active_seconds': 300,
                                  'request_timeout_seconds': 90, 'temperature': 0.1,
                                  'action_max_tokens': 2500, 'vision_max_tokens': 800},
               'knowledge_policy': 'empty' if args.phase == 'a' else 'one_explicit_nonblind_public_source',
               'driver_sha256': sha(Path(__file__).read_bytes()),
               'attribution_gate': 'without_observed_image_references_all_claims_insufficient_or_out_of_scope',
               'scope_limit': 'observations_reasons_and_supplement_requests_not_authenticity_or_independent_dating_accuracy',
               'planned_trials': 6 if args.phase == 'a' else 1, 'completed_trials': 0}
    mapping = []
    cases = manifest['cases'] if args.phase == 'a' else [next(c for c in manifest['cases'] if c['id'] == args.case_id)]
    if args.phase == 'b':
        prior = json.loads((args.phase_a_results/'summary.json').read_text())
        if prior.get('phase') != 'a' or prior.get('completed_trials') != 6:
            raise ValueError('phase_B_requires_all_six_phase_A_trials_saved')
        prior_images = {c['id']: c['image_sha256'] for c in prior['cases']}
        if prior_images.get(args.case_id) != [im['_sha256'] for im in cases[0]['images']]:
            raise ValueError('phase_B_image_bytes_must_match_completed_phase_A_case')
    for case_index, item in enumerate(cases):
        order = ['plain', 'skills'] if case_index % 2 == 0 else ['skills', 'plain']
        if args.phase == 'b':
            order = ['skills']
        for order_index, mode in enumerate(order):
            trial_id = f'trial-{case_index+1:03d}-{order_index+1}'
            trial_dir = args.output/trial_id
            store = Store(trial_dir/'case-data')
            case = store.create_case(S.NewCase(request_id=uid('req'), title=f'公开器物{case_index+1:03d}',
                question=QUESTION_A if args.phase == 'a' else QUESTION_B,
                target_attribution=TARGET, source_declaration=SOURCE_A if args.phase == 'a' else SOURCE_B).model_dump())
            for image_index, image in enumerate(item['images'], 1):
                case = store.add_evidence(case['id'], S.EvidenceIn(request_id=uid('req'),
                    expected_case_revision=case['revision'], filename=f'photo-{image_index}.jpg',
                    image_base64=base64.b64encode(image['_raw']).decode(), view=image['view'],
                    edit_declaration=image['edit_declaration'], source=SOURCE_A if args.phase == 'a' else SOURCE_B).model_dump())['case']
            if source is not None:
                document = KnowledgeStore(store.root).add_document({**source['source'], 'chunks': source['chunks']})['source']
                case = store.link_document(case['id'], S.CaseDocumentIn(request_id=uid('req'),
                    expected_case_revision=case['revision'], document_id=document['document_id'],
                    document_revision=document['revision'], document_sha256=document['document_sha256']).model_dump())
            engine = Engine(store, model)
            versions = engine.versions(mode)
            run_id = store.start_run(case['id'], S.RunIn(request_id=uid('req'),
                expected_case_revision=case['revision'], mode=mode).model_dump(), versions)['run_id']
            before = store.read('run', run_id)
            frozen = validate_snapshot(before['knowledge_snapshot'])
            if args.phase == 'a' and (frozen['sources'] or before['reference_snapshot'] or case['knowledge_links']):
                raise ValueError('phase_A_reference_or_knowledge_leakage')
            write_new(trial_dir/'pre-run-knowledge-check.json', {'knowledge_sources': len(frozen['sources']),
                'image_references': len(before['reference_snapshot']), 'case_knowledge_links': len(case['knowledge_links']),
                'knowledge_snapshot_sha256': frozen['snapshot_sha256'], 'phase_A_empty_knowledge_verified': args.phase == 'a'})
            model.bind(trial_dir/'requests')
            started = time.monotonic()
            await engine.execute(run_id)
            run = store.read('run', run_id)
            write_new(trial_dir/'final-run.json', run)
            audit = audit_claim_support(run)
            write_new(trial_dir/'claim-support-audit.json', audit)
            write_new(trial_dir/'review-template.json', review_template(audit['packet']))
            request_records = [json.loads(path.read_text()) for path in sorted((trial_dir/'requests').glob('request-*.json'))]
            model_events = [event for event in run['events'] if event['type'] == 'model']
            pairs = [{'request_index': record['request_index'], 'messages_sha256': record['messages_sha256'],
                      'event_input_sha256': event['input_hash'], 'exact_hash_match': record['messages_sha256'] == event['input_hash'],
                      'purpose': event['purpose'], 'outcome': event['outcome']}
                     for record, event in zip(request_records, model_events)]
            write_new(trial_dir/'request-event-bindings.json', {'request_count': len(request_records),
                'model_event_count': len(model_events), 'pairs': pairs,
                'all_bound': len(request_records) == len(model_events) and all(pair['exact_hash_match'] for pair in pairs)})
            trial = {'trial_id': trial_id, 'case_id': item['id'], 'mode': mode, 'order': order_index,
                     'state': run['state'], 'error': run.get('error'), 'seconds': round(time.monotonic()-started, 6),
                     'model_calls': run['model_calls'], 'tool_calls': run['tool_calls'], 'versions': run['versions'],
                     'image_sha256': [im['_sha256'] for im in item['images']],
                     'knowledge_source_count': len(run['knowledge_snapshot']['sources']),
                     'reference_count': len(run['reference_snapshot']), 'expert_validation': False}
            summary['trials'].append(trial)
            summary['completed_trials'] = len(summary['trials'])
            summary['model_calls'] = sum(t['model_calls'] for t in summary['trials'])
            summary['protocol_completed'] = sum(t['state'] in ('ready', 'waiting_evidence') for t in summary['trials'])
            # Random packet names do not establish that an actual blind reviewer participated.
            packet_id = uid('packet')
            packet_images = []
            stored_images = {media['sha256']: media for media in run['snapshot']['media']}
            for image in item['images']:
                media = stored_images[image['_sha256']]
                suffix = 'png' if media['mime'] == 'image/png' else 'jpg'
                asset = f"assets/{image['_sha256']}.{suffix}"
                asset_path = args.output/'review-packets'/asset
                asset_path.parent.mkdir(parents=True, exist_ok=True)
                if asset_path.exists():
                    if asset_path.read_bytes() != image['_raw']:
                        raise ValueError('review_asset_hash_collision')
                else:
                    asset_path.write_bytes(image['_raw'])
                packet_images.append({'media_id': media['id'], 'image_sha256': image['_sha256'],
                                      'path': asset, 'view_declaration': image['view']})
            write_new(args.output/'review-packets'/f'{packet_id}.json', {
                'packet_id': packet_id, 'images': packet_images,
                'observations': run['observations'], 'assessment': run['assessment'],
                'evidence_request': run.get('evidence_request'), 'state': run['state'], 'error': run.get('error'),
                'expert_validation': False, 'packet_note': '未认证阅评者；随机命名不代表已完成盲评。'})
            mapping.append({'packet_id': packet_id, 'trial_id': trial_id, 'case_id': item['id'], 'mode': mode})
            # Incremental atomic replacement retains every failed and completed trial.
            temp = args.output/'summary.next.json'
            temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
            temp.replace(args.output/'summary.json')
            (args.output/'reviewer-hidden-mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description='公开馆藏个案核查；默认仅检查清单、零模型调用。')
    parser.add_argument('--phase', choices=['a', 'b'], default='a')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--model-url', default='http://127.0.0.1:8005/v1')
    parser.add_argument('--model', default='Qwen/Qwen3-VL-8B-Instruct')
    parser.add_argument('--source-record', type=Path)
    parser.add_argument('--case-id')
    parser.add_argument('--phase-a-results', type=Path)
    args = parser.parse_args()
    configure()
    manifest, prepared = load_neutral_manifest(args.manifest)
    if args.phase == 'a' and any((args.source_record, args.case_id, args.phase_a_results)):
        parser.error('phase_A_forbids_source_record_and_answer_inputs')
    source = None
    if args.phase == 'b':
        if not all((args.source_record, args.case_id, args.phase_a_results)):
            parser.error('phase_B_requires_source_record_case_id_and_completed_phase_A_directory')
        if args.case_id not in {c['id'] for c in manifest['cases']}:
            parser.error('unknown_case_id')
        source = source_record(args.source_record)
    if args.run:
        result = asyncio.run(execute(args, manifest, prepared, source))
        print(json.dumps({'phase': args.phase, 'completed_trials': result['completed_trials'],
                          'protocol_completed': result['protocol_completed'], 'expert_validation': False}, ensure_ascii=False))
        if result['protocol_completed'] != result['planned_trials']:
            parser.exit(1, '存在失败或未完成的试验，全部已保留；工程完成不等于专业正确。\n')
    else:
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_new(args.output/'preparation.json', {**prepared, 'phase': args.phase, 'fixed_config': CONFIG,
            'neutral_text_policy': 'fixed_driver_strings_no_catalogue_identity_or_attribution',
            'source_record_validated': source is not None, 'expert_validation': False})
        print('清单检查完成；模型调用为 0。')


if __name__ == '__main__':
    main()
