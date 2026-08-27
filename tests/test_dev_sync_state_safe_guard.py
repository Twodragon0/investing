"""`scripts/dev_sync_state_safe.sh` 의 안전장치가 조용히 빠지지 않게 고정한다.

## 왜 있나

이 스크립트는 **파일을 되돌린다**(`git checkout --`). 되돌리는 대상이 `_state/*.json`
로 한정되는 것이 유일한 안전 근거이고, 그 한정이 사라지면 사용자의 작업물을 지운다.
그런데 그 사고는 **조용하다** — 스크립트는 성공으로 끝나고, 지워진 것은 git 에도
남지 않는다.

세 가지가 동시에 성립해야 안전하다:

1. `_state` 밖 dirty 파일이 있으면 **중단**한다. 이게 없으면 `git checkout --` 이
   무엇이든 되돌린다.
2. diff 가 큰 `_state` 파일은 `--force` 없이 되돌리지 않는다. 타임스탬프 한 줄
   bump 는 안전하지만 큰 diff 는 실제 내용일 수 있다.
3. 중간 실패 시 skip-worktree 를 **복구**한다. 안 하면 사용자 트리가 이 스크립트를
   실행하기 전보다 나쁜 상태(플래그 없음 = `git status` 가 _state 로 오염)로 남는다.

## 검사 방식

셸 스크립트이므로 파일 텍스트를 읽는다. 다만 **주석이 아니라 코드**를 봐야 한다 —
이 스크립트는 상단 주석에서 자기 안전장치를 설명하므로, 파일 전체를 검색하면 그
설명문에 매칭돼 무엇을 지우든 green 이 된다. 그래서 주석 줄을 먼저 제거한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "dev_sync_state_safe.sh"


def _code_only(text: str) -> str:
    """주석(`#` 으로 시작하는 줄)과 빈 줄을 제거한 코드 본문.

    heredoc 이 없는 스크립트라 줄 단위 제거로 충분하다. heredoc 이 추가되면 이
    함수가 그 안의 `#` 을 주석으로 오인하므로 함께 갱신할 것.
    """
    assert "<<" not in text, (
        "스크립트에 heredoc 이 추가됐다. _code_only() 가 heredoc 본문의 '#' 을 주석으로 "
        "오인해 코드를 지워버리므로, 이 헬퍼를 heredoc-aware 하게 고칠 것."
    )
    return "\n".join(ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def code() -> str:
    assert _SCRIPT.is_file(), f"{_SCRIPT} 가 없다"
    return _code_only(_SCRIPT.read_text(encoding="utf-8"))


def test_script_exists_and_is_executable() -> None:
    assert _SCRIPT.is_file(), f"{_SCRIPT} 가 없다 — 이 가드가 지킬 대상이 사라졌다"


def test_uses_strict_mode(code: str) -> None:
    assert "set -euo pipefail" in code, (
        "`set -euo pipefail` 이 없다. 이 스크립트는 되돌리기·pull 을 순서대로 하므로, "
        "중간 실패를 무시하고 진행하면 되돌린 뒤 pull 을 안 한 상태로 끝날 수 있다."
    )


def test_aborts_when_non_state_files_are_dirty(code: str) -> None:
    """가장 중요한 단언 — 이게 없으면 `git checkout --` 이 무엇이든 되돌린다."""
    assert "_state/*" in code, (
        "`_state/*` 경로 판정이 사라졌다. dirty 파일을 _state 안/밖으로 분류하는 것이 "
        "되돌리기 범위를 한정하는 유일한 근거다."
    )
    assert re.search(r"OUTSIDE\[@\]\}?\s*-gt\s*0", code) or "${#OUTSIDE[@]}" in code, (
        "_state 밖 dirty 파일이 있을 때 중단하는 분기가 없다. 그 분기가 없으면 이 "
        "스크립트는 사용자의 미커밋 작업을 조용히 지운다."
    )


def test_restores_only_state_files(code: str) -> None:
    """`git checkout --` 의 인자가 분류된 _state 목록이어야 한다."""
    checkouts = re.findall(r"git checkout -- (\S+)", code)
    assert checkouts, "되돌리기(`git checkout --`) 호출이 없다 — 스크립트가 목적을 잃었다"
    assert all("INSIDE" in c for c in checkouts), (
        f"되돌리기 대상이 분류된 _state 목록이 아니다: {checkouts}. "
        "`git checkout -- .` 이나 `-- _state/` 같은 광범위 인자는 금지 — 분류를 우회한다."
    )


def test_large_state_diff_requires_force(code: str) -> None:
    assert "MAX_STATE_DIFF_LINES" in code, (
        "diff 크기 상한이 사라졌다. 상한이 없으면 타임스탬프 bump 와 실제 내용 변경을 구분하지 않고 전부 버린다."
    )
    assert "FORCE" in code, "--force 우회 경로가 없다 — 상한이 있으면 우회 수단도 있어야 한다"


def test_restores_skip_worktree_on_failure(code: str) -> None:
    assert "restore_skip_worktree" in code, "실패 복구 함수가 없다"
    assert re.search(r"trap\s+'?restore_skip_worktree'?\s+ERR", code), (
        "ERR trap 이 없다. 중간 실패 시 skip-worktree 가 복구되지 않으면 사용자 트리가 "
        "실행 전보다 나쁜 상태(플래그 없음)로 남는다."
    )


def test_dry_run_unskips_so_it_can_actually_see_changes(code: str) -> None:
    """dry-run 이 un-skip 을 건너뛰면 변경을 못 보고 '버릴 것 없음' 으로 거짓 보고한다.

    개발 중 실제로 그렇게 만들었다가 발견한 결함이다. un-skip 은 인덱스 플래그만
    바꾸고 파일 내용은 건드리지 않으므로 dry-run 에서도 안전하다.
    """
    lines = [ln for ln in code.splitlines() if "update-index --no-skip-worktree" in ln]
    assert lines, (
        "un-skip 호출을 찾지 못했다. 이 스크립트는 skip-worktree 를 해제해야 로컬 변경을 "
        "볼 수 있다 — 해제가 없으면 판정 자체가 불가능하다."
    )
    # 복구 함수(restore) 쪽이 아니라 본문의 해제 호출을 본다.
    main_unskip = [ln for ln in lines if "SKIPPED[@]" in ln]
    assert main_unskip, f"본문의 un-skip 호출을 특정할 수 없다: {lines}"
    assert all("DRY_RUN" not in ln for ln in main_unskip), (
        "un-skip 이 DRY_RUN 조건에 걸려 있다. 그러면 dry-run 에서 skip-worktree 가 변경을 "
        "가려 `git diff` 가 비어 보이고, '버릴 것 없음' 이라고 거짓 보고한다."
    )
