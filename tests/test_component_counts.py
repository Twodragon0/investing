"""component_counts 도구 회귀 가드.

docs/component-counts.md 가 실측과 드리프트되면 CI(pytest)에서 실패시켜
문서 수치가 코드와 어긋난 채 병합되는 것을 방지한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# render_table / _replace_block
# ---------------------------------------------------------------------------

_SAMPLE = {
    "collectors": 1,
    "generators": 2,
    "common_modules": 3,
    "workflows": 4,
    "category_pages": 5,
    "tests": 6,
}


class TestRenderTable:
    def test_contains_markers_and_all_labels(self):
        block = component_counts.render_table(_SAMPLE)
        assert block.startswith(component_counts.START_MARKER)
        assert block.rstrip().endswith(component_counts.END_MARKER)
        # 각 라벨이 자신의 값과 같은 행에 렌더되는지 확인 (라벨↔값 매핑 오라클).
        for key, label in component_counts._LABELS.items():
            assert f"| {label} | {_SAMPLE[key]} |" in block


class TestReplaceBlock:
    def test_replaces_between_markers(self):
        text = f"before\n{component_counts.START_MARKER}\nOLD\n{component_counts.END_MARKER}\nafter"
        out = component_counts._replace_block(text, "NEWBLOCK")
        assert out == "before\nNEWBLOCK\nafter"

    def test_raises_without_markers(self):
        with pytest.raises(ValueError, match="마커"):
            component_counts._replace_block("no markers here", "X")


# ---------------------------------------------------------------------------
# write_targets
# ---------------------------------------------------------------------------


class TestWriteTargets:
    @pytest.fixture(autouse=True)
    def _repo_root(self, tmp_path, monkeypatch):
        # write/check 함수는 출력용으로 target.relative_to(REPO_ROOT) 를 호출하므로
        # tmp 타깃이 REPO_ROOT 하위에 있도록 REPO_ROOT 를 tmp_path 로 고정한다.
        monkeypatch.setattr(component_counts, "REPO_ROOT", tmp_path)

    def test_updates_existing_marker_block(self, tmp_path, capsys):
        target = tmp_path / "doc.md"
        target.write_text(
            f"# Doc\n{component_counts.START_MARKER}\nstale\n{component_counts.END_MARKER}\n",
            encoding="utf-8",
        )
        component_counts.write_targets(_SAMPLE, [target])
        text = target.read_text(encoding="utf-8")
        assert "stale" not in text
        assert "| 6 |" in text
        assert "updated" in capsys.readouterr().out

    def test_creates_default_target_when_missing(self, tmp_path, monkeypatch, capsys):
        fake_default = tmp_path / "docs" / "component-counts.md"
        monkeypatch.setattr(component_counts, "DEFAULT_TARGET", fake_default)
        component_counts.write_targets(_SAMPLE, [fake_default])
        assert fake_default.is_file()
        body = fake_default.read_text(encoding="utf-8")
        assert component_counts.START_MARKER in body
        assert "created" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# check_targets
# ---------------------------------------------------------------------------


class TestCheckTargets:
    @pytest.fixture(autouse=True)
    def _repo_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(component_counts, "REPO_ROOT", tmp_path)

    def test_ok_when_synced(self, tmp_path, capsys):
        target = tmp_path / "doc.md"
        target.write_text(f"# Doc\n{component_counts.render_table(_SAMPLE)}\n", encoding="utf-8")
        assert component_counts.check_targets(_SAMPLE, [target]) == 0
        assert "OK:" in capsys.readouterr().out

    def test_drift_when_stale(self, tmp_path, capsys):
        target = tmp_path / "doc.md"
        target.write_text(
            f"# Doc\n{component_counts.START_MARKER}\nstale\n{component_counts.END_MARKER}\n",
            encoding="utf-8",
        )
        assert component_counts.check_targets(_SAMPLE, [target]) == 1
        assert "DRIFT:" in capsys.readouterr().out

    def test_missing_target(self, tmp_path, capsys):
        target = tmp_path / "nope.md"
        assert component_counts.check_targets(_SAMPLE, [target]) == 1
        assert "MISSING:" in capsys.readouterr().out

    def test_no_markers(self, tmp_path, capsys):
        target = tmp_path / "doc.md"
        target.write_text("no markers at all", encoding="utf-8")
        assert component_counts.check_targets(_SAMPLE, [target]) == 1
        assert "NO MARKERS" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_json_output(self, capsys):
        assert component_counts.main(["--json"]) == 0
        import json

        parsed = json.loads(capsys.readouterr().out)
        assert set(parsed) == set(_SAMPLE)

    def test_default_table_output(self, capsys):
        assert component_counts.main([]) == 0
        assert component_counts.START_MARKER in capsys.readouterr().out

    def test_write_then_check_roundtrip(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(component_counts, "REPO_ROOT", tmp_path)
        target = tmp_path / "doc.md"
        target.write_text(
            f"# Doc\n{component_counts.START_MARKER}\nstale\n{component_counts.END_MARKER}\n",
            encoding="utf-8",
        )
        assert component_counts.main(["--write", str(target)]) == 0
        capsys.readouterr()
        assert component_counts.main(["--check", str(target)]) == 0

    def test_check_returns_1_on_drift(self, tmp_path, monkeypatch):
        monkeypatch.setattr(component_counts, "REPO_ROOT", tmp_path)
        target = tmp_path / "doc.md"
        target.write_text(
            f"{component_counts.START_MARKER}\nstale\n{component_counts.END_MARKER}\n",
            encoding="utf-8",
        )
        assert component_counts.main(["--check", str(target)]) == 1
