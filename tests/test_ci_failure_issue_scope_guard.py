"""CI-failure 이슈를 **기본 브랜치 실패에만** 여는지 고정한다.

## 왜 있나

`classify-workflow-failures.yml` 은 원래 브랜치를 가리지 않고 `code` 분류 실패마다
이슈를 열었다. 그런데 PR 브랜치의 실패는 **그 PR 위에 빨간 체크로 이미 보이고**,
대개 같은 PR 안에서 고쳐진다. 그때 이슈는 남아 `close-stale` 의 30일 기한까지
방치된다.

2026-09-17 전수 실측 — 열린 `ci-failure` 이슈 24건 중:

| 판정 | 건수 | 뜻 |
|---|---|---|
| 현재 main 에 도달한 커밋 | 3 | 진짜 신호 후보 |
| main 에 도달하지 못한 커밋 | **21 (88%)** | 같은 PR 에서 고쳐졌거나 브랜치가 버려짐 |

즉 트래커의 88%가 노이즈였고, 진짜 신호 3건이 그 속에 묻혀 있었다. 노이즈가 많은
트래커는 아무도 보지 않으므로, 이 필터가 빠지면 트래커 자체가 무력해진다 — 그리고
그 무력화는 **조용하다**(이슈는 계속 열리니 동작하는 것처럼 보인다).

## 이 가드가 지키는 것

1. 이슈 생성이 기본 브랜치로 한정돼 있을 것.
2. 그 조건이 **이슈 생성 스텝에만** 걸려 있을 것 — 네트워크 실패 자동 재실행은
   PR 에서도 유용하므로 브랜치를 가리면 안 된다. 한쪽만 맞고 다른 쪽이 틀리면
   "고쳤다" 고 믿으면서 재실행 편익을 잃는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "classify-workflow-failures.yml"

#: 기본 브랜치 판정에 쓸 수 있는 표현. 리터럴 `'main'` 하드코딩은 받지 않는다 —
#: 기본 브랜치 이름이 바뀌면 조용히 항상-false 가 되어 이슈가 하나도 안 열린다.
_DEFAULT_BRANCH_EXPR = "github.event.repository.default_branch"


@pytest.fixture(scope="module")
def parsed() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _steps(parsed: dict) -> list[dict]:
    return ws.steps(_WORKFLOW) or [s for job in parsed["jobs"].values() for s in job.get("steps", [])]


def _step_named(parsed: dict, needle: str) -> dict:
    hits = [s for s in _steps(parsed) if needle in str(s.get("name", ""))]
    assert len(hits) == 1, (
        f"이름에 {needle!r} 를 포함하는 스텝이 정확히 1개여야 한다(현재 {len(hits)}개). "
        "이름을 바꿨다면 이 가드도 함께 갱신할 것 — 아니면 조용히 아무것도 지키지 않는다."
    )
    return hits[0]


def test_issue_creation_is_scoped_to_the_default_branch(parsed: dict) -> None:
    gate = str(_step_named(parsed, "Create issue")["if"])
    assert _DEFAULT_BRANCH_EXPR in gate, (
        f"이슈 생성이 기본 브랜치로 한정돼 있지 않다: {gate!r}. PR 브랜치 실패까지 "
        "이슈가 열리면 트래커의 대부분이 노이즈가 되고(2026-09-17 실측 88%), "
        "진짜 main 회귀가 그 속에 묻힌다."
    )
    assert "head_branch" in gate, (
        f"비교 대상이 `workflow_run.head_branch` 가 아니다: {gate!r}. 다른 필드를 쓰면 "
        "PR 컨텍스트에서 의도와 다르게 평가될 수 있다."
    )


def test_gate_does_not_hardcode_the_branch_name(parsed: dict) -> None:
    """리터럴 이름을 박으면 기본 브랜치 개명 시 **이슈가 하나도 안 열린다.**

    그 방향의 고장은 red 를 내지 않아 다음 main 회귀를 놓칠 때까지 드러나지 않는다.
    """
    gate = str(_step_named(parsed, "Create issue")["if"])
    assert "'main'" not in gate and '"main"' not in gate, (
        f"기본 브랜치 이름이 리터럴로 박혀 있다: {gate!r}. {_DEFAULT_BRANCH_EXPR} 를 쓸 것."
    )


def test_network_rerun_is_not_branch_scoped(parsed: dict) -> None:
    """재실행까지 기본 브랜치로 좁히면 PR 의 일시적 네트워크 실패를 사람이 손으로 돌려야 한다.

    이슈 노이즈를 고치면서 이쪽까지 좁히기 쉬운데, 그러면 "고쳤다" 고 믿으면서
    편익 하나를 잃는다. 두 스텝의 조건이 **서로 다른지**를 단언한다.
    """
    rerun = [s for s in _steps(parsed) if "rerun" in str(s.get("id", "")) or "Rerun" in str(s.get("name", ""))]
    assert rerun, "재실행 스텝을 찾지 못했다 — 이 가드가 대상을 잃었다"
    for step in rerun:
        gate = str(step.get("if", ""))
        assert _DEFAULT_BRANCH_EXPR not in gate, (
            f"재실행 스텝({step.get('name')!r})이 기본 브랜치로 좁혀졌다: {gate!r}. "
            "네트워크 실패 재실행은 PR 에서도 유용하다."
        )
