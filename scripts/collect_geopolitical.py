#!/usr/bin/env python3
"""Collect geopolitical risk data from free public APIs for investment analysis.

Sources:
- Polymarket API (public, no auth): prediction markets on geopolitics/elections/conflicts
- GDELT API (free, public): global news event database with tone analysis
- Google News RSS (English + Korean): geopolitical risk investment news
"""

import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import requests

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    get_ssl_verify,
    setup_logging,
)
from common.dedup import DedupEngine
from common.enrichment import enrich_items
from common.markdown_utils import (
    html_reference_details,
    markdown_link,
    markdown_table,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.utils import sanitize_string, truncate_text

logger = setup_logging("collect_geopolitical")

VERIFY_SSL = get_ssl_verify()

_GEO_SOURCE_CONTEXT: Dict[str, Dict[str, Any]] = {
    "polymarket.com": {"name": "Polymarket", "tags": ["prediction-market"]},
    "gdeltproject.org": {"name": "GDELT", "tags": ["geopolitical", "data"]},
}

# Minimum volume (USD) for Polymarket markets to include
_POLYMARKET_MIN_VOLUME = 10_000

# Geopolitical keywords to filter Polymarket markets
_POLYMARKET_GEO_TAGS = ["geopolitics", "politics", "elections", "ukraine", "middle-east", "nato"]

# GDELT API query for geopolitical risk events
_GDELT_QUERY = "geopolitical+risk+OR+military+conflict+OR+sanctions+OR+war+OR+coup+OR+nuclear"


def fetch_polymarket(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch active prediction markets related to geopolitics from Polymarket.

    Uses the public gamma-api.polymarket.com endpoint (no auth required).
    Filters for markets with volume > _POLYMARKET_MIN_VOLUME.
    """
    items: List[Dict[str, Any]] = []

    for tag in _POLYMARKET_GEO_TAGS:
        if len(items) >= limit:
            break
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "tag": tag,
            "active": "true",
            "closed": "false",
            "limit": 50,
        }
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_SSL,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [])

            for market in markets:
                if not isinstance(market, dict):
                    continue

                # Filter by volume
                volume = _parse_float(market.get("volume") or market.get("volumeNum"))
                if volume is not None and volume < _POLYMARKET_MIN_VOLUME:
                    continue

                question = sanitize_string(market.get("question", ""), 300)
                if not question:
                    continue

                # Parse outcome prices / probabilities
                outcomes = market.get("outcomes", [])
                prices = market.get("outcomePrices", [])
                probability_str = _parse_probability(outcomes, prices)

                end_date = market.get("endDate", market.get("end_date_iso", ""))
                slug = market.get("slug", market.get("conditionId", ""))
                link = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"

                volume_str = f"${volume:,.0f}" if volume is not None else "N/A"

                description = (
                    f"예측 확률: {probability_str} | "
                    f"거래량: {volume_str} | "
                    f"마감: {end_date[:10] if end_date else 'N/A'}"
                )

                items.append(
                    {
                        "title": question,
                        "description": description,
                        "link": link,
                        "published": end_date,
                        "source": "Polymarket",
                        "tags": ["prediction-market", "geopolitical", tag],
                        "volume": volume or 0,
                        "probability": probability_str,
                    }
                )

            logger.info("Polymarket tag=%s: fetched %d valid markets", tag, len(items))

        except requests.exceptions.RequestException as e:
            logger.warning("Polymarket tag=%s fetch failed: %s", tag, e)
        except (ValueError, KeyError) as e:
            logger.warning("Polymarket tag=%s parse error: %s", tag, e)

    # Sort by volume descending, limit results
    items.sort(key=lambda x: x.get("volume", 0), reverse=True)
    return items[:limit]


def _parse_float(value: Any) -> Optional[float]:
    """Parse a numeric value from various types."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_probability(outcomes: List[Any], prices: List[Any]) -> str:
    """Parse outcome prices into a readable probability string."""
    if not outcomes or not prices:
        return "N/A"

    parts = []
    for i, outcome in enumerate(outcomes[:3]):
        if i < len(prices):
            prob = _parse_float(prices[i])
            if prob is not None:
                # Polymarket prices are 0-1 (probability) or 0-100 (cents)
                if prob > 1:
                    prob = prob / 100
                parts.append(f"{outcome}: {prob:.0%}")

    return " / ".join(parts) if parts else "N/A"


def fetch_gdelt(limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch recent geopolitical news from GDELT API with tone analysis.

    Uses the free GDELT DOC 2.0 API (no auth required).
    Returns articles with tone sentiment scores.
    """
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": _GDELT_QUERY,
        "mode": "ArtList",
        "maxrecords": min(limit, 75),
        "format": "json",
        "sortby": "DateDesc",
        "timespan": "1d",
    }

    items: List[Dict[str, Any]] = []

    try:
        resp = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        if not isinstance(articles, list):
            logger.warning("GDELT: unexpected response format")
            return []

        for article in articles[:limit]:
            title = sanitize_string(article.get("title", ""), 300)
            if not title:
                continue

            url_link = article.get("url", "")
            source = article.get("domain", article.get("sourcecountry", "GDELT"))
            pub_date = article.get("seendate", "")
            tone = _parse_float(article.get("tone"))

            # Convert tone to readable label
            tone_label = _tone_label(tone)
            tone_str = f"{tone:.1f}" if tone is not None else "N/A"

            description = f"출처: {source} | 감성 점수: {tone_str} ({tone_label})"

            items.append(
                {
                    "title": title,
                    "description": description,
                    "link": url_link,
                    "published": pub_date,
                    "source": f"GDELT/{source}",
                    "tags": ["geopolitical", "gdelt", "news"],
                    "tone": tone or 0.0,
                }
            )

        logger.info("GDELT: fetched %d articles", len(items))

    except requests.exceptions.RequestException as e:
        logger.warning("GDELT fetch failed: %s", e)
    except (ValueError, KeyError) as e:
        logger.warning("GDELT parse error: %s", e)

    return items


def _tone_label(tone: Optional[float]) -> str:
    """Convert GDELT tone score to Korean label.

    GDELT tone: negative = negative sentiment, positive = positive.
    Range typically -10 to +10 but can extend further.
    """
    if tone is None:
        return "중립"
    if tone <= -5:
        return "매우 부정"
    if tone <= -2:
        return "부정"
    if tone < 2:
        return "중립"
    if tone < 5:
        return "긍정"
    return "매우 긍정"


def fetch_google_news_geopolitical() -> List[Dict[str, Any]]:
    """Fetch geopolitical risk news from Google News RSS (English + Korean)."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=geopolitical+risk+investment&hl=en&gl=US&ceid=US:en",
            "Google News EN (Geopolitical)",
            ["geopolitical", "risk", "english"],
        ),
        (
            "https://news.google.com/rss/search?q=military+conflict+sanctions+war&hl=en&gl=US&ceid=US:en",
            "Google News EN (Conflict)",
            ["geopolitical", "conflict", "english"],
        ),
        (
            "https://news.google.com/rss/search?q=%EC%A7%80%EC%A0%95%ED%95%99+%EB%A6%AC%EC%8A%A4%ED%81%AC+%ED%88%AC%EC%9E%90&hl=ko&gl=KR&ceid=KR:ko",
            "Google News KR (지정학)",
            ["geopolitical", "risk", "korean"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def _classify_geo_theme(title: str) -> str:
    """Classify geopolitical news into investment-relevant themes."""
    text = title.lower()
    if any(kw in text for kw in ["sanction", "제재", "embargo"]):
        return "제재/경제압박"
    if any(kw in text for kw in ["election", "선거", "vote", "ballot", "poll"]):
        return "선거/정치"
    if any(kw in text for kw in ["war", "military", "전쟁", "군사", "attack", "strike", "missile", "ceasefire"]):
        return "군사/분쟁"
    if any(kw in text for kw in ["nuclear", "핵", "nuke", "icbm", "ballistic"]):
        return "핵/WMD"
    if any(kw in text for kw in ["trade", "tariff", "무역", "관세", "supply chain", "공급망"]):
        return "무역/공급망"
    if any(kw in text for kw in ["energy", "oil", "gas", "pipeline", "opec", "에너지", "원유"]):
        return "에너지/자원"
    if any(kw in text for kw in ["diplomacy", "summit", "외교", "협상", "treaty", "agreement"]):
        return "외교/협상"
    return "기타 지정학"


def _risk_level_from_theme(theme: str) -> str:
    """Map geopolitical theme to investment risk level."""
    high_risk = {"군사/분쟁", "핵/WMD", "제재/경제압박"}
    medium_risk = {"무역/공급망", "에너지/자원", "선거/정치"}
    if theme in high_risk:
        return "높음"
    if theme in medium_risk:
        return "중간"
    return "낮음"


def _build_polymarket_section(markets: List[Dict[str, Any]]) -> List[str]:
    """Build the Polymarket prediction market section of the post."""
    if not markets:
        return []

    lines = []
    rows = []
    for i, market in enumerate(markets[:10], 1):
        question = truncate_text(market.get("title", ""), 80)
        link = market.get("link", "")
        probability = market.get("probability", "N/A")
        volume = market.get("volume", 0)
        volume_str = f"${volume:,.0f}" if volume else "N/A"

        question_cell = markdown_link(f"**{question}**", link) if link else f"**{question}**"
        rows.append((i, question_cell, probability, volume_str))

    lines.append(
        markdown_table(
            ["#", "이벤트 질문", "예측 확률", "거래량"],
            rows,
            aligns=["center", "left", "center", "right"],
        )
    )

    # Summary stats
    total_volume = sum(m.get("volume", 0) for m in markets)
    lines.append(
        f"\n> 총 {len(markets)}개 예측 시장 | "
        f"합산 거래량: ${total_volume:,.0f} | "
        f"출처: [Polymarket](https://polymarket.com)\n"
    )

    return lines


def _build_gdelt_section(articles: List[Dict[str, Any]]) -> List[str]:
    """Build the GDELT news section with tone analysis."""
    if not articles:
        return []

    lines = []

    # Tone distribution summary
    tones = [a.get("tone", 0.0) for a in articles if isinstance(a.get("tone"), (int, float))]
    if tones:
        avg_tone = sum(tones) / len(tones)
        tone_label = _tone_label(avg_tone)
        lines.append(
            f"**GDELT 감성 분석**: 평균 톤 점수 `{avg_tone:.2f}` ({tone_label}) "
            f"— 음수일수록 부정적, 양수일수록 긍정적 보도입니다.\n"
        )

    # Top articles by most negative tone (highest risk signal)
    sorted_articles = sorted(articles, key=lambda x: x.get("tone", 0.0))
    shown = 0
    for article in sorted_articles[:10]:
        title = article.get("title", "")
        if not title:
            continue
        link = article.get("link", "")
        source = article.get("source", "GDELT")
        tone = article.get("tone", 0.0)
        tone_str = f"{tone:.1f}" if isinstance(tone, (int, float)) else "N/A"
        tone_lbl = _tone_label(tone if isinstance(tone, (int, float)) else None)

        if link:
            lines.append(f"**{shown + 1}. [{truncate_text(title, 100)}]({link})**")
        else:
            lines.append(f"**{shown + 1}. {truncate_text(title, 100)}**")
        lines.append(f"출처: `{source}` | 감성: `{tone_str}` ({tone_lbl})\n")
        shown += 1

    return lines


def _build_news_section(items: List[Dict[str, Any]]) -> List[str]:
    """Build the Google News geopolitical section."""
    if not items:
        return []

    lines = []
    theme_counter: Counter = Counter()
    rows = []

    for item in items[:15]:
        title = item.get("title", "")
        if not title:
            continue
        link = item.get("link", "")
        source = item.get("source", "")
        theme = _classify_geo_theme(title)
        risk = _risk_level_from_theme(theme)
        theme_counter[theme] += 1

        title_cell = (
            markdown_link(f"**{truncate_text(title, 80)}**", link) if link else f"**{truncate_text(title, 80)}**"
        )
        rows.append((title_cell, theme, risk, source))

    if rows:
        lines.append(
            markdown_table(
                ["주요 기사", "테마", "리스크", "출처"],
                rows,
                aligns=["left", "center", "center", "left"],
            )
        )

    # Theme distribution
    if theme_counter:
        theme_str = ", ".join(f"**{t}**({c}건)" for t, c in theme_counter.most_common(4))
        lines.append(f"\n**테마 분포**: {theme_str}\n")

    return lines


def _generate_risk_analysis(
    markets: List[Dict[str, Any]],
    gdelt_articles: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
    today: str,
) -> List[str]:
    """Generate the risk analysis summary section."""
    lines = []

    # Overall theme analysis
    theme_counter: Counter = Counter()
    for item in news_items:
        theme = _classify_geo_theme(item.get("title", ""))
        theme_counter[theme] += 1
    for article in gdelt_articles:
        theme = _classify_geo_theme(article.get("title", ""))
        theme_counter[theme] += 1

    # Risk score
    risk_score = (
        theme_counter.get("군사/분쟁", 0) * 4
        + theme_counter.get("핵/WMD", 0) * 5
        + theme_counter.get("제재/경제압박", 0) * 3
        + theme_counter.get("무역/공급망", 0) * 2
        + theme_counter.get("에너지/자원", 0) * 2
        + theme_counter.get("선거/정치", 0) * 1
    )

    if risk_score > 40:
        overall_risk = "매우 높음"
        risk_note = (
            "지정학적 긴장이 극도로 고조된 상태입니다. 안전자산(금·달러·미국채) 비중 확대와 위험자산 축소가 권장됩니다."
        )
    elif risk_score > 20:
        overall_risk = "높음"
        risk_note = "복수의 지정학적 리스크 요인이 동시에 활성화되어 있습니다. 방산·에너지·귀금속 섹터를 주목하세요."
    elif risk_score > 10:
        overall_risk = "보통"
        risk_note = "지정학적 이슈가 산발적으로 발생 중입니다. 에너지 가격과 원자재 시장 변동성에 유의하세요."
    elif risk_score > 3:
        overall_risk = "낮음"
        risk_note = "지정학적 긴장은 제한적이나 돌발 이벤트 가능성은 상존합니다."
    else:
        overall_risk = "안정"
        risk_note = "글로벌 지정학적 환경이 비교적 안정적입니다."

    lines.append(f"**종합 지정학 리스크 레벨: {overall_risk}** (점수: {risk_score})")
    lines.append(f"\n{risk_note}\n")

    # Top themes
    if theme_counter:
        top_themes = theme_counter.most_common(3)
        theme_str = ", ".join(f"**{t}**({c}건)" for t, c in top_themes)
        lines.append(f"**핵심 테마**: {theme_str}")

    # Polymarket signal
    if markets:
        top_market = markets[0]
        lines.append(
            f"\n**예측 시장 신호**: 가장 활발한 이벤트는 "
            f'*"{truncate_text(top_market.get("title", ""), 80)}"* '
            f"({top_market.get('probability', 'N/A')})입니다."
        )

    # GDELT tone signal
    tones = [a.get("tone", 0.0) for a in gdelt_articles if isinstance(a.get("tone"), (int, float))]
    if tones:
        avg_tone = sum(tones) / len(tones)
        lines.append(
            f"\n**GDELT 글로벌 뉴스 감성**: 평균 {avg_tone:.2f} ({_tone_label(avg_tone)}) "
            f"— {'부정적 보도 우세, 리스크 프리미엄 상승 가능성' if avg_tone < -2 else '중립적 보도 기조 유지 중'}."
        )

    # Investment implications
    lines.append("\n**투자 시사점**:")
    high_risk_themes = [t for t in theme_counter if _risk_level_from_theme(t) == "높음" and theme_counter[t] > 0]
    if "군사/분쟁" in high_risk_themes or "핵/WMD" in high_risk_themes:
        lines.append("- 방산·사이버보안 섹터 주목")
        lines.append("- 금·달러·엔화 등 안전자산 비중 점검")
    if "에너지/자원" in theme_counter or "제재/경제압박" in theme_counter:
        lines.append("- WTI/Brent 원유 가격 및 에너지 ETF 변동성 모니터링")
    if "무역/공급망" in theme_counter:
        lines.append("- 글로벌 공급망 관련 섹터(반도체·물류·원자재) 리스크 점검")
    if "선거/정치" in theme_counter:
        lines.append("- 이벤트 드리븐 전략 적합 — 선거 결과에 따른 섹터 로테이션 준비")

    lines.append(
        "\n> *본 리포트는 Polymarket, GDELT, Google News에서 자동 수집된 데이터를 기반으로 합니다. "
        "투자 조언이 아니며, 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )

    return lines


def main() -> None:
    """Main collection routine for geopolitical risk data."""
    logger.info("=== Starting geopolitical risk data collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("geopolitical_seen.json")
    generator = PostGenerator("worldmonitor")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)
    post_title = f"지정학 리스크 리포트 - {today}"

    # Skip if already generated today
    if dedup.is_duplicate_exact(post_title, "geopolitical", today):
        logger.info("Geopolitical report already exists for today, skipping")
        log_collection_summary(
            logger,
            collector="collect_geopolitical",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "duplicate"},
        )
        dedup.save()
        return

    # Collect from all sources (continue if any fail)
    markets: List[Dict[str, Any]] = []
    gdelt_articles: List[Dict[str, Any]] = []
    google_news_items: List[Dict[str, Any]] = []

    try:
        markets = fetch_polymarket(limit=15)
    except Exception as e:
        logger.warning("Polymarket collection failed entirely: %s", e)

    try:
        gdelt_articles = fetch_gdelt(limit=30)
    except Exception as e:
        logger.warning("GDELT collection failed entirely: %s", e)

    try:
        google_news_items = fetch_google_news_geopolitical()
    except Exception as e:
        logger.warning("Google News collection failed entirely: %s", e)

    # Enrich Google News items for descriptions
    if google_news_items:
        enrich_items(google_news_items, _GEO_SOURCE_CONTEXT, fetch_url=False)

    # Count total items across sources
    total_items = len(markets) + len(gdelt_articles) + len(google_news_items)

    if total_items < 3:
        logger.warning(
            "Insufficient data collected (%d items total), skipping post generation",
            total_items,
        )
        log_collection_summary(
            logger,
            collector="collect_geopolitical",
            source_count=3,
            unique_items=total_items,
            post_created=0,
            started_at=started_at,
            extras={"status": "insufficient_data", "total_items": total_items},
        )
        dedup.save()
        return

    logger.info(
        "Collected: Polymarket=%d, GDELT=%d, GoogleNews=%d",
        len(markets),
        len(gdelt_articles),
        len(google_news_items),
    )

    # Build post content
    content_parts: List[str] = []

    # Header summary
    source_count = sum(
        [
            1 if markets else 0,
            1 if gdelt_articles else 0,
            1 if google_news_items else 0,
        ]
    )
    content_parts.append(
        f"**{today}** 기준 지정학적 리스크 데이터를 {source_count}개 소스에서 수집·분석했습니다. "
        f"예측 시장 {len(markets)}건, 글로벌 뉴스 분석 {len(gdelt_articles)}건, "
        f"뉴스 {len(google_news_items)}건을 종합합니다.\n"
    )

    # Alert box
    theme_counter: Counter = Counter()
    for item in google_news_items + gdelt_articles:
        theme = _classify_geo_theme(item.get("title", ""))
        theme_counter[theme] += 1

    top_theme = theme_counter.most_common(1)[0][0] if theme_counter else "N/A"
    content_parts.extend(
        [
            '<div class="alert-box alert-warning"><strong>지정학 리스크 스냅샷</strong><ul>',
            f"<li>Polymarket 예측 시장: <strong>{len(markets)}건</strong></li>",
            f"<li>GDELT 글로벌 뉴스: <strong>{len(gdelt_articles)}건</strong></li>",
            f"<li>뉴스 기사: <strong>{len(google_news_items)}건</strong></li>",
            f"<li>주요 테마: <strong>{top_theme}</strong></li>",
            "</ul></div>\n",
        ]
    )

    # Section 1: Polymarket prediction markets
    content_parts.append("## 1. 예측 시장 동향 (Polymarket)\n")
    content_parts.append(
        "글로벌 예측 시장 Polymarket에서 지정학·정치 이벤트에 대한 집단지성 확률을 확인합니다. "
        "거래량이 많을수록 시장 참여자의 신뢰도가 높습니다.\n"
    )
    content_parts.extend(_build_polymarket_section(markets))

    # Section 2: GDELT geopolitical news
    content_parts.append("## 2. 주요 지정학 뉴스 (GDELT)\n")
    content_parts.append(
        "GDELT(글로벌 사건·언어·음색 데이터베이스)에서 최신 지정학 관련 기사와 "
        "감성 분석 점수를 제공합니다. 음수 톤은 부정적 보도를 의미합니다.\n"
    )
    content_parts.extend(_build_gdelt_section(gdelt_articles))

    # Section 3: Google News (geopolitical investment news)
    content_parts.append("## 3. 투자 관점 지정학 뉴스 (Google News)\n")
    content_parts.append("투자자 관점에서 주목해야 할 지정학 리스크 뉴스를 수집·분류했습니다.\n")
    content_parts.extend(_build_news_section(google_news_items))

    # Section 4: Risk analysis
    content_parts.append("## 4. 리스크 분석\n")
    content_parts.extend(_generate_risk_analysis(markets, gdelt_articles, google_news_items, today))

    # References
    all_link_items = [item for item in (google_news_items + gdelt_articles) if item.get("link")]
    if all_link_items:
        content_parts.append("\n---\n")
        content_parts.append(
            html_reference_details(
                "참고 링크",
                all_link_items,
                limit=15,
                title_max_len=80,
            )
        )

    # Footer
    content_parts.extend(
        [
            "\n---",
            f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC",
            "**데이터 소스**: Polymarket (gamma-api.polymarket.com), GDELT Project, Google News RSS",
        ]
    )

    content = "\n".join(content_parts)

    # Generate briefing image
    briefing_image = ""
    try:
        from common.image_generator import generate_news_briefing_card

        card_themes = []
        for theme_name, count in theme_counter.most_common(5):
            theme_emojis = {
                "군사/분쟁": "⚔️",
                "핵/WMD": "☢️",
                "제재/경제압박": "🚫",
                "선거/정치": "🗳️",
                "무역/공급망": "🔗",
                "에너지/자원": "⛽",
                "외교/협상": "🤝",
                "기타 지정학": "🌍",
            }
            card_themes.append(
                {
                    "name": theme_name,
                    "emoji": theme_emojis.get(theme_name, "🌍"),
                    "count": count,
                    "keywords": [],
                }
            )

        if card_themes:
            img = generate_news_briefing_card(
                card_themes,
                today,
                category="Geopolitical Risk Report",
                total_count=total_items,
                filename=f"news-briefing-geopolitical-{today}.png",
            )
            if img:
                briefing_image = img
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts_with_img = content.split("## 1.")
                if len(content_parts_with_img) > 1:
                    content = (
                        content_parts_with_img[0]
                        + f"\n![geopolitical-briefing]({web_path})\n\n## 1."
                        + content_parts_with_img[1]
                    )
                logger.info("Generated geopolitical briefing card: %s", img)
    except ImportError as e:
        logger.debug("Optional dependency unavailable: %s", e)
    except Exception as e:
        logger.warning("Geopolitical briefing card generation failed: %s", e)

    # Create post
    filepath = generator.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["geopolitical", "polymarket", "risk", "conflict", "prediction-market"],
        source="geopolitical",
        lang="ko",
        image=briefing_image or "",
        slug="daily-geopolitical-risk-report",
    )

    created_count = 0
    if filepath:
        dedup.mark_seen(post_title, "geopolitical", today)
        created_count = 1
        logger.info("Created geopolitical risk report: %s", filepath)
    else:
        logger.warning("Failed to create geopolitical risk report post")

    dedup.save()

    unique_items = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in (markets + gdelt_articles + google_news_items)
            if item.get("title")
        }
    )
    source_names = set()
    if markets:
        source_names.add("Polymarket")
    if gdelt_articles:
        source_names.add("GDELT")
    if google_news_items:
        source_names.add("Google News")

    log_collection_summary(
        logger,
        collector="collect_geopolitical",
        source_count=len(source_names),
        unique_items=unique_items,
        post_created=created_count,
        started_at=started_at,
    )
    logger.info("=== Geopolitical risk collection complete: %d posts created ===", created_count)


if __name__ == "__main__":
    main()
