"""`scripts/tools/guard_falsifiability.py` 의 순수 함수 단위 테스트.

서브프로세스로 pytest 를 8회 × 2 돌리는 `run_all()` 은 여기서 실행하지 않는다
(전체 스위트가 자기 자신을 재귀 실행하게 된다). 대신 소스 변환/판정/렌더링 등
결정적 부분만 검증한다. 실제 falsifiability 실행은 주간 워크플로우가 담당한다.
"""

import guard_falsifiability as gf
import pytest

CONFTEST_SAMPLE = '''\
"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _first_fixture(monkeypatch):
    """Doc."""
    return None


@pytest.fixture
def _not_autouse(monkeypatch):
    return None


@pytest.fixture(autouse=True)
def _second_fixture(request, tmp_path, monkeypatch):
    return None
'''


def test_discover_autouse_fixtures_finds_only_autouse():
    found = gf.discover_autouse_fixtures(CONFTEST_SAMPLE)

    assert found == ["_first_fixture", "_second_fixture"]
    assert "_not_autouse" in CONFTEST_SAMPLE, "샘플에 비-autouse fixture가 있어야 의미 있는 검증"


def test_discover_autouse_fixtures_empty_source():
    assert gf.discover_autouse_fixtures("") == []


def test_registry_matches_real_conftest():
    """CASES 레지스트리가 실제 conftest 의 autouse fixture 전수와 일치해야 한다.

    새 격리 fixture 를 가드 등록 없이 추가하면 여기서 잡힌다 — 주간 워크플로우를
    기다리지 않고 PR 시점에 red 가 된다.
    """
    src = gf.CONFTEST.read_text(encoding="utf-8")
    found = set(gf.discover_autouse_fixtures(src))
    registered = {name for name in gf.CASES if not name.startswith("module-level:")}

    assert found == registered, (
        f"conftest autouse fixture 와 CASES 레지스트리 불일치. "
        f"미등록={sorted(found - registered)}, 잔존={sorted(registered - found)}. "
        "새 격리 fixture 는 가드 테스트와 함께 CASES 에 등록할 것 (docs/test-isolation.md)."
    )


def test_disable_fixture_flips_autouse():
    patched = gf._disable_fixture(CONFTEST_SAMPLE, "_first_fixture")

    assert "@pytest.fixture(autouse=False)\ndef _first_fixture(" in patched
    # 다른 fixture 는 건드리지 않는다.
    assert "@pytest.fixture(autouse=True)\ndef _second_fixture(" in patched


def test_disable_fixture_rejects_unknown_name():
    with pytest.raises(RuntimeError, match="정확히 1개"):
        gf._disable_fixture(CONFTEST_SAMPLE, "_nonexistent_fixture")


def test_disable_module_level_breaks_the_import():
    src = "try:\n" + gf._MODULE_LEVEL_IMPORT + "\nexcept ImportError:\n    pass\n"

    patched = gf._disable_module_level(src)

    assert "image_rejection_metrics_ABSENT" in patched
    assert gf._MODULE_LEVEL_IMPORT not in patched


def test_disable_module_level_rejects_missing_import():
    with pytest.raises(RuntimeError, match="찾지 못했다"):
        gf._disable_module_level("import os\n")


@pytest.mark.parametrize(
    ("patched_rc", "control_rc", "expected"),
    [
        (1, 0, "FALSIFIABLE"),
        (0, 0, "VACUOUS"),
        (1, 1, "CONTROL-FAIL"),
    ],
)
def test_render_table_reports_verdict(patched_rc, control_rc, expected):
    results = [
        {
            "fixture": "_x",
            "guard": "test_x",
            "patched_rc": patched_rc,
            "control_rc": control_rc,
            "verdict": expected,
        }
    ]

    out = gf._render_table(results)

    assert expected in out
    assert "test_x" in out


def test_render_table_marks_unmapped_fixture():
    results = [
        {
            "fixture": "_orphan",
            "guard": None,
            "patched_rc": None,
            "control_rc": None,
            "verdict": "UNMAPPED",
        }
    ]

    out = gf._render_table(results)

    assert "0/1 guards falsifiable" in out
    assert "CASES 미등록" in out
