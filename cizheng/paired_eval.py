"""Paired plain/skills trials on independent cases; no built-in model substitute."""
import argparse
import asyncio
import base64
import hashlib
import json
import platform
import time
from pathlib import Path

from .agent import Engine, LocalModel
from .store import Store, uid, decode_image, Problem


def read_manifest(path):
    """No answer key is accepted here. Review labels stay in a separate file."""
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding='utf-8'))
    if set(value) != {'cases', 'references'} or not value['cases']:
        raise ValueError('manifest requires nonempty cases and references; no answer key')
    if not isinstance(value['cases'], list) or not isinstance(value['references'], list):
        raise ValueError('cases and references must be lists')
    ids, objects, image_owners = set(), set(), {}
    allowed = {'id', 'object_id', 'question', 'target_attribution', 'source_declaration', 'images'}
    for case in value['cases']:
        if set(case) != allowed or case['id'] in ids or case['object_id'] in objects:
            raise ValueError('case fields, case IDs or independent object IDs invalid')
        if not all(isinstance(case[k], str) and case[k].strip() for k in allowed - {'images'}):
            raise ValueError('case text fields must be nonempty strings')
        ids.add(case['id']); objects.add(case['object_id'])
        if not isinstance(case['images'], list) or not 1 <= len(case['images']) <= 8:
            raise ValueError(f"case {case['id']}: first-round trials require 1–8 selected images")
        for im in case['images']:
            if set(im) != {'path', 'view', 'edit_declaration'}:
                raise ValueError('image requires path, view, edit_declaration')
            raw = _image_bytes(path.parent, im['path'])
            sha = hashlib.sha256(raw).hexdigest()
            if sha in image_owners and image_owners[sha] != case['object_id']:
                raise ValueError('same image bytes assigned to different test objects')
            if sha in image_owners:
                raise ValueError(f"case {case['id']}: duplicate image bytes; keep one entry with a consistent view declaration")
            image_owners[sha] = case['object_id']
            im['_raw'] = raw
            im['_sha256'] = sha
    ref_ids = set()
    required_ref = {'object_id', 'title', 'locator', 'source_url', 'attribution', 'authority', 'permission', 'notes', 'path'}
    for ref in value['references']:
        if set(ref) != required_ref or ref['object_id'] in objects or ref['object_id'] in ref_ids:
            raise ValueError('reference fields/objects invalid; unseen-object test cannot retrieve same object')
        ref_ids.add(ref['object_id'])
        if ref['permission'] != 'local_use_authorized':
            raise ValueError('benchmark references require documented local-use permission')
        raw = _image_bytes(path.parent, ref['path'])
        sha = hashlib.sha256(raw).hexdigest()
        if sha in image_owners:
            raise ValueError('reference contains exact test image')
        ref['_raw'] = raw
        ref['_sha256'] = sha
    return value


def _image_bytes(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError('image paths must be relative to the manifest directory')
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError('image must stay within the manifest directory')
    if resolved.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('image exceeds 20MB')
    raw = resolved.read_bytes()
    try:
        decode_image(base64.b64encode(raw).decode())
    except Problem as exc:
        raise ValueError(f'Invalid image {relative}: {exc.message}') from exc
    return raw


def prepare(manifest):
    return {'semantic_evaluation': 'not_run', 'model_calls': 0,
            'scope': 'fixed-evidence first-round paired comparison; active supplements are separate',
            'cases': [{'id': c['id'], 'object_id': c['object_id'],
                       'image_sha256': [im['_sha256'] for im in c['images']]} for c in manifest['cases']],
            'reference_sha256': [r['_sha256'] for r in manifest['references']],
            'arms': ['plain', 'skills'], 'answer_key_passed_to_model': False}


async def evaluate(manifest, output, model=None):
    model = model or LocalModel()
    if not model.configured:
        raise ValueError('No local model configured. Prepare only; do not invent benchmark results.')
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a new output directory to preserve prior trials')
    output.mkdir(parents=True)
    summary = prepare(manifest)
    summary.update(semantic_evaluation='requires_blind_expert_review', model_calls=None,
                   environment={'python': platform.python_version(), 'platform': platform.platform()},
                   model=model.identity(), trials=[], planned_trials=2*len(manifest['cases']),
                   completed_trials=0, excluded_trials=0)
    (output / 'blind').mkdir()
    (output / 'blind' / 'assets').mkdir()
    mapping = []
    for index, item in enumerate(manifest['cases']):
        # Alternate which arm runs first to expose order/warm-cache effects.
        order = ['plain', 'skills'] if index % 2 == 0 else ['skills', 'plain']
        for position, mode in enumerate(order):
            trial_start = time.perf_counter()
            trial_id = f'trial-{index+1:03d}-{position+1}'
            store = Store(output / trial_id)
            case = store.create_case({'request_id': uid('req'), 'title': f'Evaluation object {index+1}',
                **{k: item[k] for k in ('question', 'target_attribution', 'source_declaration')}})
            for n, im in enumerate(item['images']):
                case = store.add_evidence(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
                    'filename': f'image-{n+1}.bin', 'image_base64': base64.b64encode(im['_raw']).decode(),
                    'view': im['view'], 'edit_declaration': im['edit_declaration'], 'source': item['source_declaration']})['case']
            for n, ref in enumerate(manifest['references']):
                store.add_reference({'request_id': uid('req'), 'filename': f'reference-{n+1}.bin',
                    'image_base64': base64.b64encode(ref['_raw']).decode(),
                    **{k: ref[k] for k in ('title','locator','source_url','attribution','authority','permission','notes')}})
            engine = Engine(store, model)
            versions = engine.versions(mode)
            rid = store.start_run(case['id'], {'request_id': uid('req'), 'expected_case_revision': case['revision'],
                                               'mode': mode}, versions)['run_id']
            start = time.perf_counter()
            await engine.execute(rid)
            run = store.read('run', rid)
            trial = {'trial_id': trial_id, 'case_id': item['id'], 'mode': mode, 'order': position,
                     'state': run['state'], 'model_calls': run['model_calls'], 'tool_calls': run['tool_calls'],
                     'execution_seconds': round(time.perf_counter()-start, 4),
                     'preparation_and_execution_seconds': round(time.perf_counter()-trial_start, 4),
                     'timing_excludes': ['manifest_validation', 'external_model_server_loading', 'human_review', 'packet_export'],
                     'error': run.get('error'),
                     'versions': versions, 'case_image_sha256': [im['_sha256'] for im in item['images']]}
            summary['trials'].append(trial)
            # Blind packets omit mode, loaded skill names and ordered IDs; provenance remains in trial stores.
            blind_id = uid('packet')
            media = []
            stored_media = {m['sha256']: m for m in case['media']}
            for image in item['images']:
                m = stored_media[image['_sha256']]
                suffix = 'png' if m['mime'] == 'image/png' else 'jpg'
                asset = f"assets/{image['_sha256']}.{suffix}"
                (output / 'blind' / asset).write_bytes(image['_raw'])
                media.append({'media_id': m['id'], 'path': asset, 'sha256': image['_sha256'], 'declared_view': image['view']})
            references = []
            used = set((run.get('assessment') or {}).get('reference_ids', []))
            for ref in run['reference_snapshot']:
                if ref['id'] in used:
                    _, raw = store.blob(ref['media']['id'])
                    suffix = 'png' if ref['media']['mime'] == 'image/png' else 'jpg'
                    asset = f"assets/{ref['media']['sha256']}.{suffix}"
                    (output / 'blind' / asset).write_bytes(raw)
                    references.append({**ref, 'image_path': asset})
            packet = {'packet_id': blind_id, 'question': item['question'], 'images': media,
                      'references': references,
                      'assessment': run.get('assessment'), 'observations': run.get('observations', []),
                      'evidence_request': run.get('evidence_request'), 'state': run['state'],
                      'error': run.get('error')}
            (output / 'blind' / f'{blind_id}.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2))
            mapping.append({'packet_id': blind_id, 'trial_id': trial_id, 'case_id': item['id'], 'mode': mode})
            summary['completed_trials'] = len(summary['trials'])
            # Incremental write retains completed and failed trials if a later trial is interrupted.
            (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            (output / 'reviewer-hidden-mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    summary['protocol_completed'] = sum(t['state'] in ('ready','waiting_evidence') for t in summary['trials'])
    summary['model_calls'] = sum(t['model_calls'] for t in summary['trials'])
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='同模型、同资料、独立预算的有/无Skills对照；默认只检查输入')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', action='store_true', help='实际调用已配置的本地VLM')
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.manifest)
        if args.run:
            result = asyncio.run(evaluate(manifest, args.output))
            if result['protocol_completed'] != result['planned_trials']:
                parser.exit(1, '存在未完成的对照运行；失败结果已保留，不能计为成功验证。\n')
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(prepare(manifest), stream, ensure_ascii=False, indent=2)
        print('完成；工程协议完成数不等于陶瓷鉴定正确数。')
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
