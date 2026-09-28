"""The scan gate must retain findings and must fail on an unfamiliar JSON schema."""
import runpy
from pathlib import Path

import pytest

summarize_report = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/nvidia-skill-scan.py"))["summarize_report"]


def test_official_report_schema_retains_high_findings_and_partial_scope():
    result = summarize_report({"risk_assessment": {"score": 40, "recommendation": "DO_NOT_INSTALL"},
                               "issues": [{"id": "P1", "severity": "HIGH", "location": {"file": "SKILL.md"},
                                           "remediation": "Remove instruction override"}],
                               "metadata": {"llm_requested": False, "inference_usage": []},
                               "analysis_completeness": {"is_complete": False, "status": "partial"}})
    assert result["finding_count"] == result["high_or_critical_count"] == 1
    assert result["findings"][0]["rule"] == "P1" and result["risk_score"] == 40
    assert result["analysis_completeness"]["is_complete"] is False
    assert result["scan_mode"] == "static_only" and result["llm_used"] is False


def test_unfamiliar_report_cannot_be_misreported_as_clean():
    with pytest.raises(ValueError, match="unrecognized_skillspector_report_schema"):
        summarize_report({"findings": [], "risk_score": 0})
