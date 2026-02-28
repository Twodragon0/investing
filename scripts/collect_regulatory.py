#!/usr/bin/env python3
"""Collect regulatory news from government agencies and generate Jekyll posts.

Sources:
- US: SEC (Google News proxy), CFTC (official RSS), Federal Reserve (Atom feed)
- Korea: FSC (official RSS), Google News Korean regulatory
- Asia: Japan FSA (official RSS), MAS Singapore (Google News)
- Europe: ESMA, UK FCA (Google News)
"""

import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import setup_logging
from common.dedup import DedupEngine
from common.markdown_utils import html_reference_details, html_source_tag
from common.post_generator import PostGenerator
from common.rss_fetcher import fetch_rss_feed
from common.summarizer import ThemeSummarizer

logger = setup_logging("collect_regulatory")


# Feed definitions: (url, source_name, tags, region)
US_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://news.google.com/rss/search?q=site:sec.gov+crypto+OR+digital+asset&hl=en-US&gl=US&ceid=US:en",
        "SEC (Google News)",
        ["regulation", "sec", "us"],
    ),
    (
        "https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
        "CFTC Press Releases",
        ["regulation", "cftc", "us"],
    ),
    (
        "https://www.cftc.gov/RSS/RSSENF/rssenf.xml",
        "CFTC Enforcement",
        ["regulation", "cftc", "enforcement", "us"],
    ),
    (
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "Federal Reserve",
        ["regulation", "fed", "us"],
    ),
]

KOREA_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111",
        "금융위원회 보도자료",
        ["regulation", "fsc", "korea"],
    ),
    (
        "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0112",
        "금융위원회 보도참고",
        ["regulation", "fsc", "korea"],
    ),
    (
        "https://news.google.com/rss/search?q=금융위원회+가상자산+규제&hl=ko&gl=KR&ceid=KR:ko",
        "한국 금융규제 뉴스",
        ["regulation", "korea", "가상자산"],
    ),
]

ASIA_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://www.fsa.go.jp/fsaEnNewsList_rss2.xml",
        "Japan FSA",
        ["regulation", "japan", "fsa"],
    ),
    (
        "https://news.google.com/rss/search?q=MAS+Singapore+crypto+regulation&hl=en-US&gl=US&ceid=US:en",
        "MAS Singapore",
        ["regulation", "singapore", "mas"],
    ),
]

EUROPE_FEEDS: List[Tuple[str, str, List[str]]] = [
    (
        "https://news.google.com/rss/search?q=ESMA+crypto+MiCA+regulation&hl=en-US&gl=US&ceid=US:en",
        "EU ESMA",
        ["regulation", "eu", "esma", "mica"],
    ),
    (
        "https://news.google.com/rss/search?q=FCA+UK+crypto+regulation&hl=en-US&gl=US&ceid=US:en",
        "UK FCA",
        ["regulation", "uk", "fca"],
    ),
]


def fetch_region_feeds(
    feeds: List[Tuple[str, str, List[str]]],
    region: str,
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
    items: List[Dict[str, Any]],
    region_title: str,
    source_links: list,
) -> List[str]:
    """Build a description card section for a region."""
    lines = [f"\n## {region_title}\n"]
    if not items:
        lines.append("*수집된 항목이 없습니다.*")
        return lines

    for i, item in enumerate(items[:10], 1):
        title = item["title"]
        link = item.get("link", "")
        source = item.get("source", "")
        description = item.get("description", "").strip()

        if link:
            source_links.append({"title": title, "link": link, "source": source})
            lines.append(f"**{i}. [{title}]({link})**")
        else:
            lines.append(f"**{i}. {title}**")
        if description and description != title and i <= 5:
            # Extract first sentence for clean summary
            desc_text = description
            for sep in ["。", ". ", "다. ", "요. "]:
                idx = desc_text.find(sep)
                if 20 < idx < 250:
                    desc_text = desc_text[: idx + len(sep)].strip()
                    break
            else:
                desc_text = desc_text[:200].rsplit(" ", 1)[0] if len(desc_text) > 200 else desc_text
            lines.append(desc_text)
        lines.append(f"{html_source_tag(source)}\n")

    return lines


def main():
    """Main regulatory news collection routine."""
    logger.info("=== Starting regulatory news collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("regulatory_news_seen.json")
    gen = PostGenerator("regulatory-news")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC)

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
            collector="collect_regulatory",
            source_count=source_count,
            unique_items=unique_count,
            post_created=0,
            started_at=started_at,
        )
        dedup.save()
        return

    # Region counts
    region_counts = Counter(item.get("region", "기타") for item in all_items)
    source_links: list = []

    content_parts = [
        f"전 세계 금융 규제기관의 최신 동향을 정리합니다. 총 {len(all_items)}건의 규제 관련 뉴스가 수집되었습니다.\n",
    ]

    # Executive summary (한눈에 보기)
    exec_summary = summarizer.generate_executive_summary(
        category_type="regulatory",
        extra_data={"region_counts": region_counts},
    )
    if exec_summary:
        content_parts.append(exec_summary)

    overall_summary = summarizer.generate_overall_summary_section(extra_data={"region_counts": region_counts})
    if overall_summary:
        content_parts.append(overall_summary)

    # Key summary
    content_parts.append("## 핵심 요약\n")
    content_parts.append(f"- **총 수집 건수**: {len(all_items)}건")
    for region, count in region_counts.most_common():
        content_parts.append(f"- **{region}**: {count}건")

    # Distribution chart
    dist = summarizer.generate_distribution_chart()
    if dist:
        content_parts.append(f"\n---\n{dist}")

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

    # Regulatory insight - impact analysis
    content_parts.append("\n---")
    content_parts.append("\n## 규제 인사이트\n")
    insight_lines = []

    # Regulatory keyword analysis for impact assessment
    _REG_IMPACT_KEYWORDS = {
        "enforcement": "집행",
        "lawsuit": "소송",
        "fine": "벌금",
        "ban": "금지",
        "approval": "승인",
        "license": "라이선스",
        "framework": "프레임워크",
        "compliance": "준수",
        "consultation": "협의",
        "guidance": "가이드라인",
        "제재": "제재",
        "처분": "처분",
        "인가": "인가",
        "허가": "허가",
    }
    impact_counter: Counter = Counter()
    for item in all_items:
        text = (item.get("title", "") + " " + item.get("description", "")).lower()
        for kw, label in _REG_IMPACT_KEYWORDS.items():
            if kw in text:
                impact_counter[label] += 1

    # Market impact mapping
    _REGION_MARKET_IMPACT = {
        "미국": "글로벌 암호화폐·주식 시장",
        "한국": "국내 가상자산·금융 시장",
        "아시아": "아시아-태평양 금융 시장",
        "유럽": "EU 디지털 자산 시장",
    }

    # Cross-region analysis with impact assessment
    active_regions = []
    if us_items:
        active_regions.append(("미국", len(us_items)))
    if korea_items:
        active_regions.append(("한국", len(korea_items)))
    if asia_items:
        active_regions.append(("아시아", len(asia_items)))
    if europe_items:
        active_regions.append(("유럽", len(europe_items)))

    if active_regions:
        # Identify the most active region
        most_active = max(active_regions, key=lambda x: x[1])
        regions_str = ", ".join(f"{r}({c}건)" for r, c in active_regions)
        insight_lines.append(
            f"오늘 {regions_str}에서 총 {len(all_items)}건의 규제 뉴스가 포착되었으며, "
            f"**{most_active[0]}**이 가장 활발합니다."
        )

    # Impact type summary
    enforce_count = 0
    enable_count = 0
    if impact_counter:
        enforcement_types = ["집행", "소송", "벌금", "금지", "제재", "처분"]
        enabling_types = ["승인", "라이선스", "인가", "허가", "프레임워크"]
        enforce_count = sum(impact_counter.get(t, 0) for t in enforcement_types)
        enable_count = sum(impact_counter.get(t, 0) for t in enabling_types)

        if enforce_count > enable_count:
            impact_tone = (
                "집행·제재 성격의 규제가 우세하여, 관련 프로젝트 및 거래소의 컴플라이언스 리스크가 상승하고 있습니다."
            )
        elif enable_count > enforce_count:
            impact_tone = (
                "승인·라이선스 등 시장 참여 확대 방향의 규제가 부각되어, 제도권 진입 기대감이 형성되고 있습니다."
            )
        else:
            impact_tone = "규제 강화와 시장 개방 신호가 혼재하여, 방향성 확인이 필요한 시점입니다."
        top_impacts = ", ".join(f"**{label}**({cnt}건)" for label, cnt in impact_counter.most_common(4))
        insight_lines.append(f"\n**규제 성격 분석**: {top_impacts}. {impact_tone}")

    # Region-specific insights with data-driven content extraction
    def _extract_top_topic(items: list, max_len: int = 80) -> str:
        """Extract the most relevant topic from region items."""
        if not items:
            return ""
        title = items[0].get("title", "")
        return title[:max_len] if title else ""

    if us_items:
        # Extract specific agency mentions
        sec_count = sum(1 for i in us_items if "sec" in " ".join(i.get("tags", [])))
        cftc_count = sum(1 for i in us_items if "cftc" in " ".join(i.get("tags", [])))
        fed_count = sum(1 for i in us_items if "fed" in " ".join(i.get("tags", [])))
        agency_parts = []
        if sec_count:
            agency_parts.append(f"SEC {sec_count}건")
        if cftc_count:
            agency_parts.append(f"CFTC {cftc_count}건")
        if fed_count:
            agency_parts.append(f"Fed {fed_count}건")
        agency_str = f" ({', '.join(agency_parts)})" if agency_parts else ""

        # Dynamic US insight based on dominant agency
        if sec_count > cftc_count and sec_count > fed_count:
            us_focus = "SEC 중심 규제 활동이 집중되어, 증권성 판단과 거래소 등록 이슈가 시장의 핵심 변수입니다."
        elif cftc_count > sec_count:
            us_focus = "CFTC 관련 소식이 부각되어, 파생상품·선물 시장 규제와 디지털 자산 상품 분류가 쟁점입니다."
        elif fed_count > 0:
            us_focus = (
                "Fed 관련 뉴스가 포함되어, 통화정책과 금융 안정성 규제가 디지털 자산 시장 유동성에 영향을 줍니다."
            )
        else:
            us_focus = f"{_REGION_MARKET_IMPACT['미국']}에 직접적 영향을 미치는 규제 변화를 주시해야 합니다."
        top_us = _extract_top_topic(us_items)
        us_topic_note = f" 주요 건: *{top_us}*" if top_us else ""
        insight_lines.append(f"\n**미국**{agency_str}: {us_focus}{us_topic_note}")

    if korea_items:
        fsc_count = sum(1 for i in korea_items if "fsc" in " ".join(i.get("tags", [])))
        va_count = sum(1 for i in korea_items if "가상자산" in (i.get("title", "") + " " + i.get("description", "")))
        kr_detail = f" (금융위 {fsc_count}건 포함)" if fsc_count else ""
        if va_count > 0:
            kr_focus = (
                f"가상자산 관련 규제가 **{va_count}건** 포착되어, "
                "거래소 운영 기준과 이용자 보호 정책 변화를 주시하세요."
            )
        else:
            kr_focus = "금융 규제 전반의 동향이 수집되었으며, 국내 금융시장 제도 변화에 대한 모니터링이 필요합니다."
        top_kr = _extract_top_topic(korea_items)
        kr_topic_note = f" 주요 건: *{top_kr}*" if top_kr else ""
        insight_lines.append(f"\n**한국**{kr_detail}: {kr_focus}{kr_topic_note}")

    if asia_items:
        japan_count = sum(1 for i in asia_items if "japan" in " ".join(i.get("tags", [])))
        sg_count = sum(1 for i in asia_items if "singapore" in " ".join(i.get("tags", [])))
        if japan_count > sg_count:
            asia_focus = (
                f"일본 FSA 관련 {japan_count}건으로, 일본의 Web3 전략과 "
                "스테이블코인 규제 프레임워크가 아태 시장의 기준점이 되고 있습니다."
            )
        elif sg_count > japan_count:
            asia_focus = (
                f"싱가포르 MAS 관련 {sg_count}건으로, MAS의 라이선스 정책이 "
                "아시아 디지털 자산 허브 경쟁의 방향을 결정짓고 있습니다."
            )
        else:
            asia_focus = "일본 FSA와 싱가포르 MAS의 라이선스 정책이 아태 지역 디지털 자산 허브 경쟁의 핵심 변수입니다."
        insight_lines.append(f"\n**아시아**: {asia_focus}")

    if europe_items:
        mica_count = sum(
            1 for i in europe_items if "mica" in (i.get("title", "") + " " + i.get("description", "")).lower()
        )
        if mica_count > 0:
            eu_focus = (
                f"MiCA 관련 뉴스가 **{mica_count}건** 포착되어, "
                "EU의 포괄적 디지털 자산 규제가 본격 시행 단계에 진입했습니다. "
                "스테이블코인 발행사와 거래소의 등록 요건을 확인하세요."
            )
        else:
            eu_focus = (
                "EU와 UK의 규제 동향이 수집되었으며, "
                "ESMA/FCA의 투자자 보호 조치가 글로벌 규제 표준 형성에 영향을 미칩니다."
            )
        insight_lines.append(f"\n**유럽**: {eu_focus}")

    # Cross-region regulatory convergence/divergence analysis
    if len(active_regions) >= 2:
        _CROSS_REGION_TEMPLATES = [
            (
                {"미국", "유럽"},
                enforce_count > enable_count,
                (
                    "미국과 유럽이 동시에 규제 집행을 강화하고 있어, "
                    "글로벌 디지털 자산 시장의 컴플라이언스 비용이 구조적으로 상승하는 구간입니다. "
                    "규제 준수 인프라를 갖춘 프로젝트가 차별화될 수 있습니다."
                ),
            ),
            (
                {"미국", "유럽"},
                enable_count > enforce_count,
                (
                    "미국과 유럽 모두 시장 개방 방향의 규제를 추진하여, "
                    "기관 자금의 디지털 자산 진입이 가속화될 수 있습니다. "
                    "ETF·커스터디·스테이블코인 분야에 주목하세요."
                ),
            ),
            (
                {"미국", "한국"},
                True,
                (
                    "미국과 한국의 규제 동향이 동시에 움직여, "
                    "국내 거래소의 해외 서비스 전략과 한미 규제 정합성이 쟁점이 됩니다. "
                    "특히 미국 SEC 판례가 국내 규제 방향에 참고 기준이 됩니다."
                ),
            ),
            (
                {"유럽", "아시아"},
                True,
                (
                    "유럽 MiCA와 아시아 라이선스 체계가 동시에 진화하여, "
                    "크로스보더 디지털 자산 서비스의 규제 차익 구조가 변화하고 있습니다."
                ),
            ),
            (
                {"미국", "아시아"},
                True,
                (
                    "미국 규제 동향과 아시아 허브 경쟁이 맞물려, "
                    "미국 규제 불확실성을 피한 프로젝트의 아시아 이전 가능성이 부각됩니다."
                ),
            ),
            (
                {"한국", "아시아"},
                True,
                (
                    "한국과 아시아 역내 규제 동향이 함께 포착되어, "
                    "아태 지역 가상자산 규제 협력과 상호 인정 프레임워크 논의에 주목하세요."
                ),
            ),
        ]

        active_set = {r for r, _ in active_regions}
        cross_text = None
        for required_regions, condition, template in _CROSS_REGION_TEMPLATES:
            if required_regions.issubset(active_set) and condition:
                cross_text = template
                break

        if not cross_text:
            if all(r[1] >= 3 for r in active_regions):
                cross_text = (
                    f"**{len(active_regions)}개 지역**에서 동시에 활발한 규제 논의가 진행 중입니다. "
                    "이는 글로벌 규제 동조화 경향을 시사하며, "
                    "어느 한 지역의 규제 변화가 다른 지역의 후속 조치를 촉발할 가능성이 높습니다."
                )
            else:
                dominant = max(active_regions, key=lambda x: x[1])
                cross_text = (
                    f"**{dominant[0]}** 중심({dominant[1]}건)의 규제 이벤트가 "
                    "다른 지역의 후속 정책에 영향을 줄 수 있습니다."
                )
        insight_lines.append(f"\n**지역간 규제 연동**: {cross_text}")

    if not insight_lines:
        insight_lines.append("현재 수집된 규제 뉴스가 제한적입니다.")
    insight_lines.append("")
    insight_lines.append(
        "> *본 규제 동향 리포트는 자동 수집된 데이터를 기반으로 생성되었으며, "
        "법률 자문이 아닙니다. 규제 관련 의사결정은 전문가와 상담하시기 바랍니다.*"
    )
    content_parts.extend(insight_lines)

    # References
    if source_links:
        seen_links: set = set()
        unique_refs = []
        for ref in source_links[:20]:
            if ref["link"] not in seen_links:
                seen_links.add(ref["link"])
                unique_refs.append(ref)

        if unique_refs:
            content_parts.append("\n## 참고 링크\n")
            content_parts.append(
                html_reference_details(
                    "참고 링크",
                    unique_refs,
                    limit=20,
                    title_max_len=80,
                )
            )

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
        image="/assets/images/og-default.png",
        slug="daily-regulatory-report",
    )
    if filepath:
        dedup.mark_seen(post_title, "consolidated", today)
        logger.info("Created regulatory news post: %s", filepath)

    dedup.save()
    logger.info("=== Regulatory news collection complete ===")
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
        collector="collect_regulatory",
        source_count=source_count,
        unique_items=unique_count,
        post_created=1 if filepath else 0,
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
