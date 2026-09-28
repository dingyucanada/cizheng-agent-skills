"""Readable research reports; machine provenance stays in the companion JSON."""
import base64
import html
import json
from .visual_tools import derivative
from .photo_report import photo_report, CAPTURE_LABELS

DIM={'period':'制作时期','kiln':'窑口归属','style':'装饰风格'}
STATUS={'supported':'当前资料支持','conflicting':'存在冲突','insufficient':'依据不足','out_of_scope':'专科范围外'}


def nvidia_audit_lines(bundle):
    """The same fixed-report audit scope is visible in both research tasks."""
    lines = ['', '## NVIDIA 引用身份核查（独立可选流程）']
    for audit in bundle.get('nvidia_audits', []):
        result = audit.get('result') or {}
        lines += ['核查记录：'+audit['id']+'；执行状态：'+audit['state'],
                  '源意见：'+audit['assessment_run_id']+'；资料第'+str(audit['source_case_revision'])+'版。',
                  '引用核查结果：'+result.get('status', '未完成')+'；模型调用：0。',
                  '知识快照SHA256：'+str(result.get('snapshot_sha256', '未完成')),
                  '只核对实际阅读知识引用的版本、哈希与定位；不认证资料文字、图像、归属或真伪。']
    if not bundle.get('nvidia_audits'):
        lines.append('本报告未执行独立 NVIDIA NAT 引用核查；原有读取合同继续保留。')
    return lines


def markdown_report(bundle):
    if bundle['run'].get('research_task', 'visual_research') == 'documentary_audit':
        return documentary_report(bundle)
    case,run=bundle['case'],bundle['run'];assessment=run['assessment'] or {}
    lines=['# 瓷证 · '+case['title'],'',bundle['notice'],'',
        f"资料第{case['revision']}版；运行状态：{run['state']}。当前复核：{(bundle.get('review') or {}).get('status','pending')}。",'',
        '## 研究问题',case['question'],'','## 来源声明',case['source_declaration']]
    scope = run['snapshot'].get('analysis_scope', {})
    lines += ['', '## 本轮图像范围',
              f'本轮选用{len(run["snapshot"]["media"])}张；本案档案共{scope.get("archive_media_count",len(case["media"]))}张。',
              scope.get('notice', '意见只覆盖本轮明确保存的输入。'),
              '未选图片：'+('、'.join(scope.get('omitted_media_ids', [])) or '无'),
              '', '## 器物登记（由操作人提供，未作认证）']
    from .pro_workflow import CATALOGUE_LABELS
    for key, label in CATALOGUE_LABELS.items():
        lines.append(label+'：'+(case.get('catalogue', {}).get(key) or '未登记'))
    indicators = photo_report(run)
    capture = indicators['capture_coverage']
    observed = indicators['photo_observation_coverage']
    lines += ['', '## 多图研判 · 指数与适用范围',
              f'采集覆盖指数：{capture["value"]}/100（{capture["numerator"]}/{capture["denominator"]}类上传者视角标记）。',
              capture['meaning'], *capture['limitations'],
              '待标记 / 补拍：'+('、'.join(CAPTURE_LABELS[r] for r in capture['missing_roles']) or '通用采集类别已标记，仍须核对实际画面。'),
              f'有模型区域观察记录：{observed["observed_count"]}/{observed["selected_count"]}张本轮原照。',
              observed['meaning'], '真品概率：尚不可估计（not_calibrated，数值为null）。',
              '拟核查归属：'+indicators['authenticity_probability']['target_attribution'],
              indicators['authenticity_probability']['reason'], indicators['notice'],
              '', '## 每张照片的细节与解释']
    for item in indicators['photos']:
        lines += ['', '### '+item['filename']+' · '+item['media_id'],
                  '上传者视角标记：'+CAPTURE_LABELS.get(item['capture_role'], '未标记')+'；原视角声明：'+item['declared_view'],
                  '原图SHA256：'+str(item['sha256'])]
        for observation in item['observations']:
            lines += ['定位 '+observation['id']+'：'+str(observation['region']),
                      '可见现象：'+observation['visible'],
                      '解释：'+(observation.get('interpretation') or '未作解释'),
                      '限制：'+(observation.get('limitation') or '未另登记')]
        if not item['observations']:
            lines.append('本轮没有该图的区域观察记录；不能据此声称已研究此图。')
    lines += ['', '## 归属意见 · 判断理由与反证']
    for claim in assessment.get('claims',[]):
        lines += ['', '### '+DIM[claim['dimension']]+'：'+claim['candidate'],
            '状态：'+STATUS[claim['status']],claim['reasoning_summary'],
            '支持观察：'+('、'.join(claim['support']) or '未登记'),
            '冲突观察：'+('、'.join(claim['conflict']) or '未登记')]
    lines += ['', '## 状况疑点与解释（需回查）'] + (assessment.get('condition_hypotheses', []) or ['本轮未登记状况解释；不表示没有损伤或修复。'])
    lines += ['', '## 竞争解释']+assessment.get('alternatives',[])+['','## 参照比较',assessment.get('reference_comparison','未形成意见'),'', '## 限制']+assessment.get('limitations',[])
    if run.get('evidence_request'):
        request=run['evidence_request'];lines += ['','## 下一项优先补证',request['view'],request['reason'],
            '要区分的解释：'+request['distinguishes'],'采集方法：'+request['capture_instructions']]
    lines+=['','## 可回查观察']
    for observation in run['observations']:
        lines += ['', '### '+observation['id'], '图片：'+observation['media_id']+'；方向校正原图区域：'+str(observation['region']),
            '现象：'+observation['visible'],'解释：'+(observation['interpretation'] or '未另作解释'),
            '限制：'+(observation['limitation'] or '未另登记')]
    lines += ['', '## 实际引用的资料']
    for reference in run['reference_snapshot']:
        if reference['id'] in assessment.get('reference_ids',[]):
            lines += ['',reference['title']+'；'+reference['locator'],reference['attribution'],
                '归属依据：'+reference['authority'],'来源：'+reference['source_url']]
    lines += ['', '## 文字来源与实际引用段落']
    sources = {d['source']['id']: d for d in bundle.get('knowledge_sources', [])}
    reads = {(c['document_id'], c['chunk_id']): c for c in run.get('read_knowledge', [])}
    for citation in assessment.get('knowledge_citations', []):
        source = sources.get(citation['document_id'], {}).get('source', {})
        read = reads.get((citation['document_id'], citation['chunk_id']), {})
        lines += ['', '### '+source.get('title', citation['document_id']),
                  '资料机构：'+source.get('institution', '未登记')+'；摘要/记录作者：'+source.get('author', '未登记'),
                  '原出处：'+source.get('source_url', ''), '定位：'+citation['locator'],
                  '引用用途：'+citation['use']+'；关联说明：'+citation['relevance'],
                  f'资料第{citation["document_revision"]}版；文档SHA256：{citation["document_sha256"]}',
                  '段落SHA256：'+citation['chunk_sha256'], '本轮实际读到的内容：'+read.get('text', '未保存阅读内容'),
                  '适用范围：'+source.get('scope', ''), '限制：'+'；'.join(source.get('limitations', [])),
                  '资料文字使用依据：'+source.get('rights_note', ''),
                  '该来源记录未由机构或本项目专家认证；检索排序不表示可信度。']
    if not assessment.get('knowledge_citations'):
        lines.append('本轮未登记文字段落引用；不附未阅读的检索内容作为证据。')
    lines+=['','## 修订及文字审查回应',assessment.get('revision_explanation','无已完成修订')]
    for disposition in run.get('critic_dispositions',[]):
        lines += ['疑点 '+str(disposition['issue_index']+1)+'：'+disposition['decision']+'；'+disposition['reason']]
    lines += nvidia_audit_lines(bundle)
    lines+=['','## 人工复核记录（身份未认证）']
    for record in case.get('reviews',[]):lines += [record['reviewer']+'：'+record['note'],'依据：'+record['basis']]
    for record in case.get('corrections',[]):lines += [record['reviewer']+'：'+record['correction'],'依据：'+record['basis']]
    lines+=['','## 附录：运行与预算','完整JSON档案保存观察、文字审查、模型和技能版本、派生图关联及事件。',
        '```json',json.dumps({'run_id':run['id'],'input_hash':run['input_hash'],'versions':run['versions'],
                             'episode':bundle['episode']},ensure_ascii=False,indent=2),'```']
    return '\n'.join(lines)


DOCUMENTARY_STATUS = {'consistent': '已读材料陈述相符', 'conflicting': '已读材料陈述冲突',
                      'missing': '已读材料未覆盖问题', 'needs_review': '需人工回查'}


def documentary_report(bundle):
    case, run = bundle['case'], bundle['run']
    assessment = run.get('assessment') or {}
    lines = ['# 瓷证 · 文字凭据核查 · '+case['title'], '',
             '本报告只核查已读文字材料的陈述关系；不认证历史、文书真实性、器物同一性或真伪，不作年代、窑口、风格归属意见。',
             f'案卷第{run["case_revision"]}版；运行状态：{run["state"]}；专家复核未完成。',
             '', '## 核查问题', run['snapshot']['question'], '', '## 操作人来源声明（未经核验）',
             run['snapshot']['source_declaration'], '', '## 器物登记（未经核验）']
    from .pro_workflow import CATALOGUE_LABELS
    for key, label in CATALOGUE_LABELS.items():
        lines.append(label+'：'+(run['snapshot'].get('catalogue', {}).get(key) or '未登记'))
    lines += ['', '## 已读材料核查摘要', assessment.get('summary', '未形成已完成核查意见。')]
    reads = {read['read_id']: read for read in run.get('read_evidence_documents', []) + run.get('read_knowledge', [])
             if read.get('read_id')}
    sources = {entry['source']['document_id']: entry['source'] for entry in bundle.get('knowledge_sources', [])}
    documents = {document['id']: document for document in run['snapshot'].get('evidence_documents', [])}
    cited = set()
    for finding in assessment.get('documentary_findings', []):
        lines += ['', '### '+finding['question'], '状态：'+DOCUMENTARY_STATUS[finding['status']],
                  finding['finding'], '下一补证：'+finding['next_evidence'], '限制：'+'；'.join(finding['limitations'])]
        for citation in finding['evidence_refs']:
            cited.add(citation['read_id'])
            lines += ['引用：'+citation['document_id']+'；'+citation['locator'],
                      '阅读记录：'+citation['read_id']+'；关联说明：'+citation['relevance'],
                      '固定资料版本：'+str(citation['document_revision']) if citation['kind']=='knowledge' else '本案附件，字节内容固定保存。',
                      '文档SHA256：'+citation['document_sha256'], '段落SHA256：'+citation['chunk_sha256']]
            if citation['kind'] == 'knowledge':
                source = sources.get(citation['document_id'], {})
                lines += ['来源标题：'+source.get('title', citation['document_id']),
                          '来源机构：'+source.get('institution', '')+'；作者：'+source.get('author', ''),
                          '出处URL（不自动访问）：'+source.get('source_url', ''),
                          '适用范围：'+source.get('scope', ''),
                          '来源限制：'+'；'.join(source.get('limitations', [])),
                          '文字使用依据：'+source.get('rights_note', ''),
                          '机构仅是出处记录，不代表认证本案或核查结论。']
            else:
                document = documents.get(citation['document_id'], {})
                lines += ['本案附件：'+document.get('filename', citation['document_id']),
                          '来源声明：'+document.get('source', ''), '本地文字使用依据：'+document.get('rights_note', '')]
    lines += ['', '## 实际引用正文（未经真实性认证）']
    for read_id in sorted(cited):
        read = reads.get(read_id, {})
        lines += ['', '### '+read_id, '定位：'+read.get('locator', ''),
                  '本次返回文字SHA256：'+read.get('read_text_sha256', ''),
                  '本次仅返回'+str(len(read.get('text', '')))+'字符，不据此宣称阅读完整文档。',
                  read.get('text', '未保存阅读正文。')]
    lines += ['', '## 阅读范围与限制',
              '只列实际引用片段，未读取的附件、PDF正文、未选段落和其它资料不构成已读证据；missing不表示外部资料不存在。',
              '档案图片未进入本轮视觉观察；StepFun文字反证审查暂不支持此任务。'] + assessment.get('limitations', [])
    if run.get('evidence_request'):
        request = run['evidence_request']
        lines += ['', '## 下一项优先补证', request['view'], request['reason'], request['capture_instructions']]
    lines += nvidia_audit_lines(bundle)
    lines += ['', '## 人工资料复核与订正（操作人身份未认证）']
    for record in case.get('reviews', []):
        lines += ['资料核对方式：'+record.get('review_method', '未登记')+'；复核人：'+record.get('reviewer', ''),
                  '复核状态：'+record['status']+'；仅适用案卷第'+str(record.get('case_revision', '?'))+'版。',
                  record['note'], '依据：'+record['basis']]
    for record in case.get('corrections', []):
        lines += ['订正方式：'+record.get('review_method', '未登记')+'；登记人：'+record.get('reviewer', ''),
                  record['correction'], '依据：'+record['basis']]
    lines += ['人工记录不自动改写模型核查，不构成机构或真实性认证。']
    lines += ['', '## 修订说明', assessment.get('revision_explanation', '无已完成修订'),
              '', '## 附录：固定输入、工具记录与预算',
              '完整JSON档案保留本轮正文读取回执、段落SHA、版本、工具结果SHA和模型调用事件。',
              '```json', json.dumps({'run_id': run['id'], 'research_task': run.get('research_task'),
                                    'input_hash': run['input_hash'], 'versions': run['versions'],
                                    'episode': bundle['episode']}, ensure_ascii=False, indent=2), '```']
    return '\n'.join(lines)


def html_report(bundle,get_blob):
    escape=lambda value:html.escape(str(value),quote=True)
    run=bundle['run'];body=markdown_report(bundle)
    summary = ''
    indicators = photo_report(run)
    if indicators['status'] != 'not_applicable':
        coverage = indicators['capture_coverage']
        observation = indicators['photo_observation_coverage']
        summary = ('<aside class="report-indicators" aria-label="报告指标">'
                   '<div><small>采集覆盖 · 上传者标记</small><strong>'+str(coverage['value'])+
                   '<span>/100</span></strong><p>'+str(coverage['numerator'])+'/5类通用视角，不表示真伪</p></div>'
                   '<div><small>有区域观察记录</small><strong>'+str(observation['observed_count'])+'<span>/'+
                   str(observation['selected_count'])+'张</span></strong><p>观察内容及定位需逐项复核</p></div>'
                   '<div><small>真品概率</small><strong class="uncalibrated">待校准</strong>'
                   '<p>尚无独立专家真值支持的数值</p></div></aside>')
    # Plain-text paragraphs/headings rendered with escaping, no raw HTML or arbitrary markdown URL execution.
    sections=[];in_code=False;code=[]
    for line in body.splitlines():
        if line.startswith('```'):
            if in_code:sections.append('<details><summary>运行版本与预算</summary><pre>'+escape('\n'.join(code))+'</pre></details>');code=[]
            in_code=not in_code;continue
        if in_code:code.append(line);continue
        if not line:continue
        level=3 if line.startswith('### ') else 2 if line.startswith('## ') else 1 if line.startswith('# ') else 0
        tag='h'+str(level) if level else 'p';text=line[level+1:] if level else line
        sections.append('<'+tag+'>'+escape(text)+'</'+tag+'>')
    media={} if run.get('research_task') == 'documentary_audit' else {m['id']:m for m in run['snapshot']['media']}
    for ref in run['reference_snapshot']:
        if run.get('research_task') != 'documentary_audit' and ref['id'] in (run['assessment'] or {}).get('reference_ids',[]):media[ref['media']['id']]=ref['media']
    images=[] if run.get('research_task') == 'documentary_audit' else ['<h2>原图关联的显示图</h2><p>下列概览校正EXIF方向并缩小显示，原始文件未被改写。区域框对应本轮观察；颜色框不表示专业结论。</p>']
    for identifier,metadata in media.items():
        _,raw=get_blob(identifier);data,derived=derivative(raw,identifier)
        image='data:image/jpeg;base64,'+base64.b64encode(data).decode()
        images+=['<figure><div class="image"><img alt="关联图片" src="'+image+'">']
        for observation in run['observations']:
            if observation['media_id']!=identifier:continue
            x0,y0,x1,y1=observation['region']
            images.append('<div class="box" style="left:%.3f%%;top:%.3f%%;width:%.3f%%;height:%.3f%%"></div>'%(x0*100,y0*100,(x1-x0)*100,(y1-y0)*100))
        images += ['</div><figcaption>'+escape(identifier)+' · 原图SHA256：'+escape(metadata['sha256'])+
                   '<br>显示图SHA256：'+escape(derived['derived_sha256'])+'</figcaption></figure>']
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>瓷证研究档案</title><style>body{margin:auto;max-width:920px;padding:32px;font:16px/1.8 system-ui;background:#faf9f5;color:#203b3e}h1,h2,h3{line-height:1.4}h2{margin-top:2em;border-bottom:1px solid #cdd6ce}p{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.image{position:relative;width:fit-content;max-width:100%}img{max-width:100%;display:block;max-height:650px}.box{position:absolute;border:2px solid #a76c23;box-sizing:border-box}figure{margin:25px 0}figcaption{font-size:12px;overflow-wrap:anywhere}.report-indicators{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;padding:24px;background:#eaf0e9;border:1px solid #cdd6ce;border-radius:8px;margin-bottom:32px}.report-indicators small{font-size:12px}.report-indicators strong{display:block;font:42px/1.8 Georgia,serif}.report-indicators strong span{font:15px system-ui;color:#64776b}.report-indicators p{font-size:12px;margin:0}.report-indicators .uncalibrated{font:26px/2.9 system-ui}@media(max-width:600px){body{padding:18px}.report-indicators{grid-template-columns:1fr;gap:15px}.report-indicators div+div{border-top:1px solid #cdd6ce;padding-top:12px}}@media print{body{background:white;padding:0}.image{break-inside:avoid}.report-indicators{break-inside:avoid}}</style><body>'''+summary+''.join(sections+images)+'</body></html>'
