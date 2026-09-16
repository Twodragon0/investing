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
"""

from __future__ import annotations

import re
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
        assert run.index("headRefOid") < run.index("while") or run.index("headRefOid") < run.index("gh pr merge"), (
            "head SHA 를 머지 직전이 아니라 폴링 시점에 캡처할 것 — 아니면 고정의 의미가 없다."
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
