#!/usr/bin/env python3
"""Upload an original photo through the local device bridge; Python stdlib only."""
import argparse
import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def local_base(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or
            parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError('Use a loopback http://127.0.0.1:port URL; remote devices need a local bridge')
    return value.rstrip('/')


def call(base, path, body=None, token=None, content_type='application/json'):
    headers = {'Content-Type':content_type}
    if token:
        headers['X-Cizheng-Token'] = token
    if isinstance(body,dict):
        body = json.dumps(body,ensure_ascii=False).encode()
    try:
        with urlopen(Request(base+path,data=body,headers=headers),timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # Never log a request body or session token.
        raise RuntimeError(f'HTTP {exc.code}: '+str(json.load(exc).get('detail','capture failed'))) from None


def multipart(metadata, filename, raw):
    boundary = 'cizheng_'+uuid.uuid4().hex
    prefix = ('--'+boundary+'\r\nContent-Disposition: form-data; name="metadata"\r\n'
              'Content-Type: application/json\r\n\r\n').encode()
    suffix = ('\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+filename+'"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode()
    return (prefix+json.dumps(metadata,ensure_ascii=False).encode()+suffix+raw+
            ('\r\n--'+boundary+'--\r\n').encode(),'multipart/form-data; boundary='+boundary)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=local_base,default='http://127.0.0.1:8000')
    p.add_argument('--case',required=True)
    p.add_argument('--image',type=Path,required=True)
    p.add_argument('--kind',choices=['phone','glasses_bridge','handheld_imager','desktop_box','web_upload'],default='phone')
    p.add_argument('--device-label',required=True)
    p.add_argument('--operator',required=True)
    p.add_argument('--captured-at',required=True,help='Actual capture/declaration timestamp with timezone; never infer from upload time')
    p.add_argument('--source',required=True)
    p.add_argument('--rights',required=True)
    p.add_argument('--view',default='overall / not verified')
    p.add_argument('--role',choices=['unknown','overall','base','mouth','glaze','decoration','inscription','condition'],default='unknown')
    p.add_argument('--metadata',type=Path,help='Optional JSON containing only sensors and edit_declaration')
    p.add_argument('--receipt',type=Path,required=True,help='New local receipt file; not a public evidence export')
    args=p.parse_args()
    if args.receipt.exists():
        p.error('Receipt already exists; preserve previous receipt')
    if args.image.stat().st_size>20*1024*1024:
        p.error('Image exceeds 20MB')
    raw=args.image.read_bytes();name=args.image.name
    if any(c in name for c in ['"','\r','\n','\\']) or not name.isascii():
        p.error('Client transport requires an ASCII filename without quote/control/path characters')
    extra=json.loads(args.metadata.read_text()) if args.metadata else {}
    if not isinstance(extra,dict) or set(extra)-{'sensors','edit_declaration'}:
        p.error('Optional metadata accepts only sensors/edit_declaration')
    status=call(args.base,'/api/status');token=status['session_token']
    case=call(args.base,'/api/cases/'+args.case)['case']
    session=call(args.base,'/api/cases/'+args.case+'/capture-sessions',
                 {'request_id':uuid.uuid4().hex,'expected_case_revision':case['revision'],
                  'device':{'kind':args.kind,'label':args.device_label}},token)
    metadata={'request_id':uuid.uuid4().hex,'expected_case_revision':case['revision'],
              'session_id':session['id'],'original_sha256':hashlib.sha256(raw).hexdigest(),
              'captured_at':args.captured_at,'operator':args.operator,'source':args.source,
              'rights_declaration':args.rights,'view':args.view,'capture_role':args.role,**extra}
    body,ctype=multipart(metadata,name,raw)
    result=call(args.base,'/api/cases/'+args.case+'/device-captures',body,token,ctype)
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    with args.receipt.open('x',encoding='utf-8') as out:
        json.dump(result['receipt'],out,ensure_ascii=False,indent=2)
    print('Original SHA256 verified; device declaration receipt saved. No model was called.')


if __name__=='__main__':
    main()
