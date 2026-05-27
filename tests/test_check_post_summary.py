"""Unit tests for scripts/check_post_summary.py.

Covers the regression classifier (``_classify``) and the site-walking
loop (``scan_site``). A ``filler_excerpts`` fixture pins 65 realistic
filler-vs-content excerpts so a pattern weakening (e.g. a positive-signal
regex regression) shows up immediately rather than next Monday's CI run.

Each tuple in ``FILLER_FIXTURES`` is ``(label, body, expected_issue_or_None)``
so a failing case names itself in pytest output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_post_summary import (
    SummaryFinding,
    _classify,
    _extract_post_date,
    scan_site,
)

# ---------------------------------------------------------------------------
# _classify — exhaustive issue-label coverage
# ---------------------------------------------------------------------------


class TestClassifyEmpty:
    def test_empty_string(self) -> None:
        assert _classify("") == "empty"

    def test_whitespace_only(self) -> None:
        assert _classify("   \n\t  ") == "empty"


class TestClassifyHtmlLeak:
    def test_paragraph_tag(self) -> None:
        assert _classify("<p>이건 leak입니다</p>") == "html-leak"

    def test_anchor_tag(self) -> None:
        body = "BTC 가격이 <a href='/post'>3% 상승</a>했습니다."
        assert _classify(body) == "html-leak"

    def test_self_closing_tag(self) -> None:
        assert _classify("내용입니다.<br/>줄바꿈 leak.") == "html-leak"


class TestClassifyPureCount:
    def test_simple_count(self) -> None:
        # 9 chars — falls into too-short before pure-count check
        assert _classify("47건 수집.") == "too-short"

    def test_count_above_length_threshold(self) -> None:
        # Pure-count regex now exercised on length >= 30 input
        assert _classify("1, 234, 567, 890, 100, 200 종") == "pure-count"

    def test_count_with_other_content_not_flagged(self) -> None:
        # Not pure-count: contains alphabetic + numeric + unit
        body = r"BTC 47건 수집했고 평균 가격은 \$75,000입니다."
        assert _classify(body) is None


class TestClassifyTooShort:
    def test_short_korean(self) -> None:
        assert _classify("짧은 요약.") == "too-short"

    def test_just_under_threshold(self) -> None:
        # 29 chars → still too-short
        body = "x" * 29
        assert _classify(body) == "too-short"


class TestClassifyNoSignal:
    """Filler-only bodies that pass length/HTML/count checks but carry zero
    positive signal — the regression Task 3 is meant to lock down."""

    def test_pure_filler_korean(self) -> None:
        body = "최근 시장 동향과 주요 뉴스를 정리한 보고서입니다 자세한 내용은 본문에서."
        assert _classify(body) == "no-signal"

    def test_filler_without_numbers_or_proper_nouns(self) -> None:
        body = "오늘의 시장 흐름과 투자 환경 변화를 종합적으로 살펴본 분석 보고서를 제공합니다."
        assert _classify(body) == "no-signal"


class TestClassifyHealthy:
    """Real production excerpts (sampled from 2026-05 posts) must pass."""

    @pytest.mark.parametrize(
        "body",
        [
            # Currency + percent + ticker
            "BTC $75,788 (24h -0.9%). 공포·탐욕 지수: 28/100 (Fear), BTC 도미넌스 58.0%.",
            # Acronyms + numbers with units
            "BTC 해시레이트 1.07 ZH/s, 일일 트랜잭션 702,788건. ETH 가스 0.15 Gwei",
            # Headline lead-in + proper nouns
            "크립토 뉴스 114건 수집. 주요 출처: Binance, Google News KR, Decrypt.",
            # 4-digit year + currency
            "2026-05-24 DeFi 생태계 TVL: 상위 20개 프로토콜 $131 - Investing Dragon.",
            # KOSPI/KOSDAQ + percent
            "2026-05-24 주식 시장: KOSPI 7,847.71(+0.41%), KOSDAQ 1,161.13(+4.99%).",
            # Korean unit (조)
            "BTC 시가총액은 1조 4천억 달러를 돌파했고 일일 거래량은 850억 달러 수준입니다.",
        ],
    )
    def test_healthy_excerpts_pass(self, body: str) -> None:
        assert _classify(body) is None


# ---------------------------------------------------------------------------
# FILLER_FIXTURES — 65-case regression pin
# ---------------------------------------------------------------------------
# Format: (case_id, body, expected_issue_or_None)
# Buckets:
#   - empty (3) | html-leak (5) | pure-count (3) | too-short (5)
#   - no-signal filler (20) | healthy with positive signal (29)
# Total: 65 cases.

FILLER_FIXTURES: list[tuple[str, str, str | None]] = [
    # --- empty (3) -----------------------------------------------------------
    ("empty-blank", "", "empty"),
    ("empty-spaces", "          ", "empty"),
    ("empty-tabs-newlines", "\t\n  \n\t", "empty"),
    # --- html-leak (5) -------------------------------------------------------
    ("html-p", "<p>본문 leak</p>", "html-leak"),
    ("html-anchor", "BTC는 <a href='x'>3% 상승</a>했습니다.", "html-leak"),
    ("html-strong", "<strong>주요 뉴스</strong> 정리 보고서입니다.", "html-leak"),
    ("html-br", "내용 첫 줄.<br/>두 번째 줄도 있습니다.", "html-leak"),
    ("html-figure", "<figure>이미지 캡션</figure>이 leak되었습니다.", "html-leak"),
    # --- pure-count (3, length >= 30) ----------------------------------------
    ("pure-count-multi", "1, 234, 567, 890, 100, 200, 300 건", "pure-count"),
    ("pure-count-large", "1,234,567,890,100,200,300,400 개", "pure-count"),
    ("pure-count-types", "100, 200, 300, 400, 500, 600 종", "pure-count"),
    # --- too-short (5) -------------------------------------------------------
    ("short-1", "짧음.", "too-short"),
    ("short-2", "오늘의 뉴스.", "too-short"),
    ("short-3", "x" * 29, "too-short"),
    ("short-4", "47건 수집.", "too-short"),
    ("short-5", "정리 완료.", "too-short"),
    # --- no-signal filler (20) ----------------------------------------------
    # All length >= 30 with no numbers, no acronyms, no headline lead-in.
    ("filler-01", "최근 시장 동향과 주요 뉴스를 정리한 보고서입니다 자세한 내용은 본문을 참고하세요.", "no-signal"),
    ("filler-02", "오늘의 시장 흐름과 투자 환경 변화를 종합적으로 살펴본 분석 보고서를 제공합니다.", "no-signal"),
    ("filler-03", "암호화폐 관련 주요 동향을 모아 정리했습니다 자세한 분석은 본문에서 확인하세요.", "no-signal"),
    ("filler-04", "글로벌 매크로 환경 변화를 살펴본 종합 분석 자료입니다 본문에서 자세히 확인하세요.", "no-signal"),
    ("filler-05", "주요 자산군의 흐름과 시장 심리를 살펴본 종합 보고서를 제공해 드립니다 본문에서.", "no-signal"),
    ("filler-06", "투자 환경의 변화와 시장 참여자들의 반응을 모아 살펴본 분석 자료를 제공합니다.", "no-signal"),
    ("filler-07", "오늘 시장에서 주목해야 할 흐름과 변화를 종합적으로 살펴본 분석 자료입니다.", "no-signal"),
    ("filler-08", "최근 시장에서 주목받는 흐름과 동향을 종합적으로 살펴본 일일 분석 자료를 제공합니다.", "no-signal"),
    ("filler-09", "글로벌 시장의 주요 흐름과 변화를 살펴본 종합 분석 보고서를 본문에서 확인하세요.", "no-signal"),
    ("filler-10", "오늘의 시장에서 부각되는 흐름과 분위기를 모아 정리해 분석 자료를 제공합니다.", "no-signal"),
    ("filler-11", "최근의 시장 변화와 투자자들의 관심사를 살펴본 종합적인 분석 자료를 제공합니다.", "no-signal"),
    ("filler-12", "주요 흐름과 시장 심리를 종합적으로 살펴본 일일 분석 자료를 본문에서 확인하세요.", "no-signal"),
    ("filler-13", "오늘 부각된 주제들을 모아 살펴본 종합 정리 자료를 본문에서 확인하시기 바랍니다.", "no-signal"),
    ("filler-14", "시장 참여자들의 관심과 흐름을 종합적으로 살펴본 자료를 본문에서 자세히 확인하세요.", "no-signal"),
    ("filler-15", "최근 부각되는 흐름과 시장 분위기를 모아 살펴본 분석 자료를 제공해 드립니다.", "no-signal"),
    ("filler-16", "오늘의 주요 흐름과 시장 분위기를 종합적으로 살펴본 정리 자료를 제공합니다.", "no-signal"),
    ("filler-17", "글로벌 흐름과 시장 분위기 변화를 살펴본 종합 분석 자료를 본문에서 확인하세요.", "no-signal"),
    ("filler-18", "오늘의 시장에서 부각되는 흐름과 시장 심리를 살펴본 종합 분석을 제공합니다.", "no-signal"),
    ("filler-19", "최근의 흐름과 시장 참여자들의 관심을 살펴본 종합 정리 자료를 제공해 드립니다.", "no-signal"),
    ("filler-20", "시장 흐름과 분위기 변화를 종합적으로 살펴본 정리 자료를 본문에서 확인해 보세요.", "no-signal"),
    # --- healthy with positive signal (29) -----------------------------------
    # Numbers + units
    ("ok-pct", "오늘 BTC 가격은 5% 상승했고 거래량도 12% 늘었습니다 시장 심리도 호전.", None),
    ("ok-currency-usd", "이더리움은 $3,200 수준에서 거래 중이며 일일 변동폭은 약 2% 입니다.", None),
    ("ok-currency-won", "코스피는 2,800원 부근에서 횡보 중이며 외국인 순매수가 이어지고 있습니다.", None),
    ("ok-eok", "오늘 외국인은 5,000억 원을 순매수했고 기관은 2,000억 원 순매도였습니다.", None),
    ("ok-jo", "비트코인 시가총액은 1조 5천억 달러를 돌파했고 일일 거래량은 850억입니다.", None),
    ("ok-decimal", "BTC 도미넌스는 58.0% 수준이고 ETH 비중은 18.5% 입니다 알트 약세 지속.", None),
    ("ok-thousand-sep", "코스닥은 1,234.56 포인트에서 마감했고 외국인 순매도는 1,500억 원입니다.", None),
    # Acronyms / tickers
    ("ok-btc", "BTC 가격은 안정적이며 도미넌스도 일정 수준을 유지하고 있는 상황입니다 시장.", None),
    ("ok-eth-btc", "ETH/BTC 비율이 0.05 부근에서 반등 시도하며 알트 시즌 기대감이 살아납니다.", None),
    ("ok-sec-etf", "SEC는 ETF 승인 심사를 진행 중이며 시장 참여자들이 결과를 주시하고 있는 상황.", None),
    ("ok-kospi", "KOSPI 지수가 강세를 보이며 외국인 순매수가 이어지는 모습을 보였습니다.", None),
    ("ok-nasdaq", "NASDAQ 종합지수가 사상 최고치 부근에서 거래되고 있으며 기술주 강세입니다.", None),
    # Headline lead-in
    ("ok-headline", "오늘의 헤드라인: 비트코인 신고가 돌파와 알트 시즌 기대감이 동시에 부각됩니다.", None),
    ("ok-themes", "주요 테마: 매크로/금리, 규제/정책, AI/기술 분야가 시장을 주도하고 있습니다.", None),
    ("ok-sources", "주요 출처: 다양한 매체에서 보도된 시장 흐름을 종합적으로 살펴본 자료입니다.", None),
    ("ok-issues", "주요 이슈: 시장 변동성 확대와 투자 심리 위축이 동시에 관찰되는 모습입니다.", None),
    # Korean date / year
    ("ok-year", "2026년 1분기 실적 발표가 이어지며 시장 참여자들이 가이던스를 주목하는 상황.", None),
    ("ok-date", "2026-05-24 기준 시장 분위기 변화와 흐름을 종합 분석한 자료를 제공합니다.", None),
    # Quoted phrase
    ("ok-quoted", '시장은 "변동성 확대"를 우려하는 분위기로 투자자들의 관심이 집중되는 상황입니다.', None),
    # Title-case proper noun pairs
    ("ok-proper-noun", "Cathie Wood의 Ark Invest가 시장 전망을 공유하며 투자 환경의 변화를 분석.", None),
    ("ok-proper-noun-2", "Federal Reserve가 금리 정책 방향성을 시사하며 시장 심리에 영향을 주고 있습니다.", None),
    # Currency variants
    ("ok-eur", "유럽 자산은 €1,200 수준에서 거래되며 변동성 확대 조짐이 관찰되고 있는 상황.", None),
    ("ok-jpy", "엔화 자산은 ¥150 부근에서 거래되며 일본은행 정책 방향성이 주목받고 있습니다.", None),
    ("ok-krw", "원화는 ₩1,300 부근에서 거래되며 환율 변동성이 시장에 영향을 주고 있는 상황.", None),
    # Percent only
    ("ok-pct-only", "오늘 시장은 평균적으로 3% 상승 마감했고 거래량도 평소 대비 1.5배 늘었습니다.", None),
    # Number with 만/조
    ("ok-man", "외국인 매수세는 5만 계약 수준으로 평소 대비 두 배 이상 늘어난 상황을 보입니다.", None),
    # SEC/IPO/CPI/PCE acronyms
    ("ok-cpi", "CPI 발표를 앞두고 시장 변동성이 확대되며 투자자들의 경계감이 높아지는 흐름.", None),
    ("ok-pce", "PCE 지표는 인플레이션 둔화 추세를 시사하며 연준 정책 기대감에 영향을 줍니다.", None),
    ("ok-ipo", "IPO 시장은 활기를 되찾으며 신규 상장 종목들의 거래량이 증가하는 모습입니다.", None),
    # Broadened units (recovered from 30-day _site/ analysis, 2026-05-26): 건/종/개/월/일
    ("ok-count-gun", "비트코인 (49건): 비트코인 심리 지표가 변동 중이며 지지·저항선 근접 여부를 점검하세요.", None),
    ("ok-count-jong", "총 100종의 자산을 다루며 신규 상장 종목과 기존 종목 흐름을 종합 분석합니다.", None),
    ("ok-count-gae", "오늘 50개의 코인을 추적하며 거래량과 변동성을 종합적으로 살펴본 자료입니다.", None),
    ("ok-date-korean", "이번 주 (05월 04일 05월 11일) 투자 시장의 주요 동향과 핵심 이슈를 종합 분석합니다.", None),
    ("ok-date-month", "10월 12일부터 시작된 흐름이 이번 주에도 지속되며 시장 참여자들이 주목하는 상황입니다.", None),
]


# Sanity: confirm fixture set has exactly 70 cases (locked in by spec).
def test_filler_fixtures_size_is_70() -> None:
    assert len(FILLER_FIXTURES) == 70, f"FILLER_FIXTURES drifted from spec (expected 70, got {len(FILLER_FIXTURES)})"


@pytest.mark.parametrize(
    ("case_id", "body", "expected"),
    FILLER_FIXTURES,
    ids=[c[0] for c in FILLER_FIXTURES],
)
def test_filler_fixture(case_id: str, body: str, expected: str | None) -> None:
    """Pin classifier output against the 65 representative cases."""
    assert _classify(body) == expected


# ---------------------------------------------------------------------------
# scan_site — end-to-end against a temp _site/ directory
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_site(tmp_path, monkeypatch):
    """Build a minimal _site/ tree and point scan_site at it."""
    import scripts.check_post_summary as cps

    site = tmp_path / "_site"
    site.mkdir()
    monkeypatch.setattr(cps, "_SITE_DIR", site)
    return site


def _write_post(site: Path, url_path: str, summary_body: str) -> Path:
    post_dir = site / url_path.strip("/")
    post_dir.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html>
<body>
<article>
<section class="post-summary"><div class="summary-label">요약</div><p>{summary_body}</p></section>
<p>본문 내용</p>
</article>
</body>
</html>"""
    target = post_dir / "index.html"
    target.write_text(html, encoding="utf-8")
    return target


def test_scan_site_flags_no_signal_post(temp_site, monkeypatch) -> None:
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y/%m/%d")
    _write_post(
        temp_site,
        f"/crypto-news/{today}/filler-post/",
        "최근 시장 흐름과 주요 변화를 종합적으로 살펴본 정리 자료를 제공해 드립니다 본문에서.",
    )
    findings = scan_site(days=7)
    assert len(findings) == 1
    assert findings[0].issue == "no-signal"


def test_scan_site_skips_healthy_post(temp_site) -> None:
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y/%m/%d")
    _write_post(
        temp_site,
        f"/crypto-news/{today}/healthy-post/",
        "BTC $75,788 (24h -0.9%). 공포·탐욕 지수: 28/100 (Fear). 시장 분위기 호전.",
    )
    assert scan_site(days=7) == []


def test_scan_site_respects_cutoff(temp_site) -> None:
    """A post older than --days is skipped even if it has issues."""
    _write_post(
        temp_site,
        "/crypto-news/2020/01/01/old-bad-post/",
        "",  # empty body would normally fail
    )
    assert scan_site(days=7) == []


def test_scan_site_missing_summary_section_is_ignored(temp_site) -> None:
    """Pages without a .post-summary section (e.g. category landing) are skipped."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y/%m/%d")
    post_dir = temp_site / f"crypto-news/{today}/no-summary/"
    post_dir.mkdir(parents=True)
    (post_dir / "index.html").write_text("<html><body><p>no section here</p></body></html>", encoding="utf-8")
    assert scan_site(days=7) == []


def test_extract_post_date_parses_url() -> None:
    """_extract_post_date pulls YYYY-MM-DD from the rendered URL."""
    import scripts.check_post_summary as cps

    # The function compares against _SITE_DIR; build a path relative to it.
    p = cps._SITE_DIR / "stock-news" / "2026" / "05" / "24" / "post" / "index.html"
    assert _extract_post_date(p) == "2026-05-24"


def test_summary_finding_dataclass_fields() -> None:
    f = SummaryFinding(
        path=Path("/x/y/index.html"),
        post_date="2026-05-24",
        body="abc",
        issue="too-short",
    )
    assert f.issue == "too-short"
    assert f.post_date == "2026-05-24"
