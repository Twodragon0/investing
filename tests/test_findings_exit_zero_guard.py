"""발견 경로가 exit 0 이 된 워크플로우의 출력 경로 가드.

## 왜 있나

`Dependency Security Check` 와 `Integrated Quality Report` 는 원래 발견 시(취약점 /
품질 회귀) 의도적으로 `exit 1` 했다. 그래서 잡 실패가 **두 가지**를 뜻했다:

    실패 = "찾았다"  또는  "죽었다"

밖에서 구분되지 않으니 크래시에만 알림을 붙일 수 없었고, 두 워크플로우는
`test_workflow_alerting_coverage_guard.py` 의 면제 목록에 남아 있었다 — 즉 워크플로우가
통째로 죽어도 아무도 몰랐다.

2026-08-18 에 발견 경로를 `exit 0` 으로 옮겼다. 이제 잡 실패는 크래시만 뜻하고
`alert-consecutive-failures` 가 의미를 갖는다.

## 그래서 생긴 새 위험

**발견의 유일한 출력 경로가 이슈 생성 step 하나가 됐다.** 예전에는 그 step 이 조용히
실패해도 뒤의 `exit 1` 이 잡을 red 로 만들어 흔적이 남았다. 지금은 그 안전망이 없다 —
이슈 생성이 `continue-on-error` 로 덮이거나 조건이 틀어지면 **취약점을 찾고도 아무
일도 일어나지 않는다.** 그리고 잡은 green 이다.

이 파일은 그 한 지점을 지킨다.

## 지키는 것

1. 발견 경로에 `exit 1` 이 되돌아오지 않을 것 (되돌아오면 면제 상태로 회귀한다)
2. 이슈 생성 step 이 blocking 일 것 (`continue-on-error` 금지)
3. 이슈 생성 step 이 실제로 존재하고 발견 조건에 걸려 있을 것
4. 알림이 연결돼 있을 것 — exit 0 전환의 대가로 얻어야 하는 것
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ALERT_REF = "./.github/workflows/alert-consecutive-failures.yml"

# 파일 → (발견 조건을 담은 step 이름, 그 조건이 참조하는 출력)
CONVERTED: dict[str, tuple[str, str]] = {
    "dependency-check.yml": ("Create issue on vulnerabilities", "vuln_count"),
    "integrated-quality-report.yml": ("Open issue on combined failure", "combined_status"),
}


def _load(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _steps(wf: dict) -> list[dict]:
    out: list[dict] = []
    for job in (wf.get("jobs") or {}).values():
        if isinstance(job, dict):
            out.extend(s for s in (job.get("steps") or []) if isinstance(s, dict))
    return out


def _step_named(wf: dict, name: str) -> dict | None:
    return next((s for s in _steps(wf) if s.get("name") == name), None)


@pytest.mark.parametrize("workflow", sorted(CONVERTED))
def test_issue_creation_step_exists(workflow: str) -> None:
    """발견의 유일한 출력 경로다. 이름이 바뀌면 아래 단언들이 vacuous 해진다."""
    step_name, _ = CONVERTED[workflow]
    assert _step_named(_load(workflow), step_name) is not None, (
        f"{workflow}: '{step_name}' step 이 없다. 이름을 바꿨다면 CONVERTED 도 갱신할 것 — "
        "이 가드가 조용히 아무것도 지키지 않게 된다."
    )


@pytest.mark.parametrize("workflow", sorted(CONVERTED))
def test_issue_creation_is_blocking(workflow: str) -> None:
    """`continue-on-error` 가 붙으면 취약점을 찾고도 아무 일이 없고 잡은 green 이다."""
    step_name, _ = CONVERTED[workflow]
    step = _step_named(_load(workflow), step_name)
    assert step is not None
    assert not step.get("continue-on-error"), (
        f"{workflow}: '{step_name}' 에 continue-on-error 가 붙었다. 발견의 유일한 출력 "
        "경로이므로 실패하면 잡도 실패해야 한다 — 예전엔 뒤의 exit 1 이 안전망이었지만 "
        "이제 없다."
    )


@pytest.mark.parametrize("workflow", sorted(CONVERTED))
def test_issue_creation_is_gated_on_the_finding(workflow: str) -> None:
    """조건이 발견 신호를 참조해야 한다. 상수 조건이면 매번 이슈가 생기거나 안 생긴다."""
    step_name, signal = CONVERTED[workflow]
    step = _step_named(_load(workflow), step_name)
    assert step is not None
    condition = str(step.get("if") or "")
    assert signal in condition, (
        f"{workflow}: '{step_name}' 의 if 가 `{signal}` 을 참조하지 않는다 (현재: {condition!r})"
    )


@pytest.mark.parametrize("workflow", sorted(CONVERTED))
def test_finding_path_does_not_exit_nonzero(workflow: str) -> None:
    """발견 경로에 `exit 1` 이 되돌아오면 면제 상태로 회귀한다.

    잡 실패가 다시 "찾았다/죽었다" 두 뜻이 되고, 아래 알림이 모든 발견에 울게 된다.
    """
    _, signal = CONVERTED[workflow]
    for step in _steps(_load(workflow)):
        run = str(step.get("run") or "")
        if signal in str(step.get("if") or "") and "exit 1" in run:
            pytest.fail(
                f"{workflow}: 발견 조건({signal})이 걸린 step '{step.get('name')}' 에 exit 1 이 있다. "
                "발견은 exit 0 + 이슈여야 잡 실패가 크래시만 뜻한다."
            )


@pytest.mark.parametrize("workflow", sorted(CONVERTED))
def test_alerting_is_attached(workflow: str) -> None:
    """exit 0 전환의 대가로 얻어야 하는 것. 없으면 크래시가 다시 조용해진다."""
    text = (WORKFLOWS_DIR / workflow).read_text(encoding="utf-8")
    assert ALERT_REF in text, (
        f"{workflow}: 발견을 exit 0 으로 옮겼는데 실패 알림이 없다. "
        "크래시가 green 도 red 도 아닌 채로 아무에게도 안 보인다."
    )


def test_check_post_summary_covers_crashes_by_issue_on_failure() -> None:
    """`check-post-summary.yml` 은 전환 대상이 **아니다** — 이미 다른 방식으로 덮고 있다.

    이 워크플로우의 이슈 생성은 `if: failure()` 라 회귀뿐 아니라 **크래시에도** 돈다.
    그래서 exit 0 전환 없이도 크래시가 보인다. 그 성질이 사라지면(조건이 좁아지면)
    전환 대상이 되므로 여기서 지킨다.
    """
    wf = _load("check-post-summary.yml")
    step = _step_named(wf, "Open issue on regression")
    assert step is not None, "'Open issue on regression' step 이 사라졌다"
    condition = str(step.get("if") or "")
    assert "failure()" in condition, (
        f"check-post-summary.yml: 이슈 생성 조건이 `failure()` 가 아니다 (현재: {condition!r}). "
        "좁아졌다면 크래시가 더 이상 이슈를 만들지 않으므로 exit 0 전환이 필요하다."
    )
    assert not step.get("continue-on-error"), "이슈 생성이 non-blocking 이 되면 크래시가 조용해진다"
