"""CI config regression guard: source-delimiter regexes must require a leading space.

A regex that strips a trailing outlet name looks like this:

    re.sub(r"\\s*[-–—|]\\s*\\S+$", "", title)

The `\\s*` allows **zero** spaces before the delimiter, so the hyphen inside a
compound word matches. The tail after it is then deleted:

    "…net inflows to a multi-month high."       -> "…to a multi"
    "…미국-이란 평화 협정을 지적했습니다."          -> "…미국"
    "…(BTC-USD:Cryptocurrency)"                 -> "…(BTC"
    "…U.S.-Iran conflict drags on for months."  -> "…U.S."

This shipped **four separate times** in this repo (2026-08-06):
`enrichment_synthetic._strip_source_suffix`, `enrichment_synthetic.clean_title`,
`summarizer.clean`, and `collect_crypto_news`'s security-summary cleaner. The
first reached `main` and truncated 13 published blurbs before a golden snapshot
caught it. Each fix was the same one-character edit, so the pattern is worth
banning outright rather than re-auditing after the fifth.

Direction: presence — the check is on the *shape of the regex source*, so a new
delimiter regex written with `\\s+` stays green and only the `\\s*` spelling
trips.

## What is allowed

* **Fixed alternations** — `\\s*[-–—|]\\s*(?:Reuters|Bloomberg|…)` is safe: a
  compound word does not match an outlet name. Measured on 4605 corpus titles:
  zero truncations. These are the majority of the repo's delimiter regexes.
* **Markdown bullet classes** — `[-*]` is a list marker, not a delimiter. The
  discriminator is that a delimiter class contains an en dash, em dash, or pipe.
* **Anchored literals** — `\\s*[-–]\\s*\\d{4}-\\d{2}-\\d{2}$` matches a date, not
  arbitrary text.

The ban targets exactly the dangerous shape: zero-or-more whitespace, a
delimiter class, then an *open-ended* tail (`\\S+`, `.{n,m}`, `[A-Z]…`).

Text scan of the source files (no import of the scanned modules, so the guard
cannot move the coverage gate) per the conventions in
`docs/devsecops/ci-regression-guards.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# Canary: the repo had 100+ Python files under scripts/ when this was written.
_MIN_SCANNED_FILES = 50

# A character class that acts as a source delimiter carries an en dash, em dash
# or pipe. `[-*]` (markdown bullet) deliberately does not match.
_DELIM_CLASS = r"\[[^\]]*[–—|][^\]]*\]"

# The dangerous shape: `\s*` + delimiter class + an **open-ended** tail.
#
# Two tail forms are bounded and therefore safe, and both are excluded:
#   `(?:Reuters|Bloomberg|…)` — a fixed alternation of outlet names
#   `\d{4}-\d{2}-\d{2}`       — a fixed numeric literal (a trailing date)
# Everything else (`\S+$`, `.{2,20}$`, `[A-Z][\w\s.]+$`) can swallow arbitrary
# text once the delimiter matches inside a compound word.
_UNSAFE_RE = re.compile(r"\\s\*" + _DELIM_CLASS + r"\\s\*(?!\(\?:|\\d)")

# Same shape but with the required leading space — what a fix looks like.
_SAFE_RE = re.compile(r"\\s\+" + _DELIM_CLASS)


def _python_sources() -> list[Path]:
    return sorted(_SCRIPTS_DIR.rglob("*.py"))


def _offenders() -> list[str]:
    hits: list[str] = []
    for path in _python_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _UNSAFE_RE.search(line):
                rel = path.relative_to(_REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    return hits


def test_scripts_tree_exists() -> None:
    """Canary: a moved tree fails loudly instead of scanning nothing."""
    assert _SCRIPTS_DIR.is_dir(), f"{_SCRIPTS_DIR} not found"
    assert len(_python_sources()) >= _MIN_SCANNED_FILES, (
        f"only {len(_python_sources())} Python files found under scripts/ "
        f"(expected >= {_MIN_SCANNED_FILES}); the scanner is likely broken."
    )


def test_no_open_ended_delimiter_strip_without_leading_space() -> None:
    """`\\s*[-–—|]\\s*<open tail>` truncates hyphen compounds. Use `\\s+`."""
    offenders = _offenders()
    assert not offenders, (
        "source-delimiter regex allows zero spaces before the delimiter, so a "
        "hyphen inside a compound word ('multi-month', 'BTC-USD', '미국-이란') "
        "is treated as a delimiter and everything after it is deleted:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nUse `\\\\s+` instead of `\\\\s*`. A false positive here destroys a "
        "sentence; a false negative only leaves an outlet name behind, so the "
        "rule errs toward keeping text. If the tail is a fixed alternation "
        "`(?:Reuters|Bloomberg|…)` it is already exempt."
    )


# ---------------------------------------------------------------------------
# Detector correctness — both directions, so the guard cannot rot into a no-op
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        # The four shapes that actually shipped.
        r'clean = re.sub(r"\s*[-–—|]\s*\S+$", "", title)',
        r'_SOURCE_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*(?![^-–—|]*\d)[^-–—|]{2,20}$")',
        r'summary = re.sub(r"\s*[-|]\s*[A-Z][\w\s.]+$", "", summary)',
        r'x = re.compile(r"\s*[—]\s*.+$")',
    ],
)
def test_detector_flags_the_dangerous_shape(source: str) -> None:
    assert _UNSAFE_RE.search(source), f"detector missed a known-dangerous form: {source}"


@pytest.mark.parametrize(
    "source",
    [
        # Fixed outlet alternation — a compound cannot match an outlet name.
        r'SOURCE_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*(?:Reuters|Bloomberg|CNBC")',
        r'(r"\s*[-–—]\s*(?:나스닥|알파 추구|야후 파이낸스)\s*$", "")',
        # Markdown bullet class — not a delimiter at all.
        r'content = re.sub(r"(^\s*[-*])\s+-\s+", r"\1 ", content)',
        r'r"(^\s*[-*]\s+)\[([^\]\n]+)\]"',
        # Already fixed.
        r'clean = re.sub(r"\s+[-–—|]\s*\S+$", "", title)',
        # Fixed numeric literal tail — a trailing date, not arbitrary text.
        r'clean_title = re.sub(r"\s*[-–]\s*\d{4}-\d{2}-\d{2}\s*$", "", clean_title)',
    ],
)
def test_detector_spares_the_safe_forms(source: str) -> None:
    assert not _UNSAFE_RE.search(source), f"detector flagged a safe form: {source}"


def test_safe_spelling_is_actually_present_in_the_repo() -> None:
    """Canary: the fixed spelling exists, so the ban is achievable, not aspirational.

    If every call site were rewritten away, this guard would pass vacuously
    while protecting nothing.
    """
    found = any(_SAFE_RE.search(p.read_text(encoding="utf-8")) for p in _python_sources())
    assert found, (
        "no `\\\\s+[-–—|]` delimiter regex found anywhere in scripts/. Either the "
        "call sites moved or the scanner broke — this guard is no longer "
        "watching what it claims to."
    )
