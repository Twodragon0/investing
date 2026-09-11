"""`tests/_workflow_scan.py` 자체의 테스트.

헬퍼가 조용히 느슨해지면 그걸 쓰는 가드 전부가 같이 느슨해진다. 여기서 양방향을
고정한다 — 주석을 걷어내되 실행되는 내용은 놓치지 않는다.

합성 입력만 쓴다. 저장소 파일에 의존하면 그 파일이 바뀔 때 이 테스트가 흔들리고,
헬퍼의 성질이 아니라 저장소의 현재 상태를 재는 테스트가 된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests import _workflow_scan as ws


class TestStripShellComments:
    def test_removes_whole_line_comments(self) -> None:
        assert ws.strip_shell_comments("# continue-on-error: true\necho hi") == "echo hi"

    def test_removes_trailing_comments(self) -> None:
        assert ws.strip_shell_comments("echo hi  # git push origin main").strip() == "echo hi"

    def test_keeps_hash_without_preceding_space(self) -> None:
        """URL 프래그먼트·색상코드처럼 `#` 이 값의 일부인 경우를 자르면 안 된다."""
        line = 'curl "https://example.com/a#frag"'
        assert ws.strip_shell_comments(line) == line

    def test_keeps_executable_content(self) -> None:
        run = "# 설명\ngit push origin main  # 주석\necho done"
        out = ws.strip_shell_comments(run)
        assert "git push origin main" in out
        assert "설명" not in out and "주석" not in out


class TestRunBlocks:
    def test_finds_workflow_and_composite_action_steps(self, tmp_path: Path) -> None:
        """워크플로우(`jobs.*.steps`)와 composite action(`runs.steps`) 둘 다."""
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "jobs:\n  j:\n    steps:\n      - name: A\n        run: echo a\n",
            encoding="utf-8",
        )
        action = tmp_path / "action.yml"
        action.write_text(
            "runs:\n  using: composite\n  steps:\n    - name: B\n      run: echo b\n",
            encoding="utf-8",
        )
        assert ws.run_blocks(wf) == [("A", "echo a")]
        assert ws.run_blocks(action) == [("B", "echo b")]

    def test_unnamed_step_is_labelled_not_blank(self, tmp_path: Path) -> None:
        wf = tmp_path / "wf.yml"
        wf.write_text("jobs:\n  j:\n    steps:\n      - run: echo a\n", encoding="utf-8")
        assert ws.run_blocks(wf)[0][0] == "<unnamed step>"

    def test_yaml_comments_never_reach_the_caller(self, tmp_path: Path) -> None:
        """YAML 주석은 파서가 버린다 — 이 성질에 의존하고 있으므로 고정한다."""
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "jobs:\n  j:\n    steps:\n"
            "      # continue-on-error: true 는 쓰지 않는다\n"
            "      - name: A\n        run: echo a\n",
            encoding="utf-8",
        )
        name, run = ws.run_blocks(wf)[0]
        assert "continue-on-error" not in run
        assert "continue-on-error" not in name


class TestStepText:
    def test_includes_step_level_settings(self, tmp_path: Path) -> None:
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "jobs:\n  j:\n    steps:\n      - name: A\n        continue-on-error: true\n        run: echo a\n",
            encoding="utf-8",
        )
        text = ws.step_text(ws.steps(wf)[0])
        assert "continue-on-error: True" in text or "continue-on-error: true" in text
        assert "echo a" in text

    def test_excludes_comments_inside_run(self, tmp_path: Path) -> None:
        """이게 `test_coverage_floor_guard` 가 false-red 였던 바로 그 경로다."""
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "jobs:\n  j:\n    steps:\n"
            "      - name: A\n        run: |\n"
            "          # continue-on-error: true 는 여기서 쓰지 않는다\n"
            "          coverage report --fail-under=86\n",
            encoding="utf-8",
        )
        text = ws.step_text(ws.steps(wf)[0])
        assert "continue-on-error" not in text, f"주석이 step_text 로 샜다:\n{text}"
        assert "--fail-under=86" in text


class TestOptOutMarkerIsStable:
    def test_marker_string_is_pinned(self) -> None:
        """메타 가드가 이 문자열을 찾는다 — 바꾸면 예외 선언이 전부 무효가 된다."""
        assert ws.RAW_TEXT_OPT_OUT == "scanner: raw-text intentional"


def test_helper_is_not_importable_as_a_test_module() -> None:
    """`_` 접두어라 pytest 가 테스트로 수집하지 않는다 — 헬퍼가 테스트로 오해되면
    수집 시간에 부작용이 생긴다."""
    assert Path(ws.__file__).name.startswith("_")


@pytest.mark.parametrize("bad", ["", "not: [valid", "jobs:\n  j:\n    steps: not-a-list\n"])
def test_malformed_input_does_not_crash_the_caller(bad: str, tmp_path: Path) -> None:
    """가드가 파싱 실패로 죽으면 '위반 없음' 과 구별되지 않는다."""
    wf = tmp_path / "wf.yml"
    wf.write_text(bad, encoding="utf-8")
    if bad == "not: [valid":
        # 파싱 불가는 **조용히 빈 결과**가 되면 안 된다. "위반 없음" 과 구별되지
        # 않아 가드가 vacuously green 이 된다. 호출자에게 터뜨린다.
        with pytest.raises(yaml.YAMLError):
            ws.run_blocks(wf)
    else:
        assert ws.run_blocks(wf) == []
