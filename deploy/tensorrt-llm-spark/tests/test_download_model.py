"""Offline tests for checkpoint identity and atomic download boundaries."""
import copy
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("trt_download", Path(__file__).parents[1] / "download_model.py")
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


def metadata():
    return {"model": download.MODEL, "files": [
        {"Type": "blob", "Path": name, "Size": 3,
         "Sha256": hashlib.sha256(b"abc").hexdigest(), "Revision": "a" * 40}
        for name in ("config.json", "tokenizer.json", "model.safetensors.index.json", "model.safetensors")]}


class FakeOpener:
    def __init__(self, body):
        self.body, self.requests = body, []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return io.BytesIO(self.body)


class CheckpointDownloadTests(unittest.TestCase):
    def test_complete_metadata_has_exact_content_identity(self):
        result = download.validate_files(metadata())
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]["source_file_revision"], "a" * 40)
        self.assertEqual(sum(item["bytes"] for item in result), 12)

    def test_unsafe_paths_refused(self):
        for name in ("../config.json", "/config.json", "a/../config.json", "a//config.json",
                     "a/./config.json", "a\\config.json", "a\x00config.json"):
            with self.subTest(name=name):
                value = metadata()
                value["files"][0]["Path"] = name
                with self.assertRaises(ValueError):
                    download.validate_files(value)

    def test_duplicate_and_incomplete_metadata_refused(self):
        duplicate = metadata()
        duplicate["files"].append(copy.deepcopy(duplicate["files"][0]))
        with self.assertRaises(ValueError):
            download.validate_files(duplicate)
        incomplete = metadata()
        incomplete["files"].pop()
        with self.assertRaises(ValueError):
            download.validate_files(incomplete)

    def test_bad_identity_fields_refused(self):
        for key, value in (("Size", True), ("Size", -1), ("Sha256", "x" * 64),
                           ("Revision", "master"), ("Type", "tree")):
            with self.subTest(key=key, value=value):
                document = metadata()
                document["files"][0][key] = value
                with self.assertRaises(ValueError):
                    download.validate_files(document)

    def test_atomic_verified_download_uses_only_official_public_url(self):
        item = download.validate_files(metadata())[0]
        opener = FakeOpener(b"abc")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            self.assertEqual(download.download_file(item, directory, opener), "downloaded_verified")
            self.assertEqual((directory / "config.json").read_bytes(), b"abc")
            self.assertFalse((directory / "config.json.part").exists())
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "https://modelscope.cn/api/v1/models/Qwen/Qwen3-4B-Instruct-2507/repo?Revision=master&FilePath=config.json")
        self.assertEqual(timeout, 60)
        self.assertFalse(request.has_header("Authorization"))

    def test_mismatch_does_not_publish_or_blindly_resume(self):
        item = download.validate_files(metadata())[0]
        for body in (b"abd", b"ab", b"abcd"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary).resolve()
                with self.assertRaises(ValueError):
                    download.download_file(item, directory, FakeOpener(body))
                self.assertFalse((directory / "config.json").exists())
                self.assertTrue((directory / "config.json.part").exists())
                unopened = FakeOpener(b"abc")
                with self.assertRaises(ValueError):
                    download.download_file(item, directory, unopened)
                self.assertEqual(unopened.requests, [])

    def test_verified_file_skips_network_mismatch_never_overwrites(self):
        item = download.validate_files(metadata())[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            target = directory / "config.json"
            target.write_bytes(b"abc")
            opener = FakeOpener(b"unused")
            self.assertEqual(download.download_file(item, directory, opener), "already_verified")
            target.write_bytes(b"abd")
            with self.assertRaises(ValueError):
                download.download_file(item, directory, opener)
            self.assertEqual(target.read_bytes(), b"abd")
            self.assertEqual(opener.requests, [])

    def test_symlink_destination_refused(self):
        item = download.validate_files(metadata())[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            elsewhere = directory / "elsewhere"
            elsewhere.write_bytes(b"abc")
            (directory / "config.json").symlink_to(elsewhere)
            opener = FakeOpener(b"abc")
            with self.assertRaises(ValueError):
                download.download_file(item, directory, opener)
            self.assertEqual(opener.requests, [])


if __name__ == "__main__":
    unittest.main()
