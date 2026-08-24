"""Dependabot pip 설정의 중복 커버리지 가드.

## 왜 있나

`.github/dependabot.yml` 에는 pip 항목이 둘 있었다 — `directory: "/scripts"` 와
`directory: "/"`. 그 분리는 다음 전제 위에 있었고, 주석으로도 그렇게 적혀 있었다:

> Dependabot 의 pip 디렉토리는 정확히 그 경로의 매니페스트만 읽으므로 …

**그 전제가 틀렸다.** `/` 는 하위 `requirements*.txt` 를 재귀 탐색한다. 2026-08-24
에 브랜치 접두사(`dependabot/pip/<pkg>` = `/` 출처, `dependabot/pip/scripts/<pkg>`
= `/scripts` 출처)와 실제 변경 파일을 대조한 결과:

| 출처 설정 | `requirements-dev.txt` 변경 | `scripts/requirements.txt` 변경 |
|---|---|---|
| `/` | 7건 | **7건** ← 중복 |
| `/scripts` | 0건 | 11건 |

`/` 가 `scripts/requirements.txt` 를 바꾼 PR: #1097 #1098 #1100 #1106 #1143
#1144 #1189.

증상은 정체 PR 이 두 배가 되는 것이었다. 같은 bump 가 두 브랜치로 열리고 둘 다
락 게이트에 걸린다 — #1184 와 #1189 가 그 쌍이다(동일 boto3 bump, 동일 파일,
서로 다른 prefix). prefix 로 런타임/개발을 구분하던 신호도 이미 깨져 있었다:
#1189 는 런타임 의존성을 바꾸면서 `chore(deps-dev):` 를 달았다.

## 이 가드가 지키는 것

pip 항목의 디렉토리 스코프가 서로 겹치지 않을 것. `/` 는 재귀적이므로 `/` 와 함께
다른 pip 디렉토리를 두면 정의상 중복이다.

이 회귀는 **조용하다** — 설정은 유효하고, Dependabot 은 경고하지 않으며, 중복 PR
각각은 정상적으로 보인다. 중복이라는 사실은 브랜치 접두사와 변경 파일을 대조해야
드러난다. 그래서 정적으로 잡는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _REPO_ROOT / ".github" / "dependabot.yml"


@pytest.fixture(scope="module")
def updates() -> list[dict]:
    parsed = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    return parsed["updates"]


def _pip_directories(updates: list[dict]) -> list[str]:
    dirs: list[str] = []
    for entry in updates:
        if entry.get("package-ecosystem") != "pip":
            continue
        # `directory` (단수) 또는 `directories` (복수, 신 문법) 둘 다 지원.
        if "directory" in entry:
            dirs.append(entry["directory"])
        for d in entry.get("directories", []):
            dirs.append(d)
    return dirs


def _normalize(directory: str) -> str:
    return "/" + directory.strip("/")


def test_pip_directory_scopes_do_not_overlap(updates: list[dict]) -> None:
    """`/` 는 재귀적이다 — 다른 pip 디렉토리와 공존하면 중복 커버리지다."""
    dirs = [_normalize(d) for d in _pip_directories(updates)]
    assert dirs, "pip 항목이 하나도 없다 — 파이썬 의존성이 Dependabot 커버리지 밖이다"

    overlaps: list[str] = []
    for outer in dirs:
        for inner in dirs:
            if outer == inner:
                continue
            # outer 가 inner 의 조상이면 outer 의 재귀 탐색이 inner 를 삼킨다.
            prefix = "/" if outer == "/" else outer + "/"
            if inner.startswith(prefix):
                overlaps.append(f"{outer!r} ⊇ {inner!r}")

    assert not overlaps, (
        "pip 항목의 디렉토리 스코프가 겹친다: "
        + ", ".join(sorted(set(overlaps)))
        + ". Dependabot 의 pip 은 하위 requirements*.txt 를 재귀 탐색하므로 "
        "상위 디렉토리 항목이 하위 항목을 삼켜 같은 bump 가 두 브랜치로 열린다 "
        "(2026-08-24 실측 7건: #1097 #1098 #1100 #1106 #1143 #1144 #1189). "
        "겹치는 항목 중 하나를 지울 것."
    )


def test_pip_entry_covers_every_requirements_manifest(updates: list[dict]) -> None:
    """중복을 없애다가 매니페스트를 커버리지 밖으로 떨어뜨리지 않게 한다.

    `/scripts` 항목을 지운 통합의 전제는 "`/` 가 재귀적이라 둘 다 커버한다" 다.
    그 전제가 깨지면(Dependabot 이 비재귀로 바뀌면) `scripts/requirements.txt`
    가 조용히 취약점 알림 밖으로 나간다. 여기서는 최소한 **선언된 스코프가 모든
    매니페스트를 포함하는지** 를 단언한다.
    """
    dirs = [_normalize(d) for d in _pip_directories(updates)]
    manifests = sorted(
        "/" + p.relative_to(_REPO_ROOT).as_posix() for p in _REPO_ROOT.glob("requirements*.txt") if p.is_file()
    ) + sorted(
        "/" + p.relative_to(_REPO_ROOT).as_posix()
        for p in (_REPO_ROOT / "scripts").glob("requirements*.txt")
        if p.is_file() and p.suffix == ".txt" and "lock" not in p.name
    )
    assert manifests, "requirements 매니페스트를 하나도 못 찾았다 — 글롭을 확인할 것"

    uncovered = []
    for manifest in manifests:
        parent = "/" + manifest.rsplit("/", 1)[0].strip("/")
        covered = any(parent == d or (d == "/" or parent.startswith(d + "/")) for d in dirs)
        if not covered:
            uncovered.append(manifest)

    assert not uncovered, (
        f"Dependabot pip 스코프 {dirs} 가 커버하지 않는 매니페스트: {uncovered}. "
        "그 파일의 의존성은 취약점 알림 밖에 있다."
    )
