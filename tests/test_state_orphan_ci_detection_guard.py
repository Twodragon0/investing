"""수집 러너에서의 `_state` 고아 temp 탐지 가드.

## 왜 있나

`scripts/tools/check_state_orphans.py` 는 원자적 쓰기(`mkstemp` → `os.replace`)
도중 프로세스가 죽어 남은 temp 를 보고한다. 2026-09-07 백필 런이 ~900KB 짜리 4개를
남긴 게 실측 사례다.

그런데 그 탐지는 `scripts/ops/health_and_logrotate.sh` — 즉 **로컬/서버 헬스체크**에만
연결돼 있었다. 누출이 GitHub 러너에서 일어나면 러너가 폐기되면서 증거까지 같이
사라지므로 아무도 모른다. `.gitignore` 의 `_state/*.tmp` 는 그게 *커밋되는* 것만
막는다 — 누출 자체는 여전히 무음이다.

## 임계값이 이 가드의 핵심이다

도구의 기본 임계값은 **60분**이고, 그건 서버용으로 옳다: 로컬에서 방금 만들어진
temp 는 지금 쓰이고 있을 수 있으므로 보고하면 안 된다.

러너에서는 그 전제가 뒤집힌다.

* 러너는 몇 분 살고 폐기된다. 누출된 temp 가 60분을 넘길 방법이 없다.
* 검사 시점에 수집 스크립트는 **이미 종료했다**. 동시에 쓰고 있는 writer 가
  존재할 수 없으므로, 남아 있는 temp 는 정의상 고아다.

그래서 기본값을 그대로 쓰면 이 검사는 **영원히 0건을 보고한다** — 켜져 있지만
아무것도 잡지 않는, 최악의 종류의 green. 낮은 임계값을 명시적으로 넘겨야 한다.

## 크래시했을 때 돌아야 한다

temp 가 남는 경우는 대부분 수집 스크립트가 죽었을 때다. `if:` 없이 두면 GitHub 이
앞 step 실패 시 이 step 을 건너뛰므로, **정작 필요한 순간에만 안 도는** 검사가 된다.

가드는 파일 원문이 아니라 파싱된 `run:` 값을 읽는다. 원문을 읽으면 이 파일이나
워크플로우의 설명 주석이 스스로에게 매칭된다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _REPO_ROOT / ".github" / "actions" / "python-collect" / "action.yml"

_TOOL = "scripts/tools/check_state_orphans.py"

# 러너 수명(수 분)보다 확실히 짧아야 한다. 5분도 넉넉한 상한이다 — 검사 시점에
# 수집 프로세스는 이미 종료했으므로 원칙적으로는 0 이어도 안전하다.
_MAX_ALLOWED_THRESHOLD_MINUTES = 5.0


def _steps() -> list[dict]:
    doc = yaml.safe_load(_ACTION.read_text(encoding="utf-8"))
    return [s for s in doc["runs"]["steps"] if isinstance(s, dict)]


def _orphan_steps() -> list[dict]:
    return [s for s in _steps() if isinstance(s.get("run"), str) and _TOOL in s["run"]]


def test_collect_action_checks_for_state_orphans() -> None:
    steps = _orphan_steps()
    assert steps, (
        f"{_ACTION.relative_to(_REPO_ROOT)} does not run {_TOOL}. A temp leaked on an "
        "ephemeral runner vanishes with the runner; gitignoring `_state/*.tmp` only "
        "stops it being committed, not from happening unnoticed."
    )


def test_threshold_is_low_enough_to_ever_fire() -> None:
    """기본 60분을 쓰면 러너에서 이 검사는 구조적으로 0건이다."""
    for step in _orphan_steps():
        match = re.search(r"--min-age-minutes[= ]+([0-9]+(?:\.[0-9]+)?)", step["run"])
        assert match, (
            f"{step.get('name')!r} runs {_TOOL} without an explicit --min-age-minutes. "
            "The 60-minute default is a server threshold; a runner lives minutes, so "
            "the check would report zero orphans forever."
        )
        threshold = float(match.group(1))
        assert threshold <= _MAX_ALLOWED_THRESHOLD_MINUTES, (
            f"{step.get('name')!r} uses --min-age-minutes {threshold:g}, which exceeds "
            f"a runner's lifetime. Nothing it could detect would ever be that old."
        )


def test_check_runs_even_when_the_collector_crashed() -> None:
    """temp 가 남는 건 대개 스크립트가 죽었을 때다 — 그때 건너뛰면 의미가 없다."""
    for step in _orphan_steps():
        condition = str(step.get("if", "")).strip()
        assert "always()" in condition, (
            f"{step.get('name')!r} has `if: {condition or '<none>'}`. GitHub skips "
            "steps after a failed one, so without `always()` the orphan check would "
            "run only when nothing leaked."
        )


def test_check_does_not_fail_the_collection() -> None:
    """탐지는 경고다. 고아 하나 때문에 이미 수집된 포스트의 커밋을 막지 않는다."""
    for step in _orphan_steps():
        run = step["run"]
        assert "::warning" in run, f"{step.get('name')!r} must surface findings as a `::warning` annotation"
        assert step.get("continue-on-error") is not True, (
            f"{step.get('name')!r} uses continue-on-error. Swallow the tool's exit "
            "status explicitly inside the script instead, so a genuine crash of the "
            "step is still visible."
        )
