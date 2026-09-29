"""Fetch one public, fixed checkpoint; verify bytes independently of the CDN.

URL maps may contain temporary public CDN signatures and remain private. No
authentication token is accepted by this tool. Existing verified files resume.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.parse
import urllib.request

CHUNK = 64 * 1024 * 1024
ALLOWED_HOSTS = {'huggingface.co', 'hf-mirror.com', 'us.aws.cdn.hf.co',
                 'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co', 'cas-bridge.xethub.hf.co'}


def verify(path, entry):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != entry['bytes']:
        return None
    sha = hashlib.sha256()
    git = hashlib.sha1(('blob ' + str(entry['bytes']) + '\0').encode())
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            sha.update(block)
            git.update(block)
    if entry.get('lfs_sha256') and sha.hexdigest() != entry['lfs_sha256']:
        return None
    if not entry.get('lfs_sha256') and git.hexdigest() != entry['git_blob_sha1']:
        return None
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--url-map', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    os.umask(0o077)
    manifest = json.loads(Path(args.manifest).read_text())
    urls = json.loads(Path(args.url_map).read_text())
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not 1 <= args.workers <= 12:
        raise ValueError('workers outside bounded range')
    started = time.monotonic()
    lock = threading.Lock()
    totals = {'downloaded_bytes_this_run': 0, 'chunks_completed': 0}
    jobs = []
    completed = {}
    for entry in manifest['files']:
        name = entry['name']
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('nonflat checkpoint path rejected')
        digest = verify(root / name, entry)
        if digest:
            completed[name] = digest
            continue
        if entry['bytes'] < CHUNK:
            raise ValueError('stage and verify small checkpoint files before large transfer')
        url = urls[name]
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
            raise ValueError('unapproved public checkpoint CDN')
        parts = root / '.parts' / name
        parts.mkdir(mode=0o700, parents=True, exist_ok=True)
        for index, begin in enumerate(range(0, entry['bytes'], CHUNK)):
            end = min(begin + CHUNK, entry['bytes']) - 1
            part = parts / f'{index:05d}'
            if part.exists() and not part.is_symlink() and part.stat().st_size == end - begin + 1:
                continue
            jobs.append((entry, url, part, begin, end))

    def fetch(job):
        entry, url, part, begin, end = job
        temporary = part.with_suffix('.partial')
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'Range': f'bytes={begin}-{end}'})
                with urllib.request.urlopen(request, timeout=45) as response:
                    expected = f'bytes {begin}-{end}/{entry["bytes"]}'
                    if response.status != 206 or response.headers.get('Content-Range') != expected:
                        raise ValueError('CDN range mismatch')
                    count = 0
                    with temporary.open('wb') as target:
                        while count <= end - begin:
                            block = response.read(min(1024 * 1024, end - begin + 1 - count))
                            if not block:
                                break
                            target.write(block)
                            count += len(block)
                    if count != end - begin + 1:
                        raise ValueError('incomplete checkpoint range')
                temporary.replace(part)
                with lock:
                    totals['downloaded_bytes_this_run'] += count
                    totals['chunks_completed'] += 1
                return
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError(f'checkpoint_range_failed:{entry["name"]}:{begin}:{type(exc).__name__}:{getattr(exc,"code",None)}') from None
                time.sleep(attempt + 1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {executor.submit(fetch, job) for job in jobs}
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=10,
                return_when=concurrent.futures.FIRST_EXCEPTION)
            for future in done:
                future.result()
            print(json.dumps({'phase': 'download', **totals,
                'pending_chunks': len(pending), 'elapsed_seconds': round(time.monotonic()-started, 1)}), flush=True)
    files = []
    for entry in manifest['files']:
        path = root / entry['name']
        if entry['name'] not in completed:
            temporary = path.with_suffix(path.suffix + '.assembled')
            with temporary.open('wb') as target:
                parts = root / '.parts' / entry['name']
                for index, _ in enumerate(range(0, entry['bytes'], CHUNK)):
                    with (parts / f'{index:05d}').open('rb') as source:
                        for block in iter(lambda: source.read(4*1024*1024), b''):
                            target.write(block)
            digest = verify(temporary, entry)
            if not digest:
                raise ValueError('full checkpoint hash mismatch; partials preserved')
            temporary.replace(path)
            completed[entry['name']] = digest
        files.append({'name':entry['name'], 'bytes':entry['bytes'], 'sha256':completed[entry['name']]})
    receipt = {'model':manifest['model'], 'revision':manifest['revision'],
        'all_files_verified':True, 'file_count':len(files),
        'total_file_bytes':sum(f['bytes'] for f in files), 'files':files,
        'download_seconds':round(time.monotonic()-started, 3), **totals}
    (root / 'download-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in receipt.items() if k!='files'}), flush=True)


if __name__ == '__main__':
    main()
