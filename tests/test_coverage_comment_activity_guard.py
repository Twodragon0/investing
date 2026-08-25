"""`python-coverage-comment-action` 의 `ACTIVITY` 배선 가드.

## 왜 있나

v3 → v4 bump 는 `ACTIVITY` 입력을 도입했다. 지정하지 않으면 액션이 **휴리스틱으로
추론**한다 — 업스트림 문서도 "기본 휴리스틱이 대부분의 경우 동작한다" 고만 말한다.

이 저장소는 그 "대부분" 이 아니다. 커버리지 파이프라인이 두 워크플로우로 쪼개져 있다:

| 워크플로우 | 트리거 | 하는 일 | 필요 activity |
|---|---|---|---|
| `code-quality.yml` | push → main | 데이터 브랜치에 저장 | `save_coverage_data_files` |
| `coverage-comment.yml` | `workflow_run` + `GITHUB_PR_RUN_ID` | PR 코멘트 | `post_comment` |

추론이 틀리면 **CI 는 green 인 채로** 커버리지 배지가 갱신을 멈추거나 PR 코멘트가
사라진다. 실패가 red 로 드러나지 않는 종류라서, 명시적 배선을 테스트로 고정한다.

`ACTIVITY` 를 지우고 싶어지는 순간이 이 가드가 존재하는 이유다 — "기본값으로도
되던데" 는 관측이 아니라 추측이고, 관측하려면 배지·코멘트를 며칠 지켜봐야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_ACTION = "py-cov-action/python-coverage-comment-action"

# activity → 그 activity 가 요구하는 최소 권한 (업스트림 문서)
_REQUIRED_PERMISSION = {
    "save_coverage_data_files": ("contents", "write"),
    "post_comment": ("pull-requests", "write"),
    "process_pr": ("pull-requests", "write"),
}


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _action_steps(wf: dict) -> list[tuple[str, dict]]:
    """(job_id, step) for every step that uses the coverage-comment action."""
    out: list[tuple[str, dict]] = []
    for job_id, job in (wf.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if _ACTION in str(step.get("uses", "")):
                out.append((job_id, step))
    return out


_CALL_SITES = [
    ("code-quality.yml", "save_coverage_data_files"),
    ("coverage-comment.yml", "post_comment"),
]


@pytest.mark.parametrize(("workflow", "expected"), _CALL_SITES, ids=lambda v: str(v))
def test_activity_is_explicit(workflow: str, expected: str) -> None:
    wf = _load(workflow)
    steps = _action_steps(wf)
    assert steps, f"{workflow} 에서 {_ACTION} 사용처를 찾지 못했다 — 가드가 no-op 이 됐다"

    for job_id, step in steps:
        activity = (step.get("with") or {}).get("ACTIVITY")
        assert activity, (
            f"{workflow}:{job_id} 의 {_ACTION} 스텝에 ACTIVITY 가 없다. "
            "v4 는 지정하지 않으면 휴리스틱으로 추론하는데, 이 저장소는 저장/코멘트를 "
            "두 워크플로우로 쪼개 쓴다. 추론이 틀리면 CI 는 green 인 채로 배지 갱신이나 "
            "PR 코멘트가 조용히 멈춘다."
        )
        assert activity == expected, f"{workflow}:{job_id} 의 ACTIVITY 가 {activity!r} 다 — {expected!r} 여야 한다"


@pytest.mark.parametrize(("workflow", "expected"), _CALL_SITES, ids=lambda v: str(v))
def test_permissions_cover_the_activity(workflow: str, expected: str) -> None:
    """activity 마다 요구 권한이 다르다 — 부족하면 그 잡이 조용히 실패한다."""
    wf = _load(workflow)
    key, value = _REQUIRED_PERMISSION[expected]

    # 잡 수준 permissions 가 있으면 그것이, 없으면 워크플로우 수준이 적용된다.
    for job_id, _step in _action_steps(wf):
        job_perms = (wf["jobs"][job_id] or {}).get("permissions")
        perms = job_perms if job_perms is not None else wf.get("permissions")
        assert isinstance(perms, dict), f"{workflow}:{job_id} 에 permissions 블록이 없다"
        assert perms.get(key) == value, (
            f"{workflow}:{job_id} 는 ACTIVITY={expected} 를 쓰므로 `{key}: {value}` 가 필요하다(got {perms.get(key)!r})"
        )


def test_all_call_sites_are_covered() -> None:
    """새 사용처가 생기면 이 가드에 등록되지 않은 채 지나가지 않게 한다."""
    declared = {w for w, _ in _CALL_SITES}
    found = {p.name for p in _WORKFLOWS.glob("*.yml") if _ACTION in p.read_text(encoding="utf-8")}
    assert found == declared, (
        f"{_ACTION} 사용처가 바뀌었다. 발견={sorted(found)} 등록={sorted(declared)}. "
        "새 사용처에도 ACTIVITY 를 명시하고 _CALL_SITES 에 추가할 것."
    )
