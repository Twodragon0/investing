"""`requirements-lock-sync.yml` 의 CI 인바리언트 가드.

이 워크플로우는 `scripts/requirements.txt` bump PR 에서 락을 재생성해 결과물을
내놓는다. 설계 근거와 foot-gun 목록은
`docs/devsecops/requirements-lock-autosync-design.md` §5.

## 왜 가드가 필요한가

지키는 성질 넷은 전부 **조용히 무너질 수 있다** — 무너져도 워크플로우는 계속 green
이고, 무너진 사실이 드러나는 시점은 사고가 난 뒤다.

| 성질 | 무너지면 |
|---|---|
| `pull_request_target` 금지 | write 토큰 + PR head 코드 실행. `pip-compile` 은 sdist 빌드로 임의 코드를 실행할 수 있다 → 권한 상승 |
| `paths` 를 txt 로 한정 | 락만 바뀐 푸시가 다시 트리거 → 커밋백 도입 시 무한 루프 |
| python 3.11 고정 | 다른 마이너로 생성한 락은 내용이 달라진다 → 무관 패키지 drift, 재현 불가 |
| drift 시 잡 실패 | 재생성 결과가 어긋나는데 green. 이 워크플로우 자체가 fail-open 신호가 된다 |
| in-place 앵커 재생성 | `--upgrade` 가 붙으면 전 패키지 상류 drift. "봇이 올린 그 패키지만" 이라는 전제가 깨진다 |

## 왜 텍스트 매칭이 아니라 구조 파싱인가

이 워크플로우의 **주석에 `pull_request_target` 과 `--upgrade` 가 실제로 등장한다**
(둘 다 "쓰지 않는다"는 설명이다). 그래서 `"pull_request_target" not in text` 같은
텍스트 가드는 자기 주석에 걸려 오탐한다. `yaml.safe_load` 로 파싱하면 주석은
애초에 보이지 않으므로 이 문제가 구조적으로 사라진다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "requirements-lock-sync.yml"

HELPER = "scripts/refresh_requirements_lock.sh"
REQUIRED_PYTHON = "3.11"
TRIGGER_PATHS = ["scripts/requirements.txt"]


def _workflow() -> dict:
    """파싱된 워크플로우. 파일이 없으면 아래 단언들이 vacuous 해지므로 실패시킨다."""
    assert WORKFLOW.is_file(), (
        f"{WORKFLOW.relative_to(REPO_ROOT)} 가 없다. 이름을 바꿨거나 삭제했다면 이 가드도 "
        "함께 옮길 것 — 그러지 않으면 아무것도 지키지 않는다."
    )
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{WORKFLOW.name}: 최상위가 매핑이 아니다"
    return data


def _triggers(wf: dict) -> dict:
    """`on:` 블록.

    PyYAML 은 YAML 1.1 규칙으로 무인용 `on` 을 불리언 `True` 로 읽는다. 두 키를 다
    본다 — 한쪽만 보면 인용 방식이 바뀔 때 조용히 빈 dict 가 되어 vacuous 해진다.
    """
    raw = wf.get("on", wf.get(True))
    assert isinstance(raw, dict), f"{WORKFLOW.name}: `on:` 블록을 읽지 못했다 (얻은 값: {raw!r})"
    return raw


def _steps(wf: dict) -> list[dict]:
    out: list[dict] = []
    for job in (wf.get("jobs") or {}).values():
        if isinstance(job, dict):
            out.extend(s for s in (job.get("steps") or []) if isinstance(s, dict))
    assert out, f"{WORKFLOW.name}: step 을 하나도 찾지 못했다 — 잡 구조가 바뀌었다"
    return out


def test_workflow_exists() -> None:
    """카나리. 파일이 사라지면 나머지 단언이 조용히 통과하는 대신 여기서 실패한다."""
    _workflow()


def test_does_not_use_pull_request_target() -> None:
    """write 토큰 + PR head 코드 실행은 권한 상승 패턴이다(설계 §5.2).

    `pip-compile` 은 의존성 sdist 를 빌드하며 임의 코드를 실행할 수 있으므로, 이
    워크플로우는 특히 위험하다. 방향: 존재 금지.
    """
    triggers = _triggers(_workflow())
    assert "pull_request_target" not in triggers, (
        f"{WORKFLOW.name}: `pull_request_target` 트리거가 생겼다. 이 워크플로우는 PR head 의 "
        "코드(pip-compile → sdist 빌드)를 실행하므로 write 토큰과 결합하면 권한 상승이 된다. "
        "커밋백이 필요하면 `pull_request` 를 유지하고 푸시만 별도 토큰으로 하라(설계 §5.1~§5.2)."
    )


def test_trigger_paths_are_limited_to_requirements_txt() -> None:
    """락만 바뀐 푸시는 트리거하지 않아야 한다 — 커밋백 도입 시 무한 루프 방지(설계 §5.4).

    방향: 정확히 일치. 경로가 늘어나면(특히 `requirements.lock` 이 들어오면) 재확인이
    필요하므로 넓어지는 것도 red 다.
    """
    pull_request = _triggers(_workflow()).get("pull_request")
    assert isinstance(pull_request, dict), (
        f"{WORKFLOW.name}: `pull_request` 트리거가 없거나 매핑이 아니다 (얻은 값: {pull_request!r})"
    )
    assert pull_request.get("paths") == TRIGGER_PATHS, (
        f"{WORKFLOW.name}: `paths` 가 {TRIGGER_PATHS} 가 아니다 "
        f"(현재: {pull_request.get('paths')!r}). `requirements.lock` 이 포함되면 커밋백을 "
        "붙였을 때 자기 자신을 다시 트리거한다."
    )


def test_python_is_pinned_to_the_lock_generation_version() -> None:
    """락은 3.11 에서 생성됐다. 다른 마이너로 만들면 내용이 달라진다(설계 §5.5).

    방향: 정확히 일치. 올리는 것도 red 다 — 올릴 때는 커밋된 락을 같은 버전으로
    재생성해 byte 수준 영향을 먼저 확인해야 한다.
    """
    setup = [s for s in _steps(_workflow()) if str(s.get("uses") or "").startswith("actions/setup-python@")]
    assert setup, f"{WORKFLOW.name}: setup-python step 이 없다 — 버전 고정이 사라졌다"
    for step in setup:
        version = str((step.get("with") or {}).get("python-version") or "")
        assert version == REQUIRED_PYTHON, (
            f"{WORKFLOW.name}: python-version 이 '{REQUIRED_PYTHON}' 이 아니다 (현재: {version!r}). "
            "락 생성 버전이 바뀌면 무관 패키지까지 drift 한다. 의도적으로 올린다면 커밋된 "
            "락을 새 버전으로 재생성해 diff 를 먼저 확인하고 이 가드의 상수도 갱신할 것."
        )


def test_regeneration_stays_in_place() -> None:
    """`--upgrade` 없이 기존 락을 앵커로 재생성해야 한다(설계 §3).

    앵커가 있으면 requirements.txt 에서 실제로 바뀐 패키지만 이동하고 무관 패키지의
    상류 drift 가 0 이다. `--upgrade` 가 붙으면 그 전제가 깨져 봇 PR 하나가 전 의존성을
    끌어올린다. 방향: 플래그 존재 금지.
    """
    calls = [s for s in _steps(_workflow()) if HELPER in str(s.get("run") or "")]
    assert calls, (
        f"{WORKFLOW.name}: `{HELPER}` 를 호출하는 step 이 없다. 재생성 방식을 직접 인라인 "
        "pip-compile 로 바꿨다면 in-place 앵커 성질을 새로 검증하고 이 가드를 다시 써야 한다."
    )
    for step in calls:
        run = str(step.get("run") or "")
        assert "--upgrade" not in run, (
            f"{WORKFLOW.name}: 헬퍼 호출에 `--upgrade` 가 붙었다 (step: {step.get('name')!r}). "
            "무관 패키지까지 상류로 끌어올려 '봇이 올린 그 패키지만' 이라는 전제가 깨진다."
        )


def test_drift_fails_the_job() -> None:
    """재생성 결과가 어긋나면 잡이 실패해야 한다.

    green 으로 끝나면 이 워크플로우 자체가 fail-open 신호가 된다 — 나중에 차단 게이트가
    느슨해졌을 때 아무도 모른다. 방향: 실패 경로 존재 + 그 step 이 blocking.
    """
    failing = [
        s for s in _steps(_workflow()) if "drift" in str(s.get("if") or "") and "exit 1" in str(s.get("run") or "")
    ]
    assert failing, (
        f"{WORKFLOW.name}: drift 조건에 걸린 `exit 1` step 이 없다. 락이 어긋나는데 잡이 "
        "green 이면 이 워크플로우가 '동기 확인됨' 으로 오독된다."
    )
    for step in failing:
        assert not step.get("continue-on-error"), (
            f"{WORKFLOW.name}: drift 실패 step '{step.get('name')}' 에 continue-on-error 가 "
            "붙었다. 실패가 흡수되면 exit 1 이 아무 의미가 없다."
        )


def test_best_effort_steps_do_not_include_the_failure_path() -> None:
    """`continue-on-error` 는 PR 코멘트처럼 **없어도 신호가 남는** step 에만 허용한다.

    dependabot 런은 토큰이 read-only 로 축소돼 코멘트가 403 이 될 수 있고, 그건 흡수해도
    된다 — 권위 있는 출력은 step summary + artifact 이고 위 실패 step 이 잡을 red 로
    만든다. 반대로 요약·업로드·실패 step 이 흡수되면 신호가 사라진다.
    """
    absorbed = [s for s in _steps(_workflow()) if s.get("continue-on-error")]
    for step in absorbed:
        run = str(step.get("run") or "")
        assert "exit 1" not in run, (
            f"{WORKFLOW.name}: '{step.get('name')}' 이 continue-on-error 인데 exit 1 을 한다 — "
            "실패가 흡수되므로 아무 효과가 없다."
        )
        assert "GITHUB_STEP_SUMMARY" not in run, (
            f"{WORKFLOW.name}: '{step.get('name')}' 이 continue-on-error 인데 step summary 를 "
            "쓴다 — 조용히 실패하면 사람이 볼 유일한 diff 가 사라진다."
        )
        assert not str(step.get("uses") or "").startswith("actions/upload-artifact@"), (
            f"{WORKFLOW.name}: artifact 업로드가 continue-on-error 다 — 조용히 실패하면 재생성된 락을 내려받을 수 없다."
        )


@pytest.mark.parametrize("field", ["contents", "pull-requests"])
def test_permissions_are_declared_explicitly(field: str) -> None:
    """토큰 권한을 명시한다. 생략하면 저장소 기본값(넓을 수 있음)을 상속한다."""
    permissions = _workflow().get("permissions")
    assert isinstance(permissions, dict), (
        f"{WORKFLOW.name}: 최상위 `permissions:` 가 없다 — 기본 토큰 권한을 그대로 상속한다."
    )
    assert field in permissions, f"{WORKFLOW.name}: `permissions.{field}` 가 선언되지 않았다"
    assert permissions.get("contents") == "read", (
        f"{WORKFLOW.name}: `contents` 가 read 가 아니다 (현재: {permissions.get('contents')!r}). "
        "이 워크플로우는 커밋백을 하지 않으므로 write 가 필요 없다. 커밋백을 도입한다면 "
        "설계 §5.1~§5.2 를 먼저 다시 읽을 것."
    )
