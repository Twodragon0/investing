"""CI 인바리언트 가드: ruff 버전 핀 3곳 동기화.

배경(인시던트): code-quality.yml이 ruff를 unpinned(floating)로 설치해, 새 ruff 릴리스의
format 규칙 변경으로 코드 변경 없이 Code Quality가 이틀간 silently red였음(2026-06-10~12).
`ruff==0.15.8`로 핀하면서 핀이 3곳에 흩어짐 — 한 곳만 bump하고 나머지를 잊으면
로컬(pre-commit)·CI·requirements가 서로 다른 ruff를 써서 format 규칙 불일치 → 같은 red 재발.

이 가드는 **세 곳의 ruff 버전이 동일한지**만 검사한다(특정 값 고정이 아님 → ratchet/bump는
세 곳을 함께 올리면 통과). 한 곳만 어긋나면 실패하며, 메시지가 동기화 지점을 알려준다.

핀 3곳:
  1. .github/workflows/code-quality.yml   — `pip install ... ruff==X`
  2. requirements-dev.txt                 — `ruff==X`
  3. .pre-commit-config.yaml              — `astral-sh/ruff-pre-commit` 의 `rev: vX`

방향: 동등성(==). 의도적 bump 시 세 곳을 함께 갱신하면 그대로 통과한다.
stdlib-only(정규식 라인 스캔) — PyYAML 불필요, 측정 대상 소스를 import하지 않아 커버리지 무영향.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_QUALITY_YML = REPO_ROOT / ".github" / "workflows" / "code-quality.yml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

# 버전 토큰: 0.15.8 형태(major.minor.patch). pre-commit rev는 선행 v 허용.
_SEMVER = r"(\d+\.\d+\.\d+)"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _ruff_in_pip_install(text: str) -> str | None:
    """code-quality.yml의 `pip install ... ruff==X ...`에서 X 추출."""
    m = re.search(rf"\bruff=={_SEMVER}", text)
    return m.group(1) if m else None


def _ruff_in_requirements(text: str) -> str | None:
    """requirements-dev.txt의 `ruff==X` 라인에서 X 추출."""
    m = re.search(rf"(?m)^\s*ruff=={_SEMVER}\s*$", text)
    return m.group(1) if m else None


def _ruff_precommit_rev(text: str) -> str | None:
    """.pre-commit-config.yaml의 astral-sh/ruff-pre-commit repo 바로 뒤 `rev: vX`에서 X 추출.

    비탐욕 `.*?`로 ruff-pre-commit 직후 첫 rev만 매칭 → 다른 repo(gitleaks 등) rev와 혼동 방지.
    """
    m = re.search(
        rf"astral-sh/ruff-pre-commit\b.*?\brev:\s*v?{_SEMVER}",
        text,
        re.DOTALL,
    )
    return m.group(1) if m else None


# --- canary: 대상 파일이 옮겨지거나 사라지면 vacuous하게 통과하지 말고 실패 ---


def test_target_files_exist():
    assert CODE_QUALITY_YML.is_file(), f"{CODE_QUALITY_YML} not found"
    assert REQUIREMENTS_DEV.is_file(), f"{REQUIREMENTS_DEV} not found"
    assert PRE_COMMIT_CONFIG.is_file(), f"{PRE_COMMIT_CONFIG} not found"


def test_each_location_pins_ruff():
    """세 곳 모두 ruff 핀이 추출돼야 한다(누락 = floating 회귀 또는 가드 파손)."""
    assert _ruff_in_pip_install(_read(CODE_QUALITY_YML)), (
        "code-quality.yml에서 `ruff==X` 핀을 찾지 못함 — unpinned floating으로 회귀했거나 "
        "설치 라인이 바뀜. 핀을 유지하거나 이 가드의 추출 패턴을 갱신할 것."
    )
    assert _ruff_in_requirements(_read(REQUIREMENTS_DEV)), "requirements-dev.txt에서 `ruff==X`를 찾지 못함."
    assert _ruff_precommit_rev(_read(PRE_COMMIT_CONFIG)), (
        ".pre-commit-config.yaml의 astral-sh/ruff-pre-commit `rev: vX`를 찾지 못함."
    )


def test_ruff_versions_are_in_sync():
    """세 곳의 ruff 버전이 동일해야 한다. 불일치 시 format 규칙 드리프트로 CI red 위험."""
    ci = _ruff_in_pip_install(_read(CODE_QUALITY_YML))
    req = _ruff_in_requirements(_read(REQUIREMENTS_DEV))
    pc = _ruff_precommit_rev(_read(PRE_COMMIT_CONFIG))

    versions = {
        "code-quality.yml": ci,
        "requirements-dev.txt": req,
        "pre-commit ruff-pre-commit rev": pc,
    }
    distinct = {v for v in versions.values() if v}
    assert len(distinct) == 1, (
        "ruff 버전 핀이 3곳에서 불일치한다: "
        + ", ".join(f"{k}={v}" for k, v in versions.items())
        + ". format 규칙은 ruff 버전마다 다르므로 로컬(pre-commit)·CI·requirements가 같은 버전을 "
        "써야 한다. 버전 bump 시 .github/workflows/code-quality.yml, requirements-dev.txt, "
        ".pre-commit-config.yaml(ruff-pre-commit rev) 세 곳을 함께 갱신할 것."
    )
