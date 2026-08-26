"""component_counts 도구 회귀 가드.

docs/component-counts.md 가 실측과 드리프트되면 CI(pytest)에서 실패시켜
문서 수치가 코드와 어긋난 채 병합되는 것을 방지한다.
"""

from __future__ import annotations

import importlib.util
import re
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
        "main_push_workflows",
        "category_pages",
        "tests",
    }
    assert set(counts) == expected_keys
    for key, value in counts.items():
        assert isinstance(value, int), key
        assert value > 0, key


class TestMainPushWorkflows:
    """`main_push_workflows` 카운트가 서 있는 가정을 고정한다.

    이 수치는 `docs/devsecops/branch-protection.md` 가 Phase 2 마이그레이션 비용
    ("N개 푸시 지점 수정")으로 인용한다. 탐지는 휴리스틱이므로 — 공유 액션 참조
    또는 본문의 push 토큰 — 두 방향으로 조용히 틀릴 수 있다:

    * **과다 계수**: main 이 아닌 ref 로 푸시하는 워크플로우가 생기면 그것도 센다.
      그러면 비용 견적이 부풀고, "직접 푸시를 막으면 멈춘다" 는 서술이 과장된다.
    * **과소 계수**: 새 푸시 방식(다른 액션, `gh api` 로 커밋 생성 등)이 도입되면
      놓친다. 이쪽이 더 위험하다 — 브랜치 보호를 켰을 때 예상 밖으로 멈추는 잡이
      생긴다.

    과다 계수는 아래에서 단언으로 막는다. 과소 계수는 단언으로 막을 수 없으므로
    (모르는 방식을 열거할 수 없다) 탐지 토큰을 명시적으로 고정해서, 방식을 바꾸는
    사람이 이 테스트를 마주치게 한다.
    """

    def test_detects_a_plausible_number(self):
        hits = component_counts.main_push_workflows()
        total = component_counts._count_glob(".github/workflows/*.yml")
        assert 0 < len(hits) < total, (
            f"main 직접 푸시 워크플로우가 {len(hits)}/{total} 건이다. 0 이면 탐지가 "
            "깨진 것이고(공유 액션 이름이 바뀌었는지 확인), 전건이면 탐지가 너무 "
            "넓어진 것이다."
        )

    def test_every_match_targets_main(self):
        """명시적 `git push origin <ref>` 는 전부 main 이어야 한다."""
        pattern = re.compile(r"git\s+push\s+(?:\S+\s+)*?origin\s+(?:HEAD:)?(?P<ref>[A-Za-z0-9._/${}-]+)")
        offenders = []
        for path in component_counts.main_push_workflows():
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                ref = match.group("ref")
                if ref not in {"main", "HEAD"}:
                    offenders.append(f"{path.name} -> {ref}")

        assert not offenders, (
            f"main 이 아닌 ref 로 푸시하는 워크플로우가 카운트에 포함됐다: {offenders}. "
            "이 카운트는 'main 직접 푸시' 를 세는 것이므로 과다 계수다 — "
            "component_counts.main_push_workflows() 에서 제외 조건을 추가하거나, "
            "branch-protection.md 의 인용 맥락을 함께 고치라."
        )

    def test_detection_tokens_are_pinned(self):
        """탐지 토큰이 바뀌면 과소 계수가 조용히 생긴다 — 여기서 마주치게 한다."""
        assert component_counts.PUSH_ACTION == "actions/python-collect", (
            f"PUSH_ACTION 이 {component_counts.PUSH_ACTION!r} 로 바뀌었다. 이 상수는 대다수 "
            "워크플로우의 푸시 탐지 근거다(본문에 push 문자열이 없어 액션 참조로만 잡힌다) — "
            "공유 액션을 리네임했다면 여기와 test_shared_action_actually_pushes_to_main 의 "
            "경로를 함께 갱신하라."
        )
        assert set(component_counts.PUSH_MARKERS) == {"git push", "git-auto-commit-action"}, (
            "푸시 방식을 추가/변경했다면 PUSH_MARKERS 와 이 단언을 함께 갱신하고, "
            "docs/devsecops/branch-protection.md 의 마이그레이션 비용 서술도 다시 볼 것."
        )

    def test_shared_action_actually_pushes_to_main(self):
        """`PUSH_ACTION` 경유 계수의 근거가 실제로 성립하는지 확인한다.

        워크플로우 17건은 본문에 push 문자열이 없고 이 액션 참조로만 잡힌다. 액션이
        푸시를 그만두면 그 17건은 계수에서 빠져야 하는데, 참조만 보는 탐지는 계속
        센다.
        """
        action = component_counts.REPO_ROOT / ".github" / "actions" / "python-collect" / "action.yml"
        assert action.is_file(), f"{action} 이 없다 — PUSH_ACTION 경유 계수의 근거가 사라졌다"
        assert "git push origin main" in action.read_text(encoding="utf-8"), (
            "python-collect 액션이 더 이상 main 으로 푸시하지 않는다. 그렇다면 이 액션을 "
            "쓰는 워크플로우를 'main 직접 푸시' 로 세는 근거가 없다 — PUSH_ACTION 탐지를 "
            "제거하거나 조건을 고치라."
        )


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
    "main_push_workflows": 7,
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
