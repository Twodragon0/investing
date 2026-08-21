"""`pre-commit-state-guard.sh` 의 명령 매칭과 출력 형식 가드.

## 고친 문제 두 개 (2026-08-12)

**1. 부분문자열 매칭.** 훅은 `[[ "$COMMAND" != *"git commit"* ]]` 로 판정했다. 문자열
안의 언급까지 걸려서 `_state` 가 staged 인 동안 다음이 전부 차단됐다 — 실측:

| 명령 | 기존 | 옳은 결과 |
|---|---|---|
| `git commit -m "x"` | rc=2 | rc=2 ✓ |
| `echo "실행: git commit -m x"` | rc=2 ❌ | rc=0 |
| `git log --grep="git commit"` | rc=2 ❌ | rc=0 |

`component-counts-drift-guard.sh` 가 같은 함정을 이미 겪었다(그 훅을 만드는 도중
`echo '{"command":"git push"}'` 가 차단됐다). 같은 명령-위치 매칭으로 통일한다.

**2. 깨진 JSON.** 이유 문자열을 셸 보간으로 JSON 에 넣는데, staged 목록은 `grep` 이
개행으로 구분해 준다. `_state` 파일이 **2개 이상이면 원시 개행이 문자열 안에 들어가
invalid JSON** 이 된다 — 실측:

```
Invalid control character at: line 1 column 202
```

이 세션에서 실제로 8개 파일이 staged 된 채 차단됐고, 그 출력이 깨진 JSON 이었다.
1개일 때는 우연히 유효해서 눈에 띄지 않는다 — 그래서 조용하다.

## 방향

블로킹 가드이므로 **양방향을 다 강제**한다. 좁히다 새면 `_state` 가 커밋되고(원래
막으려던 사고), 넓으면 무관한 명령이 막혀 사람이 훅을 끄게 된다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _ROOT / ".claude" / "hooks" / "pre-commit-state-guard.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="훅은 bash + jq 를 요구한다",
)


def _run_hook(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _repo(tmp_path: Path, *, staged_state: int = 0, staged_other: bool = False) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    if staged_state:
        (tmp_path / "_state").mkdir()
        for i in range(staged_state):
            (tmp_path / "_state" / f"f{i}.json").write_text("{}", encoding="utf-8")
        subprocess.run(["git", "add", "_state/"], cwd=tmp_path, check=True)
    if staged_other:
        (tmp_path / "note.md").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "note.md"], cwd=tmp_path, check=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 실제 커밋 형태는 빠짐없이 막는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        'git commit -m "여러 단어"',
        "git commit --amend --no-edit",
        "git commit -F -",
        "git -C /repo commit -m x",
        "git add . && git commit -m x",
        "git add .; git commit -m x",
    ],
)
def test_blocks_real_commit_forms(tmp_path, command):
    """좁히다 새면 `_state` 가 커밋된다 — 원래 막으려던 사고 그 자체."""
    repo = _repo(tmp_path, staged_state=2)
    result = _run_hook(command, repo)
    assert result.returncode == 2, f"실제 커밋을 놓쳤다 {command!r} (rc={result.returncode})"


# ---------------------------------------------------------------------------
# 문자열 안의 언급은 막지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'echo "실행: git commit -m x"',
        'git log --grep="git commit"',
        """echo '{"tool_input":{"command":"git commit"}}'""",
        'grep -rn "git commit" docs/',
        "git status",
        "git diff --cached",
        "ls _state/",
    ],
)
def test_does_not_block_mentions_or_other_commands(tmp_path, command):
    """넓으면 무관한 명령이 막혀 사람이 훅을 끄게 된다."""
    repo = _repo(tmp_path, staged_state=2)
    result = _run_hook(command, repo)
    assert result.returncode == 0, f"무관한 명령을 막았다 {command!r}: {result.stderr}"


# ---------------------------------------------------------------------------
# staged 조건
# ---------------------------------------------------------------------------


def test_allows_commit_when_no_state_staged(tmp_path):
    repo = _repo(tmp_path, staged_other=True)
    result = _run_hook("git commit -m x", repo)
    assert result.returncode == 0, f"_state 가 없는데 막았다: {result.stderr}"


def test_blocks_when_state_mixed_with_other_files(tmp_path):
    """콘텐츠와 섞여 있어도 `_state` 가 있으면 막는다."""
    repo = _repo(tmp_path, staged_state=1, staged_other=True)
    result = _run_hook("git commit -m x", repo)
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# 출력 형식 — 개행이 들어가도 유효한 JSON
# ---------------------------------------------------------------------------


def test_reason_is_valid_json_with_multiple_staged_files(tmp_path):
    """staged 목록은 개행 구분이다. 셸 보간으로 넣으면 2개 이상에서 invalid JSON 이 된다.

    1개일 때는 우연히 유효해서 눈에 띄지 않는다 — 그래서 조용한 실패다.
    """
    repo = _repo(tmp_path, staged_state=3)
    result = _run_hook("git commit -m x", repo)

    payload = json.loads(result.stderr)  # 깨졌으면 여기서 raise
    decision = payload["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert decision["hookEventName"] == "PreToolUse"


def test_reason_lists_staged_files_and_remedy(tmp_path):
    repo = _repo(tmp_path, staged_state=2)
    result = _run_hook("git commit -m x", repo)

    reason = json.loads(result.stderr)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "_state/f0.json" in reason and "_state/f1.json" in reason, f"staged 목록이 없다: {reason}"
    assert "git restore --staged" in reason, f"해결 방법이 없다: {reason}"
