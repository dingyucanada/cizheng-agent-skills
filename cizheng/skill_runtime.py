"""Three-stage skill disclosure for the Cizheng tool host; no shell executor."""
import hashlib
import json
import re
from pathlib import Path

import yaml


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError('技能 YAML 字段重复或字段名无效')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class SkillRuntime:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def catalog(self):
        result = {}
        for entry in sorted(self.root.glob('*/SKILL.md')):
            if entry.is_symlink() or entry.parent.is_symlink():
                raise ValueError('技能包不接受符号链接')
            raw = entry.read_bytes()
            if len(raw) > 80000:
                raise ValueError('技能正文过大，请拆分参考资源')
            text = raw.decode('utf-8')
            match = re.match(r'\A---\s*\n(.*?)\n---\s*\n', text, re.S)
            if not match:
                raise ValueError('技能缺少 YAML frontmatter')
            meta = yaml.load(match.group(1), Loader=UniqueLoader)
            if not isinstance(meta, dict):
                raise ValueError('技能元数据必须为映射')
            name, description = meta.get('name'), meta.get('description')
            if (not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name)
                    or len(name) > 64 or name != entry.parent.name):
                raise ValueError('技能名称必须与目录一致')
            if not isinstance(description, str) or not 1 <= len(description) <= 1024:
                raise ValueError('技能描述无效')
            compatibility = meta.get('compatibility', '')
            if not isinstance(compatibility, str) or len(compatibility) > 500:
                raise ValueError('技能兼容性声明无效')
            metadata = meta.get('metadata', {})
            if not isinstance(metadata, dict) or any(not isinstance(v, str) for v in metadata.values()):
                raise ValueError('技能 metadata 必须为字符串映射')
            files = {}
            total = 0
            for path in sorted(entry.parent.rglob('*')):
                if path.is_symlink():
                    raise ValueError('技能资源不接受符号链接')
                if not path.is_file():
                    continue
                size = path.stat().st_size
                total += size
                if size > 2_000_000 or total > 4_000_000:
                    raise ValueError('技能资源过大')
                files[path.relative_to(entry.parent).as_posix()] = sha(path.read_bytes())
            if files.get('SKILL.md') != sha(raw):
                raise ValueError('技能正文读取期间版本变化，请重新加载')
            bundle = sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
            result[name] = {'name': name, 'description': description, 'compatibility': compatibility,
                            'metadata': metadata, 'sha256': bundle,
                            'entry_sha256': sha(raw), 'files': files, 'text': text}
        return result

    def read_resource(self, name, relative_path, expected_hash):
        skill = self.catalog().get(name)
        if not skill or skill['sha256'] != expected_hash:
            raise ValueError('技能包版本变化或技能不存在，请建立新运行')
        relative = Path(relative_path)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in relative_path
                or relative.as_posix() not in skill['files']):
            raise ValueError('参考资源必须在当前技能包清单内')
        target = self.root / name / relative
        if not target.resolve().is_relative_to(self.root / name):
            raise ValueError('参考资源越出技能包')
        if target.suffix.lower() not in ('.md', '.txt', '.json', '.yaml', '.yml') or target.stat().st_size > 40000:
            raise ValueError('此工具只读取40KB以内文字参考；图像须使用视觉工具')
        # Hash the exact bytes returned, rather than trusting the earlier directory scan.
        raw = target.read_bytes()
        if sha(raw) != skill['files'][relative.as_posix()] or len(raw) > 40000:
            raise ValueError('参考资源读取期间版本变化，请建立新运行')
        return {'skill': name, 'path': relative.as_posix(), 'sha256': sha(raw),
                'text': raw.decode('utf-8')}
