"""Offline Nsight contracts: synthetic CSV and fake CLI; no GPU/model capture."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verify_nsys', DEPLOY / 'nvidia-verify-nsys.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
NVTX = 'Time (%),Total Time (ns),Instances,Style,Range\n100,1000000,1,PushPop,cizheng.model-generate\n'
KERNEL = 'Time (%),Total Time (ns),Instances,Name\n100,500000,2,"void kernel<int, float>()"\n'


class NsysContract(unittest.TestCase):
    def test_registered_target_and_kernel_data_are_both_required(self):
        result = verify.evaluate('Processing report...\n' + NVTX, KERNEL)
        self.assertTrue(result['passed'])
        self.assertEqual(result['target_range_count'], 1)
        self.assertEqual(result['cuda_kernel_rows'], 1)
        self.assertEqual(result['cuda_kernel_instances'], 2)
        self.assertTrue(verify.evaluate(NVTX.replace('Instances', 'Count'), KERNEL)['passed'])
        self.assertTrue(verify.evaluate(NVTX.replace('PushPop,cizheng', 'PushPop,:cizheng'), KERNEL)['passed'])

    def test_empty_wrong_or_multiple_ranges_do_not_pass(self):
        for text in (NVTX.splitlines()[0] + '\n',
                     NVTX.replace('cizheng.model-generate', 'prefix-cizheng.model-generate'),
                     NVTX.replace(',1,PushPop', ',2,PushPop')):
            with self.subTest(text=text):
                self.assertFalse(verify.evaluate(text, KERNEL)['passed'])
        self.assertFalse(verify.evaluate(NVTX, KERNEL.splitlines()[0] + '\n')['passed'])

    def test_invalid_counts_and_incomplete_csv_are_rejected(self):
        for nvtx, kernel in ((NVTX.replace(',1,PushPop', ',NaN,PushPop'), KERNEL),
                             (NVTX, KERNEL.replace(',2,', ',0,')),
                             ('ready; report exists', KERNEL),
                             (NVTX, KERNEL + 'broken,row\n')):
            with self.subTest(nvtx=nvtx, kernel=kernel):
                with self.assertRaises(ValueError):
                    verify.evaluate(nvtx, kernel)

    def test_launch_wrapper_sets_plain_string_capture_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / 'nsys'
            log = root / 'args'
            cli.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_NSYS_LOG"\n')
            cli.chmod(0o700)
            prefix = root / 'first-vision'
            env = {**os.environ, 'CIZHENG_NSYS_BINARY': str(cli),
                   'CIZHENG_NSYS_OUTPUT': str(prefix), 'FAKE_NSYS_LOG': str(log)}
            command = ['bash', str(DEPLOY / 'nvidia-profile-native.sh'), 'python', '-m', 'owned.service']
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = log.read_text().splitlines()
            self.assertIn('--env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0', args)
            self.assertIn('--capture-range-end=stop', args)
            self.assertIn('--kill=none', args)
            self.assertEqual(args[-3:], ['python', '-m', 'owned.service'])
            (root / 'first-vision.nsys-rep').write_text('existing artifact')
            log.unlink()
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(log.exists())

    def test_cli_preserves_raw_stats_and_hashes_without_touching_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / 'first-vision.nsys-rep'
            report.write_bytes(b'OFFLINE SYNTHETIC REPORT PLACEHOLDER')
            cli = root / 'nsys'
            cli.write_text('#!/bin/sh\ncase "$1" in\n--version) printf "Fake Nsight version\\n";;\n'
                'stats) out=${4#--output=}\ncat > "${out}_nvtx_sum.csv" <<\'CSV\'\n' + NVTX + 'CSV\n'
                'cat > "${out}_cuda_gpu_kern_sum.csv" <<\'CSV\'\n' + KERNEL + 'CSV\n'
                'printf "Name,Num Calls\\ncudaLaunchKernel,2\\n" > "${out}_cuda_api_sum.csv"\n;;\nesac\n')
            cli.chmod(0o700)
            output = root / 'evidence'
            result = subprocess.run([sys.executable, str(DEPLOY / 'nvidia-verify-nsys.py'),
                '--report', str(report), '--output-dir', str(output), '--nsys', str(cli)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertTrue(summary['passed'])
            self.assertEqual(summary['report_sha256'], verify.sha256(report))
            self.assertEqual((output / 'stats_nvtx_sum.csv').read_text(), NVTX)
            self.assertEqual(report.read_bytes(), b'OFFLINE SYNTHETIC REPORT PLACEHOLDER')
            self.assertEqual([command['name'] for command in summary['commands']], ['version', 'stats'])
            self.assertEqual(summary['commands'][1]['argv'][2], '--report=' + ','.join(verify.REPORTS))


if __name__ == '__main__':
    unittest.main()
