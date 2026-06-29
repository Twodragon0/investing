"""generate_daily_summary — 일일 요약 섹션 빌더 (L2).

`generate_daily_summary.py` → `summary_sections.py` 추출 후, 2026-06-29 L2 분리
캠페인으로 leaf 헬퍼를 L0([[summary-text-ko]])·L1([[summary-analysis]])로 내리고
이 모듈은 5개 섹션 빌더(`_build_*`)만 보유한다. 의존 방향 L2→L1→L0(단방향).
메인 모듈/테스트는 gds.<name> 으로 재-export 참조한다.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

from common.entity_extractor import extract_market_signals, group_related_items
from common.markdown_utils import (
    html_report_links,
    markdown_link,
    markdown_table,
    smart_truncate,
)
from common.summary_analysis import (
    _coverage_warnings,
    _extract_category_data_points,
    _find_shared_topics_across_categories,
    _relation_rows,
    _render_generated_image,
)
from common.summary_text_ko import (
    _best_non_noise_title,
    _clean_bullet_text,
    _clean_headline,
    _description_for_korean_item,
    _display_title_for_korean_item,
    _headline_for_korean_summary,
    _is_noise_title,
    _strip_markdown_link,
    _summary_keywords_for_korean,
)
from common.translator import get_display_title

logger = logging.getLogger("daily-summary")


_REPORT_CATEGORY_LABELS = {
    "암호화폐 뉴스": "🪙 암호화폐 뉴스",
    "DeFi TVL 리포트": "🏦 DeFi TVL 리포트",
    "시장 종합 리포트": "📈 시장 종합 리포트",
    "규제 동향": "📋 규제 동향",
    "소셜 미디어": "💬 소셜 미디어",
    "월드모니터 브리핑": "🌍 월드모니터 브리핑",
    "경제 캘린더": "🗓 경제 캘린더",
}


def _build_market_signal_section(all_news_items: List[Dict[str, Any]]) -> List[str]:
    """Build '시장 시그널 분석' section using entity extraction.

    Analyzes all collected news items and returns markdown lines for the section.
    Returns an empty list if there are no items or no signals found.
    """
    if not all_news_items:
        return []

    try:
        signals = extract_market_signals(all_news_items)
    except Exception as e:
        logger.warning("Failed to extract market signals: %s", e)
        return []

    dominant_themes = signals.get("dominant_themes", [])
    entity_freq = signals.get("entity_frequencies", {})
    total = signals.get("total_items", len(all_news_items))

    # Need at least some signal data to render the section
    if not dominant_themes and not any(entity_freq.values()):
        return []

    parts: List[str] = []
    parts.append("## 시장 시그널 분석\n")

    # --- 주요 테마 ---
    if dominant_themes:
        parts.append("### 주요 테마\n")
        theme_rows = []
        for theme, count in dominant_themes[:5]:
            pct = round(count / total * 100) if total else 0
            theme_rows.append([theme, count, f"{pct}%"])
        parts.append(
            markdown_table(
                ["테마", "언급 횟수", "비중"],
                theme_rows,
                aligns=["left", "right", "right"],
            )
        )
        parts.append("")

    # --- 핫 엔티티 ---
    crypto_freq = entity_freq.get("crypto", {})
    stock_freq = entity_freq.get("stock", {})
    person_freq = entity_freq.get("person", {})

    # Canonical name → display label maps (from entity_extractor internals)
    _CRYPTO_LABELS = {
        "bitcoin": "비트코인(BTC)",
        "ethereum": "이더리움(ETH)",
        "xrp": "XRP",
        "solana": "솔라나(SOL)",
        "dogecoin": "도지코인(DOGE)",
        "cardano": "에이다(ADA)",
        "bnb": "BNB",
        "avalanche": "아발란체(AVAX)",
        "polygon": "폴리곤(MATIC)",
        "chainlink": "체인링크(LINK)",
    }
    _STOCK_LABELS = {
        "nvidia": "엔비디아(NVDA)",
        "tesla": "테슬라(TSLA)",
        "apple": "애플(AAPL)",
        "microsoft": "마이크로소프트(MSFT)",
        "amazon": "아마존(AMZN)",
        "google": "구글(GOOGL)",
        "meta": "메타(META)",
        "samsung": "삼성전자",
        "sk_hynix": "SK하이닉스",
    }
    _PERSON_LABELS = {
        "trump": "트럼프",
        "powell": "파월",
        "yellen": "옐런",
        "gensler": "겐슬러",
        "musk": "머스크",
        "buffett": "버핏",
    }

    entity_lines = []

    if crypto_freq:
        top_crypto = list(crypto_freq.items())[:5]
        crypto_str = ", ".join(f"{_CRYPTO_LABELS.get(name, name)} {cnt}회" for name, cnt in top_crypto)
        entity_lines.append(f"- 🪙 **암호화폐**: {crypto_str}")

    if stock_freq:
        top_stock = list(stock_freq.items())[:5]
        stock_str = ", ".join(f"{_STOCK_LABELS.get(name, name)} {cnt}회" for name, cnt in top_stock)
        entity_lines.append(f"- 📈 **주식**: {stock_str}")

    if person_freq:
        top_person = list(person_freq.items())[:5]
        person_str = ", ".join(f"{_PERSON_LABELS.get(name, name)} {cnt}회" for name, cnt in top_person)
        entity_lines.append(f"- 👤 **인물**: {person_str}")

    if entity_lines:
        parts.append("### 핫 엔티티\n")
        parts.extend(entity_lines)
        parts.append("")

    # --- 연관 뉴스 클러스터 ---
    try:
        related_groups = group_related_items(all_news_items, title_key="title")
    except Exception as e:
        logger.warning("Failed to group related items: %s", e)
        related_groups = {}

    # related_groups is dict[label -> list[item]]
    if related_groups:
        parts.append("### 연관 뉴스 클러스터\n")
        rendered = 0
        for label, group_items in list(related_groups.items())[:3]:
            if label == "기타 뉴스":
                continue
            count = len(group_items)
            parts.append(f"**{label}** ({count}건 연관)")
            seen_cluster: set = set()
            for item in group_items[:4]:
                raw_title = item.get("title", "")
                # Strip markdown link syntax to plain text
                plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw_title).strip()
                plain = plain.replace("**", "").strip()
                if not plain or len(plain) < 5:
                    plain = raw_title
                norm = re.sub(r"[^가-힣a-z0-9]", "", plain.lower())
                if norm in seen_cluster:
                    continue
                seen_cluster.add(norm)
                parts.append(f"- {smart_truncate(_headline_for_korean_summary(plain), 80)}")
            parts.append("")
            rendered += 1
            if rendered >= 3:
                break

    return parts


def _build_snapshot_table(
    crypto_summary: Optional[Dict[str, Any]],
    stock_summary: Optional[Dict[str, Any]],
    worldmonitor_summary: Optional[Dict[str, Any]],
    regulatory_summary: Optional[Dict[str, Any]],
    social_summary: Optional[Dict[str, Any]],
    political_summary: Optional[Dict[str, Any]],
) -> List[str]:
    rows = []

    def top_signal(summary: Optional[Dict[str, Any]]) -> str:
        if not summary:
            return "데이터 없음"
        if summary.get("count", 0) == 0:
            return "데이터 없음"

        # Priority 1: market data (price, index values)
        if summary.get("market_data"):
            return smart_truncate(_clean_bullet_text(summary["market_data"][0]), 80)

        # Priority 2: meaningful highlights/key_summary
        hl = summary.get("highlights") or summary.get("key_summary") or []
        for h in hl:
            cleaned = _clean_bullet_text(h)
            # Skip noise: pure count lines, empty signals
            if re.match(r"^[\d,]+건", cleaned) or "수집 건수" in cleaned:
                continue
            if len(cleaned) > 15:
                return smart_truncate(cleaned, 80)

        # Priority 3: top theme + representative headline
        dp = _extract_category_data_points(summary)
        if dp["titles"]:
            headline = _clean_headline(dp["titles"][0])
            if len(headline) > 15 and not _is_noise_title(headline):
                return smart_truncate(headline, 80)

        # Priority 4: theme name with count
        if summary.get("themes"):
            name, cnt = summary["themes"][0]
            return f"{name} {cnt}건"

        return "신호 추출 실패"

    dataset = [
        ("암호화폐", crypto_summary),
        ("주식", stock_summary),
        ("월드모니터", worldmonitor_summary),
        ("규제", regulatory_summary),
        ("소셜", social_summary),
        ("정치인 거래", political_summary),
    ]
    for name, summary in dataset:
        count = summary.get("count", 0) if summary else 0
        has_data = summary is not None and count > 0
        count_display: Any = count if has_data else "-"
        signal = top_signal(summary)
        # When there is no data, collapse into a single clean "데이터 없음" signal
        if not has_data:
            signal = "데이터 없음"
        rows.append([name, count_display, signal])
    return [
        markdown_table(
            ["영역", "수집 건수", "핵심 신호"],
            rows,
            aligns=["left", "right", "left"],
        )
    ]


def _build_overview_section(
    total_count: int,
    priority_items: Dict[str, list],
    theme_payload: list,
    summary_map: Dict[str, Optional[Dict[str, Any]]],
    security_summary: Optional[Dict[str, Any]],
    counts_str: str,
    sentiment: Dict[str, Any],
) -> List[str]:
    """Build the opening overview section (counts, risk level, narrative)."""
    crypto_summary = summary_map.get("crypto")
    stock_summary = summary_map.get("stock")
    regulatory_summary = summary_map.get("regulatory")
    social_summary = summary_map.get("social")
    worldmonitor_summary = summary_map.get("worldmonitor")
    political_summary = summary_map.get("political")

    content_parts: List[str] = []

    # Opening with counts
    count_parts = []
    if crypto_summary and crypto_summary["count"]:
        count_parts.append(f"암호화폐 {crypto_summary['count']}건")
    if stock_summary and stock_summary["count"]:
        count_parts.append(f"주식 {stock_summary['count']}건")
    if security_summary and security_summary["count"]:
        count_parts.append(f"보안 {security_summary['count']}건")
    if regulatory_summary and regulatory_summary["count"]:
        count_parts.append(f"규제 {regulatory_summary['count']}건")
    if social_summary and social_summary["count"]:
        count_parts.append(f"소셜 미디어 {social_summary['count']}건")
    if worldmonitor_summary and worldmonitor_summary["count"]:
        count_parts.append(f"월드모니터 {worldmonitor_summary['count']}건")
    if political_summary and political_summary["count"]:
        count_parts.append(f"정치인 거래 {political_summary['count']}건")

    # NOTE: counts_str is built externally and passed in for consistency with
    # _write_summary_post which also needs it.  The count_parts here are only
    # used to regenerate the same string; we intentionally ignore them so the
    # caller-provided counts_str is authoritative.
    content_parts.append(f"> {counts_str}의 뉴스를 종합 분석한 일일 요약입니다.\n")

    # Calculate risk level
    p0_count = len(priority_items.get("P0", []))
    neg_ratio = 100 - sentiment.get("ratio", 50)
    if p0_count >= 3 or neg_ratio >= 70:
        risk_level, risk_emoji = "높음", "🔴"
    elif p0_count >= 1 or neg_ratio >= 55:
        risk_level, risk_emoji = "주의", "🟡"
    else:
        risk_level, risk_emoji = "안정", "🟢"

    content_parts.append("> **한눈에 보는 시장 상황**")
    content_parts.append(f"> - 총 수집: **{total_count}건**")
    content_parts.append(f"> - 긴급 알림(P0): **{len(priority_items.get('P0', []))}건**")
    content_parts.append(f"> - 중요 뉴스(P1): **{len(priority_items.get('P1', []))}건**")
    content_parts.append(f"> - 리스크 레벨: **{risk_emoji} {risk_level}** (P0 {p0_count}건, 부정비율 {neg_ratio}%)\n")

    content_parts.append("## 전체 뉴스 요약\n")
    # Narrative-style summary
    if theme_payload and len(theme_payload) >= 2:
        theme_count = min(len(theme_payload), 3)
        content_parts.append(f"오늘 총 **{total_count}건**의 뉴스에서 크게 **{theme_count}가지 흐름**이 감지됩니다.\n")
        for i, item in enumerate(theme_payload[:3], 1):
            emoji = item.get("emoji", "•")
            name = item.get("name", "")
            score = item.get("count", 0)
            keywords = _summary_keywords_for_korean(item.get("keywords", [])[:3])
            if keywords:
                content_parts.append(
                    f"{i}. **{emoji} {name}** (신호 강도 {score}): {keywords} 관련 이슈가 집중되고 있습니다."
                )
            else:
                content_parts.append(f"{i}. **{emoji} {name}** (신호 강도 {score})")
        content_parts.append("")
    else:
        content_parts.append(f"총 **{total_count}건**의 뉴스가 수집되었습니다. ({counts_str})\n")

    # Priority signal
    p0_count = len(priority_items.get("P0", []))
    p1_count = len(priority_items.get("P1", []))
    if p0_count or p1_count:
        signal_parts = []
        if p0_count:
            signal_parts.append(f"P0 긴급 {p0_count}건")
        if p1_count:
            signal_parts.append(f"P1 주요 {p1_count}건")
        content_parts.append(f"**핵심 신호**: {', '.join(signal_parts)}이 포착되었습니다.")
    content_parts.append("")

    return content_parts


def _build_briefing_section(
    all_summaries: List[Optional[Dict[str, Any]]],
    all_news_items: list,
    summary_map: Dict[str, Optional[Dict[str, Any]]],
    theme_payload: list,
    sentiment: Dict[str, Any],
    today: str,
    briefing_image: Optional[str],
    priority_items: Dict[str, list],
    summarizer: Any,
) -> List[str]:
    """Build dashboard, executive briefing, themes, and risk memo sections."""
    crypto_summary = summary_map.get("crypto")
    stock_summary = summary_map.get("stock")
    regulatory_summary = summary_map.get("regulatory")
    social_summary = summary_map.get("social")
    worldmonitor_summary = summary_map.get("worldmonitor")
    political_summary = summary_map.get("political")

    total_count = sum(s["count"] for s in all_summaries if s and s.get("count"))

    content_parts: List[str] = []

    content_parts.append("## 종합 대시보드\n")
    content_parts.extend(
        _build_snapshot_table(
            crypto_summary,
            stock_summary,
            worldmonitor_summary,
            regulatory_summary,
            social_summary,
            political_summary,
        )
    )
    content_parts.append("")

    if briefing_image:
        content_parts.append(f'![multi-asset-briefing]({{{{ "{briefing_image}" | relative_url }}}})\n')
    fallback_briefing = _render_generated_image(
        f"news-briefing-daily-{today}.png", "시가총액 기준 상위 10 암호화폐 현황"
    )
    legacy_briefing = _render_generated_image(f"news-briefing-{today}.png", "시가총액 기준 상위 10 암호화폐 현황")
    if not briefing_image and fallback_briefing:
        content_parts.append(fallback_briefing + "\n")
    elif not briefing_image and legacy_briefing:
        content_parts.append(legacy_briefing + "\n")

    heatmap_img = _render_generated_image(f"market-heatmap-{today}.png", "암호화폐 시장 히트맵 (24시간 변동)")
    if heatmap_img:
        content_parts.append(heatmap_img + "\n")

    # Executive briefing: cross-category synthesis with data points
    content_parts.append("## 핵심 브리핑\n")

    # 1. Cross-cutting theme analysis
    cross_topics = _find_shared_topics_across_categories(all_summaries)
    if cross_topics:
        top_cross = cross_topics[:3]
        content_parts.append(f"오늘 **{len(cross_topics)}개 교차 테마**가 복수 카테고리에 걸쳐 감지되었습니다.\n")
        for topic_name, cat_count, cats in top_cross:
            cats_str = ", ".join(cats[:4])
            content_parts.append(f"> - **{topic_name}**: {cat_count}개 영역({cats_str})에서 동시 언급")
        content_parts.append("")

    # 2. Concentration & anomaly detection
    if all_news_items:
        concentration = summarizer.detect_concentration()
        if concentration:
            c_name, _c_key, c_ratio = concentration
            content_parts.append(
                f"> **집중도 경고**: 전체 뉴스의 **{c_ratio:.0%}**가 '{c_name}' 테마에 집중되어 있습니다. "
                f"단일 이벤트 발생 시 시장 변동성이 확대될 수 있으니 관련 포지션을 점검하세요.\n"
            )
        anomalies = summarizer.detect_anomalies()
        for _a_name, _a_key, _a_count, a_desc in anomalies:
            content_parts.append(f"> **이상 탐지**: {a_desc}\n")

    # 3. Sentiment snapshot
    active_categories = sum(1 for s in all_summaries if s and s.get("count", 0) > 0)
    content_parts.append(
        f"**시장 심리**: {sentiment['tone']} "
        f"(긍정 {sentiment['positive']}건 vs 부정 {sentiment['negative']}건, "
        f"긍정 비율 {sentiment['ratio']}%) — "
        f"{active_categories}개 카테고리 {total_count}건 기준\n"
    )

    # Actionable insights based on sentiment
    if sentiment["pos_examples"] or sentiment["neg_examples"]:
        content_parts.append("")
        if sentiment["pos_examples"]:
            content_parts.append(f"  - 긍정 신호: {'; '.join(sentiment['pos_examples'][:2])}")
        if sentiment["neg_examples"]:
            content_parts.append(f"  - 주의 신호: {'; '.join(sentiment['neg_examples'][:2])}")
        content_parts.append("")

    # 4. Per-category one-liner with concrete data
    briefing_lines = []
    category_configs = [
        ("crypto", "암호화폐"),
        ("stock", "주식"),
        ("regulatory", "규제"),
        ("worldmonitor", "월드모니터"),
        ("social", "소셜"),
        ("political", "정치인 거래"),
    ]
    summary_lookup = {
        "crypto": crypto_summary,
        "stock": stock_summary,
        "regulatory": regulatory_summary,
        "worldmonitor": worldmonitor_summary,
        "social": social_summary,
        "political": political_summary,
    }
    for key, label in category_configs:
        s = summary_lookup.get(key)
        if not s or not s.get("count"):
            continue
        dp = _extract_category_data_points(s)
        line_parts = [f"**{label}** {dp['count']}건"]
        if dp["theme_names"]:
            line_parts.append(f"핵심 테마 {', '.join(dp['theme_names'][:3])}")
        if dp["figures"]:
            line_parts.append(f"주요 지표: {dp['figures'][0]}")
        elif dp["titles"]:
            best_title = _best_non_noise_title(dp["titles"])
            if best_title:
                line_parts.append(best_title)
        if dp["titles"]:
            top_title = _best_non_noise_title(dp["titles"])
            if top_title:
                line_parts.append(f"주목: *{smart_truncate(top_title, 60)}*")
        briefing_lines.append("> - " + " — ".join(line_parts))

    if briefing_lines:
        content_parts.extend(briefing_lines)
        content_parts.append("")

    content_parts.append("## 뉴스 내용 기반 핵심 요약\n")
    # sentiment 는 파라미터로 전달되므로 그대로 사용한다.

    if crypto_summary:
        crypto_dp = _extract_category_data_points(crypto_summary)
        crypto_themes = ", ".join(f"{name}({cnt})" for name, cnt in (crypto_summary.get("themes") or [])[:3])
        crypto_detail = ""
        if crypto_themes:
            crypto_detail = f"핵심 테마는 {crypto_themes}."
        if crypto_dp["figures"]:
            crypto_detail += f" 주요 수치: {crypto_dp['figures'][0]}."
        if crypto_dp["titles"]:
            best_crypto_title = _best_non_noise_title(crypto_dp["titles"])
            if best_crypto_title:
                crypto_detail += f" 대표 헤드라인: {best_crypto_title}."
        if not crypto_detail:
            crypto_detail = "세부 데이터 확인 필요."
        content_parts.append(f"- **암호화폐:** {crypto_summary.get('count', 0)}건. {crypto_detail.strip()}")
    if stock_summary:
        stock_dp = _extract_category_data_points(stock_summary)
        stock_detail = ""
        if stock_summary.get("market_data"):
            stock_detail = _clean_bullet_text(stock_summary["market_data"][0]).rstrip(". ") + "."
        if stock_dp["figures"]:
            stock_detail += f" 주요 수치: {stock_dp['figures'][0]}."
        if stock_dp["titles"] and not stock_detail.strip():
            best_stock_title = _best_non_noise_title(stock_dp["titles"])
            if best_stock_title:
                stock_detail = f"대표 헤드라인: {best_stock_title}."
        content_parts.append(
            f"- **주식:** {stock_summary.get('count', 0)}건. "
            f"{stock_detail.strip() if stock_detail.strip() else '시장 데이터 확인 필요.'}"
        )
    if regulatory_summary:
        reg_dp = _extract_category_data_points(regulatory_summary)
        reg_detail = ""
        if reg_dp["titles"]:
            best_reg_title = _best_non_noise_title(reg_dp["titles"])
            if best_reg_title:
                reg_detail = f"주요 이슈: {best_reg_title}."
        if reg_dp["figures"]:
            reg_detail += f" 관련 수치: {reg_dp['figures'][0]}."
        if not reg_detail:
            reg_detail = "정책 공시 및 감독 이슈 중심."
        content_parts.append(f"- **규제:** {regulatory_summary.get('count', 0)}건. {reg_detail.strip()}")
    if social_summary:
        social_dp = _extract_category_data_points(social_summary)
        social_detail = ""
        if social_dp["titles"]:
            best_social_title = _best_non_noise_title(social_dp["titles"])
            if best_social_title:
                social_detail = f"화제 키워드: {best_social_title}."
        if social_dp["figures"]:
            social_detail += f" {social_dp['figures'][0]}."
        if not social_detail:
            social_detail = "소셜 채널 키워드 분석 기반."
        content_parts.append(f"- **소셜:** {social_summary.get('count', 0)}건. {social_detail.strip()}")
    if worldmonitor_summary:
        world_dp = _extract_category_data_points(worldmonitor_summary)
        world_detail = ""
        if world_dp["titles"]:
            best_world_title = _best_non_noise_title(world_dp["titles"])
            if best_world_title:
                world_detail = f"핵심 이슈: {best_world_title}."
        if world_dp["figures"]:
            world_detail += f" {world_dp['figures'][0]}."
        if not world_detail:
            world_detail = "글로벌 이슈 모니터링 기반."
        content_parts.append(f"- **월드모니터:** {worldmonitor_summary.get('count', 0)}건. {world_detail.strip()}")
    if priority_items.get("P0") or priority_items.get("P1"):
        p0_titles = [
            _strip_markdown_link(get_display_title(x)) for x in priority_items.get("P0", [])[:2] if x.get("title")
        ]
        p0_hint = f" 긴급: {', '.join(p0_titles)}." if p0_titles else ""
        content_parts.append(
            f"- **우선순위:** P0 {len(priority_items.get('P0', []))}건, "
            f"P1 {len(priority_items.get('P1', []))}건.{p0_hint}"
        )
    content_parts.append("")

    if theme_payload:
        content_parts.append("## 테마 스냅샷\n")
        theme_rows = []
        for item in theme_payload:
            keywords = _summary_keywords_for_korean(item.get("keywords", []))
            theme_rows.append(
                [
                    f"{item.get('emoji', '•')} {item.get('name', '')}",
                    item.get("count", 0),
                    keywords if keywords else "-",
                ]
            )
        content_parts.append(
            markdown_table(
                ["테마", "신호 강도", "대표 키워드"],
                theme_rows,
                aligns=["left", "right", "left"],
            )
        )
        content_parts.append("")

        # Dynamic risk/opportunity memo based on actual theme data
        content_parts.append("**리스크/기회 메모**")
        top_theme = theme_payload[0]
        top_name = top_theme.get("name", "")
        top_score = top_theme.get("count", 0)

        if top_score >= 30:
            content_parts.append(
                f"- **{top_name}** 테마에 신호가 집중(강도 {top_score})되어 "
                f"관련 자산의 단기 변동성 확대 가능성이 높습니다."
            )
        elif top_score >= 15:
            content_parts.append(
                f"- **{top_name}** 테마가 주도적(강도 {top_score})이며 후속 뉴스에 따라 방향성이 결정될 구간입니다."
            )
        else:
            content_parts.append(
                f"- 뚜렷한 지배 테마 없이 분산된 흐름(최대 강도 {top_score})으로 "
                f"개별 종목/이벤트 중심 대응이 유효합니다."
            )

        # Check policy/regulation overlap
        policy_theme = next(
            (t for t in theme_payload if "정책" in t.get("name", "") or "규제" in t.get("name", "")),
            None,
        )
        if policy_theme and policy_theme.get("count", 0) >= 5:
            content_parts.append(
                f"- 정책/규제 신호(강도 {policy_theme['count']})가 감지되어 이벤트 드리븐 포지션 점검이 필요합니다."
            )

        # Sentiment-driven observation
        if sentiment["ratio"] >= 65:
            content_parts.append(
                f"- 긍정 헤드라인 비율이 {sentiment['ratio']}%로 높아 "
                f"과열 가능성을 역발상 관점에서 점검할 필요가 있습니다."
            )
        elif sentiment["ratio"] <= 35:
            content_parts.append(
                f"- 부정 헤드라인 비율이 {100 - sentiment['ratio']}%로 높아 "
                f"공포 구간 매수 기회 여부를 점검할 수 있습니다."
            )
        content_parts.append("")

    return content_parts


def _iter_priority_items(items: List[Dict[str, Any]], limit: int):
    """우선순위 아이템을 noise 필터 + description 기준 dedup 후 순서대로 yield.

    P0/P1/P2 세 섹션이 공유하던 `[:limit]` 슬라이스 + `_is_noise_title` 필터 +
    `seen` set dedup(정규화 키는 description→title 폴백) 스캐폴딩을 한곳으로 모은다.
    렌더는 섹션별로 다르므로 호출부에 남긴다.
    """
    seen: set = set()
    for item in items[:limit]:
        title = item.get("title", "")
        if _is_noise_title(title):
            continue
        norm = re.sub(r"[^a-z가-힣0-9]", "", item.get("description", title).lower())
        if norm in seen:
            continue
        seen.add(norm)
        yield item


def _headline_bullet(t: str) -> str:
    """타이틀을 한국어 헤드라인 bullet 로 렌더(규제/보안/소셜 공통)."""
    return f"- {_headline_for_korean_summary(t)}"


def _truncate_bullet(t: str) -> str:
    """타이틀을 80자 절단 bullet 로 렌더(월드모니터 전용)."""
    return f"- {smart_truncate(t, 80)}"


def _raw_fallback(h: str) -> str:
    """fallback 항목을 가공 없이 그대로 사용."""
    return h


def _security_fallback(h: str) -> str:
    """보안 key_summary fallback 을 bullet 클린업 + 한국어 헤드라인으로 렌더."""
    return f"- {_headline_for_korean_summary(_clean_bullet_text(h))}"


def _worldmonitor_issue_rows(issues: List[str]) -> List[List[str]]:
    """월드모니터 issues 파이프 행을 [제목, 출처] 표 행으로 변환."""
    rows: List[List[str]] = []
    for row in issues[:3]:
        parts = [p.strip() for p in row.split("|") if p.strip()]
        if len(parts) >= 5:
            rows.append([parts[1], parts[4]])
        elif len(parts) >= 3:
            rows.append([parts[1], parts[2]])
    return rows


def _security_incident_rows(incidents: List[str]) -> List[List[str]]:
    """보안 incidents 파이프 행을 [프로젝트, 피해 규모, 공격 유형] 표 행으로 변환."""
    rows: List[List[str]] = []
    for row in incidents[:3]:
        parts = [p.strip() for p in row.split("|") if p.strip()]
        if len(parts) >= 3:
            rows.append(parts[:3])
    return rows


# 유사 구조 카테고리 섹션 렌더 스펙(규제/월드모니터/보안/소셜).
# 공통 흐름: 헤딩 → 타이틀 블록 → (elif) fallback → (옵션)표 → figures → 상세 링크.
# crypto/stock 은 구조가 달라 본문에 별도 코드로 남긴다.
_CATEGORY_SECTION_SPECS: List[Dict[str, Any]] = [
    {
        "key": "regulatory",
        "heading": "규제 동향",
        "titles_label": "**주요 규제 이슈:**",
        "title_render": _headline_bullet,
        "fallback_keys": ["key_summary"],
        "fallback_render": _raw_fallback,
        "table": None,
        "figures_label": "**관련 수치**",
    },
    {
        "key": "worldmonitor",
        "heading": "월드모니터 브리핑",
        "titles_label": "**주요 글로벌 이슈:**",
        "title_render": _truncate_bullet,
        "fallback_keys": ["key_summary"],
        "fallback_render": _raw_fallback,
        "table": {
            "source_key": "issues",
            "headers": ["제목", "출처"],
            "row_builder": _worldmonitor_issue_rows,
        },
        "figures_label": "**관련 수치**",
    },
    {
        "key": "security",
        "heading": "보안 리포트",
        "titles_label": "**주요 보안 이슈:**",
        "title_render": _headline_bullet,
        "fallback_keys": ["key_summary"],
        "fallback_render": _security_fallback,
        "table": {
            "source_key": "incidents",
            "headers": ["프로젝트", "피해 규모", "공격 유형"],
            "row_builder": _security_incident_rows,
        },
        "figures_label": "**피해 수치**",
    },
    {
        "key": "social",
        "heading": "소셜 미디어 동향",
        "titles_label": "**화제 토픽:**",
        "title_render": _headline_bullet,
        "fallback_keys": ["highlights", "key_summary"],
        "fallback_render": _raw_fallback,
        "table": None,
        "figures_label": "**관련 수치**",
    },
]


def _render_category_section(summary: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    """스펙 기반 카테고리 섹션 렌더. 원래 인라인 코드와 출력이 동일하다."""
    parts: List[str] = []
    parts.append(f"### {spec['heading']} ({summary['count']}건)\n")
    dp = _extract_category_data_points(summary)

    if dp["titles"]:
        parts.append(spec["titles_label"])
        for t in dp["titles"][:3]:
            parts.append(spec["title_render"](t))
        parts.append("")
    else:
        # 타이틀이 없을 때만 fallback 키 체인을 순차 평가(elif 동작 보존).
        for fkey in spec["fallback_keys"]:
            if summary.get(fkey):
                for h in summary[fkey][:3]:
                    parts.append(spec["fallback_render"](h))
                break

    table = spec["table"]
    if table and summary.get(table["source_key"]):
        table_rows = table["row_builder"](summary[table["source_key"]])
        if table_rows:
            parts.append(markdown_table(table["headers"], table_rows))
            parts.append("")

    if dp["figures"]:
        parts.append(f"{spec['figures_label']}: {', '.join(dp['figures'][:2])}\n")

    parts.append(f"[상세 보기]({summary.get('url', '#')})\n")
    return parts


def _build_priority_and_category_sections(
    priority_items: Dict[str, list],
    market_summary: Optional[Dict[str, Any]],
    security_summary: Optional[Dict[str, Any]],
    summary_map: Dict[str, Optional[Dict[str, Any]]],
    post_links: List[Tuple[str, Any, str]],
    all_news_items: list,
) -> List[str]:
    """Build P0 alerts, market overview, indicators, cross-asset, political watch,
    P1 news, category summaries, P2, report links, and signal analysis sections."""
    crypto_summary = summary_map.get("crypto")
    stock_summary = summary_map.get("stock")
    political_summary = summary_map.get("political")
    # 규제/월드모니터/보안/소셜은 _CATEGORY_SECTION_SPECS 루프에서 summary_map/
    # security_summary 를 직접 조회하므로 여기서 로컬 별칭을 두지 않는다.

    content_parts: List[str] = []

    # ═══════════════════════════════════════
    # 1. URGENT ALERTS (P0)
    # ═══════════════════════════════════════
    if priority_items.get("P0"):
        content_parts.append("## 긴급 알림\n")
        content_parts.append("> 즉시 확인이 필요한 긴급 뉴스입니다.\n")
        for item in _iter_priority_items(priority_items["P0"], 5):
            orig_title = item.get("title", "")
            display = _display_title_for_korean_item(item)
            link = item.get("link", "")
            desc = _description_for_korean_item(item)
            # Build alert line: Korean title with link + description summary
            if link:
                title_part = f"[{display}]({link})"
            else:
                title_part = display
            content_parts.append(f"- **{title_part}**")
            # Add description summary if available and different from title
            if desc and desc != display and desc != orig_title and len(desc) > 15:
                desc_short = smart_truncate(desc, 120)
                content_parts.append(f"  > {desc_short}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 2. MARKET OVERVIEW
    # ═══════════════════════════════════════
    if market_summary:
        content_parts.append("## 시장 개요\n")
        if market_summary.get("highlights"):
            for h in market_summary["highlights"]:
                content_parts.append(h)
        elif market_summary.get("exec_summary"):
            for h in market_summary["exec_summary"]:
                content_parts.append(h)
        content_parts.append("")

    # ═══════════════════════════════════════
    # 3. INDICATOR DASHBOARD
    # ═══════════════════════════════════════
    indicator_parts = []
    indicator_rows: List[List[str]] = []

    # Macro indicators from market report
    if market_summary and market_summary.get("indicator_rows"):
        for row in market_summary["indicator_rows"]:
            parts = [p.strip() for p in row.split("|") if p.strip()]
            if len(parts) >= 3:
                indicator_rows.append(parts[:3])

    if indicator_rows:
        indicator_parts.append(markdown_table(["지표", "현재 값", "변동"], indicator_rows))

    # Yield spread
    if market_summary and market_summary.get("yield_section"):
        if indicator_parts:
            indicator_parts.append("")
        indicator_parts.append("**국채 수익률 스프레드:**")
        # Extract just the key info
        for line in market_summary["yield_section"].split("\n"):
            line = line.strip()
            if line.startswith("|") and "스프레드" in line or line.startswith(">"):
                indicator_parts.append(line)

    if indicator_parts:
        content_parts.append("## 지표 대시보드\n")
        content_parts.extend(indicator_parts)
        content_parts.append("")

    relation_rows = _relation_rows(summary_map)
    coverage_notes = _coverage_warnings(summary_map)

    if relation_rows or coverage_notes:
        content_parts.append("## 교차자산 연관성 체크\n")
        content_parts.append("> 뉴스, 주식, 코인, 정치/규제 이벤트를 연결해 당일 리스크/기회 신호를 점검합니다.\n")

        if relation_rows:
            corr_rows = []
            for left, right, score, note in relation_rows:
                corr_rows.append([f"{left} ↔ {right}", score, note])
            content_parts.append(
                markdown_table(
                    ["비교 구간", "연관 점수", "진단"],
                    corr_rows,
                    aligns=["left", "right", "left"],
                )
            )
            content_parts.append("")

            # System risk warning when 3+ pairs show high correlation
            high_relation_count = sum(1 for r in relation_rows if "높음" in r[3])
            if high_relation_count >= 3:
                content_parts.append(
                    "\n> **시스템 리스크 주의**: 3개 이상 자산 쌍에서 높은 연관성이 감지되었습니다. "
                    "단일 이벤트가 복수 시장에 동시 영향을 줄 수 있으니 포트폴리오 분산 상태를 점검하세요.\n"
                )

        if coverage_notes:
            content_parts.append("**데이터 커버리지 경고**")
            content_parts.extend(coverage_notes)
            content_parts.append("")

        # Dynamic operational checklist based on actual relation data
        content_parts.append("**운영 체크리스트**")
        high_pairs = [(left, right, sc, nt) for left, right, sc, nt in relation_rows if sc >= 25]
        mid_pairs = [(left, right, sc, nt) for left, right, sc, nt in relation_rows if 12 <= sc < 25]

        if high_pairs:
            pair_names = ", ".join(f"{left}↔{right}" for left, right, _, _ in high_pairs[:3])
            content_parts.append(
                f"- **높은 연관성 감지**: {pair_names} 구간에서 장중 변동성 확대 가능성이 높아 우선 모니터링 필요"
            )
        if mid_pairs:
            pair_names = ", ".join(f"{left}↔{right}" for left, right, _, _ in mid_pairs[:3])
            content_parts.append(f"- **중간 연관성**: {pair_names} 구간은 후속 이벤트에 따라 연관성 강화 가능")
        if not high_pairs and not mid_pairs:
            content_parts.append(
                "- 교차자산 연관성이 전반적으로 낮아 개별 자산/이벤트 중심의 독립적 대응이 적합합니다."
            )

        # Check specific cross patterns from actual data
        crypto_reg = next(
            (
                (left, right, sc, nt)
                for left, right, sc, nt in relation_rows
                if ("암호화폐" in left and "규제" in right) or ("규제" in left and "암호화폐" in right)
            ),
            None,
        )
        if crypto_reg and crypto_reg[2] >= 12:
            content_parts.append(
                f"- 암호화폐↔규제 연관 점수 {crypto_reg[2]}점: 규제 이벤트가 코인 시장에 직접 영향을 줄 수 있는 구간"
            )
        political_overlap = next(
            ((left, right, sc, nt) for left, right, sc, nt in relation_rows if "정치인" in left or "정치인" in right),
            None,
        )
        if political_overlap and political_overlap[2] >= 12:
            content_parts.append(
                f"- 정치인 거래 연관 점수 {political_overlap[2]}점: 정책 변화에 따른 인사이더 거래 패턴 주시"
            )
        content_parts.append("")

    # ═══════════════════════════════════════
    # 4. POLITICAL WATCH
    # ═══════════════════════════════════════
    if political_summary:
        content_parts.append("---\n")
        content_parts.append("## 정치인 워치\n")
        if political_summary.get("key_summary"):
            for h in political_summary["key_summary"][:5]:
                content_parts.append(h)
        if political_summary.get("highlights"):
            content_parts.append("")
            for h in political_summary["highlights"][:3]:
                content_parts.append(h)
        content_parts.append(f"\n[상세 보기]({political_summary.get('url', '#')})\n")

    # ═══════════════════════════════════════
    # 5. IMPORTANT NEWS (P1)
    # ═══════════════════════════════════════
    if priority_items.get("P1"):
        content_parts.append("---\n")
        content_parts.append("## 중요 뉴스\n")
        content_parts.append("> 규제, ETF, 실적 등 주요 뉴스입니다.\n")
        for item in _iter_priority_items(priority_items["P1"], 7):
            title = item.get("title", "")
            # Ensure P1 items have clickable links
            link = item.get("link", "")
            if link and "[" not in title:
                display = _display_title_for_korean_item(item)
                content_parts.append(f"- {markdown_link(display, link)}")
            else:
                content_parts.append(f"- {_headline_for_korean_summary(title)}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 6. CATEGORY SUMMARIES
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 카테고리별 요약\n")

    # Crypto section with data-driven analysis
    if crypto_summary:
        content_parts.append(f"### 암호화폐 뉴스 ({crypto_summary['count']}건)\n")
        crypto_dp = _extract_category_data_points(crypto_summary)
        if crypto_summary.get("themes"):
            themes_str = ", ".join(f"**{t[0]}**({t[1]}건)" for t in crypto_summary["themes"][:4])
            total_themed = sum(t[1] for t in crypto_summary["themes"])
            if total_themed and crypto_summary["count"]:
                coverage = round(total_themed / crypto_summary["count"] * 100)
                content_parts.append(f"주요 테마: {themes_str} (전체의 {coverage}% 커버)\n")
            else:
                content_parts.append(f"주요 테마: {themes_str}\n")
        # Data points first, then highlights
        if crypto_dp["figures"]:
            content_parts.append(f"**주요 수치**: {', '.join(crypto_dp['figures'][:3])}\n")
        if crypto_dp["titles"]:
            content_parts.append("**대표 헤드라인:**")
            for t in crypto_dp["titles"][:3]:
                content_parts.append(f"- {_headline_for_korean_summary(t)}")
            content_parts.append("")
        elif crypto_summary.get("highlights"):
            for h in crypto_summary["highlights"][:3]:
                content_parts.append(h)
        content_parts.append(f"[상세 보기]({crypto_summary.get('url', '#')})\n")

    # Stock section with market data emphasis
    if stock_summary:
        content_parts.append(f"### 주식 시장 뉴스 ({stock_summary['count']}건)\n")
        stock_dp = _extract_category_data_points(stock_summary)
        seen_stock = set()
        if stock_summary.get("market_data"):
            content_parts.append("**시장 지표:**")
            for md in stock_summary["market_data"][:3]:
                cleaned = _clean_bullet_text(md)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
            content_parts.append("")
        if stock_dp["figures"]:
            fig_str = ", ".join(f for f in stock_dp["figures"][:3] if f not in seen_stock)
            if fig_str:
                content_parts.append(f"**주요 수치**: {fig_str}\n")
        if stock_dp["titles"]:
            content_parts.append("**대표 헤드라인:**")
            for t in stock_dp["titles"][:3]:
                if t not in seen_stock:
                    content_parts.append(f"- {_headline_for_korean_summary(t)}")
                    seen_stock.add(t)
            content_parts.append("")
        elif stock_summary.get("highlights"):
            for h in stock_summary["highlights"][:3]:
                cleaned = _clean_bullet_text(h)
                if cleaned and cleaned not in seen_stock:
                    content_parts.append(f"- {cleaned}")
                    seen_stock.add(cleaned)
        content_parts.append(f"[상세 보기]({stock_summary.get('url', '#')})\n")

    # ── 유사 구조 카테고리(규제/월드모니터/보안/소셜)를 테이블 구동으로 렌더 ──
    # crypto/stock 은 구조(테마 블록·figures 선후·market_data 중복제거)가
    # 달라 별도 코드로 둔다. 아래 4개는 "타이틀 블록 → (옵션)표 → figures" 공통 흐름.
    # security 는 summary_map 밖 별도 인자라 조회용 맵을 보강한다(불변 복사).
    category_lookup = {**summary_map, "security": security_summary}
    for spec in _CATEGORY_SECTION_SPECS:
        summary = category_lookup.get(spec["key"])
        if summary:
            content_parts.extend(_render_category_section(summary, spec))

    # ═══════════════════════════════════════
    # 7. NOTABLE NEWS (P2)
    # ═══════════════════════════════════════
    if priority_items.get("P2"):
        content_parts.append("---\n")
        content_parts.append("## 주목할 소식\n")
        for item in _iter_priority_items(priority_items["P2"], 5):
            title = item.get("title", "")
            content_parts.append(f"- {_headline_for_korean_summary(title)}")
        content_parts.append("")

    # ═══════════════════════════════════════
    # 8. REPORT LINKS
    # ═══════════════════════════════════════
    content_parts.append("---\n")
    content_parts.append("## 상세 리포트 링크\n")
    content_parts.append("관심 영역별 상세 리포트로 바로 이동할 수 있습니다.\n")
    report_rows = []
    for name, count, url in post_links:
        count_str = f"{count}건" if isinstance(count, int) and count > 0 else "-"
        display_name = _REPORT_CATEGORY_LABELS.get(name, name)
        report_rows.append([display_name, count_str, f"[리포트 보기]({url})"])
    if report_rows:
        content_parts.append(html_report_links(report_rows))

    # ═══════════════════════════════════════
    # 9. MARKET SIGNAL ANALYSIS
    # ═══════════════════════════════════════
    signal_section = _build_market_signal_section(all_news_items)
    if signal_section:
        content_parts.append("---\n")
        content_parts.extend(signal_section)

    content_parts.append("\n---\n")
    content_parts.append("*본 요약은 자동 수집된 뉴스 데이터를 기반으로 작성되었으며, 투자 조언이 아닙니다.*")

    return content_parts
