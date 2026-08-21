"""`component-counts-drift-guard.sh` 훅의 동작과 등록을 강제하는 가드.

## 이 훅이 존재하는 이유

2026-08-11 PR #1157·#1158 순차 머지에서 실제로 당했다. 두 브랜치가 각각 테스트 파일
1개를 더해 `docs/component-counts.md` 를 141→142 로 바꿨고, 리베이스의 3-way 머지가
두 번째 브랜치의 142→143 을 main 의 142 에 적용해 **143** 을 만들었다. 실제 값은 144.
충돌 마커도 에러도 없이 조용히 틀린 값이 남았다.

CI 의 `test_component_counts.py::test_generated_doc_in_sync` 가 최종 방어선이고 이
훅은 그 앞의 빠른 피드백이다.

## 훅 가드가 따로 필요한 이유

훅은 **등록되지 않으면 아무 일도 하지 않는다.** 스크립트가 완벽해도
`.claude/settings.json` 의 `PreToolUse`/`Bash` 배열에 빠져 있으면 조용히 죽어 있고,
그 실패는 다음 리베이스에서야 드러난다. 그래서 두 축을 함께 강제한다:

1. 등록 — settings.json 의 Bash 매처에 이 훅이 있다.
2. 동작 — 드리프트가 있으면 `git push` 를 deny 하고, 없으면 통과하며, push 가 아닌
   명령에는 개입하지 않는다.

`_run_hook` 은 실제 스크립트를 서브프로세스로 돌린다 — 셸 로직을 파이썬으로 다시
구현하면 그 구현만 검증하고 정작 훅은 검증하지 못한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _ROOT / ".claude" / "hooks" / "component-counts-drift-guard.sh"
_SETTINGS = _ROOT / ".claude" / "settings.json"

_HOOK_NEEDLE = "component-counts-drift-guard.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="훅은 bash + jq 를 요구한다",
)


def _run_hook(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """훅 스크립트를 실제로 실행한다. stdin 은 Claude Code 가 주는 형태."""
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# 등록 — 훅이 없으면 스크립트가 완벽해도 무의미하다
# ---------------------------------------------------------------------------


def test_hook_script_exists_and_is_executable():
    assert _HOOK.is_file(), f"훅 스크립트가 없다: {_HOOK}"


def test_hook_is_registered_for_bash_pretooluse():
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    bash_entries = [e for e in settings.get("hooks", {}).get("PreToolUse", []) if e.get("matcher") == "Bash"]
    assert bash_entries, "PreToolUse 에 Bash 매처가 없다"
    commands = [h.get("command", "") for e in bash_entries for h in e.get("hooks", [])]
    assert any(_HOOK_NEEDLE in c for c in commands), (
        f"{_HOOK_NEEDLE} 가 settings.json 의 Bash 훅에 등록되지 않았다. 등록된 훅: {commands}. "
        "등록이 빠지면 스크립트는 조용히 죽어 있고, 다음 리베이스에서야 드러납니다."
    )


# ---------------------------------------------------------------------------
# 동작 — 실제 스크립트를 돌린다
# ---------------------------------------------------------------------------


def _fake_repo(tmp_path: Path, *, drift: bool) -> Path:
    """component_counts.py 스텁을 둔 가짜 레포. --check 의 rc 로 드리프트를 흉내낸다."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tools = tmp_path / "scripts" / "tools"
    tools.mkdir(parents=True)
    rc = 1 if drift else 0
    msg = "DRIFT: docs/component-counts.md — --write 로 갱신 필요" if drift else "in sync"
    (tools / "component_counts.py").write_text(
        f"import sys\nprint({msg!r})\nsys.exit({rc})\n",
        encoding="utf-8",
    )
    return tmp_path


def test_hook_denies_push_on_drift(tmp_path):
    repo = _fake_repo(tmp_path, drift=True)
    result = _run_hook("git push origin main", repo)

    assert result.returncode == 2, f"드리프트인데 막지 않았다 (rc={result.returncode})"
    payload = json.loads(result.stderr)
    decision = payload["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "DRIFT" in decision["permissionDecisionReason"], "실제 도구 출력이 이유에 없다"
    assert "--write" in decision["permissionDecisionReason"], "해결 방법이 이유에 없다"


def test_hook_allows_push_when_synced(tmp_path):
    repo = _fake_repo(tmp_path, drift=False)
    result = _run_hook("git push origin main", repo)

    assert result.returncode == 0, f"동기화 상태인데 막았다: {result.stderr}"
    assert result.stderr.strip() == ""


def test_hook_ignores_non_push_commands(tmp_path):
    """드리프트가 있어도 push 가 아닌 명령에는 개입하지 않는다."""
    repo = _fake_repo(tmp_path, drift=True)
    for command in ("git status", "git commit -m x", "ls", "python3 -m pytest"):
        result = _run_hook(command, repo)
        assert result.returncode == 0, f"{command!r} 를 막았다: {result.stderr}"


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "docs: git push 훅 추가"',
        """echo '{"tool_input":{"command":"git push"}}'""",
        "grep -rn 'git push' docs/",
        'echo "실행: git push origin main"',
    ],
)
def test_hook_does_not_match_quoted_mentions(tmp_path, command):
    """문자열 안의 `git push` 언급에 걸리면 안 된다.

    부분문자열 매칭(`*"git push"*`)이던 초안이 실제로 이 훅을 만드는 도중
    `echo '{"command":"git push"}'` 를 차단했다. 커밋 메시지에 "git push" 를 쓰는
    것도 막혔다 — 이 훅 자체를 문서화하는 커밋이 그 형태다.
    """
    repo = _fake_repo(tmp_path, drift=True)
    result = _run_hook(command, repo)
    assert result.returncode == 0, f"인용된 언급을 막았다 {command!r}: {result.stderr}"


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "git push --force-with-lease",
        "cd /tmp/x && git push",
        "git status; git push -u origin feature",
        "git -C /repo push",
    ],
)
def test_hook_matches_real_push_forms(tmp_path, command):
    """실제 푸시 형태는 빠짐없이 잡아야 한다 — 좁히다가 새면 훅이 무의미해진다."""
    repo = _fake_repo(tmp_path, drift=True)
    result = _run_hook(command, repo)
    assert result.returncode == 2, f"실제 푸시를 놓쳤다 {command!r} (rc={result.returncode})"


def test_hook_reason_is_valid_json_with_newlines(tmp_path):
    """이유에 줄바꿈이 들어가므로 문자열 보간으로 JSON 을 만들면 깨진다."""
    repo = _fake_repo(tmp_path, drift=True)
    result = _run_hook("git push", repo)

    payload = json.loads(result.stderr)  # 깨졌으면 여기서 raise
    assert "\n" in payload["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_passes_when_tool_missing(tmp_path):
    """도구가 없는 레포(다른 워크스페이스)에서 푸시를 막아서는 안 된다."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = _run_hook("git push", tmp_path)
    assert result.returncode == 0, f"도구가 없는데 막았다: {result.stderr}"


def test_hook_denies_when_tool_errors(tmp_path):
    """도구가 깨진 경우도 막는다 — 에러를 통과로 위장시키지 않는다."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    tools = repo / "scripts" / "tools"
    tools.mkdir(parents=True)
    (tools / "component_counts.py").write_text("import sys\nsys.exit(2)\n", encoding="utf-8")

    result = _run_hook("git push", repo)
    assert result.returncode == 2, "도구가 exit 2 인데 통과시켰다"
    payload = json.loads(result.stderr)
    assert "exit 2" in payload["hookSpecificOutput"]["permissionDecisionReason"]
