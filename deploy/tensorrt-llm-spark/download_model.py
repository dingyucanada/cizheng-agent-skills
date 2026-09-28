"""Download a public official Qwen checkpoint with exact upstream file verification.

Uses no authentication, proxies, GPU, package installation, or model inference.
The metadata must already have been saved from the official ModelScope API.
"""
import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
SOURCE = "https://modelscope.cn"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def validate_files(metadata):
    if metadata.get("model") != MODEL:
        raise ValueError("unexpected model identity")
    files = metadata.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("missing upstream files")
    result, seen = [], set()
    for item in files:
        if not isinstance(item, dict) or item.get("Type") != "blob":
            raise ValueError("non-file metadata")
        name = item.get("Path")
        if (not isinstance(name, str) or not name or "\\" in name or "\x00" in name
                or PurePosixPath(name).is_absolute()
                or any(part in ("", ".", "..") for part in name.split("/"))
                or name in seen):
            raise ValueError("unsafe or duplicate file path")
        size, sha, revision = item.get("Size"), item.get("Sha256"), item.get("Revision")
        if type(size) is not int or size < 0:
            raise ValueError("invalid upstream size")
        if not isinstance(sha, str) or re.fullmatch(r"[a-f0-9]{64}", sha) is None:
            raise ValueError("invalid upstream checksum")
        if not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{40}", revision) is None:
            raise ValueError("invalid upstream file revision")
        seen.add(name)
        result.append({"name": name, "bytes": size, "sha256": sha,
                       "source_file_revision": revision})
    required = {"config.json", "tokenizer.json", "model.safetensors.index.json"}
    if not required.issubset(seen) or not any(x.endswith(".safetensors") for x in seen):
        raise ValueError("incomplete checkpoint metadata")
    return result


def identity(path):
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            count += len(chunk)
            digest.update(chunk)
    return count, digest.hexdigest()


def assert_safe_path(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink destination refused")


def download_file(item, directory, opener, request_revision="master"):
    target = directory / item["name"]
    assert_safe_path(target)
    if target.exists():
        if not target.is_file() or identity(target) != (item["bytes"], item["sha256"]):
            raise ValueError("existing file identity mismatch")
        return "already_verified"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    assert_safe_path(partial)
    if partial.exists():
        raise ValueError("incomplete prior download requires review")
    query = urllib.parse.urlencode({"Revision": request_revision, "FilePath": item["name"]})
    request = urllib.request.Request(
        f"{SOURCE}/api/v1/models/{MODEL}/repo?{query}",
        headers={"User-Agent": "cizheng-public-checkpoint-verifier/0.7"})
    digest, count = hashlib.sha256(), 0
    with opener.open(request, timeout=60) as response, partial.open("xb") as stream:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            count += len(chunk)
            if count > item["bytes"]:
                raise ValueError("upstream file exceeds declared size")
            digest.update(chunk)
            stream.write(chunk)
    if (count, digest.hexdigest()) != (item["bytes"], item["sha256"]):
        raise ValueError("download identity mismatch")
    partial.replace(target)
    return "downloaded_verified"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.upstream_manifest.read_bytes())
    files = validate_files(metadata)
    assert_safe_path(args.directory)
    assert_safe_path(args.receipt)
    args.directory.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for item in files:
        status = download_file(item, args.directory, opener)
        print(json.dumps({"file": item["name"], "bytes": item["bytes"], "status": status}), flush=True)
    receipt = {"model": MODEL, "official_source": SOURCE,
               "request_revision": "master",
               "revision_policy": "upstream-per-file-revision+exact-size-and-sha256-not-mutable-alias-trust",
               "files": files, "file_count": len(files),
               "total_file_bytes": sum(item["bytes"] for item in files),
               "upstream_manifest_sha256": hashlib.sha256(canonical_json(metadata)).hexdigest(),
               "all_files_verified": True, "model_loading": False}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    serialized = canonical_json(receipt) + b"\n"
    with args.receipt.open("xb") as stream:
        stream.write(serialized)
    print(json.dumps({"complete": True, "files": len(files),
                      "bytes": receipt["total_file_bytes"],
                      "receipt_sha256": hashlib.sha256(serialized).hexdigest(),
                      "model_loading": False}), flush=True)


if __name__ == "__main__":
    main()
