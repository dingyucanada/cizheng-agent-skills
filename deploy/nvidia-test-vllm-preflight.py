"""Offline fake-Docker checks only; no real container, GPU, or compatibility proof."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IMAGE = 'nvcr.io/nvidia/vllm@sha256:' + 'a' * 64


class PreflightContract(unittest.TestCase):
    def invoke(self, mode='image', image=IMAGE, architecture='arm64'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'docker'
            evidence = root / 'calls.jsonl'
            binary.write_text('''#!/usr/bin/python3 -S
import json, os, sys
with open(os.environ['NVIDIA_TEST_CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['image', 'inspect'] and sys.argv[-1] == '{{.Architecture}}':
    print(os.environ['NVIDIA_TEST_ARCH'])
else:
    print('SYNTHETIC fake docker; no container execution')
''')
            binary.chmod(0o700)
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                               CIZHENG_VLLM_IMAGE=image, NVIDIA_TEST_CALLS=str(evidence),
                               NVIDIA_TEST_ARCH=architecture)
            result = subprocess.run(['bash', str(ROOT / 'nvidia-preflight-vllm.sh'), mode],
                                    capture_output=True, text=True, env=environment, timeout=10)
            calls = [json.loads(line) for line in evidence.read_text().splitlines()] if evidence.exists() else []
            return result, calls

    def test_default_image_check_only_inspects(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[:2] == ['image', 'inspect'] for call in calls))
        self.assertTrue(all(IMAGE in call for call in calls))

    def test_cpu_cli_has_no_network_gpu_port_or_model_mount(self):
        result, calls = self.invoke('cpu-cli')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        launch = calls[1]
        self.assertEqual(launch[0], 'run')
        self.assertEqual(launch[launch.index('--pull') + 1], 'never')
        self.assertEqual(launch[launch.index('--network') + 1], 'none')
        self.assertIn('--rm', launch)
        self.assertIn(IMAGE, launch)
        for forbidden in ('--gpus', '--device', '-p', '--publish', '--mount', '-v', '--volume'):
            self.assertNotIn(forbidden, launch)
        self.assertIn('vllm serve --help', launch[-1])
        self.assertNotIn('torch.cuda.', launch[-1])

    def test_floating_tag_fails_before_docker(self):
        result, calls = self.invoke(image='nvcr.io/nvidia/vllm:25.11-py3')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_non_arm64_image_is_rejected_before_run(self):
        result, calls = self.invoke('cpu-cli', architecture='amd64')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ['image', 'inspect'])

    def test_unknown_mode_never_runs_container(self):
        result, calls = self.invoke('serve')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ['image', 'inspect'])


if __name__ == '__main__':
    unittest.main()
