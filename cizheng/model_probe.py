"""Real endpoint behavior probe using synthetic pixels, never an appraisal benchmark."""
import argparse
import asyncio
import base64
import io
import json
import platform
import time
from pathlib import Path
from PIL import Image
from .agent import LocalModel, parse_json


def color_frame(color):
    image=Image.new('RGB',(128,128),color);stream=io.BytesIO();image.save(stream,format='PNG')
    return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()}}


async def probe(model):
    if not model.configured:
        raise ValueError('本地模型尚未配置；没有执行探针。')
    cases=[('json-action', '只返回JSON {"actions":[{"tool":"read_case","arguments":{}}]}', [],
            lambda v:v=={'actions':[{'tool':'read_case','arguments':{}}]}),
           ('single-image','这张纯色合成图的主色是什么？只返回JSON {"color":"red|green|blue"}。',
            [color_frame('red')],lambda v:v=={'color':'red'}),
           ('two-images','按提供顺序识别两张纯色合成图。只返回JSON {"colors":["red|green|blue","red|green|blue"]}。',
            [color_frame('red'),color_frame('blue')],lambda v:v=={'colors':['red','blue']})]
    result={'scope':'synthetic transport, image-order and JSON behavior only; NOT ceramic accuracy',
            'model':model.identity(),'environment':{'python':platform.python_version(),'platform':platform.platform()},
            'checks':[],'started_at':time.time()}
    for name,question,frames,check in cases:
        start=time.perf_counter();usage={};raw=None
        try:
            raw,usage=await model.complete([{'role':'system','content':'遵循输出格式。无图时不声称看图。'},
                {'role':'user','content':[{'type':'text','text':question}]+frames}],60)
            value=parse_json(raw);passed=check(value);error=None
        except Exception as exc:
            usage=getattr(exc,'usage',usage);value=None;passed=False;error=type(exc).__name__
        result['checks'].append({'name':name,'passed':passed,'response':raw,'parsed':value,'usage':usage,
            'seconds':round(time.perf_counter()-start,4),'image_count':len(frames),'error':error})
    result['passed']=all(c['passed'] for c in result['checks'])
    result['ceramic_accuracy']='not_measured'
    return result


def main():
    parser=argparse.ArgumentParser(description='真实本地模型协议探针；只发送合成颜色图')
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if args.output.exists():parser.exit(2,'请选择新输出文件，以保留旧探针。\n')
    try:
        result=asyncio.run(probe(LocalModel()));args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    except (ValueError,OSError) as exc:parser.exit(2,str(exc)+'\n')
    print('协议探针通过' if result['passed'] else '协议探针存在失败；不要开始专业评测')
    if not result['passed']:parser.exit(1)


if __name__=='__main__':main()
