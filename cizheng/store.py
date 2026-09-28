"""Transactional records; original image bytes never overwritten.

The v1 prototype's content hashes and immutable revisions are retained as
principles. v2 deliberately does not import its synthetic visual conclusions.
"""
import base64
import hashlib
import io
import json
from copy import deepcopy
import sqlite3
import time
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path
from PIL import Image
from .preflight import case_preflight, has_documentary_text, measure_pixels


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def decode_image(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 20 * 1024 * 1024:
            raise Problem(413, '单图上限20MB')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('JPEG', 'PNG') or im.width * im.height > 40_000_000:
                    raise ValueError('只接受40MP以内JPEG/PNG')
                if getattr(im, 'n_frames', 1) != 1:
                    raise ValueError('不接受动图')
                width, height = im.size
                mime = Image.MIME[im.format]
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
    except Problem:
        raise
    except Exception as exc:
        raise Problem(422, '图片损坏、格式不支持或像素过大') from exc
    return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'mime': mime,
                 'width': width, 'height': height, 'size': len(raw)}


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'cizheng.sqlite3'
        with self.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS record_kind ON records(kind);
            CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, mime TEXT, bytes BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, hash TEXT, response TEXT);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, kind, identifier):
        row = db.execute('SELECT data FROM records WHERE id=? AND kind=?', (identifier, kind)).fetchone()
        if not row:
            raise Problem(404, '记录不存在')
        return Store.compatible(kind, json.loads(row[0]))

    @staticmethod
    def compatible(kind, record):
        if kind == 'case':
            record.setdefault('research_task', 'visual_research')
            record.setdefault('workflow', 'museum')
            record.setdefault('catalogue', {})
            record.setdefault('annotations', [])
            record.setdefault('knowledge_document_ids', [])
            record.setdefault('knowledge_links', [])
            record.setdefault('activity', [])
            record.setdefault('analysis_media_ids', [m['id'] for m in record.get('media', [])[:8]])
            record.setdefault('analysis_selection_explicit', False)
            record.setdefault('reviews', [])
            record.setdefault('reference_refreshes', [])
            record.setdefault('review_revision', 0)
            record.setdefault('review', {'status': 'pending', 'case_revision': record['revision'],
                                         'assessment_run_id': record.get('current_run_id'), 'identity_verified': False})
            record['review_required'] = record['review']['status'] != 'reviewed'
            record.setdefault('mode', None)
            from .business_records import refresh_preparation_review
            refresh_preparation_review(record)
        elif kind == 'run':
            record.setdefault('research_task', record.get('snapshot', {}).get('research_task', 'visual_research'))
            record.setdefault('mode', 'skills')
            record.setdefault('review_required', True)
            record.setdefault('review_status', 'pending')
            record.setdefault('next_step', 'ask_user' if record.get('evidence_request') else
                              ('complete' if record['state'] == 'ready' else 'run_analysis'))
        return record

    @staticmethod
    def reset_review(case, run_id=None):
        case['review'] = {'status': 'pending', 'case_revision': case['revision'],
                          'assessment_run_id': run_id, 'identity_verified': False}
        case['review_required'] = True
        case['review_revision'] = case.get('review_revision', 0) + 1
        from .business_records import refresh_preparation_review
        refresh_preparation_review(case)

    @staticmethod
    def put(db, kind, record):
        db.execute('INSERT INTO records VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                   (kind, record['id'], dump(record)))

    def read(self, kind, identifier):
        with self.tx() as db:
            return self.get(db, kind, identifier)

    def listing(self, kind):
        with self.tx() as db:
            return [self.compatible(kind, json.loads(r[0])) for r in db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def mutate(self, route, body, callback):
        key, body_hash = route + ':' + body['request_id'], digest(body)
        with self.tx() as db:
            row = db.execute('SELECT hash,response FROM requests WHERE key=?', (key,)).fetchone()
            if row:
                if row[0] != body_hash:
                    raise Problem(409, '同一request_id不可用于不同内容')
                return json.loads(row[1])
            result = callback(db)
            db.execute('INSERT INTO requests VALUES (?,?,?)', (key, body_hash, dump(result)))
            return result

    def checked_case(self, db, identifier, revision, editable=True):
        case = self.get(db, 'case', identifier)
        if case['revision'] != revision:
            raise Problem(409, '案件已更新，请刷新后操作')
        if editable:
            for r in db.execute("SELECT data FROM records WHERE kind='run'"):
                run = json.loads(r[0])
                if run['case_id'] == identifier and run['state'] in ('queued', 'running'):
                    raise Problem(409, '案件仍在分析，请先取消或等待完成')
        return case

    def create_case(self, body):
        def create(db):
            case = {k: v for k, v in body.items() if k != 'request_id'}
            case.update(id=uid('case'), schema_version=4, revision=1, media=[], corrections=[], reviews=[], review_revision=0, mode=None,
                        created_at=time.time(), current_run_id=None, episode_id=uid('episode'))
            self.compatible('case', case)
            self.put(db, 'case', case)
            self.put(db, 'episode', {'id': case['episode_id'], 'model_calls': 0, 'tool_calls': 0,
                                    'seconds': 0, 'completed_rounds': 0})
            return case
        return self.mutate('case', body, create)

    def advance(self, db, case, action, detail):
        case['revision'] += 1
        case['activity'].append({'id': uid('activity'), 'action': action, 'detail': detail,
                                 'case_revision': case['revision'], 'at': time.time(),
                                 'actor': '本地操作人（身份未认证）'})
        self.reset_review(case)
        self.put(db, 'case', case)
        return case

    def update_research_task(self, identifier, body):
        def update(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            task = body['research_task']
            if task not in ('visual_research', 'documentary_audit'):
                raise Problem(422, '未知研究任务')
            if task == case['research_task']:
                return case
            if any(json.loads(row[0])['case_id'] == identifier for row in db.execute(
                    "SELECT data FROM records WHERE kind='run'")):
                raise Problem(409, '已有运行的案卷不可切换研究任务；请另建案卷')
            case['research_task'] = task
            return self.advance(db, case, 'research_task_changed', {'research_task': task})
        return self.mutate('research-task:' + identifier, body, update)

    def update_catalogue(self, identifier, body):
        def update(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            if case['workflow'] == body['workflow'] and case['catalogue'] == body['catalogue']:
                return case
            case['catalogue_history'] = case.get('catalogue_history', []) + [
                {'case_revision': case['revision'], 'workflow': case['workflow'],
                 'catalogue': deepcopy(case['catalogue'])}]
            case['workflow'], case['catalogue'] = body['workflow'], body['catalogue']
            return self.advance(db, case, 'catalogue', '更新器物档案与任务场景；信息由操作人登记')
        return self.mutate('catalogue:' + identifier, body, update)

    def select_analysis_media(self, identifier, body):
        def select(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            selected = body['media_ids']
            available = {m['id'] for m in case['media']}
            if len(selected) > 8 or len(selected) != len(set(selected)) or not set(selected) <= available:
                raise Problem(422, '本轮最多选用8张唯一的本案照片；其余照片保留在档案')
            if case['analysis_media_ids'] == selected and case['analysis_selection_explicit']:
                return case
            case['analysis_media_ids'] = selected
            case['analysis_selection_explicit'] = True
            return self.advance(db, case, 'analysis_selection',
                                f'明确本轮选用{len(selected)}张；档案共{len(case["media"])}张。未选照片不参与该轮推理。')
        return self.mutate('analysis-selection:' + identifier, body, select)

    def annotate(self, identifier, body):
        def add(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            if body['media_id'] not in {m['id'] for m in case['media']}:
                raise Problem(422, '人工观察必须定位本案已保存的图片')
            if len(case['annotations']) >= 100:
                raise Problem(413, '本案人工区域观察已达100条；请整理后另建研究任务')
            note = {k: body[k] for k in ('media_id', 'region', 'feature', 'observation')}
            note.update(id=uid('annotation'), created_at=time.time(), case_revision=case['revision'] + 1,
                        kind='operator_observation', identity_verified=False,
                        coordinate_space='exif-corrected-original-normalized')
            case['annotations'].append(note)
            self.advance(db, case, 'annotation', '登记人工区域观察；不是AI识别或专家认证')
            return {'case': case, 'annotation': note}
        return self.mutate('annotation:' + identifier, body, add)

    def link_document(self, identifier, body):
        def link(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            from .knowledge import KnowledgeStore
            source = KnowledgeStore(self.root).source(body['document_id'], body.get('document_revision'))['source']
            if body.get('document_sha256') and body['document_sha256'] != source['document_sha256']:
                raise Problem(409, '来源资料与所显示的哈希不一致，请重新阅读后关联')
            binding = {'document_id': source['id'], 'document_revision': source['revision'],
                       'document_sha256': source['document_sha256'], 'linked_case_revision': case['revision'] + 1}
            prior = next((d for d in case['knowledge_links'] if d['document_id'] == source['id']), None)
            if prior and all(prior[k] == binding[k] for k in ('document_revision','document_sha256')):
                return case
            if not prior and source['id'] not in case['knowledge_document_ids'] and len(case['knowledge_document_ids']) >= 30:
                raise Problem(413, '本案最多关联30份资料')
            if source['id'] not in case['knowledge_document_ids']:
                case['knowledge_document_ids'].append(source['id'])
            case.setdefault('knowledge_link_history', []).append(deepcopy(binding))
            case['knowledge_links'] = [d for d in case['knowledge_links'] if d['document_id'] != source['id']] + [binding]
            return self.advance(db, case, 'document_link',
                                f'明确关联资料第{source["revision"]}版及哈希；后续资料库更新不会改写本案依据')
        return self.mutate('document-link:' + identifier, body, link)

    @staticmethod
    def save_blob(db, raw, meta):
        identifier = uid('media')
        db.execute('INSERT INTO blobs VALUES (?,?,?)', (identifier, meta['mime'], raw))
        return dict(meta, id=identifier)

    def add_evidence(self, identifier, body):
        raw, meta = decode_image(body['image_base64'])
        metrics = measure_pixels(raw)
        def add(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            duplicate = next((m for m in case['media'] if m['sha256'] == meta['sha256']), None)
            if duplicate:
                return {'case': case, 'duplicate_media_id': duplicate['id']}
            if len(case['media']) >= 30:
                raise Problem(413, '本案档案照片达到30张上限；单轮研究另选最多8张关键图')
            media = self.save_blob(db, raw, meta)
            media.update({k: body[k] for k in ('filename', 'view', 'edit_declaration', 'source')})
            media['capture_role'] = body.get('capture_role', 'unknown')
            media['added_revision'] = case['revision'] + 1
            media['pixel_metrics'] = metrics
            media['view_verified'] = False
            case['media'].append(media)
            if not case['analysis_selection_explicit'] and len(case['analysis_media_ids']) < 8:
                case['analysis_media_ids'].append(media['id'])
            self.advance(db, case, 'photo', '保存原始照片；视角与处理情况由上传者声明')
            return {'case': case, 'media': media}
        return self.mutate('evidence:' + identifier, body, add)

    def label_capture(self, identifier, media_id, body):
        def label(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            media = next((m for m in case['media'] if m['id'] == media_id), None)
            if media is None:
                raise Problem(422, '视角标记只接受本案已保存的原照')
            from .photo_report import CAPTURE_LABELS
            if body['capture_role'] not in CAPTURE_LABELS:
                raise Problem(422, '未知视角标记')
            if media.get('capture_role', 'unknown') == body['capture_role'] and media['view'] == body['view']:
                return case
            media.update(capture_role=body['capture_role'], view=body['view'], view_verified=False)
            return self.advance(db, case, 'capture_label', {'media_id': media_id,
                'capture_role': body['capture_role'], 'notice': '操作人视角声明，不改变原图字节或认证画面。'})
        return self.mutate('capture-label:' + identifier + ':' + media_id, body, label)

    def add_reference(self, body):
        raw, meta = decode_image(body['image_base64'])
        def add(db):
            ref = {k: v for k, v in body.items() if k not in ('request_id', 'image_base64')}
            ref.update(id=uid('ref'), revision=1, media=self.save_blob(db, raw, meta))
            self.put(db, 'reference', ref)
            return ref
        return self.mutate('reference', body, add)

    @staticmethod
    def authorized_reference_hash(refs):
        return digest(sorted((ref for ref in refs if ref.get('permission') == 'local_use_authorized'),
                             key=lambda ref: ref['id']))

    def refresh_references(self, identifier, body):
        """Explicitly admit changed authorized reference material into a new case revision."""
        def refresh(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            if not case['current_run_id']:
                raise Problem(409, '请先完成初判；首次运行会读取当前授权参照')
            previous = self.get(db, 'run', case['current_run_id'])
            refs = [json.loads(row[0]) for row in db.execute("SELECT data FROM records WHERE kind='reference'")]
            current_hash = self.authorized_reference_hash(refs)
            previous_hash = case.get('reference_basis_hash') or self.authorized_reference_hash(previous['reference_snapshot'])
            if current_hash == previous_hash:
                return {'case': case, 'changed': False, 'reason': '授权参照未变化，案件版本与预算保持不变'}
            case['revision'] += 1
            case['reference_basis_hash'] = current_hash
            case['reference_refreshes'].append({
                'id': uid('refrefresh'), 'case_revision': case['revision'],
                'source_run_id': previous['id'], 'previous_hash': previous_hash,
                'current_hash': current_hash, 'authorized_reference_ids': sorted(
                    ref['id'] for ref in refs if ref.get('permission') == 'local_use_authorized'),
                'created_at': time.time(),
            })
            self.reset_review(case)
            self.put(db, 'case', case)
            return {'case': case, 'changed': True, 'reason': '授权参照已刷新，请执行本轮修订'}
        return self.mutate('refresh-references:' + identifier, body, refresh)

    def blob(self, identifier):
        with self.tx() as db:
            row = db.execute('SELECT mime,bytes FROM blobs WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise Problem(404, '文件不存在')
            return row[0], row[1]

    def start_run(self, identifier, body, versions, knowledge_snapshot=None):
        mode = body.get('mode', 'skills')
        if mode not in ('skills', 'plain') or versions.get('mode', 'skills') != mode:
            raise Problem(422, '运行模式与提示版本不一致')
        initial_case = self.read('case', identifier)
        research_task = initial_case['research_task']
        if versions.get('research_task', 'visual_research') != research_task:
            raise Problem(422, '研究任务与提示版本不一致')
        preflight = case_preflight(self, initial_case)
        if set(initial_case['knowledge_document_ids']) - {d['document_id'] for d in initial_case['knowledge_links']}:
            raise Problem(409, '旧案资料尚未绑定版本，请在资料库重新关联所需版本')
        if knowledge_snapshot is None:
            from .knowledge import KnowledgeStore
            knowledge_snapshot = KnowledgeStore(self.root).snapshot(bindings=initial_case['knowledge_links'])
        def start(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            if research_task != case['research_task']:
                raise Problem(409, '研究任务已变化，请重新运行')
            selected = case['analysis_media_ids'] if research_task == 'visual_research' else []
            if research_task == 'visual_research':
                if not case['media']:
                    raise Problem(422, '请先加入真实器物照片')
                if (not 1 <= len(selected) <= 8 or len(selected) != len(set(selected))
                        or not set(selected) <= {m['id'] for m in case['media']}):
                    raise Problem(422, '请明确选用1–8张本案关键照片；未选图只归档，不进入该轮')
            elif not has_documentary_text(self, case, knowledge_snapshot):
                raise Problem(422, '文字凭据核查须先登记许可TXT附件或关联含授权正文的固定版本资料；来源卡和PDF尚不可读')
            prior_modes = {json.loads(row[0]).get('mode', 'skills') for row in db.execute(
                "SELECT data FROM records WHERE kind='run'") if json.loads(row[0])['case_id'] == identifier}
            if (case.get('mode') and case['mode'] != mode) or prior_modes - {mode}:
                raise Problem(409, '同案不可切换模式作为补证；请克隆为独立对照案件')
            if preflight['case_revision'] != case['revision']:
                raise Problem(409, '预检期间案件已更新，请重新运行')
            ep = self.get(db, 'episode', case['episode_id'])
            if ep['completed_rounds'] >= 3:
                raise Problem(409, '已完成初判及两轮补证，请导出并交专业人士复核')
            if ep['model_calls'] >= 36 or ep['tool_calls'] >= 60 or ep['seconds'] >= 900:
                raise Problem(409, '本案累计预算耗尽')
            parent = case['current_run_id']
            if parent and self.get(db, 'run', parent)['case_revision'] == case['revision']:
                raise Problem(409, '本版本已有意见；请补证或登记订正后再运行')
            refs = [json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='reference'")]
            case['mode'] = mode
            case['reference_basis_hash'] = self.authorized_reference_hash(refs)
            snapshot = deepcopy(case)
            snapshot['media'] = [m for m in case['media'] if m['id'] in selected]
            snapshot['analysis_scope'] = {
                'selected_media_ids': list(selected), 'archive_media_count': len(case['media']),
                'omitted_media_ids': [m['id'] for m in case['media'] if m['id'] not in selected],
                'notice': ('文字凭据核查只读取获许可的文字材料；未观察档案图片，PDF未OCR。'
                           if research_task == 'documentary_audit' else
                           '意见仅覆盖本轮明确选用的图片；档案其余图片未被本轮视觉模型观察。')}
            run = {'id': uid('run'), 'case_id': identifier, 'case_revision': case['revision'],
                   'episode_id': case['episode_id'], 'parent_run_id': parent, 'snapshot': snapshot,
                   'research_task': research_task, 'reference_snapshot': refs, 'versions': deepcopy(versions), 'state': 'queued', 'mode': mode,
                   'preflight': preflight, 'next_step': 'run_analysis', 'review_required': True, 'review_status': 'pending',
                   'model_calls': 0, 'tool_calls': 0, 'seconds': 0, 'events': [],
                   'observations': [], 'assessment': None, 'evidence_request': None,
                   'loaded_skills': {}, 'created_at': time.time()}
            run['knowledge_snapshot'] = deepcopy(knowledge_snapshot)
            run['versions']['knowledge_snapshot_sha256'] = knowledge_snapshot['snapshot_sha256']
            critics = [json.loads(row[0]) for row in db.execute("SELECT data FROM records WHERE kind='text_review'")]
            successful = [r for r in critics if r['assessment_run_id'] == parent and r['state'] == 'succeeded']
            run['text_review_snapshot'] = ({k: successful[-1][k] for k in
                ('id', 'packet_hash', 'permission', 'result', 'model')} if successful else None)
            run['input_hash'] = digest({'case': snapshot, 'refs': refs, 'versions': run['versions'], 'mode': mode,
                                        'text_review': run['text_review_snapshot'],
                                        'analysis_scope': snapshot['analysis_scope'],
                                        'knowledge_snapshot_sha256': knowledge_snapshot['snapshot_sha256']})
            self.put(db, 'case', case)
            self.put(db, 'run', run)
            return {'run_id': run['id'], 'state': 'queued', 'mode': mode, 'research_task': research_task}
        return self.mutate('run:' + identifier, body, start)

    def update_run(self, identifier, callback):
        with self.tx() as db:
            run = self.get(db, 'run', identifier)
            callback(run)
            self.put(db, 'run', run)
            return run

    def charge(self, identifier, counter=None):
        with self.tx() as db:
            run = self.get(db, 'run', identifier)
            if run['state'] != 'running':
                raise Problem(409, '运行已取消或不在执行状态')
            ep = self.get(db, 'episode', run['episode_id'])
            elapsed = max(0, time.time() - run['started_at'])
            ep['seconds'] += max(0, elapsed - run['seconds'])
            run['seconds'] = elapsed
            if elapsed >= 300 or ep['seconds'] >= 900:
                raise Problem(409, '主动计算时间预算耗尽')
            if counter:
                limit = 12 if counter == 'model_calls' else 20
                total_limit = 36 if counter == 'model_calls' else 60
                if run[counter] >= limit or ep[counter] >= total_limit:
                    raise Problem(409, '模型或工具调用预算耗尽')
                run[counter] += 1
                ep[counter] += 1
            self.put(db, 'run', run)
            self.put(db, 'episode', ep)
            return min(300 - elapsed, 900 - ep['seconds'])

    def finish(self, identifier, state, error=None):
        with self.tx() as db:
            run = self.get(db, 'run', identifier)
            if run['state'] not in ('queued', 'running'):
                return run
            ep = self.get(db, 'episode', run['episode_id'])
            elapsed = min(300, max(0, time.time() - run.get('started_at', time.time())))
            ep['seconds'] += max(0, elapsed - run['seconds'])
            run.update(state=state, seconds=max(run['seconds'], elapsed), error=error, ended_at=time.time())
            if state not in ('ready', 'waiting_evidence') and run.get('research_task') == 'documentary_audit' and run.get('assessment'):
                run['discarded_assessment_sha256'] = digest(run['assessment'])
                run['assessment'] = None
            if state in ('ready', 'waiting_evidence'):
                case = self.get(db, 'case', run['case_id'])
                if case['revision'] != run['case_revision']:
                    raise Problem(409, '旧任务不能覆盖新版本')
                case['current_run_id'] = identifier
                self.reset_review(case, identifier)
                run['next_step'] = 'ask_user' if run['evidence_request'] else 'complete'
                run['review_required'] = True
                run['review_status'] = 'pending'
                self.put(db, 'case', case)
                ep['completed_rounds'] += 1
            self.put(db, 'episode', ep)
            self.put(db, 'run', run)
            return run

    def recover(self):
        for run in self.listing('run'):
            if run['state'] in ('queued', 'running'):
                self.finish(run['id'], 'interrupted', '服务重启：旧过程已中断，可重新运行；累计预算保留')
        for review in self.listing('text_review'):
            if review['state'] == 'running':
                with self.tx() as db:
                    latest = self.get(db, 'text_review', review['id'])
                    if latest['state'] != 'running':
                        continue
                    elapsed = min(60, max(0, time.time()-latest['started_at']))
                    latest.update(state='interrupted', error='服务重启：文字审查外部完成状态未知，不自动重试', elapsed=elapsed)
                    ep = self.get(db, 'episode', latest['episode_id'])
                    ep['seconds'] += elapsed
                    self.put(db, 'episode', ep)
                    self.put(db, 'text_review', latest)
        for audit in self.listing('nvidia_audit'):
            if audit['state'] in ('prepared', 'running'):
                with self.tx() as db:
                    latest = self.get(db, 'nvidia_audit', audit['id'])
                    if latest['state'] in ('prepared', 'running'):
                        latest.update(state='interrupted', result=None,
                                      error='服务重启：NVIDIA引用核查已中断，未修改研究意见。')
                        self.put(db, 'nvidia_audit', latest)

    @staticmethod
    def checked_review_method(case, body):
        method = body.get('review_method')
        if case.get('research_task', 'visual_research') == 'documentary_audit':
            if method != 'document':
                raise Problem(422, '文字凭据核查的人工复核或订正须使用document资料核对方式')
        elif method == 'document':
            raise Problem(422, '视觉研究复核仍须明确image或in_person方式')

    def add_correction(self, identifier, body, reviewer):
        def add(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            self.checked_review_method(case, body)
            run = self.get(db, 'run', body['assessment_run_id'])
            if run['case_id'] != identifier or run['state'] not in ('ready', 'waiting_evidence'):
                raise Problem(422, '订正必须关联本案已完成的意见')
            correction = {k: v for k, v in body.items() if k not in ('request_id', 'expected_case_revision')}
            correction.update(id=uid('review'), reviewer=reviewer,
                              identity_verified=False, created_at=time.time())
            case['corrections'].append(correction)
            case['revision'] += 1
            self.reset_review(case)
            self.put(db, 'case', case)
            return case
        return self.mutate('correction:' + identifier, body, add)


    def add_review(self, identifier, body, reviewer):
        def add(db):
            case = self.checked_case(db, identifier, body['expected_case_revision'])
            self.checked_review_method(case, body)
            if body['expected_review_revision'] != case['review_revision']:
                raise Problem(409, '人工复核状态已更新，请刷新后操作')
            run = self.get(db, 'run', body['assessment_run_id'])
            if (run['case_id'] != identifier or run['state'] not in ('ready', 'waiting_evidence')
                    or case['current_run_id'] != run['id'] or run['case_revision'] != case['revision']):
                raise Problem(409, '只能复核当前证据版本的已完成意见；旧意见不能放行新证据')
            if body['status'] not in ('reviewed', 'request_evidence'):
                raise Problem(422, '未知复核状态')
            review = {k: v for k, v in body.items()
                      if k not in ('request_id', 'expected_case_revision', 'expected_review_revision')}
            review.update(id=uid('review'), reviewer=reviewer, identity_verified=False,
                          case_revision=case['revision'], created_at=time.time(),
                          review_revision=case['review_revision'] + 1)
            case['reviews'].append(review)
            case['review'] = dict(review)
            case['review_revision'] += 1
            case['review_required'] = review['status'] != 'reviewed'
            run['review_status'] = review['status']
            run['review_required'] = case['review_required']
            # A review never removes the model's unresolved evidence request.
            run['next_step'] = 'ask_user' if run.get('evidence_request') or review['status'] == 'request_evidence' else 'complete'
            self.put(db, 'case', case)
            self.put(db, 'run', run)
            return case
        return self.mutate('review:' + identifier, body, add)
