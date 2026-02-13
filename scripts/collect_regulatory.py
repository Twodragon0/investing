#!/usr/bin/env python3
"""Collect regulatory news from government agencies and generate Jekyll posts.

Sources:
- US: SEC (Google News proxy), CFTC (official RSS), Federal Reserve (Atom feed)
- Korea: FSC (official RSS), Google News Korean regulatory
- Asia: Japan FSA (official RSS), MAS Singapore (Google News)
- Europe: ESMA, UK FCA (Google News)
"""

import sys
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feed
from common.summarizer import ThemeSummarizer

logger = setup_logging("collect_regulatory")


# Feed definitions: (url, source_name, tags, region)
US_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://news.google.com/rss/search?q=site:sec.gov+crypto+OR+digital+asset&hl=en-US&gl=US&ceid=US:en",
        "SEC (Google News)", ["regulation", "sec", "us"],
    ),
    (
        "https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
        "CFTC Press Releases", ["regulation", "cftc", "us"],
    ),
    (
        "https://www.cftc.gov/RSS/RSSENF/rssenf.xml",
        "CFTC Enforcement", ["regulation", "cftc", "enforcement", "us"],
    ),
    (
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "Federal Reserve", ["regulation", "fed", "us"],
    ),
]

KOREA_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111",
        "금융위원회 보도자료", ["regulation", "fsc", "korea"],
    ),
    (
        "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0112",
        "금융위원회 보도참고", ["regulation", "fsc", "korea"],
    ),
    (
        "https://news.google.com/rss/search?q=금융위원회+가상자산+규제&hl=ko&gl=KR&ceid=KR:ko",
        "한국 금융규제 뉴스", ["regulation", "korea", "가상자산"],
    ),
]

ASIA_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://www.fsa.go.jp/fsaEnNewsList_rss2.xml",
        "Japan FSA", ["regulation", "japan", "fsa"],
    ),
    (
        "https://news.google.com/rss/search?q=MAS+Singapore+crypto+regulation&hl=en-US&gl=US&ceid=US:en",
        "MAS Singapore", ["regulation", "singapore", "mas"],
    ),
]

EUROPE_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://news.google.com/rss/search?q=ESMA+crypto+MiCA+regulation&hl=en-US&gl=US&ceid=US:en",
        "EU ESMA", ["regulation", "eu", "esma", "mica"],
    ),
    (
        "https://news.google.com/rss/search?q=FCA+UK+crypto+regulation&hl=en-US&gl=US&ceid=US:en",
        "UK FCA", ["regulation", "uk", "fca"],
    ),
]


def fetch_region_feeds(
    feeds: List[Tuple[str, str, List[str]]], region: str,
) -> List[Dict[str, Any]]:
    """Fetch all feeds for a given region, tagging items with the region."""
    items = []
    for url, name, tags in feeds:
        fetched = fetch_rss_feed(url, name, tags, limit=10)
        for item in fetched:
            item["region"] = region
        items.extend(fetched)
        time.sleep(1)
    return items


def build_region_section(
    items: List[Dict[str, Any]], region_title: str, source_links: list,
) -> List[str]:
    """Build a markdown table section for a region."""
    lines = [f"\n## {region_title}\n"]
    if not items:
        lines.append("*수집된 항목이 없습니다.*")
        return lines

    lines.append("| # | 제목 | 출처 |")
    lines.append("|---|------|------|")
    for i, item in enumerate(items[:15], 1):
        title = item["title"]
        link = item.get("link", "")
        source = item.get("source", "")
        if link:
            lines.append(f"| {i} | [{title}]({link}) | {source} |")
            source_links.append({"title": title, "link": link, "source": source})
        else:
            lines.append(f"| {i} | {title} | {source} |")
    return lines


def main():
    """Main regulatory news collection routine."""
    logger.info("=== Starting regulatory news collection ===")

    dedup = DedupEngine("regulatory_news_seen.json")
    gen = PostGenerator("regulatory-news")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    # Collect from all regions
    us_items = fetch_region_feeds(US_FEEDS, "미국")
    korea_items = fetch_region_feeds(KOREA_FEEDS, "한국")
    asia_items = fetch_region_feeds(ASIA_FEEDS, "아시아")
    europe_items = fetch_region_feeds(EUROPE_FEEDS, "유럽")

    all_items = us_items + korea_items + asia_items + europe_items
    summarizer = ThemeSummarizer(all_items)

    post_title = f"글로벌 규제 동향 리포트 - {today}"

    if dedup.is_duplicate_exact(post_title, "consolidated", today):
        logger.info("Regulatory post already exists, skipping")
        dedup.save()
        return

    # Region counts
    region_counts = Counter(item.get("region", "기타") for item in all_items)
    source_links: list = []

    content_parts = [
        f"전 세계 금융 규제기관의 최신 동향을 정리합니다. "
        f"총 {len(all_items)}건의 규제 관련 뉴스가 수집되었습니다.\n",
    ]

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="regulatory",
        extra_data={"region_counts": region_counts},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    # Key summary
    content_parts.append("## 핵심 요약\n")
    content_parts.append(f"- **총 수집 건수**: {len(all_items)}건")
    for region, count in region_counts.most_common():
        content_parts.append(f"- **{region}**: {count}건")

    # Distribution chart
    dist = summarizer.generate_distribution_chart()
    if dist:
        content_parts.append(f"\n---\n{dist}")

    # Image — region distribution bar chart
    try:
        from common.image_generator import generate_news_summary_card
        categories = [{"name": region, "count": count} for region, count in region_counts.most_common()]
        if categories:
            img = generate_news_summary_card(categories, today, filename=f"regulatory-summary-{today}.png")
            if img:
                fn = os.path.basename(img)
                web_path = "{{ '/assets/images/generated/" + fn + "' | relative_url }}"
                content_parts.append(f"\n![regulatory-summary]({web_path})\n")
                logger.info("Generated regulatory summary image")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Regulatory summary image failed: %s", e)

    # Region sections
    content_parts.append("\n---")
    content_parts.extend(build_region_section(us_items, "미국 규제 동향", source_links))
    content_parts.append("\n---")
    content_parts.extend(build_region_section(korea_items, "한국 규제 동향", source_links))
    content_parts.append("\n---")
    content_parts.extend(build_region_section(asia_items, "아시아 규제 동향", source_links))
    content_parts.append("\n---")
    content_parts.extend(build_region_section(europe_items, "유럽 규제 동향", source_links))

    # Theme summary
    content_parts.append("\n---")
    theme_summary = summarizer.generate_summary_section()
    if theme_summary:
        content_parts.append(theme_summary)

    # Regulatory insight
    content_parts.append("\n---")
    content_parts.append("\n## 규제 인사이트\n")
    insight_lines = []
    if us_items:
        insight_lines.append(f"미국에서 {len(us_items)}건의 규제 관련 뉴스가 수집되었습니다. SEC, CFTC, Fed 동향을 주시해야 합니다.")
    if korea_items:
        insight_lines.append(f"한국 금융위원회 관련 {len(korea_items)}건의 소식이 있습니다.")
    if asia_items:
        insight_lines.append(f"아시아 지역(일본 FSA, 싱가포르 MAS)에서 {len(asia_items)}건이 수집되었습니다.")
    if europe_items:
        insight_lines.append(f"유럽(ESMA, FCA)에서 {len(europe_items)}건의 규제 뉴스가 확인되었습니다. MiCA 규제 시행에 따른 변화를 모니터링하세요.")
    if not insight_lines:
        insight_lines.append("현재 수집된 규제 뉴스가 제한적입니다.")
    insight_lines.append("")
    insight_lines.append("> *본 규제 동향 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, 법률 자문이 아닙니다. 규제 관련 의사결정은 전문가와 상담하시기 바랍니다.*")
    content_parts.extend(insight_lines)

    # References
    if source_links:
        content_parts.append("\n## 참고 링크\n")
        seen_links: set = set()
        ref_count = 1
        for ref in source_links[:20]:
            if ref["link"] not in seen_links:
                seen_links.add(ref["link"])
                content_parts.append(f"{ref_count}. [{ref['title'][:80]}]({ref['link']}) - {ref['source']}")
                ref_count += 1

    # Data collection timestamp
    content_parts.append(f"\n---\n**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC")

    content = "\n".join(content_parts)

    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["regulation", "sec", "cftc", "fsc", "daily-digest"],
        source="consolidated",
        lang="ko",
        image=f"/assets/images/generated/regulatory-summary-{today}.png",
        slug="daily-regulatory-report",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created regulatory news post: %s", filepath)

    dedup.save()
    logger.info("=== Regulatory news collection complete ===")


if __name__ == "__main__":
    main()
