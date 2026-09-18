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
아니라 머지를 막지 않고, PR 은 그냥 영영 열린 채 쌓인다(#1319 · #1320).

## 이 가드의 1차 버전이 왜 부족했나 (2026-09-15 리뷰 실측)

초판은 8개 중 4개가 **문자열 존재 검사**였고, 리뷰어가 던진 뮤테이션 5종이 전부
통과했다. 그중 둘은 이 가드가 막겠다고 선언한 위험 그 자체였다:

* 화이트리스트에 `"FAILURE","TIMED_OUT"` 을 **추가**해도 통과했다 — `"| not)"` 이라는
  형태만 봤지 집합의 내용을 보지 않았다. 실패한 체크를 통과로 분류하는 회귀가
  무방비였다.
* `gh pr merge` 를 루프 **앞으로** 옮겨도 통과했다 — 같은 `run:` 안에 `while` 과
  `gh pr checks` 가 어디든 있으면 됐다. "머지 전에 대기" 라는 이름과 달리 순서를
  보지 않았다.
* deadline 검사를 루프 끝으로 옮겨도 통과했다 — 무한 재시도 스핀이 복원되는데
  침묵했다.

교훈은 저장소 메모 `feedback_guard_must_discriminate_not_just_red` 와 같다. red 가
되는 것만으로는 부족하고, **주장하는 위험과 같은 방향**의 변형에 red 여야 한다.
그래서 아래 가드는 형태가 아니라 값(집합의 원소, 토큰 위치, 숫자 관계)을 단언한다.

## 2차 버전도 부족했다 (2026-09-18 리뷰 실측)

값을 보도록 고쳤는데도 뮤테이션 24종 중 **9종이 22개 가드를 전부 통과**했다. 같은
병이 남아 있었다 — docstring 은 위험을 이름으로 선언하는데 단언은 문자열 존재만 본다.
가장 무거운 둘:

* **실패 체크 abort 블록 4줄을 통째로 지워도 통과**했다. `IN(...)` 집합의 내용은
  제대로 봤지만, 그 분류 결과가 실제로 머지를 막는지는 아무도 보지 않았다.
  스텁 `gh` 로 실행해 보니 FAILURE 체크를 안고 머지됐다.
* **patch 게이트의 안쪽 `&&` 를 `||` 로 바꿔도 통과**했다. 그러면 자동 경로에서
  update-type 과 무관하게 항상 참이라 semver-major 가 사람 검토 없이 머지된다.
  옛 단언은 두 문자열의 **존재**만 봤다 — 주석은 "묶여 있어야 한다" 는 결합을
  주장했지만 단언은 동거만 확인한 것이다.

그래서 이 파일은 이제 두 종류의 가드를 함께 쓴다.

* `TestMergeStepBehaviour` — 머지 스텝의 `run:` 을 스텁 `gh` 와 함께 **실제로
  실행**하고 종료코드와 `gh pr merge` 호출 여부를 관측한다.
* `TestMergeGateTruthTable` — `if:` 식을 파싱해 **진리표**로 평가한다. 연산자나
  괄호를 바꾸면 값이 달라지므로 문자열로는 빠져나갈 수 없다.

새 가드를 여기에 더할 때는 같은 질문을 먼저 하라 — **내가 막겠다는 회귀를 주입하면
이 단언이 red 가 되는가?** 답이 "그 문자열이 사라지니까" 라면 아직 부족하다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests import _workflow_scan as ws

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"
_JOB_ID = "auto-merge"

#: 체크가 이 state 로 끝났으면 머지하면 안 된다. 통과 화이트리스트에 하나라도 들어가면
#: 실패한 체크를 안고 머지하게 된다 — 이 워크플로우의 최악 실패 양식이다.
_FAILURE_STATES = frozenset(
    {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
)
#: 아직 끝나지 않은 체크. 대기 집합에서 빠지면 그 체크를 기다리지 않고 머지한다.
_PENDING_STATES = frozenset({"PENDING", "QUEUED", "IN_PROGRESS"})
#: 끝난 체크. 대기 집합에 들어가면 영원히 기다린다(교착).
_TERMINAL_OK_STATES = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})

#: `IN(...)` 의 인자 영역만 떼어 낸다. 안쪽 반복(`(?:"[A-Z_]+"\s*,?\s*)+`)으로 쓰면
#: 중첩 수량자가 되어 지수 백트래킹이 가능하다 — CodeQL `py/redos` 가 이 PR 에서
#: 실제로 잡았다. 괄호 안을 통째로 잡고 state 추출은 아래 정규식에 맡긴다.
_IN_SET_RE = re.compile(r"IN\(([^)]*)\)")
_STATE_RE = re.compile(r'"([A-Z_]+)"')


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

    주석을 걷어내는 이유는 `tests/_workflow_scan.py` 의 규약과 같다 — 이 워크플로우의
    설명 주석(`--approve` 를 왜 뺐는지 등)이 자기 가드를 red 로 만들면 안 된다.
    """
    out: list[tuple[str, str]] = []
    for step in job.get("steps", []):
        run = step.get("run")
        if isinstance(run, str):
            name = step.get("name") or "<unnamed step>"
            out.append((name, ws.strip_shell_comments(run)))
    return out


def _merge_step(job: dict) -> tuple[str, str]:
    hits = [(name, run) for name, run in _run_scripts(job) if "gh pr merge" in run]
    assert len(hits) == 1, f"`gh pr merge` 를 호출하는 스텝이 정확히 1개여야 한다(현재 {len(hits)}개)"
    return hits[0]


def _merge_step_env(job: dict) -> dict:
    name, _ = _merge_step(job)
    for step in job["steps"]:
        if step.get("name") == name:
            return step.get("env", {}) or {}
    pytest.fail(f"머지 스텝 {name!r} 의 env 를 찾지 못했다")


def _in_sets(run: str) -> list[set[str]]:
    """`jq` 의 `IN("A","B",...)` 인자를 집합으로 뽑는다."""
    return [set(_STATE_RE.findall(body)) for body in _IN_SET_RE.findall(run)]


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
        # 토큰 경계를 요구한다. 부분문자열로 보면 `--auto-...` 형태의 다른 플래그가
        # 생겼을 때 오탐한다.
        flag = re.compile(r"(?<![-\w])--auto(?![-\w])")
        offenders = [name for name, run in _run_scripts(job) if flag.search(run)]
        assert not offenders, (
            f"`gh pr merge --auto` 가 다시 들어왔다(스텝: {offenders}). 저장소 설정 "
            "`allow_auto_merge` 가 false 라 실패하고, 설령 켜더라도 required status "
            "check 가 없어 **체크 결과와 무관하게** 머지된다 "
            "(docs/devsecops/branch-protection.md §5.3)."
        )


class TestStateClassificationIsFailClosed:
    """화이트리스트의 **내용**을 본다. 형태만 보면 fail-open 회귀가 통과한다."""

    def test_pass_whitelist_excludes_every_failure_state(self, job: dict) -> None:
        _, run = _merge_step(job)
        sets = _in_sets(run)
        assert sets, "`IN(...)` state 집합을 하나도 찾지 못했다 — 분류 로직이 사라졌거나 형태가 바뀌었다"
        leaked = sorted(sets[0] & _FAILURE_STATES)
        assert not leaked, (
            f"통과 화이트리스트에 실패 state 가 들어 있다: {leaked}. 실패한 체크를 안고 "
            "머지하게 된다 — 이 워크플로우가 막으려는 바로 그 상황이다."
        )

    def test_pass_whitelist_covers_terminal_success_states(self, job: dict) -> None:
        _, run = _merge_step(job)
        missing = sorted(_TERMINAL_OK_STATES - _in_sets(run)[0])
        assert not missing, (
            f"통과 화이트리스트에서 {missing} 가 빠졌다. 정상 종료한 체크가 실패로 분류돼 모든 PR 이 머지되지 않는다."
        )

    def test_waiting_set_is_pending_only(self, job: dict) -> None:
        _, run = _merge_step(job)
        sets = _in_sets(run)
        assert len(sets) >= 2, "대기 state 집합을 찾지 못했다"
        waiting = sets[1]
        missing = sorted(_PENDING_STATES - waiting)
        assert not missing, f"대기 집합에서 {missing} 가 빠졌다 — 진행 중인 체크를 기다리지 않고 머지한다."
        terminal = sorted(waiting & _TERMINAL_OK_STATES)
        assert not terminal, f"대기 집합에 종료 state {terminal} 가 들어 있다 — 영원히 기다린다(교착)."


class TestMergeWaitsForChecks:
    def test_merge_comes_after_the_polling_loop(self, job: dict) -> None:
        """순서를 단언한다. 존재만 보면 머지를 루프 앞으로 옮겨도 통과한다."""
        name, run = _merge_step(job)
        loop = run.index("while")
        query = run.index("gh pr checks")
        merge = run.index("gh pr merge")
        assert loop < query < merge, (
            f"머지 스텝({name!r})의 순서가 while({loop}) → gh pr checks({query}) → "
            f"gh pr merge({merge}) 가 아니다. 대기 코드가 남아 있어도 머지가 먼저면 "
            "아무것도 기다리지 않는다."
        )

    def test_deadline_check_precedes_the_query_inside_the_loop(self, job: dict) -> None:
        """상한 검사가 조회 뒤에 있으면 조회 실패 경로가 상한을 통과하지 못한다.

        2026-09-15 스텁 실측: 그 배치에서는 조회가 계속 실패할 때 잡 타임아웃(30분)
        까지 공회전했다. 실패 방향이 조용해서 로그를 읽기 전엔 드러나지 않는다.
        """
        _, run = _merge_step(job)
        loop = run.index("while")
        deadline = run.index('"$SECONDS" -ge "$deadline"')
        query = run.index("gh pr checks")
        assert loop < deadline < query, (
            f"상한 검사 위치가 while({loop}) → deadline({deadline}) → query({query}) 가 "
            "아니다. 루프 맨 앞에 두어 모든 경로가 상한에 걸리게 할 것."
        )

    def test_check_query_does_not_discard_output_on_nonzero_exit(self, job: dict) -> None:
        """`gh pr checks` 는 정상 경로에서도 non-zero 다(대기 8, 실패 1).

        종료코드로 판정해 출력을 버리면 루프가 재시도만 하다 타임아웃한다. 2026-09-15
        스텁 하네스 실측: 그 형태에서는 **전부 통과한 PR 도 머지되지 않았다**
        (rc=1, merged=NO). 실패 방향이 안전하기 때문에 CI 로그를 읽기 전까지 티가
        나지 않는다.
        """
        _, run = _merge_step(job)
        line = next(ln.strip() for ln in run.splitlines() if "gh pr checks" in ln)
        assert line.endswith('|| true)"'), (
            f'체크 조회 라인이 `|| true)"` 로 끝나지 않는다: {line!r}. 종료코드를 명령 치환 '
            "안에서 삼키고, 판정은 출력 내용으로 할 것 — 바깥에서 `|| raw=` 로 처리하면 "
            "정상 경로(exit 8)의 출력까지 버린다."
        )

    def test_break_requires_at_least_one_non_self_check(self, job: dict) -> None:
        """`waiting == 0` 만 보면 '볼 체크가 아직 없다' 를 '전부 통과' 로 읽는다."""
        _, run = _merge_step(job)
        assert '"$total" -gt 0' in run, (
            "탈출 조건이 non-self 체크 개수를 보지 않는다. 목록이 자기 자신뿐인 순간에 즉시 머지된다."
        )

    def test_break_requires_a_stable_check_set(self, job: dict) -> None:
        """늦게 생성되는 commit status 와의 경주를 막는 안정화 창.

        2026-09-14 #1320 실측: `Vercel Preview Comments` 가 잡 시작 +96초에 **처음**
        목록에 나타났다. 그 전에 빠져나가면 그 체크는 대기 대상이 아니었으므로 그냥
        건너뛰게 된다.
        """
        _, run = _merge_step(job)
        assert '"$current" = "$previous"' in run, (
            "탈출 조건에 직전 폴링과의 동등성 검사가 없다. 아직 생성되지 않은 체크를 건너뛰고 머지할 수 있다."
        )

    def test_merge_is_pinned_to_the_observed_head(self, job: dict) -> None:
        """마지막 폴링과 머지 사이에 head 가 바뀌면 검증되지 않은 커밋이 들어간다."""
        _, run = _merge_step(job)
        assert "--match-head-commit" in run, (
            "`gh pr merge` 가 관측한 head SHA 에 고정돼 있지 않다. dependabot rebase 나 "
            "락 commit-back 이 폴링 직후 들어오면 검증하지 않은 트리를 머지한다."
        )
        # 옛 단언은 `... or run.index("headRefOid") < run.index("gh pr merge")` 였는데,
        # `gh pr merge` 가 스크립트의 **마지막 줄**이라 오른쪽이 항상 참이었다 —
        # `or` 때문에 왼쪽의 진짜 검사가 무력화된 vacuous 단언이다(2026-09-18 실측:
        # 캡처를 머지 직전으로 옮겨도 22/22 green). 체크 조회보다 앞서는지를 본다.
        assert run.index("headRefOid") < run.index("gh pr checks"), (
            "head SHA 를 머지 직전이 아니라 **체크 조회와 같은 시점**에 캡처할 것 — "
            "나중에 다시 읽으면 마지막 폴링 이후 들어온 커밋의 head 에 고정하게 되어 "
            "고정이 TOCTOU 를 닫는다는 전제가 사라진다. "
            "행동 단언은 TestMergeStepBehaviourRegressions::test_head_is_re_read_on_every_poll."
        )


class TestSelfExclusionCannotDeadlock:
    def test_self_check_name_matches_the_job_name(self, job: dict) -> None:
        """제외 키와 잡 이름이 어긋나면 자기 자신을 기다리다 타임아웃한다."""
        self_check = _merge_step_env(job).get("SELF_CHECK")
        job_check_name = job.get("name", _JOB_ID)
        assert self_check == job_check_name, (
            f"SELF_CHECK={self_check!r} 인데 잡의 체크 이름은 {job_check_name!r} 이다. "
            "대기 루프가 자기 자신을 제외하지 못해 교착한다."
        )

    def test_self_workflow_matches_the_workflow_name(self, job: dict, parsed: dict) -> None:
        """이름만으로 제외하면 동명의 잡이 생겼을 때 진짜 체크가 조용히 빠진다.

        실측(2026-09-15 `gh pr checks 1324`): 이 저장소에는 이미 동일 이름 체크가
        중복 존재한다(`verify` ×2, `Supply-chain lock gate` ×2). 제네릭 잡 이름이
        관례이므로 워크플로우 이름까지 맞춰야 한다.
        """
        env = _merge_step_env(job)
        assert env.get("SELF_WORKFLOW") == parsed["name"], (
            f"SELF_WORKFLOW={env.get('SELF_WORKFLOW')!r} 가 워크플로우 이름 {parsed['name']!r} 과 다르다."
        )
        _, run = _merge_step(job)
        assert "$wf" in run and ".workflow" in run, (
            "제외 조건이 워크플로우 이름을 쓰지 않는다. 다른 워크플로우의 동명 잡이 "
            "제외 대상이 되어 그 체크를 기다리지 않는다."
        )

    def test_polling_deadline_fits_inside_the_job_timeout(self, job: dict) -> None:
        """상한이 잡 타임아웃을 넘으면 러너가 먼저 죽여 상한 로직이 죽은 코드가 된다."""
        deadline = int(_merge_step_env(job)["DEADLINE_SECONDS"])
        budget = int(job["timeout-minutes"]) * 60
        assert deadline < budget, (
            f"DEADLINE_SECONDS={deadline} 가 잡 타임아웃 {budget}s 이상이다. 폴링 상한이 먼저 걸리도록 여유를 둘 것."
        )


class TestRuntimeConfiguration:
    """워크플로우 바깥 껍데기(권한·동시성). 둘 다 회귀가 조용하다."""

    def test_permissions_allow_the_merge_call(self, parsed: dict) -> None:
        """다운그레이드하면 머지가 403 으로 죽는다.

        red 이긴 하지만 이 워크플로우의 red 는 머지를 막지 않으므로, 알아채기까지
        다음 Dependabot PR 을 기다려야 한다. 저장소 기본값이 read 라
        (`default_workflow_permissions: read`, 2026-09-15 실측) 명시가 필수다.
        """
        perms = parsed.get("permissions")
        assert isinstance(perms, dict), (
            f"최상위 permissions 가 매핑이 아니다: {perms!r}. `write-all` 이나 누락은 "
            "security-scan.yml 의 Workflow Permissions Audit 대상이기도 하다."
        )
        assert perms.get("contents") == "write", (
            f"contents={perms.get('contents')!r} — `gh pr merge` 가 403 으로 죽는다."
        )
        assert perms.get("pull-requests") == "write", (
            f"pull-requests={perms.get('pull-requests')!r} — PR 조회·머지에 필요하다."
        )

    def test_concurrency_is_scoped_to_the_pull_request(self, parsed: dict) -> None:
        """폴링 런이 최대 25분 살아 있으므로 중복 런이 실제로 겹친다.

        그룹이 전역 상수면 `cancel-in-progress` 가 **다른 PR** 의 런까지 죽인다 —
        `supply-chain-lock.yml` 에서 런 58%가 그렇게 취소된 실측이 있다(#1199).
        저장소 전역 가드는 `tests/test_workflow_concurrency_scope_guard.py` 이고,
        여기서는 블록의 **존재**까지 요구한다(전역 가드는 없으면 통과시킨다).
        """
        concurrency = parsed.get("concurrency")
        assert isinstance(concurrency, dict), (
            "concurrency 블록이 없다. `synchronize` 마다 새 런이 뜨고 이전 폴링 런이 "
            "남아 둘이 동시에 `gh pr merge` 를 호출한다."
        )
        group = str(concurrency.get("group", ""))
        assert "github.event.pull_request.number" in group, (
            f"concurrency.group={group!r} 이 PR 로 스코프돼 있지 않다. 전역 상수 그룹은 다른 PR 의 런을 교차 취소한다."
        )


class TestManualDispatchPath:
    """수동 경로(`workflow_dispatch`)는 자동 경로의 게이트를 **더한 것**이지 완화가 아니다.

    2026-09-16 검토에서 "게이트를 PR 작성자 기준으로 완화하고 커밋 작성자 검사로
    되막는" 안이 철회됐다. 이유 둘:

    * `on: pull_request` 런은 PR 의 merge-ref 파일을 실행하므로, 브랜치에 푸시할 수
      있는 주체가 그 검사를 **같은 푸시로 지울 수 있다**. 반면 현행 actor 게이트는
      잡 자체가 뜨지 않아 self-modification 에 면역이다.
    * 그 커밋 검사가 사람 커밋을 막으므로, 완화의 유일한 편익(사람이 락을 고친 뒤
      자동 머지가 도는 것)을 그대로 상쇄해 순효과가 0 이었다.

    그래서 아래 가드는 **완화 회귀**를 잡는 데 초점을 둔다.
    """

    def test_automatic_path_still_keys_on_the_pusher(self, job: dict) -> None:
        """`github.actor` 가 사라지면 완화 회귀다.

        `"dependabot[bot]" in if` 만 보면 `github.event.pull_request.user.login ==
        'dependabot[bot]'` 로 바꿔도 통과한다 — 문자열이 그대로 남기 때문이다.
        판별하려면 **어느 필드를 보는지**를 단언해야 한다.
        """
        gate = str(job.get("if", ""))
        assert "github.actor" in gate, (
            f"잡 게이트가 `github.actor` 를 보지 않는다: {gate!r}. 푸시 주체 기준 게이트는 "
            "워크플로우 수정으로 우회할 수 없는 유일한 통제다 — 작성자 기준으로 바꾸면 "
            "그 성질을 잃는다."
        )
        assert "pull_request.user" not in gate, (
            f"잡 게이트가 PR 작성자 기준으로 완화됐다: {gate!r}. 2026-09-16 검토에서 철회된 변경이다."
        )

    def test_dispatch_target_is_verified_as_dependabot_pr(self, job: dict) -> None:
        """수동 경로에는 metadata 가 없다 — 대상 확인이 없으면 아무 PR 이나 머지된다."""
        steps = [s for s in job["steps"] if "workflow_dispatch" in str(s.get("if", ""))]
        checks = [
            s
            for s in steps
            # 조회를 **실제로 하는지** 본다. `author` 문자열 존재만 보면 조회 라인을
            # 지워도 `case "$author"` 같은 잔해에 매칭돼 통과한다 — 2026-09-16
            # 뮤테이션 D2 로 실측된 vacuous 케이스다.
            if isinstance(s.get("run"), str) and "gh pr view" in s["run"] and "author" in s["run"]
        ]
        assert checks, (
            "`workflow_dispatch` 경로에 PR 작성자를 **조회**하는 스텝이 없다. 번호만 "
            "넣으면 아무 PR 이나 이 경로로 머지할 수 있다."
        )
        run = ws.strip_shell_comments(checks[0]["run"])
        assert "exit 1" in run, (
            "작성자 확인 스텝이 중단 경로를 갖지 않는다. 조회만 하고 통과시키면 확인하지 않은 것과 같다."
        )
        for spelling in ("app/dependabot", "dependabot[bot]"):
            assert spelling in run, (
                f"작성자 확인이 {spelling!r} 표기를 받지 않는다. `gh` 는 봇을 "
                "`app/dependabot` 으로, 이벤트 페이로드는 `dependabot[bot]` 으로 준다 "
                "(2026-09-16 실측). 한쪽만 받으면 게이트가 조용히 항상-false 가 된다."
            )

    def test_metadata_step_is_scoped_to_the_automatic_path(self, job: dict) -> None:
        """`fetch-metadata` 는 dependabot PR 컨텍스트를 전제한다 — dispatch 에서 돌리지 않는다."""
        meta = [s for s in job["steps"] if "fetch-metadata" in str(s.get("uses", ""))]
        assert len(meta) == 1, f"fetch-metadata 스텝이 정확히 1개여야 한다(현재 {len(meta)}개)"
        assert "github.event_name == 'pull_request'" in str(meta[0].get("if", "")), (
            "fetch-metadata 가 자동 경로로 한정돼 있지 않다. dispatch 런에서 실패하면 수동 경로 전체가 죽는다."
        )

    def test_concurrency_group_covers_the_dispatch_path(self, parsed: dict) -> None:
        """dispatch 런에는 `pull_request.number` 가 없어 `github.ref` 로 폴백한다.

        그러면 서로 다른 PR 의 수동 런이 같은 그룹에 묶이고, `cancel-in-progress` 가
        한쪽을 죽인다.
        """
        group = str(parsed["concurrency"]["group"])
        assert "inputs.pr" in group, (
            f"concurrency.group={group!r} 이 dispatch 입력을 반영하지 않는다. 서로 다른 PR 의 수동 런이 교차 취소된다."
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
            gate = str(step.get("if", ""))
            assert "version-update:semver-patch" in gate, (
                f"머지 스텝({step.get('name')!r})에 patch 게이트가 없다. minor/major 까지 "
                "자동 머지되면 사람 검토 없이 동작 변경이 들어온다."
            )
            # patch 게이트가 **자동 경로에 묶여** 있어야 한다. 떼어내면 수동 경로용
            # `||` 분기가 patch 조건을 통째로 우회시킨다.
            assert "github.event_name == 'pull_request'" in gate, (
                f"patch 게이트가 자동 경로(`pull_request`)에 묶여 있지 않다: {gate!r}. "
                "수동 경로 분기와 OR 로만 이어지면 자동 경로에서도 patch 제한이 풀린다."
            )


# ---------------------------------------------------------------------------
# 실행 관측 가드 — 문자열 검사로는 못 잡는 것들
# ---------------------------------------------------------------------------
#
# 2026-09-18 제3자 리뷰 실측: 뮤테이션 24종 중 **9종이 22개 가드를 전부 통과**했다.
# 그중 가장 무거운 것이 아래 C1 이다 — 실패 체크 abort 블록 4줄을 **통째로 지워도**
# 22/22 green 이었고, 스텁 `gh` 로 실행해 보니 FAILURE 체크를 안고 머지됐다.
#
# 원인은 방어가 한 칸 어긋나 있던 것이다. `TestStateClassificationIsFailClosed` 는
# `IN(...)` **집합의 내용**을 제대로 보지만, 그 분류 결과가 실제로 머지를 막는지는
# 아무도 보지 않았다. `failed` 변수는 계산되고 버려져도 침묵했다.
#
# 그래서 이 절은 텍스트를 보지 않는다. 머지 스텝의 `run:` 을 스텁 `gh` 와 함께
# **실제로 실행**하고, 종료코드와 `gh pr merge` 호출 여부를 관측한다. 이렇게 하면
# "어떻게 썼는가" 가 아니라 "무엇이 일어나는가" 를 단언하게 되어, 구현을 바꿔도
# 성질이 유지되는 한 green 이다.

_STUB_GH = """#!/usr/bin/env bash
# 스텁 `gh`. 모든 호출을 $GH_CALLS 에 기록하고 시나리오대로 응답한다.
printf '%s\\n' "$*" >> "$GH_CALLS"
case "$1 $2" in
  "pr view")
    # 기본은 **고정 head**. 실제 PR 은 폴링 중에 head 가 바뀌지 않는 것이 정상이고,
    # 안정화 창은 같은 커밋 안에서만 세므로 여기서 매번 바꾸면 창이 영영 안 찬다.
    # `GH_HEAD_VARY=1` 일 때만 매 호출 다른 SHA 를 준다 — head 변경 시 창이
    # 초기화되는지 관측하는 시나리오 전용이다.
    if [ "${GH_HEAD_VARY:-0}" = "1" ]; then
      v="$(grep -c '^pr view' "$GH_CALLS")"
    else
      v=1
    fi
    printf 'head%036d\n' "$v"
    ;;
  "pr checks")
    # 폴링 회차마다 다른 응답을 주기 위해 호출 횟수를 센다.
    n="$(grep -c '^pr checks' "$GH_CALLS")"
    f="${GH_CHECKS_DIR}/${n}.json"
    [ -f "$f" ] || f="${GH_CHECKS_DIR}/last.json"
    cat "$f"
    # 실제 `gh pr checks` 는 대기 중이면 exit 8, 실패가 있으면 exit 1 로 끝난다.
    exit "${GH_CHECKS_RC:-8}"
    ;;
  "pr merge")
    echo "MERGED"
    ;;
esac
"""


def _merge_step_raw(job: dict) -> str:
    """머지 스텝의 `run:` **원문**. 실행 대상이므로 주석을 걷어내지 않는다."""
    hits = [s["run"] for s in job["steps"] if isinstance(s.get("run"), str) and "gh pr merge" in s["run"]]
    assert len(hits) == 1, f"`gh pr merge` 스텝이 정확히 1개여야 한다(현재 {len(hits)}개)"
    return hits[0]


def _execute_merge_step(
    job: dict,
    tmp_path: Path,
    polls: list[str],
    *,
    checks_rc: str = "8",
    deadline: str = "60",
    head_varies: bool = False,
) -> tuple[int, str, list[str]]:
    """머지 스텝의 `run:` 을 스텁 `gh` 로 실행하고 (rc, 출력, gh 호출목록) 을 준다.

    `polls` 는 폴링 **회차별** `gh pr checks` 응답(JSON 문자열)이다. 회차가 모자라면
    마지막 응답이 계속 반복된다 — 늦게 뜨는 체크 같은 시간 의존 시나리오를 표현할 수
    있게 하려는 것이다.

    `SELF_CHECK`/`SELF_WORKFLOW` 는 워크플로우의 `env:` 에서 그대로 읽는다. 여기에
    값을 베껴 두면 워크플로우 쪽이 바뀌었을 때 이 테스트만 옛 값을 보며 green 이 된다.
    """
    bash = shutil.which("bash")
    if not bash or not shutil.which("jq"):
        pytest.skip("이 가드는 `bash` 와 `jq` 를 실제로 실행한다 — 둘 다 있어야 의미가 있다")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "gh"
    stub.write_text(_STUB_GH, encoding="utf-8")
    stub.chmod(0o755)

    checks_dir = tmp_path / "checks"
    checks_dir.mkdir()
    for idx, payload in enumerate(polls, start=1):
        (checks_dir / f"{idx}.json").write_text(payload, encoding="utf-8")
    (checks_dir / "last.json").write_text(polls[-1], encoding="utf-8")

    calls = tmp_path / "calls.txt"
    calls.write_text("", encoding="utf-8")

    step_env = _merge_step_env(job)
    env = {
        **os.environ,
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALLS": str(calls),
        "GH_CHECKS_DIR": str(checks_dir),
        "GH_CHECKS_RC": checks_rc,
        "PR_URL": "https://github.com/o/r/pull/1",
        "GH_TOKEN": "stub-token-not-a-secret",
        "SELF_CHECK": str(step_env["SELF_CHECK"]),
        "SELF_WORKFLOW": str(step_env["SELF_WORKFLOW"]),
        # 안정화 창 길이는 워크플로우가 정한 값을 그대로 쓴다. 테스트가 줄여 잡으면
        # 정작 검증하려는 창을 검증하지 못한다.
        "STABLE_POLLS": str(step_env["STABLE_POLLS"]),
        "GH_HEAD_VARY": "1" if head_varies else "0",
        # 실행 시간을 줄이기 위한 값. 폴링 간격과 상한만 줄이고 로직은 그대로다.
        "DEADLINE_SECONDS": deadline,
        "POLL_SECONDS": "0",
    }
    proc = subprocess.run(
        [bash, "-c", _merge_step_raw(job)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    invoked = [line for line in calls.read_text(encoding="utf-8").splitlines() if line.strip()]
    return proc.returncode, proc.stdout + proc.stderr, invoked


def _check(name: str, state: str, workflow: str = "Some Workflow") -> dict:
    return {"name": name, "state": state, "workflow": workflow}


def _payload(*checks: dict) -> str:

    return json.dumps(list(checks))


class TestMergeStepBehaviour:
    """머지 스텝을 **실행해** 관측한다. 텍스트 단언으로는 아래 회귀를 못 잡는다."""

    def test_a_failed_check_aborts_without_merging(self, job: dict, tmp_path: Path) -> None:
        """실패 체크가 하나라도 있으면 머지 호출 자체가 없어야 한다.

        2026-09-18 실측: 실패 체크 abort 블록 4줄을 지워도 기존 22개 가드가 전부
        통과했고, 실행해 보니 rc=0 으로 **머지됐다**. 분류가 옳아도 그 결과를 쓰지
        않으면 아무 의미가 없다 — 이 단언이 그 간극을 막는다.
        """
        rc, output, calls = _execute_merge_step(
            job,
            tmp_path,
            [_payload(_check("quality", "SUCCESS"), _check("verify", "FAILURE"))],
            checks_rc="1",
        )
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"실패한 체크가 있는데 머지를 호출했다: {merges}. 이 워크플로우의 최악 실패 "
            f"양식이다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0, f"실패 체크를 보고도 성공으로 끝났다(rc={rc}).\n--- 출력 ---\n{output}"
        assert "verify" in output, (
            f"중단은 했으나 어느 체크 때문인지 남기지 않았다 — 진단 불가능한 red 다.\n--- 출력 ---\n{output}"
        )

    def test_all_green_merges_pinned_to_the_polled_head(self, job: dict, tmp_path: Path) -> None:
        """반대 방향. 전부 통과면 실제로 머지해야 하고, head 고정이 실려야 한다.

        이 단언이 없으면 "아무것도 머지하지 않는" 구현이 위 테스트를 통과한다.
        """
        green = _payload(_check("quality", "SUCCESS"), _check("verify", "SUCCESS"))
        rc, output, calls = _execute_merge_step(job, tmp_path, [green])
        merges = [c for c in calls if c.startswith("pr merge")]
        assert rc == 0, f"전부 통과인데 머지에 실패했다(rc={rc}).\n--- 출력 ---\n{output}"
        assert len(merges) == 1, f"머지 호출이 정확히 1회여야 한다(현재 {len(merges)}회): {merges}"
        assert f"--match-head-commit head{1:036d}" in merges[0], (
            f"머지가 폴링 때 관측한 head 에 고정되지 않았다: {merges[0]!r}. 고정이 빠지면 "
            "마지막 폴링 이후 들어온 커밋이 검증 없이 머지된다."
        )


# ---------------------------------------------------------------------------
# GitHub expression 진리표 가드
# ---------------------------------------------------------------------------
#
# 2026-09-18 실측: patch 게이트의 안쪽 `&&` 를 `||` 로 바꿔도 22/22 green 이었다.
# 그러면 `if:` 가 `(pull_request || patch) || dispatch` 가 되어 **자동 경로에서
# update-type 과 무관하게 항상 참**이다 — semver-major dependabot PR 이 사람 검토
# 없이 머지된다.
#
# 통과한 이유는 옛 단언이 두 문자열의 **존재**만 봤기 때문이다. 주석은 "patch 게이트가
# 자동 경로에 **묶여** 있어야 한다" 는 결합을 주장했는데, 단언은 결합이 아니라
# 동거만 확인했다. 그래서 여기서는 식을 파싱해 **진리표**로 단언한다 — 연산자를
# 바꾸거나 괄호를 옮기면 값이 달라지므로 문자열로는 빠져나갈 수 없다.

_EXPR_TOKEN_RE = re.compile(r"\s*(\(|\)|\|\||&&|==|!=|'[^']*'|[A-Za-z_][A-Za-z0-9_.\-]*)")


def _tokenize_expression(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        match = _EXPR_TOKEN_RE.match(expr, pos)
        assert match, f"GitHub expression 을 토큰화하지 못했다 — {expr[pos : pos + 40]!r} 부근"
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


def _eval_expression(expr: str, context: dict[str, str]) -> bool:
    """`if:` 식을 평가한다. `==`/`!=`/`&&`/`||`/괄호/문자열/컨텍스트 경로만 지원한다.

    모르는 컨텍스트 경로는 빈 문자열로 넘기지 않고 **에러로 만든다**. 조용히 falsy 로
    두면 식이 새 컨텍스트를 쓰기 시작했을 때 진리표가 엉뚱한 값을 검증하면서 green 이
    된다 — 가드가 스스로 무력해지는 경로다.
    """
    tokens = _tokenize_expression(expr)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        lexeme = tokens[pos]
        pos += 1
        return lexeme

    def primary() -> object:
        lexeme = take()
        if lexeme == "(":
            value = or_expr()
            assert take() == ")", f"괄호가 닫히지 않았다: {expr!r}"
            return value
        if lexeme.startswith("'"):
            return lexeme[1:-1]
        assert lexeme in context, (
            f"진리표가 모르는 컨텍스트 경로가 식에 들어왔다: {lexeme!r}. 이 가드의 "
            f"context 에 값을 추가해 의도한 진리표를 다시 정의할 것 — 그냥 두면 "
            f"가드가 엉뚱한 식을 검증하며 통과한다."
        )
        return context[lexeme]

    def comparison() -> object:
        left = primary()
        lexeme = peek()
        if lexeme in ("==", "!="):
            take()
            right = primary()
            return (left == right) if lexeme == "==" else (left != right)
        return left

    def and_expr() -> object:
        # GitHub 의 `&&`/`||` 는 불리언이 아니라 **피연산자 값**을 돌려주는 단축평가다.
        # 파이썬의 `and`/`or` 와 같은 의미이므로 그대로 옮긴다.
        value = comparison()
        while peek() == "&&":
            take()
            right = comparison()
            value = right if value else value
        return value

    def or_expr() -> object:
        value = and_expr()
        while peek() == "||":
            take()
            right = and_expr()
            value = value if value else right
        return value

    result = or_expr()
    assert pos == len(tokens), f"식을 끝까지 소비하지 못했다(남은 토큰 {tokens[pos:]!r}): {expr!r}"
    return bool(result)


def _merge_step_if(job: dict) -> str:
    steps = [s for s in job["steps"] if isinstance(s.get("run"), str) and "gh pr merge" in s["run"]]
    assert len(steps) == 1, f"`gh pr merge` 스텝이 정확히 1개여야 한다(현재 {len(steps)}개)"
    gate = steps[0].get("if")
    assert isinstance(gate, str) and gate.strip(), "머지 스텝에 `if:` 게이트가 없다 — 모든 PR 이 머지 경로를 탄다."
    return gate


_EVENT = "github.event_name"
_UPDATE_TYPE = "steps.metadata.outputs.update-type"

#: (이벤트, update-type) → 머지 스텝이 돌아야 하는가.
#:
#: 자동 경로(`pull_request`)는 patch 만, 수동 경로(`workflow_dispatch`)는 사람이
#: 명시적으로 부른 것이므로 update-type 제한을 두지 않는다 — 범위 제약 bump 가
#: semver-major 로 **오분류**되어 자동 경로를 못 타는 실측(#1321·#1329) 때문에
#: 수동 경로까지 patch 로 묶으면 정작 막힌 PR 을 풀 수단이 사라진다.
_GATE_TRUTH_TABLE = [
    ("pull_request", "version-update:semver-patch", True),
    ("pull_request", "version-update:semver-minor", False),
    ("pull_request", "version-update:semver-major", False),
    ("pull_request", "", False),
    ("workflow_dispatch", "version-update:semver-major", True),
    ("workflow_dispatch", "", True),
    ("push", "version-update:semver-patch", False),
    ("schedule", "version-update:semver-patch", False),
]


class TestMergeGateTruthTable:
    @pytest.mark.parametrize(("event", "update_type", "expected"), _GATE_TRUTH_TABLE)
    def test_merge_gate_evaluates_as_specified(self, job: dict, event: str, update_type: str, expected: bool) -> None:
        gate = _merge_step_if(job)
        actual = _eval_expression(gate, {_EVENT: event, _UPDATE_TYPE: update_type})
        assert actual is expected, (
            f"머지 게이트가 event_name={event!r}, update-type={update_type!r} 에서 "
            f"{actual} 로 평가된다(기대 {expected}).\n게이트: {gate!r}\n"
            "자동 경로에서 patch 제한이 풀리면 semver-minor/major 가 사람 검토 없이 머지된다."
        )


class TestMergeStepBehaviourRegressions:
    """리뷰(2026-09-18)가 뚫은 나머지 뮤테이션을 실행으로 고정한다.

    전부 "탈출 조건을 느슨하게 하면 무엇이 머지되는가" 를 묻는다. 문자열 존재 검사는
    앵커를 `: '...'` no-op 으로 남기면 그대로 통과하므로 여기서는 텍스트를 보지 않는다.
    """

    def _self_check(self, job: dict, state: str = "SUCCESS") -> dict:
        env = _merge_step_env(job)
        return _check(str(env["SELF_CHECK"]), state, str(env["SELF_WORKFLOW"]))

    def test_does_not_merge_when_only_its_own_check_exists(self, job: dict, tmp_path: Path) -> None:
        """자기 자신만 목록에 있는 순간은 "전부 통과" 가 아니라 "아직 볼 게 없다" 다.

        탈출 조건에서 체크 개수 검사가 빠지면(`&&`→`||`, 또는 조건만 제거) non-self
        체크가 0건인 첫 폴링에서 즉시 머지된다. 다른 워크플로우의 체크가 아직
        올라오지 않은 시점이므로 **아무것도 검증하지 않은 머지**다.
        """
        only_self = _payload(self._self_check(job))
        # 상한은 안정화 창(STABLE_POLLS 회 폴링)을 **채우고도 남을** 만큼 줘야 한다.
        # 짧게 잡으면 개수 검사를 없앤 변형도 머지에 도달하기 전에 상한에 걸려
        # 이 시나리오가 아무것도 판별하지 못한다(2026-09-18 하네스가 VACUOUS 로 잡음).
        rc, output, calls = _execute_merge_step(job, tmp_path, [only_self], deadline="25")
        polls_done = len([c for c in calls if c.startswith("pr checks")])
        assert polls_done >= 1, "폴링이 한 번도 일어나기 전에 끝났다 — 이 시나리오가 아무것도 검증하지 못한다."
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"non-self 체크가 0건인데 머지했다: {merges}. 목록이 자기 자신뿐인 순간은 "
            f"'전부 통과' 가 아니다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0, f"볼 체크가 없는데 성공으로 끝났다(rc={rc}).\n--- 출력 ---\n{output}"

    def test_waits_for_a_check_that_appears_late(self, job: dict, tmp_path: Path) -> None:
        """늦게 생성되는 commit status 를 건너뛰지 않는다.

        2026-09-14 #1320 실측: `Vercel Preview Comments` 가 잡 시작 +96초에 **처음**
        목록에 나타났다. 없는 체크는 대기 대상이 아니므로, 안정화 창이 없으면 그
        체크가 나타나기 전에 빠져나가 그냥 건너뛴다.

        1회차엔 통과 체크 하나만, 2회차에 실패 체크가 등장하는 시나리오다. 안정화
        창이 살아 있으면 2회차를 보고 중단하고, 없으면 1회차에서 머지한다 — 두 경우의
        관측 결과가 **다르므로** 판별력이 있다.
        """
        polls = [
            _payload(_check("quality", "SUCCESS")),
            _payload(_check("quality", "SUCCESS"), _check("Vercel Preview Comments", "FAILURE")),
        ]
        rc, output, calls = _execute_merge_step(job, tmp_path, polls)
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"늦게 나타난 실패 체크를 건너뛰고 머지했다: {merges}. 안정화 창이 없으면 "
            f"첫 폴링에서 빠져나간다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0 and "Vercel Preview Comments" in output, (
            f"늦게 나타난 체크를 포착하지 못했다(rc={rc}).\n--- 출력 ---\n{output}"
        )

    def test_does_not_exclude_a_same_named_check_from_another_workflow(self, job: dict, tmp_path: Path) -> None:
        """자기 제외는 이름과 워크플로우가 **둘 다** 맞을 때만이다.

        `and` 를 `or` 로 느슨하게 하면 다른 워크플로우의 동명 잡이 제외되어 그 체크를
        기다리지 않는다. 이 저장소에는 이미 동명 체크가 중복 존재한다
        (2026-09-15 `gh pr checks 1324`: `verify` ×2, `Supply-chain lock gate` ×2).

        여기서는 **남의 워크플로우**에 자기와 같은 이름의 실패 체크를 둔다. 제외가
        올바르면 실패로 잡혀 중단하고, 느슨하면 제외되어 머지까지 간다.
        """
        env = _merge_step_env(job)
        foreign = _check(str(env["SELF_CHECK"]), "FAILURE", "Some Other Workflow")
        polls = [_payload(foreign, _check("quality", "SUCCESS"))]
        rc, output, calls = _execute_merge_step(job, tmp_path, polls, checks_rc="1")
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"다른 워크플로우의 동명 체크를 자기 자신으로 오인해 제외하고 머지했다: {merges}. "
            f"제외는 이름과 워크플로우가 둘 다 맞을 때만이어야 한다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0, f"남의 실패 체크를 보고도 성공으로 끝났다(rc={rc}).\n--- 출력 ---\n{output}"

    def test_head_is_re_read_on_every_poll(self, job: dict, tmp_path: Path) -> None:
        """head 캡처가 폴링과 **같은 시점**이어야 `--match-head-commit` 이 의미를 갖는다.

        머지 직전에 다시 읽으면 마지막 폴링 이후 들어온 커밋의 head 를 읽어 거기에
        고정하므로, 검증하지 않은 트리를 그대로 머지한다 — 고정이 TOCTOU 를 닫는다는
        전제가 사라진다.

        옛 단언(`run.index("headRefOid") < run.index("gh pr merge")`)은 `gh pr merge`
        가 스크립트의 **마지막 줄**이라 항상 참이었다(vacuous). 대신 여기서는 조회
        횟수를 본다 — 루프 안에 있으면 폴링 회차만큼, 루프 밖이면 1회다.
        """
        green = _payload(_check("quality", "SUCCESS"))
        _, output, calls = _execute_merge_step(job, tmp_path, [green])
        views = len([c for c in calls if c.startswith("pr view")])
        checks = len([c for c in calls if c.startswith("pr checks")])
        assert views == checks, (
            f"head 조회 {views}회 / 체크 조회 {checks}회 — 두 값이 다르면 head 를 폴링과 "
            f"같은 시점에 읽고 있지 않다.\n--- 출력 ---\n{output}"
        )
        assert checks >= 2, (
            f"이 시나리오는 안정화 창 때문에 폴링이 2회 이상이어야 판별력이 있다(현재 {checks}회). "
            "루프 구조가 바뀌었다면 이 가드의 시나리오도 다시 설계할 것."
        )


#: GitHub App 이 올리는 commit status 가 잡 시작 뒤 **처음 목록에 나타나기까지** 걸린
#: 실측 최대치(초). 2026-09-14 PR #1320, `Vercel Preview Comments` = 96초.
#: 안정화 창이 이 값보다 짧으면 그 뒤에 나타나는 체크는 조회조차 되지 않는다.
_OBSERVED_STATUS_DELAY_SECONDS = 96


class TestStabilizationWindowCoversObservedDelay:
    """창의 **길이**를 단언한다. 창의 존재만 보면 30초짜리 창도 통과한다.

    2026-09-18 실측: `STABLE_POLLS` 도입 전에는 "직전 폴링과 동일" 한 번이면 빠져나가
    보장 창이 정확히 1 × POLL_SECONDS = 30초였다. 근거로 인용한 지연은 96초이므로
    3배 부족했고, 3회차에 처음 나타나는 **실패** 체크를 조회하지 않고 머지했다
    (스텁 재현: 폴링 2회 후 MERGED, rc=0).

    그때 사고가 나지 않은 이유는 이 루프 밖에 있었다 — `code-quality.yml` 의 PR
    트리거에 경로 필터가 없어 13.5분짜리 `quality` 가 모든 PR 에 붙었기 때문이다
    (#1328 실측). 이 루프가 통제하지 않는 외부 사실에 기대고 있었으므로, 그 사실이
    바뀌면 조용히 되살아난다. 그래서 창 길이를 **이 워크플로우 안에서** 고정한다.
    """

    def test_window_is_longer_than_the_measured_status_delay(self, job: dict) -> None:
        env = _merge_step_env(job)
        poll = int(str(env["POLL_SECONDS"]))
        stable = int(str(env["STABLE_POLLS"]))
        window = poll * stable
        assert window > _OBSERVED_STATUS_DELAY_SECONDS, (
            f"안정화 창이 {window}s(= POLL_SECONDS {poll} × STABLE_POLLS {stable})인데, "
            f"늦게 생성되는 commit status 의 실측 지연은 {_OBSERVED_STATUS_DELAY_SECONDS}s 다. "
            "창이 더 짧으면 그 뒤에 나타나는 체크는 조회되지 않고 머지된다 — 실패 체크여도."
        )

    def test_deadline_leaves_room_for_the_window(self, job: dict) -> None:
        """창이 상한을 넘으면 모든 PR 이 deadline red 로 끝난다(반대 방향 고장)."""
        env = _merge_step_env(job)
        window = int(str(env["POLL_SECONDS"])) * int(str(env["STABLE_POLLS"]))
        deadline = int(str(env["DEADLINE_SECONDS"]))
        assert window * 2 < deadline, (
            f"안정화 창 {window}s 가 상한 {deadline}s 에 비해 너무 크다. 체크가 끝난 뒤에도 "
            "창을 채우지 못해 정상 PR 이 timeout 으로 죽는다."
        )


class TestStabilizationWindowBehaviour:
    def test_catches_a_check_that_appears_after_the_first_confirmation(self, job: dict, tmp_path: Path) -> None:
        """첫 "동일 확인" 이후에 나타나는 체크도 포착해야 한다.

        창이 1폴링이던 시절의 실제 사고 형태다 — 2회차에서 빠져나가므로 3회차에
        처음 등장하는 실패 체크를 못 본다. `test_waits_for_a_check_that_appears_late`
        는 2회차에 등장하는 경우만 덮으므로 이 시나리오는 그 가드를 통과한다.
        """
        green = _payload(_check("quality", "SUCCESS"))
        late = _payload(_check("quality", "SUCCESS"), _check("Vercel Preview Comments", "FAILURE"))
        rc, output, calls = _execute_merge_step(job, tmp_path, [green, green, late])
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"세 번째 폴링에 나타난 실패 체크를 건너뛰고 머지했다: {merges}. 안정화 창이 "
            f"실측 지연({_OBSERVED_STATUS_DELAY_SECONDS}s)보다 짧다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0 and "Vercel Preview Comments" in output, (
            f"늦게 나타난 체크를 포착하지 못했다(rc={rc}).\n--- 출력 ---\n{output}"
        )

    def test_head_change_restarts_the_window(self, job: dict, tmp_path: Path) -> None:
        """안정 판정은 **같은 커밋 안에서만** 유효하다.

        head 가 바뀌면 그 커밋의 체크는 다시 생성되므로, 옛 커밋에서 센 안정 횟수를
        이어 쓰면 새 head 를 단 1회 관측하고 머지할 수 있다. `--match-head-commit` 은
        "관측한 커밋을 머지" 는 보장하지만 "그 커밋의 체크가 다 생성됐는지" 는
        보장하지 않는다.

        head 가 매 폴링 바뀌는 극단을 넣는다 — 창이 초기화되면 영영 차지 않아 머지가
        일어나지 않아야 한다. 초기화가 없으면 이름 집합이 같으므로 곧장 빠져나간다.
        """
        green = _payload(_check("quality", "SUCCESS"))
        rc, output, calls = _execute_merge_step(job, tmp_path, [green], head_varies=True, deadline="12")
        merges = [c for c in calls if c.startswith("pr merge")]
        assert not merges, (
            f"head 가 폴링마다 바뀌는데 머지했다: {merges}. 안정 판정이 커밋을 추적하지 "
            f"않으면 새 head 를 1회만 보고 머지한다.\n--- 출력 ---\n{output}"
        )
        assert rc != 0, f"창이 차지 않았는데 성공으로 끝났다(rc={rc}).\n--- 출력 ---\n{output}"
        assert len([c for c in calls if c.startswith("pr checks")]) >= 3, (
            "폴링이 3회 미만이면 이 시나리오가 창 초기화를 관측하지 못한다."
        )


class TestDiagnosticsAndResilience:
    """리뷰(2026-09-18)가 남긴 LOW 4건. 전부 "사고는 안 나지만 진단이 불가능" 계열이다.

    이 워크플로우는 실패해도 required check 가 아니라 아무도 막지 않는다. 그래서
    로그가 원인을 말해 주지 못하면 결함이 그대로 묻힌다 — #1319·#1320 이 그렇게
    쌓였다. 진단 가능성은 여기서 기능 요건이다.
    """

    def test_head_and_checks_stderr_go_to_separate_files(self, job: dict) -> None:
        """두 조회의 stderr 를 한 파일에 받으면 실패 사유가 빈칸이 된다.

        `gh pr checks` 가 성공하면 `2>"$file"` 리다이렉션이 파일을 truncate 한다.
        head 조회만 실패한 경우 재시도 로그가 그 빈 파일을 읽어 `재시도 ()` 가 된다
        — 주어도 틀리고(체크는 읽혔다) 사유도 없다. 25분을 돌고 deadline red 가 난
        뒤에는 인증 문제인지 URL 문제인지 구분할 수단이 없다.
        """
        _, run = _merge_step(job)
        redirects = set(re.findall(r'2>"\$(\w+)"', run))
        assert len(redirects) >= 2, (
            f"stderr 리다이렉션 대상이 {sorted(redirects)} 뿐이다. head 조회와 체크 조회가 "
            "같은 파일을 쓰면 한쪽 성공이 다른 쪽 실패 사유를 지운다."
        )
        assert "2>/dev/null" not in run.split("gh pr view")[1].split("\n")[0], (
            "head 조회가 stderr 를 버린다. 버리면 실패 사유를 영영 알 수 없다."
        )

    def test_malformed_json_is_retried_not_fatal(self, job: dict, tmp_path: Path) -> None:
        """비-JSON 응답 1회로 런 전체가 죽지 않아야 한다.

        `set -euo pipefail` 아래에서 오염된 출력을 `jq` 에 넘기면 스크립트가 즉시
        죽는다. 방향은 안전하지만(머지 안 함) `::error::` 없이 jq 파스 에러만 남아
        Actions 요약에 원인이 드러나지 않고, 일시적 오염 1회로 런을 잃는다.
        빈 응답은 재시도인데 오염 응답은 치명이라는 **비대칭**도 근거가 없다.
        """
        green = _payload(_check("quality", "SUCCESS"))
        rc, output, calls = _execute_merge_step(job, tmp_path, ["<html>502 Bad Gateway</html>", green])
        merges = [c for c in calls if c.startswith("pr merge")]
        assert len([c for c in calls if c.startswith("pr checks")]) >= 2, (
            f"오염된 응답 1회로 루프가 끝났다 — 재시도하지 않는다.\n--- 출력 ---\n{output}"
        )
        assert merges, f"오염된 응답 뒤 정상 응답이 와도 회복하지 못했다.\n--- 출력 ---\n{output}"
        assert rc == 0, f"회복 후에도 실패로 끝났다(rc={rc}).\n--- 출력 ---\n{output}"

    def test_merge_call_is_time_bounded(self, job: dict) -> None:
        """머지 호출이 걸리면 `::error::` 없이 러너 메시지만 남는다.

        그러면 "체크를 기다리다 못 끝났다"(deadline)와 "머지 호출이 멈췄다"가
        로그에서 구별되지 않는다. 둘은 대응이 다르다.
        """
        _, run = _merge_step(job)
        calls = [ln.strip() for ln in run.splitlines() if "gh pr merge" in ln]
        bounded = [ln for ln in calls if "timeout " in ln]
        # `next()` 로 뽑으면 가드가 깨졌을 때 StopIteration 이 나서 **왜** 깨졌는지
        # 메시지가 없다. 진단 가능성을 다루는 절이 스스로 그러면 곤란하다.
        assert bounded, (
            "`timeout` 으로 감싼 `gh pr merge` 호출이 없다. 머지 호출이 걸리면 잡 "
            "타임아웃이 잡되 `::error::` 없이 러너 메시지만 남아 deadline 초과와 "
            "구별되지 않는다.\n현재 머지 호출:\n  " + "\n  ".join(calls)
        )
        assert all("$merge_budget" in ln for ln in bounded), (
            f"머지 호출의 시간 예산이 남은 deadline 에서 오지 않는다: {bounded!r}. "
            "상수를 박으면 deadline 을 바꿔도 따라오지 않는다."
        )
        assert "-eq 124" in run, (
            "`timeout` 의 종료코드 124 를 구분하지 않는다. 구분하지 않으면 시간 초과가 "
            "일반 실패와 같은 모양으로 보여 진단이 안 된다."
        )

    def test_self_exclusion_job_has_no_matrix(self, job: dict) -> None:
        """matrix 를 붙이면 `SELF_CHECK` 가 더는 체크 이름과 맞지 않아 교착한다.

        `gh pr checks` 의 체크 이름은 잡의 `name:` 과 다를 수 있다. 실측(#1328·#1343):

            SKIPPED  Guard Falsifiability  falsifiability (${{ matrix.shard }}/${{ strategy.job-total }})

        matrix 잡은 이름이 확장되거나(`auto-merge (1)`) 스킵 시 템플릿 원문이 그대로
        노출된다. 그러면 자기 자신을 제외하지 못해 **모든 PR 이 25분 deadline red** 다.

        `test_self_check_name_matches_the_job_name` 은 `SELF_CHECK == job["name"]` 을
        보는데 matrix 를 붙여도 `job["name"]` 은 그대로라 통과한다 — 그 가드가 막겠다고
        선언한 교착의 한 형태가 무방비였다(2026-09-18 리뷰). 여기서 닫는다.
        """
        assert "strategy" not in job, (
            f"`{_JOB_ID}` 잡에 strategy 가 생겼다: {job.get('strategy')!r}. matrix 를 쓰면 "
            f"체크 이름이 `{_JOB_ID} (…)` 로 확장되거나 템플릿 원문으로 노출돼 "
            "SELF_CHECK 매칭이 깨지고, 자기 자신을 기다리다 모든 PR 이 deadline red 가 된다. "
            "정말 필요하면 SELF_CHECK 도 확장된 이름을 쓰도록 함께 고칠 것."
        )
