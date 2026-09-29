"""Stage fixed public metadata/small files and keep temporary CDN URLs private.

No model weight body is downloaded here. The generic downloader fetches the
three large shards separately, after every small file has been verified.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_SHA256 = "c05398358bdde37fe7ce1656bea3388bf270012f216d10bcaa25fcbf6e085795"
DOWNLOADER_SHA256 = "27a61dd6f49a3ad03f1164efcb1a72a2991c913992046a6ff17fb55becb711b7"
CDN_HOSTS = {"us.aws.cdn.hf.co", "cdn-lfs.huggingface.co", "cdn-lfs.hf.co", "cas-bridge.xethub.hf.co"}


def verify(data, entry):
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != entry["bytes"]:
        raise ValueError("fixed file byte count mismatch")
    if entry.get("lfs_sha256"):
        if digest != entry["lfs_sha256"]:
            raise ValueError("fixed LFS SHA256 mismatch")
    else:
        git = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if git != entry["git_blob_sha1"]:
            raise ValueError("fixed Git blob SHA1 mismatch")
    return digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.stage.resolve()
    stage.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage.chmod(0o700)
    receipt_path = stage / f"prepare-receipt-attempt-{args.attempt:02d}.json"
    if receipt_path.exists():
        raise FileExistsError("preserve the prior preparation attempt")
    raw = (ROOT / "checkpoint.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("fixed 27B manifest changed")
    if hashlib.sha256((ROOT / "download_fixed.py").read_bytes()).hexdigest() != DOWNLOADER_SHA256:
        raise ValueError("generic downloader changed")
    manifest = json.loads(raw)
    urls = {}
    results = []

    def fetch(entry):
        url = f'https://huggingface.co/{manifest["model"]}/resolve/{manifest["revision"]}/{entry["name"]}'
        try:
            if entry["bytes"] >= 64 * 1024**2:
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
                    parsed = urllib.parse.urlsplit(response.url)
                    if response.status != 200 or parsed.scheme != "https" or parsed.hostname not in CDN_HOSTS:
                        raise ValueError("public CDN HEAD unavailable")
                    if int(response.headers.get("Content-Length", "-1")) != entry["bytes"]:
                        raise ValueError("CDN size differs from fixed manifest")
                    return ({"name": entry["name"], "bytes": entry["bytes"], "head_status": 200,
                             "source_host": parsed.hostname, "large_url_saved_privately": True}, response.url)
            path = stage / entry["name"]
            if path.is_symlink():
                raise ValueError("symlink in private staging directory")
            if path.exists():
                data = path.read_bytes()
                digest = verify(data, entry)
            else:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read(entry["bytes"] + 1)
                    host = urllib.parse.urlsplit(response.url).hostname
                digest = verify(data, entry)
                with path.open("xb") as target:
                    target.write(data)
                path.chmod(0o600)
            return ({"name": entry["name"], "bytes": entry["bytes"], "sha256": digest,
                     "small_file_verified": True}, None)
        except Exception as exc:
            return ({"name": entry["name"], "prepared": False,
                     "error_type": type(exc).__name__, "http_status": getattr(exc, "code", None)}, None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result, url in pool.map(fetch, manifest["files"]):
            results.append(result)
            if url:
                urls[result["name"]] = url
            print(json.dumps(result), flush=True)
    passed = all(item.get("small_file_verified") or item.get("large_url_saved_privately") for item in results)
    receipt = {"model": manifest["model"], "revision": manifest["revision"],
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "preparation_passed": passed, "manifest_sha256": MANIFEST_SHA256,
               "large_weight_bodies_downloaded": False, "files": results}
    with receipt_path.open("x") as target:
        target.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    if not passed:
        return 1
    private_map = stage / "private-url-map.json"
    if private_map.exists():
        shutil.copy2(private_map, stage / f"private-url-map-before-attempt-{args.attempt:02d}.json")
    private_map.write_text(json.dumps(urls))
    private_map.chmod(0o600)
    for source, name in ((ROOT / "checkpoint.json", "checkpoint-manifest.json"),
                         (ROOT / "expected_identity.json", "expected-identity.json"),
                         (ROOT / "download_fixed.py", "download_fixed.py"),
                         (ROOT / "cpu_compatibility.py", "cpu_compatibility.py")):
        shutil.copyfile(source, stage / name)
        (stage / name).chmod(0o600)
    print(json.dumps({"preparation_passed": True, "verified_small_files": len(results) - len(urls),
                      "large_public_cdn_urls_saved_privately": len(urls)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
