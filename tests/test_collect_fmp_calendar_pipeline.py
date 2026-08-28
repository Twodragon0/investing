"""`scripts/collect_fmp_calendar.py` 의 포매팅·섹션 조립·수집기 파이프라인 테스트.

기존 `tests/test_collect_fmp_calendar.py` 는 포매터 2개와 섹션 2개만 덮는다(27%).
이 파일은 나머지를 덮는다 — 6개 섹션 빌더, 심각도 분류, 뉴스 카드 폴백,
`FmpCalendarCollector` 의 `fetch` / `build_content` / `run`, 그리고 `main()`.

## 이 모듈이 조용히 틀릴 수 있는 지점

이 수집기는 크론이 하루 한 번 돌리고 결과를 아무도 즉시 읽지 않는다. 아래가 깨져도
워크플로우는 성공으로 끝난다:

- **키 이름 불일치** — 표·헤드라인·description 이 **같은 키**를 읽어야 한다.
  실제로 이 버그가 있었다: 표는 `event` 를, 헤드라인과 description 은 `name` 을
  읽었는데 생산자(`common/fmp_api.py`)는 `name` 을 낸 적이 없다. 그래서 본문 표는
  멀쩡한 채 요약만 173개 포스트에서 조용히 비었다. 픽스처는 반드시 `_event()` /
  `_earn()` (= 생산자와 동일한 키 집합)을 쓴다 — 손으로 `name` 을 끼워 넣으면
  그 버그가 다시 정답처럼 보인다.
- **중요도 필터** — `_build_economic_section` 은 High/Medium 만 담는다.
  다른 값이 들어오면 카운트에는 잡히고 표에서는 사라진다.
- **폴백 판정** — `is_news_fallback` 플래그 하나로 캘린더 표 대신 뉴스 카드가 나간다.
  플래그 판정이 뒤집히면 포스트 형태가 통째로 바뀐다.
- **단위 변환** — 국채는 percentage point → basis point(×100), 실적/IPO 는
  B/M 절단이다. 배수를 놓쳐도 숫자는 그럴듯하게 렌더된다.
- **멱등성** — `run()` 은 `is_duplicate_exact` 로만 재실행을 막는다. 그 가드가
  풀리면 같은 날 API 를 다시 때리고 포스트를 덮어쓰려 든다.

## 격리

- 네트워크: FMP fetch 함수 6개를 **모듈 네임스페이스에서** 대체해 HTTP 계층에
  닿기 전에 끊는다 (conftest 의 `HTTPAdapter.send` 차단은 최후 방어선).
- 디스크: `run()` 은 포스트와 브리핑 이미지를 쓴다. `post_generator.POSTS_DIR` 을
  tmp 로 돌리고 이미지 생성은 대역으로 바꾼다. dedup `_state` 는 conftest autouse 가
  이미 tmp 로 보낸다.
- 시각: 날짜를 하드코딩하지 않고 `collector.today` 를 기준으로 기대값을 만든다.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

import pytest

fmp = importlib.import_module("collect_fmp_calendar")


# ---------------------------------------------------------------------------
# _fmt_number / _fmt_change_pct
# ---------------------------------------------------------------------------


class TestFmtNumber:
    def test_thousands_separator_and_decimals(self) -> None:
        assert fmp._fmt_number(1234567.891, 2) == "1,234,567.89"

    def test_zero_decimals_truncates_toward_zero(self) -> None:
        """`int(f)` 는 반올림이 아니라 버림 — 4,999.9 가 5,000 이 되면 안 된다."""
        assert fmp._fmt_number(4999.9, 0) == "4,999"

    def test_three_decimals_are_honoured(self) -> None:
        assert fmp._fmt_number(1.23456, 3) == "1.235"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_missing_value_is_na(self, empty: Any) -> None:
        assert fmp._fmt_number(empty) == "N/A"

    def test_zero_is_formatted_not_treated_as_missing(self) -> None:
        """0 은 유효한 값이다 — `not val` 로 판정했다면 N/A 가 됐을 것."""
        assert fmp._fmt_number(0) == "0.00"

    def test_numeric_string_is_parsed(self) -> None:
        assert fmp._fmt_number("1234.5", 2) == "1,234.50"

    def test_unparseable_value_falls_back_to_str(self) -> None:
        assert fmp._fmt_number("해당없음") == "해당없음"

    def test_non_numeric_type_falls_back_to_str(self) -> None:
        assert fmp._fmt_number(["a"]) == "['a']"


class TestFmtChangePct:
    def test_positive_gets_green_icon_and_explicit_sign(self) -> None:
        assert fmp._fmt_change_pct(1.5) == "🟢 +1.50%"

    def test_negative_gets_red_icon_without_extra_sign(self) -> None:
        assert fmp._fmt_change_pct(-2.25) == "🔴 -2.25%"

    def test_zero_counts_as_positive(self) -> None:
        assert fmp._fmt_change_pct(0) == "🟢 +0.00%"

    def test_percent_suffix_is_stripped_before_parsing(self) -> None:
        assert fmp._fmt_change_pct("3.5%") == "🟢 +3.50%"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_missing_value_is_na(self, empty: Any) -> None:
        assert fmp._fmt_change_pct(empty) == "N/A"

    def test_unparseable_value_falls_back_to_str(self) -> None:
        assert fmp._fmt_change_pct("n/a") == "n/a"


# ---------------------------------------------------------------------------
# _build_index_section
# ---------------------------------------------------------------------------


class TestBuildIndexSection:
    def test_empty_input_yields_empty_string(self) -> None:
        """빈 문자열이어야 `build_content` 가 빈 헤더를 붙이지 않는다."""
        assert fmp._build_index_section([]) == ""

    def test_row_renders_all_quote_fields(self) -> None:
        section = fmp._build_index_section(
            [
                {
                    "symbol": "SPY",
                    "name": "S&P 500 ETF",
                    "price": 512.345,
                    "change": -1.2,
                    "change_pct": -0.23,
                    "day_high": 515.0,
                    "day_low": 510.0,
                }
            ]
        )
        assert "## 📊 주요 시장 지수" in section
        assert "| **SPY** | S&P 500 ETF | 512.35 | -1.20 | 🔴 -0.23% | 515.00 | 510.00 |" in section

    def test_missing_name_falls_back_to_symbol(self) -> None:
        section = fmp._build_index_section([{"symbol": "^VIX"}])
        assert "| **^VIX** | ^VIX |" in section

    def test_missing_numbers_render_as_na(self) -> None:
        section = fmp._build_index_section([{"symbol": "DIA"}])
        assert section.count("N/A") == 5, section

    def test_one_row_per_quote(self) -> None:
        section = fmp._build_index_section([{"symbol": "SPY"}, {"symbol": "QQQ"}])
        assert len([ln for ln in section.splitlines() if ln.startswith("| **")]) == 2


# ---------------------------------------------------------------------------
# _build_sector_section
# ---------------------------------------------------------------------------


class TestBuildSectorSection:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_sector_section([]) == ""

    def test_known_sector_is_translated_to_korean(self) -> None:
        section = fmp._build_sector_section([{"sector": "Technology", "change_pct": 1.1}])
        assert "| 기술 | 🟢 +1.10% |" in section
        assert "Technology" not in section

    def test_unknown_sector_passes_through_untranslated(self) -> None:
        """매핑에 없는 섹터를 버리면 표가 조용히 짧아진다 — 원문 그대로 실어야 한다."""
        section = fmp._build_sector_section([{"sector": "Crypto Mining", "change_pct": -0.5}])
        assert "| Crypto Mining | 🔴 -0.50% |" in section

    def test_every_mapped_sector_has_a_korean_label(self) -> None:
        sectors = [{"sector": s, "change_pct": 0} for s in fmp._SECTOR_KR]
        section = fmp._build_sector_section(sectors)
        for korean in fmp._SECTOR_KR.values():
            assert f"| {korean} |" in section


# ---------------------------------------------------------------------------
# _build_economic_section
# ---------------------------------------------------------------------------


def _event(**over: Any) -> Dict[str, Any]:
    """경제 이벤트 1건 — 키 집합은 `common/fmp_api.py` 생산자와 **동일**하다.

    두 생산 경로(FMP stable, Forex Factory 폴백)가 모두 이 7개 키를 낸다.
    여기에 없는 키(예: `name`)를 테스트에서 손으로 끼워 넣지 말 것 — 생산자가
    내지 않는 키를 소비자가 읽는 버그를 정답으로 고정시킨다.
    """
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
    """실적 1건 — 키 집합은 `fetch_earnings_calendar` 생산자와 **동일**하다.

    회사명 키는 없다. `symbol` 이 유일한 식별자다.
    """
    base = {
        "symbol": "AAPL",
        "date": "2026-08-20",
        "eps_estimated": "1.50",
        "revenue_estimated": "1000000",
        "time": "amc",
    }
    base.update(over)
    return base


class TestBuildEconomicSection:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_economic_section([]) == ""

    def test_dates_are_sorted_within_the_same_impact(self) -> None:
        section = fmp._build_economic_section(
            [_event(event="Later", date="2026-08-25"), _event(event="Earlier", date="2026-08-21")]
        )
        assert section.index("**Earlier**") < section.index("**Later**")

    def test_high_impact_precedes_medium_even_when_dated_later(self) -> None:
        """중요도가 1차 키, 날짜가 2차 키다.

        기존 파일의 순서 테스트는 High 쪽 날짜가 더 이르기도 해서 '날짜만으로
        정렬' 하는 구현도 통과시킨다. 날짜를 반대로 두면 그 구현이 죽는다.
        """
        section = fmp._build_economic_section(
            [
                _event(event="MediumFirstByDate", impact="Medium", date="2026-08-21"),
                _event(event="HighLastByDate", impact="High", date="2026-08-27"),
            ]
        )
        assert section.index("**HighLastByDate**") < section.index("**MediumFirstByDate**")

    def test_impact_emoji_is_prefixed(self) -> None:
        section = fmp._build_economic_section([_event(), _event(event="PMI", impact="Medium")])
        assert "| 🔴 High |" in section
        assert "| 🟡 Medium |" in section

    def test_unknown_impact_is_dropped_entirely(self) -> None:
        """High/Medium 이 아닌 이벤트는 표에서 사라진다 — 카운트와 표가 어긋나는 지점."""
        section = fmp._build_economic_section([_event(event="Housing Starts", impact="Low")])
        assert "Housing Starts" not in section

    def test_blank_forecast_previous_actual_become_dashes(self) -> None:
        section = fmp._build_economic_section([_event(forecast="", previous=None, actual="")])
        row = [ln for ln in section.splitlines() if "**CPI**" in ln][0]
        assert row.endswith("| - | - | - |"), row

    def test_country_is_rendered(self) -> None:
        section = fmp._build_economic_section([_event(country="KR")])
        assert "| KR |" in section


# ---------------------------------------------------------------------------
# _build_treasury_section
# ---------------------------------------------------------------------------


class TestBuildTreasurySection:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_treasury_section([]) == ""

    def test_percentage_points_are_converted_to_basis_points(self) -> None:
        """0.055 %p = 5.5bp. ×100 를 놓치면 0.1bp 로 렌더돼 변화가 없어 보인다."""
        section = fmp._build_treasury_section([{"maturity": "10Y", "rate": 4.2567, "change": 0.055}])
        assert "| 10Y | 4.257 | 🔺 +5.5bp |" in section

    def test_negative_change_uses_down_icon_without_extra_sign(self) -> None:
        section = fmp._build_treasury_section([{"maturity": "2Y", "rate": 3.9, "change": -0.021}])
        assert "🔻 -2.1bp" in section

    def test_zero_change_counts_as_up(self) -> None:
        section = fmp._build_treasury_section([{"maturity": "1M", "rate": 5.0, "change": 0.0}])
        assert "🔺 +0.0bp" in section

    def test_missing_rate_is_na_and_missing_changes_are_dashes(self) -> None:
        section = fmp._build_treasury_section([{"maturity": "30Y"}])
        assert "| 30Y | N/A | - | - |" in section

    def test_change_pct_is_signed_and_rounded(self) -> None:
        section = fmp._build_treasury_section([{"maturity": "5Y", "rate": 4.0, "change_pct": 1.234}])
        assert "| +1.23% |" in section
        section_neg = fmp._build_treasury_section([{"maturity": "5Y", "rate": 4.0, "change_pct": -1.5}])
        assert "| -1.50% |" in section_neg

    def test_rate_zero_is_rendered_not_treated_as_missing(self) -> None:
        section = fmp._build_treasury_section([{"maturity": "1M", "rate": 0.0}])
        assert "| 1M | 0.000 |" in section


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------


class TestClassifySeverity:
    @pytest.mark.parametrize(
        "title",
        [
            "Apple BEAT estimates",
            "Nvidia earnings miss",
            "Stock surges to record high",
            "Analyst downgrade hits shares",
            "Trading halt on the exchange",
            "SEC probes the filing",
            "FDA clears the drug",
            "Company raises $1.2 billion",
            "IPO priced above range",
        ],
    )
    def test_high_keywords(self, title: str) -> None:
        assert fmp._classify_severity(title) == "high"

    @pytest.mark.parametrize("title", ["Company conducts EGM", "Share reallocation notice", "Limited update"])
    def test_low_keywords(self, title: str) -> None:
        assert fmp._classify_severity(title) == "low"

    def test_default_is_medium(self) -> None:
        assert fmp._classify_severity("Quarterly results published today") == "medium"

    def test_matching_is_case_insensitive(self) -> None:
        assert fmp._classify_severity("EARNINGS BEAT") == fmp._classify_severity("earnings beat") == "high"

    def test_high_wins_over_low_when_both_match(self) -> None:
        """우선순위가 뒤집히면 중요한 뉴스가 회색 배지로 묻힌다."""
        assert fmp._classify_severity("Limited partnership conducts record IPO") == "high"

    def test_section_argument_does_not_change_the_result(self) -> None:
        assert fmp._classify_severity("record high", "실적 관련 뉴스") == "high"

    def test_every_severity_has_a_color_and_label(self) -> None:
        assert set(fmp._SEVERITY_COLORS) == set(fmp._SEVERITY_LABELS) == {"high", "medium", "low"}


# ---------------------------------------------------------------------------
# _build_news_cards
# ---------------------------------------------------------------------------


class TestBuildNewsCards:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_news_cards([], "실적 관련 뉴스", "💰") == ""

    def test_heading_and_icon_are_rendered(self) -> None:
        cards = fmp._build_news_cards([{"title": "제목"}], "실적 관련 뉴스", "💰")
        assert cards.startswith("## 💰 실적 관련 뉴스")

    def test_trailing_source_is_split_out_of_the_title(self) -> None:
        cards = fmp._build_news_cards([{"title": "Apple beats estimates - Reuters"}], "뉴스", "💰")
        assert '<span class="fmp-news-source">Reuters</span>' in cards
        assert ">Apple beats estimates<" in cards

    def test_only_the_last_separator_splits_the_source(self) -> None:
        """`rsplit(..., 1)` — 제목 안의 하이픈이 잘리면 안 된다."""
        cards = fmp._build_news_cards([{"title": "A - B - CNBC"}], "뉴스", "💰")
        assert ">A - B<" in cards
        assert ">CNBC<" in cards

    def test_link_renders_an_anchor_with_noopener(self) -> None:
        cards = fmp._build_news_cards([{"title": "제목", "link": "https://example.com/a"}], "뉴스", "💰")
        assert '<a href="https://example.com/a" class="fmp-news-title" target="_blank" rel="noopener">' in cards

    def test_missing_link_renders_a_span_instead_of_an_empty_anchor(self) -> None:
        cards = fmp._build_news_cards([{"title": "제목"}], "뉴스", "💰")
        assert "<a href=" not in cards
        assert '<span class="fmp-news-title">제목</span>' in cards

    def test_date_is_omitted_when_absent(self) -> None:
        with_date = fmp._build_news_cards([{"title": "제목", "date": "2026-08-20"}], "뉴스", "💰")
        without = fmp._build_news_cards([{"title": "제목"}], "뉴스", "💰")
        assert '<span class="fmp-news-date">2026-08-20</span>' in with_date
        assert "fmp-news-date" not in without

    def test_severity_badge_uses_the_classified_color(self) -> None:
        cards = fmp._build_news_cards([{"title": "Nvidia earnings beat"}], "뉴스", "💰")
        assert f'style="background:{fmp._SEVERITY_COLORS["high"]}">HIGH<' in cards

    def test_severity_is_classified_after_the_source_is_stripped(self) -> None:
        """소스명이 키워드를 포함하면 판정이 오염된다 — 분리 후에 분류해야 한다."""
        cards = fmp._build_news_cards([{"title": "Quarterly update published - IPO Daily"}], "뉴스", "💰")
        assert ">MED<" in cards

    def test_item_count_is_capped(self) -> None:
        items = [{"title": f"뉴스 {i}"} for i in range(20)]
        cards = fmp._build_news_cards(items, "뉴스", "💰")
        assert cards.count('<div class="fmp-news-card">') == 15
        assert fmp._build_news_cards(items, "뉴스", "💰", max_items=3).count('<div class="fmp-news-card">') == 3

    def test_list_wrapper_is_closed(self) -> None:
        cards = fmp._build_news_cards([{"title": "제목"}], "뉴스", "💰")
        assert cards.count('<div class="fmp-news-list">') == 1
        assert cards.rstrip().endswith("</div>")


# ---------------------------------------------------------------------------
# _build_ipo_section
# ---------------------------------------------------------------------------


class TestBuildIpoSection:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_ipo_section([]) == ""

    def test_news_fallback_switches_to_cards(self) -> None:
        section = fmp._build_ipo_section([{"is_news_fallback": True, "title": "새 IPO 소식", "date": "2026-08-20"}])
        assert "## 🚀 IPO 관련 뉴스" in section
        assert "IPO 캘린더" not in section

    def test_a_single_flagged_item_flips_the_whole_section(self) -> None:
        """`any()` 판정 — 한 건만 폴백이어도 표 전체가 카드로 바뀐다."""
        items = [{"company": "Acme", "date": "2026-08-20"}, {"is_news_fallback": True, "title": "뉴스"}]
        assert "fmp-news-card" in fmp._build_ipo_section(items)

    def test_calendar_row_renders_all_fields(self) -> None:
        section = fmp._build_ipo_section(
            [
                {
                    "date": "2026-08-20",
                    "company": "Acme Inc",
                    "symbol": "ACME",
                    "exchange": "NASDAQ",
                    "price_range": "$18-$20",
                    "market_value": 2_500_000_000,
                }
            ]
        )
        assert "## 🚀 IPO 캘린더" in section
        assert "| 2026-08-20 | **Acme Inc** | ACME | NASDAQ | $18-$20 | $2.50B |" in section

    @pytest.mark.parametrize(
        ("market_value", "expected"),
        [
            (1_000_000_000, "$1.00B"),
            (999_999_999, "$1,000.00M"),
            (5_500_000, "$5.50M"),
            (999_999, "$999,999"),
            (0, "$0"),
        ],
    )
    def test_market_value_scale_thresholds(self, market_value: Any, expected: str) -> None:
        section = fmp._build_ipo_section([{"company": "A", "market_value": market_value}])
        assert f"| {expected} |" in section

    def test_unparseable_market_value_is_shown_verbatim(self) -> None:
        section = fmp._build_ipo_section([{"company": "A", "market_value": "미정"}])
        assert "| 미정 |" in section

    def test_missing_market_value_becomes_a_dash(self) -> None:
        section = fmp._build_ipo_section([{"company": "A"}])
        assert section.rstrip().endswith("| - |")

    def test_missing_fields_use_dash_defaults(self) -> None:
        section = fmp._build_ipo_section([{"date": "2026-08-20"}])
        assert "| 2026-08-20 | **-** | - | - | - | - |" in section


# ---------------------------------------------------------------------------
# _build_earnings_section
# ---------------------------------------------------------------------------


class TestBuildEarningsSection:
    def test_empty_input_yields_empty_string(self) -> None:
        assert fmp._build_earnings_section([]) == ""

    def test_news_fallback_switches_to_cards(self) -> None:
        section = fmp._build_earnings_section([{"is_news_fallback": True, "title": "실적 소식"}])
        assert "## 💰 실적 관련 뉴스" in section
        assert "실적 발표 일정" not in section

    def test_rows_are_sorted_by_date(self) -> None:
        section = fmp._build_earnings_section(
            [{"symbol": "LATE", "date": "2026-08-25"}, {"symbol": "EARLY", "date": "2026-08-21"}]
        )
        assert section.index("**EARLY**") < section.index("**LATE**")

    @pytest.mark.parametrize(
        ("time_label", "expected"),
        [("bmo", "장전 (BMO)"), ("amc", "장후 (AMC)"), ("14:30", "14:30"), ("", "-")],
    )
    def test_time_labels_are_normalised(self, time_label: str, expected: str) -> None:
        section = fmp._build_earnings_section([{"symbol": "AAPL", "date": "2026-08-20", "time": time_label}])
        assert f"| {expected} |" in section

    @pytest.mark.parametrize(
        ("revenue", "expected"),
        [
            (1_000_000_000, "$1.00B"),
            (999_999_999, "$1,000.00M"),
            (2_500_000, "$2.50M"),
            (750_000, "$750,000"),
            (0, "$0"),
        ],
    )
    def test_revenue_scale_thresholds(self, revenue: Any, expected: str) -> None:
        section = fmp._build_earnings_section([{"symbol": "A", "revenue_estimated": revenue}])
        assert f"| {expected} |" in section

    def test_unparseable_revenue_is_shown_verbatim(self) -> None:
        section = fmp._build_earnings_section([{"symbol": "A", "revenue_estimated": "미공개"}])
        assert "| 미공개 |" in section

    def test_missing_revenue_is_na(self) -> None:
        section = fmp._build_earnings_section([{"symbol": "A"}])
        assert section.rstrip().endswith("| N/A |")

    def test_eps_estimate_is_formatted_to_two_decimals(self) -> None:
        section = fmp._build_earnings_section([{"symbol": "AAPL", "eps_estimated": 1.5}])
        assert "| 1.50 |" in section

    def test_missing_eps_is_na(self) -> None:
        section = fmp._build_earnings_section([{"symbol": "AAPL"}])
        assert "| N/A |" in section


# ---------------------------------------------------------------------------
# FmpCalendarCollector — 격리 fixture
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
    """브리핑 카드 생성을 기본 차단한다 — 켜두면 실제 렌더가 돌고 느려진다.

    카드 인자를 검증하는 테스트는 이 fixture 뒤에 다시 `setattr` 해 덮어쓴다
    (나중 것이 이긴다).
    """
    import common.image_generator as ig

    monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *_a, **_kw: "")


@pytest.fixture
def fake_api(monkeypatch):
    """FMP fetch 함수 6개를 모듈 네임스페이스에서 전부 대체한다.

    반환 dict 의 키를 채우면 그 소스가 데이터를 낸다. `calls` 로 실제 호출 여부와
    인자를 관측한다 — 배선이 끊긴 채 통과하는 false green 을 막는다.
    """
    state: Dict[str, Any] = {
        "indices": {},
        "sectors": [],
        "economic": [],
        "earnings": [],
        "treasury": [],
        "ipo": [],
        "calls": [],
    }
    calls: List[Any] = state["calls"]

    def _index(symbol: str) -> Dict[str, Any]:
        calls.append(("index", symbol))
        return dict(state["indices"].get(symbol) or {})

    def _sectors() -> List[Dict[str, Any]]:
        calls.append(("sectors", None))
        return list(state["sectors"])

    def _economic(days_ahead: int = 30) -> List[Dict[str, Any]]:
        calls.append(("economic", days_ahead))
        return list(state["economic"])

    def _earnings(days_ahead: int = 7) -> List[Dict[str, Any]]:
        calls.append(("earnings", days_ahead))
        return list(state["earnings"])

    def _treasury() -> List[Dict[str, Any]]:
        calls.append(("treasury", None))
        return list(state["treasury"])

    def _ipo(days_ahead: int = 30) -> List[Dict[str, Any]]:
        calls.append(("ipo", days_ahead))
        return list(state["ipo"])

    monkeypatch.setattr(fmp, "fetch_market_index_data", _index)
    monkeypatch.setattr(fmp, "fetch_sector_performance", _sectors)
    monkeypatch.setattr(fmp, "fetch_economic_calendar", _economic)
    monkeypatch.setattr(fmp, "fetch_earnings_calendar", _earnings)
    monkeypatch.setattr(fmp, "fetch_treasury_rates", _treasury)
    monkeypatch.setattr(fmp, "fetch_ipo_calendar", _ipo)
    monkeypatch.setattr(fmp, "_INDEX_SYMBOLS", ["SPY", "QQQ"])
    return state


# ---------------------------------------------------------------------------
# fetch / process
# ---------------------------------------------------------------------------


class TestCollectorFetch:
    def test_index_symbols_default_is_not_empty(self) -> None:
        """설정이 비면 지수 섹션이 통째로 사라진다 — 임포트 시점 기본값을 고정한다."""
        assert fmp._INDEX_SYMBOLS

    def test_all_six_sources_are_queried_with_their_windows(self, fake_api) -> None:
        fmp.FmpCalendarCollector().fetch()
        assert fake_api["calls"] == [
            ("index", "SPY"),
            ("index", "QQQ"),
            ("sectors", None),
            ("economic", 30),
            ("earnings", 7),
            ("treasury", None),
            ("ipo", 30),
        ]

    def test_empty_quote_is_skipped(self, fake_api) -> None:
        """`fetch_market_index_data` 는 실패 시 `{}` 를 낸다 — 빈 행을 실으면 안 된다."""
        fake_api["indices"] = {"SPY": {"symbol": "SPY", "price": 1.0}}
        collector = fmp.FmpCalendarCollector()
        collector.fetch()
        assert [q["symbol"] for q in collector._indices] == ["SPY"]

    def test_items_are_tagged_by_source_and_type(self, fake_api) -> None:
        fake_api["indices"] = {"SPY": {"symbol": "SPY"}}
        fake_api["sectors"] = [{"sector": "Technology"}]
        fake_api["economic"] = [{"event": "CPI"}]
        fake_api["earnings"] = [{"symbol": "AAPL"}]
        fake_api["treasury"] = [{"maturity": "10Y"}]
        fake_api["ipo"] = [{"company": "Acme"}]

        items = fmp.FmpCalendarCollector().fetch()
        assert [(i["source"], i["type"], i["title"]) for i in items] == [
            ("fmp_index", "index", "SPY"),
            ("fmp_sector", "sector", "Technology"),
            ("fmp_economic", "economic", "CPI"),
            ("fmp_earnings", "earnings", "AAPL"),
            ("fmp_treasury", "treasury", "10Y"),
            ("fmp_ipo", "ipo", "Acme"),
        ]

    def test_original_payload_fields_survive_the_merge(self, fake_api) -> None:
        fake_api["treasury"] = [{"maturity": "10Y", "rate": 4.25}]
        (item,) = fmp.FmpCalendarCollector().fetch()
        assert item["rate"] == 4.25

    def test_payload_title_key_overrides_the_tag(self, fake_api) -> None:
        """`{**idx}` 가 뒤에 오므로 페이로드의 `title` 이 이긴다 — 실제 동작을 고정한다."""
        fake_api["indices"] = {"SPY": {"symbol": "SPY", "title": "S&P 500"}}
        (item,) = fmp.FmpCalendarCollector().fetch()
        assert item["title"] == "S&P 500"

    def test_no_data_yields_an_empty_list(self, fake_api) -> None:
        assert fmp.FmpCalendarCollector().fetch() == []

    def test_fetch_stores_each_dataset_on_the_instance(self, fake_api) -> None:
        """`build_content` 가 인자가 아니라 인스턴스 속성을 읽는다 — 배선이 끊기면 빈 포스트."""
        fake_api["sectors"] = [{"sector": "Energy"}]
        fake_api["ipo"] = [{"company": "Acme"}]
        collector = fmp.FmpCalendarCollector()
        collector.fetch()
        assert collector._sectors == [{"sector": "Energy"}]
        assert collector._ipo_data == [{"company": "Acme"}]


class TestCollectorProcess:
    def test_process_is_a_passthrough(self, fake_api) -> None:
        """FMP 데이터는 필터링하지 않는다 — 여기서 걸러지면 카운트가 어긋난다."""
        items = [{"title": "a"}, {"title": "b"}]
        assert fmp.FmpCalendarCollector().process(items) == items


# ---------------------------------------------------------------------------
# build_content
# ---------------------------------------------------------------------------


def _loaded(collector, **datasets: Any):
    """`fetch()` 없이 인스턴스 데이터셋을 채운다 (build_content 는 속성만 읽는다)."""
    collector._indices = datasets.get("indices", [])
    collector._sectors = datasets.get("sectors", [])
    collector._economic_events = datasets.get("economic", [])
    collector._earnings = datasets.get("earnings", [])
    collector._treasury_rates = datasets.get("treasury", [])
    collector._ipo_data = datasets.get("ipo", [])
    return collector


class TestBuildContent:
    def test_headline_reads_the_same_event_key_the_table_reads(self) -> None:
        """헤드라인과 표는 **같은 키**(`event`)를 읽어야 한다.

        회귀 이력: 헤드라인이 `name` 을 읽던 시절, 생산자
        (`common/fmp_api.py`)는 `name` 을 낸 적이 없어 헤드라인이 173개 포스트에서
        조용히 비어 있었다. 표는 `event` 를 읽어 정상이었기 때문에 본문만 보면
        멀쩡했다. 그래서 `_event()` (= 생산자와 동일한 키 집합)만 넣고 단언한다 —
        `name` 을 손으로 끼워 넣으면 그 버그가 다시 정답처럼 보인다.
        """
        c = _loaded(fmp.FmpCalendarCollector(), economic=[_event(event="소비자물가지수")])
        content = c.build_content([])
        assert "**주요 경제 이벤트 소비자물가지수**" in content
        assert "오늘 일정 핵심" in content

    def test_headline_is_empty_when_the_producer_shape_has_no_event_text(self) -> None:
        c = _loaded(fmp.FmpCalendarCollector(), economic=[_event(event="")])
        content = c.build_content([])
        assert "주요 경제 이벤트" not in content.split("\n")[0]
        assert "오늘 일정 핵심" not in content

    def test_headline_falls_back_to_the_top_earning_symbol(self) -> None:
        """실적에는 회사명 키가 없다 — 생산자가 내는 건 `symbol` 뿐이다."""
        c = _loaded(fmp.FmpCalendarCollector(), earnings=[_earn(symbol="AAPL")])
        assert "**대형 실적 AAPL**" in c.build_content([])

    def test_economic_event_wins_over_earnings_for_the_headline(self) -> None:
        c = _loaded(
            fmp.FmpCalendarCollector(),
            economic=[_event(event="CPI")],
            earnings=[_earn(symbol="AAPL")],
        )
        content = c.build_content([])
        assert "**주요 경제 이벤트 CPI**" in content
        assert "대형 실적 AAPL" not in content

    def test_secondary_tag_appears_only_when_both_sources_exist(self) -> None:
        both = _loaded(
            fmp.FmpCalendarCollector(),
            economic=[_event(event="CPI")],
            earnings=[_earn(symbol="AAPL")],
        ).build_content([])
        assert "(실적: AAPL)" in both

        event_only = _loaded(fmp.FmpCalendarCollector(), economic=[_event(event="CPI")]).build_content([])
        assert "실적:" not in event_only

    def test_label_degrades_when_there_is_no_headline(self) -> None:
        c = _loaded(fmp.FmpCalendarCollector())
        content = c.build_content([])
        assert "오늘 일정 —" in content
        assert "오늘 일정 핵심" not in content

    def test_detail_line_reports_every_dataset_count(self) -> None:
        c = _loaded(
            fmp.FmpCalendarCollector(),
            indices=[{}, {}],
            sectors=[{}] * 3,
            economic=[{}] * 4,
            earnings=[{}] * 5,
            treasury=[{}] * 6,
            ipo=[{}] * 7,
        )
        content = c.build_content([])
        assert "시장 지수 2종" in content
        assert "섹터 3개" in content
        assert "국채 금리 6개 만기" in content
        assert "경제 이벤트 4건" in content
        assert "대형주 실적 5건" in content
        assert "IPO 일정 7건" in content

    def test_intro_carries_the_collection_date(self) -> None:
        c = _loaded(fmp.FmpCalendarCollector())
        assert f"**{c.today}**" in c.build_content([])

    def test_stat_grid_only_lists_non_empty_datasets(self) -> None:
        c = _loaded(fmp.FmpCalendarCollector(), indices=[{}], ipo=[{}] * 2)
        content = c.build_content([])
        assert '<div class="stat-label">주요 지수</div>' in content
        assert '<div class="stat-label">IPO 일정</div>' in content
        assert "실적 발표</div>" not in content
        assert "경제 이벤트</div>" not in content

    def test_stat_grid_is_omitted_when_everything_is_empty(self) -> None:
        """섹터·국채만 있으면 stat 항목이 하나도 없다 — 빈 그리드를 내면 안 된다."""
        c = _loaded(fmp.FmpCalendarCollector(), sectors=[{}], treasury=[{}])
        assert '<div class="stat-grid">' not in c.build_content([])

    def test_all_six_sections_are_assembled_in_order(self) -> None:
        c = _loaded(
            fmp.FmpCalendarCollector(),
            indices=[{"symbol": "SPY"}],
            sectors=[{"sector": "Technology"}],
            economic=[_event()],
            earnings=[{"symbol": "AAPL", "date": "2026-08-20"}],
            treasury=[{"maturity": "10Y", "rate": 4.0}],
            ipo=[{"company": "Acme"}],
        )
        content = c.build_content([])
        order = [
            content.index("## 📊 주요 시장 지수"),
            content.index("## 🏦 미국 국채 금리"),
            content.index("## 🏭 섹터 퍼포먼스"),
            content.index("## 📅 주요 경제 이벤트"),
            content.index("## 💰 실적 발표 일정"),
            content.index("## 🚀 IPO 캘린더"),
        ]
        assert order == sorted(order), content

    def test_disclaimer_and_footer_are_appended(self) -> None:
        c = _loaded(fmp.FmpCalendarCollector())
        content = c.build_content([])
        assert "투자 조언이 아닙니다" in content
        assert "<span>소스: Financial Modeling Prep API</span>" in content
        assert f"수집 시각: {c.now.strftime('%Y-%m-%d %H:%M')} KST" in content

    def test_empty_datasets_still_produce_a_post_body(self) -> None:
        content = _loaded(fmp.FmpCalendarCollector()).build_content([])
        # 섹션이 전부 "" 라 구분선만 남는다 — 6개 섹션 뒤 각 1개 (표가 없으므로 "---" 는 구분선뿐).
        assert content.count("---") == 6
        assert "투자 조언이 아닙니다" in content

    def test_fetch_output_flows_into_build_content(self, fake_api) -> None:
        """fetch → build_content 배선 — 속성 이름이 어긋나면 여기서 깨진다."""
        fake_api["indices"] = {"SPY": {"symbol": "SPY", "price": 512.0}}
        fake_api["economic"] = [_event(event="소비자물가지수")]
        collector = fmp.FmpCalendarCollector()
        content = collector.build_content(collector.fetch())
        assert fake_api["calls"], "fetch 가 실제로 호출되지 않았다"
        assert "| **SPY** |" in content
        assert "**주요 경제 이벤트 소비자물가지수**" in content


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _spy_create_post(collector, monkeypatch) -> Dict[str, Any]:
    """`create_post` 에 넘어간 인자를 캡처한다 (원래 동작은 유지).

    최종 파일에서 description 을 읽으면 안 된다 — `post_generator` 가 generic
    description 정책으로 값을 갈아치우기도 하므로, 그 경우 `run()` 이 무엇을
    계산했는지 관측할 수 없다. 여기서 보는 것은 **run() 자신의 출력**이다.
    """
    captured: Dict[str, Any] = {}
    original = collector.create_post

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(collector, "create_post", spy)
    return captured


def _populate(state: Dict[str, Any]) -> None:
    """포스트가 실제로 만들어질 만큼의 데이터를 채운다."""
    state["indices"] = {"SPY": {"symbol": "SPY", "price": 512.0}}
    state["sectors"] = [{"sector": "Technology", "change_pct": 1.0}]
    state["economic"] = [_event(event="소비자물가지수")]
    state["earnings"] = [_earn(symbol="AAPL")]
    state["treasury"] = [{"maturity": "10Y", "rate": 4.25, "change": 0.01}]
    state["ipo"] = [{"company": "Acme Inc", "date": "2026-08-21"}]


class TestCollectorRun:
    def test_creates_one_post_with_expected_metadata(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        written = list(isolated_posts.glob("*.md"))
        assert len(written) == 1, [p.name for p in written]
        assert captured["title"] == f"주요 경제 캘린더 및 실적 일정 ({collector.today})"
        assert captured["source"] == "fmp"
        assert captured["slug"] == "fmp-economic-calendar"
        assert captured["tags"] == [
            "market-analysis",
            "economic-calendar",
            "earnings",
            "treasury",
            "ipo",
            "fmp",
        ]

    def test_permalink_is_dated_and_unique_per_day(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()
        expected = f"/market-analysis/{collector.today.replace('-', '/')}/fmp-economic-calendar/"
        assert captured["extra_frontmatter"]["permalink"] == expected

    def test_description_lists_each_populated_dataset(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()
        desc = captured["extra_frontmatter"]["description"]
        assert desc.startswith("경제 캘린더 6건 수집. ")
        assert "시장 지수 1개" in desc
        assert "실적 발표 1건" in desc
        assert "경제 이벤트 1건" in desc
        assert "IPO 1건" in desc
        assert "주목 이벤트: 소비자물가지수." in desc
        assert captured["extra_frontmatter"]["description_ko"] == desc

    def test_description_falls_back_to_the_earnings_symbol(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """경제 이벤트 텍스트가 비면 실적 `symbol` 로 넘어간다 (20자로 잘림)."""
        fake_api["economic"] = [_event(event="")]
        fake_api["earnings"] = [_earn(symbol="가" * 50)]
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()
        desc = captured["extra_frontmatter"]["description"]
        assert f"주목 실적: {'가' * 20} 등." in desc
        assert "가" * 21 not in desc

    def test_long_event_name_is_truncated_before_it_reaches_the_description(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """이벤트명은 30자로 잘린다.

        길이를 실제로 제한하는 건 이 슬라이스다. 뒤따르는 `[:160]` 캡은 나머지
        구성요소가 짧아 현재 입력 공간에서는 도달하지 않으므로, 길이만 단언하면
        슬라이스를 없애도 통과하는 false green 이 된다.
        """
        _populate(fake_api)
        fake_api["economic"] = [_event(event="아" * 200)]
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()
        desc = captured["extra_frontmatter"]["description"]
        assert f"주목 이벤트: {'아' * 30}." in desc
        assert "아" * 31 not in desc
        assert len(desc) <= 160

    def test_briefing_card_gets_only_non_empty_themes_capped_at_four(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        _populate(fake_api)
        calls: Dict[str, Any] = {}

        import common.image_generator as ig

        def fake_card(themes, date, **kwargs):
            calls["themes"] = themes
            calls["date"] = date
            calls.update(kwargs)
            # 실제로 쓰지 않는 반환값 — run() 은 basename 만 떼어 쓴다.
            return str(isolated_posts / "news-briefing-calendar.png")

        monkeypatch.setattr(ig, "generate_news_briefing_card", fake_card)

        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()

        assert [t["name"] for t in calls["themes"]] == [
            "주요 시장 지수",
            "미국 국채 금리",
            "섹터 퍼포먼스",
            "주요 경제 이벤트",
        ], "빈 데이터셋이 카드에 실렸거나 4개 상한이 깨졌다"
        assert calls["date"] == collector.today
        assert calls["category"] == "Economic Calendar"
        assert calls["total_count"] == 6
        assert calls["filename"] == f"news-briefing-calendar-{collector.today}.png"
        assert captured["image"] == "/assets/images/generated/news-briefing-calendar.png"

    def test_empty_card_result_leaves_the_image_field_blank(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        collector.run()
        assert captured["image"] == ""

    def test_missing_image_dependency_is_debug_logged_not_fatal(
        self, fake_api, isolated_posts, monkeypatch, caplog
    ) -> None:
        """옵셔널 의존성 부재로 포스트 자체가 사라지면 안 된다."""
        monkeypatch.setitem(__import__("sys").modules, "common.image_generator", None)
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        with caplog.at_level("DEBUG"):
            collector.run()
        assert captured["image"] == ""
        assert any("Optional dependency unavailable" in r.message for r in caplog.records)
        assert len(list(isolated_posts.glob("*.md"))) == 1

    def test_card_failure_is_warned_and_the_post_still_ships(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch, caplog
    ) -> None:
        import common.image_generator as ig

        def boom(*_a, **_kw):
            raise RuntimeError("렌더 실패")

        monkeypatch.setattr(ig, "generate_news_briefing_card", boom)
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        with caplog.at_level("WARNING"):
            collector.run()
        assert any("briefing image failed" in r.message for r in caplog.records)
        assert captured["image"] == ""
        assert len(list(isolated_posts.glob("*.md"))) == 1

    def test_duplicate_title_skips_fetching_entirely(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch, caplog
    ) -> None:
        """중복 가드는 API 호출 *전에* 걸려야 한다 — 뒤에 있으면 쿼터를 그냥 태운다."""
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: True)
        with caplog.at_level("INFO"):
            collector.run()
        assert fake_api["calls"] == []
        assert list(isolated_posts.glob("*.md")) == []
        assert any("already exists for today, skipping" in r.message for r in caplog.records)

    def test_rerunning_the_same_collector_is_idempotent(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch
    ) -> None:
        """1회차가 `mark_seen` 하므로 2회차는 API 도 안 때리고 포스트도 안 만든다."""
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        collector.run()
        first_calls = len(fake_api["calls"])
        assert first_calls > 0

        collector.run()
        assert len(fake_api["calls"]) == first_calls, "2회차에서 API 를 다시 호출했다"
        assert len(list(isolated_posts.glob("*.md"))) == 1

    def test_no_data_warns_and_creates_nothing(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch, caplog
    ) -> None:
        collector = fmp.FmpCalendarCollector()
        captured = _spy_create_post(collector, monkeypatch)
        with caplog.at_level("WARNING"):
            collector.run()
        assert captured == {}, "데이터가 없는데 포스트를 만들려 했다"
        assert list(isolated_posts.glob("*.md")) == []
        assert any("FMP_API_KEY may not be set" in r.message for r in caplog.records)

    def test_skipped_creation_does_not_mark_the_title_seen(
        self, fake_api, isolated_posts, no_image_writes, monkeypatch, caplog
    ) -> None:
        """`create_post` 가 빈 값을 내면 다음 실행이 재시도할 수 있어야 한다."""
        _populate(fake_api)
        collector = fmp.FmpCalendarCollector()
        monkeypatch.setattr(collector, "create_post", lambda **_kw: "")
        marked: Dict[str, Any] = {}
        monkeypatch.setattr(collector, "mark_seen", lambda *a: marked.setdefault("called", a))
        with caplog.at_level("INFO"):
            collector.run()
        assert marked == {}
        assert not any("Created FMP calendar post" in r.message for r in caplog.records)

    def test_state_is_saved_on_every_exit_path(self, fake_api, isolated_posts, no_image_writes, monkeypatch) -> None:
        """중복 스킵·데이터 없음·정상 생성 셋 다 상태를 저장해야 프루닝이 돈다."""
        saves: list[str] = []

        for label, prepare in (
            ("dup", lambda c: monkeypatch.setattr(c, "is_duplicate_exact", lambda *_a, **_kw: True)),
            ("empty", lambda c: None),
            ("created", lambda c: _populate(fake_api)),
        ):
            collector = fmp.FmpCalendarCollector()
            prepare(collector)
            monkeypatch.setattr(collector, "save_state", lambda label=label: saves.append(label))
            collector.run()
        assert saves == ["dup", "empty", "created"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_constructs_and_runs_the_collector(self, monkeypatch) -> None:
        calls: list[str] = []

        class _Fake:
            def run(self) -> None:
                calls.append("run")

        monkeypatch.setattr(fmp, "FmpCalendarCollector", _Fake)
        fmp.main()
        assert calls == ["run"]


# ---------------------------------------------------------------------------
# 생산자/소비자 키 계약
#
# 이 절만 `common/fmp_api.py`(생산자)를 직접 호출한다. 나머지 테스트는 위의
# `_event()` / `_earn()` 픽스처를 쓰는데, 그 픽스처가 생산자와 어긋나면 소비자
# 버그를 정답으로 고정시킬 수 있다 — 실제로 그렇게 173개 포스트의 헤드라인이
# 조용히 비었다. 아래 테스트가 픽스처를 생산자에 **묶어 둔다**.
# ---------------------------------------------------------------------------


_fmp_api = importlib.import_module("common.fmp_api")


@pytest.fixture
def stub_fmp_http(monkeypatch):
    """`request_with_retry` 를 대체해 임의 JSON 을 생산자에 흘려 넣는다."""
    box: Dict[str, Any] = {"payload": [], "calls": []}

    class _Resp:
        def json(self) -> Any:
            return box["payload"]

    def _fake(url: str, **kwargs: Any) -> _Resp:
        box["calls"].append(url)
        return _Resp()

    monkeypatch.setattr(_fmp_api, "request_with_retry", _fake)
    return box


class TestProducerConsumerKeyContract:
    def test_economic_producer_emits_exactly_the_fixture_keys(self, stub_fmp_http, monkeypatch) -> None:
        monkeypatch.setattr(_fmp_api, "get_env", lambda *_a, **_kw: "dummy-key")
        stub_fmp_http["payload"] = [
            {
                "event": "CPI",
                "country": "US",
                "date": "2026-08-20",
                "impact": "High",
                "estimate": "3.0%",
                "previous": "2.9%",
                "actual": "3.1%",
            }
        ]
        (produced,) = _fmp_api.fetch_economic_calendar(days_ahead=30)
        assert stub_fmp_http["calls"], "생산자가 호출되지 않았다 — 배선이 끊겼다"
        assert set(produced) == set(_event()), (
            "생산자 키 집합이 `_event()` 픽스처와 다르다. 픽스처를 맞추고, "
            "소비자(collect_fmp_calendar)가 읽는 키도 함께 확인할 것."
        )

    def test_forex_factory_fallback_emits_the_same_keys(self, stub_fmp_http, monkeypatch) -> None:
        """폴백 경로도 같은 계약을 지켜야 한다 — 한쪽만 맞으면 키가 소스마다 갈린다."""
        monkeypatch.setattr(_fmp_api, "get_env", lambda *_a, **_kw: "")
        stub_fmp_http["payload"] = [
            {
                "title": "Non-Farm Payrolls",
                "country": "USD",
                "date": "2026-08-20",
                "impact": "High",
                "forecast": "180K",
                "previous": "175K",
            }
        ]
        (produced,) = _fmp_api.fetch_economic_calendar(days_ahead=30)
        assert set(produced) == set(_event())
        assert produced["event"] == "Non-Farm Payrolls", "폴백은 `title` 을 `event` 로 옮겨야 한다"

    def test_earnings_producer_emits_exactly_the_fixture_keys(self, stub_fmp_http, monkeypatch) -> None:
        monkeypatch.setattr(_fmp_api, "get_env", lambda *_a, **_kw: "dummy-key")
        stub_fmp_http["payload"] = [
            {
                "symbol": "AAPL",
                "date": "2026-08-20",
                "epsEstimated": 1.5,
                "revenueEstimated": 1e6,
                "time": "amc",
                # 시총 20억 달러 미만은 생산자가 걸러낸다 — 넘겨야 항목이 남는다.
                "marketCap": 3_000_000_000_000,
            }
        ]
        (produced,) = _fmp_api.fetch_earnings_calendar(days_ahead=7)
        assert set(produced) == set(_earn())

    def test_producers_never_emit_a_name_key(self, stub_fmp_http, monkeypatch) -> None:
        """이 버그의 핵심 단언.

        소비자가 `name` 을 읽어도 표는 `event` 를 읽으므로 본문은 멀쩡하다.
        그래서 "요약만 빈" 상태가 5개월 넘게 안 보였다. 생산자가 `name` 을
        내지 않는다는 사실 자체를 못 박아 둔다.
        """
        monkeypatch.setattr(_fmp_api, "get_env", lambda *_a, **_kw: "dummy-key")
        stub_fmp_http["payload"] = [
            {"event": "CPI", "country": "US", "date": "2026-08-20", "impact": "High", "name": "소비자물가지수"}
        ]
        (produced,) = _fmp_api.fetch_economic_calendar(days_ahead=30)
        assert "name" not in produced, "생산자가 `name` 을 내기 시작했다면 소비자 쪽도 재검토할 것"

    def test_consumer_summary_is_populated_from_producer_shaped_data(self) -> None:
        """계약의 반대편: 생산자 모양 그대로 넣으면 요약이 채워져야 한다.

        표만 보는 단언으로는 이 회귀를 못 잡는다 — 버그가 있을 때도 표는 정상이었다.
        """
        collector = _loaded(
            fmp.FmpCalendarCollector(),
            economic=[_event(event="소비자물가지수")],
            earnings=[_earn(symbol="AAPL")],
        )
        content = collector.build_content([])
        assert "| **소비자물가지수** |" in content, "표가 비었다"
        assert "**주요 경제 이벤트 소비자물가지수**" in content, "표는 찼는데 헤드라인이 비었다 — 그 버그다"
        assert "(실적: AAPL)" in content
