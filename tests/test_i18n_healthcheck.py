"""`tests/_i18n_healthcheck.py` 단위 테스트 — Playwright / Jekyll 불필요.

## 왜 있나

`tests/i18n/conftest.py` 의 서버 대기 루프는 conftest 안에 있어서 import 가 불가능했고,
그래서 **한 번도 검증된 적이 없었다.** 그 사이 서버가 없을 때 30초를 통째로 태우는
동작이 자리잡았다 (2026-08-25 실측 `16 skipped in 30.43s`, setup phase 30.40s).

이 파일은 `i18n_e2e` 마커를 **일부러 붙이지 않는다.** 브라우저도 서버도 필요 없으므로
`code-quality.yml` 의 `-m "not i18n_e2e"` 스위트에서 항상 돌아야 한다.

시계와 소켓을 주입해서 실제 대기 없이 검증한다 — 유예 로직을 실제 2초 기다리며
확인하면 이 파일 자체가 느린 테스트가 된다.
"""

from __future__ import annotations

import urllib.error

import pytest
from _i18n_healthcheck import (
    DEFAULT_BASE_URL,
    FAST_FAIL_GRACE_S,
    HEALTHCHECK_INTERVAL_S,
    HEALTHCHECK_TIMEOUT_S,
    REASON_DEADLINE,
    REASON_OK,
    REASON_REFUSED,
    Probe,
    is_connection_refused,
    resolve_base_url,
    should_fail_hard,
    unreachable_message,
    wait_for_server,
)


class _FakeClock:
    """가짜 단조 시계. **잠들 때만** 시간이 흐른다.

    읽을 때마다 흐르게 만들면 `wait_for_server` 가 한 번의 반복에서 시계를 몇 번
    읽는지에 결과가 좌우된다 — 구현의 내부 사정이 테스트 결과를 바꾸는 것이라
    유예 시간을 검증하는 테스트가 조용히 틀린 값을 재게 된다(실제로 그렇게 짰다가
    `test_refused_then_ready_still_succeeds` 가 2회째에 포기하는 것으로 나왔다).
    현실과 같게, `sleep()` 이 호출될 때만 진행시킨다.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _refused() -> urllib.error.URLError:
    """`urlopen` 이 실제로 올리는 형태 — 원 예외를 `reason` 에 감싼 URLError."""
    return urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


def _timed_out() -> TimeoutError:
    return TimeoutError("timed out")


def _opener(outcomes):
    """`outcomes` 를 순서대로 내놓고, 소진되면 마지막 것을 계속 반복하는 opener."""
    calls = list(outcomes)

    def open_url(_url, timeout=None):  # noqa: ARG001
        outcome = calls.pop(0) if len(calls) > 1 else calls[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return open_url


# ---------------------------------------------------------------------------
# refused 판별
# ---------------------------------------------------------------------------


def test_wrapped_connection_refused_is_detected() -> None:
    """`urlopen` 은 원 예외를 `URLError.reason` 에 감싼다 — 그 형태를 잡아야 한다."""
    assert is_connection_refused(_refused()) is True


def test_bare_connection_refused_is_detected() -> None:
    """감싸지 않고 올라오는 경로도 있다."""
    assert is_connection_refused(ConnectionRefusedError(61, "Connection refused")) is True


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        urllib.error.URLError("name resolution failed"),
        urllib.error.HTTPError("http://x/", 503, "Service Unavailable", {}, None),
    ],
    ids=["timeout", "urlerror-str-reason", "httperror"],
)
def test_non_refused_failures_are_not_misread(exc: BaseException) -> None:
    """timeout·DNS·HTTPError 는 "포트에 누가 있다" 쪽이다.

    특히 `HTTPError.reason` 은 문자열이라, `isinstance` 검사가 문자열에 걸려 오탐하면
    살아 있는 서버를 부재로 판정하게 된다.
    """
    assert is_connection_refused(exc) is False


# ---------------------------------------------------------------------------
# fast-fail
# ---------------------------------------------------------------------------


def test_all_refused_gives_up_after_grace_not_full_budget() -> None:
    """AC1 — 아무도 안 듣고 있으면 전체 예산이 아니라 유예 시간에 포기한다."""
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=30.0,
        grace_s=2.0,
        opener=_opener([_refused()]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.ok is False
    assert probe.reason == REASON_REFUSED
    # 30s 예산을 다 썼다면 시도 횟수가 수십 회다. 유예 2s / 0.5s 단위이므로 한 자릿수.
    assert probe.attempts <= 6, f"유예를 넘겨 계속 시도했다 ({probe.attempts}회)"


def test_zero_grace_gives_up_on_first_refusal() -> None:
    """`I18N_E2E_FAST_FAIL_GRACE=0` 은 즉시 포기를 뜻한다."""
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=30.0,
        grace_s=0.0,
        opener=_opener([_refused()]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.reason == REASON_REFUSED
    assert probe.attempts == 1


def test_refused_then_ready_still_succeeds() -> None:
    """AC2 — 유예 안에 포트가 열리면(startup race) 정상 성공이다.

    `jekyll serve --detach` 는 셸 명령이 리턴한 뒤에 바인드한다. 이 케이스를 잃으면
    "방금 serve 띄웠는데 skip 된다" 가 된다.
    """
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=30.0,
        grace_s=2.0,
        opener=_opener([_refused(), _refused(), _FakeResponse(200)]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.ok is True
    assert probe.reason == REASON_OK
    assert probe.attempts == 3


def test_timeouts_use_the_full_budget_not_the_grace() -> None:
    """AC3 — 바인드는 됐는데 느린 서버에는 fast-fail 이 걸리면 안 된다.

    이 단언이 red 가 되지 않으면 `only_refused` 갱신이 죽은 것이다 — 그때는 느린
    서버까지 2초 만에 포기하게 된다.
    """
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=10.0,
        grace_s=2.0,
        opener=_opener([_timed_out()]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.ok is False
    assert probe.reason == REASON_DEADLINE
    # 유예(2s = 4회)를 훨씬 넘겨 예산(10s)까지 갔어야 한다.
    assert probe.attempts > 6, f"유예 구간에서 포기했다 ({probe.attempts}회)"


def test_first_refused_then_timeout_switches_to_full_budget() -> None:
    """refused 로 시작해도 non-refused 가 한 번 나오면 fast-fail 을 포기한다."""
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=10.0,
        grace_s=2.0,
        opener=_opener([_refused(), _timed_out()]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.reason == REASON_DEADLINE
    assert probe.attempts > 6


def test_5xx_response_is_not_ready_but_counts_as_listening() -> None:
    """5xx 는 준비 안 된 것이지만 포트에는 누가 있다 — fast-fail 대상이 아니다."""
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=10.0,
        grace_s=2.0,
        opener=_opener([_FakeResponse(503)]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.reason == REASON_DEADLINE
    assert probe.attempts > 6


@pytest.mark.parametrize("status", [200, 301, 404, 499])
def test_any_non_5xx_status_counts_as_ready(status: int) -> None:
    """홈페이지가 무엇이든 돌려주면 서버는 뜬 것이다(404 도 포함)."""
    clock = _FakeClock()
    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=10.0,
        grace_s=2.0,
        opener=_opener([_FakeResponse(status)]),
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe.ok is True


def test_zero_timeout_never_probes() -> None:
    """예산이 0이면 시도 자체를 하지 않는다 — 기존 동작 보존."""
    clock = _FakeClock()

    def _explode(_url, timeout=None):  # noqa: ARG001
        raise AssertionError("timeout_s=0 인데 요청을 보냈다")

    probe = wait_for_server(
        "http://127.0.0.1:4000",
        timeout_s=0.0,
        grace_s=2.0,
        opener=_explode,
        sleep=clock.sleep,
        monotonic=clock,
    )

    assert probe == Probe(False, REASON_DEADLINE, 0, None)


# ---------------------------------------------------------------------------
# 메시지 · 환경
# ---------------------------------------------------------------------------


def test_message_distinguishes_the_two_causes() -> None:
    """AC6 — 두 사유가 다른 행동을 지시해야 한다."""
    refused = unreachable_message("http://127.0.0.1:4000", Probe(False, REASON_REFUSED, 4))
    deadline = unreachable_message("http://127.0.0.1:4000", Probe(False, REASON_DEADLINE, 60))

    assert "jekyll serve" in refused, "서버를 띄우라는 지시가 없다"
    assert "I18N_E2E_HEALTHCHECK_TIMEOUT" in deadline, "예산을 늘리라는 지시가 없다"
    assert refused != deadline


@pytest.mark.parametrize(
    ("env", "expected"),
    [({}, False), ({"CI": ""}, False), ({"CI": "true"}, True), ({"CI": "1"}, True)],
    ids=["absent", "empty", "true", "one"],
)
def test_ci_turns_unreachable_into_a_hard_failure(env: dict, expected: bool) -> None:
    """AC7 — CI 에서 서버가 사라지면 skip 이 아니라 fail 이어야 한다.

    `i18n-e2e.yml` 은 pytest 앞의 `curl` 루프로 서버를 보장하지만, 그 체크와 pytest
    사이에 서버가 죽으면 16건이 skip 되고 **잡은 green 으로 끝난다.**
    """
    assert should_fail_hard(env) is expected


def test_base_url_override_and_trailing_slash() -> None:
    assert resolve_base_url({}) == DEFAULT_BASE_URL
    assert resolve_base_url({"I18N_E2E_BASE_URL": "http://127.0.0.1:4001/"}) == "http://127.0.0.1:4001"


def test_module_defaults_stay_sane() -> None:
    """AC4 의 기본값 쪽 — 상수가 조용히 어긋나면 fast-fail 이 무의미해진다."""
    assert 0 <= FAST_FAIL_GRACE_S <= 5.0, "유예가 너무 길면 fast-fail 의 의미가 없다"
    assert FAST_FAIL_GRACE_S < HEALTHCHECK_TIMEOUT_S, "유예가 예산보다 크면 fast-fail 이 죽은 코드다"
    assert HEALTHCHECK_INTERVAL_S > 0
