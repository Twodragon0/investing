"""Retry policy for ``common.translator.translate_to_korean``.

``translate_to_korean`` was fail-open with no retry: any exception returned the
input unchanged and logged at DEBUG. A single transient failure or rate-limit
window during a collection run therefore published English prose permanently —
106 untranslated lines accumulated over seven days (measured 2026-09-02) with
no visible signal, and every one of them translated fine on a later call.

Three properties are pinned here, and they pull against each other:

* **Retry**, so a transient failure does not become a permanent one.
* **A per-attempt timeout**, because deep-translator passes none and an
  unanswered read blocks forever — a state no retry or breaker can escape,
  since control never returns.
* **A circuit breaker**, because retrying into a rate limit does not recover.
  Sweeping 433 posts rate-limited the endpoint, and retries *inside* that pass
  did not help — three separate later invocations were needed.

The breaker has two triggers and needs both. The consecutive count catches a
sustained outage fast, but a success resets it, so an alternating
"give up, succeed" pattern slips past while every give-up still pays full
freight — ~48 items at 51s each is half an hour. The cumulative time budget
bounds that pattern regardless of shape.

Fail-open itself is not under test as a nice-to-have: an outage must not stop
13 collectors from publishing, so every path here still ends in the original
text.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

import common.translator as tr

_ENGLISH = "The Federal Reserve signalled a rate cut as price pressures cooled."
_KOREAN = "연방준비제도가 물가 압력 완화를 근거로 금리 인하 가능성을 시사했습니다."


# The breaker's globals are reset for every test by ``conftest``'s autouse
# ``_reset_translator_breaker``. It lives there rather than here because the
# leak is not local to this file: give-ups accumulate across the whole suite,
# and a latched-open breaker makes ``translate_to_korean`` return its input in
# any later test.


@pytest.fixture
def isolated_cache():
    """Run ``translate_to_korean`` against an in-memory cache.

    Without this the call reads ``_state/translation_cache.json`` and would
    write to it — the repo tree is off limits to tests.
    """
    cache: dict[str, str] = {}
    with (
        patch("common.translator._load_cache", return_value=cache),
        patch("common.translator._save_cache"),
        patch("common.translator.TRANSLATION_ENABLED", True),
    ):
        yield cache


def _retryable_exc() -> Exception:
    from deep_translator.exceptions import TooManyRequests

    return TooManyRequests()


def _fatal_exc() -> Exception:
    from deep_translator.exceptions import NotValidLength

    return NotValidLength("x", 0, 5000)


class TestBackoffSchedule:
    def test_retries_twice_with_exponential_backoff(self, isolated_cache, sleep_calls):
        """Mirrors ``utils.request_with_retry`` (max_retries=2, base_delay=2.0)
        so the repo has one backoff policy, not two."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()) as once:
            assert tr.translate_to_korean(_ENGLISH) == _ENGLISH
        assert once.call_count == 3, "1회 시도 + 재시도 2회여야 한다"
        assert sleep_calls.calls == [2.0, 4.0]

    def test_succeeds_on_a_later_attempt(self, isolated_cache, sleep_calls):
        attempts = [_retryable_exc(), _retryable_exc(), _KOREAN]

        def _side_effect(text):
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch("common.translator._translate_once", side_effect=_side_effect):
            assert tr.translate_to_korean(_ENGLISH) == _KOREAN
        assert sleep_calls.calls == [2.0, 4.0]

    def test_no_sleep_when_the_first_attempt_works(self, isolated_cache, sleep_calls):
        with patch("common.translator._translate_once", return_value=_KOREAN):
            assert tr.translate_to_korean(_ENGLISH) == _KOREAN
        assert sleep_calls.calls == []

    def test_backoff_delays_stay_above_the_suites_sleep_floor(self):
        """Below ``conftest.SKIPPED_SLEEP_FLOOR_S`` the fixture really sleeps,
        so a smaller base delay would cost wall-clock in every test."""
        from tests.conftest import SKIPPED_SLEEP_FLOOR_S

        delays = [tr._RETRY_BASE_DELAY * (2**i) for i in range(tr._MAX_RETRIES)]
        assert min(delays) >= SKIPPED_SLEEP_FLOOR_S


class TestCircuitBreaker:
    def test_an_open_breaker_skips_the_call_entirely(self, isolated_cache, sleep_calls):
        """Dropping only the retries is not enough once an attempt can wait
        ``REQUEST_TIMEOUT``: the remaining items would still pay one timeout
        each, which is the bulk of the cost."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()) as once:
            for i in range(tr._CIRCUIT_BREAKER_FAILURES):
                tr.translate_to_korean(f"{_ENGLISH} {i}")
            assert tr._breaker_open is True
            before = once.call_count

            for i in range(3):
                assert tr.translate_to_korean(f"after breaker {i}") == f"after breaker {i}"

        assert once.call_count == before, "브레이커가 열린 뒤에는 엔드포인트를 호출해서는 안 된다"
        assert len(sleep_calls.calls) == tr._CIRCUIT_BREAKER_FAILURES * tr._MAX_RETRIES

    def test_worst_case_is_bounded_including_the_request_timeout(self):
        """The number that makes the 10-minute collect workflows safe.

        The retry-only bound was 5 give-ups x 6s = 30s. Adding a per-attempt
        ``REQUEST_TIMEOUT`` raises a give-up to 3*15 + 6 = 51s, so the bound has
        to be recomputed with the timeout in it — asserting the backoff sum
        alone would keep passing while the real cost grew 8x.
        """
        from common.config import REQUEST_TIMEOUT

        backoff = sum(tr._RETRY_BASE_DELAY * (2**i) for i in range(tr._MAX_RETRIES))
        per_give_up = (tr._MAX_RETRIES + 1) * REQUEST_TIMEOUT + backoff
        # The breaker opens on whichever trigger fires first, and the call that
        # crosses the time budget is already in flight when it does.
        worst_case = min(tr._CIRCUIT_BREAKER_FAILURES * per_give_up, tr._FAILURE_TIME_BUDGET_S + per_give_up)
        assert worst_case <= 300, (
            f"최악 번역 실패 비용 {worst_case}s — 실측 런타임 ~115초와 합치면 10분 예산 워크플로우가 위험하다"
        )

    def test_time_budget_bounds_a_pattern_the_consecutive_count_misses(self, isolated_cache, sleep_calls, monkeypatch):
        """The hole the consecutive counter leaves open.

        A success resets the count, so alternating "give up, succeed" never
        reaches the threshold while every give-up still pays full freight. That
        was survivable when a failure returned instantly; with a 15s timeout per
        attempt, ~48 items in that pattern would spend half an hour.

        The clock is faked rather than ``_failure_time_spent`` pre-set, because
        pre-setting it does not exercise the accumulation: deleting
        ``_failure_time_spent += elapsed`` would leave such a test green while
        the budget trigger became unreachable in production.
        """
        advance = tr._FAILURE_TIME_BUDGET_S + 1
        clock = {"t": 0.0}

        def _fake_monotonic() -> float:
            clock["t"] += advance
            return clock["t"]

        monkeypatch.setattr(tr.time, "monotonic", _fake_monotonic)

        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("crosses the budget")

        assert tr._failure_time_spent >= advance, "give-up 소요 시간이 누적되지 않았다"
        assert tr._breaker_open is True, "시간 예산이 브레이커를 열어야 한다"
        assert tr._consecutive_failures < tr._CIRCUIT_BREAKER_FAILURES, (
            "연속 카운터가 아니라 시간 예산으로 열렸음을 확인해야 판별력이 있다"
        )

    def test_instant_give_ups_do_not_charge_the_budget(self, isolated_cache, sleep_calls):
        """The counterpart: a give-up that costs no wall-clock must not consume
        budget, or a fast-failing endpoint would open the breaker for free."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("instant failure")

        assert tr._failure_time_spent < 1.0, f"즉시 실패가 예산을 {tr._failure_time_spent}s 나 썼다"

    def test_a_give_up_then_a_success_resets_the_counter(self, isolated_cache, sleep_calls):
        """The breaker must trip on a *sustained* outage, not on give-ups
        scattered across an otherwise healthy run.

        The counter tracks give-ups, not attempt failures: a call whose first
        attempt raises and whose second succeeds never increments it. So the
        reset can only be observed after a call that exhausted its attempts —
        testing it with a mid-call recovery proves nothing either way.
        """
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("gives up")
        assert tr._consecutive_failures == 1, "포기가 카운터를 올려야 한다"

        with patch("common.translator._translate_once", return_value=_KOREAN):
            assert tr.translate_to_korean("succeeds") == _KOREAN
        assert tr._consecutive_failures == 0, "성공이 연속 카운터를 되돌려야 한다"
        assert tr._breaker_open is False

    def test_the_consecutive_trigger_needs_consecutive_give_ups(self, isolated_cache, sleep_calls):
        """Alternating give-up / success must not fire the *consecutive*
        trigger, however many give-ups accumulate in total.

        That is the hole the time budget exists to close — see
        ``test_time_budget_bounds_a_pattern_the_consecutive_count_misses``.
        Here the give-ups are instant (mocked), so the budget is untouched and
        only the consecutive rule is under test.
        """
        for i in range(tr._CIRCUIT_BREAKER_FAILURES + 2):
            with patch("common.translator._translate_once", side_effect=_retryable_exc()):
                tr.translate_to_korean(f"fail {i}")
            with patch("common.translator._translate_once", return_value=_KOREAN):
                tr.translate_to_korean(f"ok {i}")

        assert tr._failure_total > tr._CIRCUIT_BREAKER_FAILURES
        assert tr._breaker_open is False, "연속이 아닌 실패는 브레이커를 올려서는 안 된다"


class TestFatalInputErrors:
    def test_input_errors_are_not_retried(self, isolated_cache, sleep_calls):
        with patch("common.translator._translate_once", side_effect=_fatal_exc()) as once:
            assert tr.translate_to_korean(_ENGLISH) == _ENGLISH
        assert once.call_count == 1, "입력 문제는 재시도해도 답이 바뀌지 않는다"
        assert sleep_calls.calls == []
        # Attempt count alone does not separate the fatal branch from the
        # unclassified one — both make a single attempt. The give-up counter
        # does: input problems are not the endpoint's fault.
        assert tr._failure_total == 0

    def test_input_errors_do_not_trip_the_breaker(self, isolated_cache):
        """A run full of over-long strings must not disable retries for the
        transient failures that retrying would actually fix."""
        with patch("common.translator._translate_once", side_effect=_fatal_exc()):
            for i in range(tr._CIRCUIT_BREAKER_FAILURES + 2):
                tr.translate_to_korean(f"{_ENGLISH} {i}")
        assert tr._breaker_open is False
        assert tr._failure_total == 0

    def test_unclassified_errors_fail_open_without_backoff(self, isolated_cache, sleep_calls):
        with patch("common.translator._translate_once", side_effect=RuntimeError("boom")) as once:
            assert tr.translate_to_korean(_ENGLISH) == _ENGLISH
        assert once.call_count == 1
        assert sleep_calls.calls == []


class TestFailOpenContract:
    def test_failures_are_never_cached(self, isolated_cache, sleep_calls):
        """Caching a failure would kill the repair path in
        ``scripts/tools/fix_untranslated_body.py``, which is what took the
        7-day window from 106 findings to 0."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean(_ENGLISH)
        assert isolated_cache == {}

    def test_service_returning_nothing_is_not_retried(self, isolated_cache, sleep_calls):
        """A falsy return means the service handed back the input. Retrying
        cannot change that answer."""
        with patch("common.translator._translate_once", return_value=None) as once:
            assert tr.translate_to_korean(_ENGLISH) == _ENGLISH
        assert once.call_count == 1
        assert sleep_calls.calls == []
        assert isolated_cache == {}


class TestFailureVisibility:
    def test_first_failure_warns_and_the_rest_are_debug(self, isolated_cache, sleep_calls, caplog):
        """DEBUG-only logging is why 106 lines accumulated unnoticed. One
        warning is the signal; latching it stops a degraded endpoint from
        flooding the log."""
        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._translate_once", side_effect=_retryable_exc()),
        ):
            tr.translate_to_korean("first")
            tr.translate_to_korean("second")
            tr.translate_to_korean("third")

        failure_warnings = [r for r in caplog.records if "Translation failed" in r.getMessage()]
        assert len(failure_warnings) == 1, "실패마다 warning 을 내면 로그가 넘친다"

    def test_tripping_the_breaker_is_visible(self, isolated_cache, sleep_calls, caplog):
        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._translate_once", side_effect=_retryable_exc()),
        ):
            for i in range(tr._CIRCUIT_BREAKER_FAILURES):
                tr.translate_to_korean(f"text {i}")

        assert any("번역 호출을 중단" in r.getMessage() for r in caplog.records)

    def test_run_end_reports_the_total(self, isolated_cache, sleep_calls, caplog):
        """Per-failure logs are latched, so without a total a run that lost 40
        translations looks identical to one that lost 1."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("first")
            tr.translate_to_korean("second")

        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._save_cache"),
        ):
            tr.save_translation_cache()

        totals = [r.getMessage() for r in caplog.records if "번역 실패 누적" in r.getMessage()]
        assert len(totals) == 1
        assert "2건" in totals[0]

    def test_repeated_flushes_do_not_reprint_the_same_total(self, isolated_cache, sleep_calls, caplog):
        """``save_translation_cache`` is a flush point, not the end of the run.

        ``enrichment.py`` calls it once per ``enrich_items`` pass and collectors
        run several passes. Production, 2026-09-04: run 33816242897 printed
        "번역 실패 누적 2건" three times for the same two failures.
        """
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("first")
            tr.translate_to_korean("second")

        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._save_cache"),
        ):
            tr.save_translation_cache()
            tr.save_translation_cache()
            tr.save_translation_cache()

        totals = [r.getMessage() for r in caplog.records if "번역 실패 누적" in r.getMessage()]
        assert len(totals) == 1, f"같은 총계를 반복 출력했다: {totals}"

    def test_a_later_failure_is_reported_on_the_next_flush(self, isolated_cache, sleep_calls, caplog):
        """The watermark must not silence genuinely new failures — a later
        enrichment pass that loses more translations still reports."""
        with patch("common.translator._translate_once", side_effect=_retryable_exc()):
            tr.translate_to_korean("first")

        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._save_cache"),
        ):
            tr.save_translation_cache()
            with patch("common.translator._translate_once", side_effect=_retryable_exc()):
                tr.translate_to_korean("second")
            tr.save_translation_cache()

        totals = [r.getMessage() for r in caplog.records if "번역 실패 누적" in r.getMessage()]
        assert len(totals) == 2, f"새 실패가 보고되지 않았다: {totals}"
        assert "1건" in totals[0]
        assert "2건" in totals[1]

    def test_run_end_is_silent_when_nothing_failed(self, isolated_cache, caplog):
        with (
            caplog.at_level(logging.WARNING, logger="common.translator"),
            patch("common.translator._save_cache"),
        ):
            tr.save_translation_cache()
        assert not [r for r in caplog.records if "번역 실패 누적" in r.getMessage()]


class TestHttpTimeoutShim:
    """``GoogleTranslator.translate`` passes no ``timeout`` to ``requests.get``.

    Without one, a server that accepts the connection and never answers blocks
    forever, and neither the retry nor the breaker can help because control
    never returns. ``socket.setdefaulttimeout`` does not fix it (urllib3
    assigns ``None`` to the socket, overriding the process default) and
    ``ThreadPoolExecutor`` makes it worse (its ``atexit`` join stops the
    interpreter from exiting), so the timeout is injected at the call site.
    """

    def test_shim_injects_the_repo_timeout(self):
        from common.config import REQUEST_TIMEOUT

        captured = {}

        class _FakeRequests:
            def get(self, *args, **kwargs):
                captured.update(kwargs)
                return "response"

        shim = tr._TimeoutRequests(_FakeRequests(), REQUEST_TIMEOUT)
        assert shim.get("http://example.invalid/") == "response"
        assert captured["timeout"] == REQUEST_TIMEOUT

    def test_shim_does_not_override_an_explicit_timeout(self):
        captured = {}

        class _FakeRequests:
            def get(self, *args, **kwargs):
                captured.update(kwargs)

        tr._TimeoutRequests(_FakeRequests(), 15).get("http://example.invalid/", timeout=1)
        assert captured["timeout"] == 1

    def test_install_does_not_wrap_a_shim_in_a_shim(self, monkeypatch):
        import deep_translator.google as dt_google

        monkeypatch.setattr(dt_google, "requests", dt_google.requests, raising=False)
        monkeypatch.setattr(tr, "_timeout_patched", False)
        tr._ensure_timeout()
        first = dt_google.requests
        assert isinstance(first, tr._TimeoutRequests)

        monkeypatch.setattr(tr, "_timeout_patched", False)
        tr._ensure_timeout()
        assert dt_google.requests is first, "shim 을 shim 으로 다시 감싸서는 안 된다"

    def test_a_library_without_the_submodule_still_translates(self, isolated_cache, monkeypatch, caplog):
        """Best-effort install. A stub or restructured library must cost the
        timeout, not the translation — raising here would stop all 13
        collectors from translating."""
        import sys

        class _MockTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                return _KOREAN

        stub = type("deep_translator", (), {"GoogleTranslator": _MockTranslator})
        monkeypatch.setattr(tr, "_timeout_patched", False)
        monkeypatch.setattr(tr, "_timeout_warned", False)
        monkeypatch.setitem(sys.modules, "deep_translator", stub)
        monkeypatch.delitem(sys.modules, "deep_translator.google", raising=False)

        with caplog.at_level(logging.WARNING, logger="common.translator"):
            assert tr.translate_to_korean(_ENGLISH) == _KOREAN

        assert any("timeout 을 설치하지 못했다" in r.getMessage() for r in caplog.records), (
            "설치 실패를 조용히 넘기면 안 된다"
        )

    def test_the_timeout_reaches_the_transport_through_translate(self, monkeypatch):
        """End-to-end wiring, observed at the layer that consumes the value.

        A unit test on ``_TimeoutRequests`` alone would keep passing if
        ``_translate_once`` stopped installing it, or if deep-translator stopped
        calling ``requests.get``. Asserting at ``HTTPAdapter.send`` — the last
        hop before the socket — covers the whole chain.

        The suite blocks real outbound HTTP there (``conftest._block_real_http``),
        so this reuses that seam instead of standing up a socket: no network,
        and the hang mode it guards against cannot be reproduced in-process
        anyway. The real stalled-server behaviour was verified out-of-suite.
        """
        from requests.adapters import HTTPAdapter

        from common.config import REQUEST_TIMEOUT

        seen = {}

        def _capture(self, request, *args, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("blocked in test")

        monkeypatch.setattr(HTTPAdapter, "send", _capture)
        monkeypatch.setattr(tr, "_timeout_patched", False)

        # Unclassified RuntimeError -> fail-open, which is fine: the assertion
        # is about what reached the transport, not what came back.
        tr._translate_with_retry("A sentence whose request never leaves the harness.")

        assert seen.get("timeout") == REQUEST_TIMEOUT, (
            f"timeout 이 전송 계층에 도달하지 않았다: {seen.get('timeout')!r}"
        )

    def test_the_timeout_error_is_already_retryable(self):
        """The shim needs no new classification work: its exception is a
        ``RequestException``, which ``_retry_exceptions`` already retries."""
        import requests

        tr._exception_policy = None
        try:
            retryable, _fatal = tr._retry_exceptions()
        finally:
            tr._exception_policy = None
        assert issubclass(requests.exceptions.ReadTimeout, retryable)


class TestExceptionPolicyMatchesTheLibrary:
    """The policy names real deep-translator classes, not guesses.

    ``requirements.txt`` pins 1.11.4; a rename there must fail here rather than
    silently degrade every exception to the unclassified branch, which does not
    retry at all.
    """

    def test_policy_resolves_against_the_installed_library(self):
        tr._exception_policy = None
        try:
            retryable, fatal = tr._retry_exceptions()
        finally:
            tr._exception_policy = None

        from deep_translator import exceptions as dte

        assert dte.TooManyRequests in retryable, "429 는 재시도 대상이어야 한다"
        assert dte.TranslationNotFound in retryable
        assert dte.NotValidLength in fatal
        assert dte.NotValidPayload in fatal

    def test_google_translator_still_raises_what_the_policy_expects(self):
        """Pins the coupling: the retryable set was derived from reading
        ``GoogleTranslator.translate`` (429 -> TooManyRequests, non-2xx ->
        RequestError, missing result container -> TranslationNotFound)."""
        import inspect

        from deep_translator.google import GoogleTranslator

        src = inspect.getsource(GoogleTranslator.translate)
        assert "TooManyRequests" in src
        assert "RequestError" in src
        assert "TranslationNotFound" in src
