"""Extract verified official Ubuntu Python headers inside a dedicated project.

No sudo, system package install, system apt update, or interpreter upgrade.
The pinned package reflects the observed Spark deployment, not every machine.
"""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "3.12.3-1ubuntu0.17"
SHA256 = "945ad3f651f683c11e72d19d804b1cff097308dcffa01057635cba038f875164"
PACKAGE = "libpython3.12-dev"
KEYRING = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
ARCHIVE = "http://ports.ubuntu.com/ubuntu-ports/"


def prepare(project: Path):
    if platform.system() != "Linux" or platform.machine() != "aarch64" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("This pinned recipe requires Ubuntu ARM64 and Python 3.12")
    for command in ("apt-get", "apt-cache", "dpkg-deb", "gcc"):
        if not shutil.which(command):
            raise RuntimeError("Required tool unavailable: " + command)
    if not Path(KEYRING).is_file():
        raise RuntimeError("Official Ubuntu archive keyring unavailable")
    project = project.expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("An existing dedicated project directory is required")
    apt = project / "runtime-apt-headers"
    for relative in ("lists/partial", "cache/partial"):
        (apt / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
    source = apt / "ubuntu-headers.list"
    source.write_text("deb [arch=arm64 signed-by=" + KEYRING + "] " + ARCHIVE + " noble-updates main\n")
    options = ["-o", f"Dir::State::lists={apt}/lists",
               "-o", f"Dir::Etc::sourcelist={source}", "-o", "Dir::Etc::sourceparts=-",
               "-o", f"Dir::Cache::archives={apt}/cache",
               "-o", f"Dir::Cache::pkgcache={apt}/cache/pkgcache.bin",
               "-o", f"Dir::Cache::srcpkgcache={apt}/cache/srcpkgcache.bin",
               "-o", "Acquire::Languages=none", "-o", "Acquire::Retries=2",
               "-o", "APT::Get::List-Cleanup=0"]
    subprocess.run(["apt-get", *options, "update"], check=True)
    specification = PACKAGE + "=" + VERSION
    metadata = subprocess.check_output(["apt-cache", *options, "show", specification], text=True)
    records = []
    for paragraph in metadata.strip().split("\n\n"):
        record = dict(line.split(": ", 1) for line in paragraph.splitlines()
                      if line and not line[0].isspace() and ": " in line)
        if (record.get("Package"), record.get("Version"), record.get("Architecture")) == (PACKAGE, VERSION, "arm64"):
            records.append(record)
    if not records or any(record.get("SHA256") != SHA256 for record in records):
        raise ValueError("Pinned package unavailable or signed index SHA256 differs")
    record = records[0]
    if not record["Filename"].startswith("pool/main/p/python3.12/"):
        raise ValueError("Unexpected official package path")
    directory = project / ("runtime-headers-ubuntu-" + VERSION)
    directory.mkdir(exist_ok=True, mode=0o700)
    package = directory / Path(record["Filename"]).name
    if not package.is_file():
        subprocess.run(["apt-get", *options, "download", specification], cwd=directory, check=True)
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != SHA256 or package.stat().st_size != int(record["Size"]):
        raise ValueError("Downloaded package bytes differ from signed official index")
    subprocess.run(["dpkg-deb", "--extract", str(package), str(directory)], check=True)
    includes = [directory / name for name in (
        "usr/include/python3.12", "usr/include", "usr/include/aarch64-linux-gnu/python3.12")]
    subprocess.run(["gcc", "-fsyntax-only", *[f"-I{path}" for path in includes], "-x", "c", "-"],
                   input="#include <Python.h>\nint main(void) { return 0; }\n", text=True, check=True)
    receipt = {"package": PACKAGE, "version": VERSION, "architecture": "arm64",
               "url": ARCHIVE + record["Filename"], "sha256": digest, "sha256_verified": True,
               "bytes": package.stat().st_size, "system_changed": False,
               "interpreter_upgraded": False, "sudo_used": False,
               "gcc_python_header_check_passed": True,
               "extract_relative_directory": directory.relative_to(project).as_posix()}
    evidence = project / "runtime-evidence"
    evidence.mkdir(exist_ok=True, mode=0o700)
    (evidence / "python-headers.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    prepare(parser.parse_args().project)
