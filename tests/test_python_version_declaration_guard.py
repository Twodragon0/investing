"""`.python-version` 이 실제 런타임 파이썬과 어긋나지 않게 고정한다.

## 왜 있나

이 파일은 사람이 읽으라고 있는 게 아니라 **Dependabot 이 읽으라고** 있다.

이 저장소의 실행 파이썬은 3.11 이다 — setup-python 선언 26곳 중 24곳(수집기 공통
액션 `.github/actions/python-collect/action.yml` 포함)이 3.11 이고,
`scripts/requirements.lock` 도 3.11 에서 생성한다(결정성 요구사항이라
`supply-chain-lock.yml` / `requirements-lock-sync.yml` 주석에 명시돼 있다).

2026-08-24 까지 그 제약을 선언한 파일이 하나도 없었다. `.python-version` ·
`runtime.txt` · `[project] requires-python` 전부 부재였고, `[tool.ruff]
target-version = "py311"` 은 ruff 전용이라 패키징 메타데이터가 아니다. 그래서
Dependabot 은 최신 파이썬 기준으로 해소해 **3.12+ 전용 버전을 제안했다**:

| numpy | `requires_python` | cp311 휠 |
|---|---|---|
| 2.4.4 / 2.4.6 | `>=3.11` | 11개 |
| 2.5.0 / 2.5.2 | `>=3.12` | **0개** |

PR #1209 (`numpy ~=2.4.4 → ~=2.5.2`) 는 락 재생성이 `DistributionNotFound` 로 죽어
닫혔다.

## `.python-version` 하나로는 부족하다 — 존중 여부를 관측할 수 없다

2026-08-26 실측으로 확정된 사실: `.python-version` 이 실제로 존중되는지 **확인할
방법이 없다.**

* #1209 를 닫자 Dependabot 이 *"won't notify you again about this release"* 라고
  응답했다. 같은 릴리스로는 재제안되지 않으므로 **"numpy PR 이 없다" 가 존중의
  증거가 못 된다**. 스케줄 런이든 수동 런이든 마찬가지다.
* 그 PR 의 head 브랜치를 Dependabot 이 삭제해서 `reopen`/`recreate` 로 억제를
  우회할 수도 없다(`gh pr reopen` → `Could not open the pull request`,
  `@dependabot reopen` → 무응답).
* 직접 의존성 23개를 PyPI 전수 조회한 결과 최신이 3.12 전용인 것은 **numpy 하나뿐**
  이다. 3.12 갭을 만들 대체 프로브가 없다.

그래서 2026-08-26 에 `[project] requires-python = ">=3.11,<3.12"` 로 승격했다.
Dependabot 이 파이썬 제약을 읽는 순서(dependabot-core `python_requirement_parser.rb`)
에서 `[project] requires-python` 은 **2위**, `.python-version` 은 4위다. 둘 다 두는
이유는 서로 다른 실패 모드를 덮기 때문이고, 그래서 **드리프트가 새 위험**이 된다.

## 이 가드가 지키는 것

1. `.python-version` 이 존재하고 `major.minor` 한 줄일 것.
2. 그 값이 **락을 만드는 파이썬** 및 **테스트를 돌리는 파이썬**과 일치할 것.
3. `[project] requires-python` 이 존재하고, 그 범위가 `.python-version` 에서
   기계적으로 파생되는 값(`>=X.Y,<X.(Y+1)`)과 정확히 일치할 것.

회귀는 조용하다. 3.12 로 마이그레이션하면서 워크플로우만 바꾸고 이 선언들을 잊으면
CI 는 전부 green 인 채로 Dependabot 만 3.11 기준으로 해소하기 시작한다 — 이번엔
반대 방향으로, 쓸 수 있는 버전을 제안하지 않는 형태로. 두 선언 모두 어떤 잡도 읽지
않으므로(모든 setup-python 이 버전을 명시한다) 틀려도 red 가 나지 않는다.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_VERSION_FILE = _REPO_ROOT / ".python-version"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: 워크플로우 -> 그 파일의 setup-python 이 이 저장소의 "런타임 파이썬"을 정의하는 이유.
_ANCHORS = {
    "supply-chain-lock.yml": "scripts/requirements.lock 을 생성/검증하는 파이썬. 다르면 해시 락이 재현되지 않는다.",
    "code-quality.yml": "테스트 스위트와 커버리지 게이트를 돌리는 파이썬.",
}


def _declared_version() -> str:
    assert _VERSION_FILE.exists(), (
        ".python-version 이 없다. 이 파일이 없으면 Dependabot 은 최신 파이썬 기준으로 "
        "해소해 3.12+ 전용 버전을 제안하고(numpy 2.5 → cp311 휠 0개), 그 PR 은 락 "
        "재생성에서 DistributionNotFound 로 죽은 뒤 매주 재생성된다."
    )
    lines = [ln.strip() for ln in _VERSION_FILE.read_text(encoding="utf-8").splitlines()]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    assert len(body) == 1, f".python-version 은 버전 한 줄이어야 한다 (got {body!r})"
    return body[0]


def _setup_python_versions(workflow: str) -> set[str]:
    wf = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return {
        str((step.get("with") or {}).get("python-version"))
        for job in (wf.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if "actions/setup-python" in str(step.get("uses", ""))
    }


def test_python_version_file_is_a_single_version() -> None:
    version = _declared_version()
    assert version.count(".") == 1 and all(p.isdigit() for p in version.split(".")), (
        f".python-version 은 `major.minor` 여야 한다 (got {version!r}). 패치까지 고정하면 "
        "러너의 패치 릴리스마다 이 가드가 낡는다."
    )


@pytest.mark.parametrize(("workflow", "why"), sorted(_ANCHORS.items()))
def test_declared_version_matches_the_runtime(workflow: str, why: str) -> None:
    declared = _declared_version()
    found = _setup_python_versions(workflow)

    assert found, f"{workflow} 에서 setup-python 스텝을 찾지 못했다 — 이 가드가 no-op 이 됐다"
    assert found == {declared}, (
        f".python-version={declared!r} 인데 {workflow} 는 {sorted(found)} 를 쓴다. {why} "
        "런타임을 옮겼다면 .python-version 도 함께 옮길 것 — 이 파일은 어떤 잡도 읽지 "
        "않으므로 어긋나도 CI 는 green 이고, Dependabot 만 조용히 틀린 기준으로 해소한다."
    )


def _expected_requires_python(declared: str) -> str:
    """`3.11` -> `>=3.11,<3.12`. 상한은 락이 그 마이너에 묶여 있다는 사실의 반영이다."""
    major, minor = (int(part) for part in declared.split("."))
    return f">={major}.{minor},<{major}.{minor + 1}"


def _project_table() -> dict:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project")
    assert project is not None, (
        "pyproject.toml 에서 `[project]` 테이블이 사라졌다. 이 테이블은 배포용이 아니라 "
        "**`requires-python` 을 선언하려고** 존재한다 — Dependabot 이 파이썬 제약을 읽는 "
        "순서에서 `[project] requires-python` 은 2위로 `.python-version`(4위)보다 우선한다. "
        "지우면 3.12+ 전용 패키지 제안을 막는 가장 강한 신호가 사라진다."
    )
    return project


def test_requires_python_is_declared() -> None:
    assert "requires-python" in _project_table(), (
        "`[project]` 는 있는데 `requires-python` 이 없다. 그 키가 이 테이블의 유일한 존재 "
        "이유이므로, 없으면 테이블만 남고 목적이 사라진 상태다."
    )


def test_requires_python_matches_python_version_file() -> None:
    declared = _declared_version()
    expected = _expected_requires_python(declared)
    actual = _project_table()["requires-python"]

    assert actual == expected, (
        f"`.python-version`={declared!r} 에서 파생되는 값은 {expected!r} 인데 "
        f"pyproject 는 {actual!r} 을 선언한다. 두 선언이 어긋나면 Dependabot 은 우선순위가 "
        "높은 pyproject 쪽을 따르므로, `.python-version` 만 고치고 여기를 잊으면 아무것도 "
        "바뀌지 않는다 — 그런데 CI 는 green 이다. 런타임을 옮길 때 둘을 함께 옮길 것."
    )


def test_upper_bound_excludes_the_next_minor() -> None:
    """상한이 빠지면 3.12+ 전용 패키지가 '3.11 사용자만 못 쓰는' 형태로 통과할 수 있다."""
    actual = _project_table()["requires-python"]
    assert "<" in actual, (
        f"requires-python={actual!r} 에 상한이 없다. 하한만 있으면 numpy 2.5.x 처럼 "
        '`requires_python = ">=3.12"` 인 패키지를 배제하는 근거가 약해진다 — 이 저장소의 '
        "락은 3.11 전용이므로 상한은 사실의 반영이지 과잉 제약이 아니다."
    )
