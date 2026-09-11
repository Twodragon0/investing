"""메타 가드: 워크플로우의 **행동**을 판정하는 가드는 파싱된 값을 읽어야 한다.

## 왜 있나

이 저장소는 같은 결함으로 네 번 터졌다. 워크플로우 파일 원문을 문자열로 검색하면
실행되지 않는 산문(YAML 주석, `run:` 안의 셸 주석)에 매칭된다.

| 날짜 | 대상 | 방향 |
|---|---|---|
| 2026-09-02 (2건) | 워크플로우 가드 | false-red — 수정 설명 주석에 매칭 |
| 2026-09-10 | `component_counts.main_push_workflows()` | false-green — 주석 2건을 "직접 푸시" 로 계수 |
| 2026-09-11 | `test_coverage_floor_guard` | false-red — 금지를 적은 주석이 가드를 red 로 |

매번 개별로 고쳤고 매번 재발했다. 개별 수정은 다음 스캐너를 막지 못한다.

## 지키는 것

`.github/workflows` 를 읽으면서 **행동 토큰**(`continue-on-error`, `git push`,
`always()`, `exit 1` 등)을 찾는 테스트는 둘 중 하나여야 한다:

1. `tests/_workflow_scan.py` 를 쓴다 (파싱 + 주석 제거), 또는
2. 예외를 명시한다 — 파일에 `# scanner: raw-text intentional — <이유>`

## 왜 예외가 필요한가

주석 **자체가 검사 대상**인 가드가 있다.
`test_workflow_action_version_label_guard.py` 는 `uses: x@<sha>  # v1.2.3` 의
라벨이 업스트림 태그와 맞는지 본다 — 라벨은 주석이고, 그게 요점이다. 이런 가드에
파싱을 강요하면 검사 대상 자체가 사라진다.

예외를 **표식으로** 요구하는 이유는, 원문 읽기가 의도인지 실수인지 코드만 봐서는
구별되지 않기 때문이다. 표식이 있으면 그건 결정이고, 없으면 놓친 것이다.

## 이 가드의 한계

토큰 목록은 열거다 — 새로운 행동 토큰을 찾는 스캐너가 생기면 놓친다. 과소탐지
방향이므로 조용히 틀린다. 그래서 토큰 목록을 아래에 고정하고, 목록을 바꾸는
사람이 이 주석을 마주치게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

#: 워크플로우에서 "무엇을 실행/설정하는가" 를 묻는 토큰. 이것들을 원문에서 찾으면
#: 주석이 판정을 뒤집을 수 있다. 핀/라벨(`uses:`, `@sha`, `# v1.2.3`)은 일부러
#: 제외했다 — 그건 원문을 읽는 게 맞는 부류다.
_BEHAVIOURAL_TOKENS = (
    "continue-on-error",
    "git push",
    "git-auto-commit-action",
    "always()",
    "|| true",
    "set +e",
)

#: 헬퍼 자신과 그 테스트는 대상이 아니다.
_EXEMPT_FILENAMES = frozenset(
    {
        "_workflow_scan.py",
        "test_workflow_scan_helper.py",
        "test_workflow_scanner_convention_guard.py",
    }
)

_WORKFLOW_REF_RE = re.compile(r"\.github[/\\]workflows|WORKFLOWS_DIR|_WORKFLOW\b")


def _candidate_files() -> list[Path]:
    """워크플로우를 읽으면서 행동 토큰을 찾는 테스트 파일."""
    out: list[Path] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        if path.name in _EXEMPT_FILENAMES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _WORKFLOW_REF_RE.search(text):
            continue
        if not any(f'"{t}' in text or f"'{t}" in text for t in _BEHAVIOURAL_TOKENS):
            continue
        out.append(path)
    return out


def test_there_are_candidates_to_check() -> None:
    """후보가 0건이면 아래 검사는 아무것도 증명하지 않는다."""
    assert _candidate_files(), (
        "no workflow-scanning test matched the behavioural-token filter — either "
        "the filter broke or the scanners moved. A vacuous meta-guard is worse "
        "than none."
    )


@pytest.mark.parametrize("path", _candidate_files(), ids=lambda p: p.name)
def test_behavioural_scanners_read_parsed_content(path: Path) -> None:
    """불변식은 "내 헬퍼를 써라" 가 아니라 **"파싱된 내용을 읽어라"** 다.

    그래서 자체 `yaml.safe_load` 도 통과시킨다. 공유 헬퍼는 그 방법 중 하나일 뿐이고,
    이미 파싱하는 가드를 마이그레이션하라고 요구하는 것은 근거 없는 작업이다.

    **한계를 분명히 해 둔다.** 파일 안에 `yaml.safe_load` 가 한 번이라도 있으면
    통과하므로, 한 테스트는 파싱하고 다른 테스트는 원문을 훑는 혼합 파일을 잡지
    못한다. 파일 단위 판정의 한계이고, 함수 단위로 좁히려면 AST 분석이 필요하다 —
    지금은 그 복잡도를 지불할 근거(실측된 혼합 사례)가 없다. 나오면 그때 좁힌다.
    """
    text = path.read_text(encoding="utf-8")
    parses = "_workflow_scan" in text or "yaml.safe_load" in text
    opted_out = ws.RAW_TEXT_OPT_OUT in text
    assert parses or opted_out, (
        f"{path.relative_to(_REPO_ROOT)} scans workflows for behavioural tokens "
        f"using raw text.\n"
        f"A comment can flip the verdict in either direction — this repo has been "
        f"bitten four times (see this file's docstring).\n"
        f"Fix: use `tests/_workflow_scan.py`, or declare the exception with\n"
        f"    # {ws.RAW_TEXT_OPT_OUT} — <why>"
    )


def test_token_list_is_pinned() -> None:
    """토큰을 바꾸면 과소탐지가 조용히 생긴다 — 여기서 마주치게 한다."""
    assert set(_BEHAVIOURAL_TOKENS) == {
        "continue-on-error",
        "git push",
        "git-auto-commit-action",
        "always()",
        "|| true",
        "set +e",
    }, (
        "behavioural token list changed. Adding a token is fine (it widens the "
        "net); removing one narrows this meta-guard silently. Update this "
        "assertion deliberately."
    )
