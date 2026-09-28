#!/usr/bin/env python3
"""Run real NVIDIA SkillSpector static scans with outbound sockets disabled.

No LLM or transitive fetch is requested. Findings are retained without automatic
suppression. A static result is not NVIDIA verification, semantic evaluation,
cryptographic signing, or a current online dependency vulnerability check.
Run with the Python from the isolated SkillSpector environment.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
SCANNER_COMMIT = "89e90872e2ec813bcb137bf6b3145c92e55811ae"
EXCLUDED_TREES = {"eval", "evals", "benchmark", "artifact", "artifacts"}
BOOTSTRAP = """
import sys
def offline_guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise OSError('network disabled for Cizheng static Skill scan')
sys.addaudithook(offline_guard)
from skillspector.cli import app
sys.argv[0] = 'skillspector'
app()
"""


def tree_hash(directory):
    entries = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("skill bundle symlink refused")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            entries.append([path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def summarize_report(report):
    """Read the actual 2.12 JSON schema; unknown schema fails closed."""
    risk = report.get("risk_assessment")
    findings = report.get("issues")
    completeness = report.get("analysis_completeness")
    metadata = report.get("metadata")
    if not isinstance(risk, dict) or not isinstance(findings, list) or not isinstance(completeness, dict) or not isinstance(metadata, dict):
        raise ValueError("unrecognized_skillspector_report_schema")
    severe = [finding for finding in findings if str(finding.get("severity", "")).upper() in ("HIGH", "CRITICAL")]
    return {"finding_count": len(findings), "high_or_critical_count": len(severe),
            "risk_score": risk.get("score"), "recommendation": risk.get("recommendation"),
            "scan_mode": "static_only" if metadata.get("llm_requested") is False else "unknown",
            "llm_used": bool(metadata.get("inference_usage")),
            "findings": [{"rule": item.get("id"), "severity": item.get("severity"),
                          "location": item.get("location"), "remediation": item.get("remediation")} for item in findings],
            "analysis_completeness": {key: completeness.get(key) for key in (
                "status", "is_complete", "coverage_percent", "execution_successful", "ledger_exceptions")}}


def stage_runtime_scope(skill, output):
    """NVIDIA Tier-1 policy excludes artifact and evaluation trees from staging."""
    staged = output / "runtime-scope" / skill.name
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    excluded = []
    for entry in sorted(skill.iterdir()):
        if entry.name in EXCLUDED_TREES:
            excluded.append({"path": entry.name + ("/" if entry.is_dir() else ""),
                             "reason": "NVIDIA Tier-1 runtime staging excludes artifact and evaluation trees"})
        elif entry.is_dir():
            shutil.copytree(entry, staged / entry.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif entry.suffix != ".pyc":
            shutil.copy2(entry, staged / entry.name)
    return staged, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=SOURCE / "skills")
    parser.add_argument("--output", type=Path, default=SOURCE / ".tmp/nvidia-skillspector")
    args = parser.parse_args()
    skills, output = args.skills_dir.resolve(), args.output.resolve()
    if skills != SOURCE / "skills":
        parser.error("This release gate scans only the project's local Skills directory.")
    if output == skills or skills in output.parents:
        parser.error("Scan reports and staged runtime copies must be outside the Skills directory.")
    if version("skillspector") != "2.12.0":
        parser.error("Install the documented pinned SkillSpector 2.12.0 source commit first.")
    output.mkdir(parents=True, exist_ok=True)
    # Inherit only process essentials, excluding all provider credentials.
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR", "SYSTEMROOT") if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
               OTEL_SDK_DISABLED="true", SKILLSPECTOR_LOG_LEVEL="WARNING", SKILLSPECTOR_OSV_TIMEOUT="0.1")
    results = []
    for skill in sorted(skills.iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").is_file():
            continue
        digest = tree_hash(skill)
        staged, excluded = stage_runtime_scope(skill, output)
        report_path = output / (skill.name + ".json")
        completed = subprocess.run([sys.executable, "-c", BOOTSTRAP, "scan", str(staged),
                                    "--no-llm", "--format", "json", "--output", str(report_path)],
                                   env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (output / (skill.name + ".log")).write_text(completed.stdout)
        if completed.returncode != 0 or not report_path.is_file():
            results.append({"skill": skill.name, "bundle_sha256": digest, "status": "scan_failed",
                            "exit_code": completed.returncode})
            continue
        report = json.loads(report_path.read_text())
        parsed = summarize_report(report)
        results.append({"skill": skill.name, "bundle_sha256": digest, "status": "scan_completed",
                        "scan_scope": "runtime_staged_subset", "scope_exclusions": excluded,
                        "runtime_scope_sha256": tree_hash(staged),
                        "exit_code": completed.returncode, **parsed})
    needs_review = (not results or any(r["status"] != "scan_completed" or r["finding_count"] or
                    r["analysis_completeness"]["is_complete"] is not True for r in results))
    summary = {"scanner": "NVIDIA SkillSpector", "version": version("skillspector"),
               "official_source_commit": SCANNER_COMMIT, "network_policy": "outbound_socket_calls_blocked",
               "llm_requested": False, "nvidia_verified_skill": False,
               "online_dependency_database_checked": False, "automatic_findings_suppression": False,
               "release_gate": "needs_review" if needs_review else "static_checks_clear",
               "results": results}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if needs_review:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
