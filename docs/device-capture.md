# 统一设备采集与本机桥接

已经实现的功能是**统一本机multipart采集协议与归档**：手机文件、智能眼镜导出/桥接文件、专业手持成像文件、未来桌面箱式设备文件可由本机客户端上传；原网页上传继续可用。本轮没有接入这些厂商的SDK、认证设备、直接控制摄像头或建造箱式硬件。设备类别、厂商、型号、操作者、采集时钟和传感器都是声明，不是硬件身份证明。

## 协议与原件

1. `POST /api/cases/{id}/capture-sessions`：当前会话令牌、request_id、expected_case_revision、设备类别及标签。会话最多8张、80MiB、1小时；默认8张/40MiB/15分钟，每案最多5个有效会话。
2. `POST .../device-captures`：multipart正好一个metadata JSON与一个file原图。metadata携带会话ID、当前案件版本、幂等request_id、原始SHA256、带时区采集时间、操作者、来源、本地使用依据、部位/处理声明和可选传感器。
3. 先校验实际字节SHA、非空JPEG/PNG、≤20MiB/40MP、metadata≤16KiB，然后在一个SQLite事务内检查案件/会话归属、版本、有效期、数量/字节预算，保存不可改写的原始blob及采集回执。

同一request_id和完全相同内容重放返回原回执，不增加预算；不同内容重用ID返回409。相同原图不重复存blob，但新的采集声明追加回执且使用一次数量/字节预算。最多30张案卷原图；本轮分析选图仍最多8张。采集会话不会提前占用图像分析额度。模型运行中的案件继承原编辑阻止规则。

每条回执记录original_sha256、media_id、采集声明时间与服务器接收时间、保存资料版本、设备声明、来源与许可依据。`clock_verified=false`、`vendor_authenticated=false`、`sensor_inference_performed=false`。传感器读数需有限数值、明确单位和来源；只做登记，不用于真伪或年代结论。单位有mm/cm/nm/lux/degC/s/percent/instrument_native，校准状态是未知/操作人声明/附文档但未核验。

本地UI「图像研究 → 设备采集入口」可实际完成该协议。它与未来非网页客户端共享相同会话接口，不能把填写设备类别当作实际眼镜或手持设备验收。

## 可运行的独立客户端

Python标准库客户端不依赖浏览器或厂商SDK。已运行一次真实loopback HTTP自测，公开Met照片原字节上传/下载一致。示例：

```sh
python scripts/device-capture-client.py \
  --base http://127.0.0.1:8000 --case CASE_ID \
  --image public-photo.jpg --kind handheld_imager \
  --device-label '手持导出文件（设备身份未认证）' \
  --operator '本地采集操作人' \
  --captured-at '2026-09-29T08:00:00+08:00' \
  --source '本人拍摄，原始导出' --rights '本人本地研究授权' \
  --role base --view '底足' --receipt local-capture-receipt.json
```

时间必须填写实际采集声明，不自动把上传时间当作相机拍摄时间。可选`--metadata`只接受sensors与edit_declaration，不能覆盖案件/会话/原图哈希。回执已存在则拒绝覆盖。客户端只接受loopback HTTP地址，不打印令牌或请求原图。

可复跑真实公开图HTTP检查：`python scripts/device-http-selftest.py --output NEW_PRIVATE_RECEIPT.json`。它启动临时本机服务、运行独立客户端、实际下载原件、验证SHA并执行明确标记的合成数字矛盾练习，随后停止临时服务；不调用模型和外部审查。

## 权限与边界

沿用原工作台单机可信操作者模型：本机会话令牌、TrustedHost、Origin、请求流上限、版本和幂等。并非多租户用户权限或设备配对授权。不要将工作台改为0.0.0.0直接接收眼镜请求；远端设备须先通过已有可信传输导出至本机桥接。设备传输通道、认证、供应商SDK和自动拍摄可以后续独立开发，本轮不声称完成。

原图保留本地，设备/风险接口没有远程模型调用，原StepFun仍只发送人工批准的四类文字。采集回执可能含操作者与设备个人信息，应作为案卷私有材料保存；不能直接当作脱敏公开证据。
