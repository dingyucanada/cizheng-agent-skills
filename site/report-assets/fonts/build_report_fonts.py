#!/usr/bin/env python3
"""Build the renamed report WOFF2 subsets from pinned official Adobe OTFs.

Requires only fonttools and Brotli from requirements.txt. The script only writes
to --output and --upstream-dir; it never edits the report, SVGs, or PDFs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from fontTools import subset
from fontTools.ttLib import TTFont

UPSTREAM = [
    {
        "repository": "adobe-fonts/source-han-serif",
        "commit": "7889f11bf31170b5d092a083b357c8c8130f89e0",
        "upstream_family": "Source Han Serif SC",
        "upstream_style": "Medium",
        "upstream_version": "2.003",
        "filename": "SourceHanSerifSC-Medium.otf",
        "sha256": "1d4dc4b757c07034e2412d6edf48f54f94ec7172d4deb3b90a3e4fc9dcb94f5d",
        "license_filename": "OFL-SourceHanSerif.txt",
        "license_sha256": "9ff5bb567e1b92c801fc1069e5fbf992ff8efccacb9db94e5959a5b3ba9bb903",
        "derived_family": "Cizheng Report Serif",
        "derived_style": "Medium",
        "derived_postscript_name": "CizhengReportSerif-Medium",
        "output": "cizheng-report-serif-medium.woff2",
    },
    {
        "repository": "adobe-fonts/source-han-sans",
        "commit": "a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2",
        "upstream_family": "Source Han Sans SC",
        "upstream_style": "Regular",
        "upstream_version": "2.005",
        "filename": "SourceHanSansSC-Regular.otf",
        "sha256": "f1d8611151880c6c336aabeac4640ef434fa13cbfbf1ffe82d0a71b2a5637256",
        "license_filename": "OFL-SourceHanSans.txt",
        "license_sha256": "fcac737e761ec63dbfbdce11030a1780161920d80315edba9c8beff1c2bac5a2",
        "derived_family": "Cizheng Report Sans",
        "derived_style": "Regular",
        "derived_postscript_name": "CizhengReportSans-Regular",
        "output": "cizheng-report-sans-regular.woff2",
    },
]

# This is a report subset, not a general-purpose Chinese font. Add changed report
# text by rebuilding rather than relying on a fallback for new Chinese words.
COMMON_UI = (
    "首页返回上一页下一页关于帮助设置搜索登录退出注册确认取消保存关闭打开"
    "删除编辑新增添加移除上传下载查看详情展开收起全部选择清空复制导出打印"
    "加载中请稍候成功失败错误提示警告完成重试刷新提交时间日期年月日时分秒"
    "零一二三四五六七八九十百千万编号名称用户记录来源结果文件页总共"
    "状态当前在线离线等待运行已停止已开始连接断开未知语言中文英文"
    "→←↗↓↑·—–“”‘’（）【】《》，。；：？！、"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if not self.hidden_depth:
            self.fragments.extend(value for key, value in attrs if key in {"alt", "aria-label", "title"} and value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.fragments.append(data)


def json_text(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for v in value.values() for text in json_text(v)]
    if isinstance(value, list):
        return [text for v in value for text in json_text(v)]
    return []


def collect(site: Path) -> tuple[set[int], list[dict[str, object]]]:
    parser = VisibleText()
    html_path = site / "report.html"
    parser.feed(html_path.read_text(encoding="utf-8"))
    fragments = parser.fragments + [COMMON_UI]
    inputs = [html_path]
    for path in sorted((site / "report-assets").glob("*.svg")):
        document = ET.parse(path)
        for element in document.iter():
            if element.tag.rsplit("}", 1)[-1] in {"text", "title", "desc"}:
                fragments.append("".join(element.itertext()))
        inputs.append(path)
    deployment = site / "report-assets" / "deployment-status.json"
    if deployment.exists():
        fragments.extend(json_text(json.loads(deployment.read_text(encoding="utf-8"))))
        inputs.append(deployment)
    # Whitespace control characters are layout instructions, not font glyphs.
    codepoints = {ord(c) for c in "".join(fragments) if unicodedata.category(c) not in {"Cc", "Cf"}}
    codepoints.update(range(0x20, 0x7F))
    # Preserve literal Unicode; do not normalize text or replace wrong mappings.
    records = [{"path": str(p.relative_to(site)), "sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in inputs]
    return codepoints, records


def fetch_checked(url: str, target: Path, expected: str, allow_download: bool) -> bytes:
    if not target.exists():
        if not allow_download:
            raise FileNotFoundError(f"{target}; use --download to fetch the pinned official upstream")
        with urlopen(Request(url, headers={"User-Agent": "Cizheng-report-fonts"}), timeout=180) as stream:
            data = stream.read()
        if sha(data) != expected:
            raise ValueError(f"SHA-256 mismatch from {url}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    data = target.read_bytes()
    if sha(data) != expected:
        raise ValueError(f"SHA-256 mismatch for {target}")
    return data


def rename(font: TTFont, identity: dict[str, str]) -> None:
    names = font["name"]
    family = identity["derived_family"]
    style = identity["derived_style"]
    full = f"{family} {style}" if style != "Regular" else family
    # Replace every localized identity record. Copyright, designer and OFL
    # records are retained verbatim. The reserved name remains in attribution
    # only and is not used as any derived font family or PostScript name.
    replacements = {
        1: full if style != "Regular" else family,
        2: "Regular",
        3: f"Cizheng report subset 1.0; {identity['derived_postscript_name']}",
        4: full,
        5: f"Version {identity['upstream_version']}; Cizheng report subset 1.0",
        6: identity["derived_postscript_name"],
        16: family,
        17: style,
        18: full,
        21: family,
        22: style,
        25: identity["derived_postscript_name"],
    }
    for record in list(names.names):
        if record.nameID in replacements:
            names.setName(replacements[record.nameID], record.nameID, record.platformID, record.platEncID, record.langID)
    for name_id in [1, 2, 3, 4, 5, 6, 16, 17]:
        names.setName(replacements[name_id], name_id, 3, 1, 0x409)
    if "CFF " in font:
        cff = font["CFF "].cff
        cff.fontNames = [identity["derived_postscript_name"]]
        top = cff.topDictIndex[0]
        top.FullName = full
        top.FamilyName = family
        top.Weight = style
    if "DSIG" in font:
        del font["DSIG"]


def main() -> None:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--site", type=Path, required=True)
    arguments.add_argument("--upstream-dir", type=Path, required=True)
    arguments.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    arguments.add_argument("--download", action="store_true")
    args = arguments.parse_args()
    site = args.site.resolve()
    output = args.output.resolve()
    codepoints, inputs = collect(site)
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "format": "cizheng-report-font-subset-v1",
        "license": "SIL Open Font License 1.1",
        "modifications": ["report/UI Unicode subset", "WOFF2 compression", "renamed families and PostScript identities"],
        "original_outlines_and_metrics_preserved": True,
        "text_normalization_or_replacement": False,
        "generator": {"python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "fonttools": importlib.metadata.version("fonttools"), "Brotli": importlib.metadata.version("Brotli")},
        "input_sources": inputs,
        "common_ui": COMMON_UI,
        "unicode_count": len(codepoints),
        "fonts": [],
    }
    for identity in UPSTREAM:
        base = f"https://raw.githubusercontent.com/{identity['repository']}/{identity['commit']}"
        font_url = f"{base}/OTF/SimplifiedChinese/{identity['filename']}"
        upstream_path = args.upstream_dir / identity["filename"]
        font_bytes = fetch_checked(font_url, upstream_path, identity["sha256"], args.download)
        if not font_bytes.startswith(b"OTTO"):
            raise ValueError("Pinned source is not an OpenType CFF font")
        license_url = f"{base}/LICENSE.txt"
        license_bytes = fetch_checked(license_url, args.upstream_dir / identity["license_filename"], identity["license_sha256"], args.download)
        (output / identity["license_filename"]).write_bytes(license_bytes)
        font = TTFont(upstream_path, recalcTimestamp=False)
        cmap = font.getBestCmap()
        missing = sorted(codepoints - cmap.keys())
        if missing:
            raise ValueError(f"{identity['filename']} missing report codepoints: " + ", ".join(f"U+{cp:04X} {chr(cp)}" for cp in missing))
        copyright_notices = sorted({n.toUnicode() for n in font["name"].names if n.nameID == 0})
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.name_legacy = True
        options.notdef_glyph = True
        options.notdef_outline = True
        options.recalc_timestamp = False
        worker = subset.Subsetter(options=options)
        worker.populate(unicodes=sorted(codepoints))
        worker.subset(font)
        rename(font, identity)
        font.flavor = "woff2"
        target = output / identity["output"]
        font.save(target, reorderTables=True)
        built = TTFont(target)
        if codepoints - built.getBestCmap().keys():
            raise ValueError("Derived font lost required Unicode mappings")
        built_notices = sorted({n.toUnicode() for n in built["name"].names if n.nameID == 0})
        if built_notices != copyright_notices:
            raise ValueError("Derived font did not preserve copyright notices")
        record = dict(identity)
        record.update({"download_url": font_url, "license_url": license_url, "embedded_original_copyright": copyright_notices, "bytes": target.stat().st_size, "output_sha256": sha(target.read_bytes()), "unicode_count": len(built.getBestCmap()), "glyph_count": len(built.getGlyphOrder())})
        manifest["fonts"].append(record)
        print(target.name, target.stat().st_size, record["output_sha256"])
    (output / "subset-codepoints.txt").write_text("\n".join(f"U+{cp:04X}" for cp in sorted(codepoints)) + "\n", encoding="utf-8")
    (output / "FONT-SOURCES.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
