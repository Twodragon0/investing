"""CI 인바리언트 가드: ruff 버전 핀의 단일 출처(SSoT).

## 배경 (인시던트)

`code-quality.yml` 이 ruff 를 unpinned 로 설치해, 새 ruff 릴리스의 format 규칙
변경만으로 코드 변경 없이 Code Quality 가 이틀간 silently red 였다
(2026-06-10~12). `ruff==X` 로 핀하면서 핀이 **3곳**에 흩어졌다.

## 왜 "3곳 동기화" 에서 "단일 출처" 로 바꿨나

이전 가드는 세 곳이 *같은지*만 봤다. 규율로 지키자는 설계였는데, 실측으로
두 번 실패했다:

* `code-quality.yml` 주석은 "여기에 버전 숫자를 다시 적지 말 것 — bump 마다
  낡는다. 2026-08-24 에 0.16.1→0.16.4 bump 후 실제로 낡은 채 남았다" 라고
  적어 놓고, 바로 아래 줄에 리터럴 핀을 두고 있었다.
* `.pre-commit-config.yaml` 주석은 "rev 는 로컬/CI ruff 버전(0.16.4)에 맞춤"
  이라고 적혀 있었지만 실제 rev 는 `v0.16.5` 였다.

더 중요한 건 **누가 막히느냐**다. Dependabot 의 pip 스캔은 매니페스트 파일만
본다 — `requirements-dev.txt` 하나만 올릴 수 있다. 그래서 이 가드는 모든 ruff
Dependabot PR 을 구조적으로 red 로 만들었다 (#1275 가 3일 정체). 가드가 회귀를
막은 게 아니라 정상 업데이트를 막고 있었다.

그래서 `code-quality.yml` 이 버전을 **적지 않고 읽도록** 바꿨다.

## 현재 상태: 핀 위치 2곳

| 위치 | 역할 |
|---|---|
| `requirements-dev.txt` | **SSoT.** Dependabot 이 편집하는 유일한 파일 |
| `.pre-commit-config.yaml` (`rev:`) | 파생 불가 — pre-commit `rev` 는 git ref 라 파일 참조가 안 된다 |

`code-quality.yml` 은 더 이상 버전을 적지 않고 SSoT 에서 읽는다.

pre-commit 은 아직 남아 있으므로 ruff bump 는 여전히 수동 개입 1회가 필요하다.
그걸 없애려면 원격 훅을 `repo: local` + `language: system` 으로 바꿔야 하는데,
그러면 pre-commit 이 ruff 를 자동 provisioning 하지 않게 되어 새 클론의 DX 가
나빠진다. 별건으로 남긴다.

## 이 파일이 지키는 것

1. SSoT 가 존재하고 핀되어 있을 것 (없으면 floating 회귀)
2. 워크플로우에 **리터럴 핀이 다시 생기지 않을 것** — 이게 뒤집힌 명제다.
   그냥 리터럴만 지우면 floating 설치로 조용히 회귀할 수 있으므로, 3번과
   짝이어야 의미가 있다
3. 워크플로우가 실제로 SSoT 에서 읽도록 **배선**되어 있을 것
4. pre-commit rev 가 SSoT 와 일치할 것

2·3번은 파일 원문이 아니라 **파싱된 `run:` 값**만 읽는다. 원문을 읽으면 이
설명이나 워크플로우 주석의 `ruff==` 가 스스로에게 매칭돼 항상 red 가 된다 —
이 저장소에서 두 번 발생한 실패 양식이다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CODE_QUALITY_YML = WORKFLOWS_DIR / "code-quality.yml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

_SEMVER = r"(\d+\.\d+\.\d+)"

# SSoT 파일명. 워크플로우가 여기서 핀을 읽어야 한다.
_SSOT_FILENAME = "requirements-dev.txt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _strip_shell_comments(run: str) -> str:
    """`run:` 안의 셸 주석을 제거한다.

    "파일 원문이 아니라 `run:` 값을 읽어라" 를 한 단계 더 밀어야 한다. `run:` 값
    **안**에도 주석이 있고, 그건 실행되지 않는 산문이다. 실측: 배선 검사가
    `# ... requirements-dev.txt 의 ruff== 와 ...` 라는 설명 주석에 매칭돼, 워크플로우가
    아직 리터럴 핀을 쓰고 있는데도 green 을 냈다.

    `#` 이 따옴표 안에 있을 수 있으므로(URL 프래그먼트 등) 줄 전체가 주석인 경우와
    공백 뒤 `#` 만 자른다 — 셸 파서를 흉내 내지는 않는다.
    """
    out = []
    for line in run.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(re.sub(r"\s+#(?=\s).*$", "", line))
    return "\n".join(out)


def _iter_run_blocks(node: object):
    """모든 중첩 깊이의 `run:` 문자열."""
    if isinstance(node, dict):
        run = node.get("run")
        if isinstance(run, str):
            name = node.get("name")
            yield (name if isinstance(name, str) else "<unnamed step>", run)
        for value in node.values():
            yield from _iter_run_blocks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_run_blocks(item)


def _workflow_run_blocks() -> list[tuple[Path, str, str]]:
    out: list[tuple[Path, str, str]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step_name, run in _iter_run_blocks(doc):
            out.append((path, step_name, _strip_shell_comments(run)))
    return out


def _ruff_in_requirements(text: str) -> str | None:
    m = re.search(rf"(?m)^\s*ruff=={_SEMVER}\s*$", text)
    return m.group(1) if m else None


def _ruff_precommit_rev(text: str) -> str | None:
    """`astral-sh/ruff-pre-commit` 바로 뒤의 첫 `rev: vX`.

    비탐욕 `.*?` 로 다른 repo(gitleaks 등) 의 rev 와 혼동하지 않는다.
    """
    m = re.search(rf"astral-sh/ruff-pre-commit\b.*?\brev:\s*v?{_SEMVER}", text, re.DOTALL)
    return m.group(1) if m else None


# --- canary: 대상이 사라지면 vacuous 하게 통과하지 말고 실패 ---


def test_target_files_exist() -> None:
    assert CODE_QUALITY_YML.is_file(), f"{CODE_QUALITY_YML} not found"
    assert REQUIREMENTS_DEV.is_file(), f"{REQUIREMENTS_DEV} not found"
    assert PRE_COMMIT_CONFIG.is_file(), f"{PRE_COMMIT_CONFIG} not found"


def test_workflows_have_run_blocks() -> None:
    """`run:` 이 0개면 아래 스캔 기반 검사들이 아무것도 증명하지 않는다."""
    assert _workflow_run_blocks(), "no `run:` blocks parsed from .github/workflows/ — the scan is vacuous"


# --- 1. SSoT 존재 ---


def test_ssot_pins_ruff() -> None:
    assert _ruff_in_requirements(_read(REQUIREMENTS_DEV)), (
        f"{_SSOT_FILENAME} 에서 `ruff==X` 를 찾지 못했다. 이 파일이 ruff 핀의 단일 "
        "출처다 — 핀이 사라지면 CI 가 floating ruff 를 설치해 2026-06-10 회귀가 "
        "재발한다."
    )


# --- 2. 리터럴 핀 재도입 금지 (뒤집힌 명제) ---


def test_no_literal_ruff_pin_in_any_workflow() -> None:
    offenders = [
        (path, step_name, m.group(0))
        for path, step_name, run in _workflow_run_blocks()
        if (m := re.search(rf"\bruff=={_SEMVER}", run))
    ]
    assert not offenders, (
        "워크플로우 `run:` 에 ruff 버전 리터럴이 다시 생겼다:\n"
        + "\n".join(f"  {p.relative_to(REPO_ROOT)} :: {s!r} -> {v}" for p, s, v in offenders)
        + f"\n버전은 {_SSOT_FILENAME} 한 곳에만 둔다. 워크플로우가 직접 적으면 "
        "Dependabot 이 그 파일을 못 건드리므로 모든 ruff bump PR 이 막힌다 (#1275)."
    )


# --- 3. 배선: 리터럴만 지우면 floating 회귀 ---


# `VAR="$( ... requirements-dev.txt ... )"` — SSoT 를 실제로 읽어 변수에 담는 형태.
# 파일명 언급만으로는 부족하다: 배선을 `RUFF_PIN=ruff` 로 바꾸는 변이를 넣었을 때,
# 아래 `echo "... requirements-dev.txt: $RUFF_PIN"` 한 줄 때문에 "파일명이 있으면
# 통과" 버전의 검사가 green 을 냈다. floating 설치로 회귀했는데도.
#
# `[^)]*` 로 닫는 괄호까지 매칭하려던 첫 시도는 실패했다 — 읽기 명령 자체가
# 정규식 캡처 그룹 `(...)` 을 담고 있어서 문자 클래스가 조기 종료했다. 괄호 균형을
# 맞추려 들지 말고 한 줄 안으로 스코프를 좁힌다.
_PIN_READ_RE = re.compile(rf"([A-Za-z_][A-Za-z0-9_]*)=\"?\$\([^\n]*{re.escape(_SSOT_FILENAME)}")


def test_code_quality_derives_the_pin_from_the_ssot() -> None:
    """2번과 짝. 리터럴 부재가 '핀 없음'을 뜻하지 않도록 읽기→사용을 끝단으로 단언한다."""
    for path, step_name, run in _workflow_run_blocks():
        if path != CODE_QUALITY_YML:
            continue
        match = _PIN_READ_RE.search(run)
        if not match:
            continue
        var = match.group(1)
        install_lines = [ln for ln in run.splitlines() if "pip install" in ln]
        assert any(f"${var}" in ln or f"${{{var}}}" in ln for ln in install_lines), (
            f"{step_name!r} reads the ruff pin from {_SSOT_FILENAME} into ${var}, but no "
            f"`pip install` line uses it:\n  " + "\n  ".join(install_lines) + "\n"
            "Reading the pin and not installing it is the same as not pinning."
        )
        return

    raise AssertionError(
        f"code-quality.yml 의 어떤 `run:` 도 {_SSOT_FILENAME} 을 명령 치환으로 읽지 "
        "않는다. 리터럴을 지우기만 하면 ruff 가 unpinned 로 설치돼 2026-06-10 의 "
        "silently-red 회귀가 그대로 돌아온다."
    )


def test_pin_read_failure_is_loud() -> None:
    """SSoT 에서 핀을 못 읽었을 때 조용히 floating 설치로 넘어가면 안 된다."""
    for _path, step_name, run in _workflow_run_blocks():
        if not _PIN_READ_RE.search(run):
            continue
        assert "exit 1" in run, (
            f"{step_name!r} reads the ruff pin from {_SSOT_FILENAME} but never fails "
            "when the read comes back empty. An empty pin would make `pip install` "
            "resolve ruff to latest — exactly the floating install this guard exists "
            "to prevent, and it would be green."
        )


# --- 4. pre-commit 도 SSoT 의 ruff 를 쓴다 (두 번째 핀 제거) ---


def _precommit_ruff_hooks() -> list[tuple[str, dict, dict]]:
    """(repo_url, repo_node, hook_node) — id 가 ruff / ruff-format 인 훅."""
    doc = yaml.safe_load(_read(PRE_COMMIT_CONFIG)) or {}
    out = []
    for repo in doc.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") in {"ruff", "ruff-format"}:
                out.append((str(repo.get("repo", "")), repo, hook))
    return out


def test_precommit_has_both_ruff_hooks() -> None:
    """lint 와 format 둘 다 있어야 한다 — format 누락이 2026-06-10 회귀의 원인이었다."""
    ids = {hook["id"] for _url, _repo, hook in _precommit_ruff_hooks()}
    assert ids == {"ruff", "ruff-format"}, f"expected both ruff hooks in pre-commit, found {sorted(ids) or 'none'}"


def test_precommit_ruff_has_no_second_version_pin() -> None:
    """`rev:` 로 버전을 다시 적으면 SSoT 가 둘이 된다.

    원격 `astral-sh/ruff-pre-commit` 훅은 `rev: vX` 를 요구하고, 그 `rev` 는 git ref
    라 파일에서 파생할 수 없다. 그래서 Dependabot 이 `requirements-dev.txt` 만 올릴
    때마다 로컬 훅이 다른 ruff 를 쓰게 된다 — #1275 가 막힌 이유의 나머지 절반이다.
    """
    assert _ruff_precommit_rev(_read(PRE_COMMIT_CONFIG)) is None, (
        "`astral-sh/ruff-pre-commit` 원격 훅이 `rev: vX` 로 두 번째 ruff 핀을 만든다. "
        f"버전은 {_SSOT_FILENAME} 한 곳에만 둔다 — 로컬 훅은 설치된 ruff 를 쓰도록 "
        "`repo: local` + `language: system` 으로 둘 것."
    )


def test_precommit_ruff_uses_the_installed_ruff() -> None:
    """`rev` 를 지우기만 하면 훅이 사라진 것과 같다 — 배선을 단언한다."""
    hooks = _precommit_ruff_hooks()
    assert hooks, "no ruff hook found in .pre-commit-config.yaml"
    for url, _repo, hook in hooks:
        assert url == "local", f"hook {hook['id']!r} still comes from remote repo {url!r}; expected `repo: local`"
        assert hook.get("language") == "system", (
            f"hook {hook['id']!r} has language={hook.get('language')!r}; `system` is what makes it "
            f"use the ruff installed from {_SSOT_FILENAME} instead of provisioning its own."
        )
        entry = str(hook.get("entry", ""))
        assert "ruff" in entry, f"hook {hook['id']!r} entry={entry!r} does not invoke ruff"
        assert not re.search(_SEMVER, entry), (
            f"hook {hook['id']!r} entry={entry!r} contains a version literal — that is a second pin again."
        )
