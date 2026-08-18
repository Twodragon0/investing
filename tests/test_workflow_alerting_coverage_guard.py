"""스케줄 워크플로우의 실패 알림 커버리지 가드.

## 왜 있나

2026-08-18 에 `Push Folder Info To Slack` 이 **11일 연속 매일 실패**하고 있던 것을
발견했다(마지막 성공 08-07 04:08). Dependabot 이 `slackapi/slack-github-action` 을
3.0.1 → 4.0.0 으로 올리면서 payload YAML 파싱이 엄격해진 것이 원인이었는데,
문제는 **아무 알림도 울리지 않았다**는 것이다.

`docs/ops-external-watchdog.md` 는 4계층 알림 피라미드를 문서화하고 있다. 이번
장애는 네 계층을 전부 통과했다:

| 계층 | 커버 범위 | 이번 장애 |
|---|---|---|
| `alert-consecutive-failures` | `workflow_call` — 각 워크플로우가 **직접 호출**해야 함 | 호출하지 않음 |
| `watchdog-zero-job-runs` | `startup_failure` 만 | 일반 step 실패라 해당 없음 |
| 외부 서버(Layer 4) | 위 watchdog 감시 | 무관 |
| `classify-workflow-failures` | **20개 화이트리스트** | 목록에 없음 |

즉 커버리지가 **두 개의 옵트인 목록**으로 관리되는데 둘 다 조용히 드리프트한다.
워크플로우를 새로 만들거나 이름을 바꿔도 등록 누락을 아무것도 감지하지 않는다.
발견 시점 실측으로 워크플로우 53개 중 32개가 무커버리지였고, 그중 **17개가
스케줄 실행** — 이번처럼 매일 조용히 실패할 수 있는 것들이었다.

## 이 파일이 지키는 것

1. **새 갭이 생기지 않을 것.** 스케줄 워크플로우가 두 계층 중 어디에도 없으면
   `KNOWN_UNCOVERED` 에 명시적으로 적어야 통과한다. 적는 행위가 리뷰 대상이 된다.
2. **목록이 저절로 줄어들 것.** 비교는 부분집합이 아니라 **정확한 일치**다. 커버리지를
   붙였는데 `KNOWN_UNCOVERED` 에서 안 빼면 red — 목록이 낡은 채로 남지 않는다.
3. **이름 드리프트를 잡을 것.** `classify-workflow-failures.yml` 의 화이트리스트는
   워크플로우의 `name:` 문자열로 매칭한다. 워크플로우 이름을 바꾸면 그 항목이 조용히
   아무것도 가리키지 않게 되고 커버리지가 사라진다. 실존을 강제한다.

이 가드는 갭을 **없애지 않는다.** 갭이 11일 뒤가 아니라 PR 시점에 보이게 할 뿐이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

CLASSIFIER = WORKFLOWS_DIR / "classify-workflow-failures.yml"
CONSECUTIVE_ALERT_REF = "./.github/workflows/alert-consecutive-failures.yml"

# 커버리지가 없는 스케줄 워크플로우 — 2026-08-18 기준 **0건**.
#
# 발견 시점에는 17건이었다. 셋으로 나눠 없앴다:
# - 11건 → `alert-consecutive-failures` 호출 (#1176)
# - 3건  → 자기참조 위험 우선 (#1174)
# - 2건  → 발견 경로를 exit 0 으로 옮겨 잡 실패가 크래시만 뜻하게 만든 뒤 알림 연결.
#          `tests/test_findings_exit_zero_guard.py` 가 그 전환의 불변식을 지킨다.
# - 1건  → `check-post-summary.yml`. 전환 없이 이미 커버돼 있었다 — 이슈 생성이
#          `if: failure()` 라 크래시에도 돈다. `_issue_on_failure_workflows()` 가 그
#          메커니즘을 모델에 넣는다.
#
# **비어 있다고 가드가 무의미해지지 않는다.** 새 스케줄 워크플로우가 커버리지 없이
# 들어오면 여기 적어야 통과하고, 적는 행위가 리뷰 대상이 된다.
# `test_uncovered_scheduled_workflow_would_be_detected` 가 탐지 로직이 vacuous 하지
# 않음을 따로 지킨다.
KNOWN_UNCOVERED: frozenset[str] = frozenset()


def _load(path: Path) -> dict:
    """워크플로우 YAML 을 읽는다.

    `on:` 은 YAML 1.1 에서 **boolean True 로 파싱된다.** 문자열 키로 찾으면 트리거가
    없는 것처럼 보여 모든 워크플로우가 "스케줄 아님" 이 되고, 이 가드가 통째로
    vacuous 해진다.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _triggers(wf: dict) -> dict:
    on = wf.get("on", wf.get(True))
    return on if isinstance(on, dict) else {}


def _workflow_name(path: Path, wf: dict) -> str:
    name = wf.get("name")
    return str(name) if isinstance(name, str) and name.strip() else path.stem


def _all_workflows() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        found[_workflow_name(path, _load(path))] = path
    return found


def _scheduled() -> set[str]:
    names: set[str] = set()
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        wf = _load(path)
        if "schedule" in _triggers(wf):
            names.add(_workflow_name(path, wf))
    return names


def _classifier_allowlist() -> set[str]:
    wf = _load(CLASSIFIER)
    run = _triggers(wf).get("workflow_run") or {}
    listed = run.get("workflows") or []
    return {str(n) for n in listed}


def _consecutive_alert_callers() -> set[str]:
    names: set[str] = set()
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if CONSECUTIVE_ALERT_REF in path.read_text(encoding="utf-8"):
            names.add(_workflow_name(path, _load(path)))
    return names


def _issue_on_failure_workflows() -> set[str]:
    """실패 시(크래시 포함) 이슈를 만드는 워크플로우 — 세 번째 커버리지 메커니즘.

    `check-post-summary.yml` 이 이 방식이다. 이슈 생성 step 의 `if:` 가 `failure()` 라
    회귀뿐 아니라 크래시에도 돌므로, 알림 계층에 등록돼 있지 않아도 고장이 보인다.

    이 메커니즘을 모델에 넣지 않으면 baseline 이 "커버 안 됨" 과 "다르게 커버됨" 을
    뒤섞어, 남은 숫자가 실제 위험을 과장한다.
    """
    names: set[str] = set()
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        wf = _load(path)
        for job in (wf.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                if "failure()" not in str(step.get("if") or ""):
                    continue
                script = str((step.get("with") or {}).get("script") or "")
                if "issues.create" in script:
                    names.add(_workflow_name(path, wf))
    return names


def _covered() -> set[str]:
    return _classifier_allowlist() | _consecutive_alert_callers() | _issue_on_failure_workflows()


def test_scheduled_workflows_are_discovered() -> None:
    """스캐너가 붕괴하면 아래 단언이 전부 vacuous 해진다.

    `on:` 이 boolean True 로 파싱되는 함정 때문에 실제로 0개가 나올 수 있다.
    """
    scheduled = _scheduled()
    assert len(scheduled) >= 20, f"스케줄 워크플로우 {len(scheduled)}개 — 스캐너가 깨졌을 것"
    assert "Push Folder Info To Slack" in scheduled


def test_coverage_sources_are_discovered() -> None:
    """두 커버리지 원본이 다 읽혀야 한다. 하나가 비면 갭이 과대 보고된다."""
    assert len(_classifier_allowlist()) >= 15, "classify 화이트리스트를 못 읽었다"
    assert len(_consecutive_alert_callers()) >= 10, "alert-consecutive-failures 호출자를 못 찾았다"
    assert _issue_on_failure_workflows(), "`if: failure()` 이슈 생성 워크플로우를 못 찾았다"


def test_no_new_uncovered_scheduled_workflow() -> None:
    """새 스케줄 워크플로우는 알림 계층에 등록되거나 baseline 에 명시돼야 한다.

    정확한 일치를 요구한다 — 커버리지를 붙이고 baseline 에서 빼지 않으면 red 다.
    목록이 낡은 채로 남으면 "17개 갭" 이라는 숫자가 거짓이 된다.
    """
    uncovered = _scheduled() - _covered()

    newly_uncovered = uncovered - KNOWN_UNCOVERED
    assert not newly_uncovered, (
        f"알림 커버리지 없는 스케줄 워크플로우가 새로 생겼다: {sorted(newly_uncovered)}. "
        "classify-workflow-failures.yml 의 workflows: 목록에 넣거나, "
        "alert-consecutive-failures.yml 를 호출하거나, "
        "조용히 실패해도 되는 이유를 적고 KNOWN_UNCOVERED 에 추가할 것."
    )

    now_covered = KNOWN_UNCOVERED - uncovered
    assert not now_covered, (
        f"커버리지가 생겼는데 baseline 에 남아 있다: {sorted(now_covered)}. "
        "KNOWN_UNCOVERED 에서 뺄 것 — 목록은 줄어들기만 해야 한다."
    )


def test_classifier_allowlist_names_exist() -> None:
    """화이트리스트는 `name:` 문자열 매칭이다 — 이름을 바꾸면 조용히 커버리지가 사라진다.

    `COLLECTOR_WORKFLOWS` 가 파일명 조립으로 겪은 것과 같은 종류의 드리프트다.
    """
    known = set(_all_workflows())
    dangling = _classifier_allowlist() - known
    assert not dangling, (
        f"classify-workflow-failures.yml 이 존재하지 않는 워크플로우를 가리킨다: {sorted(dangling)}. "
        "이름이 바뀌었다면 그 워크플로우는 지금 무커버리지다."
    )


def test_known_uncovered_entries_exist() -> None:
    """baseline 에 없는 이름이 남아 있으면 그만큼 갭이 작아 보인다."""
    known = set(_all_workflows())
    stale = KNOWN_UNCOVERED - known
    assert not stale, f"KNOWN_UNCOVERED 에 존재하지 않는 워크플로우가 있다: {sorted(stale)}"


@pytest.mark.parametrize("path", sorted(WORKFLOWS_DIR.glob("*.yml")), ids=lambda p: p.name)
def test_every_workflow_declares_a_name(path: Path) -> None:
    """`name:` 이 없으면 파일명으로 폴백하는데, 그 값은 화이트리스트와 절대 일치하지 않는다.

    즉 이름 없는 워크플로우는 등록해도 커버되지 않는다.
    """
    wf = _load(path)
    assert isinstance(wf.get("name"), str) and wf["name"].strip(), f"{path.name} 에 name: 이 없다"


def test_alert_reference_path_is_current() -> None:
    """호출자 탐지는 경로 문자열 매칭이다 — 재사용 워크플로우가 옮겨지면 조용히 0건이 된다."""
    assert (WORKFLOWS_DIR / "alert-consecutive-failures.yml").is_file(), (
        f"{CONSECUTIVE_ALERT_REF} 가 없다 — 호출자 탐지가 전부 빗나간다"
    )


def test_regression_marker_push_folder_info_is_now_covered() -> None:
    """이 가드를 만들게 한 워크플로우(11일 조용한 실패, #1172)가 이제 커버되는지.

    2026-08-18 에 `alert-consecutive-failures` 를 붙였다. 여기서 red 가 나면 그 연결이
    끊어진 것이고, 같은 사고가 다시 조용히 일어날 수 있다.
    """
    name = "Push Folder Info To Slack"
    assert name in _scheduled(), "스케줄 트리거가 사라졌다 — 이 단언의 전제가 깨졌다"
    assert name in _covered(), "알림 연결이 끊어졌다 — #1172 와 같은 사고가 다시 조용해진다"


def test_uncovered_scheduled_workflow_would_be_detected() -> None:
    """탐지 로직 자체가 살아 있는지 — baseline 이 비어 가도 vacuous 해지지 않게.

    커버리지가 100% 가 되면 `_scheduled() - _covered()` 가 항상 빈 집합이라 위
    단언들이 전부 자동 통과한다. 합성 입력으로 탐지 로직을 따로 확인한다.
    """
    synthetic_scheduled = _scheduled() | {"Synthetic Uncovered Workflow"}
    assert "Synthetic Uncovered Workflow" in synthetic_scheduled - _covered()


def test_yaml_on_key_trap_is_handled() -> None:
    """`on:` 이 True 로 파싱되는 것을 처리하지 못하면 이 가드는 전부 vacuous 하다."""
    raw = yaml.safe_load("name: X\non:\n  schedule:\n    - cron: '0 0 * * *'\n")
    assert "on" not in raw and True in raw, "PyYAML 동작이 바뀌었다 — _triggers 를 재검토할 것"
    assert "schedule" in _triggers(raw)


def test_yaml_quoted_on_key_also_works() -> None:
    """`'on':` 으로 따옴표를 쓴 워크플로우도 있을 수 있다."""
    raw = yaml.safe_load("name: X\n'on':\n  schedule:\n    - cron: '0 0 * * *'\n")
    assert "schedule" in _triggers(raw)


def test_scanner_ignores_non_workflow_files() -> None:
    """`AGENTS.md` 같은 비-yml 파일이 섞여도 이름 집합이 오염되지 않아야 한다."""
    assert all(p.suffix == ".yml" for p in WORKFLOWS_DIR.glob("*.yml"))
    assert "AGENTS" not in _all_workflows()
