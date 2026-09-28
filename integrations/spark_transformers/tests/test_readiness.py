import base64
import asyncio
import hashlib
import io
import json
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from integrations.spark_transformers import adapter


def test_cancelled_http_call_keeps_real_worker_generation_serial(monkeypatch):
    """Cancellation must not overlap RNG or allocator peaks with the next call.

    Uses real Python worker threads and cancellation, with no model or GPU.
    """
    entered_first, release_first, entered_second = (threading.Event() for _ in range(3))
    order = []

    def blocking_generation(request):
        name = request.messages[0]["content"]
        order.append(name)
        if name == "first":
            entered_first.set()
            assert release_first.wait(5), "Test did not release first worker"
        else:
            entered_second.set()
        return {"name": name}

    runtime = adapter.Runtime()
    runtime.ready = True
    monkeypatch.setattr(adapter, "runtime", runtime)
    monkeypatch.setattr(adapter, "_infer", blocking_generation)
    monkeypatch.setattr(adapter, "generation_lock", threading.Lock())

    async def exercise():
        monkeypatch.setattr(adapter, "lock", asyncio.Lock())
        def request(name):
            return adapter.Completion(model=runtime.name, messages=[{"role": "user", "content": name}])
        first = asyncio.create_task(adapter.complete(request("first")))
        second = None
        try:
            assert await asyncio.to_thread(entered_first.wait, 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not adapter.lock.locked()  # The async guard has already released.
            second = asyncio.create_task(adapter.complete(request("second")))
            assert not await asyncio.to_thread(entered_second.wait, 0.1)
            release_first.set()
            assert await asyncio.wait_for(second, 2) == {"name": "second"}
            assert order == ["first", "second"]
        finally:
            release_first.set()
            if not first.done():
                first.cancel()
            if second and not second.done():
                second.cancel()

    asyncio.run(exercise())


def test_failed_gpu_start_never_reports_healthy(monkeypatch):
    runtime = adapter.Runtime()

    def unavailable():
        raise RuntimeError("CUDA unavailable")

    monkeypatch.setattr(runtime, "load", unavailable)
    monkeypatch.setattr(adapter, "runtime", runtime)
    with TestClient(adapter.app) as client:
        health = client.get("/health")
        assert health.status_code == 503
        assert health.json()["status"] == "not_ready"
        assert client.get("/v1/models").status_code == 503
        assert client.post("/v1/chat/completions", json={
            "model": adapter.MODEL_DEFAULT, "messages": []}).status_code == 503


def test_loaded_model_with_failed_vision_generation_is_not_ready(monkeypatch, tmp_path):
    """Reproduce a successful model load followed by a native JIT failure.

    These are software doubles: this test does not assert a GPU was available.
    """
    class Matrix:
        def __matmul__(self, other):
            return self

        def __getitem__(self, index):
            return self

        def cpu(self):
            return 64.0

    class Inputs(dict):
        def to(self, device):
            return self

    inputs = Inputs(input_ids=SimpleNamespace(shape=(1, 3)), token_type_ids="unused")
    processor = SimpleNamespace(apply_chat_template=lambda *args, **kwargs: inputs)
    calls = []

    class Model:
        def to(self, device):
            return self

        def parameters(self):
            return iter([SimpleNamespace(device=SimpleNamespace(type="cuda"))])

        def eval(self):
            pass

        def generate(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("native vision kernel compilation failed")

    fake_torch = SimpleNamespace(
        __version__="test-double", version=SimpleNamespace(cuda="test-double"),
        float32="float32", bfloat16="bfloat16", ones=lambda *args, **kwargs: Matrix(),
        inference_mode=nullcontext, cuda=SimpleNamespace(
            is_available=lambda: True, get_device_name=lambda: "test-double",
            get_device_capability=lambda: (0, 0), get_arch_list=lambda: [],
            synchronize=lambda: None))
    fake_transformers = SimpleNamespace(
        Qwen3VLForConditionalGeneration=SimpleNamespace(from_pretrained=lambda *a, **k: Model()),
        AutoProcessor=SimpleNamespace(from_pretrained=lambda *a, **k: processor))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setenv("CIZHENG_SPARK_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(adapter, "validate_manifest", lambda *args: {"files_manifest_sha256": "a" * 64})
    runtime = adapter.Runtime()
    monkeypatch.setattr(adapter, "runtime", runtime)
    with TestClient(adapter.app) as client:
        assert client.get("/health").status_code == 503
        assert runtime.model is not None  # Loaded weights alone do not establish readiness.
        assert calls and calls[0]["max_new_tokens"] == 8
        assert "token_type_ids" not in calls[0]
        assert not runtime.ready
        assert client.get("/v1/models").status_code == 503
        assert client.post("/v1/chat/completions", json={
            "model": runtime.name, "messages": []}).status_code == 503
        assert "synthetic_image_generation_passed" not in runtime.gpu_evidence


def test_remote_image_url_is_rejected_without_fetching():
    with pytest.raises(ValueError, match="Only local"):
        adapter.convert([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/private.jpg"}}]}])


def frame(color):
    image = Image.new("RGB", (8, 8), color)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}}


def test_local_image_preparation_preserves_order_and_budget():
    messages, images = adapter.convert([{"role": "user", "content": [frame("red"), frame("blue")]}])
    assert len(images) == 2
    assert messages[0]["content"][0]["image"].getpixel((0, 0)) == (255, 0, 0)
    assert messages[0]["content"][1]["image"].getpixel((0, 0)) == (0, 0, 255)
    with pytest.raises(ValueError, match="At most four"):
        adapter.convert([{"role": "user", "content": [frame("red")] * 5}])


def test_changed_model_bytes_fail_identity_check(tmp_path):
    weight = tmp_path / "model.safetensors"
    weight.write_bytes(b"abcd")
    identities = {weight.name: {"sha256": hashlib.sha256(b"abcd").hexdigest(), "bytes": 4}}
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"model": adapter.MODEL_DEFAULT,
                                   "downloaded_file_identity": identities,
                                   "files_manifest_sha256": hashlib.sha256(canonical).hexdigest()}))
    adapter.validate_manifest(tmp_path, manifest, adapter.MODEL_DEFAULT)
    weight.write_bytes(b"wxyz")
    with pytest.raises(ValueError, match="SHA-256 changed"):
        adapter.validate_manifest(tmp_path, manifest, adapter.MODEL_DEFAULT)
