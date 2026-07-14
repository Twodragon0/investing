"""component_counts 도구 회귀 가드.

docs/component-counts.md 가 실측과 드리프트되면 CI(pytest)에서 실패시켜
문서 수치가 코드와 어긋난 채 병합되는 것을 방지한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = REPO_ROOT / "scripts" / "tools" / "component_counts.py"

_spec = importlib.util.spec_from_file_location("component_counts", _MODULE_PATH)
assert _spec and _spec.loader
component_counts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(component_counts)


def test_counts_are_positive_ints():
    counts = component_counts.compute_counts()
    expected_keys = {
        "collectors",
        "generators",
        "common_modules",
        "workflows",
        "category_pages",
        "tests",
    }
    assert set(counts) == expected_keys
    for key, value in counts.items():
        assert isinstance(value, int), key
        assert value > 0, key


def test_generated_doc_in_sync():
    """docs/component-counts.md 가 실측과 일치해야 한다.

    실패 시: `python scripts/tools/component_counts.py --write` 실행.
    """
    counts = component_counts.compute_counts()
    drift = component_counts.check_targets(counts, [component_counts.DEFAULT_TARGET])
    assert drift == 0, "component-counts.md 드리프트 — --write 로 갱신 필요"
