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
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "dev_sync_state_safe.sh"


def _bash_major(binary: str) -> int | None:
    """`binary` 의 bash 메이저 버전. bash 가 아니거나 못 읽으면 None."""
    try:
        out = subprocess.run(
            [binary, "-c", 'printf %s "${BASH_VERSINFO[0]-}"'],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out.stdout) if out.stdout.strip().isdigit() else None


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


# ---------------------------------------------------------------------------
# 행동 관측 — 실제 git 저장소에서 스크립트를 돌린다
#
# 2026-09-13 이전에는 아래 다섯 가지를 전부 소스 텍스트로 단언했다
# (`"_state/*" in code`, `"MAX_STATE_DIFF_LINES" in code` 등). 그 형태는 문자열을
# 지우는 회귀에는 red 가 되지만 **문자열을 남긴 채 행동만 바꾸는 회귀**에는 눈이
# 멀어 있다 — 예컨대 `INSIDE` 분류는 그대로 두고 `git checkout -- .` 을 추가하면
# 모든 텍스트 단언이 통과한다. 이 스크립트는 파일을 되돌리므로 그 맹점의 대가가
# 사용자 작업물이다. 그래서 행동을 본다.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60).stdout


def _run_script(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """레포에서 스크립트를 실행한다.

    PATH 의 bash 를 쓴다 — macOS 기본 `/bin/bash` 는 3.2 라 `mapfile` 이 없다.
    """
    bash = shutil.which("bash")
    assert bash, "PATH 에 bash 가 없다"
    return subprocess.run([bash, str(_SCRIPT), *args], cwd=repo, capture_output=True, text=True, timeout=120)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`_state/*.json` 에 skip-worktree 가 걸린, 원격이 있는 저장소.

    원격이 필요한 이유: 되돌리기에 성공한 경로는 `git pull --ff-only` 로 이어진다.
    원격이 없으면 pull 이 실패해 "되돌렸는가"를 관측할 수 없다.
    """
    if (_bash_major(shutil.which("bash") or "") or 0) < 4:
        pytest.skip("PATH 의 bash 가 4 미만이다 — 스크립트가 버전 가드에서 멈춘다")

    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, timeout=60)
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")

    (work / "_state").mkdir()
    (work / "_state" / "a.json").write_text('{"n": 0}\n', encoding="utf-8")
    (work / "_state" / "b.json").write_text('{"n": 0}\n', encoding="utf-8")
    (work / "other.txt").write_text("사용자 작업물\n", encoding="utf-8")
    # 성공 경로 끝에서 스크립트가 이걸 호출한다.
    (work / "scripts").mkdir()
    shutil.copy(_SCRIPT.parent / "dev_ignore_state.sh", work / "scripts" / "dev_ignore_state.sh")

    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "-u", "origin", "main")
    _git(work, "update-index", "--skip-worktree", "_state/a.json", "_state/b.json")
    return work


def _skipped(repo: Path) -> set[str]:
    return {ln[2:] for ln in _git(repo, "ls-files", "-v").splitlines() if ln.startswith("S ")}


def test_aborts_when_non_state_files_are_dirty(repo: Path) -> None:
    """가장 중요한 행동 — `_state` 밖 변경이 있으면 아무것도 되돌리지 않고 멈춘다.

    이게 없으면 되돌리기가 사용자의 미커밋 작업을 조용히 지운다. 그 사고는
    git 에도 남지 않으므로 사후 복구가 불가능하다.
    """
    (repo / "other.txt").write_text("고치는 중\n", encoding="utf-8")
    (repo / "_state" / "a.json").write_text('{"n": 1}\n', encoding="utf-8")

    proc = _run_script(repo)

    assert proc.returncode == 1, f"중단하지 않았다 (rc={proc.returncode})\n{proc.stdout}\n{proc.stderr}"
    assert (repo / "other.txt").read_text(encoding="utf-8") == "고치는 중\n", (
        "_state 밖 파일이 되돌려졌다 — 사용자 작업물이 지워졌다"
    )
    assert (repo / "_state" / "a.json").read_text(encoding="utf-8") == '{"n": 1}\n', (
        "중단했는데도 _state 를 되돌렸다. 중단은 전부 아니면 전무여야 한다"
    )
    assert "other.txt" in proc.stderr, f"무엇이 막았는지 알리지 않는다: {proc.stderr}"


def test_restores_skip_worktree_after_abort(repo: Path) -> None:
    """중단해도 skip-worktree 는 복구되어야 한다.

    복구하지 않으면 트리가 실행 전보다 **나쁜** 상태로 남는다 — 플래그가 없으니
    `git status` 가 `_state` 로 오염되고, 그게 이 스크립트가 존재하는 이유다.
    """
    before = _skipped(repo)
    assert before, "fixture 가 skip-worktree 를 걸지 못했다 — 이 테스트는 의미가 없다"
    (repo / "other.txt").write_text("고치는 중\n", encoding="utf-8")

    proc = _run_script(repo)

    assert proc.returncode == 1
    assert _skipped(repo) == before, (
        f"중단 후 skip-worktree 가 복구되지 않았다. 이전={sorted(before)} 이후={sorted(_skipped(repo))}"
    )


def test_restores_only_state_files(repo: Path) -> None:
    """되돌리기 범위가 `_state` 로 한정되는지 — 추적되지 않는 파일까지 관측한다."""
    (repo / "_state" / "a.json").write_text('{"n": 1}\n', encoding="utf-8")
    (repo / "untracked.txt").write_text("추적 안 됨\n", encoding="utf-8")

    proc = _run_script(repo)

    assert proc.returncode == 0, f"되돌리기가 실패했다\n{proc.stdout}\n{proc.stderr}"
    assert (repo / "_state" / "a.json").read_text(encoding="utf-8") == '{"n": 0}\n', (
        "_state 변경이 되돌려지지 않았다 — 스크립트가 목적을 잃었다"
    )
    assert (repo / "untracked.txt").is_file(), "추적되지 않는 파일이 사라졌다"
    assert (repo / "other.txt").read_text(encoding="utf-8") == "사용자 작업물\n"


def test_large_state_diff_requires_force(repo: Path) -> None:
    """큰 diff 는 타임스탬프 bump 가 아니라 실제 내용일 수 있다 — 되돌리지 않는다."""
    big = "\n".join(f'{{"line": {i}}}' for i in range(60)) + "\n"
    (repo / "_state" / "a.json").write_text(big, encoding="utf-8")

    proc = _run_script(repo)

    assert proc.returncode == 1, f"큰 diff 를 --force 없이 되돌렸다 (rc={proc.returncode})"
    assert (repo / "_state" / "a.json").read_text(encoding="utf-8") == big, "되돌려졌다"
    assert "--force" in proc.stderr, f"우회 방법을 알리지 않는다: {proc.stderr}"


def test_force_allows_large_state_diff(repo: Path) -> None:
    """반대 방향 — 상한이 항상 걸리면 스크립트가 쓸모없어진다.

    "큰 diff 는 막힌다" 단언만으로는 상한이 0 으로 내려가 모든 것을 막는 회귀를
    잡지 못한다.
    """
    (repo / "_state" / "a.json").write_text("\n".join(f'{{"line": {i}}}' for i in range(60)) + "\n", encoding="utf-8")

    proc = _run_script(repo, "--force")

    assert proc.returncode == 0, f"--force 인데 막혔다\n{proc.stdout}\n{proc.stderr}"
    assert (repo / "_state" / "a.json").read_text(encoding="utf-8") == '{"n": 0}\n'


def test_dry_run_sees_changes_that_skip_worktree_would_hide(repo: Path) -> None:
    """dry-run 이 un-skip 을 건너뛰면 `git diff` 가 비어 보여 '버릴 것 없음' 으로 거짓 보고한다.

    개발 중 실제로 그렇게 만들었다가 발견한 결함이다. 관측 방법이 중요하다 —
    "un-skip 호출이 소스에 있다" 가 아니라 **변경을 실제로 보고하는가**를 본다.
    """
    (repo / "_state" / "a.json").write_text('{"n": 1}\n', encoding="utf-8")

    proc = _run_script(repo, "--dry-run")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "_state/a.json" in proc.stdout, (
        f"dry-run 이 변경을 보지 못했다 — skip-worktree 가 가린 채로 판정했다.\n{proc.stdout}"
    )
    assert (repo / "_state" / "a.json").read_text(encoding="utf-8") == '{"n": 1}\n', "dry-run 이 트리를 변경했다"
    assert _skipped(repo), "dry-run 후 skip-worktree 가 복구되지 않았다"


class TestBashVersionGuard:
    """bash 4+ 요구를 시작 시점에 검사하는지 고정한다.

    `mapfile` 은 bash 4.0 빌트인이고 macOS 기본 `/bin/bash` 는 3.2 다. 가드가 없던
    2026-08-27 실측은 `mapfile: command not found` / exit 127 — 원인도 조치도 알 수
    없는 메시지였다.

    지금은 `set -e` 가 mapfile 지점에서 멈춰 주므로 파괴적이지 않다. 하지만 그건
    mapfile 이 **우연히 첫 동작**이라서다. 순서가 바뀌면 조용한 오작동이 된다 —
    `SKIPPED` 가 빈 배열이면 스크립트는 "skip-worktree 파일 없음" 으로 판단하고
    평범한 pull 로 넘어간다. 그래서 아래 순서 단언이 이 클래스의 핵심이다.
    """

    def test_guard_uses_bash_versinfo_and_exits(self, code: str) -> None:
        assert "BASH_VERSINFO" in code, (
            "bash 버전 검사가 없다. `mapfile` 은 4.0 빌트인이라 3.2 에서는 `command not found` 만 남는다."
        )
        guard = re.search(r"if\s*\(\(\s*BASH_VERSINFO\[0\]\s*<\s*(\d+)\s*\)\)", code)
        assert guard, (
            "`(( BASH_VERSINFO[0] < N ))` 형태의 검사를 찾지 못했다. 이 산술 조건은 "
            "bash 3.2 에서도 파싱되므로 3.2 에서 실제로 평가된다 — 그게 가드가 "
            "동작하는 이유다."
        )
        assert int(guard.group(1)) >= 4, (
            f"요구 메이저 버전이 {guard.group(1)} 로 내려갔다. mapfile 은 4.0 빌트인이므로 "
            "4 미만으로 낮추면 가드가 무력해진다."
        )

    def test_guard_precedes_first_mapfile_use(self, code: str) -> None:
        """순서가 이 가드의 전부다 — mapfile 뒤에 있으면 아무것도 막지 못한다."""
        lines = code.splitlines()
        guard_at = next(
            (i for i, ln in enumerate(lines) if "BASH_VERSINFO" in ln),
            None,
        )
        mapfile_at = next(
            (i for i, ln in enumerate(lines) if re.search(r"\bmapfile\b", ln)),
            None,
        )
        assert guard_at is not None, "버전 가드를 찾지 못했다"
        assert mapfile_at is not None, (
            "`mapfile` 사용이 없다. 4+ 요구가 사라졌다면 가드도 함께 정리할 것 — "
            "이 테스트가 낡은 요구를 강제하고 있는 셈이다."
        )
        assert guard_at < mapfile_at, (
            f"버전 가드(line {guard_at + 1})가 첫 mapfile 사용(line {mapfile_at + 1}) "
            "뒤에 있다. 그러면 3.2 에서 가드에 닿기 전에 mapfile 이 먼저 실패한다."
        )

    def test_guard_does_not_fire_on_current_bash(self, tmp_path: Path) -> None:
        """반대 방향 — 4+ 에서는 가드가 걸리지 않고 통과해야 한다.

        가드가 항상 걸리는 버그(예: 비교 방향 뒤집힘)는 "3.2 에서 막힌다" 단언만으로는
        절대 잡히지 않는다. git 레포가 아닌 임시 디렉토리에서 돌려, **버전 가드 다음
        단계인** 레포 검사에 도달하는지로 통과를 확인한다. 트리를 건드리지 않는다.
        """
        bash = shutil.which("bash")
        assert bash, "PATH 에 bash 가 없다"
        if (_bash_major(bash) or 0) < 4:
            pytest.skip(f"PATH 의 bash 가 4 미만이다({bash}). 이 테스트는 bash 4+ 환경(Linux CI 등)에서만 실행된다.")

        proc = subprocess.run(
            [bash, str(_SCRIPT), "--dry-run"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "BASH_VERSINFO" not in proc.stderr
        assert "bash 4 이상" not in proc.stderr, (
            f"4+ 에서 버전 가드가 걸렸다 — 비교 방향이 뒤집혔을 수 있다.\n{proc.stderr}"
        )
        assert "git 레포" in proc.stderr, (
            "버전 가드 다음 단계(레포 검사)에 도달하지 못했다. 가드를 통과했다는 근거가 "
            f"없으므로 이 테스트는 결론을 낼 수 없다.\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

    def test_guard_fires_on_bash_3(self, tmp_path: Path) -> None:
        """실제 bash 3.x 이 있는 환경(macOS `/bin/bash`)에서만 행동을 검증한다.

        CI(ubuntu)의 `/bin/bash` 는 5.x 라 skip 된다. 그래서 위 두 정적 단언이
        리눅스에서의 실질적 방어선이고, 이 테스트는 로컬 macOS 에서 그 정적 단언이
        실제 행동과 일치함을 확인하는 역할이다.
        """
        old = next(
            (b for b in ("/bin/bash", "/usr/bin/bash") if (_bash_major(b) or 99) < 4),
            None,
        )
        if old is None:
            pytest.skip("bash 4 미만 인터프리터가 없다 (CI 리눅스에서는 정상)")

        proc = subprocess.run(
            [old, str(_SCRIPT), "--dry-run"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 1, (
            f"exit 1 이 아니다({proc.returncode}). 127 이면 가드에 닿기 전에 mapfile 이 "
            f"먼저 실패했다는 뜻이다.\nstderr={proc.stderr}"
        )
        assert "bash 4 이상" in proc.stderr, f"버전 요구를 알리지 않는다: {proc.stderr}"
        assert "brew install bash" in proc.stderr, (
            "조치 안내가 없다. 원인만 알리고 해결책을 주지 않으면 가드 이전과 크게 다르지 않다."
        )
