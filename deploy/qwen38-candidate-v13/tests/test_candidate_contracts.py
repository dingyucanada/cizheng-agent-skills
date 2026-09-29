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
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("qwen38_preflight", ROOT / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
sys.modules["preflight"] = preflight
guard_spec = importlib.util.spec_from_file_location("qwen38_memory_guard", ROOT / "memory_guard.py")
memory_guard = importlib.util.module_from_spec(guard_spec)
guard_spec.loader.exec_module(memory_guard)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


class Response:
    status = 200

    def __init__(self, endpoint, *, bad_status=False, ready=True, guard_kib=33554432, watchdog_seconds=2):
        self.status = 503 if bad_status else 200
        self.data = json_bytes({"ready": ready, "minimum_remaining_memory_kib": guard_kib, "remaining_memory_watchdog_seconds": watchdog_seconds} if endpoint.endswith("/v1/health/ready") else {"status": "ok"})

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
        self.cpu_dir = self.root / "original-cpu"; self.cpu_dir.mkdir()
        self.output_dir = self.root / "evidence"; self.output_dir.mkdir()
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
        (self.source / "resource_policy.json").write_bytes((ROOT / "resource_policy.json").read_bytes())
        self.cpu = {"cpu_compatibility": "passed", "gpu_requested": False, "model_weights_loaded": False,
                    "model": self.identity["model"], "revision": self.identity["revision"],
                    "mixed_quantization": {"kv_cache_quant_algo": None, "quantized_layers": 401},
                    "processor": {"image_tokens_per_probe": [256, 256]}}
        self.cpu_raw = json_bytes(self.cpu)
        self.cpu_path = self.cpu_dir / "cpu.json"; self.cpu_path.write_bytes(self.cpu_raw)
        self.cpu_host = {"image": preflight.IMAGE, "image_id": preflight.CONFIG_ID, "architecture": "arm64",
                         "source_sha256": {"cpu_compatibility.py": preflight.CPU_SOURCE_SHA256}}
        self.host_path = self.cpu_dir / "cpu-host.json"; self.host_path.write_bytes(json_bytes(self.cpu_host))
        self.container = {"Image": preflight.CONFIG_ID,
                          "Config": {"Image": preflight.IMAGE, "Env": ["CUDA_VISIBLE_DEVICES=", "NVIDIA_VISIBLE_DEVICES=void"]},
                          "State": {"ExitCode": 0, "Running": False},
                          "HostConfig": {"NetworkMode": "none", "Memory": 4 * 1024**3, "MemorySwap": 4 * 1024**3,
                                         "Devices": [], "DeviceRequests": None}}
        self.container_path = self.cpu_dir / "cpu-container.json"; self.container_path.write_bytes(json_bytes([self.container]))
        self.image = {"Id": preflight.CONFIG_ID, "Architecture": "arm64", "Os": "linux",
                      "RepoDigests": [preflight.IMAGE], "Config": {"Entrypoint": ["/opt/nim/start_server.sh"]}}
        self.memory = {"MemAvailable": 64 * 1024**3, "MemTotal": 128 * 1024**3, "SwapTotal": 0, "SwapFree": 0}
        self.retired = {"Id": preflight.RETIRED_NIM_ID, "Name": "/" + preflight.RETIRED_NIM_NAME,
                        "Image": preflight.CONFIG_ID, "Config": {"Image": preflight.IMAGE,
                          "Entrypoint": ["/opt/nim/start_server.sh"],
                          "Env": ["NIM_MODEL_PATH=/models/qwen3-4b", "NIM_SERVED_MODEL_NAME=Qwen3-4B-Instruct-2507"]},
                        "State": {"Running": False, "Status": "exited", "Paused": False,
                                  "Restarting": False, "Dead": False, "Pid": 0, "ExitCode": 0},
                        "HostConfig": {"PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8007"}]}}}
        self.bad_endpoint = None; self.ready = True; self.image_calls = []; self.health_calls = []
        self.retriever_guard_kib = 33554432; self.watchdog_seconds = 2
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(preflight, "ROOT", self.source))
        self.stack.enter_context(mock.patch.object(preflight, "IDENTITY_SHA256", hashlib.sha256(self.identity_raw).hexdigest()))
        self.stack.enter_context(mock.patch.object(preflight, "CPU_COMPATIBILITY_SHA256", hashlib.sha256(self.cpu_raw).hexdigest()))
        self.stack.enter_context(mock.patch.object(preflight, "memory_snapshot", side_effect=lambda: self.memory.copy()))
        self.stack.enter_context(mock.patch.object(preflight.subprocess, "run", side_effect=self.image_inspect))
        self.stack.enter_context(mock.patch.object(preflight.urllib.request, "build_opener", return_value=self))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("real network forbidden")))
        self.stack.enter_context(mock.patch.object(socket.socket, "bind", return_value=None))
        self.stack.enter_context(mock.patch.object(subprocess, "Popen", side_effect=AssertionError("real process forbidden")))
        self.stack.enter_context(mock.patch.object(preflight, "require_free_port", return_value=None))
        self.output_counter = 0

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def image_inspect(self, argv, **_):
        self.image_calls.append(argv)
        if argv == ["docker", "image", "inspect", preflight.IMAGE]:
            return subprocess.CompletedProcess(argv, 0, stdout=json_bytes([self.image]))
        self.assertEqual(argv, ["docker", "container", "inspect", preflight.RETIRED_NIM_ID])
        return subprocess.CompletedProcess(argv, 0, stdout=json_bytes([self.retired]))

    def open(self, endpoint, **_):
        self.assertIn(endpoint, preflight.BASELINE_ENDPOINTS)
        self.health_calls.append(endpoint)
        return Response(endpoint, bad_status=endpoint == self.bad_endpoint, ready=self.ready, guard_kib=self.retriever_guard_kib, watchdog_seconds=self.watchdog_seconds)

    def run_main(self, extras=()):
        self.output_counter += 1; output = self.output_dir / f"preflight-{self.output_counter}.json"
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
                  "image_tokens_per_probe": [256, 256], "kv_cache_argument": "auto", "kv_cache_expected_dtype": "bfloat16",
                  "loader_extra_config": {"enable_multithread_load": False},
                  "loader_contract_script_sha256": preflight.LOADER_CONTRACT_SHA256,
                  "loader_selection_verified": True, "serial_loader_lazy_reads_verified": True}
        path = self.output_dir / "cpu-profile.json"; path.write_bytes(json_bytes(result))
        return result, path

    def test_healthy_full_admission_hashes_nineteen_files_and_four_services_twice(self):
        code, result, _ = self.run_main()
        self.assertEqual(code, 0); self.assertTrue(result["model"]["all_files_verified"])
        self.assertEqual(len(result["model"]["files"]), 19)
        self.assertEqual(result["model"]["bf16_full_attention_kv_estimate"]["raw_kv_payload_bytes"], 1610612736)
        self.assertEqual(self.health_calls, list(preflight.BASELINE_ENDPOINTS) * 2)
        self.assertFalse(result["budget"]["estimate_is_measured"])

    def test_extra_cache_directory_and_json_file_refuse_before_external_or_weight_io(self):
        for name, directory in (("cache", True), ("nested-evidence.json", False)):
            with self.subTest(name=name):
                extra = self.model / name
                extra.mkdir() if directory else extra.write_bytes(b"{}")
                with mock.patch.object(preflight, "verify_model", side_effect=AssertionError("no weight IO")):
                    code, result, _ = self.run_main()
                self.assertEqual(code, 1); self.assertIn("only the 19", result["error"])
                self.assertEqual(self.image_calls, []); self.assertEqual(self.health_calls, [])
                extra.rmdir() if directory else extra.unlink()

    def test_symlink_replacing_an_official_file_refuses_before_external_io(self):
        file = self.model / "vocab.json"; original = file.read_bytes()
        target = self.root / "outside-vocab"; target.write_bytes(original)
        file.unlink(); file.symlink_to(target)
        code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("never symlinks", result["error"])
        self.assertEqual(self.image_calls, [])

    def test_exact_regular_hardlink_view_is_allowed_without_changing_original_modes(self):
        view = self.root / "checkpoint-view"; view.mkdir()
        before = {entry.name: entry.stat().st_mode for entry in self.model.iterdir()}
        for entry in self.model.iterdir():os.link(entry, view / entry.name)
        old_model = self.model; self.model = view
        code, result, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue(result["model_view_layout"]["hardlinks_allowed"])
        self.assertTrue(all(item["st_nlink"] == 2 for item in result["model_view_layout"]["files"]))
        self.assertEqual(before, {entry.name: entry.stat().st_mode for entry in old_model.iterdir()})
        for entry in old_model.iterdir():
            self.assertEqual(entry.stat().st_ino, (view / entry.name).stat().st_ino)

    def test_new_view_does_not_rewrite_old_cpu_mount_provenance(self):
        original_source = "/home/synthetic-fixture-user/cizheng-next-model27-20260929"
        self.container["Mounts"] = [{"Source": original_source, "Destination": "/models/qwen38", "RW": False}]
        original_raw = json_bytes([self.container]); self.container_path.write_bytes(original_raw)
        original_cpu = self.cpu_path.read_bytes()
        code, result, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(result["cpu_compatibility"]["historical_model_mounts"],
                         [{"source": original_source, "destination": "/models/qwen38", "read_only": True}])
        self.assertFalse(result["cpu_compatibility"]["rewritten_for_new_host_model_path"])
        self.assertNotEqual(str(self.model), original_source)
        self.assertEqual(self.container_path.read_bytes(), original_raw)
        self.assertEqual(self.cpu_path.read_bytes(), original_cpu)

    def test_model_isolation_rejects_both_nesting_directions_but_allows_evidence_cache(self):
        for label in ("source directory", "original CPU directory", "evidence directory", "cache directory", "download receipt"):
            for path in (self.model, self.model / "nested", self.model.parent):
                with self.subTest(label=label, path=path), self.assertRaisesRegex(ValueError, "must not contain or be inside"):
                    preflight.require_model_path_isolation(self.model, {label: path})
        result = preflight.require_model_path_isolation(self.model, {
            "evidence directory": self.output_dir, "cache directory": self.output_dir / "cache",
            "source directory": self.source, "original CPU directory": self.cpu_dir,
            "download receipt": self.receipt_path})
        self.assertTrue(result["model_disjoint_from_every_protected_path"])
        self.assertTrue(result["protected_paths_may_nest_with_each_other"])

    def test_nested_cpu_or_receipt_input_refuses_without_mutating_model_view(self):
        names = {entry.name for entry in self.model.iterdir()}
        for flag in ("--cpu-compatibility-report", "--model-receipt"):
            with self.subTest(flag=flag):
                code, result, _ = self.run_main([flag, str(self.model / "config.json")])
                self.assertEqual(code, 1); self.assertIn("model directory must not", result["error"])
                self.assertEqual(names, {entry.name for entry in self.model.iterdir()})
                self.assertEqual(self.image_calls, [])

    def test_new_cache_after_full_hash_refuses_immediate_guard(self):
        _, _, verified = self.run_main(); _, cpu = self.cpu_profile()
        (self.model / "new-cache").mkdir()
        code, result, _ = self.run_main(["--guard-only", "--verified-report", str(verified), "--cpu-profile-report", str(cpu)])
        self.assertEqual(code, 1); self.assertIn("only the 19", result["error"])

    def test_current_35_active_low_memory_refuses_before_image_or_hash(self):
        self.memory["MemAvailable"] = 25 * 1024**3
        with mock.patch.object(preflight, "verify_model", side_effect=AssertionError("must not read weights")):
            code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("60 GiB", result["error"]); self.assertEqual(self.image_calls, [])

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

    def test_current_five_service_memory_and_below_sixty_refuse_before_weight_or_docker_io(self):
        for available in (53035340 * 1024, 60 * 1024**3 - 1):
            with self.subTest(available=available):
                self.memory["MemAvailable"] = available
                with mock.patch.object(preflight, "verify_model", side_effect=AssertionError("no weight IO")):
                    code, result, _ = self.run_main()
                self.assertEqual(code, 1); self.assertIn("60 GiB", result["error"])
                self.assertEqual(self.image_calls, [])

    def test_retired_four_b_running_or_wrong_fixed_identity_refuses(self):
        for section, key, value in (("State", "Running", True), ("State", "Status", "running"),
                                    ("Config", "Image", "other"), ("Config", "Env", [])):
            with self.subTest(key=key):
                original = self.retired[section][key]; self.retired[section][key] = value
                code, result, _ = self.run_main(); self.assertEqual(code, 1)
                self.assertIn("must already be stopped", result["error"])
                self.retired[section][key] = original
        for key, value in (("Id", "0" * 64), ("Name", "/different"), ("Image", "wrong")):
            with self.subTest(key=key):
                original = self.retired[key]; self.retired[key] = value
                self.assertEqual(self.run_main()[0], 1); self.retired[key] = original

    def test_replacement_process_on_eight_zero_zero_seven_refuses(self):
        with mock.patch.object(socket.socket, "bind", side_effect=OSError("8007 occupied")):
            code, result, _ = self.run_main()
        self.assertEqual(code, 1); self.assertIn("8007 occupied", result["error"])

    def test_missing_or_relaxed_retriever_guard_or_changed_watchdog_refuses(self):
        for guard, interval in ((None, 2), (16 * 1024**2, 2), (33554432, 5)):
            with self.subTest(guard=guard, interval=interval):
                self.retriever_guard_kib = guard; self.watchdog_seconds = interval
                code, result, _ = self.run_main(); self.assertEqual(code, 1)
                self.assertIn("unchanged 32 GiB", result["error"])

    def test_changed_resource_policy_refuses_even_unchanged_cli_profile(self):
        raw = (self.source / "launch_profile.json").read_bytes()
        (self.source / "resource_policy.json").write_bytes(b'{"minimum_available_bytes": 1}')
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), preflight.PROFILE_SHA256)

    def test_preceding_legacy_resource_receipt_cannot_pass_new_immediate_guard(self):
        _, _, verified = self.run_main(); _, cpu = self.cpu_profile()
        old = json.loads(verified.read_bytes()); old.pop("resource_policy_sha256")
        verified.write_bytes(json_bytes(old))
        code, result, _ = self.run_main(["--guard-only", "--verified-report", str(verified), "--cpu-profile-report", str(cpu)])
        self.assertEqual(code, 1); self.assertIn("preceding complete", result["error"])
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

    def test_old_threaded_profile_or_fake_serial_bool_refuses(self):
        cpu, path = self.cpu_profile()
        for change in ({"loader_extra_config": {}}, {"loader_extra_config": {"enable_multithread_load": "false"}},
                       {"loader_extra_config": {"enable_multithread_load": True}},
                       {"loader_extra_config": {"enable_multithread_load": 0}},
                       {"loader_selection_verified": False}, {"serial_loader_lazy_reads_verified": False},
                       {"loader_contract_script_sha256": "old-helper"},
                       {"launch_profile_sha256": "1c8ea9059772c186e081f141501c191e6f40a0b0b54113bd50b445c6bd68c9df"}):
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


class MemoryGuardContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.container_id = "a" * 64; self.calls = []; self.now = 0.0
        self.item = {"Id": self.container_id, "Name": "/cizheng-nim-qwen38-v13-attempt-03",
                     "Image": preflight.CONFIG_ID, "Config": {"Image": preflight.IMAGE,
                       "Entrypoint": ["/opt/nim/start_server.sh"],
                       "Env": ["NIM_MODEL_PATH=/models/qwen38", "NIM_SERVED_MODEL_NAME=Qwen3.8-27B-NVFP4"]},
                     "State": {"Running": True, "Status": "running"},
                     "HostConfig": {"Memory": 40 * 1024**3, "MemorySwap": 40 * 1024**3,
                       "PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8009"}]}}}
        self.stop_returncode = 0
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(preflight.subprocess, "run", side_effect=self.external))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("no real network")))
        self.stack.enter_context(mock.patch.object(subprocess, "Popen", side_effect=AssertionError("no real process")))

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def external(self, argv, **_):
        self.calls.append(argv)
        if argv == ["docker", "container", "inspect", self.container_id]:
            return subprocess.CompletedProcess(argv, 0, stdout=json_bytes([self.item]))
        self.assertEqual(argv, ["docker", "stop", "--time", "0", self.container_id])
        return subprocess.CompletedProcess(argv, self.stop_returncode, stdout=b"candidate-only\n", stderr=b"")

    def pause(self, seconds):
        self.assertGreaterEqual(seconds, 0); self.assertLessEqual(seconds, 0.5)
        self.now += seconds

    def run_guard(self, available):
        values = [{"MemAvailable": item} for item in available]
        with mock.patch.object(preflight, "memory_snapshot", side_effect=values):
            return memory_guard.monitor(self.container_id, self.root / "guard", clock=lambda: self.now, pause=self.pause)

    def test_crossing_34_stops_only_bound_candidate_with_original_receipt(self):
        self.assertEqual(self.run_guard([64 * 1024**3, 36 * 1024**3, 33 * 1024**3]), 1)
        stops = [call for call in self.calls if call[1] == "stop"]
        self.assertEqual(stops, [["docker", "stop", "--time", "0", self.container_id]])
        evidence = json.loads((self.root / "guard/stop-receipt.json").read_bytes())
        self.assertTrue(evidence["stopped_only_exact_candidate"])
        self.assertTrue(evidence["restore_old_4b_required_by_coordinator"])
        self.assertFalse(evidence["hard_reservation"])
        self.assertEqual(evidence["interval_seconds"], 0.5)
        self.assertEqual(evidence["sample_count"], 2)
        self.assertTrue((self.root / "guard/before-stop-container-inspect.json").is_file())

    def test_exact_boundary_is_kept_until_a_lower_sample(self):
        self.run_guard([64 * 1024**3, 34 * 1024**3, 34 * 1024**3 - 1])
        rows = [json.loads(row) for row in (self.root / "guard/memory-samples.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]["mem_available_bytes"], 34 * 1024**3)
        self.assertEqual(rows[1]["elapsed_seconds"], 0.5)

    def test_wrong_ownership_cannot_stop_any_container(self):
        for key, value in (("Name", "/cizheng-nim-qwen4b-v09"), ("Id", preflight.RETIRED_NIM_ID), ("Image", "wrong")):
            with self.subTest(key=key):
                saved = self.item[key]; self.item[key] = value
                with self.assertRaisesRegex(ValueError, "exact fixed v11"):
                    memory_guard.inspect_candidate(self.container_id)
                self.item[key] = saved
        self.assertFalse(any(call[1] == "stop" for call in self.calls))

    def test_docker_stop_failure_is_recorded_without_claiming_stop(self):
        self.stop_returncode = 1
        self.assertEqual(self.run_guard([64 * 1024**3, 33 * 1024**3]), 1)
        evidence = json.loads((self.root / "guard/stop-receipt.json").read_bytes())
        self.assertFalse(evidence["stopped_only_exact_candidate"])
        self.assertEqual(evidence["stop_exit_code"], 1)

    def test_already_ended_candidate_finishes_without_stop(self):
        self.item["State"] = {"Running": False, "Status": "exited"}
        self.assertEqual(self.run_guard([64 * 1024**3] * 11), 1)
        self.assertFalse(any(call[1] == "stop" for call in self.calls))
        self.assertTrue((self.root / "guard/completion.json").is_file())


class ProductionPins(unittest.TestCase):
    def test_actual_remote_stopped_four_b_metadata_satisfies_exact_name_id_contract(self):
        raw = (ROOT / "tests/fixtures/retired-nim-actual-20260929.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "382f0687de404259ca0a8ca895e501da1fe012f4e16fb4f7455061e656ce66c9")
        fixture = json.loads(raw)
        self.assertEqual(fixture["raw_docker_inspect_sha256"], "2ea2756d1cabcdbc6b2e66587ad3ff1e0aa86395149eeb8b53d89f23b1acb0ad")
        self.assertEqual(fixture["original_rotation_receipt_sha256"], "5264e942fa77f5e4e09b84d2490baa704aae406c0d7b344ea1cb79bcfe2ed38e")
        self.assertEqual(fixture["containers"][0]["Name"], "/cizheng-nim-qwen4b-v09-attempt-04")
        def inspect(argv, **_):
            self.assertEqual(argv, ["docker", "container", "inspect", preflight.RETIRED_NIM_ID])
            return subprocess.CompletedProcess(argv, 0, stdout=json_bytes(fixture["containers"]))
        with mock.patch.object(preflight.subprocess, "run", side_effect=inspect), mock.patch.object(socket.socket, "bind"):
            result = preflight.require_retired_nim()
            self.assertFalse(result["running"])
            self.assertTrue(result["port_8007_free"])
            fixture["containers"][0]["Name"] = "/cizheng-nim-qwen4b-v09"
            with self.assertRaisesRegex(ValueError, "must already be stopped"):
                preflight.require_retired_nim()

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
        self.assertEqual(profile["port"], 8009)
        # Preserve the tested CLI bytes and original CPU binding. Resource
        # metadata is explicitly superseded by the separately hashed v11 policy.
        policy = preflight.require_resource_policy()
        self.assertFalse(policy["legacy_profile_resource_metadata_is_superseded"])
        self.assertEqual(policy["minimum_system_buffer_bytes"], 34 * 1024**3)
        self.assertEqual(policy["minimum_available_bytes"], 60 * 1024**3)
        self.assertEqual(len(policy["baseline_endpoints"]), 4)
        self.assertEqual(profile["arguments"][profile["arguments"].index("--kv-cache-dtype") + 1], "auto")
        self.assertNotIn("--moe-runner-backend", profile["arguments"])

    def test_only_serial_loader_cli_pair_is_added_and_old_profile_is_preserved(self):
        legacy_raw = (ROOT.parent / "qwen38-candidate-v11/launch_profile.json").read_bytes()
        self.assertEqual(hashlib.sha256(legacy_raw).hexdigest(), "1c8ea9059772c186e081f141501c191e6f40a0b0b54113bd50b445c6bd68c9df")
        legacy_args = json.loads(legacy_raw)["arguments"]
        profile = preflight.read_pinned_json(ROOT / "launch_profile.json", preflight.PROFILE_SHA256)
        self.assertEqual(len(legacy_args), 41); self.assertEqual(len(profile["arguments"]), 43)
        self.assertEqual(profile["arguments"][:41], legacy_args)
        self.assertEqual(profile["arguments"][41:], ["--model-loader-extra-config", '{"enable_multithread_load":false}'])
        self.assertEqual(profile["minimum_available_bytes"], 60 * 1024**3)
        self.assertEqual(profile["minimum_system_buffer_bytes"], 34 * 1024**3)
        policy = preflight.require_resource_policy()
        self.assertEqual(policy["model_loader_extra_config"], {"enable_multithread_load": False})
        self.assertFalse(policy["weight_loader_disable_mmap"])
        self.assertFalse(policy["weight_loader_prefetch_checkpoints"])

    def test_serial_extra_config_requires_json_boolean_false(self):
        spec = importlib.util.spec_from_file_location("loader_contract", ROOT / "loader_contract.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.require_serial_options('{"enable_multithread_load":false}'), {"enable_multithread_load": False})
        for invalid in ('{"enable_multithread_load":"false"}', '{"enable_multithread_load":true}', '{}',
                        '{"enable_multithread_load":0}',
                        '{"num_threads":1}', '{"enable_multithread_load":false,"num_threads":1}', 'null'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.require_serial_options(invalid)

    def test_real_size_budget_rejects_35_active_and_preserves_thirty_four_gib(self):
        identity = json.loads((ROOT / "expected_identity.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "60 GiB"):
            preflight.budget_summary({"MemAvailable": 25 * 1024**3}, identity)
        result = preflight.budget_summary({"MemAvailable": 60 * 1024**3}, identity)
        self.assertGreaterEqual(result["estimated_remaining_system_bytes"], 34 * 1024**3)
        self.assertEqual(result["runtime_overhead_estimate_bytes"], 5 * 1024**3)
        self.assertTrue(result["runtime_overhead_includes_bf16_kv"])
        self.assertEqual(result["peak_estimate_bytes"], 21921697280 + 5 * 1024**3)
        self.assertFalse(result["estimate_is_measured"])

    def launcher_refusal(self, mutate, expected_error, *, path_guard=False):
        """Run the real shell and preflight, denying every mutable external call."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executables = root / "bin"; executables.mkdir()
            model = root / "model"; model.mkdir(); cpu = root / "cpu"; cpu.mkdir()
            for item in json.loads((ROOT / "expected_identity.json").read_bytes())["files"]:
                (model / item["name"]).write_bytes(b"")
            paths = {"model": model, "cpu": cpu, "receipt": root / "receipt.json", "evidence": root / "attempt"}
            mutate(root, paths)
            before = {entry.name: (entry.lstat().st_mode, entry.lstat().st_ino) for entry in model.iterdir()}
            log = root / "docker-calls.jsonl"
            docker = executables / "docker"
            docker.write_text(f"#!{sys.executable}\n" + '''import json,os,sys
from pathlib import Path
with Path(os.environ['CONTRACT_DOCKER_LOG']).open('a') as stream:stream.write(json.dumps(sys.argv[1:])+'\\n')
raise SystemExit(1 if sys.argv[1:3]==['container','inspect'] else 99)
''')
            docker.chmod(0o700)
            python = executables / "python3"
            python.write_text(f"#!{sys.executable}\n" + '''import importlib.util,os,socket,sys
if len(sys.argv)>2 and sys.argv[2].endswith('/qwen38-candidate-v13/preflight.py'):
    sys.path.insert(0,os.path.dirname(sys.argv[2]))
    spec=importlib.util.spec_from_file_location('real_preflight',sys.argv[2]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def denied(*args,**kwargs):raise AssertionError('layout refusal must precede weight, memory and external IO')
    module.memory_snapshot=denied;module.verify_model=denied;module.subprocess.run=denied;socket.socket=denied
    sys.argv=sys.argv[2:];raise SystemExit(module.main())
os.execv(sys.executable,[sys.executable]+sys.argv[1:])
''')
            python.chmod(0o700)
            env = os.environ.copy(); env.update(PATH=str(executables) + os.pathsep + env["PATH"],
                                               CONTRACT_DOCKER_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(["bash", str(ROOT / "start_nim_candidate.sh"),
                                     *(str(paths[key]) for key in ("model", "receipt", "cpu", "evidence"))],
                                    env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            if path_guard:
                self.assertIn(expected_error, result.stderr.decode())
                self.assertFalse(paths["evidence"].exists())
            else:
                receipt = json.loads((paths["evidence"] / "preflight.json").read_bytes())
                self.assertIn(expected_error, receipt["error"])
                self.assertFalse(receipt["gpu_model_requested"])
            self.assertEqual(before, {entry.name: (entry.lstat().st_mode, entry.lstat().st_ino) for entry in model.iterdir()})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls, [["container", "inspect", name] for name in (
                "cizheng-nim-qwen38-v13-attempt-03", "cizheng-nim-qwen38-v13-attempt-03-templates",
                "cizheng-nim-qwen38-v13-attempt-03-cpu-preflight")])

    def test_actual_launcher_cache_json_and_symlink_refuse_before_cpu_or_gpu(self):
        def directory(root, paths):(paths["model"] / "cache").mkdir()
        def extra_json(root, paths):(paths["model"] / "evidence.json").write_bytes(b"{}")
        def symlink(root, paths):
            target = root / "vocab-original"; target.write_bytes(b"")
            file = paths["model"] / "vocab.json"; file.unlink(); file.symlink_to(target)
        for mutate, error in ((directory, "only the 19"), (extra_json, "only the 19"),
                              (symlink, "never symlinks")):
            with self.subTest(mutate=mutate.__name__):self.launcher_refusal(mutate, error)

    def test_actual_launcher_nested_evidence_cpu_and_receipt_refuse_without_creating_evidence(self):
        def evidence(root, paths):paths["evidence"] = paths["model"] / "new-evidence"
        def cpu(root, paths):paths["cpu"] = paths["model"]
        def receipt(root, paths):paths["receipt"] = paths["model"] / "config.json"
        for mutate in (evidence, cpu, receipt):
            with self.subTest(mutate=mutate.__name__):
                self.launcher_refusal(mutate, "model directory must not contain or be inside", path_guard=True)

    def test_actual_launcher_low_memory_cannot_create_cpu_or_gpu_or_stop_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executables = root / "bin"; executables.mkdir()
            model = root / "model"; model.mkdir(); cpu = root / "cpu"; cpu.mkdir()
            for item in json.loads((ROOT / "expected_identity.json").read_bytes())["files"]:(model / item["name"]).write_bytes(b"")
            log = root / "docker-calls.jsonl"
            docker = executables / "docker"
            docker.write_text(f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nwith Path(os.environ['CONTRACT_DOCKER_LOG']).open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\nraise SystemExit(1 if sys.argv[1:3]==['container','inspect'] else 99)\n")
            docker.chmod(0o700)
            python = executables / "python3"
            python.write_text(f"#!{sys.executable}\n" + '''import importlib.util,os,socket,subprocess,sys
if len(sys.argv)>2 and sys.argv[2].endswith('/qwen38-candidate-v13/preflight.py'):
    sys.path.insert(0,os.path.dirname(sys.argv[2]))
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
            self.assertIn("60 GiB", evidence["error"])
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls, [["container", "inspect", name] for name in (
                "cizheng-nim-qwen38-v13-attempt-03", "cizheng-nim-qwen38-v13-attempt-03-templates",
                "cizheng-nim-qwen38-v13-attempt-03-cpu-preflight")])


if __name__ == "__main__":
    unittest.main()
