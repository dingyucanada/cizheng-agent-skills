"""Software contract checks only; these tests are not real GPU measurements."""

from types import SimpleNamespace

import pytest

from integrations.spark_transformers.cuda_metrics import CudaGenerationMeasurement, CudaMetricsError


class RecordingCuda:
    """Detect unsafe ordering and inject errors without pretending to run CUDA."""

    def __init__(self, *, available=True, elapsed=12.5, allocated=4096, reserved=8192,
                 backend="native"):
        self.available = available
        self.elapsed = elapsed
        self.allocated = allocated
        self.reserved = reserved
        self.backend = backend
        self.calls = []
        self.events = []
        self.end_synchronized = False
        self.failure = None
        self.stream = object()

    def is_available(self):
        self.calls.append("available")
        return self.available

    def current_device(self):
        self.calls.append("current_device")
        return 2

    def get_allocator_backend(self):
        self.calls.append("allocator_backend")
        return self.backend

    def synchronize(self, device):
        self.calls.append(("synchronize", device))
        if self.events and self.events[1].recorded:
            if self.failure:
                raise self.failure
            self.end_synchronized = True

    def reset_peak_memory_stats(self, device):
        assert self.calls[-1] == ("synchronize", device)
        self.calls.append(("reset_peaks", device))

    def current_stream(self, device):
        self.calls.append(("current_stream", device))
        return self.stream

    def Event(self, *, enable_timing):
        assert enable_timing
        number = len(self.events)
        cuda = self

        class RecordingEvent:
            recorded = False

            def record(self, stream):
                assert stream is cuda.stream
                self.recorded = True
                cuda.calls.append(("record", number))

            def elapsed_time(self, end):
                assert self.recorded and end.recorded and cuda.end_synchronized
                cuda.calls.append("elapsed")
                return cuda.elapsed

        event = RecordingEvent()
        self.events.append(event)
        return event

    def max_memory_allocated(self, device):
        assert self.end_synchronized
        self.calls.append(("allocated", device))
        return self.allocated

    def max_memory_reserved(self, device):
        assert self.end_synchronized
        self.calls.append(("reserved", device))
        return self.reserved


def measurement(cuda, device_index=None):
    return CudaGenerationMeasurement(SimpleNamespace(cuda=cuda), device_index)


def test_orders_generation_between_events_and_reads_only_after_synchronization():
    cuda = RecordingCuda()
    measured = measurement(cuda)
    assert measured.metrics is None
    with measured:
        assert measured.metrics is None
        cuda.calls.append("generate")
    assert cuda.calls == [
        "available", "current_device", "allocator_backend", ("synchronize", 2), ("reset_peaks", 2),
        ("current_stream", 2), ("record", 0), "generate", ("record", 1),
        ("synchronize", 2), "elapsed", ("allocated", 2), ("reserved", 2),
    ]
    assert measured.metrics["elapsed_ms"] == 12.5
    assert measured.metrics["max_memory_allocated_bytes"] == 4096
    assert measured.metrics["max_memory_reserved_bytes"] == 8192
    assert measured.metrics["allocator_backend"] == "native"
    assert measured.metrics["memory_scope"].startswith("this_process_pytorch_allocator")
    assert measured.metrics["memory_is_total_system_usage"] is False


def test_async_pool_metrics_do_not_claim_native_pytorch_only_memory_scope():
    cuda = RecordingCuda(backend="cudaMallocAsync")
    with measurement(cuda) as measured:
        pass
    assert measured.metrics["allocator_backend"] == "cudaMallocAsync"
    assert measured.metrics["memory_scope"].startswith("this_process_cuda_pools_reported_by_pytorch")
    assert measured.metrics["memory_peak_scope"] == "allocator_reported_high_water_marks"
    assert measured.metrics["memory_is_total_system_usage"] is False


def test_explicit_device_is_used_for_stream_synchronization_and_allocator():
    cuda = RecordingCuda()
    with measurement(cuda, 0) as measured:
        pass
    assert "current_device" not in cuda.calls
    assert measured.metrics["device_index"] == 0
    assert [call for call in cuda.calls if isinstance(call, tuple) and call[0] != "record"] == [
        ("synchronize", 0), ("reset_peaks", 0), ("current_stream", 0),
        ("synchronize", 0), ("allocated", 0), ("reserved", 0),
    ]


def test_cuda_unavailable_never_runs_body_or_publishes_metrics():
    cuda = RecordingCuda(available=False)
    measured = measurement(cuda)
    with pytest.raises(CudaMetricsError, match="unavailable"):
        with measured:
            pytest.fail("generation must not run without CUDA")
    assert measured.metrics is None
    assert cuda.calls == ["available"]


def test_generation_error_is_preserved_without_partial_measurement():
    cuda = RecordingCuda()
    measured = measurement(cuda)
    error = RuntimeError("generation failed")
    with pytest.raises(RuntimeError) as caught:
        with measured:
            raise error
    assert caught.value is error
    assert measured.metrics is None
    assert ("record", 1) not in cuda.calls
    assert "elapsed" not in cuda.calls


def test_asynchronous_cuda_failure_never_publishes_success_or_memory():
    cuda = RecordingCuda()
    cuda.failure = RuntimeError("asynchronous kernel failed")
    measured = measurement(cuda)
    with pytest.raises(RuntimeError) as caught:
        with measured:
            pass
    assert caught.value is cuda.failure
    assert measured.metrics is None
    assert "elapsed" not in cuda.calls
    assert ("allocated", 2) not in cuda.calls


@pytest.mark.parametrize("field,value", [
    ("elapsed", None), ("elapsed", float("nan")), ("elapsed", float("inf")), ("elapsed", 0),
    ("allocated", None), ("allocated", 0), ("reserved", None), ("reserved", 0),
    ("reserved", 1024),
])
def test_missing_or_invalid_measurement_is_an_error_not_a_zero_metric(field, value):
    cuda = RecordingCuda()
    setattr(cuda, field, value)
    measured = measurement(cuda)
    with pytest.raises(CudaMetricsError, match="missing or invalid|below allocated"):
        with measured:
            pass
    assert measured.metrics is None


def test_missing_allocator_api_never_publishes_partial_metrics(monkeypatch):
    cuda = RecordingCuda()
    monkeypatch.delattr(RecordingCuda, "max_memory_reserved")
    measured = measurement(cuda)
    with pytest.raises(AttributeError):
        with measured:
            pass
    assert measured.metrics is None


def test_measurement_cannot_be_reused_as_stale_evidence():
    cuda = RecordingCuda()
    measured = measurement(cuda)
    with measured:
        pass
    assert measured.metrics is not None
    with pytest.raises(CudaMetricsError, match="fresh"):
        with measured:
            pytest.fail("reused measurement must not run generation")
    assert measured.metrics is None
