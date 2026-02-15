#!/usr/bin/env python3
"""Collect political trades, insider filings, and policy news.

Sources:
- US Congressional stock trading disclosures (Google News RSS)
- SEC insider trading / Form 4 filings (EDGAR + Google News)
- Trump executive orders & economic policy (Google News RSS)
- Korean politician asset disclosures (Google News RSS)
- Central bank policy decisions (Google News RSS)
"""

import sys
import os
import re
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging, get_ssl_verify
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feeds_concurrent
from common.summarizer import ThemeSummarizer

logger = setup_logging("collect_political_trades")

VERIFY_SSL = get_ssl_verify()
REQUEST_TIMEOUT = 15


def fetch_congressional_trades() -> List[Dict[str, Any]]:
    """Fetch US congressional stock trading news via Google News RSS."""
    feeds = [
        ("https://news.google.com/rss/search?q=congressional+stock+trading+disclosure&hl=en-US&gl=US&ceid=US:en",
         "Congressional Trades EN", ["political-trades", "congress", "us"]),
        ("https://news.google.com/rss/search?q=Pelosi+stock+trades+congress&hl=en-US&gl=US&ceid=US:en",
         "Pelosi Trades", ["political-trades", "pelosi", "congress"]),
        ("https://news.google.com/rss/search?q=senator+stock+trading+disclosure&hl=en-US&gl=US&ceid=US:en",
         "Senator Trades", ["political-trades", "senate", "us"]),
        ("https://news.google.com/rss/search?q=미국+의원+주식+거래&hl=ko&gl=KR&ceid=KR:ko",
         "미국 의회 거래 KR", ["political-trades", "congress", "korean"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_sec_insider_trades() -> List[Dict[str, Any]]:
    """Fetch SEC insider trading / Form 4 news."""
    feeds = [
        ("https://news.google.com/rss/search?q=SEC+insider+trading+Form+4+filing&hl=en-US&gl=US&ceid=US:en",
         "SEC Insider Trading", ["political-trades", "sec", "insider"]),
        ("https://news.google.com/rss/search?q=SEC+insider+buying+selling+stock&hl=en-US&gl=US&ceid=US:en",
         "SEC Insider Activity", ["political-trades", "sec", "insider"]),
        ("https://news.google.com/rss/search?q=SEC+내부자+거래+공시&hl=ko&gl=KR&ceid=KR:ko",
         "SEC 내부자거래 KR", ["political-trades", "sec", "korean"]),
    ]
    items = fetch_rss_feeds_concurrent(feeds)

    # Also try EDGAR Full-Text Search API for recent Form 4 filings
    try:
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": "Form 4",
            "dateRange": "custom",
            "startdt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "forms": "4",
        }
        resp = requests.get(
            url, params=params, timeout=REQUEST_TIMEOUT,
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
                items.append({
                    "title": f"[SEC Form {form_type}] {entity}",
                    "description": f"SEC Form {form_type} filing by {entity} on {filed}",
                    "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={entity}&type=4&dateb=&owner=include&count=10",
                    "published": filed,
                    "source": "SEC EDGAR",
                    "tags": ["political-trades", "sec", "form4", "insider"],
                })
            logger.info("SEC EDGAR: fetched %d Form 4 filings", len(hits[:10]))
    except Exception as e:
        logger.warning("SEC EDGAR search failed: %s", e)

    return items


def fetch_trump_executive_orders() -> List[Dict[str, Any]]:
    """Fetch Trump executive order & economic policy news."""
    feeds = [
        ("https://news.google.com/rss/search?q=Trump+executive+order+economy&hl=en-US&gl=US&ceid=US:en",
         "Trump EO Economy", ["political-trades", "trump", "executive-order"]),
        ("https://news.google.com/rss/search?q=Trump+executive+order+tariff+trade&hl=en-US&gl=US&ceid=US:en",
         "Trump Tariff Policy", ["political-trades", "trump", "tariff"]),
        ("https://news.google.com/rss/search?q=트럼프+행정명령+경제&hl=ko&gl=KR&ceid=KR:ko",
         "트럼프 행정명령 KR", ["political-trades", "trump", "korean"]),
        ("https://news.google.com/rss/search?q=Trump+crypto+executive+order+regulation&hl=en-US&gl=US&ceid=US:en",
         "Trump Crypto Policy", ["political-trades", "trump", "crypto"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_korean_political_trades() -> List[Dict[str, Any]]:
    """Fetch Korean politician asset/trade disclosures."""
    feeds = [
        ("https://news.google.com/rss/search?q=이재명+재산+공개&hl=ko&gl=KR&ceid=KR:ko",
         "이재명 재산공개", ["political-trades", "이재명", "korea"]),
        ("https://news.google.com/rss/search?q=국회의원+주식+거래+매매&hl=ko&gl=KR&ceid=KR:ko",
         "국회의원 주식거래", ["political-trades", "국회의원", "korea"]),
        ("https://news.google.com/rss/search?q=공직자+재산신고+변동&hl=ko&gl=KR&ceid=KR:ko",
         "공직자 재산신고", ["political-trades", "공직자", "korea"]),
        ("https://news.google.com/rss/search?q=한국+정치인+부동산+주식&hl=ko&gl=KR&ceid=KR:ko",
         "정치인 재산 KR", ["political-trades", "정치인", "korea"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def fetch_central_bank_policy() -> List[Dict[str, Any]]:
    """Fetch central bank policy decision news."""
    feeds = [
        ("https://news.google.com/rss/search?q=Federal+Reserve+rate+decision+FOMC&hl=en-US&gl=US&ceid=US:en",
         "Fed Rate Decision", ["political-trades", "fed", "central-bank"]),
        ("https://news.google.com/rss/search?q=한국은행+금리+결정+기준금리&hl=ko&gl=KR&ceid=KR:ko",
         "한국은행 금리결정", ["political-trades", "한국은행", "central-bank"]),
        ("https://news.google.com/rss/search?q=ECB+interest+rate+decision&hl=en-US&gl=US&ceid=US:en",
         "ECB Policy", ["political-trades", "ecb", "central-bank"]),
    ]
    return fetch_rss_feeds_concurrent(feeds)


def main():
    """Main political trades collection routine."""
    logger.info("=== Starting political trades collection ===")

    dedup = DedupEngine("political_trades_seen.json")
    gen = PostGenerator("political-trades")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

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
        dedup.save()
        return

    all_items = congress_items + sec_items + trump_items + korea_items + central_bank_items

    # Deduplicate individual items
    unique_items = []
    for item in all_items:
        if not dedup.is_duplicate(item.get("title", ""), item.get("source", ""), today):
            unique_items.append(item)

    total_count = len(unique_items)

    if total_count == 0:
        logger.warning("No political trades items collected, skipping post")
        dedup.save()
        return

    # Theme analysis
    summarizer = ThemeSummarizer(unique_items)

    # Count by source category
    congress_count = sum(1 for i in unique_items if any(t in i.get("tags", []) for t in ["congress", "pelosi", "senate"]))
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

    content_parts.append(f"**{today}** 정치인 거래·재산 공개·정책 동향을 종합 분석합니다. {sources_str}, 총 {total_count}건이 수집되었습니다.\n")

    # Keyword analysis for executive summary
    all_texts = " ".join(
        item.get("title", "") + " " + item.get("description", "")
        for item in unique_items
    ).lower()
    keyword_targets = ["trump", "pelosi", "이재명", "congress", "sec", "fed", "tariff", "관세",
                       "executive order", "행정명령", "insider", "disclosure", "재산"]
    keyword_hits = {kw: len(re.findall(re.escape(kw), all_texts, re.IGNORECASE))
                    for kw in keyword_targets}
    top_keywords = [(kw, cnt) for kw, cnt in sorted(keyword_hits.items(), key=lambda x: -x[1]) if cnt > 0]

    # Executive summary
    exec_summary = summarizer.generate_executive_summary(
        category_type="general",
        extra_data={"top_keywords": top_keywords},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    # Theme distribution
    dist = summarizer.generate_distribution_chart()
    if dist:
        content_parts.append("\n" + dist)

    content_parts.append("\n---\n")

    # Collect source links
    source_links = []

    def _render_news_cards(items: List[Dict], section_title: str,
                           max_items: int = 10, featured: int = 5):
        """Add a news card section with descriptions to content_parts."""
        if not items:
            return
        content_parts.append(f"\n## {section_title}\n")
        for i, item in enumerate(items[:max_items], 1):
            title = item.get("title", "")
            source = item.get("source", "unknown")
            link = item.get("link", "")
            description = item.get("description", "").strip()
            if link:
                source_links.append({"title": title, "link": link, "source": source})
                content_parts.append(f"**{i}. [{title}]({link})**")
            else:
                content_parts.append(f"**{i}. {title}**")
            if description and description != title and i <= featured:
                desc_text = description[:150]
                if len(description) > 150:
                    desc_text += "..."
                content_parts.append(f"{desc_text}")
            content_parts.append(f'<span class="source-tag">{source}</span>\n')
        content_parts.append("")

    # Filter unique items by category for sections
    congress_filtered = [i for i in unique_items if any(t in i.get("tags", []) for t in ["congress", "pelosi", "senate"])]
    trump_filtered = [i for i in unique_items if "trump" in i.get("tags", [])]
    sec_filtered = [i for i in unique_items if "sec" in i.get("tags", [])]
    korea_filtered = [i for i in unique_items if "korea" in i.get("tags", [])]
    cb_filtered = [i for i in unique_items if "central-bank" in i.get("tags", [])]

    _render_news_cards(congress_filtered, "미국 의회 거래 동향")
    _render_news_cards(trump_filtered, "트럼프 행정명령/정책")
    _render_news_cards(sec_filtered, "SEC 내부자 거래 (Form 4)")
    _render_news_cards(korea_filtered, "한국 정치인 재산/거래")
    _render_news_cards(cb_filtered, "중앙은행 정책 동향")

    content_parts.append("---\n")

    # Policy impact analysis (enhanced with description-based insights)
    content_parts.append("\n## 정책 영향 분석\n")
    analysis_lines = []
    if trump_count:
        analysis_lines.append(f"트럼프 관련 {trump_count}건의 정책 뉴스가 수집되었습니다. 행정명령 및 관세 정책은 글로벌 시장에 직접적인 영향을 미치고 있습니다.")
        # Add top description from trump items
        for item in trump_filtered[:1]:
            desc = item.get("description", "").strip()
            title = item.get("title", "")
            if desc and desc != title and len(desc) > 20:
                analysis_lines.append(f"> 주요 내용: {desc[:200]}")
    if congress_count:
        analysis_lines.append(f"\n미국 의회 거래 {congress_count}건이 보고되었습니다. 의원들의 주식 거래 패턴은 향후 입법 방향을 예측하는 참고 자료가 될 수 있습니다.")
    if korea_count:
        analysis_lines.append(f"\n한국 정치인 관련 {korea_count}건의 재산/거래 소식이 수집되었습니다.")
    if cb_count:
        analysis_lines.append(f"\n중앙은행 정책 관련 {cb_count}건의 뉴스가 수집되었으며, 금리 결정은 채권·주식·암호화폐 시장 전반에 영향을 줍니다.")
        for item in cb_filtered[:1]:
            desc = item.get("description", "").strip()
            title = item.get("title", "")
            if desc and desc != title and len(desc) > 20:
                analysis_lines.append(f"> 주요 내용: {desc[:200]}")
    if not analysis_lines:
        analysis_lines.append("현재 수집된 정치인 거래/정책 데이터가 제한적입니다.")
    analysis_lines.append("")
    analysis_lines.append("> *본 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*")
    content_parts.extend(analysis_lines)

    # References (top 10 only) - collapsible
    if source_links:
        unique_links = []
        seen_links = set()
        for ref in source_links[:10]:
            if ref["link"] not in seen_links:
                seen_links.add(ref["link"])
                unique_links.append(ref)

        ref_count = len(unique_links)
        content_parts.append(f"\n<details><summary>참고 링크 ({ref_count}건)</summary><div class=\"details-content\">\n")
        for idx, ref in enumerate(unique_links, 1):
            content_parts.append(f"{idx}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
        content_parts.append("\n</div></details>")

    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["political-trades", "congress", "sec", "trump", "이재명", "central-bank", "insider-trading"],
        source="consolidated",
        lang="ko",
        slug="daily-political-trades-report",
    )
    if filepath:
        # Mark individual items as seen
        for item in unique_items:
            dedup.mark_seen(item.get("title", ""), item.get("source", ""), today)
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created political trades post: %s", filepath)

    dedup.save()
    logger.info("=== Political trades collection complete ===")


if __name__ == "__main__":
    main()
