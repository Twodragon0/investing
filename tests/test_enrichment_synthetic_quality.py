"""Output-quality tests for the synthetic description generator.

`tests/test_enrichment.py` covers which category branch a title routes to.
These cover what the reader actually sees, which is a different question — a
correctly-categorised description can still be unpublishable.

The three defects pinned here were measured on the 2026-08-06 backfill dry-run:
of 417 synthesised replacements, a large share read worse than the title
restatement they were meant to improve. That is why
`fix_post_url_summaries.py` ships with `--skip-synthetic`; these tests are the
precondition for turning it back on.
"""

from __future__ import annotations

import pytest

from common.enrichment_synthetic import generate_synthetic_description


def _synth(title: str, source: str = "") -> str:
    return generate_synthetic_description(title, source, None)


# ---------------------------------------------------------------------------
# 1. Source suffix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "source_name"),
    [
        ("FBI 요원, 러시아에서 약 100만 달러 규모의 암호화폐를 훔친 혐의로 기소 - The Hill", "The Hill"),
        ("코스피, 롤러코스터 장세 끝에 1.6%↑ - 프리진경제", "프리진경제"),
        ("삼성전자·SK하이닉스, 주식시장 상승세 | 공감신문", "공감신문"),
        ("비트코인 8% 급등, 기관 매수세 유입 — Bloomberg News", "Bloomberg News"),
    ],
)
def test_source_suffix_is_dropped(title: str, source_name: str) -> None:
    """A trailing outlet name is metadata, not part of the summary.

    The single-token pattern that shipped stripped `- 프리진경제` but left
    `- The Hill`, so multi-word outlets survived into published text.
    """
    assert source_name not in _synth(title)


@pytest.mark.parametrize(
    "title",
    [
        # Not an outlet: a real subtitle carrying the substance of the story.
        "삼성전자 - 2분기 영업이익 14조 원으로 32% 증가",
        "코스피 급등 - 외국인 순매수 1조 2000억 원 유입",
    ],
)
def test_informative_tail_is_kept(title: str) -> None:
    """Only outlet-shaped tails go. A tail carrying figures is the story."""
    result = _synth(title)
    assert "조" in result or "억" in result or "%" in result


# ---------------------------------------------------------------------------
# 2. Keyword tail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "junk"),
    [
        ("FBI 요원, 러시아에서 약 100만 달러 규모의 암호화폐를 훔친 혐의로 기소", "러시아에서"),
        ("연구에 따르면 플로리다는 암호화폐 사기 손실이 가장 많은 주로 선정되었습니다", "따르면"),
        ("美 증시 3대 지수 일제히 하락했습니다", "일제히"),
    ],
)
def test_keyword_tail_excludes_particles_and_filler(title: str, junk: str) -> None:
    """`주요 키워드: 요원, 러시아에서, 달러` is noise wearing a label.

    Hangul runs were taken verbatim, so particle-suffixed fragments
    (`러시아에서`) and adverbs (`일제히`, `따르면`) were presented as keywords.
    """
    result = _synth(title)
    if "주요 키워드" in result:
        tail = result.split("주요 키워드:", 1)[1]
        assert junk not in tail


def test_keyword_tail_is_omitted_when_nothing_survives_filtering() -> None:
    """A label with one filler word under it is worse than no label."""
    result = _synth("그리고 그러나 따라서 하지만 그런데 이렇게")
    assert "주요 키워드" not in result


def test_keyword_tail_keeps_real_entities() -> None:
    """Filtering must not empty out titles that do carry entities."""
    result = _synth("현대차와 기아, 미국 관세 협상 결과에 촉각")
    if "주요 키워드" in result:
        tail = result.split("주요 키워드:", 1)[1]
        assert "현대차" in tail or "기아" in tail


# ---------------------------------------------------------------------------
# 3. Punctuation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "美 증시 3대 지수 일제히 하락했습니다.",
        "코스피가 2,900선을 회복했다.",
        "비트코인 급등!",
        "이번에도 반등할까?",
    ],
)
def test_no_doubled_sentence_punctuation(title: str) -> None:
    """A title that already ends a sentence must not gain a second terminator."""
    result = _synth(title)
    assert ".." not in result
    assert "!." not in result
    assert "?." not in result


def test_output_still_ends_as_a_sentence() -> None:
    result = _synth("코스피가 2,900선을 회복했다")
    assert result.rstrip().endswith((".", "!", "?"))


# ---------------------------------------------------------------------------
# Regression: the generator must still say something
# ---------------------------------------------------------------------------


def test_output_is_not_empty_for_a_plain_title() -> None:
    assert _synth("한국은행 기준금리 동결 결정").strip()


@pytest.mark.parametrize(
    ("title", "junk"),
    [
        ("美 증시 3대 지수 일제히 하락했습니다", "하락했습니다"),
        ("코스피가 2,900선을 회복했다", "회복했다"),
        ("한국은행이 기준금리를 동결한다", "동결한다"),
        ("FBI 요원, 러시아에서 약 100만 달러 규모의 암호화폐 절도", "달러"),
    ],
)
def test_keyword_tail_excludes_predicates_and_units(title: str, junk: str) -> None:
    """A conjugated verb is not a keyword, and neither is a bare currency unit.

    `주요 키워드: 증시, 지수, 하락했습니다` survived the first pass of filtering —
    the particle strip does not touch verb endings.
    """
    result = _synth(title)
    if "주요 키워드" in result:
        tail = result.split("주요 키워드:", 1)[1]
        assert junk not in tail


def test_numeric_context_is_preferred_over_a_keyword_bag() -> None:
    """A figure from the title informs; a bag of its own words does not.

    The fallback branch used to reach for `주요 키워드:` first, so a title
    carrying a percentage got a word list instead of the number.
    """
    result = _synth("국내 관광객 수 3.2% 늘어난 것으로 집계")
    assert "3.2%" in result
    assert "주요 키워드" not in result


@pytest.mark.parametrize(
    "title",
    [
        # A hyphen inside a compound is not a delimiter. Allowing zero spaces
        # before it truncated real text: "…to a multi-month high." lost its tail
        # to "…a multi", and "미국-이란 평화 협정을 지적했습니다." became "…미국".
        "Daily creation activity pushes weekly net inflows to a multi-month high.",
        "최근 암호화폐 매각을 종식시키는 촉매제로 SpaceX IPO과 미국-이란 평화 협정을 지적했습니다.",
        "비트코인: 하락장에도 무슨 일이 일어나고 있나요(암호화폐:BTC-USD).",
        "오늘의 주식 시장: 엔비디아, 인텔 주식 하락; 트럼프-이란 일시 정지로 유가 폭락",
    ],
)
def test_hyphen_compound_is_not_a_source_delimiter(title: str) -> None:
    """A false positive destroys a sentence; a false negative leaves a name.

    The rule therefore requires whitespace before the delimiter and errs toward
    keeping text. Found by a golden-master failure after the first version
    shipped, which had already truncated 13 published blurbs.
    """
    assert _synth(title).startswith(title.rstrip("."))
