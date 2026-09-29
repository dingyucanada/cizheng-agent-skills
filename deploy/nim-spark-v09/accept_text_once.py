"""Send one approved public-text request to the isolated NIM; preserve original bytes."""
import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8007"
MODEL = "Qwen3-4B-Instruct-2507"
PUBLIC_SOURCE = "https://www.metmuseum.org/art/collection/search/48559"
REQUEST = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "你是文字核查助手。仅依据所给公开文字，区分图录记载与独立实物证据；不推断未见器物的归属，不输出思维链。"},
        {"role": "user", "content": "公开馆藏摘要：纽约大都会艺术博物馆，Bottle，馆藏号79.2.467；馆方记载为清代康熙时期（1662—1722）、18世纪初，景德镇瓷器，釉下钴蓝彩，高36.8厘米，饰葫芦与蝙蝠纹。来源：https://www.metmuseum.org/art/collection/search/48559 。另有一件未知器物被主张为‘康熙景德镇制’，但没有提供照片、底款、尺寸、来源或检测资料。请在150字以内分列馆方记载、该未知器物主张的证据边界、两项最需补充的证据。不能把馆方记录当作未知器物的鉴定结论。"},
    ],
    "max_tokens": 256,
    "temperature": 0.2,
    "stream": False,
}


def request_bytes():
    return json.dumps(REQUEST, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def validated_usage(data):
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        raise ValueError("missing_usage")
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    counts = [usage.get(key) for key in keys]
    if (any(type(value) is not int or value < 0 for value in counts)
            or counts[1] == 0 or counts[1] > REQUEST["max_tokens"]
            or counts[2] != counts[0] + counts[1]):
        raise ValueError("invalid_usage")
    return dict(zip(keys, counts))


def validate_response(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("model") != MODEL:
        raise ValueError("model_identity_mismatch")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("invalid_response_envelope")
    if choices[0].get("finish_reason") != "stop":
        raise ValueError("response_not_complete")
    message = choices[0].get("message")
    if (not isinstance(message, dict) or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str) or not message["content"].strip()):
        raise ValueError("invalid_assistant_content")
    usage = validated_usage(data)
    return {"model": data["model"], "finish_reason": "stop", "usage": usage,
            "assistant_characters": len(message["content"]), "accepted_interface": True,
            "semantic_quality_proven": False, "image_understanding_tested": False}


def accept_once(directory, opener=None, clock_ns=time.time_ns, monotonic=time.monotonic):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw_request = request_bytes()
    claim = {"request": REQUEST, "public_source": PUBLIC_SOURCE,
             "request_sha256": hashlib.sha256(raw_request).hexdigest(),
             "inference_request_limit": 1, "automatic_retries": 0}
    # A failed or interrupted attempt retains this exclusive claim and cannot be replayed.
    with (directory / "claimed.json").open("x") as stream:
        json.dump(claim, stream, ensure_ascii=False, sort_keys=True)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started_at, start = clock_ns(), monotonic()
    receipt = {"request_sha256": claim["request_sha256"], "request_started_at_unix_ns": started_at,
               "model": MODEL, "inference_requests_sent": 1, "automatic_retries": 0,
               "max_tokens": REQUEST["max_tokens"], "http_timeout_seconds": 80,
               "accepted_interface": False}
    response_raw = b""
    try:
        request = urllib.request.Request(BASE_URL + "/v1/chat/completions", data=raw_request,
                                         headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=80) as response:
            receipt["http_status"] = response.status
            response_raw = response.read()
            if response.status != 200:
                raise ValueError("unexpected_http_status")
        # Preserve verified usage even when a complete-looking payload reports truncation.
        try:
            receipt["usage"] = validated_usage(json.loads(response_raw))
        except (ValueError, TypeError):
            pass
        receipt.update(validate_response(response_raw))
    except urllib.error.HTTPError as error:
        response_raw = error.read()
        receipt.update(http_status=error.code, failure_category="http_error")
    except ValueError as error:
        category = str(error)
        allowed = {"model_identity_mismatch", "invalid_response_envelope", "response_not_complete",
                   "invalid_assistant_content", "missing_usage", "invalid_usage", "unexpected_http_status"}
        receipt["failure_category"] = category if category in allowed else "invalid_json"
    except Exception:
        receipt["failure_category"] = "transport_error"
    finally:
        receipt["request_finished_at_unix_ns"] = clock_ns()
        receipt["elapsed_seconds"] = monotonic() - start
        if not math.isfinite(receipt["elapsed_seconds"]) or receipt["elapsed_seconds"] < 0:
            raise ValueError("invalid elapsed time")
        receipt["response_sha256"] = hashlib.sha256(response_raw).hexdigest()
        with (directory / "response.raw.json").open("xb") as stream:
            stream.write(response_raw)
        with (directory / "receipt.json").open("x") as stream:
            json.dump(receipt, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    receipt = accept_once(args.evidence_directory)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if not receipt["accepted_interface"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
