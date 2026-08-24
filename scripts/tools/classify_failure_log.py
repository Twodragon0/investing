#!/usr/bin/env python3
r"""Classify a GitHub Actions failed-job log as `network` (transient, retry) or
`code` (real, open an issue), and extract the log lines worth reading.

## Why this is a module and not an inline grep

`classify-workflow-failures.yml` used to do both jobs inline: a
`grep -Eqi "$network_pattern"` over the whole `gh run view --log-failed` output,
plus a heredoc'd Python snippet that took the *first* 12 keyword matches as
"evidence". Neither was testable, and both were wrong in the same way.

A pytest log is overwhelmingly **test names**, and this repo's test names contain
the exact keywords the classifier searched for:

    tests/test_browser.py::TestBrowserSessionWaitFor::test_wait_for_with_timeout PASSED
    tests/test_base_collector.py::TestErrorHandling::test_fetch_exception_propagates PASSED

Measured on run 32456925989 (→ issue #1181): 20 `timeout` matches in the failed
log — 16 on `PASSED` lines, the remainder a `PytestConfigWarning`. **Zero**
genuine network indicators. The one real signal was
`test_lock_pins_satisfy_requirements_specifiers FAILED`.

Every code failure in the pytest-running workflows therefore took this path:

    raw=network → `gh run rerun` (a full ~13min quality job) → attempt 2
    → escalate to code → issue filed late, mislabelled, with 12 PASSED lines
      as its "evidence"

## The two defences

**1. Drop outcome-noise lines.** `PASSED`/`SKIPPED`/`XFAIL`/`XPASS` progress
lines cannot carry failure signal — a passing test's name is not evidence of
anything. `FAILED`/`ERROR` lines are kept: those *are* signal.

**2. Anchor on shapes that only errors have.** Bare `timeout` is ambiguous — it
appears in `test_wait_for_with_timeout`, `timeout_method`, `--timeout=300`. So
the network patterns are either multi-word phrases (`timed out`, `connection
refused`, `tls handshake timeout`) or CamelCase exception classes
(`ReadTimeout`, `TimeoutError`) — neither shape occurs in snake_case
identifiers or CLI flags. Word boundaries (`(?<!\w)…(?!\w)`) make `_timeout`
and `timeout_` non-matches by construction.

## Fail direction

Absent transient evidence the answer is `code`: report the failure rather than
retry it. A false `code` costs one issue a human closes; a false `network` costs
a rerun *and* delays the true signal — and, on attempt 2, mislabels it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Line-level noise filter
# ---------------------------------------------------------------------------

# pytest progress/summary outcomes that prove something *worked*. Deliberately
# excludes FAILED and ERROR — those are the lines we most want to keep.
_PASSING_OUTCOME_RE = re.compile(r"\b(PASSED|SKIPPED|XFAIL|XPASS|no tests ran)\b")

# `job<TAB>step<TAB>2026-08-21T07:12:42.2940521Z message` — the shape
# `gh run view --log-failed` emits. Stripped for readability: inside a 12-line
# evidence budget the timestamp is pure overhead.
_LOG_PREFIX_RE = re.compile(r"^(?:[^\t]*\t){0,2}\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+")


def _strip_prefix(line: str) -> str:
    return _LOG_PREFIX_RE.sub("", line).strip()


def _is_noise(line: str) -> bool:
    """True when the line reports a *successful* test and so cannot be evidence."""
    return bool(_PASSING_OUTCOME_RE.search(line))


def _signal_lines(text: str) -> list[tuple[int, str]]:
    """(1-based line number, prefix-stripped text) for lines that may carry signal."""
    out: list[tuple[int, str]] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        if _is_noise(raw):
            continue
        stripped = _strip_prefix(raw)
        if stripped:
            out.append((idx, stripped))
    return out


# ---------------------------------------------------------------------------
# Network (transient) detection
# ---------------------------------------------------------------------------

# Multi-word phrases and HTTP statuses. None of these can appear inside a
# snake_case identifier, so they need no further disambiguation.
_NETWORK_PHRASES = (
    r"timed out",
    r"could ?n[o']?t connect",
    r"could not connect",
    r"failed to connect",
    r"connection reset",
    r"connection refused",
    r"connection aborted",
    r"connection closed",
    r"remote end closed connection",
    r"temporary failure in name resolution",
    r"could not resolve host",
    r"name or service not known",
    r"network is unreachable",
    r"no route to host",
    r"max retries exceeded",
    r"tls handshake timeout",
    r"ssl connect error",
    r"eof occurred in violation of protocol",
    r"gateway timeout",
    r"502 bad gateway",
    r"503 service unavailable",
    r"504 gateway timeout",
    r"429 too many requests",
    r"server misbehaving",
    r"operation timed out",
)

# CamelCase exception classes only. `ReadTimeout`, `ConnectTimeoutError`,
# `TimeoutError` match; `timeout_method` and `test_x_timeout` cannot, because a
# capital letter is required at the class-name boundary.
_NETWORK_EXCEPTION_RE = re.compile(
    r"(?<![\w.])(?:[A-Z][A-Za-z]*)?"
    r"(?:Timeout|ConnectionError|ConnectionReset|ConnectTimeout|ReadTimeout|"
    r"NewConnectionError|ProtocolError|SSLError|ProxyError)"
    r"(?:Error|Exception)?(?![\w])"
)

_NETWORK_PHRASE_RE = re.compile("|".join(rf"(?<!\w){p}(?!\w)" for p in _NETWORK_PHRASES), re.IGNORECASE)


def _looks_transient(line: str) -> bool:
    return bool(_NETWORK_PHRASE_RE.search(line) or _NETWORK_EXCEPTION_RE.search(line))


def classify(text: str) -> str:
    """Return `"network"` if the log shows transient failure, else `"code"`.

    `code` is the default: see "Fail direction" in the module docstring.
    """
    return "network" if any(_looks_transient(line) for _, line in _signal_lines(text)) else "code"


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------

# Tier 1 — the lines a human opens the log to find.
_PRIMARY_RE = re.compile(
    r"(?:##\[error\]|\bFAILED\b|\bERROR\b|Traceback \(most recent call last\)|"
    r"^E\s{2,}|(?<![\w.])[A-Z][A-Za-z]*(?:Error|Exception)(?![\w]))"
)

# Tier 2 — weaker but still failure-shaped context.
_SECONDARY_RE = re.compile(
    r"(?:(?<!\w)error:|(?<!\w)fatal:|(?<!\w)assert(?!\w)|exit code|"
    r"(?<!\w)warning:|(?<!\w)exception(?!\w))",
    re.IGNORECASE,
)

_NO_EVIDENCE = "no failure-shaped log lines captured"


def extract_evidence(text: str, limit: int = 12) -> list[str]:
    """Return up to `limit` `L<n>: <line>` strings, failure-shaped lines first.

    Ordering matters as much as selection. The old snippet took the *first* N
    matches, which in a pytest log means the earliest lines — i.e. setup and
    warnings, never the failure. Here tier-1 matches win, and within a tier the
    lines closest to the end are kept: on GitHub Actions the failure summary is
    always at the tail.
    """
    lines = _signal_lines(text)
    if not lines:
        return [_NO_EVIDENCE]

    primary = [(n, ln) for n, ln in lines if _PRIMARY_RE.search(ln)]
    secondary = [
        (n, ln) for n, ln in lines if (n, ln) not in primary and (_SECONDARY_RE.search(ln) or _looks_transient(ln))
    ]

    selected: list[tuple[int, str]] = primary[-limit:]
    if len(selected) < limit:
        room = limit - len(selected)
        chosen = set(selected)
        selected = [item for item in secondary[-room:] if item not in chosen] + selected

    if not selected:
        selected = lines[-limit:]

    selected.sort(key=lambda item: item[0])
    return [f"L{n}: {ln}" for n, ln in selected[:limit]] or [_NO_EVIDENCE]


# ---------------------------------------------------------------------------
# GITHUB_OUTPUT rendering
# ---------------------------------------------------------------------------


def render_github_output(classification: str, evidence: list[str]) -> str:
    """Render `$GITHUB_OUTPUT` lines, with a delimiter the payload cannot contain.

    A log line equal to the heredoc delimiter would terminate the value early and
    let the rest of the log be parsed as further outputs. The delimiter is
    therefore derived from the payload's own digest — deterministic (so it is
    testable) and, since it embeds a hash of the text it delimits, never present
    inside it.
    """
    body = "\n".join(evidence)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    delimiter = f"EVIDENCE_EOF_{digest}"
    # Belt and braces: a line that somehow equals the delimiter is dropped.
    safe = [line for line in evidence if line.strip() != delimiter]
    return f"classification={classification}\nevidence_snippet<<{delimiter}\n" + "\n".join(safe) + f"\n{delimiter}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="failed-job log file")
    parser.add_argument(
        "--github-output",
        type=Path,
        help="append classification + evidence here (defaults to stdout)",
    )
    parser.add_argument("--limit", type=int, default=12, help="max evidence lines")
    args = parser.parse_args(argv)

    # A missing or unreadable log must not fail the classify job — it would
    # replace a real failure signal with a meta-failure. Report `code` so the
    # issue still gets filed and a human sees it.
    try:
        text = args.log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"could not read {args.log}: {exc}", file=sys.stderr)
        text = ""

    rendered = render_github_output(classify(text), extract_evidence(text, limit=args.limit))

    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
