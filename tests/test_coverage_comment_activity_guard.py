"""`python-coverage-comment-action` 의 `ACTIVITY` 배선 가드.

## 왜 있나

v3 → v4 bump 는 `ACTIVITY` 입력을 도입했다. 지정하지 않으면 액션이 **휴리스틱으로
추론**한다 — 업스트림 문서도 "기본 휴리스틱이 대부분의 경우 동작한다" 고만 말한다.

이 저장소는 그 "대부분" 이 아니다. 커버리지 파이프라인이 두 워크플로우로 쪼개져 있다:

| 워크플로우 | 트리거 | 하는 일 | 필요 activity |
|---|---|---|---|
| `code-quality.yml` | push → main | 데이터 브랜치에 저장(배지) | `save_coverage_data_files` |
| `code-quality.yml` | `pull_request` | 코멘트 본문 계산 → artifact | `process_pr` |
| `coverage-comment.yml` | `workflow_run` + `GITHUB_PR_RUN_ID` | 그 artifact 를 PR 에 붙임 | `post_comment` |

추론이 틀리면 **CI 는 green 인 채로** 커버리지 배지가 갱신을 멈추거나 PR 코멘트가
사라진다. 실패가 red 로 드러나지 않는 종류라서, 명시적 배선을 테스트로 고정한다.

`ACTIVITY` 를 지우고 싶어지는 순간이 이 가드가 존재하는 이유다 — "기본값으로도
되던데" 는 관측이 아니라 추측이고, 관측하려면 배지·코멘트를 며칠 지켜봐야 한다.

두 번째 행(`process_pr`)은 처음엔 없었다. 그래서 코멘트 경로가 통째로 죽어 있었는데도
이 가드의 원래 두 테스트는 통과했다 — `test_post_comment_has_a_producer` 참고.
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


#: 워크플로우 -> 그 파일이 써야 하는 activity 전수. code-quality.yml 은 두 개를 쓴다
#: (PR 에서 `process_pr`, main push 에서 `save_coverage_data_files`).
_CALL_SITES: dict[str, set[str]] = {
    "code-quality.yml": {"process_pr", "save_coverage_data_files"},
    "coverage-comment.yml": {"post_comment"},
}

#: `post_comment` 가 찾는 artifact 이름 = 액션의 `COMMENT_ARTIFACT_NAME` 기본값.
_COMMENT_ARTIFACT = "python-coverage-comment-action"


def _activities(workflow: str) -> set[str]:
    return {(step.get("with") or {}).get("ACTIVITY") for _job, step in _action_steps(_load(workflow))}


@pytest.mark.parametrize(("workflow", "expected"), sorted(_CALL_SITES.items()), ids=lambda v: str(v))
def test_activity_is_explicit(workflow: str, expected: set[str]) -> None:
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
        assert activity in expected, (
            f"{workflow}:{job_id} 의 ACTIVITY 가 {activity!r} 다 — {sorted(expected)} 중 하나여야 한다"
        )

    assert _activities(workflow) == expected, (
        f"{workflow} 의 activity 집합이 {sorted(_activities(workflow))} 다 — {sorted(expected)} 여야 한다"
    )


@pytest.mark.parametrize(("workflow", "expected"), sorted(_CALL_SITES.items()), ids=lambda v: str(v))
def test_permissions_cover_the_activity(workflow: str, expected: set[str]) -> None:
    """activity 마다 요구 권한이 다르다 — 부족하면 그 잡이 조용히 실패한다."""
    wf = _load(workflow)

    # 잡 수준 permissions 가 있으면 그것이, 없으면 워크플로우 수준이 적용된다.
    for job_id, step in _action_steps(wf):
        activity = (step.get("with") or {}).get("ACTIVITY")
        key, value = _REQUIRED_PERMISSION[activity]
        job_perms = (wf["jobs"][job_id] or {}).get("permissions")
        perms = job_perms if job_perms is not None else wf.get("permissions")
        assert isinstance(perms, dict), f"{workflow}:{job_id} 에 permissions 블록이 없다"
        assert perms.get(key) == value, (
            f"{workflow}:{job_id} 는 ACTIVITY={activity} 를 쓰므로 `{key}: {value}` 가 필요하다(got {perms.get(key)!r})"
        )

    assert expected  # 파라미터가 실제로 쓰이는지 — 빈 집합이면 위 루프가 vacuous 다


def test_post_comment_has_a_producer() -> None:
    """`post_comment` 소비자에는 `process_pr` 생산자와 artifact 업로드가 짝지어져야 한다.

    이 가드의 원래 두 테스트(ACTIVITY 명시 / 권한)는 v4 배선이 **완전히 깨진 상태에서도
    통과했다**. `post_comment` 는 커버리지를 계산하지 않는다 — `process_pr` 가 남긴
    ``python-coverage-comment-action`` artifact 를 받아 붙일 뿐인데, 그 생산자가 아예
    없었다. 액션은 artifact 를 못 찾으면 `NoArtifact` 를 내고도 **exit 0** 으로 끝나서
    잡은 green 이었다 (2026-08-25 run 32797674530, PR #1219 — 코멘트 0건).

    배지(`save_coverage_data_files`)는 같은 기간 정상 동작했으므로, 배지만 보고
    "파이프라인이 산다" 고 판단할 수 없다. 그래서 생산자-소비자 짝을 정적으로 고정한다.
    """
    # `_CALL_SITES` 가 아니라 워크플로우 파일에서 직접 읽는다 — 레지스트리는 기대값이고,
    # 여기서 물어야 하는 건 실제 배선이다.
    workflows = {p.name for p in _WORKFLOWS.glob("*.yml") if _ACTION in p.read_text(encoding="utf-8")}
    consumers = {w for w in workflows if "post_comment" in _activities(w)}
    producers = {w for w in workflows if "process_pr" in _activities(w)}
    assert consumers, "post_comment 사용처가 사라졌다 — 이 가드가 no-op 이 됐다"
    assert producers, (
        f"post_comment 를 쓰는 워크플로우({sorted(consumers)})가 있는데 process_pr 생산자가 없다. "
        "코멘트는 조용히 사라지고 잡은 green 으로 끝난다."
    )

    for workflow in producers:
        wf = _load(workflow)
        uploads = [
            step
            for job in (wf.get("jobs") or {}).values()
            for step in (job.get("steps") or [])
            if "actions/upload-artifact" in str(step.get("uses", ""))
            and (step.get("with") or {}).get("name") == _COMMENT_ARTIFACT
        ]
        assert uploads, (
            f"{workflow} 가 ACTIVITY=process_pr 를 쓰지만 `{_COMMENT_ARTIFACT}` 이름으로 "
            "업로드하는 스텝이 없다. post_comment 는 정확히 이 이름으로 찾으므로 "
            "코멘트가 붙지 않는다(그래도 잡은 green)."
        )
        for step in uploads:
            assert "COMMENT_FILE_WRITTEN" in str(step.get("if", "")), (
                f"{workflow} 의 `{_COMMENT_ARTIFACT}` 업로드에 "
                "`steps.<id>.outputs.COMMENT_FILE_WRITTEN == 'true'` 조건이 없다. "
                "액션이 코멘트를 직접 붙인 경우엔 파일을 쓰지 않으므로 업로드가 실패한다."
            )


def test_all_call_sites_are_covered() -> None:
    """새 사용처가 생기면 이 가드에 등록되지 않은 채 지나가지 않게 한다."""
    declared = set(_CALL_SITES)
    found = {p.name for p in _WORKFLOWS.glob("*.yml") if _ACTION in p.read_text(encoding="utf-8")}
    assert found == declared, (
        f"{_ACTION} 사용처가 바뀌었다. 발견={sorted(found)} 등록={sorted(declared)}. "
        "새 사용처에도 ACTIVITY 를 명시하고 _CALL_SITES 에 추가할 것."
    )
