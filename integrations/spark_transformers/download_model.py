"""Download official Qwen weights or hash an explicitly supplied local copy."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

MODELS = ("Qwen/Qwen3-VL-2B-Instruct", "Qwen/Qwen3-VL-8B-Instruct", "Qwen/Qwen3-VL-32B-Instruct")
PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "LICENSE*"]


def file_identities(directory):
    identities = {}
    for file in sorted(directory.rglob("*")):
        relative = file.relative_to(directory)
        if (not file.is_file() or file.name.startswith(".") or ".cache" in relative.parts
                or file.name == "_file_manifest.json"):
            continue
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for data in iter(lambda: stream.read(16 * 1024 * 1024), b""):
                digest.update(data)
        identities[str(relative)] = {"sha256": digest.hexdigest(), "bytes": file.stat().st_size}
    if not any(name.endswith(".safetensors") for name in identities):
        raise ValueError("No actual model weights found")
    return identities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default=MODELS[0])
    parser.add_argument("--revision", default="master")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--download-workers", type=int, choices=range(1, 9), default=2,
                        help="Parallel official-repository file downloads (default: 2)")
    parser.add_argument("--hash-existing", action="store_true",
                        help="Offline identity hashing; does not prove original download source")
    args = parser.parse_args()
    os.umask(0o077)
    started = time.perf_counter()
    destination = args.output.expanduser().resolve()
    manifest_path = destination / "_file_manifest.json"
    if manifest_path.exists():
        parser.error("Preserve previous manifest; choose a new output or use it unchanged")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not args.hash_existing:
        from modelscope import snapshot_download
        options = {"revision": args.revision, "local_dir": str(destination),
                   "max_workers": args.download_workers, "allow_patterns": PATTERNS}
        if args.cache_dir:
            options["cache_dir"] = str(args.cache_dir.expanduser())
        snapshot_download(args.model, **options)
    identities = file_identities(destination)
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
    manifest = {"model": args.model,
                "download_workers": None if args.hash_existing else args.download_workers,
                "source": ("operator-supplied local copy; original download route not inferred"
                           if args.hash_existing else "official Qwen ModelScope repository"),
                "official_repository": "https://modelscope.cn/models/" + args.model,
                "requested_revision": args.revision,
                "revision_is_mutable": True if args.revision == "master" else None,
                "revision_reference_status": ("mutable" if args.revision == "master"
                                              else "not independently resolved to immutable commit"),
                "downloaded_file_identity": identities,
                "files_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
                "recorded_at": time.time(), "seconds": time.perf_counter() - started}
    with manifest_path.open("x") as output:
        json.dump(manifest, output, indent=2)
    print(json.dumps({"model": args.model, "file_count": len(identities),
                      "bytes": sum(item["bytes"] for item in identities.values()),
                      "files_manifest_sha256": manifest["files_manifest_sha256"],
                      "source": manifest["source"]}, indent=2))


if __name__ == "__main__":
    main()
