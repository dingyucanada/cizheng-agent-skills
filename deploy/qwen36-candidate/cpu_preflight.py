"""Run only in the pinned NIM image without GPU devices or a network.

Inspect the installed backend and process two synthetic images on CPU. No
model tensors are loaded. This verifies arguments, not SM121 kernel execution.
"""
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import re
from pathlib import Path

PROFILE_SHA256 = "2e4f0d0b02e4769be5b92487cbba4a9bb4d2f346e18602de31e8fa108ece571e"
ENTRYPOINT_SHA256 = "bc8c7cca428dc1eb843752b518df7e8b5ecad747e315a764f9fb5512137f2e26"


def source_receipt(callable_):
    text = inspect.getsource(callable_)
    return text, {"path": inspect.getsourcefile(callable_),
                  "sha256": hashlib.sha256(text.encode()).hexdigest(), "source": text}


def main():
    result = {"cpu_preflight": "failed", "gpu_model_requested": False,
              "production_modified": False, "gpu_initialized": False}
    try:
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
        raw = Path("/candidate/launch_profile.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == PROFILE_SHA256
        profile = json.loads(raw)
        result["launch_profile_sha256"] = PROFILE_SHA256
        result["packages"] = {name: importlib.metadata.version(name)
                              for name in ("sglang", "transformers", "torch", "flashinfer-python")}
        assert result["packages"]["sglang"] == "0.5.16"
        assert result["packages"]["transformers"] == "5.12.1"
        assert result["packages"]["torch"] == "2.11.0+cu130"
        assert hashlib.sha256(Path("/opt/nim/start_server.sh").read_bytes()).hexdigest() == ENTRYPOINT_SHA256
        result["original_nim_entrypoint_sha256"] = ENTRYPOINT_SHA256

        import torch
        assert not torch.cuda.is_initialized()
        assert torch.version.cuda == "13.0"
        from sglang.srt.server_args import ServerArgs
        parser = argparse.ArgumentParser()
        ServerArgs.add_cli_args(parser)
        parsed = parser.parse_args(["--model-path", "/models/qwen36"] + profile["arguments"])
        # Do not construct ServerArgs: its post-init is a runtime hardware check.
        result["parsed_arguments"] = profile["arguments"]
        assert parsed.kv_cache_dtype == "fp8_e4m3"
        assert parsed.moe_runner_backend == "marlin"
        assert parsed.fp4_gemm_runner_backend == "marlin"
        assert parsed.mem_fraction_static == 0.58
        assert parsed.context_length == 24576
        assert parsed.max_total_tokens == 24576
        result["requested_context_length"] = parsed.context_length
        result["requested_max_total_tokens"] = parsed.max_total_tokens
        assert parsed.max_running_requests == 1
        assert parsed.max_mamba_cache_size == 1
        assert parsed.disable_radix_cache and parsed.disable_overlap_schedule

        from sglang.srt.models.qwen3_5 import EntryClass
        result["architectures"] = [entry.__name__ for entry in EntryClass]
        assert "Qwen3_5MoeForConditionalGeneration" in result["architectures"]
        from sglang.srt.configs.model_config import ModelConfig
        from sglang.srt.layers.quantization.modelopt_quant import ModelOptMixedPrecisionConfig
        quant_json = json.loads(Path("/models/qwen36/hf_quant_config.json").read_text())
        resolved = ModelConfig._parse_modelopt_quant_config(object(), quant_json)
        assert resolved["quant_method"] == "modelopt_mixed"
        quant = ModelOptMixedPrecisionConfig.from_config(quant_json)
        assert quant.kv_cache_quant_algo == "FP8"
        assert len(quant.quantized_layers) == 291
        result["mixed_quantization"] = {"normalized": resolved, "kv_cache_quant_algo": quant.kv_cache_quant_algo,
                                        "quantized_layers": len(quant.quantized_layers),
                                        "minimum_capability": quant.get_min_capability()}

        from sglang.srt.mem_cache.kv_cache_configurator import KVCacheConfigurator
        from sglang.srt.utils.common import get_available_gpu_memory
        pool_source, pool_receipt = source_receipt(KVCacheConfigurator._profile_available_bytes)
        available_source, available_receipt = source_receipt(get_available_gpu_memory)
        normalized = re.sub(r"\s+", "", pool_source)
        assert "pre_model_load_memory*(1-self.server_args.mem_fraction_static)" in normalized
        assert "rest_memory=available_gpu_memory-slack_gb" in normalized
        assert "props.is_integrated" in available_source
        assert "psutil.virtual_memory().available" in available_source
        result["memory_formula_verified"] = True
        result["memory_formula"] = pool_receipt
        result["integrated_memory_source"] = available_receipt

        from sglang.srt.multimodal.processors.base_processor import BaseMultimodalProcessor
        mm_source, mm_receipt = source_receipt(BaseMultimodalProcessor.process_mm_data)
        mm_normalized = re.sub(r"\s+", "", mm_source).replace("'", '"')
        assert 'kwargs.setdefault("images_kwargs",{}).update(self.image_config)' in mm_normalized
        result["multimodal_config_forwarding"] = mm_receipt
        from transformers import AutoProcessor
        from PIL import Image
        processor = AutoProcessor.from_pretrained("/models/qwen36", local_files_only=True, trust_remote_code=False)
        processed = processor.image_processor(
            images=[Image.new("RGB", (1024, 1024)), Image.new("RGB", (1024, 1024))],
            **parsed.mm_process_config["image"], return_tensors="pt", device="cpu")
        grids = processed["image_grid_thw"].tolist()
        merge_size = processor.image_processor.merge_size
        tokens = [int(t * h * w // merge_size**2) for t, h, w in grids]
        assert tokens == [256, 256]
        result["processor_class"] = type(processor).__name__
        result["image_processor_class"] = type(processor.image_processor).__name__
        result["image_grid_thw"] = grids
        result["image_tokens_per_probe"] = tokens
        result["processor_size"] = parsed.mm_process_config["image"]["size"]
        assert not torch.cuda.is_initialized()
        result["gpu_initialized"] = torch.cuda.is_initialized()
        result["cpu_preflight"] = "passed"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode()
    with Path("/audit/cpu-preflight.json").open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"cpu_preflight": result["cpu_preflight"], "receipt_sha256": hashlib.sha256(raw).hexdigest(),
                      "error": result.get("error")}, ensure_ascii=False))
    return 0 if result["cpu_preflight"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
