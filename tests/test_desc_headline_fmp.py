"""`collect_fmp_calendar.run()` 의 description 헤드라인이 한국어인지 검증한다.

## 무엇이 조용히 틀렸었나

`_desc_ko` 는 `economic_events[0]["event"]` 를 **그대로** 이어 붙였다. FMP 는 이
필드를 영어 문장으로 내려주므로("Treasury Sec Bessent Speaks"), 한국어 포스트의
description 이 영어로 끝났다. 표와 카운트는 멀쩡했고 워크플로우도 성공으로
끝나서, 이 결함은 `scripts/check_description_quality.py` 의 "번역 이슈" 집계에서만
드러났다 — 2026-08-29 / 2026-08-30 두 포스트가 그 사례다.

## 이 파일이 관측하는 것

`run()` 이 `create_post` 에 넘긴 `extra_frontmatter` 다. 최종 `.md` 를 읽으면
`post_generator` 의 generic-description 정책이 값을 갈아치울 수 있어 `run()` 자신의
계산을 관측할 수 없다.

번역은 `common.headline.translate_to_korean` 에서 끊는다 — `select_korean_headline`
자체를 대역으로 바꾸면 배선만 확인하고 **판정 로직은 검증하지 못한다**. 실제
헬퍼가 돌아야 fail-open 폴백(번역 실패 시 원문 반환)을 거르는지 알 수 있다.

## `symbol` 을 번역하면 안 되는 이유

`주목 실적:` 절이 쓰는 `earnings[0]["symbol"]` 은 티커다. ASCII 인 것이 정상이고
한국어 대응물이 없다. 헤드라인 가드를 여기까지 확장하면 fail-open 경로에서 "" 가
되어 절이 통째로 사라진다. 아래 `test_earnings_symbol_is_not_language_filtered` 가
그 확장을 RED 로 만든다.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

fmp = importlib.import_module("collect_fmp_calendar")

# FMP 가 실제로 내려주는 형태의 영어 이벤트명 — 결함 포스트에 박힌 문자열이다.
_ENGLISH_EVENT = "Treasury Sec Bessent Speaks"
_KOREAN_EVENT = "베선트 재무장관 연설"


def _event(**over: Any) -> Dict[str, Any]:
    """경제 이벤트 1건 — 키 집합은 `common/fmp_api.py` 생산자와 동일하다."""
    base = {
        "date": "2026-08-20",
        "country": "US",
        "event": "CPI",
        "impact": "High",
        "forecast": "3.0%",
        "previous": "2.9%",
        "actual": "3.1%",
    }
    base.update(over)
    return base


def _earn(**over: Any) -> Dict[str, Any]:
    """실적 1건 — `symbol` 이 유일한 식별자다 (회사명 키는 생산자에 없다)."""
    base = {
        "symbol": "AAPL",
        "date": "2026-08-20",
        "eps_estimated": "1.50",
        "revenue_estimated": "1000000",
        "time": "amc",
    }
    base.update(over)
    return base


@pytest.fixture
def isolated_posts(tmp_path, monkeypatch):
    """`create_post` 가 저장소 `_posts/` 대신 tmp 에 쓰게 한다."""
    from common import post_generator as pg

    posts = tmp_path / "_posts"
    posts.mkdir()
    monkeypatch.setattr(pg, "POSTS_DIR", str(posts))
    return posts


@pytest.fixture
def no_image_writes(monkeypatch):
    """브리핑 카드 렌더를 차단한다 — 켜두면 실제 이미지가 생성되고 느려진다."""
    import common.image_generator as ig

    monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *_a, **_kw: "")


@pytest.fixture
def fake_api(monkeypatch):
    """FMP fetch 함수 6개를 모듈 네임스페이스에서 대체한다 (HTTP 이전에 차단)."""
    state: Dict[str, Any] = {
        "indices": {"SPY": {"symbol": "SPY", "price": 512.0}},
        "sectors": [{"sector": "Technology", "change_pct": 1.0}],
        "economic": [],
        "earnings": [],
        "treasury": [{"maturity": "10Y", "rate": 4.25, "change": 0.01}],
        "ipo": [{"company": "Acme Inc", "date": "2026-08-21"}],
    }

    monkeypatch.setattr(fmp, "fetch_market_index_data", lambda s: dict(state["indices"].get(s) or {}))
    monkeypatch.setattr(fmp, "fetch_sector_performance", lambda: list(state["sectors"]))
    monkeypatch.setattr(fmp, "fetch_economic_calendar", lambda days_ahead=30: list(state["economic"]))
    monkeypatch.setattr(fmp, "fetch_earnings_calendar", lambda days_ahead=7: list(state["earnings"]))
    monkeypatch.setattr(fmp, "fetch_treasury_rates", lambda: list(state["treasury"]))
    monkeypatch.setattr(fmp, "fetch_ipo_calendar", lambda days_ahead=30: list(state["ipo"]))
    monkeypatch.setattr(fmp, "_INDEX_SYMBOLS", ["SPY", "QQQ"])
    return state


def _run_and_capture(monkeypatch) -> Dict[str, Any]:
    """`run()` 을 돌리고 `create_post` 에 넘어간 인자를 돌려준다."""
    collector = fmp.FmpCalendarCollector()
    captured: Dict[str, Any] = {}
    original = collector.create_post

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(collector, "create_post", spy)
    collector.run()
    assert captured, "run() 이 create_post 를 호출하지 않았다 — 픽스처가 포스트 생성 조건을 못 채웠다"
    return captured


def _desc(captured: Dict[str, Any]) -> str:
    return captured["extra_frontmatter"]["description_ko"]


class TestEventHeadlineIsKorean:
    def test_english_event_is_translated_before_it_reaches_the_description(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        fake_api["economic"] = [_event(event=_ENGLISH_EVENT)]
        fake_api["earnings"] = [_earn()]

        with patch("common.headline.translate_to_korean", return_value=_KOREAN_EVENT) as mock_tr:
            desc = _desc(_run_and_capture(monkeypatch))

        mock_tr.assert_called_once_with(_ENGLISH_EVENT)
        assert f"주목 이벤트: {_KOREAN_EVENT}." in desc
        assert _ENGLISH_EVENT not in desc

    def test_untranslatable_event_drops_the_clause_instead_of_leaking_english(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """`translate_to_korean` 은 실패 시 입력을 그대로 돌려준다(fail-open).

        그 반환값을 신뢰하면 결함 포스트가 그대로 재현된다. 절을 버리는 것이
        영어를 붙이는 것보다 낫다 — 나머지 문장이 이미 건수를 전달한다.
        """
        fake_api["economic"] = [_event(event=_ENGLISH_EVENT)]
        fake_api["earnings"] = []

        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            desc = _desc(_run_and_capture(monkeypatch))

        assert "주목 이벤트:" not in desc
        assert _ENGLISH_EVENT not in desc
        assert "Bessent" not in desc
        assert desc.startswith("경제 캘린더 ")

    def test_korean_event_is_passed_through_without_a_translation_call(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        fake_api["economic"] = [_event(event="소비자물가지수")]
        fake_api["earnings"] = [_earn()]

        with patch("common.headline.translate_to_korean") as mock_tr:
            desc = _desc(_run_and_capture(monkeypatch))

        mock_tr.assert_not_called()
        assert "주목 이벤트: 소비자물가지수." in desc

    def test_translated_event_is_still_truncated_to_thirty_characters(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """`[:30]` 슬라이스는 번역 뒤에도 살아 있어야 한다.

        뒤따르는 `[:160]` 캡은 이 입력 공간에서 도달하지 않으므로, 길이만
        단언하면 슬라이스를 지워도 통과하는 false green 이 된다.
        """
        fake_api["economic"] = [_event(event=_ENGLISH_EVENT)]
        fake_api["earnings"] = []

        with patch("common.headline.translate_to_korean", return_value="아" * 200):
            desc = _desc(_run_and_capture(monkeypatch))

        assert f"주목 이벤트: {'아' * 30}." in desc
        assert "아" * 31 not in desc
        assert len(desc) <= 160


class TestEarningsSymbolIsExempt:
    def test_earnings_symbol_is_not_language_filtered(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """티커는 ASCII 인 것이 정상이다 — 헤드라인 가드를 여기 적용하면 안 된다.

        가드를 `_next_earn` 까지 확장하면 fail-open 경로에서 "" 가 되어 절이
        사라진다. 이 테스트는 그 확장을 RED 로 만든다.
        """
        fake_api["economic"] = [_event(event="")]
        fake_api["earnings"] = [_earn(symbol="AAPL")]

        with patch("common.headline.translate_to_korean", side_effect=lambda t: t) as mock_tr:
            desc = _desc(_run_and_capture(monkeypatch))

        assert "주목 실적: AAPL 등." in desc
        translated: List[str] = [c.args[0] for c in mock_tr.call_args_list if c.args]
        assert "AAPL" not in translated, f"티커가 번역기로 넘어갔다: {translated}"

    def test_long_symbol_keeps_its_twenty_character_trim(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        fake_api["economic"] = [_event(event="")]
        fake_api["earnings"] = [_earn(symbol="가" * 50)]

        desc = _desc(_run_and_capture(monkeypatch))

        assert f"주목 실적: {'가' * 20} 등." in desc
        assert "가" * 21 not in desc
