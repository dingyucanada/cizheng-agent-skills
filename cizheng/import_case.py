"""Explicit local import; no model call, no network, no alteration of originals."""
import argparse
import base64
import hashlib
from pathlib import Path
from .agent import ROOT
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--title', required=True)
    parser.add_argument('--limit', type=int, default=4)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    if not 1 <= args.limit <= 12:
        parser.error('limit must be 1..12')
    files = sorted(p for p in args.directory.iterdir() if p.suffix.lower() in ('.png', '.jpg', '.jpeg'))
    if not files:
        parser.error('No supported photos')
    store = Store(args.data_dir)
    batch = hashlib.sha256(str(args.directory.resolve()).encode()).hexdigest()
    case = store.create_case({'request_id': 'local-import-' + batch, 'title': args.title,
        'question': '研究器类、制作时期与窑口候选；检验支持和冲突证据，提出最有用的下一项补证。',
        'target_attribution': '实际制作时期未知；风格相似不视为制作年代证明',
        'source_declaration': '用户提供的开发案例；尺寸、购藏来源及实际制作时期未知。图像处理情况待核实。非盲测样本。'})
    # Refresh existing revision: repeating an import does not replace case state.
    case = store.read('case', case['id'])
    for path in files[:args.limit]:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if any(m['sha256'] == sha for m in case['media']):
            continue
        result = store.add_evidence(case['id'], {'request_id': 'import-' + batch[:20] + '-' + sha,
            'expected_case_revision': case['revision'], 'filename': path.name,
            'image_base64': base64.b64encode(raw).decode(), 'view': '视角待核实：' + path.stem,
            'edit_declaration': '未取得原始拍摄文件；处理情况未知，不据文件名判断真实性',
            'source': '用户提供的本地图片；归属未认证'})
        case = result['case']
    print(f"案件 {case['id']} / 版本 {case['revision']} / 已存 {len(case['media'])} 张原图")
    print(f"本次目录其余 {max(0,len(files)-args.limit)} 张未导入，可供开发补证流程；不属于独立测试数据。")
    print('未调用模型，未形成真假或年代判断。')


if __name__ == '__main__':
    main()
