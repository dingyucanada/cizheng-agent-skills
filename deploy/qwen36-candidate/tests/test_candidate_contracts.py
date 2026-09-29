"""Offline deployment contracts, never model/GPU or ceramic-quality evidence.

Exercise the real download and preflight entry points. Only HTTPS responses,
Docker inspection, health endpoints and host resources are substituted. Small
synthetic bytes and a smaller transfer chunk exercise restart behavior without
downloading weights. Any accidental network connection or process is forbidden.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location("qwen36_contract_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


download = load_module("download_fixed")
preflight = load_module("preflight")


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qwen36-offline-contract-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        old_umask = os.umask(0o077)
        self.addCleanup(os.umask, old_umask)
        for target in ("socket.socket.connect", "socket.create_connection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("real network/process forbidden in offline contracts"))
            guard.start()
            self.addCleanup(guard.stop)


class Response:
    def __init__(self, body, status=200, headers=None, fail_after=None):
        self.status = status
        self.headers = headers or {}
        self.stream = io.BytesIO(body)
        self.fail_after = fail_after

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount=-1):
        if self.fail_after is not None:
            if self.stream.tell() >= self.fail_after:
                raise OSError("synthetic connection interrupted during body")
            amount = min(amount, self.fail_after - self.stream.tell())
        return self.stream.read(amount)


class RangeServer:
    """Substitute RFC byte-range responses, not the downloader's control flow."""
    def __init__(self, payload, interrupt_from=None, wrong_range=False):
        self.payload = payload
        self.interrupt_from = interrupt_from
        self.wrong_range = wrong_range
        self.requests = []

    def open(self, request, timeout):
        if request.get_header("Authorization") is not None:
            raise AssertionError("anonymous public download must not add authentication")
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.get_header("Range", ""))
        if not match:
            raise AssertionError("a bounded byte-range request is required")
        begin, end = map(int, match.groups())
        self.requests.append((begin, end))
        total = len(self.payload) + int(self.wrong_range)
        fail_after = 64 if self.interrupt_from is not None and begin >= self.interrupt_from else None
        return Response(self.payload[begin:end + 1], 206,
                        {"Content-Range": f"bytes {begin}-{end}/{total}"}, fail_after)


class DownloadContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.destination = self.directory / "checkpoint"
        self.destination.mkdir()
        self.filename = "model-00001-of-00001.safetensors"
        self.payload = (b"SYNTHETIC OFFLINE BYTE FIXTURE\n" * 200)[:3089]
        self.chunk = 1024
        small = b'{"synthetic_fixture":true}\n'
        (self.destination / "config.json").write_bytes(small)
        self.manifest = self.directory / "manifest.json"
        self.manifest.write_text(json.dumps({
            "model": "SYNTHETIC-OFFLINE-NOT-A-MODEL", "revision": "0" * 40,
            "files": [
                {"name": "config.json", "bytes": len(small),
                 "git_blob_sha1": hashlib.sha1(f"blob {len(small)}\0".encode() + small).hexdigest()},
                {"name": self.filename, "bytes": len(self.payload),
                 "lfs_sha256": hashlib.sha256(self.payload).hexdigest()},
            ]}))
        self.url_map = self.directory / "urls.json"
        self.url_map.write_text(json.dumps({self.filename: "https://us.aws.cdn.hf.co/synthetic-offline-fixture"}))

    def invoke(self, server):
        argv = ["download_fixed.py", "--manifest", str(self.manifest),
                "--url-map", str(self.url_map), "--directory", str(self.destination), "--workers", "1"]
        with patch.object(sys, "argv", argv), patch.object(download, "CHUNK", self.chunk), \
                patch.object(download.urllib.request, "urlopen", side_effect=server.open), \
                patch.object(download.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            return download.main()

    def test_interrupted_body_resumes_completed_chunks_then_verified_file_needs_no_http(self):
        interrupted = RangeServer(self.payload, interrupt_from=self.chunk)
        with self.assertRaises(RuntimeError):
            self.invoke(interrupted)
        parts = self.destination / ".parts" / self.filename
        first = parts / "00000"
        self.assertEqual(first.read_bytes(), self.payload[:self.chunk])
        first_mtime = first.stat().st_mtime_ns
        self.assertTrue(any(parts.glob("*.partial")), "interrupted body must leave restartable partial state")
        self.assertFalse((self.destination / self.filename).exists())
        self.assertFalse((self.destination / "download-receipt.json").exists())

        resumed = RangeServer(self.payload)
        self.invoke(resumed)
        self.assertTrue(resumed.requests)
        self.assertTrue(all(begin >= self.chunk for begin, _ in resumed.requests), "already-complete first chunk was fetched again")
        self.assertEqual(first.stat().st_mtime_ns, first_mtime)
        self.assertEqual((self.destination / self.filename).read_bytes(), self.payload)
        receipt = json.loads((self.destination / "download-receipt.json").read_text())
        self.assertTrue(receipt["all_files_verified"])
        self.assertEqual(receipt["file_count"], 2)
        weight = next(item for item in receipt["files"] if item["name"] == self.filename)
        self.assertEqual(weight["sha256"], hashlib.sha256(self.payload).hexdigest())

        already_complete = RangeServer(self.payload)
        self.invoke(already_complete)
        self.assertEqual(already_complete.requests, [])
        final = json.loads((self.destination / "download-receipt.json").read_text())
        self.assertEqual(final["downloaded_bytes_this_run"], 0)

    def test_wrong_content_range_cannot_replace_existing_file_or_issue_receipt(self):
        old = b"preserve this rejected destination until a verified replacement exists"
        (self.destination / self.filename).write_bytes(old)
        with self.assertRaises(RuntimeError):
            self.invoke(RangeServer(self.payload, wrong_range=True))
        self.assertEqual((self.destination / self.filename).read_bytes(), old)
        self.assertFalse((self.destination / "download-receipt.json").exists())
        accepted = [path for path in (self.destination / ".parts").rglob("*")
                    if path.is_file() and path.name.isdecimal()]
        self.assertEqual(accepted, [], "wrong ranges cannot become completed chunks")

    def test_correct_ranges_with_wrong_lfs_content_fail_final_verification(self):
        corrupted = bytes([self.payload[0] ^ 1]) + self.payload[1:]
        with self.assertRaises(ValueError):
            self.invoke(RangeServer(corrupted))
        self.assertFalse((self.destination / self.filename).exists())
        self.assertFalse((self.destination / "download-receipt.json").exists())
        self.assertTrue((self.destination / ".parts" / self.filename / "00000").is_file())
        self.assertTrue((self.destination / (self.filename + ".assembled")).is_file())

    def test_same_size_corrupt_resume_chunk_is_not_certified(self):
        parts = self.destination / ".parts" / self.filename
        parts.mkdir(parents=True)
        (parts / "00000").write_bytes(b"X" * self.chunk)
        resumed = RangeServer(self.payload)
        with self.assertRaises(ValueError):
            self.invoke(resumed)
        self.assertFalse((self.destination / self.filename).exists())
        self.assertFalse((self.destination / "download-receipt.json").exists())

    def test_corrupt_staged_git_file_is_rejected_before_transfer(self):
        path = self.destination / "config.json"
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        server = RangeServer(self.payload)
        with self.assertRaises(ValueError):
            self.invoke(server)
        self.assertEqual(server.requests, [])
        self.assertFalse((self.destination / "download-receipt.json").exists())


class HealthServices:
    def __init__(self, status_by_url=None, not_ready=False):
        self.status_by_url = status_by_url or {}
        self.not_ready = not_ready
        self.calls = []

    def open(self, endpoint, timeout):
        self.calls.append(endpoint)
        body = json.dumps({"ready": not self.not_ready}).encode()
        return Response(body, self.status_by_url.get(endpoint, 200))


class PreflightContracts(OfflineCase):
    def setUp(self):
        super().setUp()
        self.bundle = self.directory / "guard-bundle"
        self.bundle.mkdir()
        for name in ("expected_identity.json", "launch_profile.json"):
            shutil.copyfile(ROOT / name, self.bundle / name)
        self.image = {"Id": preflight.CONFIG_ID, "RepoDigests": [preflight.IMAGE],
                      "Architecture": "arm64", "Os": "linux", "Size": 1,
                      "Config": {"Entrypoint": ["/opt/nim/start_server.sh"]}}
        self.memory = {"MemAvailable": 49 * 1024**3, "MemTotal": 120 * 1024**3,
                       "SwapTotal": 0, "SwapFree": 0}
        self.model_directory = self.directory / "unused-model"
        self.model_directory.mkdir()
        self.output = self.directory / "preflight-result.json"

    def invoke(self, health=None, extra_args=()):
        services = health or HealthServices()
        argv = ["preflight.py", "--guard-only", "--model-directory", str(self.model_directory),
                "--model-receipt", str(self.directory / "unused-download-receipt.json"),
                "--output", str(self.output), *extra_args]
        image_result = subprocess.CompletedProcess([], 0, stdout=json.dumps([self.image]).encode())
        with patch.object(sys, "argv", argv), patch.object(preflight, "ROOT", self.bundle), \
                patch.object(preflight, "memory_snapshot", return_value=self.memory), \
                patch.object(preflight, "require_free_port"), \
                patch.object(preflight.subprocess, "run", return_value=image_result) as docker, \
                patch.object(preflight.urllib.request, "build_opener", return_value=services), \
                contextlib.redirect_stdout(io.StringIO()):
            code = preflight.main()
        for call in docker.call_args_list:
            self.assertEqual(call.args[0], ["docker", "image", "inspect", preflight.IMAGE],
                             "preflight may only inspect the installed image")
        result = json.loads(self.output.read_bytes())
        self.assertFalse(result["gpu_model_requested"])
        self.assertFalse(result["production_modified"])
        return code, result, docker, services

    def test_healthy_read_only_guard_inspects_all_five_services(self):
        code, result, docker, services = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(result["preflight"], "passed")
        self.assertEqual(services.calls, list(preflight.BASELINE_ENDPOINTS))
        self.assertEqual(len(result["existing_services"]), 5)
        self.assertEqual(result["requested_context_length"], 24576)
        self.assertEqual(result["budget"]["runtime_overhead_estimate_bytes"], 5 * 1024**3)
        docker.assert_called_once()

    def test_changed_profile_fails_before_docker_or_service_inspection(self):
        path = self.bundle / "launch_profile.json"
        profile = json.loads(path.read_text())
        profile["arguments"][profile["arguments"].index("--context-length") + 1] = "8192"
        path.write_text(json.dumps(profile))
        code, result, docker, services = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")
        docker.assert_not_called()
        self.assertEqual(services.calls, [])

    def test_low_memory_rejects_before_docker_or_service_inspection(self):
        self.memory["MemAvailable"] = 43 * 1024**3
        code, result, docker, services = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")
        docker.assert_not_called()
        self.assertEqual(services.calls, [])

    def test_old_static_fraction_is_rejected_without_a_gpu_load(self):
        code, result, docker, services = self.invoke(extra_args=("--static-fraction", "0.24"))
        self.assertEqual(code, 1)
        self.assertLess(result["budget"]["static_budget_estimate_bytes"], result["budget"]["raw_weight_bytes"])
        docker.assert_not_called()
        self.assertEqual(services.calls, [])

    def test_other_image_config_cannot_pass_as_the_pinned_original(self):
        self.image["Id"] = "sha256:" + "0" * 64
        code, result, docker, services = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")
        docker.assert_called_once()
        self.assertEqual(services.calls, [])

    def test_old_nim_service_failure_is_preserved_as_failed_preflight(self):
        services = HealthServices({"http://127.0.0.1:8007/health": 503})
        code, result, _, observed = self.invoke(services)
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")
        self.assertIn("http://127.0.0.1:8007/health", observed.calls)

    def test_retriever_200_with_ready_false_is_not_healthy(self):
        code, result, _, _ = self.invoke(HealthServices(not_ready=True))
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")

    def test_old_cpu_profile_cannot_be_reused_for_24k_startup(self):
        report = self.directory / "cpu-receipt.json"
        original = json.dumps({"cpu_preflight": "passed", "gpu_initialized": False,
                               "launch_profile_sha256": "aa4d19bb8124c15103da16edd8aafb6d4befc706a4352cc6c904e56a9bf4ba35",
                               "requested_context_length": 8192, "requested_max_total_tokens": 8192,
                               "memory_formula_verified": True, "image_tokens_per_probe": [256, 256]}).encode()
        report.write_bytes(original)
        code, result, _, _ = self.invoke(extra_args=("--cpu-report", str(report)))
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")
        self.assertEqual(report.read_bytes(), original, "the old CPU evidence must be preserved")

    def test_current_profile_hash_does_not_override_wrong_cpu_context(self):
        report = self.directory / "cpu-receipt.json"
        report.write_text(json.dumps({"cpu_preflight": "passed", "gpu_initialized": False,
                                      "launch_profile_sha256": preflight.PROFILE_SHA256,
                                      "requested_context_length": 8192, "requested_max_total_tokens": 8192,
                                      "memory_formula_verified": True, "image_tokens_per_probe": [256, 256]}))
        code, result, _, _ = self.invoke(extra_args=("--cpu-report", str(report)))
        self.assertEqual(code, 1)
        self.assertEqual(result["preflight"], "failed")

    def test_prior_preflight_evidence_is_not_overwritten(self):
        prior = b'{"prior_attempt":"preserve original evidence"}\n'
        self.output.write_bytes(prior)
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), prior)


class FixedMetadataContracts(unittest.TestCase):
    def test_download_checkpoint_matches_independently_pinned_identity(self):
        expected_raw = (ROOT / "expected_identity.json").read_bytes()
        self.assertEqual(hashlib.sha256(expected_raw).hexdigest(), preflight.IDENTITY_SHA256)
        expected = json.loads(expected_raw)
        checkpoint = json.loads((ROOT / "checkpoint.json").read_text())
        self.assertEqual((checkpoint["model"], checkpoint["revision"]), (expected["model"], expected["revision"]))
        actual = {item["name"]: item for item in checkpoint["files"]}
        self.assertEqual(len(actual), len(checkpoint["files"]))
        self.assertEqual(set(actual), {item["name"] for item in expected["files"]})
        for item in expected["files"]:
            with self.subTest(file=item["name"]):
                received = actual[item["name"]]
                self.assertEqual(received["bytes"], item["bytes"])
                key = "lfs_sha256" if "lfs_sha256" in item else "git_blob_sha1"
                self.assertEqual(received[key], item[key])
        self.assertEqual(sum(item["bytes"] for item in actual.values()), expected["total_file_bytes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
