#!/usr/bin/env python3
"""Build only explicitly public data; never touch a runtime case database or env."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def description(text):
    front = text.split('---', 2)[1]
    match = re.search(r'^description:\s*(.*)$', front, re.M)
    if not match:
        raise ValueError('SKILL.md has no description')
    first = match.group(1)
    if first not in ('>-', '>', '|', '|-'):
        return first.strip('"\'')
    rest = front[match.end():].splitlines()
    lines = []
    for line in rest:
        if not line.strip():
            continue
        if not line[0].isspace():
            break
        lines.append(line.strip())
    return ' '.join(lines)


def build_payloads():
    names = {
        'ceramic-route': '任务与补拍路由', 'ceramic-research-record': '陶瓷编目研究',
        'bluewhite-attribution-test': '青花比较研究', 'condition-hypothesis-test': '状况竞争解释',
        'provenance-evidence-audit': '来源经历核查', 'documentary-evidence-audit': '文字凭据核查',
        'evidence-revise': '补证与版本修订',
    }
    skills = []
    for skill_id, name in names.items():
        folder = ROOT / 'skills' / skill_id
        raw = (folder / 'SKILL.md').read_bytes()
        references = [{'path': str(f.relative_to(folder)), 'content': f.read_text(),
                       'sha256': digest(f.read_bytes())} for f in sorted((folder / 'references').rglob('*')) if f.is_file()]
        files = [{'path': str(f.relative_to(folder)), 'sha256': digest(f.read_bytes())}
                 for f in sorted(folder.rglob('*')) if f.is_file()]
        skills.append({'id': skill_id, 'name': name, 'description': description(raw.decode()),
                       'content': raw.decode(), 'sha256': digest(raw), 'references': references,
                       'package_files': files, 'notice': '项目方法包；未获NVIDIA认证或专家签署'})
    sources = json.loads((ROOT / 'knowledge/seeds.json').read_text())
    for item in sources:
        item['text_sha256'] = digest(item['text'].encode('utf-8'))
    objects = json.loads((ROOT / 'examples/public-demo/professional-cases.json').read_text())
    for obj in objects['objects']:
        for photo in obj['images']:
            for folder in [SITE / 'assets', ROOT / 'examples/public-demo']:
                if digest((folder / photo['file']).read_bytes()) != photo['sha256']:
                    raise ValueError('Public photo bytes do not match source manifest: ' + photo['file'])
    return {
        'skills.json': {'skills': skills},
        'knowledge.json': {'notice': '项目原创来源摘要，待专家审核，不是鉴定真值', 'sources': sources},
        'sources.json': objects,
        'project.json': {'name': '瓷证', 'version': '0.6.0', 'mode': 'public_teaching',
                         'ai_inference_performed': False, 'model_calls': 0,
                         'repository': 'https://github.com/dingyucanada/cizheng-agent-skills',
                         'cases': len(objects['objects']), 'skills': len(skills), 'sources': len(sources)},
    }


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.ids = set(); self.lang = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'html' and attrs.get('lang') == 'zh-CN':
            self.lang = True
        for name in ('href', 'src'):
            if attrs.get(name):
                self.links.append(attrs[name])


def validate_static_site():
    htmls = {f.resolve(): Links() for f in SITE.glob('*.html')}
    for file, parser in htmls.items():
        parser.feed(file.read_text())
        if not parser.lang:
            raise ValueError('Missing language in ' + file.name)
    for file, parser in htmls.items():
        for link in parser.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                if parsed.scheme not in ('https', 'mailto', 'data'):
                    raise ValueError('Unsafe scheme in ' + file.name + ': ' + link)
                continue
            if parsed.path.startswith('/'):
                raise ValueError('Root-absolute URL would fail in project Pages: ' + link)
            target = (file.parent / unquote(parsed.path or file.name)).resolve()
            if target.is_dir():
                target = target / 'index.html'
            if not target.is_relative_to(SITE.resolve()) or not target.is_file():
                raise ValueError('Missing local link in ' + file.name + ': ' + link)
            if parsed.fragment and target in htmls and parsed.fragment not in htmls[target].ids:
                raise ValueError('Missing fragment in ' + file.name + ': ' + link)
    forbidden = [f for f in SITE.rglob('*') if f.is_file() and
                 (f.suffix in ('.env', '.db', '.sqlite', '.pem', '.key') or f.name == '.DS_Store')]
    if forbidden:
        raise ValueError('Forbidden public runtime/private files')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    (SITE / 'data').mkdir(exist_ok=True, parents=True)
    for name, payload in build_payloads().items():
        path = SITE / 'data' / name; expected = json_bytes(payload)
        if args.check:
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError('Generated public data stale: ' + name)
        else:
            path.write_bytes(expected)
    case_builder = ROOT / 'scripts/build-public-cases.py'
    if not case_builder.exists():
        raise ValueError('Missing public case builder')
    subprocess.run([sys.executable, str(case_builder)] + (['--check'] if args.check else []), check=True)
    validate_static_site()
    print(json.dumps({'result': 'pass', 'public_mode': 'teaching', 'private_data_read': False,
                      'skills': 7, 'sources': 25, 'cases': 3, 'check': args.check}, ensure_ascii=False))


if __name__ == '__main__':
    main()
