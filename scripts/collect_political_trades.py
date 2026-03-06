#!/usr/bin/env python3
"""Collect political trades, insider filings, and policy news.

Sources:
- US Congressional stock trading disclosures (Google News RSS)
- SEC insider trading / Form 4 filings (EDGAR + Google News)
- Trump executive orders & economic policy (Google News RSS)
- Korean politician asset disclosures (Google News RSS)
- Central bank policy decisions (Google News RSS)
"""

import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import REQUEST_TIMEOUT, get_ssl_verify, setup_logging
from common.dedup import DedupEngine
from common.enrichment import _POLITICAL_SOURCE_CONTEXT, enrich_items
from common.markdown_utils import (
    html_reference_details,
    html_source_tag,
)
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.translator import get_display_title

logger = setup_logging("collect_political_trades")

VERIFY_SSL = get_ssl_verify()


def fetch_congressional_trades() -> List[Dict[str, Any]]:
    """Fetch US congressional stock trading news via Google News RSS."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=congressional+stock+trading+disclosure&hl=en-US&gl=US&ceid=US:en",
            "Congressional Trades EN",
            ["political-trades", "congress", "us"],
        ),
        (
            "https://news.google.com/rss/search?q=Pelosi+stock+trades+congress&hl=en-US&gl=US&ceid=US:en",
            "Pelosi Trades",
            ["political-trades", "pelosi", "congress"],
        ),
        (
            "https://news.google.com/rss/search?q=senator+stock+trading+disclosure&hl=en-US&gl=US&ceid=US:en",
            "Senator Trades",
            ["political-trades", "senate", "us"],
        ),
        (
            "https://news.google.com/rss/search?q=미국+의원+주식+거래&hl=ko&gl=KR&ceid=KR:ko",
            "미국 의회 거래 KR",
            ["political-trades", "congress", "korean"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_sec_insider_trades() -> List[Dict[str, Any]]:
    """Fetch SEC insider trading / Form 4 news."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=SEC+insider+trading+Form+4+filing&hl=en-US&gl=US&ceid=US:en",
            "SEC Insider Trading",
            ["political-trades", "sec", "insider"],
        ),
        (
            "https://news.google.com/rss/search?q=SEC+insider+buying+selling+stock&hl=en-US&gl=US&ceid=US:en",
            "SEC Insider Activity",
            ["political-trades", "sec", "insider"],
        ),
        (
            "https://news.google.com/rss/search?q=SEC+내부자+거래+공시&hl=ko&gl=KR&ceid=KR:ko",
            "SEC 내부자거래 KR",
            ["political-trades", "sec", "korean"],
        ),
    ]
    items = fetch_rss_feeds_concurrent(feeds)

    # Also try EDGAR Full-Text Search API for recent Form 4 filings
    try:
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": "Form 4",
            "dateRange": "custom",
            "startdt": datetime.now(UTC).strftime("%Y-%m-%d"),
            "enddt": datetime.now(UTC).strftime("%Y-%m-%d"),
            "forms": "4",
        }
        resp = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
            headers={"User-Agent": "InvestingDragon/1.0 (contact@example.com)"},
        )
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:10]:
                source = hit.get("_source", {})
                entity = source.get("entity_name", "Unknown")
                form_type = source.get("form_type", "4")
                filed = source.get("file_date", "")
                items.append(
                    {
                        "title": f"[SEC Form {form_type}] {entity}",
                        "description": f"SEC Form {form_type} filing by {entity} on {filed}",
                        "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={entity}&type=4&dateb=&owner=include&count=10",
                        "published": filed,
                        "source": "SEC EDGAR",
                        "tags": ["political-trades", "sec", "form4", "insider"],
                    }
                )
            logger.info("SEC EDGAR: fetched %d Form 4 filings", len(hits[:10]))
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        logger.warning("SEC EDGAR search failed: %s", e)

    return items


def fetch_trump_executive_orders() -> List[Dict[str, Any]]:
    """Fetch Trump executive order & economic policy news."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=Trump+executive+order+economy&hl=en-US&gl=US&ceid=US:en",
            "Trump EO Economy",
            ["political-trades", "trump", "executive-order"],
        ),
        (
            "https://news.google.com/rss/search?q=Trump+executive+order+tariff+trade&hl=en-US&gl=US&ceid=US:en",
            "Trump Tariff Policy",
            ["political-trades", "trump", "tariff"],
        ),
        (
            "https://news.google.com/rss/search?q=트럼프+행정명령+경제&hl=ko&gl=KR&ceid=KR:ko",
            "트럼프 행정명령 KR",
            ["political-trades", "trump", "korean"],
        ),
        (
            "https://news.google.com/rss/search?q=Trump+crypto+executive+order+regulation&hl=en-US&gl=US&ceid=US:en",
            "Trump Crypto Policy",
            ["political-trades", "trump", "crypto"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_korean_political_trades() -> List[Dict[str, Any]]:
    """Fetch Korean politician asset/trade disclosures."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=이재명+재산+공개&hl=ko&gl=KR&ceid=KR:ko",
            "이재명 재산공개",
            ["political-trades", "이재명", "korea"],
        ),
        (
            "https://news.google.com/rss/search?q=국회의원+주식+거래+매매&hl=ko&gl=KR&ceid=KR:ko",
            "국회의원 주식거래",
            ["political-trades", "국회의원", "korea"],
        ),
        (
            "https://news.google.com/rss/search?q=공직자+재산신고+변동&hl=ko&gl=KR&ceid=KR:ko",
            "공직자 재산신고",
            ["political-trades", "공직자", "korea"],
        ),
        (
            "https://news.google.com/rss/search?q=한국+정치인+부동산+주식&hl=ko&gl=KR&ceid=KR:ko",
            "정치인 재산 KR",
            ["political-trades", "정치인", "korea"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_central_bank_policy() -> List[Dict[str, Any]]:
    """Fetch central bank policy decision news."""
    feeds = [
        (
            "https://news.google.com/rss/search?q=Federal+Reserve+rate+decision+FOMC&hl=en-US&gl=US&ceid=US:en",
            "Fed Rate Decision",
            ["political-trades", "fed", "central-bank"],
        ),
        (
            "https://news.google.com/rss/search?q=한국은행+금리+결정+기준금리&hl=ko&gl=KR&ceid=KR:ko",
            "한국은행 금리결정",
            ["political-trades", "한국은행", "central-bank"],
        ),
        (
            "https://news.google.com/rss/search?q=ECB+interest+rate+decision&hl=en-US&gl=US&ceid=US:en",
            "ECB Policy",
            ["political-trades", "ecb", "central-bank"],
        ),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def main():
    """Main political trades collection routine."""
    logger.info("=== Starting political trades collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("political_trades_seen.json")
    gen = PostGenerator("political-trades")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)

    # Collect from all sources
    congress_items = fetch_congressional_trades()
    sec_items = fetch_sec_insider_trades()
    trump_items = fetch_trump_executive_orders()
    korea_items = fetch_korean_political_trades()
    central_bank_items = fetch_central_bank_policy()

    # ── Consolidated political trades post ──
    post_title = f"정치인 거래·정책 리포트 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Political trades post already exists, skipping")
        all_items = congress_items + sec_items + trump_items + korea_items + central_bank_items
        unique_count = len(
            {
                f"{item.get('title', '')}|{item.get('source', '')}|{item.get('link', '')}"
                for item in all_items
                if item.get("title")
            }
        )
        source_count = len({item.get("source", "") for item in all_items if item.get("source")})
        log_collection_summary(
            logger,
            collector="collect_political_trades",
            source_count=source_count,
            unique_items=unique_count,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    all_items = congress_items + sec_items + trump_items + korea_items + central_bank_items
    pre_dedup_count = len(all_items)

    # Deduplicate individual items
    unique_items = []
    for item in all_items:
        if not dedup.is_duplicate(item.get("title", ""), item.get("source", ""), today):
            unique_items.append(item)

    total_count = len(unique_items)
    logger.info(
        "Dedup filter: %d items -> %d unique (%d removed)",
        pre_dedup_count,
        total_count,
        pre_dedup_count - total_count,
    )

    if total_count == 0:
        logger.warning("No political trades items after dedup (pre-dedup: %d), skipping post", pre_dedup_count)
        log_collection_summary(
            logger,
            collector="collect_political_trades",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    enrich_items(unique_items, context_map=_POLITICAL_SOURCE_CONTEXT, max_fetch=8)

    # Count by source category
    congress_count = sum(
        1 for i in unique_items if any(t in i.get("tags", []) for t in ["congress", "pelosi", "senate"])
    )
    sec_count = sum(1 for i in unique_items if "sec" in i.get("tags", []))
    trump_count = sum(1 for i in unique_items if "trump" in i.get("tags", []))
    korea_count = sum(1 for i in unique_items if "korea" in i.get("tags", []))
    cb_count = sum(1 for i in unique_items if "central-bank" in i.get("tags", []))

    # Build content
    content_parts = []

    # Data-driven opening
    source_parts = []
    if congress_count:
        source_parts.append(f"미국 의회 거래 {congress_count}건")
    if sec_count:
        source_parts.append(f"SEC 내부자 거래 {sec_count}건")
    if trump_count:
        source_parts.append(f"트럼프 정책 {trump_count}건")
    if korea_count:
        source_parts.append(f"한국 정치인 {korea_count}건")
    if cb_count:
        source_parts.append(f"중앙은행 {cb_count}건")
    sources_str = ", ".join(source_parts) if source_parts else "데이터 없음"

    content_parts.append("미국 정치인 거래 동향과 주요 정책 변동을 분석한 일일 리포트입니다.\n")

    # Keyword analysis
    all_texts = " ".join(item.get("title", "") + " " + item.get("description", "") for item in unique_items).lower()
    keyword_targets = [
        "trump",
        "pelosi",
        "이재명",
        "congress",
        "sec",
        "fed",
        "tariff",
        "관세",
        "executive order",
        "행정명령",
        "insider",
        "disclosure",
        "재산",
    ]
    keyword_hits = {kw: len(re.findall(re.escape(kw), all_texts, re.IGNORECASE)) for kw in keyword_targets}
    top_keywords = [(kw, cnt) for kw, cnt in sorted(keyword_hits.items(), key=lambda x: -x[1]) if cnt > 0]

    # Helper: extract first sentence from text
    def _first_sentence(text: str, max_len: int = 200) -> str:
        """Extract first complete sentence from text."""
        for sep in ["。", ". ", "다. ", "요. ", "다.", "요."]:
            idx = text.find(sep)
            if 15 < idx < max_len:
                return text[: idx + len(sep)].strip()
        return text[:max_len].rsplit(" ", 1)[0] if len(text) > max_len else text

    # Filter unique items by category for sections
    congress_filtered = [
        i for i in unique_items if any(t in i.get("tags", []) for t in ["congress", "pelosi", "senate"])
    ]
    trump_filtered = [i for i in unique_items if "trump" in i.get("tags", [])]
    sec_filtered = [i for i in unique_items if "sec" in i.get("tags", [])]
    korea_filtered = [i for i in unique_items if "korea" in i.get("tags", [])]
    cb_filtered = [i for i in unique_items if "central-bank" in i.get("tags", [])]

    # ── 한눈에 보기 (stat-grid + alert-box, 깨끗한 HTML) ──
    stat_items = [
        f'<div class="stat-item"><div class="stat-value">{total_count}</div>'
        f'<div class="stat-label">총 수집 건수</div></div>'
    ]
    if congress_count:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{congress_count}</div>'
            f'<div class="stat-label">의회 거래</div></div>'
        )
    if trump_count:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{trump_count}</div>'
            f'<div class="stat-label">트럼프 정책</div></div>'
        )
    if sec_count:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{sec_count}</div>'
            f'<div class="stat-label">SEC 내부자</div></div>'
        )
    if korea_count:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{korea_count}</div>'
            f'<div class="stat-label">한국 정치인</div></div>'
        )
    if cb_count:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{cb_count}</div>'
            f'<div class="stat-label">중앙은행</div></div>'
        )

    content_parts.append("## 한눈에 보기\n")
    content_parts.append(f'<div class="stat-grid">{"".join(stat_items)}</div>\n')

    # Alert box with top keywords
    if top_keywords:
        kw_text = ", ".join(f"**{kw}**({cnt}회)" for kw, cnt in top_keywords[:5])
        content_parts.append(
            f'<div class="alert-box alert-info"><strong>오늘의 핵심 키워드</strong>: {kw_text}</div>\n'
        )

    # ── 전체 뉴스 요약 (내러티브 형식) ──
    content_parts.append("## 전체 뉴스 요약\n")
    summary_narrative = []
    summary_narrative.append(
        f"오늘 정치인 거래·정책 분야에서 총 **{total_count}건**의 뉴스가 수집되었습니다. "
        f"세부 구성은 {sources_str}입니다."
    )
    if trump_count and trump_filtered:
        item = trump_filtered[0]
        desc = item.get("description", "").strip()
        title = item.get("title", "")
        highlight = _first_sentence(desc) if desc and desc != title and len(desc) > 20 else title
        summary_narrative.append(
            f"\n**트럼프 정책** 관련으로는 {highlight} 등의 소식이 포착되었으며, "
            f"행정명령과 관세 정책 변화가 글로벌 시장 심리에 직접적 영향을 미치고 있습니다."
        )
    if congress_count and congress_filtered:
        item = congress_filtered[0]
        desc = item.get("description", "").strip()
        title = item.get("title", "")
        highlight = _first_sentence(desc) if desc and desc != title and len(desc) > 20 else title
        summary_narrative.append(
            f"\n**미국 의회 거래** 동향에서는 {highlight} 등이 보고되었습니다. "
            "의원들의 주식 거래 패턴은 향후 입법 방향의 간접 신호로 해석될 수 있습니다."
        )
    if cb_count and cb_filtered:
        item = cb_filtered[0]
        desc = item.get("description", "").strip()
        title = item.get("title", "")
        highlight = _first_sentence(desc) if desc and desc != title and len(desc) > 20 else title
        summary_narrative.append(
            f"\n**중앙은행 정책**에서는 {highlight} 관련 뉴스가 수집되었으며, "
            "금리 결정은 채권·주식·암호화폐 시장 전반에 파급 효과를 줍니다."
        )
    if korea_count and korea_filtered:
        item = korea_filtered[0]
        desc = item.get("description", "").strip()
        title = item.get("title", "")
        highlight = _first_sentence(desc) if desc and desc != title and len(desc) > 20 else title
        summary_narrative.append(f"\n**한국 정치인** 관련으로는 {highlight} 등의 재산/거래 소식이 수집되었습니다.")
    content_parts.extend(summary_narrative)

    content_parts.append("\n\n---\n")

    # Collect source links
    source_links = []

    def _render_news_cards(items: List[Dict], section_title: str, max_items: int = 10, featured: int = 5):
        """Add a news card section with descriptions to content_parts."""
        if not items:
            return
        content_parts.append(f"\n## {section_title}\n")
        for i, item in enumerate(items[:max_items], 1):
            title = get_display_title(item)
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = (item.get("description_ko") or item.get("description", "")).strip()
            if link:
                source_links.append(item)
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title:
                desc_text = _first_sentence(description)
                content_parts.append(f"{desc_text}")
            content_parts.append(f"{html_source_tag(source)}\n")
        content_parts.append("")

    _render_news_cards(congress_filtered, "미국 의회 거래 동향")
    _render_news_cards(trump_filtered, "트럼프 행정명령/정책")
    _render_news_cards(sec_filtered, "SEC 내부자 거래 (Form 4)")
    _render_news_cards(korea_filtered, "한국 정치인 재산/거래")
    _render_news_cards(cb_filtered, "중앙은행 정책 동향")

    content_parts.append("---\n")

    # ── 정책 영향 분석 (데이터 기반 내러티브) ──
    content_parts.append("\n## 정책 영향 분석\n")
    analysis_lines = []

    # Buy/sell pattern detection from titles
    buy_signals = 0
    sell_signals = 0
    stock_mentions: Counter = Counter()
    _BUY_KW = ["buy", "bought", "purchase", "매수", "매입", "취득", "long"]
    _SELL_KW = ["sell", "sold", "sale", "매도", "매각", "처분", "short"]
    for item in unique_items:
        title_lower = item.get("title", "").lower()
        desc_lower = item.get("description", "").lower()
        text = title_lower + " " + desc_lower
        if any(kw in text for kw in _BUY_KW):
            buy_signals += 1
        if any(kw in text for kw in _SELL_KW):
            sell_signals += 1
        # Extract stock ticker mentions (e.g., $AAPL, NVDA, MSFT)
        tickers = re.findall(r"\$([A-Z]{2,5})\b", item.get("title", "") + " " + item.get("description", ""))
        for ticker in tickers:
            stock_mentions[ticker] += 1

    # Trade pattern summary
    if buy_signals or sell_signals:
        total_trades = buy_signals + sell_signals
        buy_pct = buy_signals / max(total_trades, 1) * 100
        if buy_signals > sell_signals * 1.5:
            pattern_note = "매수 비중이 압도적으로 높아, 정치인들이 시장에 대해 낙관적 시각을 갖고 있음을 시사합니다."
        elif sell_signals > buy_signals * 1.5:
            pattern_note = "매도 비중이 높아, 리스크 회피 또는 차익 실현 움직임이 감지됩니다."
        else:
            pattern_note = "매수·매도가 균형을 이루며, 시장 방향에 대한 정치권의 의견이 엇갈리고 있습니다."
        analysis_lines.append(
            f"**거래 패턴**: 매수 신호 {buy_signals}건({buy_pct:.0f}%), "
            f"매도 신호 {sell_signals}건({100 - buy_pct:.0f}%). {pattern_note}"
        )

    # Stock concentration analysis
    if stock_mentions:
        top_stocks = stock_mentions.most_common(5)
        stocks_str = ", ".join(f"**${t}**({c}건)" for t, c in top_stocks)
        analysis_lines.append(
            f"\n**종목 집중도**: {stocks_str}. "
            f"정치인 거래가 특정 종목에 집중되는 것은 "
            f"해당 섹터의 입법·규제 방향에 대한 내부 정보 가능성을 시사합니다."
        )

    if trump_count:
        # Detect specific policy areas
        tariff_items = sum(
            1
            for i in trump_filtered
            if any(
                kw in (i.get("title", "") + " " + i.get("description", "")).lower()
                for kw in ["tariff", "관세", "trade war", "무역"]
            )
        )
        crypto_items = sum(
            1
            for i in trump_filtered
            if any(
                kw in (i.get("title", "") + " " + i.get("description", "")).lower()
                for kw in ["crypto", "bitcoin", "digital asset", "암호화폐"]
            )
        )
        eo_items = sum(
            1
            for i in trump_filtered
            if any(
                kw in (i.get("title", "") + " " + i.get("description", "")).lower()
                for kw in ["executive order", "행정명령"]
            )
        )
        policy_details = []
        if tariff_items:
            policy_details.append(f"관세·무역 {tariff_items}건")
        if crypto_items:
            policy_details.append(f"암호화폐 {crypto_items}건")
        if eo_items:
            policy_details.append(f"행정명령 {eo_items}건")
        detail_str = f" ({', '.join(policy_details)})" if policy_details else ""

        analysis_lines.append(
            f"\n**트럼프 정책**: {trump_count}건{detail_str}. "
            "행정명령 및 관세 정책 변화는 반도체·자동차·에너지 섹터의 변동성을 확대시킵니다."
        )
        for item in trump_filtered[:1]:
            desc = (item.get("description_ko") or item.get("description", "")).strip()
            title = get_display_title(item)
            if desc and desc != title and len(desc) > 20:
                analysis_lines.append(f"\n> **주요 내용**: {_first_sentence(desc)}")

    if congress_count:
        analysis_lines.append(
            f"\n**미국 의회 거래**: {congress_count}건. "
            "의원들의 거래 패턴은 입법 방향의 간접 신호로 해석됩니다. "
            "특히 대규모 매수는 해당 섹터 지원 법안 발의 가능성과 연결될 수 있습니다."
        )

    if korea_count:
        analysis_lines.append(
            f"\n**한국 정치인**: {korea_count}건. "
            "공직자 재산 변동 공개는 부동산·주식 정책 방향의 선행 지표가 될 수 있으며, "
            "국내 규제 환경 변화에 대한 선제적 대응이 필요합니다."
        )

    if cb_count:
        # Detect hawkish/dovish signals
        hawkish = sum(
            1
            for i in cb_filtered
            if any(
                kw in (i.get("title", "") + " " + i.get("description", "")).lower()
                for kw in ["hike", "인상", "hawkish", "매파", "tightening", "긴축"]
            )
        )
        dovish = sum(
            1
            for i in cb_filtered
            if any(
                kw in (i.get("title", "") + " " + i.get("description", "")).lower()
                for kw in ["cut", "인하", "dovish", "비둘기", "easing", "완화"]
            )
        )
        if hawkish > dovish:
            cb_tone = "매파적 신호가 우세하여, 채권 수익률 상승과 성장주 압박이 예상됩니다."
        elif dovish > hawkish:
            cb_tone = "비둘기파 신호가 우세하여, 유동성 확대 기대감이 형성되고 있습니다."
        else:
            cb_tone = "금리 결정과 통화정책 기조를 면밀히 주시해야 합니다."
        analysis_lines.append(f"\n**중앙은행 정책**: {cb_count}건. {cb_tone}")
        for item in cb_filtered[:1]:
            desc = (item.get("description_ko") or item.get("description", "")).strip()
            title = get_display_title(item)
            if desc and desc != title and len(desc) > 20:
                analysis_lines.append(f"\n> **주요 내용**: {_first_sentence(desc)}")

    # Cross-theme synthesis: combined signals across categories
    active_categories = []
    if trump_count:
        active_categories.append("트럼프 정책")
    if congress_count:
        active_categories.append("의회 거래")
    if cb_count:
        active_categories.append("중앙은행")
    if korea_count:
        active_categories.append("한국 정치인")
    if sec_count:
        active_categories.append("SEC 내부자")

    if len(active_categories) >= 2:
        _CROSS_POLICY_TEMPLATES = [
            (
                {"트럼프 정책", "중앙은행"},
                "행정부 정책과 중앙은행 통화정책이 동시에 움직이는 구간입니다. "
                "재정·통화 정책의 방향이 일치하면 시장 모멘텀이 강화되고, "
                "충돌하면 혼조세와 변동성 확대가 나타납니다.",
            ),
            (
                {"트럼프 정책", "의회 거래"},
                "행정명령과 의회 거래가 동시에 포착되어, 정책 수혜 예상 종목에 "
                "정치인 자금이 선제적으로 유입되었을 가능성이 있습니다. "
                "관련 섹터의 입법·규제 일정을 주시하세요.",
            ),
            (
                {"의회 거래", "SEC 내부자"},
                "의회 거래와 SEC 내부자 활동이 동시에 활발한 것은 "
                "특정 섹터에 대한 정보 비대칭이 존재할 수 있음을 시사합니다. "
                "해당 종목의 실적 발표와 규제 일정을 함께 점검하세요.",
            ),
            (
                {"중앙은행", "의회 거래"},
                "금리 결정과 의원 거래 패턴이 함께 나타나, "
                "통화정책 변화에 앞선 포지셔닝이 진행 중일 수 있습니다. "
                "금리 민감 섹터(부동산·금융·성장주) 중심으로 점검이 필요합니다.",
            ),
            (
                {"트럼프 정책", "한국 정치인"},
                "미국 행정부 정책과 한국 정치 동향이 동시에 부각되어, "
                "한미 경제 관계(반도체·무역·방산)에 영향을 줄 수 있는 구간입니다.",
            ),
            (
                {"중앙은행", "한국 정치인"},
                "글로벌 통화정책과 국내 정치 동향이 겹쳐, "
                "한국은행 금리 결정과 재정정책 방향에 대한 시장의 관심이 높아지고 있습니다.",
            ),
        ]

        cross_text = None
        active_set = set(active_categories)
        for required_set, template in _CROSS_POLICY_TEMPLATES:
            if required_set.issubset(active_set):
                cross_text = template
                break

        if not cross_text:
            # Concentration-based fallback
            cat_counts = {
                "트럼프 정책": trump_count,
                "의회 거래": congress_count,
                "중앙은행": cb_count,
                "한국 정치인": korea_count,
                "SEC 내부자": sec_count,
            }
            sorted_cats = sorted(
                ((k, v) for k, v in cat_counts.items() if v > 0),
                key=lambda x: -x[1],
            )
            if sorted_cats:
                top_cat = sorted_cats[0]
                top_pct = top_cat[1] / max(total_count, 1) * 100
                if top_pct > 50:
                    cross_text = (
                        f"**{top_cat[0]}** 관련 뉴스가 전체의 {top_pct:.0f}%를 차지하여, "
                        f"오늘 시장의 정책 리스크가 이 분야에 집중됩니다."
                    )
                else:
                    cross_text = (
                        f"{len(active_categories)}개 분야에서 뉴스가 고르게 분포하여, "
                        "다각적 정책 리스크 모니터링이 필요한 시점입니다."
                    )

        if cross_text:
            analysis_lines.append(f"\n**복합 정책 신호**: {cross_text}")

    if not analysis_lines:
        analysis_lines.append("현재 수집된 정치인 거래/정책 데이터가 제한적입니다.")
    analysis_lines.append("")
    analysis_lines.append(
        "> *본 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )
    content_parts.extend(analysis_lines)

    # References (top 10 only) - collapsible
    if source_links:
        content_parts.append(
            html_reference_details(
                "참고 링크",
                source_links,
                limit=10,
                title_max_len=80,
            )
        )

    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    # Build excerpt
    excerpt_parts = []
    if congress_count:
        excerpt_parts.append(f"의회 거래 {congress_count}건")
    if sec_count:
        excerpt_parts.append(f"SEC 내부자 {sec_count}건")
    if trump_count:
        excerpt_parts.append(f"트럼프 정책 {trump_count}건")
    if korea_count:
        excerpt_parts.append(f"한국 정치인 {korea_count}건")
    if cb_count:
        excerpt_parts.append(f"중앙은행 {cb_count}건")
    excerpt_text = f"{today} 정치인 거래·정책 리포트: {', '.join(excerpt_parts)}, 총 {total_count}건 수집"

    # Generate briefing card image
    briefing_image = ""
    try:
        from common.image_generator import generate_news_briefing_card

        card_themes = []
        theme_data = [
            ("SEC 내부자 거래", "📊", sec_count),
            ("트럼프 정책", "🏛️", trump_count),
            ("의회 거래", "🏦", congress_count),
            ("한국 정치인", "🇰🇷", korea_count),
            ("중앙은행", "💰", cb_count),
        ]
        for t_name, t_emoji, t_count in theme_data:
            if t_count:
                card_themes.append({"name": t_name, "emoji": t_emoji, "count": t_count, "keywords": []})
        if card_themes:
            img = generate_news_briefing_card(
                card_themes,
                today,
                category="Political Trades",
                total_count=total_count,
                filename=f"news-briefing-political-{today}.png",
            )
            if img:
                briefing_image = img
                logger.info("Generated political trades briefing card")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Political trades briefing card failed: %s", e)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=[
            "political-trades",
            "congress",
            "sec",
            "trump",
            "이재명",
            "central-bank",
            "insider-trading",
        ],
        source="consolidated",
        lang="ko",
        slug="daily-political-trades-report",
        image=briefing_image or "/assets/images/og-default.png",
        extra_frontmatter={"excerpt": excerpt_text},
    )
    if filepath:
        # Mark individual items as seen
        for item in unique_items:
            dedup.mark_seen(item.get("title", ""), item.get("source", ""), today)
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created political trades post: %s", filepath)

    dedup.save()
    logger.info("=== Political trades collection complete ===")
    source_count = len({item.get("source", "") for item in unique_items if item.get("source")})
    log_collection_summary(
        logger,
        collector="collect_political_trades",
        source_count=source_count,
        unique_items=total_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
