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
닫혔고, 선언이 없는 한 매주 재생성된다.

## 이 가드가 지키는 것

`.python-version` 이 존재할 것, 그리고 그 값이 **락을 만드는 파이썬** 및 **테스트를
돌리는 파이썬**과 일치할 것.

회귀는 조용하다. 3.12 로 마이그레이션하면서 워크플로우만 바꾸고 이 파일을 잊으면
CI 는 전부 green 인 채로 Dependabot 만 3.11 기준으로 해소하기 시작한다 — 이번엔
반대 방향으로, 쓸 수 있는 버전을 제안하지 않는 형태로. `.python-version` 은 어떤
잡도 읽지 않으므로(모든 setup-python 이 버전을 명시한다) 틀려도 red 가 나지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_VERSION_FILE = _REPO_ROOT / ".python-version"

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
