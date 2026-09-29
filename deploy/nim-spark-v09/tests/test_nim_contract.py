import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

sys.path.insert(0, str(ROOT))
preflight = module("preflight")
accept = module("accept_text_once")
gpu = module("verify_gpu_trace")


def response(finish="stop", model=accept.MODEL, usage=None):
    return json.dumps({"model": model, "choices": [{"finish_reason": finish,
        "message": {"role": "assistant", "content": "馆方记载不能直接证明未知器物归属。"}}],
        "usage": usage or {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}}).encode()

class Response:
    status = 200
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.raw

class Opener:
    def __init__(self, raw=None, error=None):
        self.raw, self.error, self.calls = raw, error, []
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error: raise self.error
        return Response(self.raw)

class ImageAndResources(unittest.TestCase):
    def test_unowned_container_rejected_without_docker_call(self):
        with patch.object(gpu.subprocess, "run") as run:
            with self.assertRaises(ValueError): gpu.capture_identity("other-service")
            run.assert_not_called()
    def valid_image(self):
        return {"Id": preflight.CONFIG_ID, "RepoDigests": [preflight.IMAGE],
                "Architecture": "arm64", "Os": "linux", "Size": 23_000_000_000}
    def test_pinned_official_arm64_identity(self):
        self.assertEqual(preflight.require_image(self.valid_image())["Architecture"], "arm64")
    def test_other_manifest_architecture_config_and_mutable_tag_fail(self):
        for key, value in [("Architecture", "amd64"), ("Id", "sha256:" + "0" * 64),
                           ("RepoDigests", [preflight.IMAGE.replace("@sha256:", ":")]), ("Os", "windows")]:
            data = self.valid_image(); data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): preflight.require_image(data)
    def test_floor_preserves_headroom(self):
        preflight.require_resources({"MemAvailable": preflight.MIN_AVAILABLE_BYTES})
        for value in [preflight.MIN_AVAILABLE_BYTES - 1, None, True, -1]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                preflight.require_resources({"MemAvailable": value})
    def test_unapproved_model_receipt_rejected_before_loading(self):
        with self.assertRaises(ValueError): preflight.verify_model("/missing", b'{}')
    def model_fixture(self, root):
        files = []
        for n in range(14):
            raw = f"public-{n}".encode(); name = f"file-{n}"
            (root / name).write_bytes(raw)
            files.append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        return json.dumps({"model": preflight.MODEL, "all_files_verified": True,
                           "file_count": 14, "files": files, "total_file_bytes": sum(x["bytes"] for x in files)}).encode()
    def test_content_verified_not_only_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); raw = self.model_fixture(root)
            with patch.object(preflight, "MODEL_RECEIPT_SHA256", hashlib.sha256(raw).hexdigest()):
                self.assertTrue(preflight.verify_model(root, raw)["all_files_verified"])
                (root / "file-0").write_bytes(b"forged-0")
                with self.assertRaises(ValueError): preflight.verify_model(root, raw)
    def test_symlink_cannot_escape_approved_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); raw = self.model_fixture(root)
            outside = root / "outside"; outside.write_bytes((root / "file-0").read_bytes())
            (root / "file-0").unlink(); (root / "file-0").symlink_to(outside)
            with patch.object(preflight, "MODEL_RECEIPT_SHA256", hashlib.sha256(raw).hexdigest()):
                with self.assertRaises(ValueError): preflight.verify_model(root, raw)

class OneOriginalPublicRequest(unittest.TestCase):
    def test_request_is_bounded_public_text_and_loopback(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(response())
            receipt = accept.accept_once(temp, opener=opener)
            self.assertTrue(receipt["accepted_interface"])
            self.assertFalse(receipt["semantic_quality_proven"])
            self.assertEqual(len(opener.calls), 1)
            request, timeout = opener.calls[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8007/v1/chat/completions")
            self.assertEqual(timeout, 80)
            self.assertEqual(json.loads(request.data), accept.REQUEST)
            self.assertEqual(set(json.loads(request.data)), {"model", "messages", "max_tokens", "temperature", "stream"})
            self.assertEqual(accept.REQUEST["max_tokens"], 256)
            self.assertTrue(all(isinstance(m["content"], str) for m in accept.REQUEST["messages"]))
            self.assertEqual(Path(temp, "response.raw.json").read_bytes(), response())
            self.assertEqual(receipt["response_sha256"], hashlib.sha256(response()).hexdigest())
    def test_claim_prevents_same_package_retry_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(response()); accept.accept_once(temp, opener=opener)
            with self.assertRaises(FileExistsError): accept.accept_once(temp, opener=opener)
            self.assertEqual(len(opener.calls), 1)
    def test_network_failure_is_preserved_and_never_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(error=TimeoutError("SECRET-do-not-export"))
            receipt = accept.accept_once(temp, opener=opener)
            self.assertFalse(receipt["accepted_interface"])
            self.assertEqual(receipt["failure_category"], "transport_error")
            self.assertNotIn("SECRET", json.dumps(receipt))
            with self.assertRaises(FileExistsError): accept.accept_once(temp, opener=opener)
            self.assertEqual(len(opener.calls), 1)
    def test_http_failure_preserves_original_bytes_and_safe_category(self):
        from io import BytesIO
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(error=urllib.error.HTTPError("http://127.0.0.1:8007", 403, "SECRET", {}, BytesIO(b'{"original":"error"}')))
            receipt = accept.accept_once(temp, opener=opener)
            self.assertEqual(receipt["http_status"], 403)
            self.assertEqual(receipt["failure_category"], "http_error")
            self.assertNotIn("SECRET", json.dumps(receipt))
            self.assertEqual(Path(temp, "response.raw.json").read_bytes(), b'{"original":"error"}')
            self.assertEqual(len(opener.calls), 1)
    def test_nonstop_even_parseable_json_is_not_completed(self):
        for finish in ["length", "content_filter", None]:
            with self.subTest(finish=finish), self.assertRaises(ValueError): accept.validate_response(response(finish))
    def test_nonstop_preserves_verified_usage_without_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(response("length"))
            receipt = accept.accept_once(temp, opener=opener)
            self.assertFalse(receipt["accepted_interface"])
            self.assertEqual(receipt["failure_category"], "response_not_complete")
            self.assertEqual(receipt["usage"]["completion_tokens"], 20)
            self.assertEqual(len(opener.calls), 1)
    def test_incomplete_json_and_wrong_identity_are_rejected(self):
        for raw in [b'{', response(model="different-model")]:
            with self.subTest(raw=raw), self.assertRaises(ValueError): accept.validate_response(raw)
    def test_usage_is_not_coerced_or_allowed_above_cap(self):
        for usage in [{"prompt_tokens": 200, "completion_tokens": True, "total_tokens": 201},
                      {"prompt_tokens": 200, "completion_tokens": 257, "total_tokens": 457},
                      {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 999}]:
            with self.subTest(usage=usage), self.assertRaises(ValueError): accept.validate_response(response(usage=usage))
    def test_invalid_json_failure_safe_with_original_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            opener = Opener(b'{"unfinished":')
            receipt = accept.accept_once(temp, opener=opener)
            self.assertEqual(receipt["failure_category"], "invalid_json")
            self.assertEqual(receipt["response_sha256"], hashlib.sha256(b'{"unfinished":').hexdigest())
            self.assertEqual(len(opener.calls), 1)

class CudaProcessBinding(unittest.TestCase):
    def fixture(self):
        before = {"container_id": "a" * 64, "image": gpu.IMAGE, "image_id": gpu.CONFIG_ID,
                  "entrypoint": ["/opt/nim/start_server.sh"], "started_at": "2026-09-29T00:00:00Z",
                  "host_init_pid": 123, "restart_count": 0, "running": True,
                  "host_pids": [123, 456], "namespace_pids": [1, 20], "captured_at_unix_ns": 100}
        after = dict(before, captured_at_unix_ns=500)
        receipt = {"accepted_interface": True, "model": gpu.MODEL, "inference_requests_sent": 1,
                   "automatic_retries": 0, "finish_reason": "stop", "request_sha256": "b" * 64,
                   "response_sha256": "c" * 64, "request_started_at_unix_ns": 300,
                   "request_finished_at_unix_ns": 400}
        arm = {"http_status": 200, "trace_files_before": [], "finished_at_unix_ns": 200,
               "request": {"output_dir": "/evidence", "num_steps": 8, "start_step": 0,
                           "activities": ["CPU", "GPU"]}}
        trace = {"traceEvents": [{"cat": "cpu_op", "pid": 20},
                   {"cat": "kernel", "ph": "X", "dur": 4, "name": "public-kernel"},
                   {"cat": "cuda_runtime", "ph": "X", "dur": 2}]}
        return trace, receipt, before, after, arm
    def test_same_process_request_and_cuda_events_bound(self):
        data = self.fixture()
        self.assertTrue(gpu.verify_binding(*data, 350)["candidate_process_bound"])
        self.assertFalse(gpu.verify_binding(*data, 350)["full_request_covered"])
        self.assertTrue(gpu.summarize(data[0])["cuda_execution_verified"])
    def test_unrelated_cpu_pid_rejected(self):
        data = self.fixture(); data[0]["traceEvents"][0]["pid"] = 999
        with self.assertRaises(ValueError): gpu.verify_binding(*data, 350)
    def test_restart_or_container_substitution_rejected(self):
        for key, value in [("restart_count", 1), ("container_id", "d" * 64),
                           ("started_at", "changed"), ("image_id", "changed")]:
            data = self.fixture(); data[3][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): gpu.verify_binding(*data, 350)
    def test_trace_outside_request_window_rejected(self):
        for mtime in [250, 450, True]:
            with self.subTest(mtime=mtime), self.assertRaises(ValueError): gpu.verify_binding(*self.fixture(), mtime)
    def test_prior_trace_or_unbounded_profiler_rejected(self):
        data = self.fixture(); data[4]["trace_files_before"] = ["old.trace.json"]
        with self.assertRaises(ValueError): gpu.verify_binding(*data, 350)
        data = self.fixture(); data[4]["request"]["num_steps"] = 100
        with self.assertRaises(ValueError): gpu.verify_binding(*data, 350)
    def test_only_one_successful_stopped_inference_request_accepted(self):
        for key, value in [("inference_requests_sent", 2), ("automatic_retries", 1),
                           ("finish_reason", "length"), ("accepted_interface", False),
                           ("request_sha256", "invalid")]:
            data = self.fixture(); data[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): gpu.verify_binding(*data, 350)
    def test_cpu_or_zero_duration_events_cannot_prove_cuda(self):
        for category in ["cpu_op", "cuda_runtime", "kernel"]:
            trace = {"traceEvents": [{"cat": category, "ph": "X", "dur": 1}]}
            with self.subTest(category=category), self.assertRaises(ValueError): gpu.summarize(trace)
        for duration in [0, -1, float("nan"), True]:
            trace = self.fixture()[0]; trace["traceEvents"][1]["dur"] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError): gpu.summarize(trace)

if __name__ == "__main__": unittest.main()
