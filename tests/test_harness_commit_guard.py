"""`guard-harness-commit-guard.sh` — 하네스 실행 중 커밋 차단 훅의 가드.

## 왜 있나

`scripts/tools/guard_falsifiability.py` 는 워킹트리의 워크플로우·스크립트를
**제자리에서 덮어썼다 복원한다.** 그 사이에 `git add`/`commit` 을 하면 뮤테이션이
그대로 커밋에 들어간다.

2026-09-18 실측: `.github/workflows/dependabot-auto-merge.yml` 의
`if [ -n "$failed" ]; then` → `if false; then`(실패 체크 abort 무력화, fail-open)이
커밋됐다. **조용한 사고다** — 커밋 직후 워킹트리는 하네스가 복원하므로
`git status` 가 깨끗하고, 그 상태로 돌린 풀 스위트도 7577 passed 로 통과한다.
테스트도 트리도 정상인데 커밋 내용만 fail-open 이다.

하네스는 반대 방향(더러운 트리에서 **시작**)은 이미 막고 있었다. 이 훅이 나머지
방향을 막는다.

## 이 가드가 지키는 것

1. **살아 있는 락에는 막는다.** 안 막으면 훅이 있으나 마나다.
2. **stale 락에는 막지 않는다.** 이쪽이 더 중요하다 — 하네스는 SIGKILL 로 죽을
   수 있고(같은 날 메모리 압박으로 두 번), 살아있음을 안 보면 남은 락이 이후
   **모든 커밋을 영영 막는다.** 막으려던 사고보다 나쁜 고장이다.
3. **`git commit` 만 막는다.** 명령 위치 매칭이라 문자열 안의 언급은 통과하고
   `git -C <path> commit` 은 잡는다 — `pre-commit-state-guard.sh` 와 같은 규칙이다.

## liveness 검사가 커맨드라인이면 안 되는 이유

초판은 `ps -o command=` 에서 `guard_falsifiability` 를 찾았다. 그러면 **호출
방식에 의존한다** — `python3 -` 로 임포트해 락을 쥐면 커맨드라인에 스크립트
이름이 없어 자기 락을 stale 로 오판한다. 이 파일의 프로브가 그걸 잡아냈고,
프로세스 **시작 시각**(PID 재사용도 함께 구별된다)으로 바꿨다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "guard-harness-commit-guard.sh"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"

sys.path.insert(0, str(_REPO_ROOT / "scripts" / "tools"))

from guard_falsifiability import LOCK_PATH, read_active_lock  # noqa: E402

#: 훅이 거부할 때의 종료코드. Claude 훅 규약이다.
_DENY = 2


def _run_hook(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=60,
        check=False,
    )


@pytest.fixture
def no_lock():
    """락이 없는 상태를 보장하고, 테스트가 남긴 락도 치운다."""
    existing = LOCK_PATH.read_bytes() if LOCK_PATH.exists() else None
    LOCK_PATH.unlink(missing_ok=True)
    yield
    LOCK_PATH.unlink(missing_ok=True)
    if existing is not None:
        LOCK_PATH.write_bytes(existing)


def test_hook_is_registered_for_bash() -> None:
    """등록되지 않은 훅은 파일만 존재하고 아무것도 막지 않는다."""
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    commands = [
        hook.get("command", "")
        for matcher in settings.get("hooks", {}).get("PreToolUse", [])
        if matcher.get("matcher") == "Bash"
        for hook in matcher.get("hooks", [])
    ]
    assert any("guard-harness-commit-guard.sh" in c for c in commands), (
        f"훅이 PreToolUse/Bash 에 등록돼 있지 않다: {commands}. 파일만 있으면 실행되지 않으므로 아무것도 지키지 않는다."
    )


def test_hook_is_executable() -> None:
    assert os.access(_HOOK, os.X_OK), f"{_HOOK.name} 에 실행 권한이 없다"


def test_commit_is_allowed_without_a_lock(no_lock: None) -> None:
    """기준선 — 이게 없으면 아래 '막는다' 단언이 항상 참이어도 알 수 없다."""
    proc = _run_hook("git commit -m x")

    assert proc.returncode == 0, f"락이 없는데 커밋을 막았다: rc={proc.returncode}\n{proc.stderr}"


def test_commit_is_blocked_while_the_harness_holds_the_lock(no_lock: None) -> None:
    """살아 있는 홀더가 있으면 막아야 한다."""
    LOCK_PATH.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "start": _own_start_marker(),
                "started": time.time(),
            }
        ),
        encoding="utf-8",
    )

    proc = _run_hook("git commit -m x")

    assert proc.returncode == _DENY, (
        f"하네스가 락을 쥔 동안 커밋이 통과했다: rc={proc.returncode}. "
        f"뮤테이션이 커밋에 들어갈 수 있다.\n{proc.stdout}\n{proc.stderr}"
    )
    decision = json.loads(proc.stderr)["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny", f"거부 결정이 아니다: {decision!r}"


def test_a_stale_lock_does_not_block_forever(no_lock: None) -> None:
    """**이쪽이 더 중요하다.** 죽은 홀더의 락이 남아 모든 커밋을 막으면 안 된다.

    하네스는 SIGKILL 로 죽을 수 있다 — 2026-09-18 에 메모리 압박으로 두 번 죽었고,
    그때마다 락이 남았을 것이다. 그 상태로 영구 차단되면 막으려던 사고보다 나쁘다.
    """
    LOCK_PATH.write_text(
        json.dumps({"pid": 999_999, "start": "Thu Jan  1 00:00:00 2099", "started": 0}),
        encoding="utf-8",
    )

    proc = _run_hook("git commit -m x")

    assert proc.returncode == 0, (
        f"stale 락이 커밋을 막았다: rc={proc.returncode}. 죽은 홀더의 락은 무시돼야 한다.\n{proc.stderr}"
    )
    assert not LOCK_PATH.exists(), "stale 락이 치워지지 않았다 — 매 커밋마다 같은 비용을 낸다"


def test_liveness_check_does_not_depend_on_how_the_harness_was_started(no_lock: None) -> None:
    """자기 락을 자기가 stale 로 오판하면 훅이 조용히 아무것도 막지 않는다.

    초판은 `ps -o command=` 에서 스크립트 이름을 찾았다. 이 테스트 프로세스는
    `pytest` 로 떠 있어 그 이름이 없으므로, 그 구현에서는 위
    `test_commit_is_blocked_...` 가 통과해 버린다 — 즉 **판별력이 사라진다.**
    """
    LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "start": _own_start_marker(), "started": time.time()}),
        encoding="utf-8",
    )

    lock = read_active_lock()

    assert lock is not None, (
        "하네스가 아닌 이름으로 뜬 프로세스가 쥔 락을 stale 로 판정했다. "
        "liveness 검사가 호출 방식에 의존하면 안 된다 — 프로세스 시작 시각을 쓸 것."
    )
    assert lock["pid"] == os.getpid()


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("git commit -m x", True),
        ("git -C /repo commit -m x", True),
        ("git add -A && git commit -m x", True),
        ("git status", False),
        ("git log --grep='git commit'", False),
        ('echo "실행: git commit 할 것"', False),
    ],
)
def test_only_real_commit_commands_are_matched(no_lock: None, command: str, blocked: bool) -> None:
    """명령 위치 매칭. 부분문자열이면 문자열 안의 언급을 막고 `git -C … commit` 은 놓친다."""
    LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "start": _own_start_marker(), "started": time.time()}),
        encoding="utf-8",
    )

    proc = _run_hook(command)

    expected = _DENY if blocked else 0
    assert proc.returncode == expected, f"{command!r} 에 대해 rc={proc.returncode} (기대 {expected}).\n{proc.stderr}"


def _own_start_marker() -> str:
    proc = subprocess.run(
        ["ps", "-p", str(os.getpid()), "-o", "lstart="],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()
