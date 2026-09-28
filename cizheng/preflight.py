"""Pixel measurements only. No calibration, semantic view verification or authentication."""
import io
from PIL import Image, ImageFilter, ImageStat

PREFLIGHT_VERSION = 'pixel-descriptive-v1'
NOTICE = '像素指标尚未用陶瓷照片校准；不据此判废图、AI生成、年代或真伪。上传视角仅为声明，未经验证。'


def measure_pixels(raw):
    with Image.open(io.BytesIO(raw)) as original:
        width, height = original.size
        gray = original.convert('L')
        gray.thumbnail((512, 512))
        histogram = gray.histogram()
        count = gray.width * gray.height
        stats = ImageStat.Stat(gray)
        # Edge response on a fixed maximum sampling size; descriptive, not a quality score.
        if gray.width >= 3 and gray.height >= 3:
            edge = gray.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128))
            response = ImageStat.Stat(edge.crop((1, 1, gray.width - 1, gray.height - 1)))
            sharpness = response.var[0]
        else:
            sharpness = None
        return {
            'version': PREFLIGHT_VERSION, 'width': width, 'height': height,
            'original_color_mode': original.mode, 'orientation': 'stored_pixels_no_exif_rotation',
            'sample_width': gray.width, 'sample_height': gray.height,
            'measurement_domain': 'all_metrics_on_resized_grayscale_sample',
            'luminance_mean_0_255': round(stats.mean[0], 4),
            'contrast_stddev_0_255': round(stats.stddev[0], 4),
            'dark_pixel_ratio_lte_5': round(sum(histogram[:6]) / count, 6),
            'bright_pixel_ratio_gte_250': round(sum(histogram[250:]) / count, 6),
            'edge_response_variance': round(sharpness, 4) if sharpness is not None else None,
            'sharpness_method': '512px_max_gray_clipped_laplacian_variance',
            'calibrated': False, 'quality_verdict': 'not_assessed',
        }


def has_documentary_text(store, case, knowledge_snapshot=None):
    """Only licensed TXT or nonempty text at the case's fixed source version."""
    if any(d.get('mime') == 'text/plain' and d.get('permission') == 'local_use_authorized'
           for d in case.get('evidence_documents', [])):
        return True
    if not case.get('knowledge_links'):
        return False
    if knowledge_snapshot is None:
        from .knowledge import KnowledgeStore
        from .store import Problem
        try:
            knowledge_snapshot = KnowledgeStore(store.root).snapshot(bindings=case['knowledge_links'])
        except Problem:
            return False
    pins = {(binding['document_id'], binding['document_revision'], binding['document_sha256'])
            for binding in case['knowledge_links']}
    return any((entry['source']['document_id'], entry['source']['revision'],
                entry['source']['document_sha256']) in pins and
               entry['source'].get('rights') == 'authorized_text' and
               any(chunk.get('text', '').strip() for chunk in entry.get('chunks', []))
               for entry in knowledge_snapshot.get('sources', []))


def case_preflight(store, case, run=None):
    if case.get('research_task') == 'documentary_audit':
        readable = has_documentary_text(store, case)
        request = (run.get('evidence_request') if run and run.get('case_revision') == case['revision'] else None)
        if not readable:
            request = {'view': '可定位的许可文字材料', 'reason': '尚无本案可读的许可正文；来源卡和PDF目录不能代替正文',
                       'capture_instructions': '登记已获本地使用许可的TXT，或关联含授权正文的固定版本资料；PDF未执行OCR。'}
        review = case.get('review', {})
        if review.get('status') == 'request_evidence' and review.get('case_revision') == case['revision']:
            request = {'view': '人工复核要求的文字补证', 'reason': review.get('basis', ''),
                       'capture_instructions': review.get('note', '')}
        return {'version': 'documentary-preflight-v1', 'case_id': case['id'], 'case_revision': case['revision'],
                'research_task': 'documentary_audit', 'images': [], 'errors': [], 'declared_views': [],
                'verified_views': [], 'semantic_view_verification': 'not_performed',
                'image_observation': 'not_performed', 'evidence_request': request,
                'next_step': 'ask_user' if request else ('complete' if run and run.get('case_revision') == case['revision']
                            and run.get('state') in ('ready', 'waiting_evidence') else 'ready_for_analysis'),
                'review_required': review.get('status') != 'reviewed', 'review_status': review.get('status', 'pending'),
                'notice': '文字材料准备情况；不要求照片，不读取PDF正文，不作器物鉴定。'}
    images, errors = [], []
    for media in case['media']:
        try:
            _, raw = store.blob(media['id'])
            metrics = measure_pixels(raw)
            images.append({'media_id': media['id'], 'original_sha256': media['sha256'], 'declared_view': media.get('view', '未知'),
                           'view_verified': False, 'metrics': metrics})
        except Exception as exc:
            # Corrupt historical files are reported without fabricating a measurement.
            errors.append({'media_id': media['id'], 'error': '像素读取失败：' + type(exc).__name__})
    missing = not case['media']
    request = None
    if missing:
        request = {'view': '器物原始照片', 'reason': '尚无图像，不能观察器物',
                   'capture_instructions': '上传未经美化的器物整体照片，并保留原始文件。'}
    elif errors:
        request = {'view': '可读取的原始图片', 'reason': '有原图无法读取',
                   'capture_instructions': '重新提供对应原始 JPEG 或 PNG。'}
    elif run and run.get('case_revision') == case['revision']:
        request = run.get('evidence_request')
    review = case.get('review', {'status': 'pending', 'identity_verified': False})
    if review.get('status') == 'request_evidence' and review.get('case_revision') == case['revision']:
        request = {'view': '人工复核要求的补证', 'reason': review.get('basis', ''),
                   'capture_instructions': review.get('note', '')}
    return {'version': PREFLIGHT_VERSION, 'case_id': case['id'], 'case_revision': case['revision'],
            'images': images, 'errors': errors, 'declared_views': [m.get('view', '未知') for m in case['media']],
            'verified_views': [], 'semantic_view_verification': 'not_performed',
            'next_step': 'ask_user' if request else ('complete' if run and run.get('case_revision') == case['revision'] and run.get('state') in ('ready', 'waiting_evidence') else 'ready_for_analysis'),
            'evidence_request': request, 'review_required': review.get('status') != 'reviewed',
            'review_status': review.get('status', 'pending'), 'notice': NOTICE}
