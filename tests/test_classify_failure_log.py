"""Regression guard: the CI failure classifier must not read pytest *successes*
as network errors.

## The defect this closes

`classify-workflow-failures.yml` used to grep the whole failed-job log for a bare
keyword set (`timeout`, `timed out`, `connection refused`, ...). A pytest log is
mostly *test names*, and this repo's test names contain those very words:

    tests/test_browser.py::TestBrowserSessionWaitFor::test_wait_for_with_timeout PASSED
    tests/test_base_collector.py::TestErrorHandling::test_fetch_exception_propagates PASSED

Measured on real run 32456925989 (issue #1181): 20 `timeout` matches in the
failed log, **16 of them on `PASSED` lines** and the rest a
`PytestConfigWarning`. Zero genuine network indicators. The single real signal
was `test_lock_pins_satisfy_requirements_specifiers FAILED`.

The consequences compounded:

1. `classification=network` on a pure code failure.
2. → `gh run rerun` burned a full ~13min quality job before reporting anything.
3. → attempt 2 escalated back to `code`, so the issue arrived late and labelled
   "escalated from network" — a lie about the failure's nature.
4. → the issue's "Classifier evidence" block held 12 `PASSED` lines, i.e. zero
   debugging value.

## What the tests assert

The fixtures below are *shaped like the real log* (tab-separated
`job<TAB>step<TAB>timestamp message` prefix, pytest progress lines, a
`##[error]` tail). Two directions are checked, because a classifier that always
answers `code` would pass a one-sided suite:

* a code failure whose log is full of timeout-ish **test names** → `code`
* a genuine transient failure → `network`

Evidence extraction is asserted to surface the *failure* lines, never the
`PASSED` noise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _REPO_ROOT / "scripts" / "tools" / "classify_failure_log.py"

sys.path.insert(0, str(_REPO_ROOT / "scripts" / "tools"))

from classify_failure_log import (  # noqa: E402
    classify,
    extract_evidence,
    render_github_output,
)


def _log(*lines: str) -> str:
    """Wrap bare messages in the real `job<TAB>step<TAB>timestamp ` prefix."""
    return "\n".join(
        f"quality\tRun tests with coverage\t2026-08-21T07:12:{idx:02d}.0000000Z {line}"
        for idx, line in enumerate(lines)
    )


# Verbatim shape of run 32456925989 — the failure that was misclassified.
CODE_FAILURE_LOG = _log(
    "tests/test_base_collector.py::TestErrorHandling::test_fetch_exception_propagates PASSED [  3%]",
    "tests/test_browser.py::TestIsPlaywrightAvailable::test_never_raises_exception PASSED [  6%]",
    "tests/test_browser.py::TestBrowserSessionWaitFor::test_wait_for_without_timeout PASSED [  6%]",
    "tests/test_browser.py::TestBrowserSessionWaitFor::test_wait_for_with_timeout PASSED [  6%]",
    "tests/test_browser.py::TestExtractGoogleNewsLinks::test_exception_in_link_parse_is_swallowed PASSED [  7%]",
    "tests/test_browser.py::TestScrapePage::test_timeout_passed_to_session PASSED [  7%]",
    "tests/test_collector_integration.py::TestStockNewsCollectorRun::test_run_completes_without_exception_when_items_present PASSED [ 17%]",
    "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/config/__init__.py:1464: "
    "PytestConfigWarning: Unknown config option: timeout_method",
    "tests/test_requirements_lock_version_sync.py::test_lock_pins_satisfy_requirements_specifiers FAILED [ 71%]",
    "FAILED tests/test_requirements_lock_version_sync.py::test_lock_pins_satisfy_requirements_specifiers",
    "##[error]Process completed with exit code 1.",
)

NETWORK_FAILURE_LOG = _log(
    "tests/test_browser.py::TestScrapePage::test_timeout_passed_to_session PASSED [  7%]",
    "Traceback (most recent call last):",
    "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='api.example.com', port=443): "
    "Max retries exceeded with url: /v1/quotes (Caused by NewConnectionError('Connection refused'))",
    "##[error]Process completed with exit code 1.",
)

GATEWAY_FAILURE_LOG = _log(
    "tests/test_crypto_api.py::test_fetch_handles_timeout PASSED [ 12%]",
    "curl: (22) The requested URL returned error: 503 Service Unavailable",
    "##[error]Process completed with exit code 22.",
)


class TestClassify:
    def test_pytest_test_names_are_not_network_evidence(self) -> None:
        """The regression: timeout-shaped *test names* must not read as network."""
        assert classify(CODE_FAILURE_LOG) == "code"

    def test_genuine_connection_error_is_network(self) -> None:
        """Counter-direction: a real transient failure must still be caught."""
        assert classify(NETWORK_FAILURE_LOG) == "network"

    def test_gateway_status_is_network(self) -> None:
        assert classify(GATEWAY_FAILURE_LOG) == "network"

    def test_empty_log_is_code(self) -> None:
        """No evidence of transience → do not retry. Fail toward reporting."""
        assert classify("") == "code"

    @pytest.mark.parametrize(
        "identifier",
        [
            "def test_wait_for_with_timeout(self):",
            "timeout_method = 'thread'",
            "self.connection_reset_count += 1",
            "--timeout=300",
        ],
    )
    def test_snake_case_identifiers_do_not_trip_network(self, identifier: str) -> None:
        """Word-boundary anchoring: `_timeout`/`timeout_` are identifiers, not errors."""
        assert classify(_log(identifier, "##[error]Process completed with exit code 1.")) == "code"

    @pytest.mark.parametrize(
        "phrase",
        [
            "ReadTimeout: HTTPSConnectionPool(host='x')",
            "socket.timeout: timed out",
            "TimeoutError: [Errno 60] Operation timed out",
            "fatal: unable to access 'https://github.com/x': Failed to connect to github.com port 443",
            "urllib3.exceptions.NewConnectionError: Temporary failure in name resolution",
            "HTTP 429 Too Many Requests",
            "net/http: TLS handshake timeout",
        ],
    )
    def test_real_transient_phrases_are_network(self, phrase: str) -> None:
        assert classify(_log(phrase)) == "network"

    def test_passing_parametrized_test_ids_are_not_network(self) -> None:
        """The one false positive word-boundary anchoring *cannot* catch.

        Anchoring works because network phrases never occur inside snake_case
        identifiers. A pytest **parametrized node id** breaks that assumption —
        the param value is echoed verbatim, spaces and all:

            ...::test_real_transient_phrases_are_network[socket.timeout: timed out] PASSED

        `timed out` there is fully word-bounded, so only the `PASSED`-noise
        filter can reject it. This is not hypothetical: the parametrize block
        directly above emits exactly these ids into every CI log for the
        Code Quality workflow, which `classify-workflow-failures.yml` watches.
        Drop the noise filter and this repo's own passing suite reads as an
        outage.
        """
        node_ids = [
            "tests/test_classify_failure_log.py::TestClassify::"
            f"test_real_transient_phrases_are_network[{phrase}] PASSED [ 42%]"
            for phrase in (
                "socket.timeout: timed out",
                "HTTP 429 Too Many Requests",
                "net/http: TLS handshake timeout",
            )
        ]
        log = _log(*node_ids, "##[error]Process completed with exit code 1.")
        assert classify(log) == "code"


class TestExtractEvidence:
    def test_evidence_prefers_failure_lines_over_passed_noise(self) -> None:
        evidence = extract_evidence(CODE_FAILURE_LOG, limit=12)
        assert evidence, "a failing log must yield evidence"
        assert not any("PASSED" in line for line in evidence), (
            "PASSED lines carry no failure signal and must never reach the issue body:\n" + "\n".join(evidence)
        )

    def test_evidence_includes_the_actual_failing_test(self) -> None:
        evidence = "\n".join(extract_evidence(CODE_FAILURE_LOG, limit=12))
        assert "test_lock_pins_satisfy_requirements_specifiers" in evidence
        assert "##[error]" in evidence

    def test_evidence_includes_the_transient_cause(self) -> None:
        evidence = "\n".join(extract_evidence(NETWORK_FAILURE_LOG, limit=12))
        assert "Connection refused" in evidence

    def test_evidence_respects_limit(self) -> None:
        assert len(extract_evidence(CODE_FAILURE_LOG, limit=2)) <= 2

    def test_evidence_reaches_the_failure_past_a_long_preamble(self) -> None:
        """Selection must be failure-shaped *and* tail-biased, not first-N.

        The real log for run 32456925989 was 6772 lines with the failure at
        L4761–6666. The old snippet took the first 12 matches, so no budget
        ever reached the failure — a small fixture cannot expose that, because
        first-N and last-N coincide. Hence the realistic preamble: pip resolver
        chatter and deprecation warnings, all of which match the weaker
        secondary tier and would monopolise a first-N budget.
        """
        preamble = [
            f"WARNING: pip is looking at multiple versions of package-{i}; this could take a while (error: retrying)"
            for i in range(40)
        ]
        log = _log(
            *preamble,
            "tests/test_requirements_lock_version_sync.py::test_lock_pins_satisfy_requirements_specifiers FAILED",
            "E   AssertionError: matplotlib: txt '~=3.11.1' -> lock '3.10.9'",
            "##[error]Process completed with exit code 1.",
        )
        evidence = "\n".join(extract_evidence(log, limit=12))
        assert "##[error]" in evidence, f"failure tail not reached:\n{evidence}"
        assert "test_lock_pins_satisfy_requirements_specifiers" in evidence, (
            f"the failing test never made the evidence budget:\n{evidence}"
        )

    def test_evidence_strips_timestamp_prefix(self) -> None:
        """The ISO timestamp is pure noise in a 12-line budget."""
        for line in extract_evidence(CODE_FAILURE_LOG, limit=12):
            assert "2026-08-21T07:12:" not in line

    def test_empty_log_yields_explicit_marker_not_silence(self) -> None:
        evidence = extract_evidence("", limit=12)
        assert len(evidence) == 1
        assert "no" in evidence[0].lower()


class TestGithubOutput:
    def test_heredoc_delimiter_cannot_collide_with_payload(self) -> None:
        """A log line equal to the delimiter would break GITHUB_OUTPUT parsing."""
        rendered = render_github_output("code", ["EOF", "##[error]boom"])
        delimiter = rendered.split("evidence_snippet<<", 1)[1].splitlines()[0]
        payload = rendered.split(f"evidence_snippet<<{delimiter}\n", 1)[1]
        body = payload.rsplit(f"{delimiter}\n", 1)[0]
        assert delimiter not in body.splitlines()

    def test_output_contains_classification_key(self) -> None:
        assert "classification=code\n" in render_github_output("code", ["x"])


class TestCli:
    def test_cli_writes_github_output_file(self, tmp_path: Path) -> None:
        """Exercise the production entrypoint, not just the library functions."""
        log_file = tmp_path / "failed.log"
        log_file.write_text(CODE_FAILURE_LOG, encoding="utf-8")
        out_file = tmp_path / "gh_output"

        result = subprocess.run(
            [
                sys.executable,
                str(_TOOL),
                "--log",
                str(log_file),
                "--github-output",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        written = out_file.read_text(encoding="utf-8")
        assert "classification=code" in written
        assert "PASSED" not in written

    def test_cli_tolerates_missing_log(self, tmp_path: Path) -> None:
        """A missing log must not crash the classify job — it must report `code`."""
        out_file = tmp_path / "gh_output"
        result = subprocess.run(
            [
                sys.executable,
                str(_TOOL),
                "--log",
                str(tmp_path / "absent.log"),
                "--github-output",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "classification=code" in out_file.read_text(encoding="utf-8")


class TestWorkflowWiring:
    """The fix is only real if the workflow actually calls this tool."""

    def test_workflow_invokes_the_tool(self) -> None:
        workflow = (_REPO_ROOT / ".github" / "workflows" / "classify-workflow-failures.yml").read_text(encoding="utf-8")
        assert "scripts/tools/classify_failure_log.py" in workflow

    def test_workflow_no_longer_greps_bare_keywords(self) -> None:
        """The inline grep is what produced the false positives — it must be gone."""
        workflow = (_REPO_ROOT / ".github" / "workflows" / "classify-workflow-failures.yml").read_text(encoding="utf-8")
        assert "network_pattern=" not in workflow, (
            "the inline keyword grep is back — classification must go through "
            "scripts/tools/classify_failure_log.py so it stays under test"
        )
