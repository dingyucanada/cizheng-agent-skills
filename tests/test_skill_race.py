from cizheng.skill_runtime import SkillRuntime
import pytest


def test_entry_text_and_bundle_are_the_same_version(tmp_path, monkeypatch):
    directory=tmp_path/'one';directory.mkdir()
    entry=directory/'SKILL.md'
    entry.write_text('---\nname: one\ndescription: Original\n---\nOriginal procedure')
    original=type(entry).read_bytes
    reads=0
    def changing_read(path):
        nonlocal reads
        if path==entry:
            reads+=1
            if reads==2:
                entry.write_text('---\nname: one\ndescription: Changed\n---\nChanged procedure')
        return original(path)
    monkeypatch.setattr(type(entry),'read_bytes',changing_read)
    with pytest.raises(ValueError,match='正文读取期间版本变化'):
        SkillRuntime(tmp_path).catalog()
