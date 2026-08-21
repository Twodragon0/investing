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
5. 이슈 **중복 판정이 새 발견을 억제할 수 없을 것** (2026-08-21 추가)

## 5번을 뒤늦게 추가한 이유 (실측)

1~4 는 "step 이 실행되는가" 를 지켰다. 그런데 step 이 **실행되고 성공하면서도 아무
이슈를 만들지 않는** 경로가 남아 있었다 — 중복 판정이다.

`dependency-check.yml` 의 판정은 제목의 상수 접두어(`'Dependency Security'`)를 훑었다.
그래서 그 접두어를 가진 **열린 이슈가 하나라도 있으면 이후 모든 발견의 이슈 생성이
영구히 억제**됐다. 실측: #985 가 2026-06-01 에 열린 뒤 82일간(`createdAt == updatedAt`)
그 역할을 했고, 정작 그 이슈의 취약점(PYSEC-2022-252)은 이미 `--ignore-vuln` 목록에
들어가 닫혀야 했던 것이다.

발견이 `exit 1` 이던 시절엔 억제돼도 잡이 red 라 흔적이 남았다. exit 0 전환 이후엔
잡도 green 이므로 **신호가 0** 이다. 즉 전환이 이 잠복 버그를 무음 사고로 승격시켰다.

조치는 지문(발견 ID 집합의 해시)을 제목에 넣고 판정을 지문으로 좁힌 것이다. 아래 두
테스트가 그 성질을 지킨다 — 제목이 다시 상수가 되거나 판정이 다시 넓어지면 red.
"""

from __future__ import annotations

import re
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

# 파일 → 이슈 제목과 중복 판정이 반드시 참조해야 하는 "발견마다 달라지는" 값.
#
# 두 워크플로우가 서로 다른 수단을 쓴다 — 하나로 통일하지 않은 것은 의도다.
#   dependency-check       : 발견 ID 집합의 해시. 같은 취약점의 주간 재실행은 억제해야
#                            하므로 실행마다 달라지면 안 된다.
#   integrated-quality-report: `run_id`. 애초에 중복 조회가 없어 억제될 수 없고, 회귀
#                            리포트는 매 실행 스냅샷이라 실행마다 새 이슈가 맞다.
FINDING_SCOPED_DEDUP: dict[str, str] = {
    "dependency-check.yml": "fingerprint",
    "integrated-quality-report.yml": "github.run_id",
}

# 제목을 **만드는** 줄의 앵커. `i.title.includes(...)` 같은 속성 접근은 제외해야 한다
# (아니면 판정식 줄이 제목 줄로 오인되어 단언이 vacuous 해진다 — 실측 확인).
_TITLE_ASSIGN = re.compile(r"^\s*(?:const\s+|let\s+|var\s+)?title\s*[:=]")


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


def _issue_script(workflow: str) -> str:
    """이슈 생성 step 의 github-script 본문. 없으면 아래 단언들이 vacuous 해지므로 실패."""
    step_name, _ = CONVERTED[workflow]
    step = _step_named(_load(workflow), step_name)
    assert step is not None, f"{workflow}: '{step_name}' step 이 없다"
    script = str((step.get("with") or {}).get("script") or "")
    assert script, (
        f"{workflow}: '{step_name}' 에 github-script 본문이 없다. 이슈 생성 방식이 바뀌었다면 "
        "중복 억제 가드도 새 형태에 맞춰 다시 써야 한다."
    )
    return script


@pytest.mark.parametrize("workflow", sorted(FINDING_SCOPED_DEDUP))
def test_issue_title_varies_with_the_finding(workflow: str) -> None:
    """제목이 상수면 중복 판정이 이후 모든 발견을 억제할 수 있다(#985, 82일)."""
    token = FINDING_SCOPED_DEDUP[workflow]
    script = _issue_script(workflow)
    # 제목을 **만드는** 줄만 본다 — 변수 대입(`const title = ...`)과 create() 인자
    # 리터럴(`title: ...`).
    #
    # 느슨하게 `"title" in ln` 으로 걸면 중복 판정식(`i.title.includes(...)`)까지
    # 잡혀서, 그 줄에 있는 지문이 이 단언을 우연히 만족시킨다. 실측으로 확인했다:
    # 제목에서 지문을 제거하는 뮤테이션이 통과했다(2026-08-21). 접두어 앵커 필수.
    title_lines = [ln for ln in script.splitlines() if _TITLE_ASSIGN.match(ln)]
    assert title_lines, f"{workflow}: 이슈 제목을 만드는 줄을 찾지 못했다 — 형태가 바뀌었다"
    assert any(token in ln for ln in title_lines), (
        f"{workflow}: 이슈 제목이 `{token}` 을 담지 않는다. 제목이 발견마다 달라지지 않으면 "
        f"열린 이슈 하나가 이후 모든 발견을 침묵시킨다. 현재 제목 줄: {title_lines!r}"
    )


@pytest.mark.parametrize("workflow", sorted(FINDING_SCOPED_DEDUP))
def test_dedup_lookup_cannot_suppress_a_different_finding(workflow: str) -> None:
    """열린 이슈를 훑어 중복을 판정한다면, 그 판정은 발견마다 달라지는 값에 걸려야 한다.

    상수 접두어로 판정하면 step 은 실행되고 성공하면서도 이슈를 만들지 않는다.
    exit 0 전환 이후에는 잡도 green 이라 그 침묵이 어디에도 드러나지 않는다.
    """
    token = FINDING_SCOPED_DEDUP[workflow]
    script = _issue_script(workflow)

    if "listForRepo" not in script and ".find(" not in script:
        # 중복 조회가 아예 없으면 억제될 수 없다. 이 상태가 유지되는지만 확인한다 —
        # 나중에 조회가 추가되면 위 조건이 참이 되어 아래 판정식 단언이 살아난다.
        assert "issues.create" in script, f"{workflow}: 중복 조회도 없고 이슈 생성도 없다. 발견의 출력 경로가 사라졌다."
        return

    predicates = [ln for ln in script.splitlines() if ".find(" in ln]
    assert predicates, (
        f"{workflow}: 열린 이슈를 조회(listForRepo)하는데 중복 판정식(.find)을 찾지 못했다. "
        "판정 형태가 바뀌었다면 이 가드를 새 형태에 맞춰 다시 써야 한다."
    )
    assert all(token in ln for ln in predicates), (
        f"{workflow}: 중복 판정식이 `{token}` 을 참조하지 않는다 — 발견 내용과 무관하게 "
        f"매칭되므로 열린 이슈 하나가 이후 모든 발견을 억제한다. 현재: {predicates!r}"
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
