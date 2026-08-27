"""`scripts/collect_geopolitical.py` 의 fetch·조립·수집기 경로 테스트.

`tests/test_collect_geopolitical.py` 는 `_build_polymarket_section` 의 엔터테인먼트
필터만 덮는다. 이 파일은 나머지를 덮는다:

- `_load_geo_keywords` 의 YAML → 기본값 fallback
- `fetch_polymarket` / `fetch_gdelt` / `fetch_google_news_geopolitical`
- 분류·라벨 순수 함수 (`_parse_probability`, `_tone_label`, `_classify_geo_theme`, ...)
- `_build_gdelt_section` / `_build_news_section` / `_generate_risk_analysis`
- `GeopoliticalCollector` 의 `fetch` / `run` / `_build_full_content` / `main`

## 네트워크

`tests/conftest.py` 가 `HTTPAdapter.send` 를 차단하지만, 그건 최후 방어선이다. 여기서는
모듈 네임스페이스의 `request_with_retry` · `fetch_rss_feeds_concurrent` 를 대체해
**HTTP 계층에 도달하기 전에** 끊는다. 대체하지 않은 경로가 남으면 차단이 예외로
드러나므로, "조용히 실제 호출" 은 일어날 수 없다.

## 디스크

`run()` 은 포스트를 만든다. `common.post_generator.POSTS_DIR` 을 tmp 로 돌린다
(dedup `STATE_DIR` 은 conftest autouse 가 이미 tmp 로 보낸다).
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

import pytest

geo = importlib.import_module("collect_geopolitical")


class _FakeResponse:
    """`request_with_retry` 반환값 대역 — `.json()` 만 쓴다."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _market(**over: Any) -> Dict[str, Any]:
    base = {
        "question": "Will new sanctions hit Iran this quarter?",
        "volume": 50_000,
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.6", "0.4"],
        "endDate": "2026-12-31T00:00:00Z",
        "slug": "iran-sanctions",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# _load_geo_keywords
# ---------------------------------------------------------------------------


class TestLoadGeoKeywords:
    def test_uses_yaml_keywords_when_present(self, monkeypatch) -> None:
        monkeypatch.setattr(geo, "_geo_cfg", {"keywords": {"geo_keywords": ["alpha", "beta"]}})
        assert geo._load_geo_keywords() == frozenset({"alpha", "beta"})

    def test_falls_back_when_keywords_section_is_not_a_dict(self, monkeypatch) -> None:
        monkeypatch.setattr(geo, "_geo_cfg", {"keywords": ["not", "a", "dict"]})
        result = geo._load_geo_keywords()
        assert "sanction" in result, "하드코딩 기본값으로 떨어지지 않았다"

    @pytest.mark.parametrize("geo_raw", [None, [], "문자열", {}])
    def test_falls_back_when_geo_keywords_missing_or_wrong_type(self, monkeypatch, geo_raw) -> None:
        monkeypatch.setattr(geo, "_geo_cfg", {"keywords": {"geo_keywords": geo_raw}})
        assert "sanction" in geo._load_geo_keywords()

    def test_fallback_is_not_empty(self, monkeypatch) -> None:
        """기본값이 비면 Polymarket 필터가 전부를 버린다 — 빈 fallback 은 무해하지 않다."""
        monkeypatch.setattr(geo, "_geo_cfg", {})
        assert len(geo._load_geo_keywords()) > 50


# ---------------------------------------------------------------------------
# fetch_polymarket
# ---------------------------------------------------------------------------


class TestFetchPolymarket:
    def _patch(self, monkeypatch, payload: Any, calls: List[Dict[str, Any]] | None = None):
        def fake(url, params=None, timeout=None, verify_ssl=True, headers=None):
            if calls is not None:
                calls.append({"url": url, "params": params, "timeout": timeout})
            return _FakeResponse(payload)

        monkeypatch.setattr(geo, "request_with_retry", fake)

    def test_parses_market_into_item(self, monkeypatch) -> None:
        self._patch(monkeypatch, [_market()])
        items = geo.fetch_polymarket(limit=1)
        assert len(items) == 1
        item = items[0]
        assert item["title"] == "Will new sanctions hit Iran this quarter?"
        assert item["link"] == "https://polymarket.com/event/iran-sanctions"
        assert item["source"] == "Polymarket"
        assert item["volume"] == 50_000
        assert "예측 확률: 🟢 Yes 60%" in item["description"]
        assert "거래량: $50,000" in item["description"]
        assert "마감: 2026-12-31" in item["description"]

    def test_dict_response_uses_markets_key(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"markets": [_market()]})
        assert len(geo.fetch_polymarket(limit=1)) == 1

    def test_low_volume_market_is_filtered(self, monkeypatch) -> None:
        monkeypatch.setattr(geo, "_POLYMARKET_MIN_VOLUME", 10_000)
        self._patch(monkeypatch, [_market(volume=500)])
        assert geo.fetch_polymarket(limit=5) == []

    def test_missing_volume_is_kept_as_na(self, monkeypatch) -> None:
        """거래량을 못 읽으면 버리지 않고 N/A 로 표기한다."""
        self._patch(monkeypatch, [_market(volume=None, volumeNum=None)])
        (item,) = geo.fetch_polymarket(limit=1)
        assert "거래량: N/A" in item["description"]
        assert item["volume"] == 0

    def test_non_dict_entries_are_skipped(self, monkeypatch) -> None:
        """limit=1 로 태그 1개만 돌린다 — 같은 payload 가 태그마다 반복 수집되면 개수가 흐려진다."""
        self._patch(monkeypatch, ["문자열", None, 42, _market()])
        assert len(geo.fetch_polymarket(limit=1)) == 1

    def test_empty_question_is_skipped(self, monkeypatch) -> None:
        self._patch(monkeypatch, [_market(question="")])
        assert geo.fetch_polymarket(limit=5) == []

    def test_slugless_market_falls_back_to_site_root(self, monkeypatch) -> None:
        self._patch(monkeypatch, [_market(slug="", conditionId="")])
        (item,) = geo.fetch_polymarket(limit=1)
        assert item["link"] == "https://polymarket.com"

    def test_results_sorted_by_volume_desc_and_truncated(self, monkeypatch) -> None:
        payload = [
            _market(question="낮은 거래량 sanctions", volume=20_000, slug="a"),
            _market(question="높은 거래량 sanctions", volume=90_000, slug="b"),
            _market(question="중간 거래량 sanctions", volume=50_000, slug="c"),
        ]
        self._patch(monkeypatch, payload)
        items = geo.fetch_polymarket(limit=2)
        assert [i["volume"] for i in items] == [90_000, 50_000]

    def test_stops_requesting_tags_once_limit_reached(self, monkeypatch) -> None:
        """태그를 전부 돌지 않는다 — limit 을 채우면 남은 태그는 요청하지 않는다."""
        calls: List[Dict[str, Any]] = []
        self._patch(monkeypatch, [_market()], calls)
        geo.fetch_polymarket(limit=1)
        assert len(calls) == 1, f"태그 {len(calls)}개를 요청했다 — 조기 종료가 사라졌다"
        assert len(geo._POLYMARKET_GEO_TAGS) > 1, "이 테스트는 태그가 2개 이상임을 전제한다"

    def test_tag_is_recorded_on_the_item(self, monkeypatch) -> None:
        self._patch(monkeypatch, [_market()])
        (item,) = geo.fetch_polymarket(limit=1)
        assert geo._POLYMARKET_GEO_TAGS[0] in item["tags"]

    def test_request_exception_is_swallowed_per_tag(self, monkeypatch, caplog) -> None:
        import requests

        def boom(*_a, **_kw):
            raise requests.exceptions.ConnectionError("네트워크 끊김")

        monkeypatch.setattr(geo, "request_with_retry", boom)
        with caplog.at_level("WARNING"):
            assert geo.fetch_polymarket(limit=5) == []
        assert any("Polymarket request failed" in r.message for r in caplog.records)

    def test_parse_error_is_swallowed_per_tag(self, monkeypatch, caplog) -> None:
        self._patch(monkeypatch, ValueError("JSON 아님"))
        with caplog.at_level("WARNING"):
            assert geo.fetch_polymarket(limit=5) == []
        assert any("Polymarket parse error" in r.message for r in caplog.records)

    def test_limit_defaults_from_config(self, monkeypatch) -> None:
        """limit=None 이면 collectors.yml 값을 쓴다 — 무제한이 아니다."""
        self._patch(monkeypatch, [_market(question=f"sanctions {i}", slug=str(i)) for i in range(200)])
        items = geo.fetch_polymarket()
        assert 0 < len(items) <= 200


# ---------------------------------------------------------------------------
# _parse_float / _parse_probability
# ---------------------------------------------------------------------------


class TestParseFloat:
    @pytest.mark.parametrize(("value", "expected"), [("1.5", 1.5), (2, 2.0), (3.5, 3.5), ("0", 0.0)])
    def test_parses_numeric(self, value, expected) -> None:
        assert geo._parse_float(value) == expected

    @pytest.mark.parametrize("value", [None, "abc", [], {}, object()])
    def test_returns_none_for_unparseable(self, value) -> None:
        assert geo._parse_float(value) is None


class TestParseProbability:
    @pytest.mark.parametrize(("outcomes", "prices"), [([], []), (["Yes"], []), ([], ["0.5"])])
    def test_missing_data_is_na(self, outcomes, prices) -> None:
        assert geo._parse_probability(outcomes, prices) == "N/A"

    def test_all_prices_unparseable_is_na(self) -> None:
        assert geo._parse_probability(["Yes", "No"], ["abc", None]) == "N/A"

    def test_binary_yes_dominant(self) -> None:
        assert geo._parse_probability(["Yes", "No"], ["0.73", "0.27"]) == "🟢 Yes 73%"

    def test_binary_no_dominant(self) -> None:
        assert geo._parse_probability(["Yes", "No"], ["0.2", "0.8"]) == "🔴 No 80%"

    def test_percent_scale_is_normalized(self) -> None:
        """1 을 넘는 값은 퍼센트로 보고 100 으로 나눈다."""
        assert geo._parse_probability(["Yes", "No"], ["73", "27"]) == "🟢 Yes 73%"

    def test_multi_outcome_shows_top_two_sorted(self) -> None:
        result = geo._parse_probability(
            ["Alpha", "Beta", "Gamma"],
            ["0.2", "0.5", "0.3"],
        )
        assert result == "Beta 50% / Gamma 30%"

    def test_only_first_four_outcomes_are_considered(self) -> None:
        outcomes = ["A", "B", "C", "D", "E"]
        prices = ["0.1", "0.1", "0.1", "0.1", "0.9"]
        assert "E" not in geo._parse_probability(outcomes, prices)

    def test_prices_shorter_than_outcomes(self) -> None:
        assert geo._parse_probability(["Yes", "No"], ["0.6"]) == "Yes 60%"


# ---------------------------------------------------------------------------
# fetch_gdelt / _tone_label
# ---------------------------------------------------------------------------


class TestFetchGdelt:
    def _patch(self, monkeypatch, payload: Any, calls: List[Dict[str, Any]] | None = None):
        def fake(url, params=None, timeout=None, verify_ssl=True, headers=None):
            if calls is not None:
                calls.append({"url": url, "params": params, "timeout": timeout})
            return _FakeResponse(payload)

        monkeypatch.setattr(geo, "request_with_retry", fake)

    def test_parses_article(self, monkeypatch) -> None:
        payload = {
            "articles": [
                {
                    "title": "Sanctions tighten on Iran",
                    "url": "https://example.com/a",
                    "domain": "example.com",
                    "seendate": "20260827T000000Z",
                    "tone": "-6.2",
                }
            ]
        }
        self._patch(monkeypatch, payload)
        (item,) = geo.fetch_gdelt(limit=5)
        assert item["title"] == "Sanctions tighten on Iran"
        assert item["source"] == "GDELT/example.com"
        assert item["tone"] == pytest.approx(-6.2)
        assert "감성 점수: -6.2 (매우 부정)" in item["description"]

    def test_uses_longer_timeout_than_global_default(self, monkeypatch) -> None:
        """GDELT 는 느려서(~20s) 전역 15s 기본값으로는 항상 타임아웃한다."""
        calls: List[Dict[str, Any]] = []
        self._patch(monkeypatch, {"articles": []}, calls)
        geo.fetch_gdelt(limit=1)
        assert calls[0]["timeout"] >= 45, calls[0]["timeout"]

    def test_maxrecords_is_capped_at_75(self, monkeypatch) -> None:
        calls: List[Dict[str, Any]] = []
        self._patch(monkeypatch, {"articles": []}, calls)
        geo.fetch_gdelt(limit=500)
        assert calls[0]["params"]["maxrecords"] == 75

    def test_non_list_articles_returns_empty(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"articles": "리스트 아님"})
        assert geo.fetch_gdelt() == []

    def test_missing_articles_key_returns_empty(self, monkeypatch) -> None:
        self._patch(monkeypatch, {})
        assert geo.fetch_gdelt() == []

    def test_empty_title_is_skipped(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"articles": [{"title": "", "url": "https://example.com/a"}]})
        assert geo.fetch_gdelt() == []

    def test_limit_truncates_articles(self, monkeypatch) -> None:
        articles = [{"title": f"Sanctions news {i}", "url": f"https://example.com/{i}"} for i in range(10)]
        self._patch(monkeypatch, {"articles": articles})
        assert len(geo.fetch_gdelt(limit=3)) == 3

    def test_missing_tone_renders_na(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"articles": [{"title": "Sanctions news", "url": "https://e.com/a"}]})
        (item,) = geo.fetch_gdelt()
        assert "감성 점수: N/A (중립)" in item["description"]
        assert item["tone"] == 0.0

    def test_falls_back_to_sourcecountry_then_gdelt(self, monkeypatch) -> None:
        self._patch(
            monkeypatch,
            {"articles": [{"title": "Sanctions news", "url": "https://e.com/a", "sourcecountry": "KR"}]},
        )
        (item,) = geo.fetch_gdelt()
        assert item["source"] == "GDELT/KR"

    def test_request_exception_is_swallowed(self, monkeypatch, caplog) -> None:
        import requests

        def boom(*_a, **_kw):
            raise requests.exceptions.Timeout("느림")

        monkeypatch.setattr(geo, "request_with_retry", boom)
        with caplog.at_level("WARNING"):
            assert geo.fetch_gdelt() == []
        assert any("GDELT request failed" in r.message for r in caplog.records)

    def test_parse_error_is_swallowed(self, monkeypatch, caplog) -> None:
        self._patch(monkeypatch, ValueError("JSON 아님"))
        with caplog.at_level("WARNING"):
            assert geo.fetch_gdelt() == []
        assert any("GDELT parse error" in r.message for r in caplog.records)


class TestToneLabel:
    @pytest.mark.parametrize(
        ("tone", "expected"),
        [
            (None, "중립"),
            (-9.0, "매우 부정"),
            (-5.0, "매우 부정"),
            (-4.9, "부정"),
            (-2.0, "부정"),
            (-1.9, "중립"),
            (0.0, "중립"),
            (1.9, "중립"),
            (2.0, "긍정"),
            (4.9, "긍정"),
            (5.0, "매우 긍정"),
            (9.0, "매우 긍정"),
        ],
    )
    def test_thresholds(self, tone, expected) -> None:
        assert geo._tone_label(tone) == expected


# ---------------------------------------------------------------------------
# fetch_google_news_geopolitical
# ---------------------------------------------------------------------------


class TestFetchGoogleNews:
    def test_passes_three_feeds_to_the_shared_fetcher(self, monkeypatch) -> None:
        captured: List[Any] = []

        def fake(feeds):
            captured.append(feeds)
            return [{"title": "지정학 뉴스"}]

        monkeypatch.setattr(geo, "fetch_rss_feeds_concurrent", fake)
        assert geo.fetch_google_news_geopolitical() == [{"title": "지정학 뉴스"}]

        (feeds,) = captured
        assert len(feeds) == 3
        assert all(url.startswith("https://news.google.com/rss/") for url, _label, _tags in feeds)
        labels = [label for _url, label, _tags in feeds]
        assert labels == [
            "Google News EN (Geopolitical)",
            "Google News EN (Conflict)",
            "Google News KR (지정학)",
        ]

    def test_korean_feed_is_included(self, monkeypatch) -> None:
        """한국어 피드가 빠지면 한글 기사가 0건이 되지만 수집은 성공으로 보인다."""
        captured: List[Any] = []
        monkeypatch.setattr(geo, "fetch_rss_feeds_concurrent", lambda feeds: captured.append(feeds) or [])
        geo.fetch_google_news_geopolitical()
        tags = [tags for _u, _l, tags in captured[0]]
        assert ["geopolitical", "risk", "korean"] in tags


# ---------------------------------------------------------------------------
# 분류 / 리스크 레벨
# ---------------------------------------------------------------------------


class TestClassifyGeoTheme:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("New sanctions on Iran", "제재/경제압박"),
            ("추가 제재 발표", "제재/경제압박"),
            ("Embargo extended", "제재/경제압박"),
            ("Presidential election results", "선거/정치"),
            ("총선 선거 결과", "선거/정치"),
            ("Missile strike reported", "군사/분쟁"),
            ("전쟁 장기화 우려", "군사/분쟁"),
            ("Nuclear test detected", "핵/WMD"),
            ("ICBM launch confirmed", "핵/WMD"),
            ("New tariff on imports", "무역/공급망"),
            ("공급망 재편 논의", "무역/공급망"),
            ("OPEC output decision", "에너지/자원"),
            ("원유 가격 급등", "에너지/자원"),
            ("Summit opens in Geneva", "외교/협상"),
            ("외교 채널 복원", "외교/협상"),
            ("Central bank holds steady", "기타 지정학"),
        ],
    )
    def test_theme_mapping(self, title, expected) -> None:
        assert geo._classify_geo_theme(title) == expected

    def test_priority_is_first_match_wins(self) -> None:
        """if 사슬 순서가 곧 우선순위다 — 제재가 군사보다 앞선다."""
        assert geo._classify_geo_theme("Sanctions follow missile strike") == "제재/경제압박"

    def test_classification_is_case_insensitive(self) -> None:
        assert geo._classify_geo_theme("SANCTIONS ANNOUNCED") == "제재/경제압박"


class TestRiskLevelFromTheme:
    @pytest.mark.parametrize("theme", ["군사/분쟁", "핵/WMD", "제재/경제압박"])
    def test_high_risk(self, theme) -> None:
        assert geo._risk_level_from_theme(theme) == "높음"

    @pytest.mark.parametrize("theme", ["무역/공급망", "에너지/자원", "선거/정치"])
    def test_medium_risk(self, theme) -> None:
        assert geo._risk_level_from_theme(theme) == "중간"

    @pytest.mark.parametrize("theme", ["외교/협상", "기타 지정학", "존재하지 않는 테마"])
    def test_low_risk(self, theme) -> None:
        assert geo._risk_level_from_theme(theme) == "낮음"


# ---------------------------------------------------------------------------
# _build_gdelt_section
# ---------------------------------------------------------------------------


def _article(title: str, *, tone: float = 0.0, source: str = "example.com", link: str = "") -> Dict[str, Any]:
    return {"title": title, "tone": tone, "source": source, "link": link or f"https://{source}/x"}


class TestBuildGdeltSection:
    """정렬·중복제거·상한 등 **구조** 규칙.

    언어 게이트는 여기서 통과시킨다. `_is_supported_language` 는 짧은 라틴 제목에서
    langdetect 에 의존하는데(`"Grim news"` → False), 그 판정에 구조 단언을 묶으면
    langdetect 버전이 바뀔 때 무관한 테스트가 깨진다. 게이트 자체는 아래
    `TestBuildGdeltSectionLanguageFilter` 가 결정적 입력으로 검증한다.
    """

    @pytest.fixture(autouse=True)
    def _pass_language_gate(self, monkeypatch):
        monkeypatch.setattr(geo, "_is_supported_language", lambda _title: True)

    def test_no_articles_message(self) -> None:
        assert geo._build_gdelt_section([]) == ["현재 GDELT에서 수집된 지정학 뉴스가 없습니다.\n"]

    def test_all_filtered_out_message(self) -> None:
        """템플릿 스팸만 남으면 '수집 없음' 과 다른 문구를 낸다 — 원인이 구분돼야 한다."""
        result = geo._build_gdelt_section([_article("Time. ai")])
        assert result == ["현재 GDELT에서 한국어·영어 지정학 뉴스가 수집되지 않았습니다.\n"]

    def test_noise_regex_only_matches_the_whole_title(self) -> None:
        """`Time. ai` 정규식은 제목 전체 일치다 — 그 문구를 포함한 실제 기사는 남는다."""
        rendered = "\n".join(geo._build_gdelt_section([_article("Time. ai firms face sanctions")]))
        assert "Time. ai firms face sanctions" in rendered

    def test_templated_noise_title_is_dropped(self) -> None:
        rendered = "\n".join(geo._build_gdelt_section([_article("Time. ai"), _article("Sanctions tighten")]))
        assert "Time. ai" not in rendered
        assert "Sanctions tighten" in rendered

    def test_articles_without_title_are_dropped(self) -> None:
        rendered = "\n".join(geo._build_gdelt_section([{"tone": 0.0}, _article("Sanctions tighten")]))
        assert "Sanctions tighten" in rendered

    def test_sorted_most_negative_first(self) -> None:
        """가장 부정적인 톤이 먼저 온다 — 리스크 신호가 가장 강한 순서."""
        articles = [
            _article("Mild story", tone=1.0, source="a.com"),
            _article("Grim story", tone=-8.0, source="b.com"),
            _article("Neutral story", tone=0.5, source="c.com"),
        ]
        rendered = "\n".join(geo._build_gdelt_section(articles))
        assert rendered.index("Grim story") < rendered.index("Neutral story") < rendered.index("Mild story")

    def test_at_most_two_articles_per_source(self) -> None:
        articles = [_article(f"Sanctions story {i}", tone=-float(i), source="flood.com") for i in range(5)]
        rendered = "\n".join(geo._build_gdelt_section(articles))
        shown = [i for i in range(5) if f"Sanctions story {i}" in rendered]
        assert len(shown) == 2, f"한 도메인에서 {len(shown)}건이 노출됐다 — 캡이 사라졌다"

    def test_shows_at_most_five_articles(self) -> None:
        articles = [_article(f"Sanctions story {i}", tone=-float(i), source=f"s{i}.com") for i in range(9)]
        rendered = "\n".join(geo._build_gdelt_section(articles))
        assert sum(1 for i in range(9) if f"Sanctions story {i}" in rendered) == 5

    def test_meaningful_tones_render_per_article_scores(self) -> None:
        rendered = "\n".join(geo._build_gdelt_section([_article("Sanctions tighten", tone=-6.2)]))
        assert "평균 톤 `-6.20`" in rendered
        assert "감성: `-6.2` (매우 부정)" in rendered

    def test_uniform_zero_tone_hides_per_article_scores(self) -> None:
        """GDELT 가 톤을 안 주는 배치에서 0.0 을 반복 표기하면 잡음만 늘어난다."""
        articles = [_article(f"Sanctions story {i}", tone=0.0, source=f"s{i}.com") for i in range(3)]
        rendered = "\n".join(geo._build_gdelt_section(articles))
        assert "모든 기사 톤이 0.0(중립)" in rendered
        assert "감성: `0.0`" not in rendered

    def test_link_is_used_when_present(self) -> None:
        rendered = "\n".join(
            geo._build_gdelt_section([_article("Sanctions tighten", tone=-3.0, link="https://e.com/a")])
        )
        assert "[Sanctions tighten](https://e.com/a)" in rendered

    def test_missing_link_renders_plain_title(self) -> None:
        article = _article("Sanctions tighten", tone=-3.0)
        article["link"] = ""
        rendered = "\n".join(geo._build_gdelt_section([article]))
        assert "**1. Sanctions tighten**" in rendered


# ---------------------------------------------------------------------------
# _build_news_section
# ---------------------------------------------------------------------------


class TestBuildNewsSection:
    def test_empty_items(self) -> None:
        assert geo._build_news_section([]) == []

    def test_renders_table_with_theme_and_risk(self) -> None:
        items = [
            {"title": "New sanctions on Iran", "link": "https://e.com/a", "source": "Reuters"},
            {"title": "Summit opens in Geneva", "link": "https://e.com/b", "source": "AP"},
        ]
        rendered = "\n".join(geo._build_news_section(items))
        assert "제재/경제압박" in rendered and "높음" in rendered
        assert "외교/협상" in rendered and "낮음" in rendered
        assert "Reuters" in rendered and "AP" in rendered

    def test_untitled_items_are_skipped(self) -> None:
        items = [{"title": "", "link": "https://e.com/a"}, {"title": "New sanctions", "link": "https://e.com/b"}]
        rendered = "\n".join(geo._build_news_section(items))
        assert rendered.count("|") > 0
        assert "New sanctions" in rendered

    def test_all_untitled_yields_no_table(self) -> None:
        assert geo._build_news_section([{"title": ""}]) == []

    def test_caps_at_fifteen_items(self) -> None:
        items = [{"title": f"Sanctions item {i}", "link": f"https://e.com/{i}"} for i in range(20)]
        rendered = "\n".join(geo._build_news_section(items))
        assert "Sanctions item 14" in rendered
        assert "Sanctions item 15" not in rendered

    def test_theme_distribution_shows_top_four(self) -> None:
        items = [
            {"title": "New sanctions on Iran"},
            {"title": "Election results in"},
            {"title": "Missile strike reported"},
            {"title": "Tariff hike announced"},
            {"title": "OPEC output decision"},
        ]
        rendered = "\n".join(geo._build_news_section(items))
        assert "**테마 분포**" in rendered
        assert rendered.count("건)") == 4, rendered

    def test_missing_link_renders_bold_title_without_anchor(self) -> None:
        rendered = "\n".join(geo._build_news_section([{"title": "New sanctions", "source": "Reuters"}]))
        assert "**New sanctions**" in rendered
        assert "](" not in rendered


# ---------------------------------------------------------------------------
# _generate_risk_analysis
# ---------------------------------------------------------------------------


class TestGenerateRiskAnalysis:
    def _run(self, markets=None, gdelt=None, news=None) -> str:
        return "\n".join(geo._generate_risk_analysis(markets or [], gdelt or [], news or [], "2026-08-27"))

    def test_stable_when_no_input(self) -> None:
        rendered = self._run()
        assert "종합 지정학 리스크 레벨: 안정" in rendered
        assert "글로벌 지정학적 환경이 비교적 안정적입니다." in rendered

    @pytest.mark.parametrize(
        ("military_count", "expected_level"),
        [(1, "낮음"), (4, "보통"), (6, "높음"), (11, "매우 높음")],
    )
    def test_risk_level_thresholds(self, military_count, expected_level) -> None:
        news = [{"title": "Missile strike reported"} for _ in range(military_count)]
        assert f"종합 지정학 리스크 레벨: {expected_level}" in self._run(news=news)

    def test_score_is_reported_with_scale_hint(self) -> None:
        """'점수: 32' 만 있으면 독자가 크기를 판단할 수 없다 — 척도를 함께 낸다."""
        rendered = self._run(news=[{"title": "Missile strike"}])
        assert "점수: 4" in rendered
        assert "척도 0~50+" in rendered

    def test_gdelt_titles_also_feed_the_score(self) -> None:
        gdelt = [{"title": "Nuclear test detected", "tone": -3.0}]
        rendered = self._run(gdelt=gdelt)
        assert "핵/WMD" in rendered
        assert "점수: 5" in rendered

    def test_top_themes_listed(self) -> None:
        news = [{"title": "New sanctions"}, {"title": "New sanctions"}, {"title": "Election day"}]
        rendered = self._run(news=news)
        assert "**핵심 테마**" in rendered
        assert "제재/경제압박**(2건)" in rendered

    def test_polymarket_signal_uses_top_market(self) -> None:
        markets = [{"title": "Will sanctions hit Iran?", "probability": "🟢 Yes 60%"}]
        rendered = self._run(markets=markets)
        assert "예측 시장 신호" in rendered
        assert "Will sanctions hit Iran?" in rendered
        assert "🟢 Yes 60%" in rendered

    def test_negative_average_tone_flags_risk_premium(self) -> None:
        gdelt = [{"title": "Grim news", "tone": -6.0}]
        rendered = self._run(gdelt=gdelt)
        assert "리스크 프리미엄 상승 가능성" in rendered

    def test_neutral_average_tone_says_so(self) -> None:
        gdelt = [{"title": "Calm news", "tone": 0.5}]
        assert "중립적 보도 기조 유지 중" in self._run(gdelt=gdelt)

    def test_non_numeric_tones_are_ignored(self) -> None:
        gdelt = [{"title": "Calm news", "tone": "문자열"}]
        assert "GDELT 글로벌 뉴스 감성" not in self._run(gdelt=gdelt)

    def test_military_theme_adds_defense_implication(self) -> None:
        rendered = self._run(news=[{"title": "Missile strike reported"}])
        assert "방산·사이버보안 섹터 주목" in rendered
        assert "안전자산 비중 점검" in rendered

    def test_nuclear_theme_also_adds_defense_implication(self) -> None:
        assert "방산·사이버보안 섹터 주목" in self._run(news=[{"title": "Nuclear test detected"}])

    def test_energy_theme_adds_oil_implication(self) -> None:
        assert "WTI/Brent" in self._run(news=[{"title": "OPEC output decision"}])

    def test_trade_theme_adds_supply_chain_implication(self) -> None:
        assert "글로벌 공급망 관련 섹터" in self._run(news=[{"title": "Tariff hike announced"}])

    def test_election_theme_adds_event_driven_implication(self) -> None:
        assert "이벤트 드리븐 전략" in self._run(news=[{"title": "Election results in"}])

    def test_disclaimer_is_preceded_by_a_blank_line(self) -> None:
        """kramdown 은 목록/HTML 뒤 빈 줄이 없으면 '>' 를 &gt; 로 이스케이프한다."""
        lines = geo._generate_risk_analysis([], [], [{"title": "Missile strike"}], "2026-08-27")
        quote_idx = next(i for i, ln in enumerate(lines) if ln.startswith("> *"))
        assert lines[quote_idx - 1] == "", lines[quote_idx - 3 : quote_idx + 1]


class TestBuildGdeltSectionLanguageFilter:
    """언어 게이트만 따로 — 스크립트 검사로 결정되는 입력만 쓴다.

    `is_supported_language` 는 한글이 있으면 즉시 True, CJK 한자·키릴은 즉시 False 다
    (langdetect 를 타지 않는다). 라틴 제목은 langdetect 판정이라 여기서 쓰지 않는다.
    """

    def test_korean_title_is_kept(self) -> None:
        rendered = "\n".join(geo._build_gdelt_section([_article("이란 제재 강화 발표", tone=-3.0)]))
        assert "이란 제재 강화 발표" in rendered

    @pytest.mark.parametrize(
        "title",
        [
            "Российские санкции усилены сегодня",  # 키릴
            "中国宣布新的贸易限制措施",  # CJK 한자
        ],
    )
    def test_unreadable_script_titles_are_dropped(self, title: str) -> None:
        result = geo._build_gdelt_section([_article(title, tone=-3.0)])
        assert result == ["현재 GDELT에서 한국어·영어 지정학 뉴스가 수집되지 않았습니다.\n"], result

    def test_korean_survives_alongside_dropped_script(self) -> None:
        articles = [
            _article("中国宣布新的贸易限制措施", tone=-9.0, source="cn.com"),
            _article("이란 제재 강화 발표", tone=-3.0, source="kr.com"),
        ]
        rendered = "\n".join(geo._build_gdelt_section(articles))
        assert "이란 제재 강화 발표" in rendered
        assert "中国宣布" not in rendered


# ---------------------------------------------------------------------------
# GeopoliticalCollector
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_posts(tmp_path, monkeypatch):
    """`create_post` 가 저장소 `_posts/` 대신 tmp 에 쓰게 한다.

    dedup `STATE_DIR` 은 conftest autouse 가 이미 tmp 로 보낸다.
    """
    from common import post_generator as pg

    posts = tmp_path / "_posts"
    posts.mkdir()
    monkeypatch.setattr(pg, "POSTS_DIR", str(posts))
    return posts


@pytest.fixture
def no_image_writes(monkeypatch):
    """브리핑 카드 생성을 기본 차단한다 — 켜두면 `assets/images/generated/` 를 오염시킨다.

    `run()` 은 실제 `generate_news_briefing_card` 를 호출해 저장소 트리에 PNG/WEBP/AVIF 를
    쓴다. 작성 중 실제로 3개 파일이 수정돼 `git checkout` 으로 복구했다. 카드 자체를
    검증하는 테스트는 이 fixture 뒤에 다시 `setattr` 해 덮어쓴다(나중 것이 이긴다).
    """
    import common.image_generator as ig

    monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *_a, **_kw: "")


@pytest.fixture
def no_network(monkeypatch):
    """세 소스를 전부 대체해 HTTP 계층에 닿지 않게 한다. 기본값은 '빈 결과'."""
    state: Dict[str, Any] = {"markets": [], "gdelt": [], "news": []}
    monkeypatch.setattr(geo, "fetch_polymarket", lambda **_kw: list(state["markets"]))
    monkeypatch.setattr(geo, "fetch_gdelt", lambda **_kw: list(state["gdelt"]))
    monkeypatch.setattr(geo, "fetch_google_news_geopolitical", lambda: list(state["news"]))
    monkeypatch.setattr(geo, "enrich_items", lambda items, ctx, **_kw: items)
    return state


class TestCollectorFetch:
    def test_tags_items_by_source(self, no_network) -> None:
        no_network["markets"] = [{"title": "sanctions market"}]
        no_network["gdelt"] = [{"title": "sanctions article"}]
        no_network["news"] = [{"title": "sanctions news", "link": "https://e.com/a"}]

        items = geo.GeopoliticalCollector().fetch()
        assert [i["_geo_source"] for i in items] == ["polymarket", "gdelt", "google_news"]

    def test_each_source_failure_is_isolated(self, monkeypatch, no_network, caplog) -> None:
        """한 소스가 죽어도 나머지는 수집된다 — 이 수집기의 핵심 내구성 속성."""

        def boom(**_kw):
            raise RuntimeError("소스 장애")

        monkeypatch.setattr(geo, "fetch_polymarket", boom)
        no_network["gdelt"] = [{"title": "sanctions article"}]

        with caplog.at_level("WARNING"):
            items = geo.GeopoliticalCollector().fetch()
        assert [i["_geo_source"] for i in items] == ["gdelt"]
        assert any("Polymarket collection failed entirely" in r.message for r in caplog.records)

    @pytest.mark.parametrize(
        ("target", "message"),
        [
            ("fetch_gdelt", "GDELT collection failed entirely"),
            ("fetch_google_news_geopolitical", "Google News collection failed entirely"),
        ],
    )
    def test_other_source_failures_are_logged(self, monkeypatch, no_network, caplog, target, message) -> None:
        def boom(*_a, **_kw):
            raise RuntimeError("소스 장애")

        monkeypatch.setattr(geo, target, boom)
        with caplog.at_level("WARNING"):
            geo.GeopoliticalCollector().fetch()
        assert any(message in r.message for r in caplog.records)

    def test_news_items_are_enriched_and_deduped(self, monkeypatch, no_network) -> None:
        enriched: List[Any] = []
        monkeypatch.setattr(geo, "enrich_items", lambda items, ctx, **_kw: enriched.append(items) or items)
        no_network["news"] = [
            {"title": "sanctions news", "link": "https://e.com/same"},
            {"title": "sanctions news 중복", "link": "https://e.com/same"},
        ]
        items = geo.GeopoliticalCollector().fetch()
        assert enriched, "enrich_items 가 호출되지 않았다"
        assert len([i for i in items if i["_geo_source"] == "google_news"]) == 1, "URL 중복이 제거되지 않았다"

    def test_enrichment_skipped_when_no_news(self, monkeypatch, no_network) -> None:
        called: List[Any] = []
        monkeypatch.setattr(geo, "enrich_items", lambda *a, **kw: called.append(1))
        geo.GeopoliticalCollector().fetch()
        assert not called


class TestCollectorSimpleHooks:
    def test_process_is_passthrough(self) -> None:
        items = [{"title": "a"}]
        assert geo.GeopoliticalCollector().process(items) is items

    def test_build_title_includes_date(self) -> None:
        collector = geo.GeopoliticalCollector()
        assert collector.build_title([]) == f"지정학 리스크 리포트 - {collector.today}"

    def test_default_tags(self) -> None:
        assert geo.GeopoliticalCollector().default_tags() == [
            "geopolitical",
            "polymarket",
            "risk",
            "conflict",
            "prediction-market",
        ]

    def test_build_content_splits_items_back_by_source(self) -> None:
        items = [
            {"title": "sanctions market", "_geo_source": "polymarket", "volume": 1000},
            {"title": "sanctions article", "_geo_source": "gdelt", "tone": -3.0},
            {"title": "sanctions news", "_geo_source": "google_news", "link": "https://e.com/a"},
        ]
        content = geo.GeopoliticalCollector().build_content(items)
        assert "Polymarket 예측 시장: <strong>1건</strong>" in content
        assert "GDELT 글로벌 뉴스: <strong>1건</strong>" in content
        assert "뉴스 기사: <strong>1건</strong>" in content


class TestBuildFullContent:
    def _content(self, markets=None, gdelt=None, news=None) -> str:
        return geo.GeopoliticalCollector()._build_full_content(markets or [], gdelt or [], news or [])

    def test_all_four_sections_present(self) -> None:
        content = self._content()
        for heading in (
            "## 1. 예측 시장 동향 (Polymarket)",
            "## 2. 주요 지정학 뉴스 (GDELT)",
            "## 3. 투자 관점 지정학 뉴스 (Google News)",
            "## 4. 리스크 분석",
        ):
            assert heading in content, heading

    def test_empty_input_still_renders_snapshot_zeros(self) -> None:
        content = self._content()
        assert "Polymarket 예측 시장: <strong>0건</strong>" in content
        assert "주요 테마: <strong>N/A</strong>" in content

    def test_lead_prefers_google_news_headline(self) -> None:
        news = [{"title": "이란 제재 강화 발표", "link": "https://e.com/a"}]
        gdelt = [{"title": "이란 관련 다른 기사", "tone": -3.0}]
        content = self._content(gdelt=gdelt, news=news)
        assert "이란 제재 강화 발표" in content

    def test_lead_uses_translated_title_when_available(self) -> None:
        news = [{"title": "Sanctions tighten", "title_ko": "제재 강화 소식", "link": "https://e.com/a"}]
        assert "제재 강화 소식" in self._content(news=news)

    def test_lead_falls_back_to_gdelt_then_polymarket(self) -> None:
        gdelt_only = self._content(gdelt=[{"title": "이란 제재 강화 발표", "tone": -3.0}])
        assert "이란 제재 강화 발표" in gdelt_only

        market_only = self._content(markets=[{"title": "이란 제재가 시행될까요", "volume": 1000}])
        assert "이란 제재가 시행될까요" in market_only

    def test_gdelt_noise_title_is_not_used_as_lead(self) -> None:
        content = self._content(gdelt=[{"title": "Time. ai", "tone": -3.0}, {"title": "이란 제재 강화", "tone": -1.0}])
        assert "Time. ai" not in content

    def test_references_section_only_when_links_exist(self) -> None:
        with_links = self._content(news=[{"title": "이란 제재", "link": "https://e.com/a"}])
        assert "참고 링크" in with_links
        assert "참고 링크" not in self._content(news=[{"title": "이란 제재"}])

    def test_entertainment_filter_count_is_recorded(self, monkeypatch) -> None:
        """필터로 걸러낸 건수가 수집기 지표로 기록되는지 — 조용히 사라지면 안 된다."""
        recorded: List[int] = []
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "record_entertainment_filtered", recorded.append)
        collector._build_full_content(
            [
                {"title": "Will NBA finals go to game 7?", "volume": 500_000},
                {"title": "Will new sanctions hit Iran?", "volume": 20_000},
            ],
            [],
            [],
        )
        assert recorded == [1], recorded

    def test_footer_lists_all_three_sources(self) -> None:
        content = self._content()
        for source in ("Polymarket", "GDELT Project", "Google News RSS"):
            assert source in content


def _spy_create_post(collector, monkeypatch) -> Dict[str, Any]:
    """`create_post` 에 넘어간 인자를 캡처한다 (원래 동작은 유지).

    `description_ko` 를 최종 파일에서 확인하면 안 된다 — `post_generator` 가 generic
    description 정책으로 값을 갈아치우기도 하므로, 그 경우 `run()` 이 무엇을 계산했는지
    관측할 수 없다. 여기서 보는 것은 **run() 자신의 출력**이다.
    """
    captured: Dict[str, Any] = {}
    original = collector.create_post

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(collector, "create_post", spy)
    return captured


class TestCollectorRun:
    def _news(self, n: int) -> List[Dict[str, Any]]:
        return [{"title": f"이란 제재 강화 소식 {i}", "link": f"https://e.com/{i}"} for i in range(n)]

    def test_creates_post_when_enough_items(self, isolated_posts, no_network, no_image_writes, monkeypatch) -> None:
        no_network["news"] = self._news(4)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        collector.run()

        written = list(isolated_posts.glob("*.md"))
        assert len(written) == 1, [p.name for p in written]
        body = written[0].read_text(encoding="utf-8")
        assert "## 4. 리스크 분석" in body
        assert "description:" in body
        assert "daily-geopolitical-risk-report" in body

    def test_skips_when_already_posted_today(
        self, isolated_posts, no_network, no_image_writes, monkeypatch, caplog
    ) -> None:
        no_network["news"] = self._news(4)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: True)
        with caplog.at_level("INFO"):
            collector.run()
        assert list(isolated_posts.glob("*.md")) == []
        assert any("already exists for today" in r.message for r in caplog.records)

    def test_skips_when_insufficient_data(
        self, isolated_posts, no_network, no_image_writes, monkeypatch, caplog
    ) -> None:
        """3건 미만이면 포스트를 만들지 않는다 — 빈 리포트 발행 방지."""
        no_network["news"] = self._news(2)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        with caplog.at_level("WARNING"):
            collector.run()
        assert list(isolated_posts.glob("*.md")) == []
        assert any("Insufficient data collected" in r.message for r in caplog.records)

    def test_description_uses_headline_and_counts(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        no_network["news"] = self._news(4)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        captured = _spy_create_post(collector, monkeypatch)
        no_network["markets"] = [{"title": "sanctions market", "volume": 1000}]
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        assert desc.startswith("핵심 이슈: 이란 제재 강화 소식 0."), desc
        assert "총 5건 (1 Polymarket / 0 GDELT / 4 뉴스)" in desc, desc
        assert "주요 테마: 제재/경제압박" in desc, desc
        assert len(desc) <= 160

    def test_description_falls_back_without_readable_headline(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        """제목이 전부 읽을 수 없는 문자라면 헤드라인 없이 건수만 낸다."""
        no_network["gdelt"] = [{"title": "中国宣布新的贸易限制措施", "tone": -1.0} for _ in range(4)]
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        assert desc.startswith("지정학적 리스크 4건 수집"), desc
        assert "핵심 이슈:" not in desc

    def test_long_headline_is_capped_at_seventy_chars(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        """헤드라인은 70자로 잘린다.

        바깥의 `[:160]` 은 사실상 도달하지 않는 안전망이다 — 헤드라인 70자 + 고정 문구 +
        테마 2개를 합쳐도 130자대에 머문다(이 입력에서 실측 132자). 그래서 길이 계약은
        70자 캡으로 단언한다.
        """
        long_title = "이란 제재 강화 동향 " * 20
        no_network["news"] = [{"title": long_title, "link": f"https://e.com/{i}"} for i in range(4)]
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        headline = desc[len("핵심 이슈: ") :].split(". 총 ")[0]
        assert len(headline) == 70, (len(headline), headline)
        assert len(desc) <= 160

    def test_briefing_image_is_spliced_before_section_one(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        no_network["news"] = self._news(4)
        import common.image_generator as ig

        monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *a, **kw: "assets/images/generated/fake-card.png")
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        # `run()` 이 조립한 본문에서 마커와 위치를 본다. 최종 파일에서는 접근성 처리가
        # alt 텍스트(`geopolitical-briefing`)를 한국어 설명으로 갈아치우므로, alt 를
        # 기준으로 단언하면 조립 로직이 아니라 그 후처리를 검사하게 된다.
        content = captured["content"]
        assert "![geopolitical-briefing](" in content
        assert content.index("![geopolitical-briefing](") < content.index("## 1.")

        body = list(isolated_posts.glob("*.md"))[0].read_text(encoding="utf-8")
        assert "fake-card.png" in body, "이미지 참조가 최종 포스트에서 사라졌다"

    def test_image_failure_does_not_abort_the_post(
        self, isolated_posts, no_network, no_image_writes, monkeypatch, caplog
    ) -> None:
        """이미지 생성 실패는 리포트를 막지 않는다 — 본문이 본질이다."""
        no_network["news"] = self._news(4)
        import common.image_generator as ig

        def boom(*_a, **_kw):
            raise RuntimeError("렌더 실패")

        monkeypatch.setattr(ig, "generate_news_briefing_card", boom)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        with caplog.at_level("WARNING"):
            collector.run()
        assert len(list(isolated_posts.glob("*.md"))) == 1
        assert any("briefing card generation failed" in r.message for r in caplog.records)

    def test_post_creation_failure_is_logged(
        self, isolated_posts, no_network, no_image_writes, monkeypatch, caplog
    ) -> None:
        no_network["news"] = self._news(4)
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        monkeypatch.setattr(collector, "create_post", lambda **_kw: "")
        with caplog.at_level("WARNING"):
            collector.run()
        assert any("Failed to create geopolitical risk report post" in r.message for r in caplog.records)


class TestMain:
    def test_main_constructs_and_runs_the_collector(self, monkeypatch) -> None:
        calls: List[str] = []

        class _Fake:
            def run(self) -> None:
                calls.append("run")

        monkeypatch.setattr(geo, "GeopoliticalCollector", _Fake)
        geo.main()
        assert calls == ["run"]


class TestCollectorRunRemainingBranches:
    """`run()` 의 나머지 분기 — 이미지 옵셔널 의존성과 헤드라인 폴백 사슬."""

    def _collector(self, monkeypatch):
        collector = geo.GeopoliticalCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
        return collector

    def test_missing_image_dependency_is_debug_logged_not_fatal(
        self, isolated_posts, no_network, monkeypatch, caplog
    ) -> None:
        """이미지 생성기 임포트 실패는 옵셔널 의존성 부재다 — 리포트는 그대로 나간다."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "common.image_generator":
                raise ImportError("Pillow 없음")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        no_network["news"] = [{"title": f"이란 제재 강화 소식 {i}", "link": f"https://e.com/{i}"} for i in range(4)]

        collector = self._collector(monkeypatch)
        with caplog.at_level("DEBUG"):
            collector.run()

        assert len(list(isolated_posts.glob("*.md"))) == 1, "임포트 실패가 포스트를 막았다"
        assert any("Optional dependency unavailable" in r.message for r in caplog.records)

    def test_description_headline_falls_back_to_gdelt(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        """뉴스가 없으면 GDELT 제목에서 헤드라인을 찾는다 (노이즈 제목은 건너뛴다)."""
        no_network["gdelt"] = [
            {"title": "Time. ai", "tone": -1.0},
            {"title": "이란 제재 강화 발표", "tone": -2.0},
            {"title": "다른 지정학 기사", "tone": -3.0},
        ]
        collector = self._collector(monkeypatch)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        assert desc.startswith("핵심 이슈: 이란 제재 강화 발표."), desc

    def test_description_headline_falls_back_to_polymarket(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        """뉴스·GDELT 가 모두 비면 마지막으로 예측 시장 질문을 쓴다."""
        no_network["markets"] = [
            {"title": "이란 제재가 올해 안에 시행될까요", "volume": 50_000},
            {"title": "다른 시장 질문", "volume": 10_000},
        ]
        no_network["gdelt"] = [
            {"title": "中国宣布新的贸易限制措施", "tone": -1.0},
            {"title": "另一篇报道", "tone": -2.0},
        ]
        collector = self._collector(monkeypatch)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        assert desc.startswith("핵심 이슈: 이란 제재가 올해 안에 시행될까요."), desc

    def test_unreadable_polymarket_question_leaves_no_headline(
        self, isolated_posts, no_network, no_image_writes, monkeypatch
    ) -> None:
        no_network["markets"] = [{"title": "中国市场问题一", "volume": 50_000}]
        no_network["gdelt"] = [{"title": "另一篇报道", "tone": -1.0}, {"title": "第三篇报道", "tone": -2.0}]
        collector = self._collector(monkeypatch)
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        desc = captured["extra_frontmatter"]["description_ko"]
        assert desc.startswith("지정학적 리스크 3건 수집"), desc
