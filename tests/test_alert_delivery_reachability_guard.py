"""연속-실패 알림이 **실제로 어딘가에 도달하는지** 지키는 가드.

`test_workflow_alerting_coverage_guard.py` 는 "스케줄 워크플로우에 알림이 붙어 있는가"
(커버리지)를 본다. 이 파일은 그 다음 질문을 본다 — **붙어 있는 알림이 도달 가능한가.**

## 왜 나중에 추가됐나 (실측 근거)

기존 `test_findings_exit_zero_guard.py::test_alerting_is_attached` 는 워크플로우 파일
텍스트에 재사용 워크플로우 경로가 있는지만 grep 한다. 그래서 알림 잡을
`if: false` 로 만들어 **도달 불가**하게 해도 통과한다(2026-08-21 뮤테이션 확인).
텍스트에 경로가 남아 있기 때문이다.

그리고 재사용 워크플로우 안에도 도달 불가 분기가 실제로 있었다.
`alert-consecutive-failures.yml` 의 fallback 조건은

    steps.check.outputs.alert == 'true' &&
    (steps.slack.outputs.can_post != 'true' || steps.post-slack.outcome == 'failure')

인데 status 함수가 없어 암묵 `success()` 가 붙는다. `post-slack` 에는
`continue-on-error` 가 없으므로 Slack 전달이 실패하면 잡이 죽고 → 암묵 `success()` 가
깨져 → **fallback 이 skip 된다.** 즉 "전달 실패 시 이슈로 대체" 라는 의도가 코드에
쓰여 있으면서 한 번도 실행될 수 없었다. `can_post != 'true'` 쪽만 도달 가능했다
(그쪽은 Slack step 이 skip 이지 fail 이 아니라 `success()` 가 유지된다).

실측 뒷받침: `gh issue list --search "alert-delivery-failed in:title" --state all`
→ 빈 결과. 이 fallback 은 프로덕션에서 한 번도 산출물을 낸 적이 없다.

## 지키는 것

1. fallback 이 **양쪽 원인 모두**에서 도달 가능할 것 (status 함수 필수)
2. fallback 이 두 원인을 **구분**할 것 — `can_post=false` 는 전달 실패가 아니라 미설정
3. Slack post 가 `can_post` 로 게이팅될 것
4. `recent_failures` 가 빈 문자열로 새지 않을 것
5. 호출자 28곳의 알림 잡이 **구조적으로** 도달 가능할 것 (M8 구멍)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ALERT_WORKFLOW = WORKFLOWS_DIR / "alert-consecutive-failures.yml"
ALERT_REF = "./.github/workflows/alert-consecutive-failures.yml"

FALLBACK_STEP = "Fallback — create GitHub issue when Slack alert did not land"
SLACK_STEP = "Post alert to Slack"

# 실패한 이전 step 을 넘어 실행되게 하는 status 함수. 하나라도 없으면 암묵 `success()`
# 가 붙어 전달-실패 분기가 죽는다.
_SURVIVES_FAILURE = ("always()", "!cancelled()")


def _load(path: Path) -> dict:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} 가 없다"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name}: 최상위가 매핑이 아니다"
    return data


def _alert_steps() -> list[dict]:
    wf = _load(ALERT_WORKFLOW)
    steps = [
        s
        for job in (wf.get("jobs") or {}).values()
        if isinstance(job, dict)
        for s in (job.get("steps") or [])
        if isinstance(s, dict)
    ]
    assert steps, f"{ALERT_WORKFLOW.name}: step 을 찾지 못했다 — 잡 구조가 바뀌었다"
    return steps


def _step(name: str) -> dict:
    """이름으로 step 을 찾는다. 못 찾으면 아래 단언들이 vacuous 해지므로 실패시킨다."""
    found = next((s for s in _alert_steps() if s.get("name") == name), None)
    assert found is not None, (
        f"{ALERT_WORKFLOW.name}: '{name}' step 이 없다. 이름을 바꿨다면 이 가드의 상수도 "
        "갱신할 것 — 그러지 않으면 도달성을 아무도 지키지 않는다."
    )
    return found


def _callers() -> list[tuple[str, str, dict]]:
    """(파일명, 잡 이름, 잡 본체) — 재사용 알림 워크플로우를 호출하는 모든 잡."""
    out: list[tuple[str, str, dict]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            wf = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - 파싱 실패는 다른 가드 책임
            pytest.fail(f"{path.name}: YAML 파싱 실패 — {exc}")
        if not isinstance(wf, dict):
            continue
        for job_name, job in (wf.get("jobs") or {}).items():
            if isinstance(job, dict) and str(job.get("uses") or "") == ALERT_REF:
                out.append((path.name, str(job_name), job))
    assert out, (
        f"{ALERT_REF} 를 호출하는 잡이 하나도 없다. 경로가 바뀌었다면 ALERT_REF 를 갱신할 것 "
        "— 그러지 않으면 아래 호출자 단언 전부가 조용히 vacuous 해진다."
    )
    return out


# ---------------------------------------------------------------------------
# 재사용 워크플로우 내부 — fallback 도달성
# ---------------------------------------------------------------------------


def test_fallback_survives_a_failed_slack_post() -> None:
    """`post-slack` 실패 분기가 도달 가능해야 한다.

    status 함수가 없으면 암묵 `success()` 가 붙고, `post-slack` 에 `continue-on-error`
    가 없으므로 전달 실패 시 이 step 이 skip 된다 — 의도가 코드에 있으면서 실행 불가.
    """
    condition = str(_step(FALLBACK_STEP).get("if") or "")
    assert any(fn in condition for fn in _SURVIVES_FAILURE), (
        f"{ALERT_WORKFLOW.name}: fallback 조건에 {list(_SURVIVES_FAILURE)} 중 어느 것도 없다 "
        f"(현재: {condition!r}). 암묵 success() 때문에 Slack 전달 실패 시 fallback 이 skip 되고, "
        "알림이 Slack 도 이슈도 없이 사라진다."
    )


def test_fallback_covers_both_causes() -> None:
    """미설정(`can_post != 'true'`)과 전달 실패(`outcome == 'failure'`) 둘 다 걸려야 한다.

    한쪽만 남으면 다른 쪽 원인으로 알림이 사라진다.
    """
    condition = str(_step(FALLBACK_STEP).get("if") or "")
    for needle, why in (
        ("can_post", "Slack 이 설정되지 않은 경우(오늘의 실제 상태)"),
        ("post-slack", "Slack 전달이 실패한 경우"),
    ):
        assert needle in condition, (
            f"{ALERT_WORKFLOW.name}: fallback 조건이 `{needle}` 을 참조하지 않는다 — "
            f"{why} 에 알림이 사라진다 (현재: {condition!r})"
        )


def test_fallback_distinguishes_not_configured_from_delivery_failure() -> None:
    """`can_post=false` 는 전달 실패가 아니라 **미설정**이다.

    이전 문구는 두 경우 모두 "Slack notify failed" 로 적고 "토큰 로테이션 확인" 을
    지시해, 실제 원인(시크릿 미설정)이 아닌 곳을 뒤지게 만들었다.
    """
    script = str((_step(FALLBACK_STEP).get("with") or {}).get("script") or "")
    assert script, f"{ALERT_WORKFLOW.name}: fallback 에 github-script 본문이 없다"

    # 느슨하게 `"can_post" in script` 로 걸면 안 된다 — 본문의 표 라벨
    # (`| Slack can_post | ... |`)에 그 문자열이 그대로 들어 있어서, 판정 로직을
    # 상수로 갈아치우는 뮤테이션이 통과한다(2026-08-21 실측). **출력을 읽는 표현식**을
    # 앵커로 삼는다.
    assert "steps.slack.outputs.can_post" in script, (
        f"{ALERT_WORKFLOW.name}: fallback 본문이 `steps.slack.outputs.can_post` 를 읽지 않는다 "
        "— 미설정과 전달 실패를 구분할 수 없으므로 진단 문구가 한쪽에는 반드시 틀린다."
    )
    for cause in ("Slack not configured", "Slack delivery failed"):
        assert cause in script, (
            f"{ALERT_WORKFLOW.name}: fallback 본문에 원인 구분 문구 {cause!r} 가 없다. "
            "두 원인을 같은 문구로 처리하면 사람이 엉뚱한 곳을 뒤진다."
        )
    assert "SLACK_CHANNEL_ID_INVESTING" in script, (
        f"{ALERT_WORKFLOW.name}: fallback 본문에 되살리는 방법(`SLACK_CHANNEL_ID_INVESTING`)이 "
        "없다. 이슈만 열리고 무엇을 고쳐야 하는지 알 수 없다."
    )


def test_slack_post_is_gated_on_can_post() -> None:
    """게이트가 사라지면 미설정 상태에서 Slack 호출이 시도되고 잡이 죽는다."""
    condition = str(_step(SLACK_STEP).get("if") or "")
    assert "can_post" in condition, (
        f"{ALERT_WORKFLOW.name}: '{SLACK_STEP}' 이 `can_post` 로 게이팅되지 않는다 (현재: {condition!r})"
    )


def test_recent_failures_never_leaks_empty() -> None:
    """threshold=1 이면 조회 대상이 현재 런 하나뿐이라 목록이 빈 문자열이 된다.

    `--limit` 을 늘려 채우면 안 된다 — 같은 JSON 으로 `prev_failures` 를 세므로 판정
    창이 넓어져 "연속 실패" 가 "창 안에 N건" 으로 의미가 바뀐다. 빈 값 처리로 막는다.
    """
    check = _step("Check previous run conclusions")
    run = str(check.get("run") or "")
    assert "recent_failures" in run, f"{ALERT_WORKFLOW.name}: recent_failures 출력이 사라졌다"
    assert '-z "${recent}"' in run or '-z "$recent"' in run, (
        f"{ALERT_WORKFLOW.name}: `recent` 의 빈 값 처리가 없다. threshold=1 에서 알림 본문에 "
        "'Recent failed runs:' 만 남는다."
    )


def test_threshold_window_is_not_widened() -> None:
    """`--limit` 은 THRESHOLD 여야 한다 — 넓히면 판정 의미가 바뀐다.

    현재 로직은 최근 THRESHOLD 건을 가져와 현재 런을 제외하고 실패를 세므로, 실질적으로
    "직전 THRESHOLD-1 건이 모두 실패" 다. limit 을 늘리면 흩어진 실패도 합산되어
    "연속" 이 아니게 된다.
    """
    run = str(_step("Check previous run conclusions").get("run") or "")
    assert '--limit "${THRESHOLD}"' in run, (
        f"{ALERT_WORKFLOW.name}: `--limit` 이 THRESHOLD 가 아니다. 판정 창이 넓어지면 비연속 실패에도 알림이 울린다."
    )


# ---------------------------------------------------------------------------
# 호출자 측 — M8 구멍
# ---------------------------------------------------------------------------


def test_every_caller_alert_job_runs_on_failure() -> None:
    """호출자의 알림 잡이 `failure()` 로 걸려 있어야 한다.

    기존 가드는 파일 텍스트에 재사용 워크플로우 경로가 있는지만 grep 하므로, 잡을
    `if: false` 로 만들어 도달 불가하게 해도 통과한다. 여기서는 구조를 본다.
    """
    broken = [(wf, job) for wf, job, body in _callers() if "failure()" not in str(body.get("if") or "")]
    assert not broken, (
        f"알림 잡의 조건에 `failure()` 가 없다: {broken}. 텍스트에 경로만 남고 잡이 절대 "
        "돌지 않으면 커버리지 가드는 green 인데 알림은 0건이다."
    )


def test_every_caller_alert_job_inherits_secrets() -> None:
    """`secrets: inherit` 이 없으면 재사용 워크플로우에서 `SLACK_BOT_TOKEN` 이 비어

    can_post=false 로 떨어진다 — Slack 알림이 조용히 이슈 fallback 으로 강등된다.
    """
    broken = [(wf, job) for wf, job, body in _callers() if body.get("secrets") != "inherit"]
    assert not broken, (
        f"알림 잡에 `secrets: inherit` 이 없다: {broken}. 토큰이 전달되지 않아 Slack 경로가 "
        "죽고 이슈 fallback 으로만 떨어진다."
    )


def test_every_caller_alert_job_needs_an_existing_job() -> None:
    """`needs` 가 없거나 존재하지 않는 잡을 가리키면 알림이 실행되지 않는다."""
    problems: list[str] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        wf = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(wf, dict):
            continue
        jobs = wf.get("jobs") or {}
        for job_name, job in jobs.items():
            if not (isinstance(job, dict) and str(job.get("uses") or "") == ALERT_REF):
                continue
            needs = job.get("needs")
            names = [needs] if isinstance(needs, str) else list(needs or [])
            if not names:
                problems.append(f"{path.name}:{job_name} — needs 없음")
                continue
            missing = [n for n in names if n not in jobs]
            if missing:
                problems.append(f"{path.name}:{job_name} — 없는 잡을 needs: {missing}")
    assert not problems, (
        f"알림 잡의 needs 가 잘못됐다: {problems}. 존재하지 않는 잡을 기다리면 알림이 "
        "영구 skip 되고, needs 가 없으면 감시 대상 잡의 실패와 무관하게 돈다."
    )
