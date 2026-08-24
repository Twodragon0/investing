"""`supply-chain-lock.yml` 의 required-check 게이트 불변식 가드.

## 왜 있나

main 룰셋(`20539046`)에는 required status check 가 **하나도 없다**(2026-08-24 실측:
`deletion`, `non_fast_forward` 뿐). 그래서 `dependabot-auto-merge.yml` 의
`gh pr merge --auto` 는 기다릴 대상이 없고, stale 락이 사람 리뷰 없이 들어갈 수 있다
(설계 §5.3).

그 구멍을 막으려면 락 검증을 required 로 걸어야 하는데, `paths:` 필터가 걸린
워크플로우는 required 로 지정할 수 없다 — 무관 PR 에서는 체크가 **아예 생성되지 않아**
영구 대기가 된다. 그래서 구조를 바꿨다:

    changes (항상)  →  verify (관련 변경 시에만)  →  gate (항상, required 대상)

`guard-falsifiability.yml` 이 이미 쓰는 형태이며, 무거운 잡은 여전히 skip 된다.

## 이 가드가 지키는 것

세 가지가 동시에 성립해야 이 구조가 작동한다. 하나라도 깨지면 **조용히** 무력해진다:

1. `pull_request` 트리거에 `paths` 가 없을 것 — 있으면 required 지정 시 무관 PR 이
   영구 대기한다. 이건 CI 가 red 로 알려주지 않고 PR 이 그냥 멈춘다.
2. `gate` 가 `if: always()` 이고 `changes`·`verify` 를 모두 `needs` 할 것 — 아니면
   `verify` 실패가 `gate` 를 통과시킬 수 있다.
3. `gate` 가 fail-closed 일 것 — `changes` 가 실패하면 "관련 변경 없음" 을 신뢰할 수
   없다. 그걸 통과시키면 판정 잡 장애가 락 검증 면제로 위장한다.

추가로 경로 목록이 `push:` 트리거와 `changes` 잡 두 곳에 존재하므로 그 **드리프트**도
막는다. 드리프트는 텍스트 충돌을 만들지 않아 리뷰에서 놓치기 쉽고, 결과는 "락이
바뀌었는데 verify 가 skip" 이라는 최악의 방향이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "supply-chain-lock.yml"


@pytest.fixture(scope="module")
def raw() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(parsed: dict) -> dict:
    # PyYAML 1.1 은 bare `on:` 을 boolean True 로 읽는다(저장소 관례).
    return parsed.get("on", parsed.get(True))


def _gate_script(parsed: dict) -> str:
    for step in parsed["jobs"]["gate"]["steps"]:
        if step.get("run"):
            return step["run"]
    pytest.fail("gate 잡에 run 스텝이 없다")


class TestAlwaysReports:
    def test_pull_request_has_no_paths_filter(self, parsed: dict) -> None:
        pr = _triggers(parsed)["pull_request"]
        # `pull_request:` 만 있으면 값이 None 이다 — 그게 정상 상태.
        paths = (pr or {}).get("paths") if isinstance(pr, dict) else None
        assert not paths, (
            "pull_request 에 paths 필터가 생겼다. paths 로 걸러진 워크플로우를 required "
            "status check 로 지정하면 무관 PR 에서 체크가 생성되지 않아 **영구 대기** 한다. "
            "무거운 잡을 아끼려면 paths 대신 `changes` 잡의 판정으로 verify 를 skip 할 것."
        )

    def test_gate_job_exists(self, parsed: dict) -> None:
        assert "gate" in parsed["jobs"], "required check 대상인 gate 잡이 사라졌다"

    def test_gate_runs_unconditionally(self, parsed: dict) -> None:
        gate = parsed["jobs"]["gate"]
        assert str(gate.get("if")).strip() == "always()", (
            f"gate 는 if: always() 여야 한다(got {gate.get('if')!r}). 아니면 upstream 이 "
            "skip/fail 일 때 체크가 리포트되지 않아 required 로서 무의미해진다."
        )

    def test_gate_needs_both_upstream_jobs(self, parsed: dict) -> None:
        needs = parsed["jobs"]["gate"]["needs"]
        needs = [needs] if isinstance(needs, str) else list(needs)
        assert set(needs) == {"changes", "verify"}, (
            f"gate 의 needs 가 {needs} 다. changes·verify 를 모두 봐야 한다 — verify 만 "
            "보면 판정 잡 장애를 놓치고, changes 만 보면 검증 실패를 놓친다."
        )


class TestFailClosed:
    def test_changes_failure_blocks(self, parsed: dict) -> None:
        script = " ".join(_gate_script(parsed).split())
        assert 'if [ "${CHANGES_RESULT}" != "success" ]' in script, (
            "changes 가 성공하지 않았을 때 gate 가 실패해야 한다 — 판정 잡이 죽으면 "
            "'관련 변경 없음' 을 신뢰할 수 없고, 통과시키면 장애가 검증 면제로 위장한다."
        )

    def test_verify_failure_blocks(self, parsed: dict) -> None:
        script = " ".join(_gate_script(parsed).split())
        assert "failure|cancelled)" in script, (
            "verify 가 failure/cancelled 일 때 gate 가 실패해야 한다. cancelled 를 빼면 "
            "취소된 런이 통과로 읽힌다(이 워크플로우에서 이미 한 번 발생한 실패 모드)."
        )

    def test_skipped_verify_passes(self, parsed: dict) -> None:
        """skip 은 통과다 — 그게 조건부 실행의 의미다."""
        assert "skipped)" in " ".join(_gate_script(parsed).split())

    def test_unknown_result_blocks(self, parsed: dict) -> None:
        """새 결과 문자열이 생기면 통과가 아니라 실패로 떨어져야 한다."""
        script = " ".join(_gate_script(parsed).split())
        assert "예상하지 못한 결과" in script, (
            "case 의 기본 분기가 fail 이어야 한다. 기본이 통과면 GitHub 이 새 result 값을 "
            "도입할 때 게이트가 조용히 열린다."
        )


class TestVerifyStaysConditional:
    def test_verify_gated_on_changes(self, parsed: dict) -> None:
        verify = parsed["jobs"]["verify"]
        assert "changes" in ([verify["needs"]] if isinstance(verify["needs"], str) else verify["needs"])
        assert "needs.changes.outputs.relevant" in str(verify.get("if")), (
            "verify 가 changes 판정에 걸려 있지 않으면 모든 PR 에서 무거운 무결성 검증이 "
            "돌아 paths 필터 제거가 순수 비용 증가가 된다"
        )


class TestPathListDoesNotDrift:
    def test_push_paths_match_detect_targets(self, parsed: dict, raw: str) -> None:
        """경로 목록이 두 곳에 있다 — 어긋나면 락 변경이 skip 될 수 있다."""
        push_paths = set(_triggers(parsed)["push"]["paths"])

        # `changes` 잡 heredoc 안의 목록을 추출한다.
        detect = _gate_targets(raw)
        assert detect, "changes 잡의 TARGETS heredoc 을 찾지 못했다 — 추출 로직 확인"

        assert push_paths == detect, (
            "push 트리거의 paths 와 changes 잡의 판정 목록이 어긋난다.\n"
            f"  push 에만: {sorted(push_paths - detect)}\n"
            f"  detect 에만: {sorted(detect - push_paths)}\n"
            "detect 에서 빠진 경로는 그 파일만 바꾼 PR 에서 verify 가 skip 된다 — "
            "즉 락이 바뀌었는데 검증이 돌지 않는다."
        )


def _gate_targets(raw: str) -> set[str]:
    """`changes` 잡의 `TARGETS` heredoc 내용을 파싱한다."""
    lines = raw.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().endswith("<<'TARGETS'"))
    except StopIteration:
        return set()
    out: set[str] = set()
    for ln in lines[start + 1 :]:
        if ln.strip() == "TARGETS":
            break
        if ln.strip():
            out.add(ln.strip())
    return out
