"""Offline protocol tests: synthetic images, runtime and trace; no GPU/network."""
import contextlib
import ast
import copy
import gzip
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qwen38_probe", ROOT / "probe_once.py")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.node = self.root / "node"; self.node.mkdir()
        self.view = self.root / "model-view"; self.view.mkdir()
        self.profiles = self.root / "profiles"; self.profiles.mkdir()
        self.inputs = self.root / "inputs"; self.inputs.mkdir()
        self.expected = []
        for n in (1, 2):
            raw = b"\xff\xd8synthetic-public-photo-" + str(n).encode()
            name = f"photo-{n}.jpg"; (self.inputs / name).write_bytes(raw)
            self.expected.append({"name": name, "input_id": f"photo-{n}", "bytes": len(raw), "sha256": probe.digest(raw)})
        self.stack = contextlib.ExitStack()
        for name, value in (("NODE_ROOT", self.node), ("MODEL_VIEW", self.view), ("INPUTS", tuple(self.expected))):
            self.stack.enter_context(mock.patch.object(probe, name, value))
        self.stack.enter_context(mock.patch.object(subprocess, "run", side_effect=AssertionError("real subprocess forbidden")))
        self.stack.enter_context(mock.patch.object(subprocess, "Popen", side_effect=AssertionError("real process forbidden")))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.before = {"container_id": probe.CONTAINER_ID, "name": "/" + probe.CONTAINER_NAME,
            "image": probe.IMAGE, "image_id": probe.IMAGE_ID, "entrypoint": ["/opt/nim/start_server.sh"],
            "started_at": probe.STARTED_AT, "host_init_pid": 100, "restart_count": 0, "running": True,
            "processes": [{"host_pid": 100, "start_ticks": 1000, "namespace_pid": 1},
                          {"host_pid": 200, "start_ticks": 2000, "namespace_pid": 10}],
            "profile_root": str(self.profiles), "captured_at_unix_ns": 100}
        self.after = {**copy.deepcopy(self.before), "captured_at_unix_ns": 1000}
        self.trace = {"traceEvents": [{"cat": "cpu_op", "ph": "X", "pid": 10, "dur": 5},
            {"cat": "cuda_runtime", "ph": "X", "pid": 10, "name": "cudaLaunchKernel", "dur": 2, "args": {"correlation": 7}},
            {"cat": "kernel", "ph": "X", "pid": 0, "name": "syntheticKernel", "dur": 3, "args": {"correlation": 7}}]}
        self.data = {"model": probe.MODEL, "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"first_visible": "visible feature A", "second_visible": "visible feature B"})}}],
            "usage": {"prompt_tokens": 520, "completion_tokens": 30, "total_tokens": 550,
                      "prompt_tokens_details": {"image_tokens": 494}}}
        self.request, self.meta = probe.build_request(self.inputs); self.response = probe.serialized(self.data)
        self.arm = {"http_status": 200, "response_sha256": "f" * 64, "action": "start", "request": {
            "output_dir": "/evidence/" + probe.PROFILE_NAME, "num_steps": 8, "start_step": 0, "activities": ["CPU", "GPU"]},
            "trace_files_before": [], "started_at_unix_ns": 200, "finished_at_unix_ns": 300}
        self.receipt = {**probe.validate_response(self.response, 200), "request_sha256": probe.digest(self.request),
            "response_sha256": probe.digest(self.response), "request_started_at_unix_ns": 400,
            "request_finished_at_unix_ns": 900, "elapsed_seconds": 1, "inference_requests_sent": 1, "automatic_retries": 0}
        self.trace_meta = {"trace_sha256": "a" * 64, "trace_bytes": 1024, "trace_mtime_unix_ns": 500}
        self.controls = []; self.posts = []

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def proof(self):
        return probe.verify_binding(self.request, self.response, self.receipt, self.before, self.after,
                                    self.arm, self.trace, self.trace_meta)

    def control(self, action):
        self.controls.append(action)
        return copy.deepcopy(self.arm) if action == "start" else {"http_status": 200, "action": "stop"}

    def post(self, url, data=None, **_):
        self.posts.append((url, data))
        self.assertEqual(url, "http://127.0.0.1:8009/v1/chat/completions")
        self.assertEqual(data, self.request)
        path = self.profiles / probe.PROFILE_NAME / "synthetic.trace.json.gz"
        path.write_bytes(gzip.compress(probe.serialized(self.trace)))
        os.utime(path, ns=(500, 500))
        return 200, self.response

    def run_fake(self, *, post=None, health_error=None):
        capture = mock.Mock(side_effect=[self.before, self.after, self.after])
        with mock.patch.object(probe, "capture_identity", capture), \
             mock.patch.object(probe, "health", side_effect=health_error, return_value={"synthetic": True}), \
             mock.patch.object(probe, "profile_control", side_effect=self.control), \
             mock.patch.object(probe, "http", side_effect=post or self.post), \
             mock.patch.object(probe.time, "time_ns", side_effect=[200, 300, 400, 900]), \
             mock.patch.object(probe.time, "monotonic", side_effect=[1.0, 2.0]), \
             contextlib.redirect_stdout(io.StringIO()):
            return probe.run_probe(self.inputs, operator_authorized=True)

    def test_authorization_absent_refuses_before_any_io_or_evidence_creation(self):
        with mock.patch.object(probe, "capture_identity", side_effect=AssertionError("no Docker")), \
             mock.patch.object(probe, "http", side_effect=AssertionError("no HTTP")), \
             mock.patch.object(probe, "profile_control", side_effect=AssertionError("no exec")):
            with self.assertRaises(PermissionError):probe.run_probe(self.inputs, operator_authorized=False)
        self.assertFalse((self.node / probe.OUTPUT_NAME).exists())
        with mock.patch.object(sys, "argv", ["probe_once", "--input-directory", str(self.inputs)]), self.assertRaises(PermissionError):
            probe.main()

    def test_runtime_digest_entrypoint_start_identity_and_readonly_model_are_required(self):
        item = {"Id": probe.CONTAINER_ID, "Name": "/" + probe.CONTAINER_NAME, "Image": probe.IMAGE_ID,
            "RestartCount": 0, "State": {"Running": True, "StartedAt": probe.STARTED_AT, "Pid": 100},
            "Config": {"Image": probe.IMAGE, "Entrypoint": ["/opt/nim/start_server.sh"],
                       "Env": ["NIM_MODEL_PATH=/models/qwen38", "NIM_SERVED_MODEL_NAME=" + probe.MODEL]},
            "HostConfig": {"Memory": 40 * 1024**3, "MemorySwap": 40 * 1024**3,
                           "PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8009"}]}},
            "Mounts": [{"Type": "bind", "Source": str(self.view), "Destination": "/models/qwen38", "RW": False},
                       {"Type": "bind", "Source": str(self.profiles), "Destination": "/evidence", "RW": True}]}
        self.assertEqual(probe.require_runtime(item), self.profiles)
        for section, key, value in ((None, "Id", "0" * 64), (None, "Name", "/old"),
                (None, "RestartCount", 1), ("Config", "Image", "wrong"), ("Config", "Entrypoint", ["/bin/sh"]),
                ("State", "Running", False), ("State", "StartedAt", "old-start"), ("State", "Pid", 0),
                ("HostConfig", "MemorySwap", -1)):
            bad = copy.deepcopy(item); (bad if section is None else bad[section])[key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):probe.require_runtime(bad)
        item["Mounts"][0]["RW"] = True
        with self.assertRaisesRegex(ValueError, "read-only"):probe.require_runtime(item)

    def test_not_ready_preserves_failure_with_zero_profiles_execs_or_inference(self):
        self.assertEqual(self.run_fake(health_error=ValueError("candidate not ready")), 1)
        failure = json.loads((self.node / probe.OUTPUT_NAME / "failure.json").read_bytes())
        self.assertEqual(failure["inference_requests_sent"], 0)
        self.assertEqual(self.posts, []); self.assertEqual(self.controls, [])

    def test_original_retained_health_guard_memory_and_model_are_required(self):
        replies = [(200, b'{}'), (200, b'{}'), (200, probe.serialized({"ready": True,
            "minimum_remaining_memory_kib": 33554432, "remaining_memory_watchdog_seconds": 2})),
            (200, b'{}'), (200, probe.serialized({"data": [{"id": probe.MODEL}]}))]
        memory = "MemAvailable: 46137344 kB\nSwapTotal: 0 kB\n"
        def verify(rows, mem=memory):
            with mock.patch.object(probe, "http", side_effect=rows) as http, \
                 mock.patch.object(Path, "read_text", return_value=mem):
                result = probe.health()
                self.assertTrue(all(call.args[0].startswith("http://127.0.0.1:") for call in http.call_args_list))
                self.assertTrue(all(len(call.args) == 1 for call in http.call_args_list))
                return result
        self.assertEqual(len(verify(replies)["endpoints"]), 5)
        bad = copy.deepcopy(replies); bad[0] = (503, b'not ready')
        with self.assertRaisesRegex(ValueError, "retained"):verify(bad)
        for key, value in (("ready", False), ("minimum_remaining_memory_kib", 16777216),
                           ("remaining_memory_watchdog_seconds", 3)):
            bad = copy.deepcopy(replies); guard = json.loads(bad[2][1]); guard[key] = value
            bad[2] = (200, probe.serialized(guard))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "32 GiB"):verify(bad)
        bad = copy.deepcopy(replies); bad[3] = (503, b'loading')
        with self.assertRaisesRegex(ValueError, "not ready"):verify(bad)
        bad = copy.deepcopy(replies); bad[4] = (200, b'{"data":[{"id":"other"}]}')
        with self.assertRaisesRegex(ValueError, "model identity"):verify(bad)
        for mem in ("MemAvailable: 35651583 kB\nSwapTotal: 0 kB\n", memory.replace("SwapTotal: 0", "SwapTotal: 1")):
            with self.subTest(memory=mem), self.assertRaisesRegex(ValueError, "34 GiB"):verify(replies, mem)

    def test_one_original_structured_request_publishes_only_bound_counts_and_hashes(self):
        self.assertEqual(self.run_fake(), 0)
        out = self.node / probe.OUTPUT_NAME
        result = json.loads((out / "gpu-proof.json").read_bytes())
        self.assertEqual(len(self.posts), 1); self.assertEqual(self.controls, ["start"])
        self.assertEqual((out / "response.raw.json").read_bytes(), self.response)
        self.assertEqual((out / "request.raw.json").read_bytes(), self.request)
        self.assertTrue(result["structured_image_output_valid"]); self.assertEqual(result["profile_step_limit"], 8)
        self.assertEqual(result["candidate_kernel_runtime_correlation_count"], 1)
        self.assertFalse(result["expert_validation"]); self.assertFalse(result["end_to_end_acceleration_proven"])
        self.assertFalse(result["full_request_covered"]); self.assertTrue(result["raw_trace_private"])
        self.assertFalse(list(out.glob("*.trace.json*")))
        self.assertNotIn("traceEvents", result); self.assertNotIn("messages", result)
        with self.assertRaises(FileExistsError):probe.run_probe(self.inputs, operator_authorized=True)
        self.assertEqual(len(self.posts), 1)

    def test_http_failure_sends_no_second_inference_and_only_cleans_same_profiler(self):
        def failed(url, data, **_):
            self.posts.append((url, data))
            raise urllib_error(url)
        self.assertEqual(self.run_fake(post=failed), 1)
        out = self.node / probe.OUTPUT_NAME
        failure = json.loads((out / "failure.json").read_bytes())
        self.assertEqual(len(self.posts), 1); self.assertEqual(self.controls, ["start", "stop"])
        self.assertEqual(failure["automatic_retries"], 0); self.assertFalse(failure["gpu_proof_published"])
        self.assertEqual((out / "http-error.raw").read_bytes(), b"schema refused")
        self.assertFalse((out / "gpu-proof.json").exists())

    def test_changed_runtime_on_failure_cannot_stop_another_profiler(self):
        self.after["container_id"] = "0" * 64
        def failed(url, data, **_):
            self.posts.append((url, data)); raise TimeoutError("single request timed out")
        self.assertEqual(self.run_fake(post=failed), 1)
        failure = json.loads((self.node / probe.OUTPUT_NAME / "failure.json").read_bytes())
        self.assertEqual(self.controls, ["start"]); self.assertEqual(len(self.posts), 1)
        self.assertTrue(failure["profile_cleanup"]["profile_may_remain_armed"])

    def test_finish_length_or_wrong_schema_is_not_repaired_or_retried(self):
        self.data["choices"][0]["finish_reason"] = "length"; self.response = probe.serialized(self.data)
        self.assertEqual(self.run_fake(), 1)
        out = self.node / probe.OUTPUT_NAME
        self.assertEqual((out / "response.raw.json").read_bytes(), self.response)
        self.assertEqual(len(self.posts), 1); self.assertEqual(self.controls, ["start", "stop"])
        self.assertFalse((out / "gpu-proof.json").exists())

    def test_original_public_image_corruption_refuses_before_profile(self):
        path = self.inputs / "photo-1.jpg"; raw = path.read_bytes(); path.write_bytes(b"X" + raw[1:])
        self.assertEqual(self.run_fake(), 1)
        self.assertEqual(self.posts, []); self.assertEqual(self.controls, [])

    def test_schema_stop_usage_and_original_model_constraints(self):
        baseline = copy.deepcopy(self.data)
        mutations = [lambda d:d.update(model="other"), lambda d:d["choices"][0].update(finish_reason="length"),
            lambda d:d["choices"][0]["message"].update(content='{"first_visible":"a","first_visible":"b","second_visible":"c"}'),
            lambda d:d["choices"][0]["message"].update(content='{"first_visible":"","second_visible":"b"}'),
            lambda d:d["choices"][0]["message"].update(content=json.dumps({"first_visible": "a" * 81, "second_visible": "b"})),
            lambda d:d["choices"][0]["message"].update(content='{"first_visible":"a","second_visible":"b","extra":1}'),
            lambda d:d["usage"].update(completion_tokens=True), lambda d:d["usage"].update(total_tokens=1),
            lambda d:d["usage"]["prompt_tokens_details"].update(image_tokens=0),
            lambda d:d["usage"]["prompt_tokens_details"].update(image_tokens=513)]
        for mutation in mutations:
            d = copy.deepcopy(baseline); mutation(d)
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, TypeError)):
                probe.validate_response(probe.serialized(d), 200)
        self.assertEqual(probe.validate_response(self.response, 200)["finish_reason"], "stop")

    def test_corrupt_request_cannot_be_blessed_by_an_updated_receipt_hash(self):
        payload = json.loads(self.request)
        payload["messages"][0]["content"][1]["image_url"]["url"] = "data:image/jpeg;base64,eA=="
        self.request = probe.serialized(payload); self.receipt["request_sha256"] = probe.digest(self.request)
        with self.assertRaisesRegex(ValueError, "public image SHA"):self.proof()

    def test_wrong_response_hash_or_claimed_expert_validation_refuses(self):
        for key, value in (("response_sha256", "0" * 64), ("expert_validation", True), ("semantic_quality_proven", True)):
            with self.subTest(key=key):
                old = self.receipt[key]; self.receipt[key] = value
                with self.assertRaises(ValueError):self.proof()
                self.receipt[key] = old

    def test_runtime_restart_worker_pid_reuse_or_unowned_gpu_events_refuses(self):
        self.assertTrue(self.proof()["cuda_execution_verified"])
        saved = copy.deepcopy(self.after)
        for key, value in (("container_id", "0" * 64), ("started_at", "changed"), ("restart_count", 1)):
            self.after[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):self.proof()
            self.after = copy.deepcopy(saved)
        self.after["processes"][1]["start_ticks"] += 1
        with self.assertRaisesRegex(ValueError, "candidate CPU process"):self.proof()
        self.after = saved
        self.trace["traceEvents"][1]["pid"] = 999
        with self.assertRaisesRegex(ValueError, "candidate-owned"):self.proof()

    def test_missing_correlation_and_nonfinite_or_zero_duration_are_not_cuda_proof(self):
        baseline = copy.deepcopy(self.trace)
        for duration in (0, -1, True, float("nan"), float("inf")):
            self.trace = copy.deepcopy(baseline); self.trace["traceEvents"][2]["dur"] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):self.proof()
        self.trace = baseline; self.trace["traceEvents"][2]["args"]["correlation"] = 8
        with self.assertRaisesRegex(ValueError, "correlate"):self.proof()

    def test_old_trace_wrong_steps_or_multiple_request_claim_refuses(self):
        for value in (399, 901):
            self.trace_meta["trace_mtime_unix_ns"] = value
            with self.assertRaisesRegex(ValueError, "time window"):self.proof()
        self.trace_meta["trace_mtime_unix_ns"] = 500
        for key, value in (("num_steps", 9), ("start_step", 1)):
            old = self.arm["request"][key]; self.arm["request"][key] = value
            with self.assertRaisesRegex(ValueError, "eight-step"):self.proof()
            self.arm["request"][key] = old
        self.arm["trace_files_before"] = ["old.trace.json"]
        with self.assertRaisesRegex(ValueError, "fresh"):self.proof()
        self.arm["trace_files_before"] = []
        for key, value in (("inference_requests_sent", 2), ("automatic_retries", 1)):
            old = self.receipt[key]; self.receipt[key] = value
            with self.assertRaises(ValueError):self.proof()
            self.receipt[key] = old
        for metadata, key, value in ((self.arm, "response_sha256", "aaa"), (self.arm, "action", "stop"),
                (self.trace_meta, "trace_sha256", "old"), (self.trace_meta, "trace_bytes", 0)):
            old = metadata[key]; metadata[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):self.proof()
            metadata[key] = old

    def test_bounded_private_gzip_trace_and_change_during_read(self):
        path = self.root / "private.trace.json.gz"; path.write_bytes(gzip.compress(probe.serialized(self.trace)))
        parsed, metadata = probe.read_trace(path)
        self.assertEqual(parsed, self.trace); self.assertEqual(metadata["trace_sha256"], probe.digest(path.read_bytes()))
        with mock.patch.object(probe, "MAX_DECOMPRESSED_TRACE_BYTES", 8), self.assertRaisesRegex(ValueError, "decompressed"):
            probe.read_trace(path)
        original_read = Path.read_bytes
        def changed(p):
            raw = original_read(p)
            if p == path:p.write_bytes(raw + b"x")
            return raw
        with mock.patch.object(Path, "read_bytes", new=changed), self.assertRaisesRegex(ValueError, "changed"):
            probe.read_trace(path)

    def test_profile_control_is_only_fixed_inner_api_and_exact_id_without_source_export(self):
        value = subprocess.CompletedProcess([], 0, stdout=probe.serialized({"http_status": 200, "response_sha256": "f" * 64}))
        with mock.patch.object(probe.subprocess, "run", return_value=value) as run:
            start = probe.profile_control("start")
            args = run.call_args.args[0]
            self.assertEqual(args[:5], ["docker", "exec", "-i", probe.CONTAINER_ID, "python3"])
            self.assertIn("http://127.0.0.1:8001/start_profile", args[-1])
            tree = ast.parse(args[-1])
            disk_open = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "open"]
            self.assertEqual(disk_open, []); self.assertNotIn("torch", args[-1]); self.assertNotIn("pathlib", args[-1])
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["num_steps"], 8)
            self.assertEqual(start["action"], "start")
            with self.assertRaises(ValueError):probe.profile_control("restart")
            self.assertEqual(run.call_count, 1)
        with mock.patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess([], 0,
                stdout=b'{"http_status":200,"response_sha256":"aaa"}')), self.assertRaises(ValueError):
            probe.profile_control("start")


def urllib_error(url):
    return probe.urllib.error.HTTPError(url, 400, "schema refused", {}, io.BytesIO(b"schema refused"))


if __name__ == "__main__":unittest.main()
