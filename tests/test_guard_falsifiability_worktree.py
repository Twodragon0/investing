"""하네스 워크트리 격리의 가드.

## 왜 있나

`guard_falsifiability.py` 는 오래 **메인 워킹트리의 파일을 제자리에서 덮어썼다
복원**했다. 그 구조가 사고 3종을 낳았다(전부 2026-09-18~19 실측):

| 사고 | 증상 |
|---|---|
| 실행 중 커밋 | 뮤테이션이 커밋에 들어감 — `if [ -n "$failed" ]` → `if false` (fail-open) |
| 스위트와 동시 실행 | bash 가 패치 중 스크립트를 이어 읽어 `exit 127` 유령 실패 |
| SIGKILL | 복원 실패 + git stat 캐시 잔상 |

첫 번째는 **조용한** 사고였다 — 복원 후 `git status` 가 깨끗하고 풀 스위트도
통과하므로 커밋 내용만 fail-open 이었다.

세 사고의 공통 원인은 하나다: **하네스와 사람이 같은 워킹트리를 공유한다.**
이제 일회용 linked worktree 에서 돌린다.

## 이 가드가 지키는 것

1. **기본 경로가 격리일 것.** `--in-worktree` 없이 부르면 워크트리를 만들어
   자식을 띄운다. 이게 뒤집히면 위 사고가 전부 돌아온다.
2. **폴백이 없을 것.** 워크트리를 못 만들면 메인 트리에서 조용히 진행하는 대신
   죽어야 한다. fail-open 은 이 저장소가 반복해 당한 형태다.
3. **메인 트리에서 뮤테이션이 시작되지 않을 것** — `_assert_running_in_worktree()`.
4. **미커밋 변경이 둘 다 이식될 것.** 추적 파일 변경(`git diff HEAD`)과
   **미추적 파일**(`git ls-files --others`). 후자를 빠뜨리면 "커밋된 것만 검증"
   과 같아진다 — 새 가드 테스트 파일이 정확히 미추적이라 전환의 목적이 사라진다.
5. **고아 워크트리가 쌓이지 않을 것.** SIGKILL 이 남긴 것을 다음 실행이 치운다.

## 판정은 합성 워크트리로 한다

메인 체크아웃만 보면 `is_linked_worktree()` 에 회귀를 넣어도 green 이다 — CI 도
메인 체크아웃에서 도므로 그대로면 아무것도 지키지 않는다. `--no-checkout` 워크트리는
0.3초면 만들어진다(`test_harness_commit_guard.py` 와 같은 수법).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import guard_falsifiability as gf
import pytest

_REPO_ROOT = Path(gf.__file__).resolve().parents[2]
_TOOL = _REPO_ROOT / "scripts" / "tools" / "guard_falsifiability.py"


@pytest.fixture
def synthetic_worktree(tmp_path: Path):
    """`--no-checkout` linked worktree. 파일이 필요 없는 검사에는 이걸로 충분하다."""
    path = tmp_path / "wt"
    created = subprocess.run(
        ["git", "worktree", "add", "-q", "--no-checkout", "--detach", str(path), "HEAD"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"worktree 를 만들지 못했다: {created.stderr.strip()}")
    try:
        yield path
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
        )
        subprocess.run(["git", "worktree", "prune"], cwd=_REPO_ROOT, capture_output=True, check=False)


# ---------------------------------------------------------------------------
# 1. linked worktree 판별
# ---------------------------------------------------------------------------


def test_main_checkout_is_not_a_linked_worktree() -> None:
    """대조군. 이게 없으면 아래 단언이 항상 참이어도 알 수 없다."""
    assert not gf.is_linked_worktree(_REPO_ROOT), (
        f"메인 체크아웃({_REPO_ROOT})을 linked worktree 로 판정했다. 그러면 메인 트리에서 뮤테이션이 그대로 진행된다."
    )


def test_a_linked_worktree_is_recognised(synthetic_worktree: Path) -> None:
    """판별이 거짓이면 3번 가드가 워크트리 실행을 막아 하네스가 아예 못 돈다."""
    assert gf.is_linked_worktree(synthetic_worktree), (
        f"linked worktree({synthetic_worktree})를 메인으로 판정했다. git-dir={gf.git_dir_for(synthetic_worktree)}"
    )


def test_assert_running_in_worktree_refuses_the_main_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """마지막 방벽. 메인 트리에서는 반드시 죽어야 한다."""
    monkeypatch.setattr(gf, "is_linked_worktree", lambda _root: False)

    with pytest.raises(SystemExit) as excinfo:
        gf._assert_running_in_worktree()

    assert "worktree" in str(excinfo.value), f"중단 사유가 워크트리를 지목하지 않는다: {excinfo.value}"


def test_assert_running_in_worktree_allows_a_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    """반대 방향. 항상 죽으면 하네스가 어디서도 못 돈다 — 위 테스트만으로는 못 본다."""
    monkeypatch.setattr(gf, "is_linked_worktree", lambda _root: True)

    gf._assert_running_in_worktree()  # 예외가 없어야 한다


def test_the_barrier_is_actually_called_before_mutating(tmp_path: Path) -> None:
    """**함수가 옳다는 것과 그 함수를 부른다는 것은 다르다.**

    위 두 테스트는 `_assert_running_in_worktree()` 를 **직접** 부른다. 그래서
    `run_all()` 안의 **호출부를 지우면 둘 다 green 이다** — 방벽이 사라졌는데
    아무도 모른다. 2026-09-22 에 실제로 그 상태였다(등록된 StaticCase 0건).

    ## 왜 합성 루트인가

    첫 설계는 `_REPO_ROOT` 에서 `--in-worktree` 를 실행했다. 그건 **주변 트리에
    의존한다** — 하네스는 워크트리 안에서 도므로 방벽이 통과해 rc=0 이 되고,
    하네스가 CONTROL-FAIL 을 냈다(2026-09-22 실측). 검증이 어디서 도느냐에 따라
    뒤집히는 테스트는 가드가 아니다.

    그래서 **git 저장소가 아닌 임시 디렉토리**에 도구만 복사해 거기서 돌린다.
    `REPO_ROOT` 는 스크립트 위치에서 파생되므로 그 임시 루트가 되고,
    `is_linked_worktree()` 는 확정적으로 False 다.

    ## 판별

    | | rc | stderr |
    |---|---|---|
    | 정상(방벽 있음) | ≠0 | 방벽 메시지 **있음** |
    | 변형(호출부 제거) | ≠0 (conftest 없음) | 방벽 메시지 **없음** |

    둘 다 죽으므로 **rc 만 보면 판별이 안 된다.** 메시지까지 봐야 한다.
    """
    root = tmp_path / "synthetic"
    (root / "scripts" / "tools").mkdir(parents=True)
    shutil.copy2(_TOOL, root / "scripts" / "tools" / _TOOL.name)
    # 모듈이 **임포트 시점에** 읽는 것. 없으면 방벽에 닿기도 전에 죽어서
    # 정상본과 변형이 같은 결과를 낸다(2026-09-22 에 실제로 그렇게 실패했다).
    shutil.copy2(_REPO_ROOT / "pyproject.toml", root / "pyproject.toml")

    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "tools" / _TOOL.name), "--in-worktree", "--json", "--shard", "99/99"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert proc.returncode != 0, (
        "git 저장소가 아닌 곳에서 `--in-worktree` 로 불렀는데 그냥 성공했다.\n"
        f"--- stdout ---\n{proc.stdout[:800]}\n--- stderr ---\n{proc.stderr[-800:]}"
    )
    assert "linked worktree 가 아니다" in proc.stderr, (
        "죽긴 했는데 **방벽 때문이 아니다.** `run_all()` 의 "
        "`_assert_running_in_worktree()` 호출부가 사라지면 하네스가 사람의 "
        f"워킹트리를 제자리에서 변형하기 시작한다.\n--- stderr ---\n{proc.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# 2. 기본 경로가 격리인가 — 실행으로 판정
# ---------------------------------------------------------------------------


def test_default_invocation_runs_in_a_worktree_not_the_main_tree() -> None:
    """`--in-worktree` 없이 부르면 **자식이 워크트리 안에서** 돈다.

    문자열로 `"worktree" in source` 만 보면 주석이나 죽은 분기도 만족시킨다.
    여기서는 실제로 프로세스를 띄워 자식이 보고한 `REPO_ROOT` 를 읽는다.

    `--shard 99/99`(빈 샤드)로 불러 실제 뮤테이션 비용을 치르지 않는다.
    """
    proc = subprocess.run(
        [sys.executable, str(_TOOL), "--json", "--shard", "99/99"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert proc.returncode == 0, f"기본 경로가 실패했다: rc={proc.returncode}\n{proc.stderr[-2000:]}"
    assert proc.stdout.strip().startswith("["), f"JSON 배열이 아니다: {proc.stdout[:200]!r}"

    # **직접 관측.** rc 만 보면 판별력이 없다 — 빈 샤드(99/99)는 뮤테이션이 없어서
    # 메인 트리에서 돌아도 rc=0 이고 트리도 안 바뀐다. 자식이 찍은 실행 위치를 읽는다.
    marked = [ln for ln in proc.stderr.splitlines() if gf._WORKTREE_MARKER in ln]
    assert marked, (
        f"자식이 실행 위치를 보고하지 않았다 — 워크트리 경로를 타지 않았을 수 있다.\nstderr:\n{proc.stderr[-2000:]}"
    )
    where = Path(marked[-1].split(gf._WORKTREE_MARKER, 1)[1].strip()).resolve()
    assert where != _REPO_ROOT.resolve(), (
        f"자식이 **메인 트리**에서 돌았다({where}). 격리가 깨졌다 — "
        "실행 중 커밋이 뮤테이션을 잡아먹는 사고가 그대로 돌아온다."
    )
    assert gf._WORKTREE_PREFIX in str(where), f"하네스 워크트리가 아닌 곳에서 돌았다: {where}"


def test_main_tree_is_untouched_by_a_run() -> None:
    """실행 전후로 뮤테이션 대상 파일이 **한 바이트도** 바뀌지 않아야 한다.

    옛 구조에서는 실행 *중* 에만 바뀌고 끝나면 복원됐다 — 그래서 사고가 조용했다.
    여기서는 끝난 뒤만 보지만, 실행 중 무손상은 워크트리 구조 자체가 보장한다
    (자식의 `REPO_ROOT` 가 워크트리다).
    """
    targets = [Path(p) for p in gf._mutated_files()][:8]
    before = {p: p.read_bytes() for p in targets if p.is_file()}
    assert before, "뮤테이션 대상이 하나도 없다 — 이 검사가 vacuous 하다"

    subprocess.run(
        [sys.executable, str(_TOOL), "--json", "--shard", "99/99"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    changed = [str(p.relative_to(_REPO_ROOT)) for p, blob in before.items() if p.read_bytes() != blob]
    assert not changed, f"실행이 메인 트리 파일을 바꿨다: {changed}"


def test_there_is_no_fallback_to_the_main_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """워크트리를 못 만들면 **죽어야 한다.** 메인 트리로 폴백하면 안 된다.

    폴백은 이 저장소가 반복해 당한 fail-open 형태다 — 조용히 옛 동작으로
    되돌아가고 아무도 모른다.
    """
    real_run = subprocess.run

    def fail_worktree_add(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:3] == ["git", "worktree", "add"]:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: 합성 실패")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(gf.subprocess, "run", fail_worktree_add)

    with pytest.raises(SystemExit) as excinfo:
        gf.run_via_worktree(["--json"])

    assert "워크트리" in str(excinfo.value), f"중단 사유가 워크트리 생성 실패를 지목하지 않는다: {excinfo.value}"


# ---------------------------------------------------------------------------
# 3. 미커밋 변경 이식 — 추적/미추적 **둘 다**
# ---------------------------------------------------------------------------


def _synthetic_repo(tmp_path: Path) -> Path:
    """일회용 git 저장소. **실제 레포에 쓰지 않는다.**

    첫 설계는 진짜 트리에 프로브 파일을 만들었다가 `_tree_write_guard` 에 걸렸다
    (2026-09-21). 그 가드가 옳다 — 트리 쓰기는 다른 테스트를 로컬 green / CI red
    로 갈라놓는다. 합성 저장소면 더 빠르고 더 정확하다.
    """
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "tracked.txt").write_text("original\n", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
    ):
        done = subprocess.run(cmd, cwd=src, capture_output=True, text=True, check=False, env={**os.environ, **env})
        if done.returncode != 0:
            pytest.skip(f"합성 저장소를 만들지 못했다: {' '.join(cmd)} -> {done.stderr.strip()}")
    return src


def _worktree_of(src: Path, dest: Path) -> Path:
    created = subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(dest), "HEAD"],
        cwd=src,
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"worktree 를 만들지 못했다: {created.stderr.strip()}")
    return dest


def test_untracked_files_are_ported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**이 테스트가 이 전환의 load-bearing 지점이다.**

    새 가드 테스트 파일은 미추적이라 `git diff HEAD` 에 **안 잡힌다.** 이식에서
    빠지면 새로 등록한 케이스가 워크트리에 존재하지 않아 실행조차 되지 않고,
    하네스는 "통과" 를 보고한다 — 이 하네스가 막으려는 바로 그 침묵이다.
    """
    src = _synthetic_repo(tmp_path)
    (src / "sub" / "brand_new_guard.py").write_text("# 새 가드\n", encoding="utf-8")
    monkeypatch.setattr(gf, "REPO_ROOT", src)
    worktree = _worktree_of(src, tmp_path / "wt-untracked")

    gf._port_uncommitted_changes(worktree)

    ported = worktree / "sub" / "brand_new_guard.py"
    assert ported.is_file(), (
        "미추적 파일이 워크트리로 이식되지 않았다. "
        "`git ls-files --others --exclude-standard` 경로가 빠지면 새 가드 테스트가 "
        "검증 대상에서 통째로 사라진다 — 하네스는 그걸 '통과' 로 보고한다."
    )
    assert ported.read_text(encoding="utf-8") == "# 새 가드\n"


def test_tracked_modifications_are_ported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """추적 파일 변경도 이식돼야 한다. 위 테스트의 짝 — 한쪽만으로는 절반이다."""
    src = _synthetic_repo(tmp_path)
    (src / "tracked.txt").write_text("original\nmodified\n", encoding="utf-8")
    monkeypatch.setattr(gf, "REPO_ROOT", src)
    worktree = _worktree_of(src, tmp_path / "wt-tracked")

    gf._port_uncommitted_changes(worktree)

    ported = (worktree / "tracked.txt").read_text(encoding="utf-8")
    assert "modified" in ported, (
        f"추적 파일의 미커밋 변경이 이식되지 않았다 — `git diff HEAD` 경로가 끊겼다. 내용: {ported!r}"
    )


def test_a_clean_tree_ports_nothing_and_does_not_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """대조군. 더러운 트리에서만 시험하면 '항상 무언가 쓴다' 는 구현도 통과한다."""
    src = _synthetic_repo(tmp_path)
    monkeypatch.setattr(gf, "REPO_ROOT", src)
    worktree = _worktree_of(src, tmp_path / "wt-clean")
    before = sorted(p.name for p in worktree.iterdir())

    gf._port_uncommitted_changes(worktree)

    assert sorted(p.name for p in worktree.iterdir()) == before, "깨끗한 트리인데 워크트리 내용이 달라졌다"
    assert (worktree / "tracked.txt").read_text(encoding="utf-8") == "original\n"


# ---------------------------------------------------------------------------
# 4. 고아 워크트리 정리
# ---------------------------------------------------------------------------


def test_created_worktree_is_recognised_by_the_pruner() -> None:
    """**생성과 정리를 묶는다.** 이게 이 파일에서 가장 중요한 단언일 수 있다.

    정리 로직은 `git worktree list` 가 주는 경로의 `.name` 에서 접두사를 찾는다.
    그런데 생성 쪽이 `mkdtemp(prefix=…) / "wt"` 였다 — 접두사가 **부모**에만 있고
    `.name` 은 `"wt"` 라서 **고아 정리가 한 번도 매치되지 않았다.**

    기존 고아 테스트는 이걸 못 잡았다. 고아를 `<prefix>orphan` 으로 직접 만들어
    **프로덕션과 모양이 달랐기** 때문이다. 손으로 만든 픽스처가 프로덕션 경로를
    대변하지 못한 전형적인 경우다.

    2026-09-23 SIGKILL 실측에서 드러났다 — 강제 종료 후 재실행해도 고아가 그대로
    남았다. 여기서는 **프로덕션이 실제로 만든 워크트리 경로**를 받아 정리 필터에
    그대로 먹여 본다.
    """
    with gf._disposable_worktree() as worktree:
        created = worktree

    assert gf._WORKTREE_PREFIX in Path(created).name, (
        f"프로덕션이 만든 워크트리 이름 {Path(created).name!r} 에 접두사 "
        f"{gf._WORKTREE_PREFIX!r} 가 없다. 정리 로직은 `.name` 만 보므로 "
        "SIGKILL 이 남긴 고아가 **영영 정리되지 않는다** — 매 실행마다 워크트리가 쌓인다."
    )


def test_orphan_harness_worktrees_are_pruned(tmp_path: Path) -> None:
    """SIGKILL 이 남긴 워크트리를 다음 실행이 치운다.

    `git worktree prune` 만으로는 부족하다 — 그건 **디렉토리가 이미 사라진** 등록만
    지운다. SIGKILL 은 디렉토리를 남기므로 이름으로 찾아 제거해야 한다.

    **합성 저장소를 쓴다.** 첫 설계는 실제 저장소를 상대로 돌렸고, 접두사 필터를
    뮤테이션한 프로브가 `.claude/worktrees/agent-*` **5개를 실제로 삭제했다**
    (2026-09-21). 커밋은 브랜치에 남아 무사했지만 미커밋 변경은 잃었다.
    파괴적 함수의 프로브는 절대 실제 트리를 겨냥하면 안 된다.
    """
    src = _synthetic_repo(tmp_path)
    orphan = tmp_path / f"{gf._WORKTREE_PREFIX}orphan"
    _worktree_of(src, orphan)
    assert orphan.exists(), "전제가 깨졌다 — 고아 워크트리가 만들어지지 않았다"

    gf._prune_orphan_worktrees(root=src)

    listed = subprocess.run(["git", "worktree", "list"], cwd=src, capture_output=True, text=True, check=False).stdout
    assert str(orphan) not in listed, f"고아 워크트리가 등록부에 남았다:\n{listed}"


def test_pruning_also_removes_the_leftover_directory(tmp_path: Path) -> None:
    """등록만 지우면 **디스크에 디렉토리가 남는다.**

    2026-09-23 SIGKILL 실측: `git worktree remove --force` 가 실패해도
    `git worktree prune` 이 등록을 지워 `git worktree list` 는 깨끗해진다. 그래서
    "정리됐다" 로 보이지만 `/tmp` 에 22k 파일짜리 체크아웃이 그대로 남는다.

    프로덕션과 **같은 모양**(부모·자식 둘 다 접두사)으로 만들어 검증한다.
    """
    src = _synthetic_repo(tmp_path)
    parent = tmp_path / f"{gf._WORKTREE_PREFIX}leftover"
    parent.mkdir()
    orphan = parent / f"{gf._WORKTREE_PREFIX}wt"
    _worktree_of(src, orphan)
    assert orphan.exists()

    gf._prune_orphan_worktrees(root=src)

    assert not parent.exists(), f"등록은 지웠지만 디렉토리 {parent} 가 남았다. 매 SIGKILL 마다 체크아웃 한 벌씩 쌓인다."


def test_pruning_never_touches_a_parent_without_the_prefix(tmp_path: Path) -> None:
    """**폭발 반경 제한.** 부모 이름 검사는 앞의 필터와 **독립**이어야 한다.

    실제 배치는 `.claude/worktrees/agent-<hex>` 다 — 부모가 `worktrees` 로,
    접두사가 없다. 부모 검사가 앞 필터에서 파생되면, 그 필터가 무력화됐을 때
    `.claude/worktrees/` 가 통째로 날아간다. 2026-09-21 에 에이전트 워크트리
    5개를 실제로 지운 적이 있어서 가정하지 않고 고정한다.
    """
    src = _synthetic_repo(tmp_path)
    shared_parent = tmp_path / "worktrees"
    shared_parent.mkdir()
    bystander = shared_parent / "agent-deadbeef"
    _worktree_of(src, bystander)
    # 같은 부모 아래에 하네스 워크트리를 둔다 — 부모는 접두사가 없다.
    harness = shared_parent / f"{gf._WORKTREE_PREFIX}wt"
    _worktree_of(src, harness)

    gf._prune_orphan_worktrees(root=src)

    assert shared_parent.exists(), f"접두사 없는 부모 {shared_parent} 를 지웠다 — 이웃 워크트리가 함께 날아간다"
    assert bystander.exists(), "하네스가 아닌 워크트리가 삭제됐다"


def test_pruning_spares_agent_worktrees(tmp_path: Path) -> None:
    """**반대 방향.** 접두사가 다른 워크트리는 건드리면 안 된다.

    실제 저장소에는 `agent-<hex>` 워크트리가 상주한다. 정리 로직이 그것까지 지우면
    진행 중인 에이전트 작업이 날아간다 — 막으려던 사고보다 나쁘다. 2026-09-21 에
    이 시나리오가 **가설이 아니라 실제로** 일어났다(위 테스트 docstring 참조).

    합성 저장소에서 검증하므로 이 테스트 자체는 아무것도 파괴하지 않는다.
    """
    src = _synthetic_repo(tmp_path)
    bystander = tmp_path / "agent-deadbeef"
    _worktree_of(src, bystander)

    gf._prune_orphan_worktrees(root=src)

    listed = subprocess.run(["git", "worktree", "list"], cwd=src, capture_output=True, text=True, check=False).stdout
    assert str(bystander) in listed, (
        f"하네스가 아닌 워크트리를 지웠다. 접두사 `{gf._WORKTREE_PREFIX}` 로만 좁힐 것.\n{listed}"
    )
    assert bystander.exists(), "디렉토리까지 삭제됐다 — 에이전트의 미커밋 작업이 날아가는 경로다"


def test_prune_defaults_to_the_real_repo_but_tests_must_not(tmp_path: Path) -> None:
    """`root` 인자가 **있어야** 한다. 없으면 프로브가 실제 저장소를 겨냥하게 된다.

    이 단언은 시그니처를 고정한다 — 기본값 하나뿐인 버전으로 되돌리면, 위 두
    테스트가 다시 실제 워크트리를 지우는 설계로 회귀한다.
    """
    import inspect

    params = inspect.signature(gf._prune_orphan_worktrees).parameters
    assert "root" in params, (
        "`_prune_orphan_worktrees` 에 `root` 인자가 없다. 그러면 파괴적 정리 로직의 "
        "프로브가 실제 저장소를 겨냥하고, 2026-09-21 의 에이전트 워크트리 삭제 사고가 재발한다."
    )
    assert params["root"].default is None, "기본값은 None 이어야 한다 (프로덕션은 REPO_ROOT 로 해소)"


def test_worktree_prefix_does_not_collide_with_agent_worktrees() -> None:
    """접두사가 `agent-` 와 겹치면 위 두 테스트가 서로 모순된다."""
    assert not gf._WORKTREE_PREFIX.startswith("agent-"), (
        f"하네스 접두사 {gf._WORKTREE_PREFIX!r} 가 에이전트 워크트리와 겹친다"
    )
    assert gf._WORKTREE_PREFIX, "접두사가 비면 모든 워크트리가 정리 대상이 된다"
