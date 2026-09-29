import asyncio
import fcntl
import html
import json
import os
import secrets
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import schemas as S
from . import __version__
from .agent import Engine, ROOT, LocalModel
from .preflight import case_preflight
from .store import Store, Problem, dump, uid
from .review_client import ReviewService, prepare_review, suggested_packet
from .agent import skill_catalog
from .visual_tools import derivative
from .reporting import markdown_report, html_report
from .knowledge import KnowledgeStore
from .knowledge_api import create_knowledge_router
from .knowledge_seed import seed_knowledge
from .pro_workflow import workplan, preparation_bundle, preparation_markdown, preparation_html
from .business_records import create_business_router
from .handoff import case_documents, make_handoff, check_case_files
from .photo_report import photo_report
from .nvidia_runtime import NvidiaAudit
from .risk_triage import create_risk_router
from .device_capture import create_device_router


def export_bundle(store, case, run):
    # A report may contain this case's evidence, but must not dump unrelated
    # private library material that happened to share the immutable run index.
    exported_run = deepcopy(run)
    snapshot = exported_run.pop('knowledge_snapshot', None)
    citations = (run.get('assessment') or {}).get('knowledge_citations', [])
    read_ids = {c['document_id'] for c in run.get('read_knowledge', [])}
    cited_ids = {c['document_id'] for c in citations}
    read_chunks = {(c['document_id'], c['chunk_id']) for c in run.get('read_knowledge', [])}
    read_chunks.update((c['document_id'], c['chunk_id']) for c in citations)
    knowledge_sources = [{'source': d['source'], 'chunks': [c for c in d['chunks']
                          if (d['source']['id'], c['chunk_id']) in read_chunks]}
                         for d in (snapshot or {}).get('sources', []) if d['source']['id'] in read_ids | cited_ids]
    exported_run['knowledge_commitment'] = {
        'snapshot_sha256': (snapshot or {}).get('snapshot_sha256'),
        'index_version': (snapshot or {}).get('index_version'),
        'export_scope': 'only actually read or cited sources; full input retained in local run record',
        'full_snapshot_included': False}
    reference_ids = set((run.get('assessment') or {}).get('reference_ids', []))
    reference_ids.update(run.get('read_references', []))
    exported_run['reference_snapshot'] = [r for r in exported_run['reference_snapshot']
                                          if r['id'] in reference_ids]
    return {'schema_version': 4, 'case': case, 'run': exported_run, 'knowledge_sources': knowledge_sources,
            'photo_report': photo_report(exported_run),
            'mode': run.get('mode', 'skills'), 'preflight': case_preflight(store, case, run),
            'review': case.get('review'), 'review_required': case.get('review_required', True),
            'expert_reviewed': False,
            'notice': ('文字凭据核查；仅核查已读材料，不作实物归属、真伪或所有权认证。'
                       if run.get('research_task') == 'documentary_audit' else
                       '照片辅助研究意见；不是实物真伪认证。复核记录不自动改写模型原意见。'),
            'episode': store.read('episode', case['episode_id']),
            'nvidia_audits': [r for r in store.listing('nvidia_audit')
                              if r['case_id'] == case['id'] and r['assessment_run_id'] == run['id']],
            'text_reviews': [r for r in store.listing('text_review') if r['case_id'] == case['id']]}




def create_app(data_dir=None, model=None, review_client=None):
    store = Store(data_dir or os.getenv('CIZHENG_DATA_DIR', str(ROOT / 'data')))
    engine = Engine(store, model)
    critic = ReviewService(store, review_client)
    knowledge = KnowledgeStore(store.root)
    nvidia_audit = NvidiaAudit(store)
    seed_knowledge(knowledge)
    session_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        with (store.root / 'server.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('此数据库已有工作台运行；只允许一个服务进程') from exc
            store.recover()
            try:
                yield
            finally:
                for task in list(engine.tasks.values()):
                    task.cancel()
                await asyncio.gather(*list(engine.tasks.values()), return_exceptions=True)
                fcntl.flock(lock, fcntl.LOCK_UN)

    app = FastAPI(title='瓷证 · 陶瓷证据研究工作台', version=__version__, lifespan=lifespan)
    app.state.store, app.state.engine = store, engine
    app.state.critic = critic
    app.state.knowledge = knowledge
    app.state.nvidia_audit = nvidia_audit
    app.include_router(create_knowledge_router(knowledge))
    app.include_router(create_business_router(store, knowledge))
    app.include_router(create_risk_router(store))
    app.include_router(create_device_router(store))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])

    @app.middleware('http')
    async def local_only(request, call_next):
        # Loopback UI, token-protected mutations, no CORS; do not expose publicly.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not secrets.compare_digest(request.headers.get('x-cizheng-token', ''), session_token):
                return JSONResponse({'detail': '请在本地工作台操作，或使用当前会话令牌'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '不接受跨站请求'}, status_code=403)
            # Limit streaming bodies too; never trust Content-Length alone.
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 29_000_000:
                    return JSONResponse({'detail': '请求过大'}, status_code=413)
            request._body = bytes(raw)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({'detail': exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_handler(request, exc):
        return JSONResponse({'detail': [{'loc': list(error['loc']), 'msg': error['msg'][:500],
                                        'type': error['type']} for error in exc.errors()[:20]]}, status_code=422)

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static/index.html')

    @app.get('/static/{name}')
    def static(name: str):
        if name not in ('app.js', 'style.css'):
            raise Problem(404, '文件不存在')
        return FileResponse(ROOT / 'static' / name)

    @app.get('/api/status')
    def status():
        return {'model_configured': engine.model.configured, 'model': engine.model.identity(),
                'harness': engine.harness_identity(),
                'action_transport': engine.action_transport_identity(),
                'model_verified': False, 'hardware_verified': False,
                'model_adapter': 'local' if isinstance(engine.model, LocalModel) else 'injected_unverified',
                'preflight_available': True,
                'nvidia_nat_configured': nvidia_audit.configured,
                'nvidia_nat_scope': 'offline_saved_report_reference_identity_only',
                'app_version': __version__, 'text_review_configured': critic.client.configured,
                'text_review_model': critic.client.identity(),
                'session_token': session_token, 'reviewer': os.getenv('CIZHENG_REVIEWER', '本地操作人（身份未认证）'),
                'phase': '开发版；模型已配置不代表已通过视觉或Spark验收'}

    @app.get('/api/skills')
    def skills():
        from .agent import TOOLS
        result = []
        for skill in skill_catalog().values():
            missing = [t.strip() for t in skill['metadata'].get('required-tools', '').split(',')
                       if t.strip() and t.strip() not in TOOLS]
            result.append({k: skill[k] for k in ('name', 'description', 'compatibility', 'sha256', 'metadata')} |
                          {'resources': [p for p in skill['files'] if p != 'SKILL.md'],
                           'available': not missing, 'missing_tools': missing})
        return result

    @app.get('/api/cases')
    def cases():
        return store.listing('case')

    @app.post('/api/demo/guided')
    def guided_demo():
        # Local mutation middleware protects token / Origin; no model call.
        from .demo import import_guided_demos
        return import_guided_demos(store.root)

    @app.post('/api/cases')
    def new_case(body: S.NewCase):
        return store.create_case(body.model_dump())

    @app.get('/api/cases/{identifier}')
    def case(identifier: str):
        record = store.read('case', identifier)
        runs = [r for r in store.listing('run') if r['case_id'] == identifier]
        return {'case': record, 'runs': [dict(r, photo_report=photo_report(r)) for r in runs],
                'nvidia_audits': [r for r in store.listing('nvidia_audit') if r['case_id'] == identifier]}

    @app.patch('/api/cases/{identifier}/evidence/{media_id}/capture-label')
    def capture_label(identifier: str, media_id: str, body: S.CaptureLabelIn):
        return store.label_capture(identifier, media_id, body.model_dump())

    @app.post('/api/cases/{identifier}/nvidia-audits')
    async def audit_nvidia(identifier: str, body: S.NvidiaAuditIn):
        return await nvidia_audit.execute(identifier, body.model_dump())

    @app.patch('/api/cases/{identifier}/catalogue')
    def catalogue(identifier: str, body: S.CatalogueIn):
        return store.update_catalogue(identifier, body.model_dump())

    @app.patch('/api/cases/{identifier}/research-task')
    def research_task(identifier: str, body: S.ResearchTaskIn):
        return store.update_research_task(identifier, body.model_dump())

    @app.put('/api/cases/{identifier}/analysis-selection')
    def analysis_selection(identifier: str, body: S.AnalysisSelection):
        return store.select_analysis_media(identifier, body.model_dump())

    @app.post('/api/cases/{identifier}/annotations')
    def annotation(identifier: str, body: S.AnnotationIn):
        return store.annotate(identifier, body.model_dump())

    @app.post('/api/cases/{identifier}/documents')
    def document_link(identifier: str, body: S.CaseDocumentIn):
        return store.link_document(identifier, body.model_dump())

    @app.get('/api/cases/{identifier}/workplan')
    def get_workplan(identifier: str):
        case = store.read('case', identifier)
        sources = knowledge.snapshot(bindings=case['knowledge_links'])['sources']
        return workplan(case, sources)

    @app.post('/api/cases/{identifier}/dossier')
    def dossier(identifier: str, body: S.Revised):
        case = store.read('case', identifier)
        if case['revision'] != body.expected_case_revision:
            raise Problem(409, '案件已更新，请刷新后导出资料准备档案')
        bundle = preparation_bundle(case, case_documents(knowledge, case))
        def save(db):
            latest = store.get(db, 'case', identifier)
            if (latest['revision'] != case['revision'] or latest['preparation_review_revision'] !=
                    case['preparation_review_revision']):
                raise Problem(409, '导出期间案件已更新，请刷新后重试')
            check_case_files(case, lambda image_id: db.execute(
                'SELECT mime,bytes FROM blobs WHERE id=?', (image_id,)).fetchone())
            contents = [('.json', 'application/json', dump(bundle)),
                        ('.md', 'text/markdown', preparation_markdown(bundle)),
                        ('.html', 'text/html', preparation_html(bundle, lambda image_id: db.execute(
                            'SELECT mime,bytes FROM blobs WHERE id=?', (image_id,)).fetchone()))]
            artifacts = []
            for ext, mime, text in contents:
                artifact_id = uid('artifact')
                db.execute('INSERT INTO blobs VALUES (?,?,?)', (artifact_id, mime, text.encode()))
                artifacts.append({'id': artifact_id, 'filename': 'cizheng-preparation'+ext,
                                  'url': '/api/artifacts/' + artifact_id + '?download=1'})
            return {'artifacts': artifacts, 'case_revision': case['revision'],
                    'preparation_review_revision': case['preparation_review_revision'],
                    'report_kind': 'research_preparation', 'bundle_sha256': bundle['bundle_sha256']}
        return store.mutate('dossier:'+identifier, body.model_dump(), save)

    @app.post('/api/cases/{identifier}/handoff')
    def handoff(identifier: str, body: S.Revised):
        def save(db):
            case = store.checked_case(db, identifier, body.expected_case_revision, editable=False)
            bundle = preparation_bundle(case, case_documents(knowledge, case))
            raw, manifest = make_handoff(bundle, lambda asset_id: db.execute(
                'SELECT mime,bytes FROM blobs WHERE id=?', (asset_id,)).fetchone())
            import hashlib
            artifact_id = uid('artifact')
            db.execute('INSERT INTO blobs VALUES (?,?,?)', (artifact_id, 'application/zip', raw))
            return {'artifacts': [{'id': artifact_id, 'filename': 'cizheng-evidence-handoff.zip',
                                  'url': '/api/artifacts/' + artifact_id + '?download=1'}],
                    'case_revision': case['revision'], 'report_kind': 'research_preparation_handoff',
                    'bundle_sha256': bundle['bundle_sha256'],
                    'archive_sha256': hashlib.sha256(raw).hexdigest(), 'file_count': len(manifest['files'])+1}
        return store.mutate('handoff:'+identifier, body.model_dump(), save)

    @app.get('/api/cases/{identifier}/preflight')
    def preflight(identifier: str):
        record = store.read('case', identifier)
        run = store.read('run', record['current_run_id']) if record['current_run_id'] else None
        return case_preflight(store, record, run)

    @app.post('/api/cases/{identifier}/evidence')
    def evidence(identifier: str, body: S.EvidenceIn):
        return store.add_evidence(identifier, body.model_dump())

    @app.post('/api/cases/{identifier}/refresh-references')
    def refresh_references(identifier: str, body: S.Revised):
        return store.refresh_references(identifier, body.model_dump())

    @app.get('/api/references')
    def references():
        return store.listing('reference')

    @app.post('/api/references')
    def add_reference(body: S.ReferenceIn):
        return store.add_reference(body.model_dump())

    @app.post('/api/cases/{identifier}/runs', status_code=202)
    async def run(identifier: str, body: S.RunIn):
        current = store.read('case', identifier)
        task = current.get('research_task', 'visual_research')
        if not engine.model.configured:
            if task == 'documentary_audit':
                raise Problem(503, '本地文字研究模型尚未配置；附件已保存，未执行文字核查。')
            raise Problem(503, '本地视觉模型尚未配置。图片已保存，未执行鉴定；没有云端替代。')
        result = store.start_run(identifier, body.model_dump(), engine.versions(body.mode, task))
        engine.schedule(result['run_id'])
        return result

    @app.get('/api/runs/{identifier}')
    def get_run(identifier: str):
        return store.read('run', identifier)

    @app.post('/api/runs/{identifier}/cancel')
    async def cancel(identifier: str, body: S.Mutation):
        # Cancellation is inherently idempotent; terminal runs are unchanged.
        result = store.finish(identifier, 'cancelled', '本地操作人取消，累计预算保留')
        if identifier in engine.tasks:
            engine.tasks[identifier].cancel()
        return result

    @app.post('/api/cases/{identifier}/corrections')
    def correction(identifier: str, body: S.CorrectionIn):
        return store.add_correction(identifier, body.model_dump(), os.getenv('CIZHENG_REVIEWER', '本地操作人（身份未认证）'))

    @app.post('/api/cases/{identifier}/reviews')
    def review(identifier: str, body: S.ReviewIn):
        return store.add_review(identifier, body.model_dump(), os.getenv('CIZHENG_REVIEWER', '本地操作人（身份未认证）'))

    @app.get('/api/cases/{identifier}/text-review-preview')
    def text_preview(identifier: str):
        return suggested_packet(store, identifier)

    @app.get('/api/cases/{identifier}/text-reviews')
    def text_reviews(identifier: str):
        store.read('case', identifier)
        return [r for r in store.listing('text_review') if r['case_id'] == identifier]

    @app.post('/api/cases/{identifier}/text-reviews')
    def text_prepare(identifier: str, body: S.ReviewPacketIn):
        return prepare_review(store, identifier, body.model_dump())

    @app.post('/api/text-reviews/{identifier}/execute')
    async def text_execute(identifier: str, body: S.ReviewCallIn):
        return await critic.execute(identifier, body.model_dump())

    @app.post('/api/text-reviews/{identifier}/revise')
    def revise_from_critic(identifier: str, body: S.Revised):
        record = store.read('text_review', identifier)
        if record['state'] != 'succeeded':
            raise Problem(409, '仅已完成的文字审查可纳入修订')
        if body.expected_case_revision != record['case_revision']:
            raise Problem(409, '本案已更新；旧审查不能直接纳入新版本')
        return store.add_correction(record['case_id'],
            {'request_id': body.request_id, 'expected_case_revision': body.expected_case_revision,
             'assessment_run_id': record['assessment_run_id'], 'review_method': 'image',
             'correction': '请求对文字反证审查进行图像核验并逐项回应。',
             'basis': '已批准文字包 '+record['packet_hash']+'；审查 '+record['id']+'。该审查未查看原图，不是专家结论。'},
            '工作台操作人（纳入文字审查，身份未认证）')

    @app.get('/api/media/{identifier}/display')
    def display(identifier: str):
        mime, raw = store.blob(identifier)
        if mime not in ('image/jpeg', 'image/png'):
            raise Problem(422, '此文件不是器物图片')
        data, _ = derivative(raw, identifier)
        return Response(data, media_type='image/jpeg')

    @app.post('/api/cases/{identifier}/regions')
    def local_region(identifier: str, body: S.RegionIn):
        def save(db):
            case = store.checked_case(db, identifier, body.expected_case_revision, editable=False)
            accessible = {m['id'] for m in case['media']}
            refs = [json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='reference'")]
            accessible.update(r['media']['id'] for r in refs if r['permission'] == 'local_use_authorized')
            if body.media_id not in accessible:
                raise Problem(422, '局部查看只接受本案或已授权参照图')
            row = db.execute('SELECT bytes FROM blobs WHERE id=?', (body.media_id,)).fetchone()
            data, metadata = derivative(row[0], body.media_id, body.region)
            asset = store.save_blob(db, data, {'mime': 'image/jpeg'})
            result = dict(metadata, artifact_id=asset['id'], case_id=identifier, id=uid('region'),
                          case_revision=case['revision'], kind='user-selected-region-no-inference')
            store.put(db, 'view_region', result)
            return result
        return store.mutate('view-region:'+identifier, body.model_dump(), save)

    def current_bundle(identifier, revision):
        case = store.read('case', identifier)
        if case['revision'] != revision or not case['current_run_id']:
            raise Problem(409, '当前版本尚无完成的意见')
        run = store.read('run', case['current_run_id'])
        if run['case_revision'] != case['revision']:
            raise Problem(409, '已补证或订正，请先修订意见后导出当前版本')
        return export_bundle(store, case, run)

    @app.post('/api/cases/{identifier}/opinions/preview')
    def preview(identifier: str, body: S.Revised):
        return current_bundle(identifier, body.expected_case_revision)

    @app.post('/api/cases/{identifier}/exports')
    def export(identifier: str, body: S.Revised):
        bundle = current_bundle(identifier, body.expected_case_revision)
        def save(db):
            latest = store.get(db, 'case', identifier)
            if (latest['revision'] != bundle['case']['revision'] or latest['current_run_id'] != bundle['run']['id']
                    or latest.get('review_revision', 0) != bundle['case'].get('review_revision', 0)):
                raise Problem(409, '导出期间案件更新，请刷新后重试')
            check_case_files(bundle['case'], lambda image_id: db.execute(
                'SELECT mime,bytes FROM blobs WHERE id=?', (image_id,)).fetchone())
            md = markdown_report(bundle)
            contents = [('.json', 'application/json', dump(bundle)),
                        ('.md', 'text/markdown', md),
                        ('.html', 'text/html', html_report(bundle, lambda image_id: db.execute(
                            'SELECT mime,bytes FROM blobs WHERE id=?', (image_id,)).fetchone()))]
            artifacts = []
            for ext, mime, text in contents:
                artifact_id = uid('artifact')
                db.execute('INSERT INTO blobs VALUES (?,?,?)', (artifact_id, mime, text.encode()))
                artifacts.append({'id': artifact_id, 'filename': 'cizheng-report' + ext,
                                  'url': '/api/artifacts/' + artifact_id + '?download=1'})
            return {'artifacts': artifacts, 'case_revision': bundle['case']['revision']}
        return store.mutate('export:' + identifier, body.model_dump(), save)

    @app.get('/api/artifacts/{identifier}')
    def artifact(identifier: str, download: bool = False):
        mime, raw = store.blob(identifier)
        headers = {}
        if download or mime == 'application/pdf':
            suffix = {'application/json': 'json', 'text/markdown': 'md', 'text/html': 'html',
                      'image/png': 'png', 'image/jpeg': 'jpg', 'text/plain': 'txt', 'application/pdf': 'pdf',
                      'application/zip': 'zip'}.get(mime, 'bin')
            headers['Content-Disposition'] = 'attachment; filename="cizheng-' + identifier + '.' + suffix + '"'
        return Response(raw, media_type=mime, headers=headers)

    return app
