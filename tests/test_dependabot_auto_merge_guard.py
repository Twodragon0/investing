"""`dependabot-auto-merge.yml` 불변식 가드.

## 왜 있나

이 워크플로우는 patch PR 에서 **항상 red** 였고, 원인이 저장소 설정 두 개였다
(2026-09-15 실측):

* `can_approve_pull_request_reviews: false` → `gh pr review --approve` 가
  "GitHub Actions is not permitted to approve pull requests" 로 죽는다.
  `shell: bash -e` 라서 그 뒤 머지 스텝은 실행조차 되지 않았다.
* `allow_auto_merge: false` → `gh pr merge --auto` 도 실패한다.

두 호출 모두 **저장소 설정이 바뀌지 않는 한 성공할 수 없다.** 그래서 이 가드는
"설정을 켜라"가 아니라 "그 설정에 의존하는 호출을 되돌리지 마라"를 지킨다. 되돌리면
CI 로그를 읽기 전까지는 티가 나지 않는다 — 워크플로우는 red 지만 required check 가
아니라 머지를 막지 않고, PR 은 그냥 영영 열린 채 쌓인다(#1319·#1320 이 그랬다).

셋째 축은 교착이다. 대기 루프가 **자기 자신의 체크**를 제외하지 않으면 자기가
끝나기를 기다리다 타임아웃까지 간다. 제외 키(`SELF_CHECK`)와 잡 이름은 서로 다른
곳에 있어 한쪽만 바꾸기 쉬우므로 일치를 강제한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"
_JOB_ID = "auto-merge"


@pytest.fixture(scope="module")
def parsed() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(parsed: dict) -> dict:
    jobs = parsed["jobs"]
    assert _JOB_ID in jobs, (
        f"잡 id {_JOB_ID!r} 가 없다. 이름을 바꿨다면 이 가드의 _JOB_ID 도 함께 갱신할 것 — "
        "아니면 가드가 조용히 아무것도 지키지 않는다."
    )
    return jobs[_JOB_ID]


def _run_scripts(job: dict) -> list[tuple[str, str]]:
    """(스텝 이름, 셸 주석을 걷어낸 run 텍스트).

    주석을 걷어내는 이유는 `tests/_workflow_scan.py` 의 규약과 같다 — 이 파일의
    설명 주석("`--approve` 는 쓰지 않는다")이 자기 가드를 red 로 만들면 안 된다.
    """
    out: list[tuple[str, str]] = []
    for step in job.get("steps", []):
        run = step.get("run")
        if isinstance(run, str):
            name = step.get("name") or "<unnamed step>"
            out.append((name, ws.strip_shell_comments(run)))
    return out


class TestNoCallsThatCannotSucceed:
    def test_does_not_approve_the_pull_request(self, job: dict) -> None:
        offenders = [name for name, run in _run_scripts(job) if "--approve" in run]
        assert not offenders, (
            f"`--approve` 가 다시 들어왔다(스텝: {offenders}). 저장소 설정 "
            "`can_approve_pull_request_reviews` 가 false 인 한 이 호출은 성공할 수 없고, "
            "`bash -e` 때문에 뒤의 머지 스텝까지 죽인다. main 에는 required review 가 "
            "없으므로 승인은 머지 조건도 아니다."
        )

    def test_does_not_use_github_auto_merge(self, job: dict) -> None:
        offenders = [name for name, run in _run_scripts(job) if "--auto" in run]
        assert not offenders, (
            f"`gh pr merge --auto` 가 다시 들어왔다(스텝: {offenders}). 저장소 설정 "
            "`allow_auto_merge` 가 false 라 실패하고, 설령 켜더라도 required status "
            "check 가 없어 **체크 결과와 무관하게** 머지된다 "
            "(docs/devsecops/branch-protection.md §5.3)."
        )


class TestMergeWaitsForChecks:
    def _merge_step(self, job: dict) -> tuple[str, str]:
        hits = [(name, run) for name, run in _run_scripts(job) if "gh pr merge" in run]
        assert len(hits) == 1, f"`gh pr merge` 를 호출하는 스텝이 정확히 1개여야 한다(현재 {len(hits)}개)"
        return hits[0]

    def test_merge_is_preceded_by_a_polling_loop(self, job: dict) -> None:
        name, run = self._merge_step(job)
        assert "while" in run and "gh pr checks" in run, (
            f"머지 스텝({name!r})에 체크 대기 루프가 없다. required check 가 없는 저장소라 "
            "이 루프가 유일한 대기 수단이다 — 빠지면 체크가 도는 중에 머지된다."
        )

    def test_self_check_name_matches_the_job_name(self, job: dict) -> None:
        """제외 키와 잡 이름이 어긋나면 자기 자신을 기다리다 타임아웃한다."""
        name, _ = self._merge_step(job)
        env = next(step.get("env", {}) for step in job["steps"] if step.get("name") == name)
        self_check = env.get("SELF_CHECK")
        job_check_name = job.get("name", _JOB_ID)
        assert self_check == job_check_name, (
            f"SELF_CHECK={self_check!r} 인데 잡의 체크 이름은 {job_check_name!r} 이다. "
            "대기 루프가 자기 자신을 제외하지 못해 교착한다."
        )

    def test_check_query_does_not_discard_output_on_nonzero_exit(self, job: dict) -> None:
        """`gh pr checks` 는 정상 경로에서도 non-zero 다(대기 8, 실패 1).

        종료코드로 판정해 출력을 버리면 루프가 재시도만 하다 타임아웃한다. 2026-09-15
        스텁 하네스 실측: `|| raw=""` 형태에서는 **전부 통과한 PR 도 머지되지 않았다**
        (rc=1, merged=NO). 실패 방향이 안전하기 때문에 CI 로그를 읽기 전까지 티가
        나지 않는다.
        """
        name, run = self._merge_step(job)
        assert 'raw=""' not in run, (
            f"머지 스텝({name!r})이 `gh pr checks` 의 종료코드로 출력을 버리고 있다. "
            "`|| true` 로 종료코드만 삼키고 판정은 내용으로 할 것."
        )

    def test_unknown_check_states_are_treated_as_failure(self, job: dict) -> None:
        """모르는 state 를 통과로 분류하면 조용히 머지된다 — fail-closed 여야 한다."""
        _, run = self._merge_step(job)
        assert "| not)" in run, (
            "체크 state 분류가 화이트리스트 부정(`| not)`) 형태가 아니다. 실패 목록을 "
            "열거하는 방식으로 바꾸면 새 state 가 생겼을 때 통과로 새어 나간다."
        )


class TestStillScopedToDependabotPatches:
    def test_job_is_gated_on_dependabot_actor(self, job: dict) -> None:
        assert "dependabot[bot]" in str(job.get("if", "")), (
            "actor 게이트가 사라지면 아무 PR 이나 이 워크플로우로 머지될 수 있다."
        )

    def test_merge_is_gated_on_semver_patch(self, job: dict) -> None:
        merge_steps = [
            step for step in job["steps"] if isinstance(step.get("run"), str) and "gh pr merge" in step["run"]
        ]
        assert merge_steps, "`gh pr merge` 스텝을 찾지 못했다"
        for step in merge_steps:
            assert "version-update:semver-patch" in str(step.get("if", "")), (
                f"머지 스텝({step.get('name')!r})에 patch 게이트가 없다. minor/major 까지 "
                "자동 머지되면 사람 검토 없이 동작 변경이 들어온다."
            )
