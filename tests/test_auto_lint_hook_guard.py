"""`auto-lint-python.sh` — 로컬 포맷 계층의 가드.

## 왜 있나

2026-09-19 조사: 이 저장소의 로컬에는 **포맷 계층이 한 층도 없었다.**

| 계층 | 상태 |
|---|---|
| pre-commit 의 `ruff-format` (`.pre-commit-config.yaml:44`) | `pre-commit install` 미실행이라 **안 돔** |
| 이 훅 | `ruff check --fix` 만 했다 |
| 수동 | 사람이 기억해야 함 |

`CLAUDE.md` 의 "format 누락이 흔한 CI red 원인" 이 정확히 이 구조다. CI 의
`ruff format --check` (`code-quality.yml:83`)는 잡아 주지만 그때는 이미 red 고,
포맷은 되돌릴 판단이 필요 없는 기계적 변환이라 red 로 알 이유가 없다.

## 이 가드가 지키는 것

1. `check --fix` 와 `format` 이 **둘 다** 실행될 것.
2. **순서** — `check --fix` 가 임포트 정렬 등을 고치면서 포맷을 깰 수 있으므로
   `format` 이 뒤여야 한다. `.pre-commit-config.yaml` 의 순서(:38 → :44)와 같다.
3. `.py` 가 아닌 파일에는 돌지 말 것.
4. **게이트가 아닐 것** — 항상 `exit 0`. 이건 편의 계층이고 진짜 게이트는 CI 다.
   여기서 편집을 막으면 ruff 가 없는 환경에서 작업이 멈춘다.

## 판정은 실행으로 한다

훅을 **실제로 돌려** 포맷이 적용됐는지 본다. 문자열로 `"ruff format" in script`
만 보면 주석에 적힌 이름이나 죽은 분기도 만족시킨다 — 이 저장소가 반복해서
겪은 실패다(메모 `feedback_guard_must_discriminate_not_just_red`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "auto-lint-python.sh"

#: 포맷이 필요한 파이썬. ruff 는 따옴표를 통일하고 줄을 정리한다.
_UNFORMATTED = "x = {  'a' :1,'b':2 }\n"


def _run_hook(file_path: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"file_path": str(file_path)}})
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
def ruff_required() -> None:
    if not shutil.which("ruff"):
        pytest.fail("ruff 가 없다 — 이 가드를 skip 하면 포맷 계층 검증이 통째로 사라진다")


def test_hook_formats_a_python_file(tmp_path: Path, ruff_required: None) -> None:
    """훅을 돌리면 파일이 **실제로 포맷된다.**

    `ruff check --fix` 만으로는 이 입력이 바뀌지 않는다 — 아래 대조 테스트가
    그걸 확인한다. 즉 이 단언은 `format` 단계가 있어야만 통과한다.
    """
    target = tmp_path / "sample.py"
    target.write_text(_UNFORMATTED, encoding="utf-8")

    proc = _run_hook(target)

    assert proc.returncode == 0, f"훅이 non-zero 로 끝났다: {proc.returncode}\n{proc.stderr}"
    after = target.read_text(encoding="utf-8")
    assert after != _UNFORMATTED, (
        f"훅이 포맷하지 않았다. 로컬에 포맷 계층이 없으면 CI 의 "
        f"`ruff format --check` 에서 red 로 알게 된다.\n결과: {after!r}"
    )
    assert after == """x = {"a": 1, "b": 2}\n""", f"ruff format 결과와 다르다: {after!r}"


def test_check_fix_alone_would_not_have_formatted_this_input(tmp_path: Path, ruff_required: None) -> None:
    """위 테스트의 판별력을 세우는 대조군.

    입력이 `check --fix` 만으로도 바뀐다면 위 단언은 `format` 유무를 구별하지
    못한다. 이 저장소가 반복해서 겪은 "red 는 나지만 그 속성 때문이 아닌" 함정이다.
    """
    target = tmp_path / "sample.py"
    target.write_text(_UNFORMATTED, encoding="utf-8")

    subprocess.run(["ruff", "check", "--fix", str(target)], capture_output=True, cwd=_REPO_ROOT, check=False)

    assert target.read_text(encoding="utf-8") == _UNFORMATTED, (
        "입력이 `check --fix` 만으로 바뀐다 — 위 테스트가 `format` 유무를 구별하지 못한다. "
        "포맷만 필요한 다른 입력으로 바꿀 것."
    )


def test_hook_ignores_non_python_files(tmp_path: Path, ruff_required: None) -> None:
    """`.py` 가 아니면 건드리지 않는다."""
    target = tmp_path / "notes.txt"
    original = "x = {  'a' :1 }\n"
    target.write_text(original, encoding="utf-8")

    proc = _run_hook(target)

    assert proc.returncode == 0
    assert target.read_text(encoding="utf-8") == original, "비-파이썬 파일을 건드렸다"


def test_hook_never_blocks_the_edit(tmp_path: Path) -> None:
    """게이트가 아니다 — 문법 오류가 있어도 `exit 0`.

    여기서 편집을 막으면 ruff 가 파싱하지 못하는 중간 상태를 저장할 수 없다.
    진짜 게이트는 CI 의 `ruff format --check` 다.
    """
    target = tmp_path / "broken.py"
    target.write_text("def f(:\n", encoding="utf-8")

    proc = _run_hook(target)

    assert proc.returncode == 0, (
        f"문법 오류에 훅이 편집을 막았다(rc={proc.returncode}). 이 훅은 편의 계층이지 "
        "게이트가 아니다 — 막으면 중간 상태를 저장할 수 없다."
    )


def test_format_runs_after_check_fix() -> None:
    """순서. `check --fix` 가 포맷을 깨뜨릴 수 있으므로 `format` 이 뒤여야 한다.

    `.pre-commit-config.yaml` 의 순서(:38 ruff → :44 ruff-format)와 같다.
    """
    script = _HOOK.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))

    check_at = body.find("ruff check --fix")
    format_at = body.find("ruff format")
    assert check_at != -1, "`ruff check --fix` 호출이 없다"
    assert format_at != -1, "`ruff format` 호출이 없다"
    assert check_at < format_at, (
        f"`ruff format`({format_at})이 `ruff check --fix`({check_at})보다 먼저다. "
        "check 가 임포트 정렬 등을 고치면서 포맷을 깰 수 있으므로 format 이 뒤여야 한다."
    )


#: `_state/` 커밋을 실제로 막는 스크립트. pre-commit 프레임워크 훅이 **아니다**.
_STATE_GUARD = ".claude/hooks/pre-commit-state-guard.sh"

#: `_state/` 차단을 설명하면서 주체를 잘못 적기 쉬운 문서들. 2026-09-19 에 5곳이
#: "pre-commit 훅이 차단한다" 고 적고 있었는데, `.pre-commit-config.yaml` 에는
#: `_state/` 를 막는 훅이 **애초에 없다**.
_STATE_BLOCK_DOCS = (
    ".github/CONTRIBUTING.md",
    "docs/state-friction-mitigation.md",
    "docs/architecture.md",
)


def test_pre_commit_config_really_has_no_state_hook() -> None:
    """아래 문서 단언의 전제. 언젠가 `_state/` 훅이 추가되면 문서를 되돌려야 한다.

    `_state` 라는 문자열의 **존재**만 보면 안 된다 — 현재 config 의 두 언급은
    `end-of-file-fixer`·`trailing-whitespace` 의 `exclude:` 패턴이라 `_state/` 를
    **막는 게 아니라 건너뛴다.** 정반대 의미다(2026-09-19 에 이 조잡한 탐지로 한 번
    틀렸다). `exclude:` 밖의 언급만 센다.
    """
    lines = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8").splitlines()
    blocking = [ln.strip() for ln in lines if "_state" in ln and not ln.lstrip().startswith(("exclude:", "#"))]

    assert not blocking, (
        f"`.pre-commit-config.yaml` 에 `exclude:` 가 아닌 `_state` 언급이 생겼다: {blocking}. "
        f"그 훅이 실제로 커밋을 막는다면 {list(_STATE_BLOCK_DOCS)} 의 "
        "'차단 주체는 Claude 훅' 서술을 다시 검토할 것 — 이 가드의 전제가 바뀐 것이다."
    )


@pytest.mark.parametrize("doc", _STATE_BLOCK_DOCS)
def test_state_blocking_docs_name_the_real_mechanism(doc: str) -> None:
    """`_state/` 차단을 설명하는 문서는 **실제 주체**를 지목해야 한다.

    2026-09-19 조사: 5개 문서가 "pre-commit 훅이 차단한다" 고 적었는데 두 겹으로
    틀렸다 — (a) 이 클론은 `pre-commit install` 이 안 돼 있고, (b) config 에
    `_state/` 훅이 **없다**. 실제 주체는 Claude 훅이다.

    안 도는 메커니즘을 근거로 안전을 주장하는 문서는, 읽는 사람이 자기 환경에서도
    막힐 것이라 믿게 만든다. 터미널 직접 커밋은 막히지 않는다.
    """
    text = (_REPO_ROOT / doc).read_text(encoding="utf-8")
    if "_state" not in text:
        pytest.skip(f"{doc} 가 더 이상 `_state/` 차단을 설명하지 않는다")

    assert _STATE_GUARD in text or "Claude 훅" in text, (
        f"{doc} 가 `_state/` 차단을 설명하면서 실제 주체를 지목하지 않는다. "
        f"`{_STATE_GUARD}`(Claude 훅)를 명시할 것 — `.pre-commit-config.yaml` 에는 "
        "그 훅이 없다."
    )


# ---------------------------------------------------------------------------
# CI 의 pre-commit 실행 — 10개 훅 전부의 **유일한** 강제 지점
# ---------------------------------------------------------------------------

_CODE_QUALITY = _REPO_ROOT / ".github" / "workflows" / "code-quality.yml"


def test_ci_runs_every_pre_commit_hook() -> None:
    """`pre-commit run --all-files` 스텝이 CI 에 살아 있어야 한다.

    2026-09-19 조사의 핵심 사실이다 — 이 클론은 `pre-commit install` 이 안 돼 있어
    `.pre-commit-config.yaml` 의 10개 훅이 **로컬에서 하나도 돌지 않는다.** 그런데도
    "검사 누락은 없다" 고 말할 수 있는 이유는 오직 이 한 줄 때문이다.

    즉 이 스텝이 사라지면 `gitleaks`·`detect-private-key`·`ruff-format`·
    `check-added-large-files` 등이 **어디서도** 돌지 않게 된다. 그런데 그 상태는
    조용하다 — 워크플로우는 계속 green 이고, 없어진 검사는 없어졌다고 말하지 않는다.

    조사 시점에 이 스텝을 지키는 가드는 **0건**이었다(`grep -rn "pre-commit run"
    tests/` → 없음). 이 저장소가 가드를 붙이는 관행에 비추면 눈에 띄는 공백이었다.

    `--all-files` 를 함께 요구한다. 그게 없으면 변경된 파일만 보는데, CI 는
    비교 기준이 되는 이전 리비전이 항상 있지 않아 **아무것도 검사하지 않을 수 있다.**
    """
    steps = ws.steps(_CODE_QUALITY)
    runs = [ws.strip_shell_comments(str(s.get("run") or "")) for s in steps if s.get("run")]
    hits = [r for r in runs if "pre-commit run" in r]

    assert hits, (
        "`pre-commit run` 스텝이 code-quality.yml 에서 사라졌다. 이 저장소는 "
        "`pre-commit install` 이 안 된 채로 운영되므로(2026-09-19 실측) 이 스텝이 "
        "10개 훅 전부의 **유일한** 강제 지점이다. 없어지면 gitleaks·detect-private-key·"
        "ruff-format 등이 어디서도 돌지 않는데, 워크플로우는 계속 green 이라 조용하다."
    )
    assert any("--all-files" in r for r in hits), (
        f"`pre-commit run` 에 `--all-files` 가 없다: {hits}. 변경 파일만 보면 비교 기준 "
        "리비전이 없을 때 아무것도 검사하지 않을 수 있다."
    )


def test_pre_commit_config_hook_count_is_pinned() -> None:
    """훅이 조용히 빠지는 것을 잡는다.

    위 테스트는 **스텝의 존재**만 본다 — config 에서 훅 하나가 사라져도 통과한다.
    개수를 고정해 삭제가 리뷰 대상이 되게 한다. 늘어나는 것도 red 이지만, 그건
    이 상수를 올리는 한 줄 편집이라 비용이 낮다.
    """
    config = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook_ids = [ln.strip() for ln in config.splitlines() if ln.strip().startswith("- id:")]

    assert len(hook_ids) == 10, (
        f"pre-commit 훅이 10개가 아니라 {len(hook_ids)}개다: {hook_ids}. "
        "줄었다면 그 검사는 이제 **어디서도** 돌지 않는다 — 로컬은 미설치이고 CI 는 "
        "이 config 를 그대로 실행하기 때문이다. 의도한 변경이면 이 숫자를 갱신할 것."
    )
