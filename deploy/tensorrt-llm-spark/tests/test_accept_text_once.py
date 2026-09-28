import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

spec = importlib.util.spec_from_file_location("trt_accept", Path(__file__).parents[1] / "accept_text_once.py")
accept = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accept)


def envelope():
    return {"model": accept.MODEL, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "馆方记载：79.2.467为康熙时期景德镇瓷。未知器物不能据此定年；待补底款照片及来源资料。"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}}


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, body=None, error=None, inventory=None):
        self.body, self.error, self.calls = body, error, []
        self.inventory = inventory if inventory is not None else {"data": [{"id": accept.MODEL}]}

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        url = request if isinstance(request, str) else request.full_url
        if url.endswith("/health"):
            return Response(b"ok")
        if url.endswith("/v1/models"):
            return Response(json.dumps(self.inventory).encode())
        if self.error:
            raise self.error
        return Response(self.body if self.body is not None else json.dumps(envelope()).encode())


class TextAcceptanceTests(unittest.TestCase):
    def test_exact_loopback_text_payload_one_post_no_external_data(self):
        opener = Opener()
        with tempfile.TemporaryDirectory() as temporary:
            result = accept.run_once(temporary, opener)
        self.assertTrue(result["accepted_interface"])
        self.assertEqual(result["usage"], envelope()["usage"])
        self.assertFalse(result["ceramic_workflow_validated"])
        self.assertFalse(result["semantic_quality_guaranteed"])
        self.assertEqual(len(opener.calls), 3)
        request, timeout = opener.calls[-1]
        self.assertEqual(request.full_url, "http://127.0.0.1:8006/v1/chat/completions")
        self.assertEqual(request.method, "POST")
        self.assertEqual(timeout, 80)
        self.assertEqual(json.loads(request.data), accept.payload())
        self.assertEqual(result["request_sha256"], hashlib.sha256(request.data).hexdigest())
        self.assertLessEqual(result["request_started_at_unix_ns"], result["request_finished_at_unix_ns"])
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(set(json.loads(request.data)), {"model", "messages", "temperature", "max_tokens", "stream"})
        self.assertTrue(all(isinstance(message["content"], str) for message in json.loads(request.data)["messages"]))

    def test_public_ceramic_question_distinguishes_catalog_and_unknown_object(self):
        request = accept.payload()
        user_text = request["messages"][1]["content"]
        self.assertIn("https://www.metmuseum.org/art/collection/search/48559", user_text)
        self.assertIn("79.2.467", user_text)
        self.assertIn("演示用未知器物，不是上述馆藏器", user_text)
        self.assertIn("证据边界", user_text)
        self.assertIn("两项待补证", user_text)
        self.assertIn("没有图片", user_text)
        self.assertNotIn("image_url", json.dumps(request))
        self.assertNotIn("data:image", json.dumps(request))
        self.assertEqual(request["max_tokens"], 256)

    def test_length_even_complete_text_rejected_with_original_usage(self):
        value = envelope()
        value["choices"][0]["finish_reason"] = "length"
        opener = Opener(json.dumps(value).encode())
        with tempfile.TemporaryDirectory() as temporary:
            result = accept.run_once(temporary, opener)
            self.assertEqual(json.loads((Path(temporary) / "response.raw.json").read_bytes()), value)
        self.assertFalse(result["accepted_interface"])
        self.assertEqual(result["diagnostic_category"], "response_truncated")
        self.assertEqual(result["usage"], value["usage"])
        self.assertEqual(result["inference_requests_sent"], 1)
        self.assertEqual(len(opener.calls), 3)

    def test_missing_or_other_termination_fails_closed(self):
        for finish in (None, "tool_calls", "error"):
            with self.subTest(finish=finish):
                value = envelope()
                value["choices"][0]["finish_reason"] = finish
                category, usage, text = accept.validate_response(value)
                self.assertEqual(category, "unverified_termination")
                self.assertEqual(usage, value["usage"])
                self.assertIsNone(text)

    def test_eof_json_preserved_failure_no_retry(self):
        opener = Opener(b'{"choices":')
        with tempfile.TemporaryDirectory() as temporary:
            result = accept.run_once(temporary, opener)
            self.assertEqual((Path(temporary) / "response.raw.json").read_bytes(), b'{"choices":')
        self.assertEqual(result["diagnostic_category"], "invalid_json_envelope")
        self.assertFalse(result["accepted_interface"])
        self.assertIsNone(result["usage"])
        self.assertEqual(len(opener.calls), 3)

    def test_http_and_network_failures_are_safe_and_never_retried(self):
        for error, expected in ((urllib.error.HTTPError("http://private.example", 503, "unsafe provider details", {}, None), "http_error"),
                                (urllib.error.URLError("unsafe environment details"), "transport_failure"),
                                (TimeoutError("unsafe timeout details"), "transport_failure")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                opener = Opener(error=error)
                result = accept.run_once(temporary, opener)
                receipt = (Path(temporary) / "receipt.json").read_text()
                self.assertNotIn("unsafe", receipt)
                self.assertNotIn("private.example", receipt)
                self.assertEqual(result["diagnostic_category"], expected)
                self.assertEqual(len(opener.calls), 3)
                self.assertFalse(result["accepted_interface"])
                self.assertIsNone(result["usage"])

    def test_unknown_inventory_does_not_generate(self):
        for inventory in ([], {"data": [{"id": "other-model"}]}, {"data": None}):
            with self.subTest(inventory=inventory), tempfile.TemporaryDirectory() as temporary:
                opener = Opener(inventory=inventory)
                result = accept.run_once(temporary, opener)
                self.assertEqual(result["inference_requests_sent"], 0)
                self.assertEqual(len(opener.calls), 2)
                self.assertEqual(result["diagnostic_category"], "model_inventory_mismatch")

    def test_failed_claim_also_cannot_be_implicitly_repeated(self):
        with tempfile.TemporaryDirectory() as temporary:
            opener = Opener(error=TimeoutError())
            accept.run_once(temporary, opener)
            other = Opener()
            with self.assertRaises(FileExistsError):
                accept.run_once(temporary, other)
            self.assertEqual(other.calls, [])

    def test_invalid_usage_and_identity_refused(self):
        for mutation, expected in ((("model", "other"), "model_identity_mismatch"),
                                   (("usage", {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2}), "invalid_usage"),
                                   (("usage", {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 10}), "invalid_usage")):
            value = copy.deepcopy(envelope())
            value[mutation[0]] = mutation[1]
            self.assertEqual(accept.validate_response(value)[0], expected)


if __name__ == "__main__":
    unittest.main()
