"""Serve real local Qwen vision inference using native PyTorch CUDA.

This optional deployment transport has no CPU, cloud, fixture or JSON fallback.
Health requires weight identity, GPU math, model loading and image generation.
"""
import asyncio
import base64
import hashlib
import io
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .cuda_metrics import CudaGenerationMeasurement
from .structured_generation import (StructuredDependencyError, StructuredFormatError,
                                    StructuredGenerationError, build_structured_generation,
                                    output_matches_schema, validate_response_format)

MODEL_DEFAULT = "Qwen/Qwen3-VL-2B-Instruct"
MAX_IMAGES = 4
MAX_CONTEXT = 32768
Image.MAX_IMAGE_PIXELS = 24_000_000


def validate_manifest(directory: Path, path: Path, expected_model: str) -> dict:
    manifest = json.loads(path.read_text())
    if manifest["model"] != expected_model:
        raise ValueError("Model identity differs from manifest")
    identities = manifest["downloaded_file_identity"]
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != manifest["files_manifest_sha256"]:
        raise ValueError("Model manifest identity mismatch")
    if not identities or not any(name.endswith(".safetensors") for name in identities):
        raise ValueError("Manifest does not identify model weights")
    root = directory.resolve(strict=True)
    for name, identity in identities.items():
        file = (root / name).resolve(strict=True)
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError("Manifest path leaves model directory")
        if file.stat().st_size != identity["bytes"]:
            raise ValueError("Downloaded model file size changed")
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for data in iter(lambda: stream.read(16 * 1024 * 1024), b""):
                digest.update(data)
        if digest.hexdigest() != identity["sha256"]:
            raise ValueError("Downloaded model file SHA-256 changed")
    return manifest


class Runtime:
    def __init__(self):
        self.name = os.getenv("CIZHENG_SPARK_MODEL_NAME", MODEL_DEFAULT)
        self.ready = False
        self.failure_type = None
        self.gpu_evidence = None
        self.manifest = None
        self.model = None
        self.processor = None
        self.torch = None

    def load(self):
        self.ready = False
        self.failure_type = None
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU unavailable; CPU inference is disabled")
        configured = os.getenv("CIZHENG_SPARK_MODEL_DIR")
        if not configured:
            raise ValueError("CIZHENG_SPARK_MODEL_DIR is required")
        directory = Path(configured)
        manifest_path = Path(os.getenv("CIZHENG_SPARK_MODEL_MANIFEST",
                                      str(directory / "_file_manifest.json")))
        manifest = validate_manifest(directory, manifest_path, self.name)
        gpu = {"torch": torch.__version__, "cuda_runtime": torch.version.cuda,
               "device": torch.cuda.get_device_name(),
               "capability": list(torch.cuda.get_device_capability()),
               "arch_list": torch.cuda.get_arch_list()}
        for dtype, label in ((torch.float32, "float32"), (torch.bfloat16, "bfloat16")):
            data = torch.ones((64, 64), device="cuda", dtype=dtype)
            result = data @ data
            torch.cuda.synchronize()
            if float(result[0, 0].cpu()) != 64.0:
                raise RuntimeError("Real GPU matrix multiplication failed")
            gpu[label + "_matrix_multiply_passed"] = True
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            directory, dtype=torch.bfloat16, attn_implementation="sdpa",
            local_files_only=True, trust_remote_code=False).to("cuda")
        if next(model.parameters()).device.type != "cuda":
            raise RuntimeError("Model parameters are not on GPU")
        processor = AutoProcessor.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False)
        model.eval()
        self.torch, self.model, self.processor = torch, model, processor
        self.manifest, self.gpu_evidence = manifest, gpu
        self.warmup()
        self.ready = True

    def warmup(self):
        """Exercise vision and token generation before accepting real requests.

        A synthetic image tests deployment readiness only. It is not a ceramic
        assessment or a model quality evaluation, and no answer is substituted.
        """
        started = time.perf_counter()
        messages = [{"role": "user", "content": [
            {"type": "image", "image": Image.new("RGB", (128, 128), "white"),
             "max_pixels": 128 * 128, "min_pixels": 128 * 128},
            {"type": "text", "text": "Describe the dominant color in one word."}]}]
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt")
        inputs.pop("token_type_ids", None)
        inputs = inputs.to("cuda")
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=8, do_sample=False)
        self.torch.cuda.synchronize()
        if output.device.type != "cuda" or int(output.shape[-1]) <= prompt_tokens:
            raise RuntimeError("Real GPU vision generation warmup failed")
        self.gpu_evidence.update({
            "synthetic_image_generation_passed": True,
            "warmup_completion_tokens": int(output.shape[-1]) - prompt_tokens,
            "warmup_seconds": time.perf_counter() - started,
            "warmup_is_domain_evaluation": False})

    def identity(self):
        return {"model": self.name,
                "weights_revision": ("files-sha256:" + self.manifest["files_manifest_sha256"]
                                     if self.manifest else "unverified"),
                "gpu": self.gpu_evidence}


runtime = Runtime()
lock = asyncio.Lock()
# Cancelling an HTTP coroutine does not stop an already running to_thread call.
# Keep the model, RNG and process-wide allocator measurements serialized inside
# the worker as well, until that real generation actually finishes.
generation_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    try:
        await asyncio.to_thread(runtime.load)
    except Exception as error:
        # Never publish credential-bearing exception strings or claim readiness.
        runtime.failure_type = type(error).__name__
        runtime.ready = False
    yield


app = FastAPI(title="Cizheng local Spark vision transport", lifespan=lifespan)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128)
    messages: list[dict[str, Any]] = Field(max_length=64)
    max_tokens: int = Field(default=2500, ge=1, le=2500)
    temperature: float = Field(default=0.1, ge=0, le=1)
    stream: bool = False
    chat_template_kwargs: dict[str, Any] = Field(default_factory=dict)
    response_format: dict[str, Any] | None = None

    @field_validator("response_format", mode="before")
    @classmethod
    def bounded_structured_format(cls, value):
        return None if value is None else validate_response_format(value)


def convert(messages):
    converted, images = [], []
    for message in messages:
        role = message.get("role")
        if role not in ("system", "user", "assistant"):
            raise ValueError("Unsupported message role")
        original = message.get("content", "")
        if isinstance(original, str):
            converted.append({"role": role, "content": original})
            continue
        if not isinstance(original, list):
            raise ValueError("Unsupported message content")
        content = []
        for item in original:
            if not isinstance(item, dict):
                raise ValueError("Unsupported multimodal content")
            if item.get("type") == "text":
                content.append({"type": "text", "text": str(item.get("text", ""))})
            elif item.get("type") == "image_url":
                image_url = item.get("image_url")
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                if not isinstance(url, str) or not url.startswith((
                        "data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
                    raise ValueError("Only local PNG, JPEG or WebP data URLs are accepted")
                payload = url.split(",", 1)[1]
                if len(payload) > 24_000_000:
                    raise ValueError("Image payload is too large")
                if len(images) >= MAX_IMAGES:
                    raise ValueError("At most four images per request")
                try:
                    data = base64.b64decode(payload, validate=True)
                    image = Image.open(io.BytesIO(data))
                    image.load()
                    image = image.convert("RGB")
                except Exception as error:
                    raise ValueError("Invalid image data") from error
                images.append({"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
                content.append({"type": "image", "image": image,
                                "max_pixels": 512 * 512, "min_pixels": 128 * 128})
            else:
                raise ValueError("Unsupported multimodal item")
        converted.append({"role": role, "content": content})
    return converted, images


def record(event):
    configured = os.getenv("CIZHENG_SPARK_LOG_DIR")
    if not configured:
        return
    directory = Path(configured)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "vision-requests.jsonl").open("a") as output:
        output.write(json.dumps(event) + "\n")


def infer(request):
    with generation_lock:
        return _infer(request)


def _infer(request):
    started = time.perf_counter()
    # Schema validation and tokenizer preprocessing happen before CUDA input
    # allocation and the existing measured model.generate interval.
    prefix, structured = build_structured_generation(
        runtime.processor.tokenizer if request.response_format is not None else None,
        request.response_format)
    messages, images = convert(request.messages)
    inputs = runtime.processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True,
        return_dict=True, return_tensors="pt")
    inputs.pop("token_type_ids", None)
    inputs = inputs.to("cuda")
    prompt_tokens = int(inputs["input_ids"].shape[-1])
    if prompt_tokens + request.max_tokens > MAX_CONTEXT:
        raise ValueError("Request exceeds the initial 32K context budget")
    options = {"max_new_tokens": request.max_tokens, "do_sample": request.temperature > 0}
    if request.temperature > 0:
        options["temperature"] = request.temperature
    if prefix is not None:
        options["prefix_allowed_tokens_fn"] = prefix
    runtime.torch.manual_seed(0)
    with runtime.torch.inference_mode(), CudaGenerationMeasurement(runtime.torch) as measured:
        output = runtime.model.generate(**inputs, **options)
    ids = output[0, prompt_tokens:]
    text = runtime.processor.decode(ids, skip_special_tokens=True,
                                    clean_up_tokenization_spaces=False)
    completion_tokens = len(ids)
    runtime.torch.cuda.synchronize()
    seconds = time.perf_counter() - started
    structure_valid = (request.response_format is None or output_matches_schema(
        text, request.response_format["json_schema"]["schema"]))
    if request.response_format is not None:
        structured["output_valid"] = structure_valid
    record({"at": time.time(), "model": runtime.name, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "image_count": len(images), "images": images,
            "temperature": request.temperature, "max_tokens": request.max_tokens,
            "seconds": seconds, "cuda": measured.metrics, "structured": structured,
            "response_sha256": hashlib.sha256(text.encode()).hexdigest()})
    if not structure_valid:
        raise StructuredGenerationError("Generated output failed the requested structure")
    result = {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion",
            "created": int(time.time()), "model": runtime.name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "length" if completion_tokens >= request.max_tokens else "stop"}],
            "cizheng_runtime": {"wall_seconds": seconds, "cuda": measured.metrics},
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}
    if request.response_format is not None:
        result["cizheng_runtime"]["structured"] = structured
    return result


@app.get("/health")
def health():
    content = {"status": "ready" if runtime.ready else "not_ready", **runtime.identity(),
               "failure_type": runtime.failure_type,
               "generation_in_progress": generation_lock.locked()}
    return JSONResponse(content, status_code=200 if runtime.ready else 503)


@app.get("/v1/models")
def models():
    if not runtime.ready:
        raise HTTPException(503, "Real local GPU model is not ready")
    return {"object": "list", "data": [{"id": runtime.name, "object": "model", "owned_by": "local-spark"}]}


@app.post("/v1/chat/completions")
async def complete(request: Completion):
    if not runtime.ready:
        raise HTTPException(503, "Real local GPU model is not ready")
    if request.model != runtime.name:
        raise HTTPException(404, "Model is not served")
    if request.stream or request.chat_template_kwargs:
        raise HTTPException(400, "Streaming and thinking options are unsupported in this transport")
    async with lock:
        try:
            return await asyncio.to_thread(infer, request)
        except StructuredFormatError as error:
            raise HTTPException(422, "Malformed or unsupported structured schema") from error
        except StructuredDependencyError as error:
            raise HTTPException(503, "Requested structured decoder is unavailable") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except Exception as error:
            record({"at": time.time(), "error_type": type(error).__name__})
            raise HTTPException(500, "Local GPU inference failed: " + type(error).__name__) from error
