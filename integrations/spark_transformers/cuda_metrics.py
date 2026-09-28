"""CUDA observations for one serialized, single-device ``model.generate`` call.

Pass the already loaded torch module; importing this helper does not import torch.
Create a fresh measurement for each call, after CPU image/token preprocessing and
the input transfer, and keep the service's single-process generation lock held.
Resetting peaks affects every PyTorch allocation on the selected device in this
process, so overlapping requests or background GPU tasks invalidate attribution.

Timing is the CUDA event interval on the captured current stream, not the sum of
kernel durations. It can include gaps while the host dispatches generation work.
Side streams must join that stream before generation returns. Allocator-reported peaks
include resident model tensors and cached blocks, not just additional generation
memory. With the native backend these cover this process's PyTorch allocator.
With cudaMallocAsync, reported CUDA pool high-water marks can be conservative
sums rather than exact simultaneous peaks, and may include other same-process
libraries sharing those pools. Always record the actual allocator backend.
On GB10's unified memory they are not total GPU, CPU, or system memory usage.
"""

from __future__ import annotations

import math
from types import TracebackType
from typing import Any


class CudaMetricsError(RuntimeError):
    """The generation has no complete, valid CUDA measurement."""


class CudaGenerationMeasurement:
    """Publish metrics only after generation and CUDA synchronization succeed.

    Example::

        with CudaGenerationMeasurement(torch) as measured:
            output = model.generate(**cuda_inputs, **options)
        request_log["cuda"] = measured.metrics

    ``metrics`` remains ``None`` for unavailable CUDA, a failed generation, or any
    measurement failure. Native CUDA errors propagate; there is no CPU fallback
    or replacement value. The caller may log an explicit unmeasured state with
    the exception type, or fail the request. Do not log a successful GPU run when
    an error propagates. This context does not select a device or change streams;
    ``device_index`` must be the CUDA device used by the model and inputs.
    """

    def __init__(self, torch_module: Any, device_index: int | None = None):
        if device_index is not None and (type(device_index) is not int or device_index < 0):
            raise ValueError("device_index must be a nonnegative CUDA device index")
        self._cuda = torch_module.cuda
        self._device_index = device_index
        self._entered = False
        self.metrics: dict[str, Any] | None = None

    def __enter__(self) -> "CudaGenerationMeasurement":
        if self._entered:
            self.metrics = None
            raise CudaMetricsError("Create a fresh CUDA measurement for each generation")
        self._entered = True
        if not self._cuda.is_available():
            raise CudaMetricsError("CUDA unavailable; generation was not measured")
        if self._device_index is None:
            self._device_index = self._cuda.current_device()
        self._allocator_backend = self._cuda.get_allocator_backend()
        if not isinstance(self._allocator_backend, str) or not self._allocator_backend:
            raise CudaMetricsError("CUDA allocator backend is missing or invalid")

        # Finish earlier work before resetting this process's allocator peaks.
        self._cuda.synchronize(self._device_index)
        self._cuda.reset_peak_memory_stats(self._device_index)
        self._stream = self._cuda.current_stream(self._device_index)
        self._start = self._cuda.Event(enable_timing=True)
        self._end = self._cuda.Event(enable_timing=True)
        self._start.record(self._stream)
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exception_type is not None:
            # Preserve the original generation error, without partial metrics.
            return False

        self._end.record(self._stream)
        # Wait for asynchronous CUDA errors and memory activity before reading.
        self._cuda.synchronize(self._device_index)
        elapsed_ms = self._start.elapsed_time(self._end)
        allocated_bytes = self._cuda.max_memory_allocated(self._device_index)
        reserved_bytes = self._cuda.max_memory_reserved(self._device_index)
        if not isinstance(elapsed_ms, (int, float)) or isinstance(elapsed_ms, bool) or not (
            math.isfinite(elapsed_ms) and elapsed_ms > 0
        ):
            raise CudaMetricsError("CUDA generation elapsed time is missing or invalid")
        # A loaded GPU model has positive allocator usage. Some unsupported
        # allocator paths return empty stats as zero: never publish that as a
        # measured model footprint, or coerce missing values to zero.
        if any(type(value) is not int or value <= 0 for value in (allocated_bytes, reserved_bytes)):
            raise CudaMetricsError("CUDA allocator peak memory is missing or invalid")
        if reserved_bytes < allocated_bytes:
            raise CudaMetricsError("CUDA allocator reserved peak is below allocated peak")

        memory_scope = "this_process_allocator_reported_by_pytorch_including_model_and_cache"
        if self._allocator_backend == "native":
            memory_scope = "this_process_pytorch_allocator_including_model_and_cache"
        elif self._allocator_backend == "cudaMallocAsync":
            memory_scope = "this_process_cuda_pools_reported_by_pytorch_including_model_and_cache"
        self.metrics = {
            "status": "measured",
            "device_index": self._device_index,
            "elapsed_ms": float(elapsed_ms),
            "max_memory_allocated_bytes": allocated_bytes,
            "max_memory_reserved_bytes": reserved_bytes,
            "timing_scope": "generate_current_stream_cuda_event_interval",
            "memory_scope": memory_scope,
            "memory_peak_scope": "allocator_reported_high_water_marks",
            "allocator_backend": self._allocator_backend,
            "memory_is_total_system_usage": False,
        }
        return False
