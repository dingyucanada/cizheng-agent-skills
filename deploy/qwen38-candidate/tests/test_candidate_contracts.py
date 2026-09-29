"""Offline contracts for 27B admission using small synthetic checkpoint files.

The production main() hashes files and checks receipts normally. Only resource,
image and health IO are replaced. No model weights, credentials, network or GPU
are available to these tests; synthetic CPU evidence is explicitly test-bound.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qwen38_preflight", ROOT / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


class Response:
    status = 200

    def __init__(self, endpoint, *, bad_status=False, ready=True):
        self.status = 503 if bad_status else 200
        self.data = json_bytes({"ready": ready} if endpoint.endswith("/v1/health/ready") else {"status": "ok"})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _):
        return self.data


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / "model"; self.model.mkdir()
        self.source = self.root / "source"; self.source.mkdir()
        production_identity = json.loads((ROOT / "expected_identity.json").read_bytes())
        bodies = {entry["name"]: ("synthetic-test:" + entry["name"]).encode()
                  for entry in production_identity["files"]}
        bodies["config.json"] = json_bytes({"architectures": ["Qwen3_5ForConditionalGeneration"],
            "model_type": "qwen3_5", "language_model_only": False,
            "text_config": {"layer_types": ["linear_attention", "linear_attention", "linear_attention", "full_attention"] * 16,
                            "num_key_value_heads": 4, "head_dim": 256}})
        bodies["hf_quant_config.json"] = json_bytes({"quantization": {"quant_algo": "MIXED_PRECISION",
            "kv_cache_quant_algo": None, "quantized_layers": {"synthetic_" + str(i): {} for i in range(401)}}})
        self.identity = {key: production_identity[key] for key in ("model", "revision", "file_count")}
        self.identity["total_file_bytes"] = sum(map(len, bodies.values()))
        self.identity["files"] = []
        receipt_files = []
        for name, raw in bodies.items():
            (self.model / name).write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            entry = {"name": name, "bytes": len(raw)}
            if name.endswith(".safetensors"):
                entry["lfs_sha256"] = digest
            else:
                entry["git_blob_sha1"] = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            self.identity["files"].append(entry)
            receipt_files.append({"name": name, "bytes": len(raw), "sha256": digest})
        self.receipt = {key: self.identity[key] for key in ("model", "revision", "file_count", "total_file_bytes")}
        self.receipt.update(all_files_verified=True, files=receipt_files)
        self.receipt_path = self.root / "download-receipt.json"; self.receipt_path.write_bytes(json_bytes(self.receipt))
        self.identity_raw = json_bytes(self.identity)
        (self.source / "expected_identity.json").write_bytes(self.identity_raw)
        (self.source / "launch_profile.json").write_bytes((ROOT / "launch_profile.json").read_bytes())
        self.cpu = {"cpu_compatibility": "passed", "gpu_requested": False, "model_weights_loaded": False,
                    "model": self.identity["model"], "revision": self.identity["revision"],
                    "mixed_quantization": {"kv_cache_quant_algo": None, "quantized_layers": 401},
                    "processor": {"image_tokens_per_probe": [256, 256]}}
        self.cpu_raw = json_bytes(self.cpu)
        self.cpu_path = self.root / "cpu.json"; self.cpu_path.write_bytes(self.cpu_raw)
        self.cpu_host = {"image": preflight.IMAGE, "image_id": preflight.CONFIG_ID, "architecture": "arm64",
                         "source_sha256": {"cpu_compatibility.py": preflight.CPU_SOURCE_SHA256}}
        self.host_path = self.root / "cpu-host.json"; self.host_path.write_bytes(json_bytes(self.cpu_host))
        self.container = {"Image": preflight.CONFIG_ID,
                          "Config": {"Image": preflight.IMAGE, "Env": ["CUDA_VISIBLE_DEVICES=", "NVIDIA_VISIBLE_DEVICES=void"]},
                          "State": {"ExitCode": 0, "Running": False},
                          "HostConfig": {"NetworkMode": "none", "Memory": 4 * 1024**3, "MemorySwap": 4 * 1024**3,
                                         "Devices": [], "DeviceRequests": None}}
        self.container_path = self.root / "cpu-container.json"; self.container_path.write_bytes(json_bytes([self.container]))
        self.image = {"Id": preflight.CONFIG_ID, "Architecture": "arm64", "Os": "linux",
                      "RepoDigests": [preflight.IMAGE], "Config": {"Entrypoint": ["/opt/nim/start_server.sh"]}}
        self.memory = {"MemAvailable": 49 * 1024**3, "MemTotal": 128 * 1024**3, "SwapTotal": 0, "SwapFree": 0}
        self.bad_endpoint = None; self.ready = True; self.image_calls = []; self.health_calls = []
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(preflight, "ROOT", self.source))
        self.stack.enter_context(mock.patch.object(preflight, "IDENTITY_SHA256", hashlib.sha256(self.identity_raw).hexdigest()))
        self.stack.enter_context(mock.patch.object(preflight, "CPU_COMPATIBILITY_SHA256", hashlib.sha256(self.cpu_raw).hexdigest()))
        self.stack.enter_context(mock.patch.object(preflight, "memory_snapshot", side_effect=lambda: self.memory.copy()))
        self.stack.enter_context(mock.patch.object(preflight.subprocess, "run", side_effect=self.image_inspect))
        self.stack.enter_context(mock.patch.object(preflight.urllib.request, "build_opener", return_value=self))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("real network forbidden")))
        self.stack.enter_context(mock.patch.object(subprocess, "Popen", side_effect=AssertionError("real process forbidden")))
        self.stack.enter_context(mock.patch.object(preflight, "require_free_port", return_value=None))
        self.output_counter = 0

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def image_inspect(self, argv, **_):
        self.assertEqual(argv, ["docker", "image", "inspect", preflight.IMAGE])
        self.image_calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json_bytes([self.image]))

    def open(self, endpoint, **_):
        self.assertIn(endpoint, preflight.BASELINE_ENDPOINTS)
        self.health_calls.append(endpoint)
        return Response(endpoint, bad_status=endpoint == self.bad_endpoint, ready=self.ready)

    def run_main(self, extras=()):
        self.output_counter += 1; output = self.root / f"preflight-{self.output_counter}.json"
        argv = ["preflight", "--model-directory", str(self.model), "--model-receipt", str(self.receipt_path),
                "--cpu-compatibility-report", str(self.cpu_path), "--cpu-host-report", str(self.host_path),
                "--cpu-container-report", str(self.container_path), "--output", str(output), *extras]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            exit_code = preflight.main()
        return exit_code, json.loads(output.read_bytes()), output

    def cpu_profile(self):
        result = {"cpu_preflight": "passed", "gpu_initialized": False, "launch_profile_sha256": preflight.PROFILE_SHA256,
                  "original_nim_entrypoint_sha256": preflight.ENTRYPOINT_SHA256,
                  "original_cpu_compatibility_sha256": preflight.CPU_COMPATIBILITY_SHA256,
                  "requested_context_length": 24576, "requested_max_total_tokens": 24576, "memory_formula_verified": True,
                  "image_tokens_per_probe": [256, 256], "kv_cache_argument": "auto", "kv_cache_expected_dtype": "bfloat16"}
        path = self.root / "cpu-profile.json"; path.write_bytes(json_bytes(result))
        return result, path

    def test_healthy_full_admission_hashes_nineteen_files_and_five_services_twice(self):
        code, result, _ = self.run_main()
        self.assertEqual(code, 0); self.assertTrue(result["model"]["all_files_verified"])
        self.assertEqual(len(result["model"]["files"]), 19)
        self.assertEqual(result["model"]["bf16_full_attention_kv_estimate"]["raw_kv_payload_bytes"], 1610612736)
        self.assertEqual(self.health_calls, list(preflight.BASELINE_ENDPOINTS) * 2)
        self.assertFalse(result["budget"]["estimate_is_measured"])

    def test_current_35_active_low_memory_refuses_before_image_or_hash(self):
        self.memory["MemAvailable"] = 25 * 1024**3
        with mock.patch.object(preflight, "verify_model", side_effect=AssertionError("must not read weights")):
            code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("44 GiB", result["error"]); self.assertEqual(self.image_calls, [])

    def test_original_nim_image_or_entrypoint_mismatch_refuses(self):
        for change in ({"Id": "sha256:wrong"}, {"Config": {"Entrypoint": ["/other"]}}):
            with self.subTest(change=change):
                original = self.image.copy(); self.image.update(change)
                self.assertEqual(self.run_main()[0], 1); self.image = original

    def test_each_old_service_failure_refuses(self):
        for endpoint in preflight.BASELINE_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                self.bad_endpoint = endpoint; self.assertEqual(self.run_main()[0], 1)

    def test_retriever_http_200_ready_false_refuses(self):
        self.ready = False
        self.assertEqual(self.run_main()[0], 1)

    def test_occupied_8009_refuses(self):
        with mock.patch.object(preflight, "require_free_port", side_effect=OSError("8009 occupied")):
            self.assertEqual(self.run_main()[0], 1)

    def test_changed_fixed_profile_refuses(self):
        (self.source / "launch_profile.json").write_bytes(b"{}")
        self.assertEqual(self.run_main()[0], 1)

    def test_changed_original_cpu_receipt_refuses(self):
        self.cpu_path.write_bytes(json_bytes({**self.cpu, "revision": "old"}))
        code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("receipt SHA256", result["error"])

    def test_wrong_cpu_image_or_gpu_metadata_refuses(self):
        for section, key, value in (("Config", "Image", "wrong"), ("HostConfig", "DeviceRequests", [{"Count": -1}]),
                                    ("HostConfig", "NetworkMode", "host"), ("State", "Running", True)):
            with self.subTest(key=key):
                saved = self.container[section][key]; self.container[section][key] = value
                self.container_path.write_bytes(json_bytes([self.container])); self.assertEqual(self.run_main()[0], 1)
                self.container[section][key] = saved

    def test_incomplete_or_other_revision_download_receipt_refuses(self):
        for change in ({"all_files_verified": False}, {"revision": "old"}, {"file_count": 18}):
            with self.subTest(change=change):
                self.receipt_path.write_bytes(json_bytes({**self.receipt, **change})); self.assertEqual(self.run_main()[0], 1)

    def test_same_size_corrupt_weight_refuses(self):
        path = self.model / "model-00001-of-00003.safetensors"
        raw = path.read_bytes(); path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("receipt SHA256 mismatch", result["error"])

    def test_receipt_cannot_bless_new_weight_hash(self):
        name = "model-00001-of-00003.safetensors"; path = self.model / name
        raw = path.read_bytes(); path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        for item in self.receipt["files"]:
            if item["name"] == name:item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.receipt_path.write_bytes(json_bytes(self.receipt))
        code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("official LFS", result["error"])

    def test_old_cpu_profile_or_fp8_choice_refuses(self):
        cpu, path = self.cpu_profile()
        for change in ({"launch_profile_sha256": "35-old-profile"}, {"requested_context_length": 8192},
                       {"kv_cache_argument": "fp8_e4m3"}, {"kv_cache_expected_dtype": "fp8_e4m3"}):
            with self.subTest(change=change):
                path.write_bytes(json_bytes({**cpu, **change}))
                self.assertEqual(self.run_main(["--cpu-profile-report", str(path)])[0], 1)

    def test_immediate_guard_requires_preceding_complete_hash_and_cpu_profile(self):
        code, _, verified = self.run_main(); self.assertEqual(code, 0)
        _, cpu = self.cpu_profile()
        self.assertEqual(self.run_main(["--guard-only"])[0], 1)
        self.assertEqual(self.run_main(["--guard-only", "--verified-report", str(verified), "--cpu-profile-report", str(cpu)])[0], 0)

    def test_file_changed_after_hash_refuses_immediate_guard(self):
        _, _, verified = self.run_main(); _, cpu = self.cpu_profile()
        path = self.model / "vocab.json"; path.write_bytes(path.read_bytes() + b"x")
        self.assertEqual(self.run_main(["--guard-only", "--verified-report", str(verified), "--cpu-profile-report", str(cpu)])[0], 1)

    def test_memory_drop_during_hash_refuses(self):
        with mock.patch.object(preflight, "memory_snapshot", side_effect=[self.memory.copy(), {**self.memory, "MemAvailable": 25 * 1024**3}]):
            self.assertEqual(self.run_main()[0], 1)

    def test_existing_evidence_is_not_overwritten(self):
        output = self.root / "existing.json"; output.write_bytes(b"keep original")
        argv = ["preflight", "--model-directory", str(self.model), "--model-receipt", str(self.receipt_path),
                "--cpu-compatibility-report", str(self.cpu_path), "--cpu-host-report", str(self.host_path),
                "--cpu-container-report", str(self.container_path), "--output", str(output)]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):preflight.main()
        self.assertEqual(output.read_bytes(), b"keep original")


class ProductionPins(unittest.TestCase):
    def test_official_checkpoint_and_bf16_profile_have_expected_identity(self):
        raw = (ROOT / "expected_identity.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), preflight.IDENTITY_SHA256)
        identity = json.loads(raw)
        self.assertEqual(identity["revision"], "482ca0f3832238542f8f5295dde86b5f22711d80")
        self.assertEqual(identity["file_count"], 19); self.assertEqual(identity["total_file_bytes"], 21945291730)
        weights = [item for item in identity["files"] if item["name"].endswith(".safetensors")]
        self.assertEqual(sum(item["bytes"] for item in weights), 21921697280)
        self.assertTrue(all(len(item["lfs_sha256"]) == 64 for item in weights))
        profile = preflight.read_pinned_json(ROOT / "launch_profile.json", preflight.PROFILE_SHA256)
        self.assertEqual(profile["port"], 8009); self.assertEqual(profile["minimum_system_buffer_bytes"], 12 * 1024**3)
        self.assertEqual(profile["arguments"][profile["arguments"].index("--kv-cache-dtype") + 1], "auto")
        self.assertNotIn("--moe-runner-backend", profile["arguments"])

    def test_real_size_budget_rejects_35_active_and_preserves_twelve_gib(self):
        identity = json.loads((ROOT / "expected_identity.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "44 GiB"):
            preflight.budget_summary({"MemAvailable": 25 * 1024**3}, identity)
        result = preflight.budget_summary({"MemAvailable": 44 * 1024**3}, identity)
        self.assertGreaterEqual(result["estimated_remaining_system_bytes"], 12 * 1024**3)
        self.assertEqual(result["runtime_overhead_estimate_bytes"], 5 * 1024**3)
        self.assertFalse(result["estimate_is_measured"])

    def test_actual_launcher_low_memory_cannot_create_cpu_or_gpu_or_stop_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executables = root / "bin"; executables.mkdir()
            model = root / "model"; model.mkdir(); cpu = root / "cpu"; cpu.mkdir()
            log = root / "docker-calls.jsonl"
            docker = executables / "docker"
            docker.write_text(f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nwith Path(os.environ['CONTRACT_DOCKER_LOG']).open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\nraise SystemExit(1 if sys.argv[1:3]==['container','inspect'] else 99)\n")
            docker.chmod(0o700)
            python = executables / "python3"
            python.write_text(f"#!{sys.executable}\n" + '''import importlib.util,os,socket,subprocess,sys
if len(sys.argv)>2 and sys.argv[2].endswith('/qwen38-candidate/preflight.py'):
    spec=importlib.util.spec_from_file_location('real_preflight',sys.argv[2]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.memory_snapshot=lambda:{'MemAvailable':25*1024**3,'MemTotal':128*1024**3,'SwapTotal':0,'SwapFree':0}
    def denied(*args,**kwargs):raise AssertionError('low-memory refusal must precede any external resource call')
    module.subprocess.run=denied;socket.socket=denied
    sys.argv=sys.argv[2:];raise SystemExit(module.main())
os.execv(sys.executable,[sys.executable]+sys.argv[1:])
''')
            python.chmod(0o700)
            env = os.environ.copy(); env.update(PATH=str(executables) + os.pathsep + env["PATH"], CONTRACT_DOCKER_LOG=str(log))
            result = subprocess.run(["bash", str(ROOT / "start_nim_candidate.sh"), str(model), str(root / "receipt.json"),
                                     str(cpu), str(root / "attempt")], env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            evidence = json.loads((root / "attempt/preflight.json").read_bytes())
            self.assertIn("44 GiB", evidence["error"])
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls, [["container", "inspect", name] for name in (
                "cizheng-nim-qwen38-v10-attempt-01", "cizheng-nim-qwen38-v10-attempt-01-templates",
                "cizheng-nim-qwen38-v10-attempt-01-cpu-preflight")])


if __name__ == "__main__":
    unittest.main()
