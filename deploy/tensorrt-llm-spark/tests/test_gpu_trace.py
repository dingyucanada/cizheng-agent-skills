import importlib.util
import copy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location("trt_trace", Path(__file__).parents[1] / "verify_gpu_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def event(category, name="public kernel", duration=3):
    return {"ph": "X", "cat": category, "name": name, "dur": duration}


class GpuTraceTests(unittest.TestCase):
    def test_cuda_execution_counts_without_utilization_or_quality_claim(self):
        summary = trace.summarize({"traceEvents": [event("kernel"), event("kernel"), event("cuda_runtime"), event("cpu_op")]})
        self.assertEqual(summary["cuda_kernel_event_count"], 2)
        self.assertEqual(summary["distinct_cuda_kernel_names"], 1)
        self.assertEqual(summary["cuda_runtime_event_count"], 1)
        self.assertFalse(summary["gpu_utilization_measured"])
        self.assertFalse(summary["end_to_end_acceleration_proven"])
        self.assertFalse(summary["semantic_quality_proven"])

    def test_cpu_only_or_only_one_cuda_category_is_insufficient(self):
        for events in ([], [event("cpu_op")], [event("kernel")], [event("cuda_runtime")]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                trace.summarize({"traceEvents": events})

    def test_nonfinite_or_bool_duration_is_not_kernel_evidence(self):
        for duration in (float("nan"), float("inf"), True, -1, 0, "3"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                trace.summarize({"traceEvents": [event("kernel", duration=duration), event("cuda_runtime")]})

    def test_instant_marker_is_not_a_kernel_duration(self):
        value = event("kernel")
        value["ph"] = "i"
        with self.assertRaises(ValueError):
            trace.summarize({"traceEvents": [value, event("cuda_runtime")]})


class RuntimeBindingTests(unittest.TestCase):
    def test_failed_runtime_capture_does_not_publish_empty_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "identity.json"
            with patch.object(trace, "capture_identity", side_effect=RuntimeError("fixture")), patch("sys.argv", ["verify", "--capture-runtime", "--output", str(output)]):
                with self.assertRaises(RuntimeError):trace.main()
            self.assertFalse(output.exists())

    def fixture(self):
        before = {"container_id": "a" * 64, "image": trace.IMAGE,
                  "image_id": "sha256:" + "b" * 64, "started_at": "2026-09-29T20:00:00Z",
                  "host_init_pid": 100, "restart_count": 0, "running": True,
                  "host_pids": [100, 200], "namespace_pids": [1, 25],
                  "captured_at_unix_ns": 10, "trace_exists": False}
        after = copy.deepcopy(before)
        after.update(captured_at_unix_ns=40, trace_exists=True,
                     profile_started_zero=True, profile_stopped_eight=True)
        receipt = {"request_started_at_unix_ns": 20, "request_finished_at_unix_ns": 30,
                   "request_sha256": "c" * 64, "response_sha256": "d" * 64}
        value = {"traceEvents": [dict(event("cpu_op"), pid=25), event("kernel"), event("cuda_runtime")]}
        return value, receipt, before, after

    def test_same_candidate_namespace_process_and_single_request_window(self):
        value, receipt, before, after = self.fixture()
        result = trace.verify_binding(value, receipt, before, after, 29)
        self.assertTrue(result["candidate_process_bound"])
        self.assertTrue(result["request_time_window_bound"])
        self.assertFalse(result["full_request_covered"])

    def test_restart_image_or_profiler_scope_mismatch_rejected(self):
        for key, value in (("container_id", "e" * 64), ("image", "other"),
                           ("host_init_pid", 999), ("restart_count", 1),
                           ("profile_stopped_eight", False)):
            with self.subTest(key=key):
                blob, receipt, before, after = self.fixture()
                after[key] = value
                with self.assertRaises(ValueError):trace.verify_binding(blob, receipt, before, after, 29)

    def test_trace_before_post_after_snapshot_or_already_existing_rejected(self):
        for mtime in (19, 31, 41):
            blob, receipt, before, after = self.fixture()
            with self.assertRaises(ValueError):trace.verify_binding(blob, receipt, before, after, mtime)
        blob, receipt, before, after = self.fixture()
        before["trace_exists"] = True
        with self.assertRaises(ValueError):trace.verify_binding(blob, receipt, before, after, 29)

    def test_unrelated_trace_process_or_missing_hash_rejected(self):
        blob, receipt, before, after = self.fixture()
        blob["traceEvents"][0]["pid"] = 999
        with self.assertRaises(ValueError):trace.verify_binding(blob, receipt, before, after, 29)
        blob, receipt, before, after = self.fixture()
        del receipt["response_sha256"]
        with self.assertRaises(ValueError):trace.verify_binding(blob, receipt, before, after, 29)


if __name__ == "__main__":
    unittest.main()
