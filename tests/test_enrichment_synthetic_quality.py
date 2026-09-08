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

from common.enrichment_synthetic import generate_synthetic_description, korean_keywords


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


@pytest.mark.parametrize(
    "title",
    [
        # Title-cleaning paths had the same `\s*` hazard as the description one.
        # Measured on 4605 corpus titles: 21 were cut inside a compound.
        "금리 인하 희망이 약화되면서 암호화폐 주가 급락 (BTC-USD:Cryptocurrency)",
        "비트코인: 약세장에도 무슨 일이 일어나고 있나요? (암호화폐:BTC-USD)",
        "Bitcoin falls amid prolonged U.S.-Israel-Iran conflict (BTC-USD:Cryptocurrency)",
    ],
)
def test_title_cleaning_keeps_hyphen_compounds(title: str) -> None:
    """The ticker pair is the subject; cutting at its hyphen loses the subject."""
    result = _synth(title)
    tail = title.rsplit("-", 1)[-1].rstrip(").")
    assert tail in result, f"compound tail {tail!r} was truncated out of {result!r}"


# ---------------------------------------------------------------------------
# 5. Conjugated forms the first predicate list missed
#
# Measured 2026-09-07 by running `korean_keywords` over all 4,652 card titles
# in `_posts/`: `_KO_PREDICATE_ENDINGS` covered finite endings (`-습니다`,
# `-했다`, …) but not connectives, adnominals or the polite interrogative, so
# verb fragments were still presented as topics. Weights are token-instances
# from that run.
#
# These call `korean_keywords` directly rather than going through
# `generate_synthetic_description`. The end-to-end tests above are guarded by
# `if "주요 키워드" in result`, which passes vacuously whenever the title routes
# to a category branch instead of the keyword tail — 10 of 15 candidate titles
# did exactly that when this was first written, so the assertions never ran.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "junk",
    [
        "뜨거워지면서",  # -면서 connective (weight 32)
        "넘어서면서",
        "고려해야",  # -해야 (weight 7), named in the 2026-09-07 backfill review
        "구매해야",
        "팔았는데",  # -는데 (weight 10)
        "반등하지",  # -하지 (weight 8)
        "개선되지",  # -되지 (weight 6)
        "인상하면",  # -하면 (weight 5)
        "넘으면",  # -으면 (weight 3)
        "시기라고",  # -라고 (weight 5)
        "싶으신가요",  # polite interrogative
        "메이커인가요",
        "일어난",  # -어난 adnominal
        "급락하던",  # -하던 (weight 3)
        "부진했던",  # -했던 (weight 1)
        "해결하려면",  # -려면
        "많은",  # bare quantifier/adnominal, no stem left (weight 10)
        "높은",
        "있는",
        "없는",
        "같은",
        "오른",
        "받은",
        "업계",  # generic noun, same class as the existing 관련/내용 stopwords
    ],
)
def test_conjugated_and_adnominal_forms_are_not_keywords(junk: str) -> None:
    """A connective, adnominal or interrogative form is not a topic.

    Two real topics pad the title so the ``>= 2 surviving`` rule cannot make
    the assertion pass by emptying the list.
    """
    title = f"비트코인 {junk} 반도체"
    assert junk not in korean_keywords(title), f"{junk!r} survived filtering"


@pytest.mark.parametrize(
    ("token", "stem"),
    [
        # `-된` is derivational, not a full predicate: discarding the token
        # throws away the topic along with the ending. Weight 56, dominated by
        # 토큰화된(21).
        ("토큰화된", "토큰화"),
        ("압수된", "압수"),
        ("연결된", "연결"),
    ],
)
def test_adnominal_done_form_is_normalized_not_discarded(token: str, stem: str) -> None:
    """Strip `-된` back to the noun the way a particle is stripped.

    `토큰화된` is wrong as a keyword but `토큰화` is exactly the topic.
    """
    kws = korean_keywords(f"비트코인 {token} 시장")
    assert stem in kws, f"stem {stem!r} lost from {kws!r}"
    assert token not in kws


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Discrimination guard: a filter that discards everything satisfies the
        # tests above, so pin what must survive. Each token ends in a syllable
        # the widened rules inspect.
        ("토큰화 규제안이 국회를 통과", "토큰화"),
        ("코스피 반등 배경은 외국인 순매수", "코스피"),
        # `korean_keywords` keeps only the first 3 survivors, so the expected
        # token has to be within that window — 반도체 is 4th here.
        ("엔비디아 실적 발표를 앞둔 반도체 업종", "엔비디아"),
        ("삼성전자 하이닉스 목표가 상향", "삼성전자"),
    ],
)
def test_widened_filter_keeps_real_topics(title: str, expected: str) -> None:
    """The widened filter must still return the title's actual subject."""
    kws = korean_keywords(title)
    assert expected in kws, f"{expected!r} missing from {kws!r} for {title!r}"


def test_keyword_label_literal_has_one_owner() -> None:
    """The label is produced in one module and stripped in another.

    `improve_existing_posts` treats a `주요 키워드:` tail as a defect and removes
    it in three places while `enrichment_synthetic` emits it. With the literal
    copied into both, renaming the label silently stops the removal from
    matching. Both sides must read the same constant.
    """
    import improve_existing_posts as iep

    from common.enrichment_synthetic import KEYWORD_TAIL_LABEL

    assert KEYWORD_TAIL_LABEL == "주요 키워드:"
    assert iep.KEYWORD_TAIL_LABEL is KEYWORD_TAIL_LABEL
