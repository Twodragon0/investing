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
