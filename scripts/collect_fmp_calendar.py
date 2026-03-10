#!/usr/bin/env python3
"""Collect economic calendar and earnings data from FMP API."""

import os
import sys
import time
from datetime import UTC, datetime
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import setup_logging
from common.dedup import DedupEngine
from common.fmp_api import (
    fetch_earnings_calendar,
    fetch_economic_calendar,
    fetch_ipo_calendar,
    fetch_market_index_data,
    fetch_sector_performance,
    fetch_treasury_rates,
)
from common.post_generator import PostGenerator

logger = setup_logging("collect_fmp_calendar")

_INDEX_SYMBOLS = ["SPY", "QQQ", "DIA", "^VIX"]

_IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟡",
}

_SECTOR_KR = {
    "Technology": "기술",
    "Healthcare": "헬스케어",
    "Financial Services": "금융",
    "Consumer Cyclical": "경기소비재",
    "Communication Services": "통신서비스",
    "Industrials": "산업재",
    "Consumer Defensive": "필수소비재",
    "Energy": "에너지",
    "Real Estate": "부동산",
    "Basic Materials": "소재",
    "Utilities": "유틸리티",
}


def _fmt_number(val: Any, decimals: int = 2) -> str:
    """Format a number with commas and fixed decimals, or return 'N/A'."""
    if val is None or val == "":
        return "N/A"
    try:
        f = float(val)
        if decimals == 0:
            return f"{int(f):,}"
        return f"{f:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_change_pct(val: Any) -> str:
    """Format change percentage with sign and color emoji."""
    if val is None or val == "":
        return "N/A"
    try:
        f = float(str(val).replace("%", ""))
        sign = "+" if f >= 0 else ""
        icon = "🟢" if f >= 0 else "🔴"
        return f"{icon} {sign}{f:.2f}%"
    except (ValueError, TypeError):
        return str(val)


def _build_index_section(indices: List[Dict[str, Any]]) -> str:
    """Build markdown table for market index quotes."""
    if not indices:
        return ""

    lines = [
        "## 📊 주요 시장 지수\n",
        "| 심볼 | 이름 | 현재가 | 변동 | 변동률 | 고가 | 저가 |",
        "|------|------|--------|------|--------|------|------|",
    ]
    for q in indices:
        symbol = q.get("symbol", "")
        name = q.get("name", symbol)
        price = _fmt_number(q.get("price"), 2)
        change = _fmt_number(q.get("change"), 2)
        change_pct = _fmt_change_pct(q.get("change_pct"))
        day_high = _fmt_number(q.get("day_high"), 2)
        day_low = _fmt_number(q.get("day_low"), 2)
        lines.append(f"| **{symbol}** | {name} | {price} | {change} | {change_pct} | {day_high} | {day_low} |")

    return "\n".join(lines) + "\n"


def _build_sector_section(sectors: List[Dict[str, Any]]) -> str:
    """Build markdown table for sector performance."""
    if not sectors:
        return ""

    lines = [
        "## 🏭 섹터 퍼포먼스\n",
        "| 섹터 | 변동률 |",
        "|------|--------|",
    ]
    for s in sectors:
        raw_sector = s.get("sector", "")
        sector_kr = _SECTOR_KR.get(raw_sector, raw_sector)
        change_pct = _fmt_change_pct(s.get("change_pct"))
        lines.append(f"| {sector_kr} | {change_pct} |")

    return "\n".join(lines) + "\n"


def _build_economic_section(events: List[Dict[str, Any]]) -> str:
    """Build markdown table for economic calendar (High impact first)."""
    if not events:
        return ""

    # Sort: High first, then Medium; within same impact sort by date
    high = [e for e in events if e.get("impact") == "High"]
    medium = [e for e in events if e.get("impact") == "Medium"]
    sorted_events = sorted(high, key=lambda x: x.get("date", "")) + sorted(medium, key=lambda x: x.get("date", ""))

    lines = [
        "## 📅 주요 경제 이벤트\n",
        "| 날짜 | 국가 | 이벤트 | 중요도 | 예측 | 이전 | 실제 |",
        "|------|------|--------|--------|------|------|------|",
    ]
    for e in sorted_events:
        date = e.get("date", "")
        country = e.get("country", "")
        event = e.get("event", "")
        impact = e.get("impact", "")
        impact_display = f"{_IMPACT_EMOJI.get(impact, '')} {impact}"
        forecast = e.get("forecast", "") or "-"
        previous = e.get("previous", "") or "-"
        actual = e.get("actual", "") or "-"
        lines.append(f"| {date} | {country} | **{event}** | {impact_display} | {forecast} | {previous} | {actual} |")

    return "\n".join(lines) + "\n"


def _build_treasury_section(rates: List[Dict[str, Any]]) -> str:
    """Build markdown table for US Treasury yields."""
    if not rates:
        return ""

    lines = [
        "## 🏦 미국 국채 금리\n",
        "| 만기 | 금리 (%) | 변동 (bp) | 변동률 |",
        "|------|----------|-----------|--------|",
    ]
    for r in rates:
        maturity = r.get("maturity", "")
        rate = r.get("rate")
        change = r.get("change")
        change_pct = r.get("change_pct")

        rate_str = f"{rate:.3f}" if rate is not None else "N/A"

        if change is not None:
            bp = change * 100  # percentage points → basis points
            sign = "+" if bp >= 0 else ""
            icon = "🔺" if bp >= 0 else "🔻"
            change_str = f"{icon} {sign}{bp:.1f}bp"
        else:
            change_str = "-"

        if change_pct is not None:
            sign = "+" if change_pct >= 0 else ""
            pct_str = f"{sign}{change_pct:.2f}%"
        else:
            pct_str = "-"

        lines.append(f"| {maturity} | {rate_str} | {change_str} | {pct_str} |")

    return "\n".join(lines) + "\n"


def _build_ipo_section(ipos: List[Dict[str, Any]]) -> str:
    """Build markdown table/list for upcoming IPO calendar."""
    if not ipos:
        return ""

    is_news = any(ipo.get("is_news_fallback") for ipo in ipos)

    if is_news:
        lines = ["## 🚀 IPO 관련 뉴스\n"]
        for ipo in ipos[:15]:
            title = ipo.get("title", "")
            link = ipo.get("link", "")
            date = ipo.get("date", "")
            if link:
                lines.append(f"- [{title}]({link}) ({date})")
            else:
                lines.append(f"- {title} ({date})")
        return "\n".join(lines) + "\n"

    lines = [
        "## 🚀 IPO 캘린더\n",
        "| 날짜 | 기업명 | 심볼 | 거래소 | 공모가 범위 | 시가총액 |",
        "|------|--------|------|--------|-------------|----------|",
    ]
    for ipo in ipos:
        date = ipo.get("date", "")
        company = ipo.get("company", "-")
        symbol = ipo.get("symbol", "-")
        exchange = ipo.get("exchange", "-")
        price_range = ipo.get("price_range", "") or "-"
        market_value = ipo.get("market_value", "")
        try:
            mv_f = float(market_value)
            if mv_f >= 1_000_000_000:
                mv_str = f"${mv_f / 1_000_000_000:,.2f}B"
            elif mv_f >= 1_000_000:
                mv_str = f"${mv_f / 1_000_000:,.2f}M"
            else:
                mv_str = f"${mv_f:,.0f}"
        except (ValueError, TypeError):
            mv_str = str(market_value) if market_value else "-"
        lines.append(f"| {date} | **{company}** | {symbol} | {exchange} | {price_range} | {mv_str} |")

    return "\n".join(lines) + "\n"


def _build_earnings_section(earnings: List[Dict[str, Any]]) -> str:
    """Build markdown table for earnings calendar."""
    if not earnings:
        return ""

    # Check if this is news fallback data
    is_news = any(e.get("is_news_fallback") for e in earnings)

    if is_news:
        lines = [
            "## 💰 실적 관련 뉴스\n",
        ]
        for e in earnings[:15]:
            title = e.get("title", "")
            link = e.get("link", "")
            date = e.get("date", "")
            if link:
                lines.append(f"- [{title}]({link}) ({date})")
            else:
                lines.append(f"- {title} ({date})")
        return "\n".join(lines) + "\n"

    sorted_earnings = sorted(earnings, key=lambda x: x.get("date", ""))

    lines = [
        "## 💰 실적 발표 일정\n",
        "| 날짜 | 심볼 | 발표 시간 | EPS 예측 | 매출 예측 |",
        "|------|------|-----------|----------|-----------|",
    ]
    for e in sorted_earnings:
        date = e.get("date", "")
        symbol = e.get("symbol", "")
        time_label = e.get("time", "")
        # Normalize BMO/AMC labels
        if time_label == "bmo":
            time_display = "장전 (BMO)"
        elif time_label == "amc":
            time_display = "장후 (AMC)"
        else:
            time_display = time_label or "-"
        eps_est = _fmt_number(e.get("eps_estimated"), 2)
        rev_est = e.get("revenue_estimated", "")
        # Revenue is typically a large number — format with billions/millions
        try:
            rev_f = float(rev_est)
            if rev_f >= 1_000_000_000:
                rev_display = f"${rev_f / 1_000_000_000:,.2f}B"
            elif rev_f >= 1_000_000:
                rev_display = f"${rev_f / 1_000_000:,.2f}M"
            else:
                rev_display = f"${rev_f:,.0f}"
        except (ValueError, TypeError):
            rev_display = str(rev_est) if rev_est else "N/A"
        lines.append(f"| {date} | **{symbol}** | {time_display} | {eps_est} | {rev_display} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    """Main collection routine — consolidated FMP calendar post."""
    logger.info("=== Starting FMP calendar collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("fmp_calendar_seen.json")
    gen = PostGenerator("market-analysis")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)

    post_title = f"주요 경제 캘린더 및 실적 일정 ({today})"

    if dedup.is_duplicate_exact(post_title, "fmp_calendar", today):
        logger.info("FMP calendar post already exists for today, skipping")
        log_collection_summary(
            logger,
            collector="collect_fmp_calendar",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Fetch all data
    logger.info("Fetching market index data for %s", _INDEX_SYMBOLS)
    indices = []
    for symbol in _INDEX_SYMBOLS:
        quote = fetch_market_index_data(symbol)
        if quote:
            indices.append(quote)

    logger.info("Fetching sector performance")
    sectors = fetch_sector_performance()

    logger.info("Fetching economic calendar (30 days ahead)")
    economic_events = fetch_economic_calendar(days_ahead=30)

    logger.info("Fetching earnings calendar (7 days ahead)")
    earnings = fetch_earnings_calendar(days_ahead=7)

    logger.info("Fetching US Treasury rates")
    treasury_rates = fetch_treasury_rates()

    logger.info("Fetching IPO calendar (30 days ahead)")
    ipo_data = fetch_ipo_calendar(days_ahead=30)

    total_items = (
        len(indices) + len(sectors) + len(economic_events) + len(earnings) + len(treasury_rates) + len(ipo_data)
    )

    if total_items == 0:
        logger.warning("No FMP data collected — FMP_API_KEY may not be set or API is unavailable")
        log_collection_summary(
            logger,
            collector="collect_fmp_calendar",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Build post content
    content_parts: List[str] = []

    # Opening summary
    content_parts.append(
        f"**{today}** 기준 주요 시장 지수 {len(indices)}종, "
        f"섹터 {len(sectors)}개, "
        f"국채 금리 {len(treasury_rates)}개 만기, "
        f"경제 이벤트 {len(economic_events)}건(고·중간 중요도), "
        f"대형주 실적 발표 {len(earnings)}건, "
        f"IPO 일정 {len(ipo_data)}건을 수집했습니다.\n"
    )

    content_parts.append(_build_index_section(indices))
    content_parts.append("\n---\n")
    content_parts.append(_build_treasury_section(treasury_rates))
    content_parts.append("\n---\n")
    content_parts.append(_build_sector_section(sectors))
    content_parts.append("\n---\n")
    content_parts.append(_build_economic_section(economic_events))
    content_parts.append("\n---\n")
    content_parts.append(_build_earnings_section(earnings))
    content_parts.append("\n---\n")
    content_parts.append(_build_ipo_section(ipo_data))
    content_parts.append("\n---\n")
    content_parts.append(
        "> *본 캘린더는 Financial Modeling Prep API에서 자동 수집된 데이터이며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*\n"
    )
    content_parts.append(f"\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["market-analysis", "economic-calendar", "earnings", "treasury", "ipo", "fmp"],
        source="fmp",
        lang="ko",
        slug="fmp-economic-calendar",
    )

    post_created = 0
    if filepath:
        dedup.mark_seen(post_title, "fmp_calendar", today)
        logger.info("Created FMP calendar post: %s", filepath)
        post_created = 1

    dedup.save()
    logger.info("=== FMP calendar collection complete ===")

    log_collection_summary(
        logger,
        collector="collect_fmp_calendar",
        source_count=6,  # indices, sectors, treasury, economic, earnings, ipo
        unique_items=total_items,
        post_created=post_created,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
