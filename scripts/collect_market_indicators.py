#!/usr/bin/env python3
"""Collect market breadth, sentiment, and risk indicators and generate a Jekyll post.

Sources:
- CNN Fear & Greed Index (stock market sentiment)
- VIX via yfinance (^VIX)
- DXY, Gold (GC=F), Oil (CL=F) via yfinance
- Treasury yield news via Google News RSS
- Put/Call ratio news via Google News RSS
- Margin debt indicator news via Google News RSS
"""

import os
import sys
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import BROWSER_USER_AGENT, REQUEST_TIMEOUT, get_ssl_verify, setup_logging
from common.dedup import DedupEngine
from common.markdown_utils import html_reference_details
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.utils import request_with_retry

logger = setup_logging("collect_market_indicators")

VERIFY_SSL = get_ssl_verify()

# ── Constants ──────────────────────────────────────────────────────────────────
CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}


# ── Data fetchers ──────────────────────────────────────────────────────────────


def fetch_cnn_fear_greed() -> Dict[str, Any]:
    """Fetch CNN Stock Market Fear & Greed Index.

    Returns dict with score (0-100), rating, and previous_close score.
    """
    try:
        resp = request_with_retry(
            CNN_FEAR_GREED_URL,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=VERIFY_SSL,
            headers=CNN_HEADERS,
        )
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        rating = fg.get("rating", "N/A")
        prev_score = fg.get("previous_close")

        if score is None:
            logger.warning("CNN Fear & Greed: 'score' field missing in response")
            return {}

        result: Dict[str, Any] = {
            "score": round(float(score), 1),
            "rating": rating,
        }
        if prev_score is not None:
            result["prev_score"] = round(float(prev_score), 1)
            result["change"] = round(float(score) - float(prev_score), 1)

        logger.info("CNN Fear & Greed: score=%.1f rating=%s", result["score"], rating)
        return result
    except requests.exceptions.RequestException as e:
        logger.warning("CNN Fear & Greed fetch failed: %s", e)
        return {}
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("CNN Fear & Greed parse error: %s", e)
        return {}


def fetch_yfinance_market_data() -> Dict[str, Any]:
    """Fetch VIX, DXY, Gold, Oil via yfinance.

    Returns dict keyed by asset name with price, change, change_pct.
    """
    results: Dict[str, Any] = {}
    try:
        import yfinance as yf

        symbols = {
            "^VIX": "VIX",
            "DX-Y.NYB": "DXY",
            "GC=F": "Gold",
            "CL=F": "Oil",
        }
        for symbol, name in symbols.items():
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price is not None and prev is not None and prev != 0:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    results[name] = {
                        "price": price,
                        "price_fmt": f"{price:,.2f}",
                        "change": change,
                        "change_fmt": f"{change:+,.2f}",
                        "change_pct": change_pct,
                        "change_pct_fmt": f"{change_pct:+.2f}%",
                    }
                    logger.info("yfinance %s (%s): %.2f (%+.2f%%)", name, symbol, price, change_pct)
                else:
                    logger.warning("yfinance %s: missing price or prev_close", symbol)
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning("yfinance %s (%s): %s", name, symbol, e)
    except ImportError:
        logger.warning("yfinance not installed, skipping market price data")
    return results


def fetch_treasury_yield_news() -> List[Dict[str, Any]]:
    """Fetch treasury yield news via Google News RSS (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=%2210-year+treasury+yield%22&hl=en-US&gl=US&ceid=US:en",
            "10Y Treasury Yield",
            ["treasury", "10y", "yield"],
        ),
        (
            "https://news.google.com/rss/search?q=%222-year+treasury+yield%22&hl=en-US&gl=US&ceid=US:en",
            "2Y Treasury Yield",
            ["treasury", "2y", "yield"],
        ),
        (
            "https://news.google.com/rss/search?q=treasury+yield+curve+inversion&hl=en-US&gl=US&ceid=US:en",
            "Yield Curve",
            ["treasury", "yield-curve"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)
    logger.info("Treasury yield news: %d items", len(items))
    return items


def fetch_put_call_ratio_news() -> List[Dict[str, Any]]:
    """Fetch put/call ratio news via Google News RSS (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=%22put+call+ratio%22+cboe&hl=en-US&gl=US&ceid=US:en",
            "Put/Call Ratio CBOE",
            ["put-call", "options", "cboe"],
        ),
        (
            "https://news.google.com/rss/search?q=%22put+call+ratio%22+options+sentiment&hl=en-US&gl=US&ceid=US:en",
            "Put/Call Ratio Sentiment",
            ["put-call", "options", "sentiment"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)
    logger.info("Put/Call ratio news: %d items", len(items))
    return items


def fetch_margin_debt_news() -> List[Dict[str, Any]]:
    """Fetch margin debt indicator news via Google News RSS (concurrent)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=%22margin+debt%22+OR+%22margin+lending%22+NYSE&hl=en-US&gl=US&ceid=US:en",
            "Margin Debt NYSE",
            ["margin-debt", "leverage", "risk"],
        ),
        (
            "https://news.google.com/rss/search?q=%22margin+call%22+OR+%22forced+liquidation%22+stock+market&hl=en-US&gl=US&ceid=US:en",
            "Margin Call/Liquidation",
            ["margin-call", "liquidation", "risk"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)
    logger.info("Margin debt news: %d items", len(items))
    return items


def fetch_market_breadth_news() -> List[Dict[str, Any]]:
    """Fetch market breadth news (advances/declines, breadth indicators) via Google News RSS."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=S%26P+500+advances+declines+market+breadth&hl=en-US&gl=US&ceid=US:en",
            "S&P 500 Breadth",
            ["breadth", "advances", "declines"],
        ),
        (
            "https://news.google.com/rss/search?q=%22new+highs%22+%22new+lows%22+NYSE+stock+market&hl=en-US&gl=US&ceid=US:en",
            "New Highs/Lows",
            ["breadth", "new-highs", "new-lows"],
        ),
        (
            "https://news.google.com/rss/search?q=%22McClellan+oscillator%22+OR+%22market+breadth%22+NYSE&hl=en-US&gl=US&ceid=US:en",
            "Breadth Indicators",
            ["breadth", "mcclellan", "oscillator"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)
    logger.info("Market breadth news: %d items", len(items))
    return items


# ── Formatting helpers ─────────────────────────────────────────────────────────


def _rating_to_korean(rating: str) -> str:
    """Map CNN Fear & Greed rating to Korean."""
    mapping = {
        "Extreme Fear": "극도의 공포",
        "Fear": "공포",
        "Neutral": "중립",
        "Greed": "탐욕",
        "Extreme Greed": "극도의 탐욕",
    }
    return mapping.get(rating, rating)


def _fear_greed_signal(score: float) -> str:
    """Return trading signal text based on score."""
    if score <= 20:
        return "매수 기회 탐색 (극도의 공포 → 역발상)"
    elif score <= 40:
        return "신중한 매수 접근"
    elif score <= 60:
        return "중립 관망"
    elif score <= 80:
        return "리스크 관리 강화"
    else:
        return "과매수 경고 (거품 리스크)"


def _vix_signal(price: float) -> str:
    """Return VIX interpretation."""
    if price < 15:
        return "낮음 (시장 안정, 자기만족 주의)"
    elif price < 20:
        return "보통 (정상 변동성)"
    elif price < 30:
        return "높음 (불안 심리 확산)"
    elif price < 40:
        return "매우 높음 (공포 구간)"
    else:
        return "극도 (패닉 수준 — 역사적 급등)"


def _price_icon(change_pct: Optional[float]) -> str:
    """Return directional emoji for price change."""
    if change_pct is None:
        return ""
    if change_pct >= 1.0:
        return "🟢"
    elif change_pct > 0:
        return "🔼"
    elif change_pct <= -1.0:
        return "🔴"
    else:
        return "🔽"


def _format_news_rows(items: List[Dict[str, Any]], limit: int = 5) -> str:
    """Format news items into a bullet list (max `limit` items)."""
    if not items:
        return "> 관련 뉴스를 가져올 수 없습니다.\n"
    rows = []
    seen_titles: set = set()
    for item in items:
        title = item.get("title", "").strip()
        link = item.get("link", "")
        source = item.get("source", "")
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        if link:
            rows.append(f"- [{title}]({link}) *({source})*")
        else:
            rows.append(f"- {title} *({source})*")
        if len(rows) >= limit:
            break
    return "\n".join(rows) + "\n" if rows else "> 관련 뉴스를 가져올 수 없습니다.\n"


# ── Content builder ────────────────────────────────────────────────────────────


def build_post_content(
    cnn_fg: Dict[str, Any],
    market_data: Dict[str, Any],
    treasury_news: List[Dict[str, Any]],
    put_call_news: List[Dict[str, Any]],
    breadth_news: List[Dict[str, Any]],
    margin_news: List[Dict[str, Any]],
    today: str,
    now: datetime,
) -> str:
    """Build full markdown content for the market indicators post."""
    parts: List[str] = []

    # ── Opening ──────────────────────────────────────────────────────────────
    source_count = sum(
        [
            1 if cnn_fg else 0,
            len(market_data),
            1 if treasury_news else 0,
            1 if put_call_news else 0,
            1 if breadth_news else 0,
            1 if margin_news else 0,
        ]
    )
    parts.append(f"**{today}** 기준 시장 심리·리스크 지표를 {source_count}개 소스에서 수집했습니다.\n")

    # ── Section 1: 시장 심리 지표 ──────────────────────────────────────────
    parts.append("## 🌡️ 시장 심리 지표\n")
    parts.append("| 지표 | 현재값 | 변화 | 신호 |")
    parts.append("|------|--------|------|------|")

    # CNN Fear & Greed
    if cnn_fg:
        score = cnn_fg["score"]
        rating_ko = _rating_to_korean(cnn_fg.get("rating", ""))
        change_str = "N/A"
        if "change" in cnn_fg:
            ch = cnn_fg["change"]
            change_str = f"{ch:+.1f}점"
        signal = _fear_greed_signal(score)
        parts.append(f"| CNN 공포탐욕 지수 | **{score}** ({rating_ko}) | {change_str} | {signal} |")
    else:
        parts.append("| CNN 공포탐욕 지수 | 데이터 없음 | — | — |")

    # VIX
    vix = market_data.get("VIX")
    if vix:
        icon = _price_icon(vix["change_pct"])
        signal = _vix_signal(vix["price"])
        parts.append(f"| VIX (공포 지수) | **{vix['price_fmt']}** | {icon} {vix['change_pct_fmt']} | {signal} |")
    else:
        parts.append("| VIX (공포 지수) | 데이터 없음 | — | — |")

    # Put/Call news (indicator of sentiment)
    parts.append("| Put/Call 비율 | 뉴스 기반 | 아래 참조 | 옵션 시장 심리 |")
    parts.append("")

    # Put/Call news detail
    parts.append("**Put/Call 비율 관련 뉴스:**\n")
    parts.append(_format_news_rows(put_call_news, limit=4))

    # ── Section 2: 주요 자산 동향 ─────────────────────────────────────────
    parts.append("\n## 📈 주요 자산 동향\n")
    parts.append("| 자산 | 가격 | 변동률 | 방향 |")
    parts.append("|------|------|--------|------|")

    asset_rows = [
        ("DXY", "달러 인덱스 (DXY)"),
        ("Gold", "금 (Gold, $/oz)"),
        ("Oil", "WTI 원유 (Oil, $/bbl)"),
    ]
    for key, label in asset_rows:
        asset = market_data.get(key)
        if asset:
            icon = _price_icon(asset["change_pct"])
            parts.append(f"| {label} | **{asset['price_fmt']}** | {asset['change_pct_fmt']} | {icon} |")
        else:
            parts.append(f"| {label} | 데이터 없음 | — | — |")

    # Treasury yields (news-based)
    parts.append("| 10년물 국채 금리 | 뉴스 기반 | 아래 참조 | — |")
    parts.append("| 2년물 국채 금리 | 뉴스 기반 | 아래 참조 | — |")
    parts.append("")

    parts.append("**국채 금리 관련 뉴스:**\n")
    parts.append(_format_news_rows(treasury_news, limit=5))

    # DXY narrative
    dxy = market_data.get("DXY")
    if dxy:
        dxy_price = dxy["price"]
        if dxy_price > 105:
            dxy_note = "달러 강세 구간 — 신흥국 자금 이탈 및 원자재 가격 하락 압력."
        elif dxy_price > 100:
            dxy_note = "달러 중립~강세 — 글로벌 자산 배분에 주의가 필요합니다."
        elif dxy_price > 95:
            dxy_note = "달러 약세 전환 — 신흥국 시장 및 원자재에 긍정적."
        else:
            dxy_note = "달러 약세 — 위험자산 선호 심리 강화 환경."
        parts.append(f"\n> **DXY 해석**: {dxy_note}")

    # ── Section 3: 시장 건강도 (Market Breadth) ───────────────────────────
    parts.append("\n## 📊 시장 건강도 (Market Breadth)\n")
    parts.append(
        "시장 폭(Market Breadth)은 전체 종목 중 상승 종목의 비율로 "
        "추세의 신뢰도를 평가합니다. 지수가 오르더라도 소수 종목만 상승하면 "
        "건강하지 못한 랠리일 수 있습니다.\n"
    )
    parts.append(_format_news_rows(breadth_news, limit=6))

    # Breadth interpretation guide
    parts.append("\n**시장 폭 해석 가이드:**\n")
    parts.append("| 상태 | 특징 | 투자자 행동 |")
    parts.append("|------|------|-------------|")
    parts.append("| 넓은 폭 (>70% 상승) | 강력한 추세, 광범위한 참여 | 추세 추종 유리 |")
    parts.append("| 보통 폭 (40~70%) | 선택적 상승, 테마 차별화 | 섹터 선별 필요 |")
    parts.append("| 좁은 폭 (<40% 상승) | 소수 주도 — 취약한 랠리 | 리스크 관리 강화 |")

    # ── Section 4: 리스크 모니터 ─────────────────────────────────────────
    parts.append("\n## ⚠️ 리스크 모니터\n")
    parts.append(
        "레버리지·마진 채무는 시장의 취약성을 나타내는 선행 지표입니다. "
        "마진 채무가 과도하게 높을 경우 급락 시 강제 청산으로 낙폭이 확대될 수 있습니다.\n"
    )
    parts.append(_format_news_rows(margin_news, limit=5))

    # Risk dashboard
    parts.append("\n**리스크 레벨 평가:**\n")
    parts.append("| 지표 | 상태 | 수준 |")
    parts.append("|------|------|------|")

    # VIX risk level
    if vix:
        vp = vix["price"]
        vix_level = "🟢 낮음" if vp < 15 else ("🟡 보통" if vp < 20 else ("🟠 높음" if vp < 30 else "🔴 위험"))
        parts.append(f"| VIX | {vix['price_fmt']} | {vix_level} |")
    else:
        parts.append("| VIX | N/A | — |")

    # CNN FG risk
    if cnn_fg:
        score = cnn_fg["score"]
        fg_level = (
            "🔴 극도 공포"
            if score <= 20
            else (
                "🟠 공포"
                if score <= 40
                else ("🟢 중립" if score <= 60 else ("🟡 탐욕" if score <= 80 else "🔴 극도 탐욕"))
            )
        )
        parts.append(f"| CNN 공포탐욕 | {cnn_fg['score']} | {fg_level} |")
    else:
        parts.append("| CNN 공포탐욕 | N/A | — |")

    # DXY risk
    if dxy:
        dxy_level = "🔴 강달러 위험" if dxy["price"] > 105 else ("🟡 주의" if dxy["price"] > 100 else "🟢 양호")
        parts.append(f"| 달러 강세 | {dxy['price_fmt']} | {dxy_level} |")
    else:
        parts.append("| 달러 강세 | N/A | — |")

    parts.append("")

    # ── Disclaimer ────────────────────────────────────────────────────────────
    parts.append("\n---\n")
    parts.append(
        "> *본 지표 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )

    # ── References ────────────────────────────────────────────────────────────
    all_news = treasury_news + put_call_news + breadth_news + margin_news
    source_links = [
        {"title": item.get("title", ""), "link": item.get("link", ""), "source": item.get("source", "")}
        for item in all_news
        if item.get("link") and item.get("title")
    ]
    if source_links:
        parts.append("\n" + html_reference_details("참고 링크", source_links, limit=20, title_max_len=90))

    # Fixed reference links
    parts.append("\n**데이터 소스:**")
    parts.append("- [CNN Fear & Greed Index](https://www.cnn.com/markets/fear-and-greed)")
    parts.append("- [CBOE VIX](https://www.cboe.com/tradable_products/vix/)")
    parts.append("- [FINVIZ Market Map](https://finviz.com/map.ashx)")

    parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    return "\n".join(parts)


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    """Main collection routine — consolidated market indicators post."""
    logger.info("=== Starting market indicators collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("market_indicators_seen.json")
    gen = PostGenerator("market-analysis")

    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")

    post_title = f"시장 심리 및 리스크 지표 ({today})"

    # Early exit if already generated today
    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Market indicators post already exists for %s, skipping", today)
        log_collection_summary(
            logger,
            collector="collect_market_indicators",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Fetch all data sources (news fetches run concurrently internally)
    cnn_fg = fetch_cnn_fear_greed()
    market_data = fetch_yfinance_market_data()
    treasury_news = fetch_treasury_yield_news()
    put_call_news = fetch_put_call_ratio_news()
    breadth_news = fetch_market_breadth_news()
    margin_news = fetch_margin_debt_news()

    all_news_items = treasury_news + put_call_news + breadth_news + margin_news
    has_any_data = cnn_fg or market_data or all_news_items

    if not has_any_data:
        logger.warning("No data collected from any source, skipping post creation")
        log_collection_summary(
            logger,
            collector="collect_market_indicators",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Build post content
    content = build_post_content(
        cnn_fg=cnn_fg,
        market_data=market_data,
        treasury_news=treasury_news,
        put_call_news=put_call_news,
        breadth_news=breadth_news,
        margin_news=margin_news,
        today=today,
        now=now,
    )

    # Generate Jekyll post
    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["market-analysis", "fear-greed", "vix", "market-breadth", "sentiment"],
        source="consolidated",
        lang="ko",
        slug="daily-market-indicators",
    )

    post_created = 0
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created market indicators post: %s", filepath)
        post_created = 1

    dedup.save()
    logger.info("=== Market indicators collection complete ===")

    unique_items = len(
        {f"{item.get('title', '')}|{item.get('link', '')}" for item in all_news_items if item.get("title")}
    )
    source_count = len([x for x in [cnn_fg, market_data] if x]) + len(
        {item.get("source", "") for item in all_news_items if item.get("source")}
    )

    log_collection_summary(
        logger,
        collector="collect_market_indicators",
        source_count=source_count,
        unique_items=unique_items,
        post_created=post_created,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
