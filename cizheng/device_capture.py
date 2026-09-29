"""Local bridge capture protocol. No vendor SDK, device attestation or sensor inference."""
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import PurePath
from typing import Literal
from fastapi import APIRouter, Request
from pydantic import Field, model_validator
from .schemas import Revised, Strict
from .store import Problem, uid, decode_image
from .preflight import measure_pixels

IMAGE_LIMIT = 20*1024*1024
NOTICE = '设备或桥接客户端上传的声明记录；厂商、时钟、校准及传感器真实性未认证，不据此判定真伪。'


class Device(Strict):
    kind: Literal['phone', 'glasses_bridge', 'handheld_imager', 'desktop_box', 'web_upload']
    label: str = Field(min_length=1, max_length=200)
    vendor: str = Field(default='', max_length=200)
    model: str = Field(default='', max_length=200)
    transport: Literal['local_bridge_multipart'] = 'local_bridge_multipart'


class SessionIn(Revised):
    device: Device
    max_images: int = Field(default=8, ge=1, le=8)
    max_total_bytes: int = Field(default=40*1024*1024, ge=1, le=80*1024*1024)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class Sensor(Strict):
    name: str = Field(min_length=1, max_length=100)
    value: float = Field(allow_inf_nan=False)
    unit: Literal['mm', 'cm', 'nm', 'lux', 'degC', 's', 'percent', 'instrument_native']
    source: str = Field(min_length=1, max_length=300)
    calibration: Literal['unknown', 'operator_declared', 'documented_not_verified'] = 'unknown'


class CaptureIn(Revised):
    session_id: str = Field(pattern=r'^capture_[a-f0-9]{32}$')
    original_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    captured_at: str = Field(min_length=1, max_length=80)
    operator: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=1000)
    rights_declaration: str = Field(min_length=1, max_length=1000)
    view: str = Field(min_length=1, max_length=100)
    capture_role: Literal['unknown', 'overall', 'base', 'mouth', 'glaze', 'decoration', 'inscription', 'condition'] = 'unknown'
    edit_declaration: str = Field(default='未经确认', max_length=1000)
    sensors: list[Sensor] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def timestamp(self):
        try:
            dt = datetime.fromisoformat(self.captured_at.replace('Z', '+00:00'))
            if dt.tzinfo is None or dt.utcoffset() is None:
                raise ValueError()
            if dt.astimezone(timezone.utc).timestamp() > time.time()+300:
                raise ValueError()
        except (ValueError, OverflowError):
            raise ValueError('采集时间须为带时区ISO8601，不能晚于服务器时间5分钟以上')
        if len({s.name for s in self.sensors}) != len(self.sensors):
            raise ValueError('传感器名称不可重复')
        return self


def parse_multipart(content_type, raw):
    # Bounded MIME parsing removes a new runtime dependency while accepting ordinary FormData.
    if len(raw) > IMAGE_LIMIT + 32*1024:
        raise Problem(413, '采集请求超过单图20MB及元数据限额')
    if '\r' in content_type or '\n' in content_type:
        raise Problem(422, '非法Content-Type')
    if not content_type.isascii():
        raise Problem(422, 'Content-Type须为ASCII')
    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: '+content_type.encode('ascii', errors='strict')+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
    boundary = message.get_boundary()
    if (message.get_content_type() != 'multipart/form-data' or not boundary or
            not re.fullmatch(r'[A-Za-z0-9_\-]{1,80}', boundary) or message.defects or
            not raw.rstrip(b'\r\n').endswith(b'--'+boundary.encode()+b'--')):
        raise Problem(422, '须使用完整的multipart/form-data')
    parts = list(message.iter_parts())
    if len(parts) != 2:
        raise Problem(422, '只接受一个metadata字段和一个file原图')
    fields = {}
    for part in parts:
        name = part.get_param('name', header='content-disposition')
        if (part.get_content_disposition() != 'form-data' or name not in ('metadata', 'file') or
                name in fields or part.is_multipart() or part.defects or
                part.get('Content-Transfer-Encoding')):
            raise Problem(422, '不接受重复、嵌套或编码的multipart字段')
        fields[name] = part
    if set(fields) != {'metadata', 'file'}:
        raise Problem(422, '须包含metadata和file字段')
    meta_bytes = fields['metadata'].get_payload(decode=True)
    if not meta_bytes or len(meta_bytes) > 16*1024:
        raise Problem(413, 'metadata最多16KB且不能为空')
    try:
        def unique(items):
            result = {}
            for k, v in items:
                if k in result:
                    raise ValueError('duplicate JSON keys')
                result[k] = v
            return result
        data = json.loads(meta_bytes.decode('utf-8'), object_pairs_hook=unique)
        body = CaptureIn.model_validate(data)
    except Exception as exc:
        raise Problem(422, 'metadata不符合采集协议：'+type(exc).__name__) from exc
    filename = fields['file'].get_filename()
    if (not filename or len(filename) > 200 or filename in ('.', '..') or
            '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename) or
            PurePath(filename).suffix.casefold() not in ('.jpg', '.jpeg', '.png')):
        raise Problem(422, '原图文件名须为无路径的JPEG/PNG名称')
    image = fields['file'].get_payload(decode=True)
    if not image or len(image) > IMAGE_LIMIT:
        raise Problem(413, '单张原图须非空且最多20MB')
    return body, filename, image


def create_device_router(store):
    router = APIRouter(prefix='/api/cases')

    @router.post('/{identifier}/capture-sessions', status_code=201)
    def session(identifier: str, body: SessionIn):
        data = body.model_dump()
        def create(db):
            case = store.checked_case(db, identifier, body.expected_case_revision)
            active = [json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='capture_session'")]
            if sum(s['case_id'] == identifier and s['expires_at'] > time.time() for s in active) >= 5:
                raise Problem(429, '本案最多5个有效采集会话')
            record = {'id': uid('capture'), 'case_id': identifier, 'opened_revision': case['revision'],
                      'created_at': time.time(), 'expires_at': time.time()+body.ttl_seconds,
                      'device': data['device'], 'max_images': body.max_images,
                      'max_total_bytes': body.max_total_bytes, 'received_images': 0,
                      'received_bytes': 0, 'vendor_authenticated': False, 'notice': NOTICE}
            store.put(db, 'capture_session', record)
            return record
        return store.mutate('capture-session:'+identifier, data, create)

    @router.get('/{identifier}/capture-sessions')
    def sessions(identifier: str):
        store.read('case', identifier)
        return {'sessions': [s for s in store.listing('capture_session') if s['case_id'] == identifier],
                'notice': NOTICE, 'listen_scope': 'loopback_only_bridge_required', 'vendor_sdk_verified': False}

    @router.post('/{identifier}/device-captures', status_code=201)
    async def capture(identifier: str, request: Request):
        body, filename, image = parse_multipart(request.headers.get('content-type', ''), await request.body())
        sha = hashlib.sha256(image).hexdigest()
        if sha != body.original_sha256:
            raise Problem(422, '客户端声明的原图SHA256与实际上传字节不一致')
        raw, meta = decode_image(base64.b64encode(image))
        pixels = measure_pixels(raw)
        data = body.model_dump() | {'filename': filename, 'size': len(raw)}
        def add(db):
            case = store.checked_case(db, identifier, body.expected_case_revision)
            session = store.get(db, 'capture_session', body.session_id)
            if session['case_id'] != identifier:
                raise Problem(422, '采集会话不属于本案')
            if session['expires_at'] <= time.time():
                raise Problem(410, '采集会话已过期，请重新开启')
            if session['received_images'] >= session['max_images'] or session['received_bytes']+len(raw) > session['max_total_bytes']:
                raise Problem(413, '会话采集数量或累计字节预算已用尽')
            duplicate = next((m for m in case['media'] if m['sha256'] == sha), None)
            if not duplicate and len(case['media']) >= 30:
                raise Problem(413, '本案档案照片达到30张上限')
            media = duplicate
            if media:
                old = db.execute('SELECT bytes FROM blobs WHERE id=?', (media['id'],)).fetchone()
                if not old or hashlib.sha256(old[0]).hexdigest() != sha:
                    raise Problem(409, '已保存的同哈希原图校验失败')
            else:
                media = store.save_blob(db, raw, meta)
                media.update(filename=filename, view=body.view, capture_role=body.capture_role,
                             source=body.source, edit_declaration=body.edit_declaration,
                             added_revision=case['revision']+1, view_verified=False, pixel_metrics=pixels)
                case['media'].append(media)
                if not case['analysis_selection_explicit'] and len(case['analysis_media_ids']) < 8:
                    case['analysis_media_ids'].append(media['id'])
            receipt = data | {'id': uid('capture_receipt'), 'case_id': identifier, 'media_id': media['id'],
                              'received_at': time.time(), 'saved_revision': case['revision']+1,
                              'device': session['device'], 'duplicate_original': bool(duplicate),
                              'original_preserved': True, 'clock_verified': False,
                              'vendor_authenticated': False, 'metadata_origin': 'device_client_declaration',
                              'sensor_inference_performed': False, 'notice': NOTICE}
            media.setdefault('captures', []).append(receipt)
            store.put(db, 'capture_receipt', receipt)
            session['received_images'] += 1
            session['received_bytes'] += len(raw)
            store.put(db, 'capture_session', session)
            store.advance(db, case, 'device_capture', {'receipt_id': receipt['id'], 'media_id': media['id'],
                                                     'original_sha256': sha, 'notice': NOTICE})
            return {'case': case, 'media': media, 'receipt': receipt, 'session': session}
        return store.mutate('device-capture:'+identifier, data, add)
    return router
