"""Professional preparation workflow, independent of model-generated judgments."""
import base64
import html
import json
from .store import digest
from .visual_tools import derivative
from .preflight import has_documentary_text

WORKFLOWS = {
    'museum': ('博物馆编目与研究', '编目草稿、图像观察、来源与状况材料，交馆内专业人员复核'),
    'collection': ('收藏档案与购藏研究', '区分持有人主张、来源材料与可观察事实，整理待核问题'),
    'auction': ('拍卖征集与图录研究', '形成有依据的图录准备材料；归属措辞与状况说明分别复核'),
}
CATALOGUE_LABELS = {
    'inventory_number': '登记编号', 'object_name': '器物名称（登记）', 'object_type': '器类（登记）',
    'material': '材料（登记）', 'decoration': '装饰描述', 'dimensions': '尺寸与测量方式',
    'inscription': '款识与文字', 'provenance': '来源经历与材料线索',
    'condition_note': '状况与已知处理', 'requested_output': '本次所需成果',
}
FEATURE_LABELS = {'foot': '底足', 'glaze': '釉面', 'decoration': '纹饰', 'inscription': '款识',
                  'body': '器形/胎体', 'damage': '损伤/处理', 'other': '其他部位'}


def workplan(case, knowledge_sources=None):
    catalogue = case.get('catalogue', {})
    workflow = case.get('workflow', 'museum')
    selected = set(case.get('analysis_media_ids', []))
    tasks = []
    def task(identifier, title, present, workspace, detail):
        tasks.append({'id': identifier, 'title': title, 'state': 'recorded' if present else 'missing',
                      'workspace': workspace, 'detail': detail})
    task('identity', '登记器物名称与编号', bool(catalogue.get('object_name') and catalogue.get('inventory_number')),
         'catalogue', '登记内容是操作人提供的信息，尚未作身份或归属认证。')
    task('measure', '记录尺寸及测量条件', bool(catalogue.get('dimensions')), 'catalogue',
         '图像没有可靠尺度时不能估算实物尺寸。')
    task('provenance', '整理来源经历与支持材料', bool(case.get('provenance_events')), 'catalogue',
         '持有人自述、旧标签、票据和机构记录要分别注明；缺口不以猜测补齐。')
    task('condition', '登记状况及已知处理', bool(case.get('condition_checks')), 'catalogue',
         '状况不是年代或真伪结论；看不到的修复或表面处理应保留未知。')
    if case.get('research_task') == 'documentary_audit':
        task('documents', '准备可读的许可文字材料',
             has_documentary_text(None, case, {'sources': knowledge_sources or []}), 'catalogue',
             '本案许可TXT或已固定的授权正文可核查；来源卡与PDF目录不能代替正文，PDF未OCR。')
    else:
        task('photos', '明确本轮关键照片', 1 <= len(selected) <= 8, 'images',
             f'本轮选用{len(selected)}张，档案共{len(case.get("media", []))}张；其余照片不进入本轮推理。')
        task('regions', '记录可定位的部位观察', bool(case.get('annotations')), 'images',
             '区域标记是操作人观察，需区分可见现象、解释和未观察的限制。')
    task('sources', '关联固定版本的来源资料', bool(case.get('knowledge_links')), 'knowledge',
         '有来源不代表主张成立；阅读定位段落、适用范围与限制。')
    preparation_review = case.get('preparation_review', {})
    task('review', '记录资料复核与待办', preparation_review.get('state') == 'reviewed'
         and not preparation_review.get('stale'), 'review',
         '本机记录的操作人身份未认证；复核记录不自动成为机构或专家背书。')
    return {'workflow': workflow, 'title': WORKFLOWS[workflow][0], 'deliverable': WORKFLOWS[workflow][1],
            'tasks': tasks, 'recorded': sum(t['state'] == 'recorded' for t in tasks),
            'total': len(tasks), 'notice': '材料登记状态，不是质量分、真实性概率或业务审批。'}


def preparation_bundle(case, documents):
    value = {'schema_version': 4, 'report_kind': 'research_preparation', 'case': case,
             'documents': documents, 'workplan': workplan(case, documents),
             'notice': '研究准备档案：包含人工登记、图像和资料线索；不是AI鉴定意见、实物认证或已审核图录。',
             'expert_reviewed': False, 'model_inference_included': False}
    value['bundle_sha256'] = digest(value)
    return value


def preparation_markdown(bundle):
    case = bundle['case']; role = WORKFLOWS[case.get('workflow', 'museum')]
    lines = ['# 瓷证 · 研究准备档案', '', case['title'], '', bundle['notice'], '',
             '## 任务与范围', role[0], role[1], case['question'],
             f'案卷第{case["revision"]}版。档案照片{len(case.get("media", []))}张；本轮选用{len(case.get("analysis_media_ids", []))}张。',
             ('任务：已读文字凭据核查；照片不进入本轮推理。' if case.get('research_task') == 'documentary_audit'
              else '所选图片只是研究范围；当前文件未包含模型推理。'), '', '## 器物登记']
    for key, label in CATALOGUE_LABELS.items():
        lines.append(label + '：' + (case.get('catalogue', {}).get(key) or '未登记'))
    lines += ['', '## 来源声明', case['source_declaration'], '拟核查归属：' + case['target_attribution'],
              '', '## 来源事件与可回查凭据（事实未核验）']
    event_types = {'acquired':'购入/取得记录','auction':'上拍记录','exhibition':'展览记录',
                   'publication':'出版记录','transfer':'流转记录','statement':'陈述','gap':'来源缺口'}
    event_states = {'declared':'声明待核','documented':'已定位资料，事实待核','disputed':'材料存在冲突','gap':'缺口未补齐'}
    for event in case.get('provenance_events', []):
        lines += ['', '### '+event['date_text']+' · '+event_types[event['event_type']],
                  event['description'], '相关方：'+(event['party'] or '未登记')+'；地点：'+(event['place'] or '未登记'),
                  '与本件器物的联系依据：'+event['object_link_basis'],
                  '记录状态：'+event_states[event['status']]]
        if event.get('supersedes'): lines.append('补正前一事件：'+event['supersedes']+'；原始记录保留。')
        for evidence in event.get('evidence', []):
            lines.append('凭据：'+evidence['kind']+' · '+evidence['document_id']+' · '+evidence['locator'])
            if evidence['kind'] == 'knowledge':
                lines.append('资料第'+str(evidence['revision'])+'版；文档哈希：'+evidence['document_sha256']+'；段落哈希：'+evidence['chunk_sha256'])
            else:
                lines.append('文件哈希：'+evidence['sha256']+'；附件页码/位置由操作人声明，系统未解析或验证该记载。')
    if not case.get('provenance_events'): lines.append('尚无结构化来源事件；自述备注不能代替来源证据。')
    lines += ['', '## 状况检查记录（与归属意见分开）']
    methods = {'image':'照片观察','in_person':'实物检查（操作人声明）','document':'资料核对'}
    for check in case.get('condition_checks', []):
        lines += ['', '### '+check['date_text']+' · '+check['area'],
                  '方式：'+methods[check['method']]+'；观察者：'+check['observer']+'（身份未认证）',
                  check['observation'], '限制：'+'；'.join(check['limitations']),
                  '关联原照：'+('、'.join(check['media_ids']) or '未关联；不能理解为AI已经看图')]
        for evidence in check.get('evidence', []):
            lines.append('状况凭据：'+evidence['document_id']+'；'+evidence['locator'])
            if evidence['kind'] == 'knowledge':
                lines.append('资料版本：'+str(evidence['revision'])+'；段落SHA256：'+evidence['chunk_sha256'])
            else:
                lines.append('原文件SHA256：'+evidence['sha256']+'；页码/位置由操作人登记，未解析正文。')
        if check.get('located_evidence_status') == 'legacy_unlocated_operator_declaration':
            lines.append('旧请求未登记定位凭据，仅为操作人声明；不视作有依据的资料核对。')
    if not case.get('condition_checks'): lines.append('尚未登记检查；未发现记录不表示完好或无修复。')
    lines += ['', '## 原始凭据附件清单']
    for document in case.get('evidence_documents', []):
        lines += [document['filename']+' · '+document['id'], '来源：'+document['source'],
                  '使用依据：'+document['rights_note'], '原文件SHA256：'+document['sha256'],
                  '系统只保存原文件，未执行或鉴定文档；独立原文件需在本机附件入口下载。']
    lines += ['', '## 可定位人工观察（身份未认证）']
    if not case.get('annotations'): lines.append('尚无人工区域观察；空白不等于无损伤或无修复。')
    for note in case.get('annotations', []):
        lines += ['', '### ' + FEATURE_LABELS[note['feature']] + ' · ' + note['id'],
                  note['observation'], '图片：' + note['media_id'] + '；EXIF校正后原图区域：' + str(note['region']),
                  '记录类型：操作人观察，未作专家身份认证。']
    lines += ['', '## 关联资料与定位']
    for document in bundle['documents']:
        source = document['source']
        lines += ['', '### ' + source['title'], '来源机构：' + source['institution'],
                  '页面：' + source['source_url'], '资料定位：' + source['locator'],
                  '摘要/记录作者：'+source.get('author', '未登记')+'；不是原机构审核或专家背书。',
                  '适用范围：' + source['scope'], '限制：' + '；'.join(source['limitations']),
                  '使用依据：' + source['rights_note'], '方法审核状态：' + source['review_status'],
                  f'资料版本：{source["revision"]}；SHA256：{source["document_sha256"]}']
        for chunk in document.get('chunks', []):
            lines += ['定位段落：' + chunk['locator'], chunk['text'],
                      '段落ID：'+chunk['chunk_id']+'；SHA256：'+chunk['chunk_sha256']]
    if not bundle['documents']: lines.append('尚未关联资料；没有预填的检索结果或专业结论。')
    lines += ['', '## 准备资料人工复核记录']
    review = case.get('preparation_review', {})
    lines.append('当前状态：'+review.get('state','pending')+'；资料复核修订：'+str(case.get('preparation_review_revision',0)))
    for entry in case.get('preparation_reviews', []):
        lines += [f'针对案卷第{entry["case_revision"]}版，复核记录第{entry["review_revision"]}版；{entry["reviewer"]}（身份未认证）。',
                  entry['state']+'：'+entry['note'], '依据：'+entry['basis']]
    lines.append('后续材料变化会使旧版资料复核过期；此记录不代替视觉模型意见复核。')
    lines += ['', '## 材料待办']
    for item in bundle['workplan']['tasks']:
        lines.append(('已登记' if item['state'] == 'recorded' else '待补充') + ' · ' + item['title'] + '：' + item['detail'])
    lines += ['', '## 图像清单与原始哈希']
    for media in case.get('media', []):
        lines += [media['filename'] + ' · ' + media['id'],
                  '声明视角：' + media['view'] + '；来源：' + media['source'], 'SHA256：' + media['sha256']]
    lines += ['', '## 追溯标识', '资料准备包SHA256：' + bundle['bundle_sha256'],
              '正文中的登记、摘要与观察不能代替实物检查、来源证明或专业复核。']
    return '\n'.join(lines)


def preparation_html(bundle, get_blob):
    escape = lambda value: html.escape(str(value), quote=True)
    sections = []
    for line in preparation_markdown(bundle).splitlines():
        if not line: continue
        level = 3 if line.startswith('### ') else 2 if line.startswith('## ') else 1 if line.startswith('# ') else 0
        tag = 'h' + str(level) if level else 'p'
        sections.append('<' + tag + '>' + escape(line[level + 1:] if level else line) + '</' + tag + '>')
    case = bundle['case']; show_ids = set(case.get('analysis_media_ids', []))
    show_ids.update(a['media_id'] for a in case.get('annotations', []))
    sections.append('<h2>选用及人工观察关联图像</h2><p>原始文件未改写；区域框是人工记录，不能理解为模型或专家识别。</p>')
    for media in case.get('media', []):
        if media['id'] not in show_ids: continue
        _, raw = get_blob(media['id']); data, _ = derivative(raw, media['id'])
        sections.append('<figure><div class="image"><img alt="档案关联图片" src="data:image/jpeg;base64,' + base64.b64encode(data).decode() + '">')
        for note in case.get('annotations', []):
            if note['media_id'] != media['id']: continue
            x0, y0, x1, y1 = note['region']
            sections.append('<div class="box" style="left:%.3f%%;top:%.3f%%;width:%.3f%%;height:%.3f%%"></div>' % (x0*100,y0*100,(x1-x0)*100,(y1-y0)*100))
        sections.append('</div><figcaption>' + escape(media['filename']) + ' · ' + escape(media['sha256']) + '</figcaption></figure>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>瓷证研究准备档案</title><style>body{max-width:960px;margin:0 auto;padding:40px;color:#192a39;background:#f9f8f3;font:15px/1.9 system-ui}h1,h2,h3{line-height:1.45}h2{margin-top:36px;border-bottom:1px solid #d2d7db;padding-bottom:10px}p{white-space:pre-wrap;overflow-wrap:anywhere}figure{margin:24px 0;break-inside:avoid}.image{position:relative;width:fit-content;max-width:100%}img{display:block;max-height:650px;max-width:100%}.box{position:absolute;box-sizing:border-box;border:2px solid #b97a31}figcaption{font-size:12px;overflow-wrap:anywhere}@media print{body{background:white;padding:0}}</style><body>''' + ''.join(sections) + '</body></html>'
