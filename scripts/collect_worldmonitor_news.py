#!/usr/bin/env python3
"""Collect worldmonitor-curated RSS feeds and generate a daily briefing post."""

import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import REQUEST_TIMEOUT, USER_AGENT, get_ssl_verify, setup_logging
from common.dedup import DedupEngine
from common.markdown_utils import (
    escape_table_cell,
    html_source_tag,
    html_text,
    markdown_link,
    markdown_table,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.worldmonitor_utils import worldmonitor_sort_key

logger = setup_logging("collect_worldmonitor_news")

WM_PROXY = "https://worldmonitor.app/api/rss-proxy?url="
WM_FINANCE_BASE = "https://finance.worldmonitor.app"
WM_MAP_VIEW_URL = (
    "https://finance.worldmonitor.app/?lat=20.0000&lon=0.0000&zoom=1.00&"
    "view=global&timeRange=7d&layers=conflicts%2Cbases%2Chotspots%2C"
    "nuclear%2Csanctions%2Cweather%2Ceconomic%2Cwaterways%2Coutages%2C"
    "military%2Cnatural"
)


def classify_theme(title: str) -> str:
    text = title.lower()
    if any(
        key in text
        for key in [
            "iran",
            "war",
            "military",
            "nuclear",
            "ukraine",
            "israel",
            "syria",
            "prisoner",
            "sanction",
        ]
    ):
        return "지정학/안보"
    if any(key in text for key in ["oil", "opec", "lng", "pipeline", "energy", "gas"]):
        return "에너지"
    if any(
        key in text
        for key in [
            "market",
            "stock",
            "bond",
            "inflation",
            "rate",
            "economy",
            "earnings",
            "etf",
        ]
    ):
        return "금융시장"
    if any(
        key in text
        for key in [
            "court",
            "judge",
            "law",
            "minister",
            "election",
            "administration",
            "policy",
        ]
    ):
        return "정책/법률"
    return "사회/기타"


def impact_label(theme: str) -> str:
    if theme == "지정학/안보":
        return "높음"
    if theme in {"에너지", "금융시장"}:
        return "중간"
    if theme == "정책/법률":
        return "중간"
    return "낮음"


def wm_url(source_url: str) -> str:
    return WM_PROXY + quote(source_url, safe="")


def _post_worldmonitor(path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{WM_FINANCE_BASE}{path}"
    try:
        resp = requests.post(
            url,
            json=payload or {},
            timeout=REQUEST_TIMEOUT,
            verify=get_ssl_verify(),
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning("WorldMonitor API failed (%s): %s", path, e)
        return {}


def _paginate_worldmonitor(
    path: str,
    payload: Dict[str, Any],
    list_key: str,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    cursor = ""
    while len(items) < limit:
        page_size = min(100, limit - len(items))
        payload["pagination"] = {"pageSize": page_size, "cursor": cursor}
        data = _post_worldmonitor(path, payload)
        batch = data.get(list_key, []) or []
        if not isinstance(batch, list):
            break
        items.extend(batch)
        cursor = (data.get("pagination") or {}).get("nextCursor", "")
        if not cursor:
            break
    return items


def _top_counts(items: List[Dict[str, Any]], key: str, limit: int = 3) -> str:
    counter = Counter(item.get(key) for item in items if isinstance(item, dict) and item.get(key))
    if not counter:
        return "N/A"
    return ", ".join(f"{name} {count}건" for name, count in counter.most_common(limit))


def _format_float(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{value:.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def fetch_worldmonitor_map_snapshot(days: int = 7) -> Dict[str, Any]:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    time_range = {
        "start": int(start.timestamp() * 1000),
        "end": int(now.timestamp() * 1000),
    }

    conflicts_acled = _paginate_worldmonitor(
        "/api/conflict/v1/list-acled-events",
        {"timeRange": time_range},
        "events",
        limit=200,
    )
    conflicts_ucdp = _paginate_worldmonitor(
        "/api/conflict/v1/list-ucdp-events",
        {"timeRange": time_range},
        "events",
        limit=200,
    )

    outages = _paginate_worldmonitor(
        "/api/infrastructure/v1/list-internet-outages",
        {"timeRange": time_range},
        "outages",
        limit=200,
    )

    earthquakes = _paginate_worldmonitor(
        "/api/seismology/v1/list-earthquakes",
        {"timeRange": time_range, "minMagnitude": 4.5},
        "earthquakes",
        limit=200,
    )

    climate = _paginate_worldmonitor(
        "/api/climate/v1/list-climate-anomalies",
        {"minSeverity": "ANOMALY_SEVERITY_MODERATE"},
        "anomalies",
        limit=200,
    )

    nav_warnings = _paginate_worldmonitor(
        "/api/maritime/v1/list-navigational-warnings",
        {},
        "warnings",
        limit=200,
    )

    vessel_snapshot = _post_worldmonitor("/api/maritime/v1/get-vessel-snapshot")
    snapshot = vessel_snapshot.get("snapshot", {}) if isinstance(vessel_snapshot, dict) else {}
    disruptions = snapshot.get("disruptions", []) if isinstance(snapshot, dict) else []
    density_zones = snapshot.get("densityZones", []) if isinstance(snapshot, dict) else []

    military = _post_worldmonitor(
        "/api/military/v1/list-military-flights",
        {"pagination": {"pageSize": 100, "cursor": ""}},
    )
    flights = military.get("flights", []) if isinstance(military, dict) else []
    clusters = military.get("clusters", []) if isinstance(military, dict) else []

    macro = _post_worldmonitor("/api/economic/v1/get-macro-signals")
    energy = _post_worldmonitor("/api/economic/v1/get-energy-prices")

    return {
        "time_range": time_range,
        "conflicts": {
            "acled": conflicts_acled,
            "ucdp": conflicts_ucdp,
        },
        "outages": outages,
        "earthquakes": earthquakes,
        "climate": climate,
        "nav_warnings": nav_warnings,
        "disruptions": disruptions,
        "density_zones": density_zones,
        "military_flights": flights,
        "military_clusters": clusters,
        "macro": macro,
        "energy": energy,
        "generated_at": now,
    }


def build_map_snapshot_section(snapshot: Dict[str, Any]) -> List[str]:
    if not snapshot:
        return []

    conflicts = snapshot.get("conflicts", {}) or {}
    acled = conflicts.get("acled", []) or []
    ucdp = conflicts.get("ucdp", []) or []
    outages = snapshot.get("outages", []) or []
    earthquakes = snapshot.get("earthquakes", []) or []
    climate = snapshot.get("climate", []) or []
    nav_warnings = snapshot.get("nav_warnings", []) or []
    disruptions = snapshot.get("disruptions", []) or []
    density_zones = snapshot.get("density_zones", []) or []
    flights = snapshot.get("military_flights", []) or []
    clusters = snapshot.get("military_clusters", []) or []

    macro = snapshot.get("macro", {}) or {}
    energy = snapshot.get("energy", {}) or {}

    # Skip the section entirely when all intelligence data is empty/zero
    energy_prices = energy.get("prices", []) if isinstance(energy, dict) else []
    has_data = any(
        [
            acled,
            ucdp,
            outages,
            earthquakes,
            climate,
            nav_warnings,
            disruptions,
            density_zones,
            flights,
            clusters,
            energy_prices,
            macro.get("verdict") if isinstance(macro, dict) else None,
        ]
    )
    if not has_data:
        return []

    top_conflict_countries = _top_counts(acled + ucdp, "country")
    top_outage_countries = _top_counts(outages, "country")
    top_climate_zones = _top_counts(climate, "zone")
    top_nav_areas = _top_counts(nav_warnings, "area")
    top_disruption_regions = _top_counts(disruptions, "region")
    top_density_zones = _top_counts(density_zones, "name")
    top_operators = _top_counts(flights, "operator")

    max_quake: Optional[Dict[str, Any]] = None
    if earthquakes:
        max_quake = max(
            earthquakes,
            key=lambda q: q.get("magnitude") or 0,
        )

    verdict = macro.get("verdict") if isinstance(macro, dict) else None
    bullish = macro.get("bullishCount") if isinstance(macro, dict) else None
    total = macro.get("totalCount") if isinstance(macro, dict) else None

    preferred = {"WTI", "Brent", "Henry Hub"}
    selected_prices = [p for p in energy_prices if any(key in p.get("name", "") for key in preferred)]
    if not selected_prices:
        selected_prices = energy_prices[:3]

    energy_summary = []
    for price in selected_prices:
        name = price.get("name") or price.get("commodity", "Energy")
        value = _format_float(price.get("price"))
        change = price.get("change")
        change_str = _format_float(change, 2)
        unit = price.get("unit", "")
        unit_suffix = f" {unit}" if unit else ""
        energy_summary.append(f"{name} {value}{unit_suffix} ({change_str}%)")

    lines = [
        "## 지도 인텔리전스 스냅샷",
        "",
        f"- 충돌 이벤트: ACLED {len(acled)}건 / UCDP {len(ucdp)}건 (상위 국가: {top_conflict_countries})",
        f"- 군용 항공기 활동: {len(flights)}대, 클러스터 {len(clusters)}개 (주요 운영자: {top_operators})",
        f"- 인터넷 장애: {len(outages)}건 (상위 국가: {top_outage_countries})",
        f"- 기후 이상: {len(climate)}건 (주요 지역: {top_climate_zones})",
        f"- 지진(M4.5+): {len(earthquakes)}건"
        + (f" (최대 {_format_float(max_quake.get('magnitude'))} {max_quake.get('place', '')})" if max_quake else ""),
        f"- 해상 경보: {len(nav_warnings)}건 (주요 해역: {top_nav_areas})",
        f"- 해상/AIS 이상: {len(disruptions)}건 (지역: {top_disruption_regions})",
        f"- 선박 혼잡: {len(density_zones)}개 구역 (상위: {top_density_zones})",
        f"- 매크로 신호: {verdict or 'UNKNOWN'} (Bullish {bullish or 0}/{total or 0})",
    ]

    if energy_summary:
        lines.append(f"- 에너지 가격: {', '.join(energy_summary)}")

    lines.extend(
        [
            "",
            "## 지도 레이어 참고",
            "- 정적 레이어(핫스팟/기지/핵시설/제재국가/경제 중심지)는 WorldMonitor 기준 데이터셋 기반입니다.",
            f"- 상세 지도: {WM_MAP_VIEW_URL}",
        ]
    )

    return lines


def fetch_worldmonitor_feeds() -> List[Dict[str, Any]]:
    feeds = [
        (
            wm_url("https://feeds.bbci.co.uk/news/world/rss.xml"),
            "WorldMonitor/BBC World",
            ["worldmonitor", "geopolitics"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://feeds.bbci.co.uk/news/world/rss.xml",
                    "https://news.google.com/rss/search?q=site:bbc.com+world+news+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url("https://www.theguardian.com/world/rss"),
            "WorldMonitor/Guardian World",
            ["worldmonitor", "geopolitics"],
            15,
            48,
        ),
        (
            wm_url("https://www.aljazeera.com/xml/rss/all.xml"),
            "WorldMonitor/Al Jazeera",
            ["worldmonitor", "middleeast"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://www.aljazeera.com/xml/rss/all.xml",
                    "https://news.google.com/rss/search?q=site:aljazeera.com+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
            "WorldMonitor/CNBC",
            ["worldmonitor", "markets"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
                    "https://news.google.com/rss/search?q=site:cnbc.com+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url("https://feeds.marketwatch.com/marketwatch/topstories/"),
            "WorldMonitor/MarketWatch",
            ["worldmonitor", "markets"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://feeds.marketwatch.com/marketwatch/topstories/",
                    "https://news.google.com/rss/search?q=site:marketwatch.com+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url("https://www.ft.com/rss/home"),
            "WorldMonitor/Financial Times",
            ["worldmonitor", "markets"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://www.ft.com/rss/home",
                    "https://news.google.com/rss/search?q=site:ft.com+markets+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
        (
            wm_url(
                "https://news.google.com/rss/search?q=(oil+price+OR+OPEC+OR+pipeline+OR+LNG)+when:2d&hl=en-US&gl=US&ceid=US:en"
            ),
            "WorldMonitor/Energy",
            ["worldmonitor", "energy"],
            15,
            48,
            {
                "fallback_urls": [
                    "https://news.google.com/rss/search?q=(oil+price+OR+OPEC+OR+pipeline+OR+LNG)+when:2d&hl=en-US&gl=US&ceid=US:en",
                ]
            },
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def _generate_worldmonitor_summary(
    theme_counter: Counter,
    total_items: int,
    top_sources: str,
    issue_items: list,
) -> str:
    """Generate data-driven global intelligence summary."""
    lines = []

    # Geopolitical risk level assessment
    security_count = theme_counter.get("지정학/안보", 0)
    energy_count = theme_counter.get("에너지", 0)
    market_count = theme_counter.get("금융시장", 0)
    policy_count = theme_counter.get("정책/법률", 0)
    risk_score = security_count * 3 + energy_count * 2 + policy_count
    if risk_score > 30:
        risk_level = "높음"
        risk_note = "지정학적 긴장이 고조되어 안전자산(금·달러·미국채) 선호가 강화될 수 있습니다."
    elif risk_score > 15:
        risk_level = "보통"
        risk_note = "안보·에너지 이슈가 산발적으로 발생하고 있어, 관련 섹터 변동성에 유의가 필요합니다."
    elif risk_score > 5:
        risk_level = "낮음"
        risk_note = "지정학적 리스크가 비교적 안정적이나, 돌발 이벤트 가능성은 상존합니다."
    else:
        risk_level = "안정"
        risk_note = "글로벌 안보 환경이 비교적 안정적인 상황입니다."

    lines.append(f"**지정학 리스크 레벨: {risk_level}** — {risk_note}")

    # Theme-based analysis
    top_3_themes = theme_counter.most_common(3)
    if top_3_themes:
        theme_str = ", ".join(f"**{t}**({c}건)" for t, c in top_3_themes)
        lines.append(f"\n핵심 테마는 {theme_str} 중심으로 전개되고 있습니다.")

    # Cross-theme analysis with diverse templates
    _CROSS_THEME_TEMPLATES = [
        (
            "지정학/안보",
            "에너지",
            lambda sc, ec: (
                f"안보 이슈({sc}건)와 에너지 뉴스({ec}건)가 동시 부각되어, "
                "중동·러시아 관련 긴장이 원유 공급망에 직접 영향을 미치는 구간입니다. "
                "WTI·브렌트 가격과 에너지 ETF 변동성을 주시하세요."
            ),
        ),
        (
            "지정학/안보",
            "금융시장",
            lambda sc, mc: (
                f"안보({sc}건)와 금융시장({mc}건) 이슈가 동시 전개되어, "
                "지정학적 리스크가 시장 심리에 직접 전이되고 있습니다. "
                f"{'안보 이슈 비중이 높아, 방산·금·안전자산 중심의 포지셔닝이 유리합니다.' if sc > mc else '금융시장 이슈가 우세하여, 안보 리스크는 제한적 영향에 그칠 수 있습니다.'}"
            ),
        ),
        (
            "에너지",
            "금융시장",
            lambda ec, mc: (
                f"에너지({ec}건)와 금융시장({mc}건) 뉴스가 맞물려, "
                "에너지 가격 변동이 인플레이션 기대와 금리 전망을 흔들 수 있는 구간입니다. "
                "에너지주·유틸리티와 금리 민감 성장주 간 로테이션 신호를 확인하세요."
            ),
        ),
        (
            "정책/법률",
            "금융시장",
            lambda pc, mc: (
                f"정책·법률({pc}건)과 금융시장({mc}건) 이슈가 교차하여, "
                "규제 변화나 선거·입법 이벤트가 시장 방향성에 직접 영향을 줍니다. "
                "이벤트 드리븐 전략에 적합한 구간입니다."
            ),
        ),
        (
            "지정학/안보",
            "정책/법률",
            lambda sc, pc: (
                f"안보({sc}건)와 정책({pc}건) 이슈가 함께 부각되어, "
                "제재·외교 정책 변화가 안보 상황과 직결되는 국면입니다. "
                "방산·사이버보안·원자재 섹터의 정책 수혜 가능성을 점검하세요."
            ),
        ),
        (
            "에너지",
            "정책/법률",
            lambda ec, pc: (
                f"에너지({ec}건)와 정책({pc}건) 이슈가 교차하여, "
                "에너지 정책(보조금·탄소세·OPEC 협상)이 "
                "원유·신재생에너지 섹터의 중장기 방향을 결정하는 변수입니다."
            ),
        ),
    ]

    # Find the best matching cross-theme template
    cross_applied = False
    if len(top_3_themes) >= 2:
        t1_name, t1_count = top_3_themes[0]
        t2_name, t2_count = top_3_themes[1]

        for tpl_a, tpl_b, tpl_fn in _CROSS_THEME_TEMPLATES:
            if t1_name == tpl_a and t2_name == tpl_b:
                lines.append(f"\n{tpl_fn(t1_count, t2_count)}")
                cross_applied = True
                break
            if t1_name == tpl_b and t2_name == tpl_a:
                lines.append(f"\n{tpl_fn(t2_count, t1_count)}")
                cross_applied = True
                break

    if not cross_applied:
        # Fallback: individual theme analysis
        if security_count and market_count:
            lines.append(
                f"\n안보 이슈({security_count}건)와 금융시장 뉴스({market_count}건)가 "
                "동시 부각되고 있어, 지정학적 긴장이 시장 심리에 직접 영향을 미치는 구간입니다."
            )
        elif security_count:
            sec_pct = security_count / max(total_items, 1) * 100
            lines.append(
                f"\n안보 관련 이슈가 전체의 **{sec_pct:.0f}%**({security_count}건)를 차지합니다. "
                "무력 충돌·제재 확대 시 원유 공급 차질과 방산 수요 증가 가능성이 있습니다."
            )

    # Energy market impact (if not already covered by cross-theme)
    if energy_count and not (cross_applied and "에너지" in (top_3_themes[0][0] if top_3_themes else "")):
        energy_pct = energy_count / max(total_items, 1) * 100
        if energy_pct > 20:
            lines.append(
                f"\n에너지 이슈가 전체의 **{energy_pct:.0f}%**({energy_count}건)를 차지합니다. "
                "원유·가스 가격 변동이 인플레이션 기대에 직접 반영되므로, "
                "중앙은행 정책 전환점에 주목해야 합니다."
            )
        elif energy_count > 0:
            lines.append(
                f"\n에너지 이슈 **{energy_count}건**이 포착되었습니다. "
                "에너지 가격 추이를 모니터링하며 관련 섹터 포지션을 점검하세요."
            )

    # Theme concentration analysis
    if top_3_themes and total_items > 0:
        top2_total = sum(c for _, c in top_3_themes[:2])
        top2_pct = top2_total / total_items * 100
        if top2_pct > 70:
            lines.append(
                f"\n**테마 집중도**: 상위 2개 테마가 전체의 {top2_pct:.0f}%를 차지하여, "
                "시장의 관심이 뚜렷하게 쏠리고 있습니다. "
                "소외 테마에서 서프라이즈 이벤트 발생 시 충격이 증폭될 수 있습니다."
            )
        elif top2_pct < 40 and len(theme_counter) >= 4:
            lines.append(
                f"\n**테마 분산**: {len(theme_counter)}개 테마에 이슈가 고르게 분포하여, "
                "다각적 리스크 모니터링이 필요합니다."
            )

    # Key issue highlights (distinct titles from top items)
    high_impact_items = [item for item in issue_items if item.get("impact") == "높음"]
    if high_impact_items:
        lines.append(f"\n**고중요도 이슈 {len(high_impact_items)}건** 중 주요 건:")
        seen: set = set()
        for item in high_impact_items[:3]:
            title = item.get("title", "")
            # Strip markdown link formatting for display
            clean_title = re.sub(r"\[?\*\*(.*?)\*\*\]?\(.*?\)", r"\1", title)
            if clean_title and clean_title not in seen:
                seen.add(clean_title)
                lines.append(f"- {clean_title[:100]}")

    lines.append(f"\n주요 출처: {top_sources}")

    return "\n".join(lines)


def main() -> None:
    logger.info("=== Starting worldmonitor feed collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("worldmonitor_news_seen.json")
    generator = PostGenerator("market-analysis")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)
    post_title = f"WorldMonitor 글로벌 인텔리전스 브리핑 - {today}"

    if dedup.is_duplicate_exact(post_title, "worldmonitor", today):
        logger.info("WorldMonitor post already exists, skipping")
        log_collection_summary(
            logger,
            collector="collect_worldmonitor_news",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "duplicate"},
        )
        dedup.save()
        return

    items = fetch_worldmonitor_feeds()
    if not items:
        logger.warning("No worldmonitor items collected, skipping post")
        log_collection_summary(
            logger,
            collector="collect_worldmonitor_news",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
            extras={"status": "empty"},
        )
        dedup.save()
        return

    source_counter: Counter = Counter()
    theme_counter: Counter = Counter()
    rows: List[List[object]] = []
    issue_items: List[Dict[str, str]] = []
    source_rows: List[List[object]] = []
    ref_items: List[Dict[str, str]] = []

    for item in items:
        if len(issue_items) >= 20:
            break

        title = item.get("title", "").strip()
        link = item.get("link", "").strip()
        source = item.get("source", "unknown").strip()
        if not title:
            continue

        source_counter[source] += 1
        theme = classify_theme(title)
        theme_counter[theme] += 1
        impact = impact_label(theme)

        display_title = markdown_link(f"**{title}**", link) if link else f"**{escape_table_cell(title)}**"
        issue_items.append(
            {
                "title": display_title,
                "theme": theme,
                "impact": impact,
                "source": source,
                "link": link,
            }
        )
        if link:
            ref_items.append({"title": title, "link": link, "source": source})

    def _sort_key(entry: Dict[str, str]) -> tuple:
        return worldmonitor_sort_key(
            entry.get("impact", ""),
            entry.get("theme", ""),
        )

    for idx, entry in enumerate(sorted(issue_items, key=_sort_key), 1):
        rows.append(
            [
                idx,
                entry["title"],
                entry["theme"],
                entry["impact"],
                entry["source"],
            ]
        )

    total_items = len(rows)
    top_sources = ", ".join(f"{name} ({count}건)" for name, count in source_counter.most_common(5))

    for name, count in source_counter.most_common(6):
        ratio = (count / max(total_items, 1)) * 100
        source_rows.append([name, f"{count}건", f"{ratio:.0f}%"])

    theme_rows = []
    for theme, count in theme_counter.most_common(5):
        ratio = (count / max(total_items, 1)) * 100
        width = max(8, min(100, int(ratio)))
        theme_rows.append(
            '<div class="theme-row">'
            f'<span class="theme-label">{theme}</span>'
            '<div class="bar-track">'
            f'<div class="bar-fill bar-fill-blue" style="width:{width}%"></div>'
            "</div>"
            f'<span class="theme-count">{count}건 ({ratio:.0f}%)</span>'
            "</div>"
        )

    content_parts = [
        f"**{today}** 기준 WorldMonitor 연계 소스에서 글로벌 이벤트/시장/에너지 관련 뉴스 {total_items}건을 정리했습니다.",
        "",
        '<div class="alert-box alert-info"><strong>오늘의 글로벌 리스크 스냅샷</strong><ul>',
        f"<li>총 수집: <strong>{total_items}건</strong></li>",
        f"<li>핵심 테마: <strong>{', '.join(t for t, _ in theme_counter.most_common(3))}</strong></li>",
        f"<li>집중 출처: <strong>{source_counter.most_common(1)[0][0] if source_counter else 'N/A'}</strong></li>",
        "</ul></div>",
        "",
        "## 핵심 요약",
        f"- 수집 건수: **{total_items}건**",
        "- 범위: 글로벌 지정학, 금융시장, 에너지 이슈",
        f"- 주요 출처: {top_sources}",
        "",
    ]

    map_snapshot = fetch_worldmonitor_map_snapshot(days=7)
    content_parts.extend(build_map_snapshot_section(map_snapshot))
    content_parts.extend(
        [
            "",
            "## 전체 뉴스 요약",
            _generate_worldmonitor_summary(theme_counter, total_items, top_sources, issue_items),
            "",
            "## 이슈 분포",
            '<div class="stat-grid">',
            f'<div class="stat-item"><div class="stat-value">{total_items}</div><div class="stat-label">총 이슈</div></div>',
            f'<div class="stat-item"><div class="stat-value">{len(theme_counter)}</div><div class="stat-label">테마 수</div></div>',
            f'<div class="stat-item"><div class="stat-value">{len(source_counter)}</div><div class="stat-label">출처 수</div></div>',
            f'<div class="stat-item"><div class="stat-value">{theme_counter.get("지정학/안보", 0)}</div><div class="stat-label">안보 이슈</div></div>',
            "</div>",
            "",
            '<div class="theme-distribution">',
        ]
    )
    content_parts.extend(theme_rows)
    content_parts.extend(
        [
            "</div>",
            "",
            "## 주요 이슈",
            "",
            markdown_table(
                ["순번", "주요 이슈", "테마", "중요도", "출처"],
                rows,
                aligns=["center", "left", "center", "center", "left"],
            ),
        ]
    )

    content_parts.extend(
        [
            "",
            "## 출처 커버리지",
            "",
            markdown_table(
                ["출처", "건수", "비중"],
                source_rows,
                aligns=["left", "right", "right"],
            ),
        ]
    )

    if ref_items:
        content_parts.extend(["", "## 원문 링크 묶음"])
        seen = set()
        unique_refs = []
        for ref in ref_items[:20]:
            link = ref["link"]
            if link in seen:
                continue
            seen.add(link)
            unique_refs.append(ref)

        content_parts.append(
            '<div class="wm-reference-summary">'
            "<strong>원문 링크 탐색 가이드</strong>"
            "<p>시장 영향이 높은 이슈를 우선 확인할 수 있도록 출처별 커버리지를 함께 제공합니다.</p>"
            "</div>"
        )

        source_pills = []
        for source, count in Counter(ref["source"] for ref in unique_refs).most_common(6):
            source_pills.append(html_source_tag(f"{source} · {count}건"))
        if source_pills:
            content_parts.append('<div class="wm-reference-pills">' + " ".join(source_pills) + "</div>")

        detail_lines = [
            f'<details class="wm-reference-details"><summary>전체 원문 {len(unique_refs)}건 펼치기</summary><div class="details-content">',
            '<ol class="wm-reference-list">',
        ]
        for ref in unique_refs:
            link = html_text(ref["link"])
            title = html_text(ref["title"][:110])
            source = html_text(ref["source"])
            detail_lines.append(
                "<li>"
                f'<a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
                f"{html_source_tag(source)}"
                "</li>"
            )
        detail_lines.extend(["</ol>", "</div></details>"])
        content_parts.append("\n".join(detail_lines))
    else:
        content_parts.extend(["", "## 원문 링크 묶음"])
        content_parts.append(
            '<details class="wm-reference-details"><summary>전체 원문 0건</summary>'
            '<div class="details-content"><p>수집된 원문 링크가 없습니다.</p></div>'
            "</details>"
        )

    content_parts.extend(
        [
            "",
            "## 읽는 방법",
            "- **지정학/안보(높음)**: 금/원유/방산/안전자산 변동성과 동시 확인",
            "- **에너지(중간)**: 원유/가스 가격과 인플레이션 민감 섹터 연동 점검",
            "- **정책/법률(중간)**: 규제 발표 시 섹터별 이벤트 드리븐 리스크 점검",
            "",
            "> *본 브리핑은 worldmonitor.app RSS proxy를 통해 자동 수집된 데이터를 기반으로 하며, 투자 조언이 아닙니다.*",
            "",
            "---",
            f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC",
            "**연계 소스**: worldmonitor.app/api/rss-proxy, finance.worldmonitor.app API",
            f"**지도 뷰**: {WM_MAP_VIEW_URL}",
        ]
    )

    content = "\n".join(content_parts)

    filepath = generator.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["worldmonitor", "geopolitics", "macro", "daily-digest"],
        source="worldmonitor",
        source_url="https://worldmonitor.app",
        lang="ko",
        image="/assets/images/og-default.png",
        slug="daily-worldmonitor-briefing",
    )

    if filepath:
        dedup.mark_seen(post_title, "worldmonitor", today)
        logger.info("Created worldmonitor briefing: %s", filepath)

    dedup.save()
    logger.info("=== Worldmonitor feed collection complete ===")
    unique_count = len(
        {
            f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
            for item in items
            if item.get("title")
        }
    )
    log_collection_summary(
        logger,
        collector="collect_worldmonitor_news",
        source_count=len(source_counter),
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
