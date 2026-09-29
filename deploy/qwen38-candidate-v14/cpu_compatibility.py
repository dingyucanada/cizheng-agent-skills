"""Inspect fixed 27B config/processor inside the existing NIM without a GPU.

No model weights are opened and no architecture is instantiated. CPU success
does not certify GPU tensor loading, SM121 kernels or ceramic correctness.
"""
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import warnings
from pathlib import Path

CONFIG_SHA256 = "71fa01bb64de20971045cd82a82c0ebb25a54e1b0a3f09ef23cf5479e9c54df8"
QUANT_SHA256 = "5f4aaa9e462ddb26a9790ab459eee69d100b9ade7541f0c86038e925c013f80b"


def source_record(callable_):
    raw = inspect.getsource(callable_)
    return {"file": inspect.getsourcefile(callable_), "sha256": hashlib.sha256(raw.encode()).hexdigest(), "source": raw}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("fresh CPU compatibility receipt required")
    result = {"cpu_compatibility": "failed", "gpu_requested": False, "model_weights_loaded": False,
              "model": "nvidia/Qwen3.8-27B-NVFP4", "revision": "482ca0f3832238542f8f5295dde86b5f22711d80"}
    try:
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
        result["packages"] = {name: importlib.metadata.version(name)
                              for name in ("sglang", "transformers", "torch", "flashinfer-python")}
        assert result["packages"]["sglang"] == "0.5.16"
        assert result["packages"]["transformers"] == "5.12.1"
        assert result["packages"]["torch"] == "2.11.0+cu130"
        config_raw = (args.model_directory / "config.json").read_bytes()
        quant_raw = (args.model_directory / "hf_quant_config.json").read_bytes()
        assert hashlib.sha256(config_raw).hexdigest() == CONFIG_SHA256
        assert hashlib.sha256(quant_raw).hexdigest() == QUANT_SHA256
        config = json.loads(config_raw)
        quant_json = json.loads(quant_raw)
        result["export_transformers_version"] = config["transformers_version"]
        assert config["architectures"] == ["Qwen3_5ForConditionalGeneration"]
        assert config["model_type"] == "qwen3_5" and config["language_model_only"] is False

        import torch
        assert not torch.cuda.is_initialized()
        from transformers import AutoConfig, AutoProcessor
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            hf_config = AutoConfig.from_pretrained(str(args.model_directory), local_files_only=True, trust_remote_code=False)
            result["autoconfig_class"] = type(hf_config).__name__
            result["hf_text_class"] = type(hf_config.text_config).__name__
            critical = ("output_gate_type", "attn_output_gate", "partial_rotary_factor", "rope_parameters", "mamba_ssm_dtype")
            parsed = hf_config.text_config.to_dict()
            result["critical_text_config"] = {key: parsed.get(key) for key in critical}
            result["critical_config_differences"] = [key for key in critical if parsed.get(key) != config["text_config"].get(key)]
            assert not result["critical_config_differences"]
            from sglang.srt.configs.qwen3_5 import Qwen3_5Config
            sglang_config = Qwen3_5Config.from_pretrained(str(args.model_directory), local_files_only=True)
            result["sglang_config_class"] = type(sglang_config).__name__
            result["sglang_output_gate_type"] = sglang_config.text_config.output_gate_type
            assert result["sglang_output_gate_type"] == config["text_config"]["output_gate_type"]

            from sglang.srt.models import qwen3_5
            result["registered_architectures"] = [entry.__name__ for entry in qwen3_5.EntryClass]
            assert "Qwen3_5ForConditionalGeneration" in result["registered_architectures"]
            result["dense_entry_source"] = source_record(qwen3_5.Qwen3_5ForConditionalGeneration)
            result["gdn_source"] = source_record(qwen3_5.Qwen3_5GatedDeltaNet)
            result["gated_norm_source"] = source_record(qwen3_5.RMSNormGated)
            assert "output_gate_type" in result["gdn_source"]["source"]
            assert "swish" in result["gated_norm_source"]["source"]
            from sglang.srt.configs.model_config import ModelConfig
            from sglang.srt.layers.quantization.modelopt_quant import ModelOptMixedPrecisionConfig
            normalized = ModelConfig._parse_modelopt_quant_config(None, quant_json)
            quant = ModelOptMixedPrecisionConfig.from_config(quant_json)
            assert normalized["quant_method"] == "modelopt_mixed"
            assert len(quant.quantized_layers) == 401
            result["mixed_quantization"] = {"normalized": normalized,
                                            "quantized_layers": len(quant.quantized_layers),
                                            "kv_cache_quant_algo": quant.kv_cache_quant_algo,
                                            "minimum_capability": quant.get_min_capability()}

            processor = AutoProcessor.from_pretrained(str(args.model_directory), local_files_only=True, trust_remote_code=False)
            from PIL import Image
            processed = processor.image_processor(images=[Image.new("RGB", (1024, 1024)), Image.new("RGB", (1024, 1024))],
                                                  size={"shortest_edge": 4096, "longest_edge": 262144},
                                                  return_tensors="pt", device="cpu")
            grids = processed["image_grid_thw"].tolist()
            merge = processor.image_processor.merge_size
            tokens = [int(t * h * w // merge**2) for t, h, w in grids]
            assert tokens == [256, 256]
            result["processor"] = {"class": type(processor).__name__, "image_class": type(processor.image_processor).__name__,
                                    "image_grid_thw": grids, "image_tokens_per_probe": tokens}
            result["python_warnings"] = [{"category": type(item.message).__name__, "message": str(item.message)} for item in captured]
        assert not torch.cuda.is_initialized()
        result["gpu_initialized"] = torch.cuda.is_initialized()
        result["cpu_compatibility"] = "passed"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    with args.output.open("x") as target:
        target.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"cpu_compatibility": result["cpu_compatibility"], "error_type": result.get("error_type"),
                      "error": result.get("error")}, ensure_ascii=False))
    return 0 if result["cpu_compatibility"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
