"""One bounded public text request; persists original response, never retries.

This independently accepts an inference interface, not the ceramic report workflow.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8006"
MODEL = "Qwen3-4B-Instruct-2507"
PUBLIC_SOURCE_URL = "https://www.metmuseum.org/art/collection/search/48559"
PUBLIC_INPUT = ("大都会艺术博物馆公开馆藏文字摘要（藏品号79.2.467；"
                + PUBLIC_SOURCE_URL + "）：一件饰有葫芦和蝙蝠的葫芦形瓶，"
                "馆方记为清代康熙时期（1662—1722）、18世纪初、景德镇釉下钴蓝彩瓷，高36.8厘米。"
                "这里只提供文字，没有图片。\n"
                "待核查主张（演示用未知器物，不是上述馆藏器）：某件青花葫芦瓶被称为“康熙景德镇制”，"
                "目前未提供照片、底款、尺寸、来源或检测资料。"
                "仅根据上述文字，用中文不超过150字分列馆方记载、未知器物归属的证据边界和两项待补证；"
                "不把图录年代当未知器物的已证实年代，不输出推理过程。")


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def payload():
    return {"model": MODEL, "messages": [
        {"role": "system", "content": "你是文字资料核查助手。仅依据所给公开资料，把馆方文字记载、对另一件未知器物无法推出的结论和待补物证分开；简洁作答，不输出推理过程，不编造观察或检测。"},
        {"role": "user", "content": PUBLIC_INPUT}],
        "temperature": 0, "max_tokens": 256, "stream": False}


def usage_of(value):
    usage = value.get("usage") if isinstance(value, dict) else None
    if not isinstance(usage, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in keys):
        return None
    return {key: usage[key] for key in keys}


def validate_response(value):
    usage = usage_of(value)
    if not isinstance(value, dict) or value.get("model") != MODEL:
        return "model_identity_mismatch", usage, None
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return "invalid_choices", usage, None
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        return "response_truncated" if choice.get("finish_reason") == "length" else "unverified_termination", usage, None
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return "missing_text", usage, None
    if usage is None or usage["completion_tokens"] <= 0 or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        return "invalid_usage", usage, content
    return None, usage, content


def run_once(directory, opener=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # The claim file prevents rerunning a completed or failed public request.
    with (directory / "claimed.json").open("xb") as stream:
        stream.write(serialized({"model": MODEL, "endpoint": BASE, "request": payload(),
                                 "automatic_retries": 0}) + b"\n")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = {"model": MODEL, "endpoint": BASE, "inference_requests_sent": 0,
              "request_sha256": hashlib.sha256(serialized(payload())).hexdigest(),
              "automatic_retries": 0, "usage": None, "accepted_interface": False,
              "public_source_url": PUBLIC_SOURCE_URL,
              "ceramic_workflow_validated": False, "semantic_quality_guaranteed": False}
    start = time.monotonic()
    try:
        with opener.open(BASE + "/health", timeout=10) as response:
            if response.status != 200:
                raise ValueError("readiness_rejected")
        with opener.open(BASE + "/v1/models", timeout=10) as response:
            inventory = json.load(response)
        if (not isinstance(inventory, dict) or not isinstance(inventory.get("data"), list)
                or MODEL not in [item.get("id") for item in inventory["data"] if isinstance(item, dict)]):
            raise ValueError("model_inventory_mismatch")
        request = urllib.request.Request(BASE + "/v1/chat/completions", data=serialized(payload()),
                                         headers={"Content-Type": "application/json"}, method="POST")
        result["inference_requests_sent"] = 1
        result["request_started_at_unix_ns"] = time.time_ns()
        with opener.open(request, timeout=80) as response:
            raw = response.read()
        result["request_finished_at_unix_ns"] = time.time_ns()
        (directory / "response.raw.json").write_bytes(raw)
        result["response_sha256"] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        category, usage, text = validate_response(value)
        result["usage"] = usage
        result["diagnostic_category"] = category
        result["accepted_interface"] = category is None
        if text is not None:
            result["public_output"] = text
            # These checks are literal retention, not a semantic truth assessment.
            result["literal_source_tokens_retained"] = {key: key.lower() in text.lower() for key in ("79.2.467", "康熙")}
    except urllib.error.HTTPError as error:
        result["diagnostic_category"] = "http_error"
        result["http_status"] = error.code
    except (TimeoutError, urllib.error.URLError, OSError):
        result["diagnostic_category"] = "transport_failure"
    except json.JSONDecodeError:
        result["diagnostic_category"] = "invalid_json_envelope"
    except ValueError as error:
        result["diagnostic_category"] = str(error) if str(error) in ("readiness_rejected", "model_inventory_mismatch") else "invalid_envelope"
    if result["inference_requests_sent"] == 1 and "request_finished_at_unix_ns" not in result:
        result["request_finished_at_unix_ns"] = time.time_ns()
    result["elapsed_seconds"] = time.monotonic() - start
    (directory / "receipt.json").write_bytes(serialized(result) + b"\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    result = run_once(args.directory)
    print(json.dumps(result, ensure_ascii=False))
    if not result["accepted_interface"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
