#!/usr/bin/env python3
"""Collect economic calendar and earnings data from FMP API."""

import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.base_collector import BaseCollector
from common.collector_config import get_collector_config
from common.fmp_api import (
    fetch_earnings_calendar,
    fetch_economic_calendar,
    fetch_ipo_calendar,
    fetch_market_index_data,
    fetch_sector_performance,
    fetch_treasury_rates,
)
from common.post_generator import build_dated_permalink

# collectors.yml에서 설정 로드
_fmp_cfg = get_collector_config("fmp_calendar")
_INDEX_SYMBOLS: List[str] = list(_fmp_cfg.get("index_symbols", ["SPY", "QQQ", "DIA", "^VIX"]))

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


def _classify_severity(title: str, section: str = "") -> str:
    """Classify news severity based on title keywords."""
    t = title.lower()
    high_kw = [
        "beat",
        "miss",
        "surprise",
        "crash",
        "surge",
        "record",
        "warn",
        "downgrade",
        "upgrade",
        "halt",
        "delist",
        "fraud",
        "sec ",
        "fda ",
        "spacex",
        "ipo",
        "$1",
        "billion",
        "trillion",
    ]
    if any(kw in t for kw in high_kw):
        return "high"
    low_kw = ["egm", "reallocation", "limited", "conducts"]
    if any(kw in t for kw in low_kw):
        return "low"
    return "medium"


_SEVERITY_COLORS = {
    "high": "#f85149",
    "medium": "#d29922",
    "low": "#8b949e",
}
_SEVERITY_LABELS = {
    "high": "HIGH",
    "medium": "MED",
    "low": "LOW",
}


def _build_news_cards(items: List[Dict[str, Any]], heading: str, icon: str, max_items: int = 15) -> str:
    """Build HTML news cards for earnings/IPO news with severity badges."""
    if not items:
        return ""

    lines = [f"## {icon} {heading}\n", '<div class="fmp-news-list">']
    for item in items[:max_items]:
        title = item.get("title", "")
        link = item.get("link", "")
        date = item.get("date", "")
        source = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            source = parts[1].strip()

        severity = _classify_severity(title, heading)
        sev_color = _SEVERITY_COLORS[severity]
        sev_label = _SEVERITY_LABELS[severity]

        lines.append('<div class="fmp-news-card">')
        lines.append(f'  <span class="fmp-news-severity" style="background:{sev_color}">{sev_label}</span>')
        lines.append('  <div class="fmp-news-body">')
        if link:
            lines.append(f'    <a href="{link}" class="fmp-news-title" target="_blank" rel="noopener">{title}</a>')
        else:
            lines.append(f'    <span class="fmp-news-title">{title}</span>')
        lines.append('    <div class="fmp-news-meta">')
        if source:
            lines.append(f'      <span class="fmp-news-source">{source}</span>')
        if date:
            lines.append(f'      <span class="fmp-news-date">{date}</span>')
        lines.append("    </div>")
        lines.append("  </div>")
        lines.append("</div>")

    lines.append("</div>\n")
    return "\n".join(lines)


def _build_ipo_section(ipos: List[Dict[str, Any]]) -> str:
    """Build markdown table/list for upcoming IPO calendar."""
    if not ipos:
        return ""

    is_news = any(ipo.get("is_news_fallback") for ipo in ipos)

    if is_news:
        return _build_news_cards(ipos, "IPO 관련 뉴스", "🚀")

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
        return _build_news_cards(earnings, "실적 관련 뉴스", "💰")

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


class FmpCalendarCollector(BaseCollector):
    """FMP 경제 캘린더 및 실적 일정 수집기."""

    name = "fmp_calendar"
    category = "market-analysis"
    state_file = "fmp_calendar_seen.json"

    def fetch(self) -> List[Dict[str, Any]]:
        """FMP API에서 모든 데이터를 수집합니다."""
        self.logger.info("Fetching market index data for %s", _INDEX_SYMBOLS)
        indices = []
        for symbol in _INDEX_SYMBOLS:
            quote = fetch_market_index_data(symbol)
            if quote:
                indices.append(quote)

        self.logger.info("Fetching sector performance")
        sectors = fetch_sector_performance()

        self.logger.info("Fetching economic calendar (30 days ahead)")
        economic_events = fetch_economic_calendar(days_ahead=30)

        self.logger.info("Fetching earnings calendar (7 days ahead)")
        earnings = fetch_earnings_calendar(days_ahead=7)

        self.logger.info("Fetching US Treasury rates")
        treasury_rates = fetch_treasury_rates()

        self.logger.info("Fetching IPO calendar (30 days ahead)")
        ipo_data = fetch_ipo_calendar(days_ahead=30)

        # 데이터를 인스턴스에 저장 (build_content에서 사용)
        self._indices = indices
        self._sectors = sectors
        self._economic_events = economic_events
        self._earnings = earnings
        self._treasury_rates = treasury_rates
        self._ipo_data = ipo_data

        # 모든 항목을 합산하여 반환 (파이프라인 호환)
        all_items: List[Dict[str, Any]] = []
        for idx in indices:
            all_items.append({"title": idx.get("symbol", ""), "source": "fmp_index", "type": "index", **idx})
        for s in sectors:
            all_items.append({"title": s.get("sector", ""), "source": "fmp_sector", "type": "sector", **s})
        for e in economic_events:
            all_items.append({"title": e.get("event", ""), "source": "fmp_economic", "type": "economic", **e})
        for e in earnings:
            all_items.append({"title": e.get("symbol", ""), "source": "fmp_earnings", "type": "earnings", **e})
        for r in treasury_rates:
            all_items.append({"title": r.get("maturity", ""), "source": "fmp_treasury", "type": "treasury", **r})
        for i in ipo_data:
            all_items.append({"title": i.get("company", ""), "source": "fmp_ipo", "type": "ipo", **i})
        return all_items

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """FMP 데이터는 별도 필터링 없이 그대로 반환합니다."""
        return items

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """마크다운 포스트 본문을 생성합니다."""
        indices = self._indices
        sectors = self._sectors
        economic_events = self._economic_events
        earnings = self._earnings
        treasury_rates = self._treasury_rates
        ipo_data = self._ipo_data

        content_parts: List[str] = []

        # Opening summary — lead with a headline (top event + top earnings),
        # keep counts as a secondary "스코어보드" sentence so the post-summary
        # excerpt reads like an editorial brief instead of a count dump.
        headlines: List[str] = []
        if economic_events:
            top_event = (economic_events[0].get("name") or "").strip()
            if top_event:
                headlines.append(f"주요 경제 이벤트 **{top_event}**")
        if earnings:
            top_earn_symbol = (earnings[0].get("symbol") or "").strip()
            top_earn_name = (earnings[0].get("name") or "").strip()
            if top_earn_symbol:
                _label = f"**{top_earn_symbol}**"
                if top_earn_name and top_earn_name != top_earn_symbol:
                    _label += f" ({top_earn_name})"
                headlines.append(f"대형 실적 발표 {_label}")

        if headlines:
            lead = f"**{self.today}** " + " · ".join(headlines) + " 등 주목 일정이 예정되어 있습니다. "
        else:
            lead = f"**{self.today}** 오늘 일정에서 "

        counts = (
            f"시장 지수 {len(indices)}종, "
            f"섹터 {len(sectors)}개, "
            f"국채 금리 {len(treasury_rates)}개 만기, "
            f"경제 이벤트 {len(economic_events)}건(고·중간 중요도), "
            f"대형주 실적 {len(earnings)}건, "
            f"IPO 일정 {len(ipo_data)}건을 정리했습니다.\n"
        )
        content_parts.append(lead + counts)

        # Stat grid
        stat_items = []
        if indices:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{len(indices)}</div><div class="stat-label">주요 지수</div></div>'
            )
        if earnings:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{len(earnings)}</div><div class="stat-label">실적 발표</div></div>'
            )
        if economic_events:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{len(economic_events)}</div><div class="stat-label">경제 이벤트</div></div>'
            )
        if ipo_data:
            stat_items.append(
                f'<div class="stat-item"><div class="stat-value">{len(ipo_data)}</div><div class="stat-label">IPO 일정</div></div>'
            )
        if stat_items:
            content_parts.append('<div class="stat-grid">' + "".join(stat_items) + "</div>\n")

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
        content_parts.append(
            '<div class="wm-footer-meta">'
            f"<span>수집 시각: {self.now.strftime('%Y-%m-%d %H:%M')} KST</span>"
            "<span>소스: Financial Modeling Prep API</span>"
            "</div>"
        )

        return "\n".join(content_parts)

    def run(self) -> None:
        """메인 실행 파이프라인 — FMP 경제 캘린더 포스트 생성."""
        import time

        self.logger.info("=== Starting FMP calendar collection ===")
        self._started_at = time.monotonic()

        post_title = f"주요 경제 캘린더 및 실적 일정 ({self.today})"

        if self.is_duplicate_exact(post_title, "fmp_calendar"):
            self.logger.info("FMP calendar post already exists for today, skipping")
            self.save_state()
            self.log_summary([])
            return

        # Fetch all data
        items = self.fetch()

        if not items:
            self.logger.warning("No FMP data collected — FMP_API_KEY may not be set or API is unavailable")
            self.save_state()
            self.log_summary([])
            return

        content = self.build_content(items)
        total_items = len(items)

        indices = self._indices
        sectors = self._sectors
        economic_events = self._economic_events
        earnings = self._earnings
        treasury_rates = self._treasury_rates
        ipo_data = self._ipo_data

        briefing_image_path = ""
        try:
            from common.image_generator import generate_news_briefing_card

            card_themes = []
            for name, emoji, count in [
                ("주요 시장 지수", "📊", len(indices)),
                ("미국 국채 금리", "🏦", len(treasury_rates)),
                ("섹터 퍼포먼스", "🏭", len(sectors)),
                ("주요 경제 이벤트", "📅", len(economic_events)),
                ("실적 발표", "💵", len(earnings)),
                ("IPO 일정", "🚀", len(ipo_data)),
            ]:
                if count > 0:
                    card_themes.append({"name": name, "emoji": emoji, "count": count, "keywords": []})

            if card_themes:
                img = generate_news_briefing_card(
                    card_themes[:4],
                    self.today,
                    category="Economic Calendar",
                    total_count=total_items,
                    filename=f"news-briefing-calendar-{self.today}.png",
                )
                if img:
                    fn = os.path.basename(img)
                    briefing_image_path = f"/assets/images/generated/{fn}"
        except ImportError as exc:
            self.logger.debug("Optional dependency unavailable: %s", exc)
        except Exception as exc:
            self.logger.warning("Economic calendar briefing image failed: %s", exc)

        _desc_parts_fmp = []
        if indices:
            _desc_parts_fmp.append(f"시장 지수 {len(indices)}개")
        if earnings:
            _desc_parts_fmp.append(f"실적 발표 {len(earnings)}건")
        if economic_events:
            _desc_parts_fmp.append(f"경제 이벤트 {len(economic_events)}건")
        if ipo_data:
            _desc_parts_fmp.append(f"IPO {len(ipo_data)}건")
        _desc_ko = f"경제 캘린더 {total_items}건 수집. "
        if _desc_parts_fmp:
            _desc_ko += f"{', '.join(_desc_parts_fmp)} 포함. "
        _next_event = economic_events[0].get("name", "")[:30] if economic_events else ""
        _next_earn = earnings[0].get("name", "")[:20] if earnings else ""
        if _next_event:
            _desc_ko += f"주목 이벤트: {_next_event}."
        elif _next_earn:
            _desc_ko += f"주목 실적: {_next_earn} 등."
        _desc_ko = _desc_ko[:160]

        filepath = self.create_post(
            title=post_title,
            content=content,
            tags=["market-analysis", "economic-calendar", "earnings", "treasury", "ipo", "fmp"],
            source="fmp",
            image=briefing_image_path,
            extra_frontmatter={
                "permalink": build_dated_permalink("market-analysis", self.today, "fmp-economic-calendar"),
                "description": _desc_ko,
                "description_ko": _desc_ko,
            },
            slug="fmp-economic-calendar",
        )

        if filepath:
            self.mark_seen(post_title, "fmp_calendar")
            self.logger.info("Created FMP calendar post: %s", filepath)

        self.save_state()
        self.logger.info("=== FMP calendar collection complete ===")
        self.log_summary(items)


def main() -> None:
    """Main collection routine — consolidated FMP calendar post."""
    collector = FmpCalendarCollector()
    collector.run()


if __name__ == "__main__":
    main()
