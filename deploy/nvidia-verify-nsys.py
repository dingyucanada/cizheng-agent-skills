"""Verify existing Nsight output; never starts, signals, or requests a model."""
import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPORTS = ('nvtx_sum', 'cuda_api_sum', 'cuda_gpu_kern_sum')
COUNT_COLUMNS = ('Instances', 'Count', 'Num Ranges', 'Num Calls')


def csv_rows(text, name_column):
    """Skip CLI progress, then accept one CSV table with the required header."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        header = next(csv.reader([line]), [])
        if name_column in header and any(name in header for name in COUNT_COLUMNS):
            reader = csv.DictReader(io.StringIO('\n'.join(lines[index:])))
            rows = []
            for row in reader:
                if not row or all(not str(value or '').strip() for value in row.values()):
                    continue
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Malformed CSV data row')
                rows.append(row)
            return rows
    raise ValueError('Required CSV header is missing: ' + name_column)


def count(row):
    columns = [name for name in COUNT_COLUMNS if name in row]
    if len(columns) != 1 or not re.fullmatch(r'[0-9]+', row[columns[0]].strip()):
        raise ValueError('Ambiguous or non-integer instance count')
    return int(row[columns[0]])


def evaluate(nvtx_text, kernel_text, target='cizheng.model-generate', expected_count=1):
    nvtx = csv_rows(nvtx_text, 'Range')
    kernels = csv_rows(kernel_text, 'Name')
    # Some CLI versions label the unnamed domain using a leading colon.
    matched = [row for row in nvtx if row['Range'] in (target, ':' + target)]
    instances = sum(count(row) for row in matched)
    kernel_instances = sum(count(row) for row in kernels)
    if any(not row['Name'].strip() or count(row) <= 0 for row in kernels):
        raise ValueError('Invalid CUDA kernel row')
    return {
        'passed': instances == expected_count and bool(kernels) and kernel_instances > 0,
        'target_range': target, 'expected_range_count': expected_count,
        'target_range_count': instances, 'target_nvtx_rows': matched,
        'cuda_kernel_rows': len(kernels), 'cuda_kernel_instances': kernel_instances,
        'scope': 'NVTX range count and CUDA kernel presence in this report only',
        'does_not_establish': ['end-to-end speedup', 'GPU utilization', 'ceramic quality',
                               '32B or candidate-container readiness'],
    }


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path, help='New evidence directory; must not exist')
    parser.add_argument('--nsys', default='nsys')
    parser.add_argument('--range', default='cizheng.model-generate', dest='target')
    parser.add_argument('--expected-count', default=1, type=int)
    parser.add_argument('--timeout-seconds', default=60, type=int)
    args = parser.parse_args()
    report = args.report.resolve()
    binary = shutil.which(args.nsys)
    if not binary or not report.is_file() or report.suffix != '.nsys-rep' or report.stat().st_size == 0:
        parser.error('Existing CLI and nonempty .nsys-rep required; readiness is not capture proof')
    if args.expected_count < 1 or not 1 <= args.timeout_seconds <= 300 or not args.target:
        parser.error('Invalid count, timeout or range')
    args.output_dir.mkdir(parents=False, exist_ok=False)
    output = args.output_dir.resolve()
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'passed': False,
               'report': str(report), 'report_bytes': report.stat().st_size,
               'report_sha256': sha256(report), 'commands': [], 'errors': []}
    texts = {}
    commands = [('version', [binary, '--version']),
                ('stats', [binary, 'stats', '--report=' + ','.join(REPORTS), '--format=csv',
                           '--output=' + str(output / 'stats'),
                           '--sqlite=' + str(output / 'report.sqlite'), str(report)])]
    for name, command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=args.timeout_seconds, check=False)
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, returncode = error.stdout or '', error.stderr or '', None
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors='replace')
        (output / (name + '.stdout.txt')).write_text(stdout)
        (output / (name + '.stderr.txt')).write_text(stderr)
        summary['commands'].append({'name': name, 'argv': command, 'returncode': returncode})
        texts[name] = stdout
        if returncode != 0:
            summary['errors'].append(name + ' failed or timed out')
    summary['nsys_version'] = texts['version'].strip()
    if not summary['nsys_version']:
        summary['errors'].append('CLI version is missing')
    for name in REPORTS:
        path = output / ('stats_' + name + '.csv')
        if path.is_file() and path.stat().st_size:
            texts[name] = path.read_text()
        else:
            summary['errors'].append(name + ' CSV is missing or empty')
    if not summary['errors']:
        try:
            summary.update(evaluate(texts['nvtx_sum'], texts['cuda_gpu_kern_sum'],
                                    args.target, args.expected_count))
            if not summary['passed']:
                summary['errors'].append('Expected NVTX count or CUDA kernel evidence is missing')
        except ValueError as error:
            summary['errors'].append(str(error))
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
