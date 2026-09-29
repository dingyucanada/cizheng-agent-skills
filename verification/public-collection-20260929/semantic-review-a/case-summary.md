阶段 A 匿名语义核查已逐包保存。包与器物的对应仅由两张照片 SHA 精确匹配得到；先行原图备忘保持不变。本阶段 `catalogue_labels_received=true`、`target_model_outputs_received=true`、`mode_labels_received=false`、`reviewer_role=automated_multimodal_reviewer`、`expert_validation=false`。这是 AI 语义阅评，不是专家验证或专业真值，未读取模式映射或模式评价。

| 器物 | 匿名包 | 原始状态 | 具体核查 |
|---|---|---|---|
| pc01 | packet_3ca212a4f1af4df08593d87ad598944b | failed；assessment=null | 人物、蝴蝶和盖罐观察有支持；“西式盾形纹饰”为风格推断，未说明依据；漏记下腹圆孔。 |
| pc01 | packet_f367a57e17d94fa7b1ae127d30242519 | waiting_evidence | “西式盾形纹饰，非中国风格”的排他结论论据不足；“底部款识是判断窑口与制作时期的直接证据”不宜变成决定身份的保证。 |
| pc02 | packet_5c433bcc9f1a40f6a9b767a6dc2cb1d8 | failed；assessment=null | 黄地、彩绘、双耳和面棱可见；具体粉彩工艺及梅鹊物种未充分核实。“可提供…依据”的补证措辞相对克制。 |
| pc02 | packet_01b02079d45444b0a62dbbadba94921a | waiting_evidence | “方形瓶身绘梅竹双禽”若指鸟数，与view-01至少四个飞鸟形象不符；“无款识”混淆未拍到底与实物没有款；款识区分年代/窑口的作用被说得过强。 |
| pc03 | packet_33ecf5aaf2a6464fb02b48947ab57c60 | failed；assessment=null | 青绿碗、外壁瓣状起伏、黄色修补征象可见；将“金缮”写入可见事实缺工艺证据。官/民窑二分补证目标未获资料支持。 |
| pc03 | packet_6b0e82a1bd1a47ef996804b6b3501e57 | waiting_evidence | “金缮”同样混入可见事实；宋代/龙泉候选保持insufficient，不判错。修复具体年代未知；“款识可明确窑口与时期”及“确保…标记可见”过度承诺。 |

三份馆方参考分别记录：[pc01](https://www.metmuseum.org/art/collection/search/854455) 为中国、清代、约1740、景德镇釉下钴蓝瓷，项目摘要说明荷兰画家Pronk设计背景；[pc02](https://www.metmuseum.org/art/collection/search/42239) 为中国、清代、18世纪晚期至19世纪、景德镇釉上多色彩瓷，并将仿古铜器形作为造型描述；[pc03](https://www.metmuseum.org/art/collection/search/48450) 为南宋、13世纪、龙泉青釉炻器，正式medium记录“gold lacquer repairs”。这些是当前参考标签，不是照片独立鉴定结果。西方设计不自动排除中国制作，金漆修补记录也不独立证明具体金缮工艺或现代修复年代。

六包均未转述这些馆方正式编目值；当前核查收到参考，不能倒推目标模型当时已知，也不因原包缺参照而追溯判错。三份failed与三份waiting_evidence按原状态保留；没有补造成功评估。没有外底图不等于没有底款，不能保证款识存在或独自明确年代窑口。修复年代、物种和未验证备选身份均保持未知；未计算总体准确率或真品概率。每份JSON含原句及对应JSON指针，并已核对摘录一致。

