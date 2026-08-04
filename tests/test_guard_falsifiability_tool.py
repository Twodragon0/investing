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


def test_restore_state_reverts_modified_file(tmp_path, monkeypatch):
    """`module-level` 케이스가 남기는 `_state` 오염을 되돌려야 한다.

    그 케이스는 import 시점 리다이렉트를 일부러 깨뜨리므로 atexit flush 가 진짜
    `_state/image_rejection_metrics.json` 에 기록된다. 로컬은 skip-worktree 가
    이를 가려 CI 에서만 드러났다(워크플로우의 "Verify working tree restored"
    단계가 실제로 잡아낸 회귀).
    """
    state_dir = tmp_path / "_state"
    state_dir.mkdir()
    target = state_dir / "image_rejection_metrics.json"
    target.write_text('{"last_seen": "original"}', encoding="utf-8")
    monkeypatch.setattr(gf, "REPO_ROOT", tmp_path)

    snapshot = gf._snapshot_state()
    target.write_text('{"last_seen": "polluted"}', encoding="utf-8")

    restored = gf._restore_state(snapshot)

    assert restored == ["_state/image_rejection_metrics.json"]
    assert target.read_text(encoding="utf-8") == '{"last_seen": "original"}'


def test_restore_state_recreates_deleted_file(tmp_path, monkeypatch):
    state_dir = tmp_path / "_state"
    state_dir.mkdir()
    target = state_dir / "seen.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gf, "REPO_ROOT", tmp_path)

    snapshot = gf._snapshot_state()
    target.unlink()

    restored = gf._restore_state(snapshot)

    assert restored == ["_state/seen.json"]
    assert target.read_text(encoding="utf-8") == "{}"


def test_restore_state_noop_when_untouched(tmp_path, monkeypatch):
    state_dir = tmp_path / "_state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gf, "REPO_ROOT", tmp_path)

    snapshot = gf._snapshot_state()

    assert gf._restore_state(snapshot) == []


def test_snapshot_state_tolerates_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gf, "REPO_ROOT", tmp_path)

    assert gf._snapshot_state() == {}


# ---------------------------------------------------------------------------
# 정적 가드 mutation 케이스
# ---------------------------------------------------------------------------


def test_static_case_anchors_are_unique_in_their_targets():
    """모든 STATIC_CASES 앵커는 대상 파일에 정확히 1회만 나타나야 한다.

    앵커가 여러 번 나타나면 `replace(..., 1)` 이 엉뚱한 줄을 바꾸고, 가드는
    정당하게 green 이 되어 VACUOUS 오탐이 난다. 실제로 `fix_defi_tvl_history.py`
    감사에서 `__file__` 앵커가 `sys.path.insert` 줄을 먼저 잡아 그렇게 됐다.
    """
    for case in gf.STATIC_CASES:
        if case.old is None:
            continue
        target = gf.REPO_ROOT / case.target
        assert target.is_file(), f"{case.label}: 대상 파일 없음 — {case.target}"
        occurrences = target.read_text(encoding="utf-8").count(case.old)
        assert occurrences == 1, (
            f"{case.label}: {case.target} 에서 앵커가 {occurrences}회 발견됨 (1회여야 함). 앵커: {case.old!r}"
        )


def test_static_case_guard_files_exist():
    """각 케이스의 node id 가 가리키는 테스트 파일이 실제로 존재해야 한다."""
    for case in gf.STATIC_CASES:
        rel = case.node_id.split("::")[0]
        assert (gf.REPO_ROOT / rel).is_file(), f"{case.label}: 가드 파일 없음 — {rel}"


def test_apply_static_mutation_appends_when_old_is_none():
    case = gf.StaticCase("probe", "x.py", None, "\nAPPENDED = 1\n", "t.py::t")

    assert gf.apply_static_mutation("ORIG = 0\n", case) == "ORIG = 0\n\nAPPENDED = 1\n"


def test_apply_static_mutation_replaces_unique_anchor():
    case = gf.StaticCase("probe", "x.py", "OLD", "NEW", "t.py::t")

    assert gf.apply_static_mutation("a = OLD\n", case) == "a = NEW\n"


@pytest.mark.parametrize("source", ["a = 1\n", "OLD\nOLD\n"], ids=["missing", "duplicated"])
def test_apply_static_mutation_rejects_non_unique_anchor(source):
    case = gf.StaticCase("probe", "x.py", "OLD", "NEW", "t.py::t")

    with pytest.raises(RuntimeError, match="정확히 1회가 아니다"):
        gf.apply_static_mutation(source, case)


def test_mutated_files_covers_every_static_target():
    """안전 검사(_assert_safe_to_run)가 변형 대상 전부를 감시해야 한다."""
    watched = {p.resolve() for p in gf._mutated_files()}

    for case in gf.STATIC_CASES:
        assert (gf.REPO_ROOT / case.target).resolve() in watched, (
            f"{case.target} 가 _mutated_files() 에 없음 — 미커밋 변경 보호가 빠진다"
        )
