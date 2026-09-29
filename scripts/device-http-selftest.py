#!/usr/bin/env python3
"""Real loopback HTTP smoke test using an existing public museum image; zero model calls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('capture_client',ROOT/'scripts/device-capture-client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',type=Path,default=ROOT/'examples/public-demo/met-48607.jpg')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('Preserve previous proof; use a new output path')
    raw=args.image.read_bytes()
    with tempfile.TemporaryDirectory(prefix='cizheng-device-http-') as d:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env=os.environ.copy();env['CIZHENG_DATA_DIR']=d;env['CIZHENG_MODEL_URL']=''
        code="from cizheng.api import create_app; import uvicorn; uvicorn.run(create_app(),host='127.0.0.1',port="+str(port)+",log_level='warning')"
        process=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(150):
                try:status=client.call(base,'/api/status');break
                except Exception:
                    if process.poll() is not None:raise RuntimeError('Local test app exited')
                    time.sleep(.1)
            else:raise RuntimeError('Local test app readiness timeout')
            token=status['session_token']
            case=client.call(base,'/api/cases',{'request_id':uuid.uuid4().hex,
                'title':'公开Met照片：设备桥接HTTP协议自测','question':'只核验上传与材料比较，非鉴定'},token)
            receipt_path=Path(d)/'receipt.json'
            command=[sys.executable,str(ROOT/'scripts/device-capture-client.py'),'--base',base,'--case',case['id'],
                '--image',str(args.image),'--kind','web_upload','--device-label','local HTTP bridge exercise, no physical hardware',
                '--operator','software test operator','--captured-at',datetime.now(timezone.utc).isoformat(),
                '--source','Met Open Access public file; timestamp is test declaration, not original camera capture',
                '--rights','Met Open Access / CC0; upload protocol exercise','--role','overall','--receipt',str(receipt_path)]
            completed=subprocess.run(command,capture_output=True,text=True,timeout=45)
            if completed.returncode:raise RuntimeError('Upload client failed: '+completed.stderr[:500])
            receipt=json.loads(receipt_path.read_text())
            from urllib.request import urlopen
            with urlopen(base+'/api/artifacts/'+receipt['media_id'],timeout=10) as response:
                returned=response.read();download_status=response.status
            if returned!=raw:raise RuntimeError('Original bytes drifted after HTTP upload')
            case=client.call(base,'/api/cases/'+case['id'])['case']
            reference={'kind':'media','id':receipt['media_id'],'sha256':receipt['original_sha256'],'locator':'whole public image'}
            for lo in [300,350]:
                result=client.call(base,'/api/cases/'+case['id']+'/risk-facts',{'request_id':uuid.uuid4().hex,
                    'expected_case_revision':case['revision'],'field':'height_mm','value_min':lo,'value_max':lo+1,
                    'statement':'SYNTHETIC contradiction exercise; not the actual museum height',
                    'evidence':[reference]},token)
                case=result['case']
            triage=client.call(base,'/api/cases/'+case['id']+'/risk-triage')
            if triage['indices']['conflict_index']!=15 or triage['indices']['review_priority_index']!=57.5:
                raise RuntimeError('Risk arithmetic mismatch')
            with sqlite3.connect(Path(d)/'cizheng.sqlite3') as db:
                episodes=[json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='episode'")]
                calls=sum(e['model_calls'] for e in episodes)
            if calls!=0:
                raise RuntimeError('Unexpected model budget charged by CPU-only feature')
            proof={'schema_version':1,'executed_at':datetime.now(timezone.utc).isoformat(),
                'transport':'actual_local_loopback_HTTP','image_source':'Met Open Access object 48607, inventory18.61.4',
                'image_sha256':hashlib.sha256(raw).hexdigest(),'image_bytes':len(raw),
                'upload_client_sha256':hashlib.sha256((ROOT/'scripts/device-capture-client.py').read_bytes()).hexdigest(),
                'original_byte_roundtrip_equal':returned==raw,'download_http_status':download_status,
                'receipt_original_sha256':receipt['original_sha256'],'device_metadata_recorded':True,
                'vendor_sdk_or_hardware_verified':False,'captured_at_is_test_declaration':True,
                'synthetic_measurement_exercise':True,'risk_indices':triage['indices'],
                'automatic_rule':triage['automatic_alerts'][0]['rule'],'model_requests':calls,
                'model_call_counter_source':'actual_local_SQLite_episode_records',
                'external_review_requests':0,'professional_quality_tested':False,
                'source_files_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                    for f in [ROOT/'cizheng/risk_triage.py',ROOT/'cizheng/device_capture.py',ROOT/'cizheng/api.py']}}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x') as out:json.dump(proof,out,ensure_ascii=False,indent=2)
            print('Actual local HTTP upload/original SHA/risk arithmetic passed; zero model requests.')
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
