"""Offline launcher argument/guard checks; a temporary fake Docker runs no image."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

DEPLOY = Path(__file__).resolve().parent
REPOSITORIES = {
    "nim": ("CIZHENG_NIM_IMAGE", "nvcr.io/nim/nvidia/model-free-nim"),
    "trtllm": ("CIZHENG_TRTLLM_IMAGE", "nvcr.io/nvidia/tensorrt-llm/release"),
    "vllm": ("CIZHENG_VLLM_IMAGE", "vllm/vllm-openai"),
    "sglang": ("CIZHENG_SGLANG_IMAGE", "lmsysorg/sglang"),
    "retriever": ("CIZHENG_RETRIEVER_IMAGE", "nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2"),
}


class LauncherContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nvidia-launcher-contract-")
        self.root = Path(self.temporary.name)
        (self.root / "bin").mkdir()
        for name in ("model", "cache", "weights/embed"):
            (self.root / name).mkdir(parents=True)
        (self.root / "model/config.json").write_text("{}")
        (self.root / "model/_file_manifest.json").write_text("{}")
        docker = self.root / "bin/docker"
        docker.write_text('''#!/bin/sh
if [ "$1" = image ] && [ "$2" = inspect ]; then
  printf '%s\\n' "${CIZHENG_DOCKER_TEST_ARCH:-arm64}"
else
  printf '%s\\n' "$@" > "$CIZHENG_DOCKER_TEST_LOG"
fi
''')
        docker.chmod(0o700)
        self.env = {
            "PATH": str(self.root / "bin") + os.pathsep + os.defpath,
            "CIZHENG_DOCKER_TEST_LOG": str(self.root / "docker-args"),
            "CIZHENG_MODEL_DIR": str(self.root / "model"),
            "CIZHENG_MODEL_NAME": "Qwen/Qwen3-VL-8B-Instruct",
            "CIZHENG_CANDIDATE_CACHE": str(self.root / "cache"),
            "CIZHENG_RETRIEVER_WEIGHTS": str(self.root / "weights"),
            "CIZHENG_RETRIEVER_CACHE": str(self.root / "cache"),
        }
        for variable, repository in REPOSITORIES.values():
            self.env[variable] = repository + "@sha256:" + "a" * 64

    def tearDown(self):
        self.temporary.cleanup()

    def launch(self, name, *args, overrides=None):
        log = self.root / "docker-args"
        log.unlink(missing_ok=True)
        result = subprocess.run(["bash", str(DEPLOY / ("nvidia-serve-" + name + ".sh")), *args],
                                env={**self.env, **(overrides or {})},
                                capture_output=True, text=True, timeout=10)
        return result, log.read_text().splitlines() if log.exists() else []

    def test_all_services_pin_images_and_publish_loopback(self):
        for name in REPOSITORIES:
            with self.subTest(name=name):
                result, args = self.launch(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args[0], "run")
                self.assertEqual(args[args.index("--pull") + 1], "never")
                port = "8003" if name == "retriever" else "8002"
                self.assertIn("127.0.0.1:" + port + ":8000", args)
                self.assertNotIn("--rm", args)
                self.assertTrue(any("readonly" in arg and "target=/" in arg for arg in args))
                self.assertNotIn("HF_TOKEN", args)
                self.assertNotIn("NGC_API_KEY", args)

    def test_floating_wrong_repository_and_x86_refuse_start(self):
        for name, (variable, repository) in REPOSITORIES.items():
            for override in ({variable: repository + ":latest"},
                             {variable: "unverified.example/model@sha256:" + "a" * 64},
                             {"CIZHENG_DOCKER_TEST_ARCH": "amd64"}):
                with self.subTest(name=name, override=override):
                    result, args = self.launch(name, overrides=override)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(args, [])

    def test_trtllm_uses_explicit_serve_and_local_configuration(self):
        result, args = self.launch("trtllm")
        self.assertEqual(result.returncode, 0)
        start = args.index("trtllm-serve")
        self.assertEqual(args[start:start + 3], ["trtllm-serve", "serve", "/mnt/model"])
        self.assertIn("--config", args)
        self.assertIn("pytorch", args)

    def test_nvidia_vllm_preserves_driver_entrypoint(self):
        result, args = self.launch("vllm", overrides={
            "CIZHENG_VLLM_IMAGE": "nvcr.io/nvidia/vllm@sha256:" + "a" * 64})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--entrypoint", args)
        self.assertIn("vllm", args)

    def test_prefetch_is_explicit_no_gpu_and_does_not_print_credential(self):
        result, args = self.launch("retriever", "prefetch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(args, [])
        marker = "synthetic-contract-value"
        result, args = self.launch("retriever", "prefetch", overrides={"HF_TOKEN": marker})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--gpus", args)
        self.assertIn("NIM_ENGINE_MODEL_DOWNLOAD_ONLY=1", args)
        self.assertIn("HF_TOKEN", args)
        self.assertNotIn(marker, result.stdout + result.stderr + repr(args))


if __name__ == "__main__":
    unittest.main()
