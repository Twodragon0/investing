"""Entertainment keyword matching must respect word boundaries.

The filter matched keywords as bare substrings (``any(kw in text ...)``), so
short sports acronyms hit the middle of ordinary words. Measured against this
repo's own 2026 post corpus (7,471 prose words appearing 6+ times):

| keyword | matched word (occurrences)                                    |
|---------|---------------------------------------------------------------|
| ``nfl`` | inflation (1200), conflict (646), conflicts (51), inflows (50) |
| ``nba`` | coinbase (804), unbacked (43)                                  |
| ``hbo`` | dashboard (214)                                                |
| ``heat``| heats (14), cheat (9)                                          |

Any social/news item whose title or description mentioned inflation, conflict,
or Coinbase was therefore dropped as "entertainment" — the three are core
vocabulary for a crypto/macro pipeline, so the filter was removing exactly the
items it exists to keep.

Surfaced 2026-09-02 while writing `tests/test_body_lead_headline.py`: the
fixture title "Bitcoin spot ETF inflows extend for a third straight session"
vanished from `collect_social_media.run()` because ``nfl`` matched
"i**nfl**ows".
"""

from __future__ import annotations

import pytest

from common.content_filters import is_entertainment

_KEYWORDS = frozenset({"nfl", "nba", "hbo", "heat", "world cup soccer", "e-sport"})


def _item(title: str) -> dict:
    return {"title": title, "description": ""}


@pytest.mark.parametrize(
    "title",
    [
        "US inflation cools to 2.1% in August",
        "Escalating conflict pressures oil prices",
        "Coinbase reports record quarterly volume",
        "Bitcoin spot ETF inflows extend for a third straight session",
        "Unbacked stablecoins draw regulator scrutiny",
        "New analytics dashboard ships for treasury desks",
    ],
)
def test_domain_vocabulary_is_not_filtered(title: str):
    assert not is_entertainment(_item(title), _KEYWORDS), f"false positive on: {title!r}"


@pytest.mark.parametrize(
    "title",
    [
        "NFL playoffs draw record viewership",
        "NBA finals ratings climb",
        "HBO renews its flagship drama",
        "World Cup soccer final breaks streaming record",
    ],
)
def test_real_entertainment_is_still_filtered(title: str):
    assert is_entertainment(_item(title), _KEYWORDS), f"missed true positive: {title!r}"


def test_keyword_matches_across_punctuation():
    """A boundary is not the same as a space — punctuation still delimits."""
    assert is_entertainment(_item("Recap: (NFL) week 1"), _KEYWORDS)
    assert is_entertainment(_item("nfl, nba and nhl highlights"), _KEYWORDS)


def test_description_is_searched_too():
    assert is_entertainment({"title": "Weekly recap", "description": "NBA finals coverage"}, _KEYWORDS)


def test_hyphenated_keyword_still_matches():
    assert is_entertainment(_item("The e-sport boom continues"), _KEYWORDS)


def test_keyword_ending_in_non_word_char_still_matches():
    """``disney+`` ends in ``+``; a trailing ``\\b`` would demand a word char
    right after the plus, so "disney+ streaming" would stop matching. The
    boundary is applied per edge, not unconditionally."""
    kws = frozenset({"disney+", "nfl"})
    assert is_entertainment(_item("Disney+ raises its subscription price"), kws)
    assert not is_entertainment(_item("Inflation eases in August"), kws)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Oscars ceremony draws record ratings", True),
        ("The esports final sold out", True),
        ("Survivors of the flood receive aid", True),
        ("Inflation eases in August", False),
        ("Coinbase lists a new token", False),
    ],
)
def test_plural_true_positives_survive_anchoring(title: str, expected: bool):
    """Substring search matched plurals for free ("oscar" caught "Oscars").
    Anchoring must not silently narrow the filter to singulars only."""
    kws = frozenset({"oscar", "esport", "survivor", "nfl", "nba"})
    assert is_entertainment(_item(title), kws) is expected


# ---------------------------------------------------------------------------
# 명시적 공백 패딩은 저자의 앵커 의도다 — `\b` 로 대체하면 넓어진다
# ---------------------------------------------------------------------------


def test_space_padded_keyword_keeps_whitespace_anchor():
    """`" f1 "` 는 공백으로 감싸 앵커한 키워드다.

    `.strip()` 후 `\\b` 를 붙이면 `https://f1.tokenpost.kr/...` 의 호스트명에
    매칭된다 — `/` 와 `.` 사이에 단어 경계가 있기 때문이다. 실측: 2026년
    코퍼스에서 70회, 전부 이 CDN 호스트명. 공백 패딩은 공백 경계로 지켜야 한다.
    """
    kws = frozenset({" f1 "})
    assert not is_entertainment(_item("chart at https://f1.tokenpost.kr/2026/08/x.webp"), kws)
    assert is_entertainment(_item("the f1 season opener drew record ratings"), kws)


# ---------------------------------------------------------------------------
# 일반명사 키워드 제거 — 측정된 오탐
# ---------------------------------------------------------------------------


def _runtime_keywords() -> set:
    """collectors.yml 의 모든 수집기 섹션에서 실제 사용되는 키워드 합집합."""
    import pathlib

    import yaml

    cfg = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parent.parent / "scripts" / "config" / "collectors.yml").read_text(
            encoding="utf-8"
        )
    )
    out: set = set()
    for value in (cfg or {}).values():
        if isinstance(value, dict):
            kws = (value.get("keywords") or {}).get("entertainment_keywords")
            if kws:
                out |= set(kws)
    return out


# 각 항목은 이 저장소 코퍼스 또는 실제 금융 문구에서 오탐이 실측된 것이다.
# 뒤 문자열은 그 근거(대표 문맥).
_COMMON_NOUN_KEYWORDS = {
    "stanley": "Morgan Stanley",
    "magic": "Magic internet money / Binance Hook & Magic 카드",
    "survivor": "earthquake survivors",
    "bulls": "bitcoin bulls",
    "heat": "rebound heats up",
    "rockets": "XRP rockets 8%",
    "nets": "IPO nets $69.5 million",
    "suns": "Justin Sun's HTX",
    "hawks": "the Fed hawks are winning",
    "spurs": "treasury buyback spurs curve control",
    "mvp": "비트코인 … MVP 주간",
    "bucks": "worth big bucks",
    "nuggets": "gold nuggets / nuggets from the Fed minutes",
    "thunder": "rate cut thunder from the ECB",
    "wizards": "quant wizards",
    "warriors": "weekend warriors",
    "pistons": "auto supplier ships pistons",
}


def test_common_noun_keywords_are_not_in_runtime_config():
    """이 단어들은 금융 문맥에서 정상적으로 등장한다 — 필터에 두면 진짜 뉴스를 지운다."""
    present = sorted(_COMMON_NOUN_KEYWORDS.keys() & _runtime_keywords())
    detail = "\n".join(f"  {k!r}: {_COMMON_NOUN_KEYWORDS[k]}" for k in present)
    assert not present, f"일반명사 키워드가 collectors.yml 에 남아 있다:\n{detail}"


def test_multiword_variants_are_kept():
    """단독 일반명사만 제거한다 — 종목명이 붙은 다어절 키워드는 유지한다."""
    kws = _runtime_keywords()
    assert "stanley cup" in kws
    assert "nba finals" in kws
