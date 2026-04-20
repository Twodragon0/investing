"""Phase 4 regression fixtures — parametrized test for risk_classifier.

5 scenarios covering false-positive suppression and true-positive detection.
Expected levels are set to match current WEIGHTS (see fixture JSON for rationale).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.common.risk_classifier import classify_risk

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "risk_cases"
_FIXTURE_FILES = sorted(_FIXTURE_DIR.glob("*.json"))


@pytest.mark.parametrize("fixture_path", _FIXTURE_FILES, ids=lambda p: p.stem)
def test_risk_case_fixture(fixture_path: Path) -> None:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    verdict = classify_risk(data["items"])
    assert verdict.level == data["expected_level"], (
        f"{data['scenario']}: expected {data['expected_level']!r},"
        f" got {verdict.level!r} (mean={verdict.aggregate_mean:.2f})"
    )
    if "expected_rule_traces" in data:
        for expected_trace in data["expected_rule_traces"]:
            assert any(expected_trace in r for r in verdict.rule_trace), (
                f"{data['scenario']}: missing rule trace {expected_trace!r} in {verdict.rule_trace}"
            )
