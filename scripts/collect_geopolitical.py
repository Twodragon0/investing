#!/usr/bin/env python3
"""Collect geopolitical risk data from free public APIs for investment analysis.

Sources:
- Polymarket API (public, no auth): prediction markets on geopolitics/elections/conflicts
- GDELT API (free, public): global news event database with tone analysis
- Google News RSS (English + Korean): geopolitical risk investment news
"""

import logging
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import requests

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.base_collector import BaseCollector
from common.collector_config import get_collector_config, get_limit, get_threshold, get_url
from common.config import (
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from common.dedup import deduplicate_by_url
from common.enrichment import enrich_items
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
    markdown_link,
    markdown_table,
)
from common.post_generator import build_dated_permalink
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.utils import request_with_retry, sanitize_string, truncate_text

_log = logging.getLogger(__name__)

# collectors.yml에서 설정 로드
_geo_cfg = get_collector_config("geopolitical")

_GEO_SOURCE_CONTEXT: Dict[str, Dict[str, Any]] = {
    "polymarket.com": {"name": "Polymarket", "tags": ["prediction-market"]},
    "gdeltproject.org": {"name": "GDELT", "tags": ["geopolitical", "data"]},
}

# Minimum volume (USD) for Polymarket markets to include
_POLYMARKET_MIN_VOLUME = get_threshold("geopolitical", "polymarket_min_volume", 10_000)

# Geopolitical keywords to filter Polymarket markets
_POLYMARKET_GEO_TAGS = [
    "geopolitics",
    "politics",
    "elections",
    "ukraine",
    "middle-east",
    "nato",
    "economics",
    "finance",
    "crypto",
    "china",
    "iran",
    "trade",
]

# GDELT API query for geopolitical risk events
_GDELT_QUERY = _geo_cfg.get(
    "gdelt_query", "geopolitical+risk+OR+military+conflict+OR+sanctions+OR+war+OR+coup+OR+nuclear"
)


def fetch_polymarket(limit: Optional[int] = None, verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """Fetch active prediction markets related to geopolitics from Polymarket.

    Uses the public gamma-api.polymarket.com endpoint (no auth required).
    Filters for markets with volume > _POLYMARKET_MIN_VOLUME.
    """
    if limit is None:
        limit = get_limit("geopolitical", "polymarket_markets", 20)
    items: List[Dict[str, Any]] = []

    for tag in _POLYMARKET_GEO_TAGS:
        if len(items) >= limit:
            break
        url = get_url("geopolitical", "polymarket_api", "https://gamma-api.polymarket.com/markets")
        params = {
            "tag": tag,
            "active": "true",
            "closed": "false",
            "limit": get_limit("geopolitical", "polymarket_per_tag", 50),
        }
        try:
            resp = request_with_retry(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                verify_ssl=verify_ssl,
                headers={"User-Agent": USER_AGENT},
            )
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

        except requests.exceptions.RequestException as e:
            _log.warning("Polymarket request failed for tag '%s': %s", tag, e)
        except (ValueError, KeyError) as e:
            _log.warning("Polymarket parse error for tag '%s': %s", tag, e)

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
    """Parse outcome prices into a readable probability string.

    For binary markets (Yes/No), show the dominant outcome with percentage.
    For multi-outcome, show top 2 outcomes.
    """
    if not outcomes or not prices:
        return "N/A"

    parsed = []
    for i, outcome in enumerate(outcomes[:4]):
        if i < len(prices):
            prob = _parse_float(prices[i])
            if prob is not None:
                if prob > 1:
                    prob = prob / 100
                label = str(outcome).strip()
                parsed.append((label, prob))

    if not parsed:
        return "N/A"

    # Binary market: show dominant side clearly
    if len(parsed) == 2 and {p[0].lower() for p in parsed} <= {"yes", "no"}:
        yes_prob = next((p for lbl, p in parsed if lbl.lower() == "yes"), 0)
        if yes_prob >= 0.5:
            return f"🟢 Yes {yes_prob:.0%}"
        return f"🔴 No {1 - yes_prob:.0%}"

    # Multi-outcome: show top 2
    parsed.sort(key=lambda x: x[1], reverse=True)
    parts = [f"{label} {prob:.0%}" for label, prob in parsed[:2]]
    return " / ".join(parts)


def fetch_gdelt(limit: int = 30, verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """Fetch recent geopolitical news from GDELT API with tone analysis.

    Uses the free GDELT DOC 2.0 API (no auth required).
    Returns articles with tone sentiment scores.
    """
    url = get_url("geopolitical", "gdelt_api", "https://api.gdeltproject.org/api/v2/doc/doc")
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
        resp = request_with_retry(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify_ssl=verify_ssl,
            headers={"User-Agent": USER_AGENT},
        )
        data = resp.json()
        articles = data.get("articles", [])
        if not isinstance(articles, list):
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

    except requests.exceptions.RequestException as e:
        _log.warning("GDELT request failed: %s", e)
    except (ValueError, KeyError) as e:
        _log.warning("GDELT parse error: %s", e)

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
            get_url(
                "geopolitical",
                "google_news_geo_en",
                "https://news.google.com/rss/search?q=geopolitical+risk+investment&hl=en&gl=US&ceid=US:en",
            ),
            "Google News EN (Geopolitical)",
            ["geopolitical", "risk", "english"],
        ),
        (
            get_url(
                "geopolitical",
                "google_news_conflict",
                "https://news.google.com/rss/search?q=military+conflict+sanctions+war&hl=en&gl=US&ceid=US:en",
            ),
            "Google News EN (Conflict)",
            ["geopolitical", "conflict", "english"],
        ),
        (
            get_url(
                "geopolitical",
                "google_news_geo_kr",
                "https://news.google.com/rss/search?q=%EC%A7%80%EC%A0%95%ED%95%99+%EB%A6%AC%EC%8A%A4%ED%81%AC+%ED%88%AC%EC%9E%90&hl=ko&gl=KR&ceid=KR:ko",
            ),
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


def _build_polymarket_section(markets: List[Dict[str, Any]]) -> tuple:
    """Build the Polymarket prediction market section of the post.

    Returns (lines, filtered_markets) tuple.
    """
    if not markets:
        return [], []

    # Filter out entertainment/sports/gaming markets — only keep geopolitical/financial
    _GEO_KEYWORDS = {
        "war",
        "conflict",
        "election",
        "president",
        "congress",
        "senate",
        "sanction",
        "tariff",
        "trade",
        "nuclear",
        "military",
        "nato",
        "china",
        "russia",
        "iran",
        "israel",
        "ukraine",
        "taiwan",
        "fed",
        "rate",
        "inflation",
        "recession",
        "gdp",
        "economy",
        "oil",
        "energy",
        "opec",
        "bitcoin",
        "crypto",
        "regulation",
        "trump",
        "biden",
        "政",
        "전쟁",
        "제재",
        "선거",
        "금리",
    }
    # Exclude sports/entertainment markets explicitly
    _SPORTS_KEYWORDS = {
        "nhl",
        "nba",
        "nfl",
        "mlb",
        "mls",
        "ufc",
        "fifa",
        "premier league",
        "stanley cup",
        "super bowl",
        "world series",
        "champions league",
        "playoffs",
        "mvp",
        "ballon d'or",
        "oscar",
        "grammy",
        "emmy",
        "bachelor",
        "bachelorette",
        "survivor",
        "gta vi",
        "gta 6",
        "formula 1",
        "f1",
        "grand prix",
        "wimbledon",
        "olympics",
    }
    _ENTERTAINMENT_KEYWORDS = _SPORTS_KEYWORDS | {
        "gta vi",
        "gta 6",
        "jesus christ",
        "netflix",
        "spotify",
        "movie",
        "album",
        "tv show",
        "reality tv",
        "celebrity",
    }
    non_entertainment = [
        m for m in markets if not any(kw in m.get("title", "").lower() for kw in _ENTERTAINMENT_KEYWORDS)
    ]
    filtered_markets = [m for m in non_entertainment if any(kw in m.get("title", "").lower() for kw in _GEO_KEYWORDS)]
    # Fall back to non-entertainment if available, otherwise full market list as last resort
    if len(filtered_markets) < 3:
        filtered_markets = non_entertainment if non_entertainment else markets

    lines = []
    rows = []
    for i, market in enumerate(filtered_markets[:10], 1):
        question = truncate_text(market.get("title", ""), 80)
        link = market.get("link", "")
        probability = market.get("probability", "N/A")
        volume = market.get("volume", 0)
        volume_str = f"${volume:,.0f}" if volume else "N/A"

        question_cell = markdown_link(f"**{question}**", link) if link else f"**{question}**"
        rows.append((i, question_cell, probability, volume_str))

    if rows:
        lines.append(
            markdown_table(
                ["#", "이벤트 질문", "예측 확률", "거래량"],
                rows,
                aligns=["center", "left", "center", "right"],
            )
        )
    else:
        lines.append("현재 지정학 관련 활성 예측 마켓이 없습니다.\n")

    # Summary stats as stat-grid (cleaner than blockquote table)
    # Keep displayed stats aligned to the same filtered market set shown in table.
    total_volume = sum(m.get("volume", 0) for m in filtered_markets)
    lines.append(
        '\n<div class="stat-grid">'
        f'<div class="stat-item"><span class="stat-value">{len(filtered_markets)}</span>'
        f'<span class="stat-label">분석 대상</span></div>'
        f'<div class="stat-item"><span class="stat-value">${total_volume:,.0f}</span>'
        f'<span class="stat-label">합산 거래량</span></div>'
        f'<div class="stat-item"><span class="stat-value">'
        f'<a href="https://polymarket.com" target="_blank" rel="noopener noreferrer">Polymarket</a></span>'
        f'<span class="stat-label">출처</span></div>'
        "</div>\n"
    )

    return lines, filtered_markets


def _build_gdelt_section(articles: List[Dict[str, Any]]) -> List[str]:
    """Build the GDELT news section with tone analysis."""
    if not articles:
        return ["현재 GDELT에서 수집된 지정학 뉴스가 없습니다.\n"]

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
        lines.append(f"{html_source_tag(source)} | 감성: `{tone_str}` ({tone_lbl})\n")
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


class GeopoliticalCollector(BaseCollector):
    """지정학 리스크 수집기.

    Polymarket, GDELT, Google News에서 지정학 리스크 데이터를
    수집하고 종합 리포트를 생성합니다.
    """

    name = "geopolitical"
    category = "worldmonitor"
    state_file = "geopolitical_seen.json"

    def fetch(self) -> List[Dict[str, Any]]:
        """모든 소스에서 지정학 데이터를 수집합니다."""
        # Collect from all sources (continue if any fail)
        markets: List[Dict[str, Any]] = []
        gdelt_articles: List[Dict[str, Any]] = []
        google_news_items: List[Dict[str, Any]] = []

        try:
            markets = fetch_polymarket(limit=15, verify_ssl=self.verify_ssl)
        except Exception as e:
            self.logger.warning("Polymarket collection failed entirely: %s", e)

        try:
            gdelt_articles = fetch_gdelt(limit=30, verify_ssl=self.verify_ssl)
        except Exception as e:
            self.logger.warning("GDELT collection failed entirely: %s", e)

        try:
            google_news_items = fetch_google_news_geopolitical()
        except Exception as e:
            self.logger.warning("Google News collection failed entirely: %s", e)

        # Enrich Google News items for descriptions
        if google_news_items:
            enrich_items(google_news_items, _GEO_SOURCE_CONTEXT, fetch_url=False)
            google_news_items = deduplicate_by_url(google_news_items)

        # Tag items by source for later retrieval
        for m in markets:
            m["_geo_source"] = "polymarket"
        for a in gdelt_articles:
            a["_geo_source"] = "gdelt"
        for n in google_news_items:
            n["_geo_source"] = "google_news"

        return markets + gdelt_articles + google_news_items

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """수집된 항목을 그대로 반환합니다 (소스별 처리는 run()에서)."""
        return items

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """지정학 리스크 리포트 본문을 생성합니다."""
        # Split items back by source
        markets = [i for i in items if i.get("_geo_source") == "polymarket"]
        gdelt_articles = [i for i in items if i.get("_geo_source") == "gdelt"]
        google_news_items = [i for i in items if i.get("_geo_source") == "google_news"]
        return self._build_full_content(markets, gdelt_articles, google_news_items)

    def build_title(self, items: List[Dict[str, Any]]) -> str:
        """포스트 제목을 생성합니다."""
        return f"지정학 리스크 리포트 - {self.today}"

    def default_tags(self) -> List[str]:
        """기본 태그 목록을 반환합니다."""
        return ["geopolitical", "polymarket", "risk", "conflict", "prediction-market"]

    def run(self) -> None:
        """메인 실행 파이프라인 — 다중 소스 수집 후 리포트 생성."""
        self.logger.info("=== Starting geopolitical risk data collection ===")
        self._started_at = time.monotonic()

        post_title = self.build_title([])

        # Skip if already generated today
        if self.is_duplicate_exact(post_title, "geopolitical"):
            self.logger.info("Geopolitical report already exists for today, skipping")
            self.save_state()
            self.log_summary([], extras={"status": "duplicate"})
            return

        # Fetch all items
        all_items = self.fetch()

        # Split by source
        markets = [i for i in all_items if i.get("_geo_source") == "polymarket"]
        gdelt_articles = [i for i in all_items if i.get("_geo_source") == "gdelt"]
        google_news_items = [i for i in all_items if i.get("_geo_source") == "google_news"]

        total_items = len(all_items)

        if total_items < 3:
            self.logger.warning(
                "Insufficient data collected (%d items total), skipping post generation",
                total_items,
            )
            self.save_state()
            self.log_summary(
                all_items,
                extras={"status": "insufficient_data", "total_items": total_items},
            )
            return

        self.logger.info(
            "Collected: Polymarket=%d, GDELT=%d, GoogleNews=%d",
            len(markets),
            len(gdelt_articles),
            len(google_news_items),
        )

        # Build content
        content = self._build_full_content(markets, gdelt_articles, google_news_items)

        # Generate briefing image
        briefing_image = ""
        theme_counter: Counter = Counter()
        for item in google_news_items + gdelt_articles:
            theme = _classify_geo_theme(item.get("title", ""))
            theme_counter[theme] += 1

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
                    self.today,
                    category="Geopolitical Risk Report",
                    total_count=total_items,
                    filename=f"news-briefing-geopolitical-{self.today}.png",
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
                    self.logger.info("Generated geopolitical briefing card: %s", img)
        except ImportError as e:
            self.logger.debug("Optional dependency unavailable: %s", e)
        except Exception as e:
            self.logger.warning("Geopolitical briefing card generation failed: %s", e)

        _top_geo_themes = [t[0] for t in theme_counter.most_common(3)] if theme_counter else []
        _desc_ko = f"지정학적 리스크 {total_items}건 수집. "
        if _top_geo_themes:
            _desc_ko += f"주요 테마: {', '.join(_top_geo_themes)}. "
        source_count = sum(
            [
                1 if markets else 0,
                1 if gdelt_articles else 0,
                1 if google_news_items else 0,
            ]
        )
        _desc_ko += f"Polymarket·GDELT·뉴스 {source_count}개 소스에서 분쟁·제재·무역 리스크를 분석합니다."

        # Create post
        filepath = self.create_post(
            title=post_title,
            content=content,
            tags=self.default_tags(),
            source="geopolitical",
            image=briefing_image or "",
            extra_frontmatter={
                "permalink": build_dated_permalink("market-analysis", self.today, "daily-geopolitical-risk-report"),
                "description_ko": _desc_ko,
            },
            slug="daily-geopolitical-risk-report",
        )

        if filepath:
            self.mark_seen(post_title, "geopolitical")
            self.logger.info("Created geopolitical risk report: %s", filepath)
        else:
            self.logger.warning("Failed to create geopolitical risk report post")

        self.save_state()
        self.log_summary(all_items)
        self.logger.info("=== Geopolitical risk collection complete: %d posts created ===", self._created_count)

    def _build_full_content(
        self,
        markets: List[Dict[str, Any]],
        gdelt_articles: List[Dict[str, Any]],
        google_news_items: List[Dict[str, Any]],
    ) -> str:
        """지정학 리스크 리포트 전체 본문을 생성합니다."""
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
            f"**{self.today}** 기준 지정학적 리스크 데이터를 {source_count}개 소스에서 수집·분석했습니다. "
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

        # Stat grid - source counts at a glance
        content_parts.append('<div class="stat-grid">')
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{len(markets)}</span>'
            '<span class="stat-label">Polymarket</span></div>'
        )
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{len(gdelt_articles)}</span>'
            '<span class="stat-label">GDELT 뉴스</span></div>'
        )
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{len(google_news_items)}</span>'
            '<span class="stat-label">뉴스 기사</span></div>'
        )
        content_parts.append(
            f'<div class="stat-item"><span class="stat-value">{source_count}</span>'
            '<span class="stat-label">데이터 소스</span></div>'
        )
        content_parts.append("</div>\n")

        # Section 1: Polymarket prediction markets
        content_parts.append("## 1. 예측 시장 동향 (Polymarket)\n")
        content_parts.append(
            "글로벌 예측 시장 Polymarket에서 지정학·정치 이벤트에 대한 집단지성 확률을 확인합니다. "
            "거래량이 많을수록 시장 참여자의 신뢰도가 높습니다.\n"
        )
        polymarket_lines, polymarket_filtered = _build_polymarket_section(markets)
        content_parts.extend(polymarket_lines)

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
        content_parts.extend(
            _generate_risk_analysis(polymarket_filtered, gdelt_articles, google_news_items, self.today)
        )

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
        content_parts.append(
            '\n<div class="wm-footer-meta">'
            f"<span>수집 시각: {self.now.strftime('%Y-%m-%d %H:%M')} KST</span>"
            "<span>소스: Polymarket, GDELT Project, Google News RSS</span>"
            "</div>"
        )

        return "\n".join(content_parts)


def main() -> None:
    """Main collection routine for geopolitical risk data."""
    collector = GeopoliticalCollector()
    collector.run()


if __name__ == "__main__":
    main()
