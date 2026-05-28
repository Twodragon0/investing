"""Pattern parity regression tests for the GENERIC_DESC_PATTERNS facade.

Pins the contract that ``scripts/common/summary_quality.GENERIC_DESC_PATTERNS``
is the **single source of truth** for generic / synthetic description
detection. The only consumer ``scripts/common/summarizer._is_generic_desc``
must delegate to the facade rather than maintaining a local pattern list.

If a stale local ``_GENERIC_DESC_PATTERNS = [...]`` re-appears in any
consumer module, these tests fail loudly. The 30-sample regression matrix
also pins the matching behavior so accidental tightening or relaxation
surfaces immediately.

Mirrors ``tests/test_pattern_parity.py`` (ARTICLE_SPECIFIC_RE parity) — same
pattern, different facade artifact.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from common import summarizer as _summarizer_mod  # noqa: E402
from common import summary_quality as _summary_quality_mod  # noqa: E402

# ---------------------------------------------------------------------------
# 30-sample regression matrix.
# Each tuple: (label, sample, expected_match).
# Covers every category of GENERIC_DESC_PATTERNS:
#   - Korean "보도/소식/공지" sentence-ending fillers
#   - HTTP error pages (access denied, 403, etc.)
#   - JS/cookie/subscribe boilerplate
#   - SEC form / amendment headers
#   - Synthetic markers from enrichment.py (확인하세요, 주시해야, etc.)
#   - New-style fact-based "보도" suffix
#   - Plus negative samples carrying real content so the pattern cannot
#     silently broaden into matching real news bodies.
# ---------------------------------------------------------------------------
SAMPLES: list[tuple[str, str, bool]] = [
    # --- Korean sentence-ending fillers ---
    ("filler-bodo-news", "한국경제에서 보도한 뉴스입니다.", True),
    ("filler-bodo-sosik", "연합뉴스에서 보도한 소식입니다.", True),
    ("filler-jeonhaem", "관련 소식을 전했습니다.", True),
    ("filler-wonmun-detail", "원문에서 세부 내용을 확인하세요.", True),
    ("filler-gyeocaeso", "거래소 공지사항입니다.", True),
    ("filler-confirm-here", "공식 사이트에서 확인하세요.", True),
    ("filler-bare-sosik", "관련 소식", True),
    # --- HTTP / JS / cookie boilerplate (English) ---
    ("http-403", "403 Forbidden access", True),
    ("http-access-denied", "Access denied to this resource", True),
    ("http-please-js", "Please enable JavaScript to view this page.", True),
    ("http-cookie-notice", "We use cookies to improve experience.", True),
    ("http-subscribe", "Subscribe to our newsletter today!", True),
    ("http-signup", "Sign up for the latest updates.", True),
    ("http-js-required", "JavaScript is required to run this app.", True),
    ("http-loading", "Loading... please wait.", True),
    # --- SEC / form headers ---
    ("sec-amendment", "AMENDMENT NO. 3 filed 2026-05-15", True),
    ("sec-form", "FORM 10-K Annual Report", True),
    # --- Read-more / click-here ---
    ("clickbait-read-more", "Read more about the latest research", True),
    ("clickbait-click-here", "Click here for full coverage", True),
    ("clickbait-this-article", "This article is reserved for premium readers.", True),
    # --- Synthetic markers (from enrichment.py) ---
    ("synth-watch", "관련 동향을 주시해야 합니다.", True),
    ("synth-market", "시장 심리와 가격이 동행합니다.", True),
    ("synth-investment-implication", "투자 시사점을 신중히 검토해야 합니다.", True),
    ("synth-tradition", "관련 시장 뉴스입니다.", True),
    # --- New-style "보도" suffix ---
    ("bodo-related", "이슈 관련 보도.", True),
    ("bodo-sector", "반도체 섹터 보도.", True),
    ("bodo-industry", "에너지 산업 보도.", True),
    # --- Negatives: real news bodies must NOT match ---
    ("neg-empty", "", False),
    ("neg-real-news-kr", "삼성전자가 2026년 1분기에 매출 71조원을 기록했다.", False),
    ("neg-real-news-en", "Apple announced record iPhone shipments in Q1 2026.", False),
]

_SAMPLE_IDS = [s[0] for s in SAMPLES]


# ---------------------------------------------------------------------------
# 1. Identity: the canonical patterns object lives in summary_quality.
# ---------------------------------------------------------------------------
def test_facade_exposes_canonical_pattern_list() -> None:
    """summary_quality must export ``GENERIC_DESC_PATTERNS`` as a list of compiled regexes."""
    patterns = _summary_quality_mod.GENERIC_DESC_PATTERNS
    assert isinstance(patterns, list), "GENERIC_DESC_PATTERNS must be a list"
    assert len(patterns) >= 30, f"expected ≥30 patterns, got {len(patterns)}"
    import re

    assert all(isinstance(p, re.Pattern) for p in patterns), "all entries must be compiled re.Pattern objects"


def test_summarizer_is_generic_desc_delegates_to_facade() -> None:
    """summarizer._is_generic_desc must call into the facade, not a local list."""
    # The wrapper's body should reach into _summary_quality_mod. The cleanest
    # contract check: the wrapper and facade produce identical results across
    # the full sample matrix (covered by test_consumers_match below). Here we
    # add a structural check that the summarizer module no longer carries a
    # local pattern list.
    assert not hasattr(_summarizer_mod, "_GENERIC_DESC_PATTERNS"), (
        "summarizer._GENERIC_DESC_PATTERNS still exists — facade SSoT broken."
    )


# ---------------------------------------------------------------------------
# 2. Static AST guard: no module outside summary_quality.py may assign a
#    *GENERIC_DESC_PATTERNS list literal containing re.compile(...) entries.
# ---------------------------------------------------------------------------
_FORBIDDEN_REDEFINITION_PATHS = [
    _SCRIPTS_DIR / "common" / "summarizer.py",
    _SCRIPTS_DIR / "common" / "enrichment.py",
    _SCRIPTS_DIR / "fix_post_descriptions.py",
    _SCRIPTS_DIR / "check_description_quality.py",
    _SCRIPTS_DIR / "check_post_summary.py",
]


@pytest.mark.parametrize(
    "path",
    _FORBIDDEN_REDEFINITION_PATHS,
    ids=lambda p: p.relative_to(_REPO_ROOT).as_posix(),
)
def test_no_local_generic_desc_pattern_list(path: Path) -> None:
    """AST-walk consumer module: refuse any *GENERIC_DESC_PATTERNS list literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.endswith("GENERIC_DESC_PATTERNS"):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    offenders.append(f"line {node.lineno}: {target.id} = [...]")
    assert not offenders, (
        f"{path.relative_to(_REPO_ROOT)} re-introduced a local GENERIC_DESC_PATTERNS "
        f"definition — facade SSoT broken:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 3. 30-sample expected-match regression — facade direct path.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("label", "sample", "expected"), SAMPLES, ids=_SAMPLE_IDS)
def test_facade_is_generic_desc(label: str, sample: str, expected: bool) -> None:
    """Pin per-branch matching behavior of summary_quality.is_generic_desc."""
    actual = _summary_quality_mod.is_generic_desc(sample)
    assert actual is expected, f"[{label}] expected match={expected} got {actual}: {sample!r}"


# ---------------------------------------------------------------------------
# 4. Parity: facade ⇔ summarizer wrapper must agree on every sample.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("label", "sample", "expected"), SAMPLES, ids=_SAMPLE_IDS)
def test_facade_and_summarizer_wrapper_match(label: str, sample: str, expected: bool) -> None:
    """Facade and summarizer._is_generic_desc must agree on every sample."""
    via_facade = _summary_quality_mod.is_generic_desc(sample)
    via_wrapper = _summarizer_mod._is_generic_desc(sample)
    assert via_facade == via_wrapper, (
        f"[{label}] parity broken — facade={via_facade}, wrapper={via_wrapper}: {sample!r}"
    )
    assert via_facade is expected


# ---------------------------------------------------------------------------
# 5. is_boilerplate orchestrator must classify every positive generic sample
#    as boilerplate (since is_generic_desc is one of its 3 detectors).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "sample"),
    [(s[0], s[1]) for s in SAMPLES if s[2]],
    ids=[s[0] for s in SAMPLES if s[2]],
)
def test_is_boilerplate_subsumes_generic_desc(label: str, sample: str) -> None:
    """Every generic-desc positive must also be flagged by is_boilerplate."""
    assert _summary_quality_mod.is_boilerplate(sample), (
        f"[{label}] is_generic_desc=True but is_boilerplate=False: {sample!r}"
    )


# ---------------------------------------------------------------------------
# 6. Coverage guard.
# ---------------------------------------------------------------------------
def test_sample_matrix_has_balanced_polarities() -> None:
    """Matrix must include both positive and negative samples (no all-True drift)."""
    positives = sum(1 for _, _, exp in SAMPLES if exp)
    negatives = sum(1 for _, _, exp in SAMPLES if not exp)
    assert positives >= 24, f"expected ≥24 positive samples, got {positives}"
    assert negatives >= 3, f"expected ≥3 negative samples, got {negatives}"
    assert len(SAMPLES) == 30, f"matrix must have exactly 30 samples, got {len(SAMPLES)}"
