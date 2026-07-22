"""Pattern parity regression tests for the summary_quality facade.

Pins the contract that ``scripts/common/summary_quality.ARTICLE_SPECIFIC_RE``
is the **single source of truth** consumed by:

- ``scripts/common/enrichment_network.py`` — accesses via ``_summary_quality_mod.ARTICLE_SPECIFIC_RE``
  (``_is_low_information_fragment`` moved here from ``enrichment.py`` in the P2-A
  facade split; the facade re-exports it for backward compat)
- ``scripts/fix_post_descriptions.py`` — accesses via ``_summary_quality_mod.ARTICLE_SPECIFIC_RE``

If a stale local ``_ARTICLE_SPECIFIC_RE = re.compile(...)`` is re-introduced
in either consumer (the failure mode that triggered the 2026-05-26 refactor),
these tests fail loudly. The 30-sample regression matrix also pins the
behavior of every branch of the canonical pattern so accidental tightening
or relaxation surfaces immediately.
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

import fix_post_descriptions as _fix_post_descriptions_mod  # noqa: E402

from common import enrichment_network as _enrichment_network_mod  # noqa: E402
from common import summary_quality as _summary_quality_mod  # noqa: E402

# ---------------------------------------------------------------------------
# 30-sample regression matrix.
# Each tuple: (label, sample, expected_match).
# Covers every branch of ARTICLE_SPECIFIC_RE plus a handful of negatives so
# the pattern cannot silently broaden to swallow filler.
# ---------------------------------------------------------------------------
SAMPLES: list[tuple[str, str, bool]] = [
    # --- Title-case proper noun (2 words+) ---
    ("proper-noun-en-1", "Goldman Sachs raised their forecast", True),
    ("proper-noun-en-2", "Federal Reserve Chair signaled caution", True),
    ("proper-noun-en-3", "United States Treasury issued new guidance", True),
    # --- Acronym / ticker ---
    ("acronym-btc", "BTC briefly cleared a key threshold", True),
    ("acronym-kospi", "KOSPI rebounded after the open", True),
    ("acronym-mixed", "The IMF cut its growth projection", True),
    # --- 4-digit year ---
    ("year-2026", "주요 사건은 2026년 1분기에 발생했다", True),
    ("year-2025", "2025 회계연도 실적은 시장 예상을 상회", True),
    # --- Decimal / comma fraction ---
    ("decimal-pct", "성장률은 3.7% 로 둔화", True),
    ("decimal-eur", "유로/달러는 1.0853 부근에서 등락", True),
    # --- Currency + digit ---
    ("currency-usd", "거래 규모는 $42 억 달러를 돌파", True),
    ("currency-krw", "예상 손익은 ₩120 억 수준", True),
    # --- Number with Korean unit ---
    ("unit-억", "순매수 1조 2,400억 원 기록", True),
    ("unit-건", "당일 신고된 사고는 47건 으로 집계", True),
    ("unit-종", "관련 종목 12종 이 동반 강세", True),
    ("unit-개", "신규 상장 5개 가 예정", True),
    ("unit-월", "출시는 7월 으로 예정", True),
    ("unit-일", "정기 발표는 매월 15일 진행", True),
    # --- Korean date fragment (월 04 / 년 2026) ---
    ("date-korean", "월 04 일자 공시 자료에 따르면", True),
    # --- 1,234,567 thousands grouping ---
    ("grouping", "거래대금은 12,345,678 원", True),
    # --- Quoted phrase ---
    ("quote-en", 'CEO said "long-term tailwind remains intact"', True),
    ("quote-ko", "관계자는 “규제 영향은 제한적”이라고 설명", True),
    # --- Korean headline lead-in ---
    ("lead-주요출처", "주요 출처: 한국은행, 통계청, 기획재정부", True),
    ("lead-주요종목", "주요 종목: 삼성전자, SK하이닉스, 현대차", True),
    ("lead-headline", "오늘의 헤드라인: 환율, 금리, 유가 동시 출렁", True),
    # --- Negative samples (filler / generic) ---
    ("neg-empty", "", False),
    ("neg-short-filler-ko", "관련 소식입니다", False),
    ("neg-short-filler-en", "see more", False),
    ("neg-single-lowercase", "today everything is fine", False),
    ("neg-no-signal-noun", "관련 시장 뉴스입니다", False),
]


_SAMPLE_IDS = [s[0] for s in SAMPLES]


# ---------------------------------------------------------------------------
# 1. Identity: every consumer must point to the same compiled pattern object.
# ---------------------------------------------------------------------------
def test_enrichment_uses_canonical_pattern_object() -> None:
    """enrichment_network.py's reference must resolve to the canonical object."""
    facade_re = _enrichment_network_mod._summary_quality_mod.ARTICLE_SPECIFIC_RE
    assert facade_re is _summary_quality_mod.ARTICLE_SPECIFIC_RE, (
        "enrichment_network.py references a different ARTICLE_SPECIFIC_RE object — "
        "indicates a stale local _ARTICLE_SPECIFIC_RE was re-introduced."
    )


def test_fix_post_descriptions_uses_canonical_pattern_object() -> None:
    """fix_post_descriptions.py's facade reference must resolve to the canonical object."""
    facade_re = _fix_post_descriptions_mod._summary_quality_mod.ARTICLE_SPECIFIC_RE
    assert facade_re is _summary_quality_mod.ARTICLE_SPECIFIC_RE, (
        "fix_post_descriptions.py references a different ARTICLE_SPECIFIC_RE — "
        "indicates a stale local _ARTICLE_SPECIFIC_RE was re-introduced."
    )


# ---------------------------------------------------------------------------
# 2. Static AST guard: no local re.compile assigned to *ARTICLE_SPECIFIC_RE
#    in consumer modules. A simple grep can miss commented-out variants but
#    a tightly-scoped AST walk catches every real definition.
# ---------------------------------------------------------------------------
_CONSUMER_PATHS = [
    _SCRIPTS_DIR / "common" / "enrichment_network.py",
    _SCRIPTS_DIR / "fix_post_descriptions.py",
]


@pytest.mark.parametrize("path", _CONSUMER_PATHS, ids=lambda p: p.relative_to(_REPO_ROOT).as_posix())
def test_consumer_has_no_local_article_specific_pattern(path: Path) -> None:
    """AST-walk consumer module: refuse any *ARTICLE_SPECIFIC_RE re.compile."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.endswith("ARTICLE_SPECIFIC_RE"):
                if isinstance(node.value, ast.Call) and (
                    (isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "compile")
                    or (isinstance(node.value.func, ast.Name) and node.value.func.id == "compile")
                ):
                    offenders.append(f"line {node.lineno}: {target.id} = re.compile(...)")
    assert not offenders, (
        f"{path.relative_to(_REPO_ROOT)} re-introduced a local ARTICLE_SPECIFIC_RE "
        f"definition — facade SSoT broken:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 3. 30-sample expected-match regression.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("label", "sample", "expected"), SAMPLES, ids=_SAMPLE_IDS)
def test_canonical_pattern_matches_sample(label: str, sample: str, expected: bool) -> None:
    """Pin per-branch matching behavior of ARTICLE_SPECIFIC_RE."""
    actual = bool(_summary_quality_mod.ARTICLE_SPECIFIC_RE.search(sample))
    assert actual is expected, f"[{label}] expected match={expected} but got {actual}: {sample!r}"


# ---------------------------------------------------------------------------
# 4. Cross-consumer parity: each sample must produce identical results when
#    matched via the facade and via each consumer's bound reference.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("label", "sample", "expected"), SAMPLES, ids=_SAMPLE_IDS)
def test_consumers_match_in_parity_with_facade(label: str, sample: str, expected: bool) -> None:
    """Facade, enrichment, and fix_post_descriptions must agree on every sample."""
    via_facade = bool(_summary_quality_mod.ARTICLE_SPECIFIC_RE.search(sample))
    via_enrichment = bool(_enrichment_network_mod._summary_quality_mod.ARTICLE_SPECIFIC_RE.search(sample))
    via_fix = bool(_fix_post_descriptions_mod._summary_quality_mod.ARTICLE_SPECIFIC_RE.search(sample))
    assert via_facade == via_enrichment == via_fix, (
        f"[{label}] parity broken — facade={via_facade}, enrichment={via_enrichment}, fix={via_fix}: {sample!r}"
    )
    assert via_facade is expected


# ---------------------------------------------------------------------------
# 5. has_positive_signal facade contract — must mirror the raw pattern.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("label", "sample", "expected"), SAMPLES, ids=_SAMPLE_IDS)
def test_has_positive_signal_mirrors_pattern(label: str, sample: str, expected: bool) -> None:
    """has_positive_signal() must agree with direct pattern.search() per sample."""
    assert _summary_quality_mod.has_positive_signal(sample) is expected, (
        f"[{label}] has_positive_signal disagrees with ARTICLE_SPECIFIC_RE: {sample!r}"
    )


# ---------------------------------------------------------------------------
# 6. Coverage guard: ensure the matrix actually covers BOTH polarities.
# ---------------------------------------------------------------------------
def test_sample_matrix_has_balanced_polarities() -> None:
    """Matrix must include both positive and negative samples (no all-True drift)."""
    positives = sum(1 for _, _, exp in SAMPLES if exp)
    negatives = sum(1 for _, _, exp in SAMPLES if not exp)
    assert positives >= 20, f"expected ≥20 positive samples, got {positives}"
    assert negatives >= 5, f"expected ≥5 negative samples, got {negatives}"
    assert len(SAMPLES) == 30, f"matrix must have exactly 30 samples, got {len(SAMPLES)}"
