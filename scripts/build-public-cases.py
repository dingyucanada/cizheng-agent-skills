#!/usr/bin/env python3
"""Build an offline teaching corpus from project-authored notes and CC0 photos.

No network, model, external webpage copy, fictional sale, or expert signature.
The paired JSON files are generated assets, not model output or benchmark truth.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = 'project_curated_teaching'
NOTICE = '公开馆藏教学导览：已知对象身份，非盲测、非真实委托。研究示例由项目人工编写；本页未调用模型，不是鉴定或专家签署。'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def doc(identifier, title, text, source_url, supplement_id=None):
    result = {'id': identifier, 'title': title, 'filename': identifier + '.txt',
              'kind': 'project_original_note', 'origin': ORIGIN, 'text': text,
              'source_url': source_url, 'sha256': digest(text.encode('utf-8')),
              'rights_note': '瓷证项目原创教学摘记与方法说明；不转载来源网页长文；未由馆方或专家审核。'}
    if supplement_id:
        result['supplement_id'] = supplement_id
    return result


def document_citation(document, needle):
    start = document['text'].index(needle)
    return {'kind': 'document', 'target_id': document['id'],
            'locator': {'start': start, 'end': start + len(needle)}}


def image_citation(identifier, region):
    return {'kind': 'image', 'target_id': identifier, 'region': region}


def finding(identifier, title, text, status, citations, next_evidence):
    return {'id': identifier, 'title': title, 'text': text, 'status': status,
            'citations': citations, 'next_evidence': next_evidence, 'origin': ORIGIN,
            'ai_inference_performed': False}


def observation(identifier, image_id, title, text, region, feature):
    return {'id': identifier, 'image_id': image_id, 'title': title, 'text': text,
            'region': region, 'feature': feature, 'origin': ORIGIN}


def source_cards(item, seeds):
    related = [s for s in seeds if s['source_url'] == item['object_url']]
    related += [s for s in seeds if s['title'] in ('旧修复迹象与观察方法', '来源链中的事件、角色与缺口')]
    return [{'id': item['object_id'] + '-source-' + str(i + 1), 'title': s['title'],
             'url': s['source_url'], 'authority': s['institution'], 'summary': s['text'],
             'locator': s['locator'], 'license': s['rights_note'], 'origin': 'project_original_summary',
             'review_status': 'pending', 'limitations': s['limitations']}
            for i, s in enumerate(related)]


def make_case(item, seeds):
    oid = item['object_id']; role = item['workflow']; supplement = oid + '-supplement'
    first_image = oid + '-image-1'
    catalogue = dict(item['catalogue'])
    if oid == '48607':
        catalogue['dimensions'] = '高48.3厘米、直径23.2厘米；馆方记载，未重新测量'
    base = {
        'id': 'met-' + oid, 'title': catalogue['object_name'], 'role': role,
        'accession_number': item['accession_number'], 'object_url': item['object_url'],
        'scope': '公开教学 · 已知馆藏身份 · 非盲测 · 非真实业务委托',
        'catalogue': catalogue, 'origin': ORIGIN, 'ai_inference_performed': False,
        'expert_reviewed': False, 'sources': source_cards(item, seeds),
        'images': [{'id': oid + '-image-' + str(i + 1), 'file': 'assets/' + image['file'],
                    'view': image['view'], 'sha256': image['sha256'], 'image_url': image['image_url'],
                    'license': item['license'], 'source_url': item['object_url'],
                    'edit_declaration': '馆方公开 JPEG 的原下载字节；未改像素；相机原文件与摄影处理历史未知',
                    **({'supplement_id': supplement} if i else {})}
                   for i, image in enumerate(item['images'])],
        'limits': ['预写研究示例只说明证据组织方法，不能当作实时模型表现或准确率。',
                   '公开 JPEG 不是相机原文件；未检查实物、底足、内部和全部表面。',
                   '馆方归属仅属于该馆藏对象，不能外推给外观相似的待鉴器物。',
                   '照片和网页未证明无修复、交易来源连续性、所有权合法性或真实性。'],
        'workflow_steps': [
            {'id': 'case', 'title': '读取案卷', 'detail': '核对馆藏号、业务问题、资料与照片来源，保留已知身份声明。'},
            {'id': 'observe', 'title': '定位观察', 'detail': '点击区域观察回到原图；观察事实与归属推断分开。'},
            {'id': 'evidence', 'title': '回查证据', 'detail': '查看可定位原创摘记与来源卡，确定哪些问题仍缺资料。'},
            {'id': 'supplement', 'title': '补证与修订', 'detail': '打开预置补充件，对比人工编写 v1 / v2 的陈述变化。'},
            {'id': 'review', 'title': '记录复核', 'detail': '访客填写自己的准备复核意见；没有专家身份认证。'},
            {'id': 'export', 'title': '交接档案', 'detail': '导出包含真实编辑、照片、资料及 SHA256 清单的教学交接包。'}],
        'skills': ['ceramic-route', 'ceramic-research-record',
                   'bluewhite-attribution-test' if oid == '48607' else 'condition-hypothesis-test',
                   'provenance-evidence-audit', 'documentary-evidence-audit', 'evidence-revise'],
    }
    if oid == '48607':
        record = doc(oid + '-catalogue', '馆方记录摘记与使用范围',
            '公开教学对象：The Metropolitan Museum of Art 馆藏18.61.4，山水纹花觚（馆方名称译记）。\n\n'
            '馆方记录：该器列为清代康熙早期景德镇釉下钴蓝瓷，高48.3厘米、直径23.2厘米，购藏记载为Rogers Fund, 1918。这里保存的是本项目原创短摘记，馆方原页面可通过来源链接回查。\n\n'
            '编目边界：年代、产地、材料及尺寸均为该对象的馆方记载；本项目没有重新测量、检查实物或进行独立鉴定。不得将这些标签转给另一件外形相似器物。\n\n'
            '影像来源：本案两幅JPEG来自该馆公开对象图像。原下载字节及SHA256随包保留，图像标为Public Domain / CC0。公共授权不等于原始摄影未经处理；本项目没有相机原文件、拍摄时间或灯光校色记录。\n\n'
            '委托问题（教学）：为博物馆接收资料的准备阶段，记录看得到的器形与装饰、写清哪些部位尚未查看，并提出下一项必要补证。该业务视角不表示本馆实际委托瓷证。', item['object_url'])
        note = doc(oid + '-observation', '首面观察与证据边界',
            '项目人工教学观察，记录对象为公开照片 met-48607.jpg；不是模型输出或文博专家意见。\n\n'
            '整体记录：器口向外扩展，器身较长，中段收窄，下部向外扩展。照片仅展示一个投影视角，不能由像素直接取得真实高度、口径、胎壁厚度或器重。\n\n'
            '装饰记录：正面长条开光内可见树木、山石和层次变化的蓝色景物；上部与下部还有蓝白相间的装饰带。可记录可见布局，不把蓝色色调直接当作钴料成分、窑口或年代证明。\n\n'
            '缺项记录：首面照片没有呈现底足、底款、器内和整圈纹饰。普通正面图也不足以排除胶接、补彩、内壁裂缝或局部修复。\n\n'
            '资料使用方法：CCI关于旧修复的原创摘要提醒，普通照片未显修复不能写成无修复；Getty CDWA来源史方法摘要提示日期、角色和缺口应分开。这里的摘要是方法参考，并非对本件状况和来源真伪的验证。\n\n'
            '阶段产物：可以交接对象信息、图片、定位观察和待补证问题；暂不能形成独立断代、窑口判定、真实性概率或收藏史连续性的结论。', item['object_url'])
        supplement_doc = doc(oid + '-supplement-note', '另一面影像加入后的教学修订',
            '本补证动作只打开包内已下载的另一面公开照片 met-48607-view2.jpg。它不是重新拍照、外部抓取或实时模型推理，新增与修订文字仍为项目人工教学示例。\n\n'
            '新增可见信息：另一面长条开光内显示花篮样纹饰，与首面山水景物不同。因此首面材料只能支持某一面的山水布局，不能把全器纹饰概括为只有山水。\n\n'
            '修订范围：教学v2将纹饰记录改为至少两种可见开光内容，并保留两幅影像的各自定位。第二面增加的是装饰覆盖范围，没有增加底足、底款、内部、实物材质或摄影原始性证据。\n\n'
            '仍需补证：如下一步研究问题涉及制作工艺或状况，应另取底足、器内和口沿近照，并由专业人员按适当方法检查。来源链若要用于交易，还需逐项取得对应的原始记录；1918年购藏摘记不构成完整流转链。\n\n'
            '可复核结果：补证前后陈述的变化可以由访客直接核对两幅图像；本动作不能证明某个年代假设正确，也不是模型性能或鉴定准确率的实测。', item['object_url'], supplement)
        regions = [{'x': .31, 'y': .35, 'width': .34, 'height': .35},
                   {'x': .22, 'y': .17, 'width': .55, 'height': .11},
                   {'x': .28, 'y': .78, 'width': .4, 'height': .075}]
        base['observations'] = [
            observation(oid + '-obs-1', first_image, '山水开光', '这一面开光内可见树木与山石样景物；记录纹饰布局，不作独立年代判断。', regions[0], 'decoration'),
            observation(oid + '-obs-2', first_image, '外扩口沿', '可见口部外扩轮廓；未看到完整内壁与口沿微距，不能排除口部旧修复。', regions[1], 'body'),
            observation(oid + '-obs-3', first_image, '下部装饰带与号记', '下部可见装饰带及较小号记；照片不是底足视角，不转录为底款。', regions[2], 'other')]
        base['findings'] = [
            finding('f1', '馆方归属与本项目观察分开', '可以登记馆方记录为资料标签；尚不能把本案写成瓷证独立断代结果。', 'limited',
                    [document_citation(record, '年代、产地、材料及尺寸均为该对象的馆方记载')], '取得独立检查和具有区分力的比较依据，明确其来源与范围。'),
            finding('f2', '目前只掌握首面纹饰', '首面支持开光内有山水景物；全器纹饰覆盖尚不完整。', 'limited',
                    [image_citation(first_image, regions[0]), document_citation(note, '首面照片没有呈现底足、底款、器内和整圈纹饰')], '打开另一面公开影像，核对两面装饰差异。'),
            finding('f3', '未见异常不能写成无修复', '当前材料没有完整状况检查记录；不输出无冲、无修、全品等肯定措辞。', 'missing',
                    [document_citation(note, '普通正面图也不足以排除胶接、补彩、内壁裂缝或局部修复')], '补充口沿、底足、内壁与局部近照，必要时由保护人员检查。')]
        after = [base['findings'][0],
                 finding('f2', '新增另一面花篮样纹饰', '两幅公开图像支持分别记录山水景物与花篮样纹饰；首面概括应修订为至少两面不同的开光内容。', 'supported',
                         [image_citation(first_image, regions[0]), image_citation(oid + '-image-2', {'x': .35, 'y': .40, 'width': .24, 'height': .32}),
                          document_citation(supplement_doc, '另一面长条开光内显示花篮样纹饰，与首面山水景物不同')], '若需要全器纹饰编目，继续获取未呈现部分并记录方向。'), base['findings'][2]]
        change_note = '加入真实另一面公开JPEG，修订纹饰覆盖范围；年代、来源和状况证据仍未得到独立验证。'
    elif oid == '51185':
        record = doc(oid + '-catalogue', '茶壶馆藏资料摘记',
            '公开教学对象：The Metropolitan Museum of Art 馆藏79.2.1202a, b，青花镂空茶壶（馆方名称译记）。\n\n'
            '馆方资料摘记：页面将对象记为18世纪中国瓷质茶壶，具有透雕和釉下蓝色装饰，高13.3厘米、宽17.8厘米。尺寸与归属来自该对象馆方记录；本项目没有实测、材质检测或独立断代。\n\n'
            '档案匹配：用馆藏号、对象页链接和这幅公开图像共同定位本次教学对象。a, b是原馆藏号的一部分，本项目不据此自行确认每个构件的原配关系。\n\n'
            '影像权利：公开图像为馆方标Public Domain / CC0的对象JPEG。保存原下载字节、SHA256及对象URL，没有相机原文件或拍摄处理记录。\n\n'
            '收藏者视角（教学）：整理接收到的器物资料，区分“馆方记载尺寸”和“本人实测尺寸”，并避免把一幅照片未呈现的部位写成已经检查。该视角不是实际购买、估价或交易委托。', item['object_url'])
        note = doc(oid + '-observation', '茶壶人工观察与状况问题',
            '项目人工教学观察：依据公开照片 met-51185.jpg，只登记能指向具体图像部位的现象；没有调用AI模型，也没有查看实物。\n\n'
            '器形记录：照片中可见盖、流、曲柄和多角形壶身。正面矩形区域呈现成排镂孔，周围有蓝白装饰。图像亮部可能受到灯光反射影响，不能把所有亮色区域解释为补彩或釉质异常。\n\n'
            '资料来源：高13.3厘米、宽17.8厘米来自馆方页面，不能放入“本次实测”栏。照片不含标尺；器物距离、投影与拍摄角度也不受本项目控制。\n\n'
            '状况缺项：未取得盖内、流口内壁、柄与壶身连接处、壶底及镂空层内部的详细影像。不能据正面图确认是否曾断裂、粘接、补配，亦不能写成可安全使用。\n\n'
            '复核方法：CCI原创方法摘要提示旧胶或补色有时需专门观察；一般照片没有呈现相关迹象，仍不能排除修复。本案仅提出检查方向，不提供清洗、拆卸或其他实物处理指令。\n\n'
            '交接原则：登记尺寸资料的出处，标出连接处待检事项，并列明缺少的背面与底部照片。人工意见保留为操作者声明，不作为专家身份确认或价值估计。', item['object_url'])
        supplement_doc = doc(oid + '-supplement-note', '尺寸与缺项清单补充',
            '这是包内预置的项目原创文字补充件，引用同一对象页既有尺寸信息；没有新增照片、实测数据、馆方回复或专家检查。补证后示例为人工编写。\n\n'
            '尺寸字段修订：高13.3厘米、宽17.8厘米应保存为“馆方页面记载，未重新测量”。物理尺寸来自外部记录，而不是照片像素计算。访客若拥有实测记录，可另建真实测量事项，不能直接改写本摘要为已实测。\n\n'
            '构件清单：盖、流、柄及多角形壶身在当前图像中可见；构件存在不等于原配关系成立。接合处和内部情况仍需近照与专业人员检查。\n\n'
            '资料审查问题：本件馆方记录不属于收藏者的交易凭据。页面可以用作教学参照，但不能证明另一件相似茶壶的年代、所有权、成交历史或真伪。\n\n'
            '补充后的结果：可以将编目中的尺寸出处写得完整，减少实测与转记混淆；图像覆盖和状况检查的缺口没有被这份文字材料消除。报告仍应保留待取底部、背面与关键连接处近照的要求。', item['object_url'], supplement)
        regions = [{'x': .38, 'y': .46, 'width': .23, 'height': .36},
                   {'x': .64, 'y': .25, 'width': .21, 'height': .43},
                   {'x': .35, 'y': .09, 'width': .3, 'height': .28}]
        base['observations'] = [
            observation(oid + '-obs-1', first_image, '成排镂孔', '正面矩形区域有成排镂孔；内部层次和制作细节仍须更多视角。', regions[0], 'decoration'),
            observation(oid + '-obs-2', first_image, '曲柄与连接处', '可定位曲柄及与壶身连接的区域；当前图像不足以排除连接处旧修复。', regions[1], 'body'),
            observation(oid + '-obs-3', first_image, '盖与顶部', '可见盖与顶端镂空部分；未取得盖内和口部配合面的近照，原配关系待查。', regions[2], 'body')]
        base['findings'] = [
            finding('f1', '尺寸字段需要来源限定', '可查到馆方尺寸，但本案没有实测记录；应避免混填实测栏。', 'limited',
                    [document_citation(note, '高13.3厘米、宽17.8厘米来自馆方页面，不能放入“本次实测”栏')], '打开预置尺寸与缺项说明，完善编目字段措辞。'),
            finding('f2', '镂空与构件可见，原配未核', '可记录盖、流、柄和镂孔布局；构件的原配关系未被图像证明。', 'limited',
                    [image_citation(first_image, regions[0]), document_citation(record, '本项目不据此自行确认每个构件的原配关系')], '取得构件配合面、内部与连接处近照。'),
            finding('f3', '连接处状况有检查缺口', '当前材料不能支持无修复或可以安全使用的判断。', 'missing',
                    [image_citation(first_image, regions[1]), document_citation(note, '不能据正面图确认是否曾断裂、粘接、补配，亦不能写成可安全使用')], '请专业人员检查盖、柄、流与壶身连接处；不由软件提供实物处理处方。')]
        after = [finding('f1', '尺寸出处已写入编目建议', '补充说明明确尺寸为馆方记载且未重新测量；解决措辞缺项，没有增加真实测量证据。', 'supported',
                         [document_citation(supplement_doc, '高13.3厘米、宽17.8厘米应保存为“馆方页面记载，未重新测量”')], '若业务要求实测，另取有日期、方法与操作者的记录。'), *base['findings'][1:]]
        change_note = '加入同页公开尺寸的原创来源说明，完善编目措辞；没有新增实测、照片或状况判断。'
    else:
        record = doc(oid + '-catalogue', '五彩瓶馆藏资料摘记',
            '公开教学对象：The Metropolitan Museum of Art 馆藏61.200.30，五彩耕织图瓶（馆方名称译记）。\n\n'
            '馆方资料摘记：页面将纹饰联系到耕织图传统，并给出相关题识解释；材料技术记为景德镇瓷、釉上多色彩绘。尺寸高45.7厘米、直径18.1厘米均为馆方記载，未重新测量。这里保存项目原创短摘记，没有复制页面解释长文。\n\n'
            '图像资料：包内只有一幅该对象的公开整体JPEG，保留原下载字节、SHA256和对象页URL；原馆方标记Public Domain / CC0。图像不是本项目现场拍摄，没有题识高清、底部或全部侧面影像。\n\n'
            '拍卖编目视角（教学）：形成可供后续审阅的目录素材与补证清单，区分馆方标题、照片中的可见文字区域和真正完成的转录；这个视角不表示本件正在拍卖或已被拍卖行委托。\n\n'
            '来源限定：公开网页记录只支持该页的馆藏对象描述。本项目没有本次交易、委托人、价款、所有权文件、出口资料、买卖记录或专家签字，不能由软件生成这些内容。', item['object_url'])
        note = doc(oid + '-observation', '人物场景、题识区域与目录措辞',
            '项目人工教学观察：只依据公开照片 met-50839.jpg，不进行AI识别、题识OCR或专家鉴定。\n\n'
            '可见装饰：瓶身正面画面中可见人物、树木、建筑和作业场景，上方左侧有竖行文字区域；颈部和肩部另有装饰带。馆方题名与解释属于资料记载，可见场景属于照片观察，两者的出处应分别保留。\n\n'
            '题识边界：目前没有完成逐字转录；整体图像中的字形大小不足以支持可靠的全部辨读。不能根据馆方标题补造诗文，不能把画面里的字直接写成底款或本朝年款。\n\n'
            '目录建议：写明“馆方记录将纹饰联系到耕织图传统”；如描述照片，可另写“整体图可见人物、建筑与竖行文字区域，未完成全文转录”。避免把资料转记混成独立图像学识别。\n\n'
            '来源链方法：Getty CDWA原创摘要要求已知日期、角色、地点与引用依据分开登记，未知跨度应明确显示。本案只有公开馆藏资料，不含可回查的交易链；不得补写传承有序或所有权已核。\n\n'
            '下一步：需要题识原比例高清、其他侧面与底部影像；若进入真实交易业务，应由相应人员核对原始权属与流转材料，并在档案中说明责任人和核查范围。', item['object_url'])
        supplement_doc = doc(oid + '-supplement-note', '目录措辞审查补充件',
            '本补充件为预置项目原创文字，采用当前已有馆藏页面与图像，不构成新增高清、馆方授权声明、拍卖成交或专家审阅记录。补证前后示例均由项目人工编写。\n\n'
            '可采用的限定措辞：馆方记录将纹饰联系到耕织图传统；本项目公开整体图可见人物、建筑与竖行文字区域，题识尚未完成逐字转录。资料归属、图像观察和未完成事项分开保存。\n\n'
            '暂不能采用的措辞：全文诗题已核、年款已核、所有权已确认、来源传承完整、无修复或真品保证。这些句子要求当前包内未包含的材料或检查，不能通过文字润色自动成立。\n\n'
            '人工复核准备：先核对每句话引用的是对象记录、图像区域还是未完成任务；有引用并不表示引文内容已被证实，更不代表引用资料与另一个未知器物具有同一性。\n\n'
            '修订效果：教学v2可形成更加谨慎的目录描述，并明确题识与来源链的缺口。这个变化属于证据措辞的整理，未增加器物真伪、市场估值、流转真实性或文物合规结论。', item['object_url'], supplement)
        regions = [{'x': .38, 'y': .32, 'width': .28, 'height': .5},
                   {'x': .38, 'y': .32, 'width': .08, 'height': .19},
                   {'x': .42, 'y': .05, 'width': .18, 'height': .23}]
        base['observations'] = [
            observation(oid + '-obs-1', first_image, '人物与建筑场景', '可见人物、树木与建筑场景；具体图像学解释另引馆方资料，不从相似题材推出年代。', regions[0], 'decoration'),
            observation(oid + '-obs-2', first_image, '竖行文字区域', '图像中有竖行文字区域；本项目没有完成全文转录，不补造字句。', regions[1], 'inscription'),
            observation(oid + '-obs-3', first_image, '颈部装饰带', '可见长颈部与装饰带；照片未展示全部侧面、器内或底足。', regions[2], 'body')]
        base['findings'] = [
            finding('f1', '题材解释的来源需要单列', '“耕织图”作为馆方资料记载保留；本项目图像观察另列可見场景，不冒称独立完成图像学识别。', 'limited',
                    [image_citation(first_image, regions[0]), document_citation(record, '页面将纹饰联系到耕织图传统')], '打开目录措辞审查补充件，逐项保留观察与资料的出处。'),
            finding('f2', '题识尚未完成逐字转录', '只能定位竖行文字区域，不生成未读清的诗文或年款。', 'missing',
                    [image_citation(first_image, regions[1]), document_citation(note, '目前没有完成逐字转录')], '补充题识原比例高清与逐字校读记录。'),
            finding('f3', '交易来源链不在教学包内', '已知对象公开记录不构成完整交易或所有权链；不写传承有序。', 'missing',
                    [document_citation(record, '本项目没有本次交易、委托人、价款、所有权文件、出口资料、买卖记录或专家签字')], '真实交易时逐项取得原始权属、流转与核查材料，明确责任人。')]
        after = [finding('f1', '形成有来源限定的目录描述', '目录建议将馆方题材记录与当前图像可见场景分开，并显式保留题识未转录状态。', 'supported',
                         [document_citation(supplement_doc, '资料归属、图像观察和未完成事项分开保存')], '取得题识高清后由具备能力的审阅者校读，记录修改依据。'), *base['findings'][1:]]
        change_note = '补充原创目录措辞审查清单，完善叙述来源；题识高清、流转和真实专家核验仍缺失。'
    base['documents'] = [record, note, supplement_doc]
    base['supplements'] = [{'id': supplement, 'title': '另一面公开影像与修订说明' if oid == '48607' else
                           '尺寸与缺项说明' if oid == '51185' else '目录措辞审查说明',
                           'reason': base['findings'][1 if oid == '48607' else 0]['next_evidence'],
                           'document_ids': [supplement_doc['id']],
                           'image_ids': [oid + '-image-2'] if oid == '48607' else [],
                           'after_findings': after, 'change_note': change_note,
                           'origin': ORIGIN, 'ai_inference_performed': False}]
    base['provenance'] = [
        {'id': oid + '-public-record', 'date_text': '公开页面查阅：' + item['retrieved_on'],
         'event_type': 'publication', 'status': 'documented', 'party': 'The Metropolitan Museum of Art（对象页资料机构）',
         'place': '公开网页', 'description': '本项目保存该馆藏号对应页面的原创资料摘记；查阅日期不是对象取得或交易日期。',
         'object_link_basis': '馆藏号、对象页 URL 与公开照片共同指向此教学对象；未验证另一件器物的同一性。',
         'document_id': record['id'], 'locator': 'TXT全文；馆方资料摘记和来源边界',
         'event_truth_verified': False, 'identity_verified': False},
        {'id': oid + '-gap', 'date_text': '未取得完整流转时段', 'event_type': 'gap', 'status': 'gap',
         'party': '未知', 'place': '未知', 'description': '未取得完整前手、转移与对应原始凭据；不补造连续收藏或交易史。',
         'object_link_basis': '只登记本教学案未包含的资料，不对外部历史作否定或肯定判断。',
         'document_id': note['id'], 'locator': 'TXT全文；缺项与交接范围',
         'event_truth_verified': False, 'identity_verified': False}]
    base['review_prompt'] = '先核对观察定位、资料来源与未完成事项，再记录您自己的准备复核意见。预写示例不是专家意见；访客身份未经认证。'
    return base


def build():
    objects = json.loads((ROOT / 'examples/public-demo/professional-cases.json').read_text())['objects']
    seeds = json.loads((ROOT / 'knowledge/seeds.json').read_text())
    payload = {'schema_version': 1, 'mode': 'guided_teaching', 'ai_inference_performed': False,
               'model_calls': 0, 'notice': NOTICE, 'case_count': len(objects),
               'citation_coordinates': 'Zero-based half-open character ranges; all supplied text is Unicode BMP.',
               'cases': [make_case(item, seeds) for item in objects]}
    validate(payload)
    return (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def validate(payload):
    assert payload['ai_inference_performed'] is False and payload['model_calls'] == 0
    for case in payload['cases']:
        assert case['scope'] and case['expert_reviewed'] is False
        image_ids = {image['id'] for image in case['images']}
        documents = {document['id']: document for document in case['documents']}
        source_ids = {source['id'] for source in case['sources']}
        assert len(image_ids) == len(case['images']) and len(documents) == len(case['documents'])
        for image in case['images']:
            raw = (ROOT / 'site' / image['file']).read_bytes()
            assert digest(raw) == image['sha256'], 'Photo SHA256 does not match source record'
        for document in documents.values():
            assert len(document['text']) > 250
            assert digest(document['text'].encode('utf-8')) == document['sha256']
            assert all(ord(c) <= 0xffff for c in document['text'])
        for entry in [*case['findings'], *(f for s in case['supplements'] for f in s['after_findings'])]:
            assert entry['ai_inference_performed'] is False and entry['origin'] == ORIGIN
            assert entry['citations']
            for citation in entry['citations']:
                target = citation['target_id']
                if citation['kind'] == 'document':
                    text = documents[target]['text']; locator = citation['locator']
                    assert 0 <= locator['start'] < locator['end'] <= len(text)
                elif citation['kind'] == 'image':
                    assert target in image_ids
                elif citation['kind'] == 'source':
                    assert target in source_ids
                else:
                    raise AssertionError('Unknown citation kind')
        for entry in case['observations']:
            assert entry['image_id'] in image_ids
            r = entry['region']
            assert 0 <= r['x'] < r['x'] + r['width'] <= 1
            assert 0 <= r['y'] < r['y'] + r['height'] <= 1
        for supplement in case['supplements']:
            assert set(supplement['document_ids']) <= documents.keys()
            assert set(supplement['image_ids']) <= image_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate exact generated files without writes')
    args = parser.parse_args()
    raw = build()
    paths = [ROOT / 'examples/public-demo/guided-cases.json', ROOT / 'site/data/demo-cases.json']
    if args.check:
        for path in paths:
            if not path.exists() or path.read_bytes() != raw:
                raise SystemExit('Teaching asset is stale; run scripts/build-public-cases.py: ' + str(path.relative_to(ROOT)))
        print('Validated 3 public teaching cases, 4 original JPEGs and 9 project-authored TXT documents; no model call.')
    else:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        print('Built 3 public teaching cases; no network or model call.')


if __name__ == '__main__':
    main()
