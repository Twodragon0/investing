"""Tests for the `--drop-unresolvable` mode of `fix_post_url_summaries.py`.

The tool has only ever *replaced* blurbs: `apply_repairs` writes when the
resolver produced text and leaves the original alone otherwise. That leaves the
population where re-fetch and translation both fail permanently in place —
2026-09-08 corpus scan: 399 English blurbs, of which ~315 carry nothing the card
does not already show.

Deleting text is not symmetric with replacing it, so the eligibility predicate
is the safety core and is pinned **in both directions**. The must-not-drop cases
are the point: a predicate that returns True for everything satisfies every
must-drop assertion.

The 7.5% finding is why the hybrid rule is not "has an English clause and some
Hangul". Measured over the 279 hybrid blurbs in `_posts/` on 2026-09-08:

    boilerplate tail  205 (73.5%)
    generic tail       53 (19.0%)
    OTHER              21  (7.5%)   <-- real Korean content

Those 21 are Korean prose quoting a long English proper-noun run
("…Mario Tama/Getty Images John Rapley는 The Globe and Mail"), which is the
residual false-positive the `ENGLISH_CLAUSE_MIN_WORDS = 6` calibration note
predicts. Dropping them would destroy content, so the tail must be *recognised
as filler* before the blurb is eligible.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

fpus = importlib.import_module("fix_post_url_summaries")


# ---------------------------------------------------------------------------
# 1. Eligibility predicate — must drop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "text"),
    [
        # Hybrid with a generic theme-context tail: the Korean title above the
        # card already says this, and the tail is filler.
        (
            "미국-이란 분쟁이 길어지면 비트코인이 최대 수혜자가 될 수 있습니다",
            "Bitcoin could be the big winner if the U.S.-Iran conflict drags on for months. "
            "지정학적 리스크가 글로벌 시장 심리에 영향을 주고 있습니다.",
        ),
        # Hybrid produced by the retired synthesizer: entities + em dash + filler.
        (
            "XPLR 인프라, LP(XIFR) 목표가 Barclays에서 12달러로 상향",
            "XPLR Infrastructure, LP (XIFR) Target Increased to $12 at Barclays. "
            "$12, XPLR, LP — 디파이 생태계의 성장과 리스크에 관한 내용입니다.",
        ),
        # All-English restatement of the headline: zero added information.
        (
            "Stocks tumble, Dow confirms correction territory",
            "Stocks tumble, Dow confirms correction territory, as Middle East tensions drag Reuters",
        ),
        # All-English site chrome the repo's own `is_boilerplate` recognises
        # (newsletter solicitation). The predicate reuses that judgement rather
        # than inventing a second one.
        (
            "다우 지수가 조정 국면에 진입했습니다",
            "Sign up for our newsletter to receive the latest crypto market updates every morning.",
        ),
        # CNN site tagline — recognised since the 2026-09-08 literal was added.
        (
            "다우 지수가 조정 국면에 진입했습니다",
            "View the latest news and breaking news today for U.S., world, weather, "
            "entertainment, politics and health at CNN.com.",
        ),
        # Motley Fool return disclaimer, same batch. "motley fool" was already
        # on the phrase list but the disclaimer never names the outlet.
        (
            "S&P 500 장기 수익률 분석",
            "Calculated by Time-Weighted Return since 2002. Volatility profiles based on "
            "trailing-three-year calculations of the standard deviation of service "
            "investment returns.",
        ),
        # Second literal batch (2026-09-09): the corpus-wide remainder after the
        # first, both previously held by the limitation test below.
        (
            "AI stock Xiao-I Corporation (Nasdaq:AIXI) makes gains",
            "Explore the best investing ideas for 2025 at Investorideas.com. Get stock "
            "news, podcasts, videos, and insights on AI, crypto, cannabis and mining.",
        ),
        (
            "암호화폐 산업의 선구자 중 하나인 크라켄이 TradingView에 합류했습니다",
            "Read fresh TradingView updates: Kraken, one of the pioneers of the "
            "cryptocurrency industry, joins TradingView. Discover more in our blog.",
        ),
    ],
)
def test_droppable_when_the_card_already_carries_it(title: str, text: str) -> None:
    assert fpus._is_droppable(text, title), f"should be droppable: {text[:70]!r}"


@pytest.mark.parametrize(
    ("title", "text"),
    [
        # Not drawn from the corpus: as of 2026-09-09 the corpus-wide
        # unrecognised-chrome population is 0, both prior entries having moved
        # to the must-drop list above. These are constructed to have the *shape*
        # of a site tagline while naming an outlet the phrase list has never
        # seen, which is the condition the predicate must decline to guess at.
        (
            "반도체 수요 회복 조짐",
            "Examplewire Markets brings you coverage of equities, rates, and "
            "commodities from our newsroom in Singapore.",
        ),
        (
            "국채 금리 급등",
            "Discover Samplefeed Pro: live quotes, screeners, and analyst research "
            "across global markets, all in one workspace.",
        ),
    ],
)
def test_unrecognised_chrome_is_kept_not_guessed_at(title: str, text: str) -> None:
    """Documented limitation, asserted so it cannot change silently.

    Deleting is not reversible per-item, so the predicate only fires on signals
    the repo already owns. A tagline `is_boilerplate` has never seen stays put;
    widening belongs in `summary_quality`'s phrase list as an **exact literal**,
    which carries no false-positive risk, not in a heuristic here.

    This test earns its place by going red when the boundary moves: written
    2026-09-08 holding the CNN tagline and the Motley Fool disclaimer, it went
    red when those literals landed; refilled with the Investorideas and
    TradingView taglines, it went red again on 2026-09-09 when those landed.
    Both pairs are now in the must-drop list. Because the corpus remainder is
    now empty, the cases here are synthetic — they pin the *policy*, not a
    live finding, and a real tagline found later should replace them.
    """
    assert not fpus._is_droppable(text, title)


# ---------------------------------------------------------------------------
# 2. Eligibility predicate — must NOT drop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "text"),
    [
        # The 7.5% case: Korean prose quoting a long English run. The Hangul is
        # the article's actual content, not a filler tail.
        (
            "비트코인 창시자 신원 관련 보도",
            "Financial Times의 보고서에 따르면 비트코인의 가명 제작자인 나카모토 사토시"
            "(Satoshi Nakamoto)의 신원이 밝혀졌습니다.",
        ),
        (
            "저비용 리츠 ETF 비교",
            "Vanguard Global ex-U.S. Real Estate ETF는 State Street SPDR 다우존스 "
            "International Real Estate ETF(NYSEMKT:RWX)에 비해 더 낮은 수수료를 제공합니다.",
        ),
        # All-English with distinct content: translation is the fix, not deletion.
        (
            "비트코인, 2023년 이후 최고의 주간 기록",
            "Bitcoin posted its best week since 2023, while crypto leaders and analysts "
            "turned bullish on Bitcoin, Ethereum and the broader market.",
        ),
        (
            "코인베이스 CEO, 암호화폐 법안 표결 임박 언급",
            "Coinbase CEO Brian Armstrong says the next major piece of U.S. crypto "
            "legislation is nearing a critical vote as blockchain adoption continues.",
        ),
        # Not an English leak at all — the predicate must not reach past its scope.
        (
            "국내 기관 비트코인 ETF 보유 확대",
            "국내 기관 투자자들이 비트코인 현물 ETF 보유를 늘리며 시장 유동성이 개선되고 있습니다.",
        ),
    ],
)
def test_not_droppable_when_content_would_be_lost(title: str, text: str) -> None:
    assert not fpus._is_droppable(text, title), f"must be kept: {text[:70]!r}"


# ---------------------------------------------------------------------------
# 3. HTML integrity — the element goes, the card stays well-formed
# ---------------------------------------------------------------------------


_CARD_POST = """---
title: 테스트
---

<div class="news-card-item news-sev-info">
<div class="news-card-num">1</div>
<div class="news-card-body">
<a href="https://example.com/a" class="news-title" target="_blank" rel="noopener noreferrer">비트코인이 반등했습니다</a>
<p class="news-desc">Bitcoin rebounds as Wall Street deepens its push. 비트코인 시장 심리와 가격 흐름에 주목하세요.</p>
<span class="news-source">Reuters</span>
</div>
</div>
<div class="news-card-item news-sev-info">
<div class="news-card-num">2</div>
<div class="news-card-body">
<a href="https://example.com/b" class="news-title" target="_blank" rel="noopener noreferrer">이더리움 업그레이드 완료</a>
<p class="news-desc">이더리움 네트워크 업그레이드가 예정대로 완료되어 수수료가 낮아졌습니다.</p>
<span class="news-source">CoinDesk</span>
</div>
</div>
"""


def test_drop_removes_the_element_not_just_its_text(tmp_path: Path) -> None:
    """A blanked `<p></p>` renders as an empty gap; the element must go."""
    post = tmp_path / "2026-09-08-daily-crypto-news-digest.md"
    post.write_text(_CARD_POST, encoding="utf-8")
    blurbs = [b for b in fpus.find_blurbs(post) if fpus._is_droppable(b.text, b.title)]
    assert len(blurbs) == 1, f"fixture should offer exactly one droppable blurb, got {len(blurbs)}"

    content, ok = fpus.drop_from_post(_CARD_POST, blurbs[0].raw, blurbs[0].kind)
    assert ok
    assert '<p class="news-desc">Bitcoin rebounds' not in content
    assert '<p class="news-desc"></p>' not in content, "left an empty element behind"

    # Structure: exactly one news-desc removed, everything else untouched.
    for tag, delta in (
        ('<p class="news-desc">', -1),
        ("</p>", -1),
        ('<div class="news-card-item', 0),
        ('<div class="news-card-body">', 0),
        ("</div>", 0),
        ('class="news-title"', 0),
        ('<span class="news-source">', 0),
    ):
        assert content.count(tag) == _CARD_POST.count(tag) + delta, f"tag count moved for {tag!r}"


def test_drop_refuses_an_ambiguous_anchor() -> None:
    """Same rule as `replace_in_post`: identical copies point at different articles."""
    doubled = _CARD_POST + _CARD_POST
    raw = "Bitcoin rebounds as Wall Street deepens its push. 비트코인 시장 심리와 가격 흐름에 주목하세요."
    _content, ok = fpus.drop_from_post(doubled, raw, "news-desc")
    assert not ok, "a blurb appearing twice must not be dropped from a single decision"


def test_drop_keeps_the_korean_blurb_untouched(tmp_path: Path) -> None:
    """The second card in the fixture is clean and must survive verbatim."""
    post = tmp_path / "2026-09-08-daily-crypto-news-digest.md"
    post.write_text(_CARD_POST, encoding="utf-8")
    blurbs = [b for b in fpus.find_blurbs(post) if fpus._is_droppable(b.text, b.title)]
    content, ok = fpus.drop_from_post(_CARD_POST, blurbs[0].raw, blurbs[0].kind)
    assert ok
    assert "이더리움 네트워크 업그레이드가 예정대로 완료되어 수수료가 낮아졌습니다." in content


# ---------------------------------------------------------------------------
# 4. Blast radius — a predicate bug must not empty the corpus in one run
# ---------------------------------------------------------------------------


def test_drops_are_capped_per_run() -> None:
    """The cap is the control that survives a wrong predicate.

    Deletion has no per-item review step, so the only thing standing between a
    predicate regression and a mass delete is this bound.
    """
    assert fpus._MAX_DROPS_PER_RUN <= 200, (
        f"drop cap is {fpus._MAX_DROPS_PER_RUN}; raising it removes the only bound on a "
        "predicate regression. Raise it only with a reviewed sample from the run below it."
    )
    candidates = [("t", "x") for _ in range(fpus._MAX_DROPS_PER_RUN + 50)]
    assert len(fpus._cap_drops(candidates)) == fpus._MAX_DROPS_PER_RUN


def test_cap_leaves_a_short_list_alone() -> None:
    candidates = [("t", "x") for _ in range(3)]
    assert len(fpus._cap_drops(candidates)) == 3


# ---------------------------------------------------------------------------
# 5. select_drops — only what the resolver gave up on
# ---------------------------------------------------------------------------


# No return annotation: `fpus` is imported dynamically, so `fpus.Blurb` is not a
# usable type expression (basedpyright reportInvalidTypeForm).
def _blurb(text: str, title: str = "비트코인이 반등했습니다"):
    return fpus.Blurb(
        path=Path("_posts/2026-09-08-daily-crypto-news-digest.md"),
        kind="news-desc",
        url="https://example.com/a",
        title=title,
        raw=text,
        text=text,
    )


_DROPPABLE = "Bitcoin rebounds as Wall Street deepens its push. 비트코인 시장 심리와 가격 흐름에 주목하세요."
_KEEPABLE = (
    "Bitcoin posted its best week since 2023, while crypto leaders and analysts turned "
    "bullish on Bitcoin, Ethereum and the broader market."
)


def test_only_unresolved_results_are_eligible() -> None:
    """A repairable blurb is repaired, never deleted.

    `skipped` is excluded for a different reason than `refetch`: it means "not
    attempted this run" (`--direct-only`), so deleting it would destroy a blurb
    the resolver has never even looked at.
    """
    repairs = [
        (_blurb(_DROPPABLE), "", "unresolved"),
        (_blurb(_DROPPABLE), "", "skipped"),
        (_blurb(_DROPPABLE), "복구된 한국어 요약입니다.", "refetch"),
        (_blurb(_DROPPABLE), "합성된 한국어 요약입니다.", "synthetic"),
    ]
    drops = fpus.select_drops(repairs)
    assert len(drops) == 1, f"only the unresolved blurb is eligible, got {len(drops)}"


def test_unresolved_but_valuable_is_not_selected() -> None:
    """The predicate still gates: unresolved is necessary, not sufficient."""
    repairs = [(_blurb(_KEEPABLE), "", "unresolved")]
    assert fpus.select_drops(repairs) == []


def test_selection_is_capped() -> None:
    repairs = [(_blurb(_DROPPABLE), "", "unresolved") for _ in range(fpus._MAX_DROPS_PER_RUN + 25)]
    assert len(fpus.select_drops(repairs)) == fpus._MAX_DROPS_PER_RUN


def test_drop_flag_defaults_off() -> None:
    """Deletion must never happen without asking for it.

    Asserted against the real parser rather than skipped when it is not
    reachable: a skipped test reads as coverage and proves nothing.
    """
    args = fpus.build_parser().parse_args([])
    assert args.drop_unresolvable is False
    assert args.apply is False
