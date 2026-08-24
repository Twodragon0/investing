"""워크플로우 concurrency 그룹 스코프 가드.

## 왜 있나

`concurrency.group` 에 `${{ }}` 표현식이 없으면 그 그룹은 **저장소 전역 상수**다.
`cancel-in-progress: true` 와 합쳐지면, 새 런이 시작될 때 **어느 ref 의 런이든**
진행 중인 것을 취소한다.

트리거가 `schedule` / `workflow_dispatch` / `workflow_run` 뿐이라면 이건 의도된
동작이다 — 실질적으로 ref 가 하나뿐이고, "최신 것만 돌면 된다" 가 맞다.

`push` 나 `pull_request` 가 섞이면 이야기가 달라진다. 브랜치·PR 마다 런이 생기는데
슬롯이 하나뿐이라 서로를 죽인다. 2026-08-24 에 `supply-chain-lock.yml` 에서 실측된
결과:

| 이벤트 | 취소 | 성공 | 실패 | 취소율 |
|---|---|---|---|---|
| `push` | 25 | 9 | 1 | **71%** |
| `pull_request` | 10 | 10 | 3 | **43%** |
| 전체 | 35 | 21 | 4 | **58%** |

그건 공급망 무결성 게이트였다(락 해시 ↔ `requirements.txt`, 상류 yank/tamper).
절반 이상 취소되면 게이트가 **대부분 돌지 않는데도 아무도 모른다** — 취소는 실패
알림을 울리지 않는다. 게다가 PR 브랜치 푸시는 `push` 런과 `pull_request` 런이 같은
슬롯을 다퉈 서로를 죽이므로, PR 에는 완주하지 못한 red X 만 남아 **막히지 않은 PR 이
막힌 것처럼 보인다**. #1184 가 그 상태였다.

## 이 가드가 지키는 것

`push` 또는 `pull_request` 를 받는 워크플로우가 `cancel-in-progress: true` 를 쓰면
그룹이 ref/PR 로 스코프돼 있어야 한다. 취소는 조용하므로 이 회귀는 런타임에
드러나지 않는다 — 정적으로 잡는 수밖에 없다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# ref 가 여러 개 동시에 존재할 수 있는 트리거. 이들이 있으면 전역 상수 그룹은
# 교차-ref 취소를 뜻한다.
_MULTI_REF_TRIGGERS = frozenset({"push", "pull_request", "pull_request_target"})


def _workflow_files() -> list[Path]:
    if not _WORKFLOWS_DIR.is_dir():
        return []
    return sorted(p for p in _WORKFLOWS_DIR.glob("*.yml") if p.is_file())


def _triggers(wf: dict) -> set[str]:
    """PyYAML 1.1 은 bare `on:` 을 boolean True 로 읽는다 — 두 키를 모두 본다."""
    raw = wf.get("on", wf.get(True))
    if isinstance(raw, dict):
        return set(raw)
    if isinstance(raw, list):
        return set(raw)
    if isinstance(raw, str):
        return {raw}
    return set()


@pytest.mark.parametrize(
    "yaml_path",
    _workflow_files(),
    ids=lambda p: p.name,
)
def test_cancelling_workflows_scope_concurrency_by_ref(yaml_path: Path) -> None:
    wf = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(wf, dict):
        pytest.skip(f"{yaml_path.name} is not a mapping")

    concurrency = wf.get("concurrency")
    if not isinstance(concurrency, dict):
        return
    if concurrency.get("cancel-in-progress") is not True:
        return

    triggers = _triggers(wf)
    if not (triggers & _MULTI_REF_TRIGGERS):
        return

    group = str(concurrency.get("group", ""))
    assert "${{" in group, (
        f"{yaml_path.name} 은 {sorted(triggers & _MULTI_REF_TRIGGERS)} 를 받으면서 "
        f"concurrency group 이 전역 상수({group!r})이고 cancel-in-progress: true 다. "
        "서로 무관한 브랜치/PR 의 런이 서로를 취소한다 — supply-chain-lock.yml 에서 "
        "런 58%가 취소돼 게이트가 대부분 돌지 않았고, 취소는 실패 알림을 울리지 않아 "
        "조용히 넘어갔다. "
        "해소: group 에 ${{ github.event.pull_request.number || github.ref }} 를 포함할 것."
    )


def test_guard_covers_at_least_one_workflow() -> None:
    """가드가 아무것도 검사하지 않는 상태로 통과하지 않게 한다.

    조건(`cancel-in-progress: true` + multi-ref 트리거)에 해당하는 워크플로우가
    0개면 위 테스트는 전부 no-op 으로 green 이다. 그럼 나중에 조건 판정이 깨져도
    아무도 모른다 — 커버 대상이 실제로 존재함을 단언한다.
    """
    covered = []
    for path in _workflow_files():
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(wf, dict):
            continue
        concurrency = wf.get("concurrency")
        if not isinstance(concurrency, dict):
            continue
        if concurrency.get("cancel-in-progress") is not True:
            continue
        if _triggers(wf) & _MULTI_REF_TRIGGERS:
            covered.append(path.name)

    assert covered, (
        "cancel-in-progress + push/pull_request 조합의 워크플로우가 하나도 없다. "
        "가드가 no-op 이 됐거나 트리거 파싱이 깨졌다 — _triggers()/_MULTI_REF_TRIGGERS 를 확인할 것."
    )
