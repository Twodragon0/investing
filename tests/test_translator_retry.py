"""Retry policy for ``common.translator.translate_to_korean``.

``translate_to_korean`` was fail-open with no retry: any exception returned the
input unchanged and logged at DEBUG. A single transient failure or rate-limit
window during a collection run therefore published English prose permanently —
106 untranslated lines accumulated over seven days (measured 2026-09-02) with
no visible signal, and every one of them translated fine on a later call.

Two properties are pinned here, and they pull against each other:

* **Retry**, so a transient failure does not become a permanent one.
* **A circuit breaker**, because retrying into a rate limit does not recover.
  Sweeping 433 posts rate-limited the endpoint, and retries *inside* that pass
  did not help — three separate later invocations were needed. Without the
  breaker the worst case is ~48 calls x 6s = 288s, which does not fit the four
  collect workflows on a 10-minute timeout.

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


@pytest.fixture(autouse=True)
def reset_retry_state():
    """Clear the module-level failure counters between tests.

    The breaker is process-scoped by design — it exists to stop a *run* from
    burning its budget — which makes it global mutable state. Left alone, one
    test that trips the breaker silently disables retries for every test after
    it, and the suite's result would depend on ordering.
    """
    tr._consecutive_failures = 0
    tr._retries_disabled = False
    tr._failure_total = 0
    tr._failure_warned = False
    tr._failure_reported = 0
    yield
    tr._consecutive_failures = 0
    tr._retries_disabled = False
    tr._failure_total = 0
    tr._failure_warned = False
    tr._failure_reported = 0


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
    def test_stops_retrying_after_consecutive_failures(self, isolated_cache, sleep_calls):
        with patch("common.translator._translate_once", side_effect=_retryable_exc()) as once:
            for i in range(tr._CIRCUIT_BREAKER_FAILURES + 3):
                tr.translate_to_korean(f"{_ENGLISH} {i}")

        assert tr._retries_disabled is True
        # Only the calls made before the breaker tripped paid backoff.
        assert len(sleep_calls.calls) == tr._CIRCUIT_BREAKER_FAILURES * tr._MAX_RETRIES
        expected = tr._CIRCUIT_BREAKER_FAILURES * (tr._MAX_RETRIES + 1) + 3
        assert once.call_count == expected, "브레이커 후 호출은 1회 시도만 해야 한다"

    def test_worst_case_delay_is_bounded_by_the_breaker(self):
        """The number that makes the 10-minute collect workflows safe.

        Without the breaker the bound scales with items per run (~48), which is
        ~288s. Pin it so raising a constant cannot quietly reintroduce that.
        """
        per_call = sum(tr._RETRY_BASE_DELAY * (2**i) for i in range(tr._MAX_RETRIES))
        worst_case = per_call * tr._CIRCUIT_BREAKER_FAILURES
        assert worst_case <= 60, f"최악 재시도 지연 {worst_case}s — 10분 예산 워크플로우가 위험하다"

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
        assert tr._retries_disabled is False

    def test_breaker_needs_consecutive_give_ups_not_a_total(self, isolated_cache, sleep_calls):
        """Alternating give-up / success must never trip the breaker, however
        many give-ups accumulate in total."""
        for i in range(tr._CIRCUIT_BREAKER_FAILURES + 2):
            with patch("common.translator._translate_once", side_effect=_retryable_exc()):
                tr.translate_to_korean(f"fail {i}")
            with patch("common.translator._translate_once", return_value=_KOREAN):
                tr.translate_to_korean(f"ok {i}")

        assert tr._failure_total > tr._CIRCUIT_BREAKER_FAILURES
        assert tr._retries_disabled is False, "연속이 아닌 실패는 브레이커를 올려서는 안 된다"


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
        assert tr._retries_disabled is False
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

        assert any("재시도를 중단" in r.getMessage() for r in caplog.records)

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
