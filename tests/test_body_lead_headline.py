"""The rendered body lead must not carry an untranslated English headline.

`_layouts/post.html` renders `page.excerpt`, and `scripts/improve_existing_posts.py`
rebuilds a low-quality excerpt from `_extract_description(body)` — so whatever the
collectors put in a post's first paragraph can surface as the visible 요약 text.

`common.headline.select_korean_headline` already guards the `description_ko`
builders (PR #1260). These four sites feed the *body* lead through the same
`title_ko or title_translated or title` chain (or, for FMP, a raw `event` field)
and were left out of that pass. Each already has a headline-free branch, so an
empty headline is a valid answer.

A ratio check is deliberately not used: the lead wraps the headline in Korean
framing ("정치권 핵심 이슈: <headline>. … 종합 정리합니다"), so a fully English
headline still leaves the paragraph under the ASCII threshold. The tests assert
on the headline string itself.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# "inflows" 는 엔터테인먼트 필터의 비앵커 substring 매칭("nfl")에 걸려
# collect_social_media 에서 아이템 자체가 제거된다 — 별개 결함이라 픽스처를
# 우회한다.
_ENGLISH_TITLE = "Bitcoin spot ETF sees a third straight day of buying"
_ENGLISH_EVENT = "Treasury Sec Bessent Speaks"
_KOREAN_TITLE = "비트코인 현물 ETF 순유입 3거래일 연속 확대"

sm = importlib.import_module("collect_social_media")


def _no_translation(text: str) -> str:
    """실패한 번역기를 재현한다 — 입력을 그대로 돌려준다(fail-open)."""
    return text


def _lead(content: str) -> str:
    """Return the rendered first paragraph, HTML stripped."""
    first = content.strip().split("\n\n", 1)[0]
    return re.sub(r"<[^>]+>", " ", first).strip()


# ---------------------------------------------------------------------------
# collect_political_trades
# ---------------------------------------------------------------------------


def _political_content(title: str) -> str:
    mod = importlib.import_module("collect_political_trades")
    collector = mod.PoliticalTradesCollector()
    items = [
        {
            "title": title,
            "description": "설명",
            "url": "https://example.com/a",
            "source": "SEC",
            "category": "sec-insider",
        }
    ]
    captured: Dict[str, Any] = {}
    with (
        patch.object(collector, "fetch", return_value=items),
        patch.object(collector, "process", return_value=items),
        patch.object(collector, "is_duplicate_exact", return_value=False),
        patch.object(collector, "create_post", side_effect=lambda **kw: (captured.update(kw), "x.md")[1]),
        patch.object(collector, "mark_seen"),
        patch.object(collector, "save_state"),
        patch.object(collector, "log_summary"),
        patch("common.image_generator.generate_news_briefing_card", return_value=""),
        patch("common.headline.translate_to_korean", side_effect=_no_translation),
    ):
        collector.run()
    return captured["content"]


def test_political_english_headline_not_in_body_lead():
    assert _ENGLISH_TITLE not in _lead(_political_content(_ENGLISH_TITLE))


def test_political_korean_headline_kept_in_body_lead():
    assert _KOREAN_TITLE in _lead(_political_content(_KOREAN_TITLE))


# ---------------------------------------------------------------------------
# collect_crypto_news
# ---------------------------------------------------------------------------


def _crypto_content(title: str) -> str:
    mod = importlib.import_module("collect_crypto_news")
    collector = mod.CryptoNewsCollector()
    items = [
        {
            "title": title,
            "description": "설명입니다.",
            "url": "https://example.com/c",
            "link": "https://example.com/c",
            "source": "CoinDesk",
        }
    ]
    captured: Dict[str, Any] = {}
    with (
        patch.object(collector, "fetch", return_value=items),
        patch.object(collector, "process", side_effect=lambda x: x),
        patch.object(collector, "fetch_security", return_value=([], [])),
        patch.object(collector, "is_duplicate_exact", return_value=False),
        patch.object(collector, "create_post", side_effect=lambda **kw: (captured.update(kw), "x.md")[1]),
        patch.object(collector, "mark_seen"),
        patch.object(collector, "save_state"),
        patch("common.headline.translate_to_korean", side_effect=_no_translation),
    ):
        collector.run()
    return captured["content"]


def test_crypto_english_headline_not_in_body_lead():
    assert _ENGLISH_TITLE not in _lead(_crypto_content(_ENGLISH_TITLE))


def test_crypto_korean_headline_kept_in_body_lead():
    assert _KOREAN_TITLE in _lead(_crypto_content(_KOREAN_TITLE))


# ---------------------------------------------------------------------------
# collect_social_media
# ---------------------------------------------------------------------------


@pytest.fixture
def sm_no_network(monkeypatch):
    state: Dict[str, Any] = {"items": []}
    monkeypatch.setattr(sm, "is_playwright_available", lambda: False)
    monkeypatch.setattr(sm, "fetch_telegram_channel", lambda ch, limit=10: [])
    monkeypatch.setattr(sm, "fetch_twitter_search", lambda token, q, limit=10: [])
    monkeypatch.setattr(sm, "fetch_google_news_social", list)
    monkeypatch.setattr(sm, "fetch_reddit_posts", lambda limit=10: list(state["items"]))
    monkeypatch.setattr(sm, "fetch_political_economy_news", list)
    monkeypatch.setattr(sm, "enrich_items", lambda items, *a, **kw: None)
    return state


def _sm_items(titles: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "title": t,
            "description": "본문 설명입니다.",
            "link": f"https://reddit.com/r/x/{i}",
            "source": f"r/src{i}",
            "tags": ["social-media", "reddit"],
            "score": 5000 - i,
        }
        for i, t in enumerate(titles)
    ]


def _social_content(monkeypatch, state, title: str) -> str:
    state["items"] = _sm_items([title])
    collector = sm.SocialMediaCollector()
    monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
    captured: Dict[str, Any] = {}
    monkeypatch.setattr(collector, "create_post", lambda **kw: (captured.update(kw), "x.md")[1])
    monkeypatch.setattr(collector, "mark_seen", lambda *_a, **_kw: None)
    monkeypatch.setattr(collector, "save_state", lambda *_a, **_kw: None)
    monkeypatch.setattr("common.headline.translate_to_korean", _no_translation)
    collector.run()
    return captured["content"]


def test_social_english_headline_not_in_body_lead(monkeypatch, sm_no_network):
    assert _ENGLISH_TITLE not in _lead(_social_content(monkeypatch, sm_no_network, _ENGLISH_TITLE))


def test_social_korean_headline_kept_in_body_lead(monkeypatch, sm_no_network):
    assert _KOREAN_TITLE in _lead(_social_content(monkeypatch, sm_no_network, _KOREAN_TITLE))


# ---------------------------------------------------------------------------
# collect_fmp_calendar — raw ``event`` field, never translated
# ---------------------------------------------------------------------------


def _fmp_content(event_name: str) -> str:
    mod = importlib.import_module("collect_fmp_calendar")
    collector = mod.FmpCalendarCollector()
    events = [{"event": event_name, "date": "2026-09-02", "country": "US", "impact": "High"}]
    earnings = [{"symbol": "AAPL", "date": "2026-09-02"}]
    # ``fetch`` normally populates these; it is stubbed out here.
    collector._indices = []
    collector._sectors = []
    collector._economic_events = events
    collector._earnings = earnings
    collector._treasury_rates = []
    collector._ipo_data = []

    captured: Dict[str, Any] = {}
    with (
        patch.object(collector, "fetch", return_value=events),
        patch.object(collector, "process", side_effect=lambda x: x),
        patch.object(collector, "is_duplicate_exact", return_value=False),
        patch.object(collector, "create_post", side_effect=lambda **kw: (captured.update(kw), "x.md")[1]),
        patch.object(collector, "mark_seen"),
        patch.object(collector, "save_state"),
        patch("common.headline.translate_to_korean", side_effect=_no_translation),
    ):
        collector.run()
    return captured["content"]


def test_fmp_english_event_not_in_body_lead():
    assert _ENGLISH_EVENT not in _lead(_fmp_content(_ENGLISH_EVENT))


def test_fmp_korean_event_kept_in_body_lead():
    korean_event = "한국은행 기준금리 결정"
    assert korean_event in _lead(_fmp_content(korean_event))
