#!/usr/bin/env python3
"""Generate weekly digest post with real analysis from the past week's posts.

Enhanced version with:
- Key highlights extraction from post bodies
- Category-wise summaries with insights
- Weekly performance overview
- Actionable takeaways
- Post permalink links in every bullet
- Dynamic SEO description from actual highlights
"""

import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import get_kst_timezone, setup_logging
from common.markdown_utils import smart_truncate
from common.post_generator import PostGenerator

logger = setup_logging("generate_weekly_digest")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")

# ---------------------------------------------------------------------------
# Category display name mapping (Korean)
# ---------------------------------------------------------------------------
CAT_NAMES: Dict[str, str] = {
    "crypto-news": "암호화폐 뉴스",
    "stock-news": "주식 시장",
    "security-alerts": "보안 알림",
    "market-analysis": "시장 분석",
    "crypto-trading-journal": "크립토 트레이딩 일지",
    "stock-trading-journal": "주식 트레이딩 일지",
    "social-media": "소셜 미디어",
    "regulatory-news": "규제 동향",
    "political-trades": "정치인 거래",
    "defi-tvl": "DeFi TVL",
    "defi": "DeFi",
    "defi-yields": "DeFi 수익률",
    "blockchain-report": "블록체인",
    "blockchain": "블록체인",
    "geopolitical-risk": "지정학 리스크",
    "worldmonitor": "글로벌 이슈",
    "market-indicators": "시장 지표",
    "economic-calendar": "경제 캘린더",
}

# ---------------------------------------------------------------------------
# Generic / boilerplate patterns to filter out from bullets
# ---------------------------------------------------------------------------
_GENERIC_PATTERNS = re.compile(
    r"(건의 뉴스를 분석|건 분석했습니다|건의 리포트가 수집|"
    r"자동 수집된 데이터|투자 조언이 아닙니다|"
    r"건을 종합합니다|건 수집$|건의 데이터를 분석|"
    r"Investing Dragon|자동 수집 분석 리포트|"
    r"총 수집 건수:\s*\d+건|^한국:\s*\d+건$|^미국:\s*\d+건$|^아시아:\s*\d+건$|"
    r"^유럽:\s*\d+건$|^기타:\s*\d+건$|"
    r"참고 링크\s*\(\d+건\)|^범위:|수집 건수:|주요 출처:|"
    r"총 \d+건 수집|데이터를 수집했습니다|TVL 데이터를 분석|"
    r"총 시가총액.*BTC 도미넌스|BTC 도미넌스.*총 시가총액|"
    r"\$[\d,]+\s*BTC\s*\([+-]|공포/탐욕\s*\(Extreme|Extreme Fear|Extreme Greed|"
    r"수집 시각:\s*\d{4}|건의 규제 관련 뉴스|보안 관련 뉴스 \d+건|"
    r"블록체인 보안 관련 뉴스)",
    re.IGNORECASE,
)

# Keywords that signal meaningful market insight sentences
_INSIGHT_KEYWORDS = re.compile(
    r"(급등|급락|최고치|신저가|최저|사상|돌파|하락|상승|폭락|폭등|반등|"
    r"조정|매도|매수|공포|탐욕|지지선|저항선|이탈|유입|유출|"
    r"금리|인플레|긴축|완화|인하|인상|위험|리스크|"
    r"\d+[.,]?\d*%|\$[\d,]+)"
)


def parse_post_frontmatter(filepath: str) -> Dict:
    """Parse YAML frontmatter from a markdown post file."""
    result = {
        "title": "",
        "date": "",
        "categories": "",
        "tags": [],
        "excerpt": "",
        "image": "",
        "permalink": "",
        "journal_strategy": "",
        "journal_market_regime": "",
        "journal_day_result": "",
        "journal_trade_count": "",
        "journal_realized_pnl": "",
        "journal_best_trade": "",
        "journal_next_focus": "",
    }
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        # Extract frontmatter between --- markers
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if not match:
            return result

        frontmatter = match.group(1)
        body = match.group(2).strip()
        result["body"] = body

        for line in frontmatter.split("\n"):
            if line.startswith("title:"):
                result["title"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("date:"):
                result["date"] = line.split(":", 1)[1].strip()
            elif line.startswith("categories:"):
                result["categories"] = line.split(":", 1)[1].strip()
            elif line.startswith("tags:"):
                tags_value = line.split(":", 1)[1].strip().strip("[]")
                result["tags"] = [tag.strip().strip('"').strip("'") for tag in tags_value.split(",") if tag.strip()]
            elif line.startswith("excerpt:"):
                result["excerpt"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("image:"):
                result["image"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("permalink:"):
                result["permalink"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_strategy:"):
                result["journal_strategy"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_market_regime:"):
                result["journal_market_regime"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_day_result:"):
                result["journal_day_result"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_trade_count:"):
                result["journal_trade_count"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_realized_pnl:"):
                result["journal_realized_pnl"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_best_trade:"):
                result["journal_best_trade"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("journal_next_focus:"):
                result["journal_next_focus"] = line.split(":", 1)[1].strip().strip('"').strip("'")

        return result
    except Exception as e:
        logger.warning("Failed to parse %s: %s", filepath, e)
        return result


def _get_post_link(post: Dict) -> str:
    """Return the permalink for a post, deriving from filename if missing."""
    permalink = post.get("permalink", "").strip()
    if permalink:
        return permalink

    # Derive from filename: YYYY-MM-DD-slug.md -> /category/YYYY/MM/DD/slug/
    filename = post.get("filename", "")
    cat = post.get("categories", "").strip("[]").strip()
    date_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", filename)
    if date_match:
        year, month, day, slug = date_match.groups()
        cat_path = cat if cat else "posts"
        return f"/{cat_path}/{year}/{month}/{day}/{slug}/"
    return ""


def collect_weekly_posts(days: int = 7) -> List[Dict]:
    """Collect all posts from the past N days."""
    now = datetime.now(get_kst_timezone())
    cutoff = now - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    posts = []
    if not os.path.isdir(POSTS_DIR):
        logger.warning("Posts directory not found: %s", POSTS_DIR)
        return posts

    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue

        # Parse date from filename (YYYY-MM-DD-slug.md)
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", filename)
        if not date_match:
            continue

        file_date = date_match.group(1)
        if file_date < cutoff_str:
            continue

        filepath = os.path.join(POSTS_DIR, filename)
        post_data = parse_post_frontmatter(filepath)
        post_data["filename"] = filename
        post_data["file_date"] = file_date
        posts.append(post_data)

    logger.info("Found %d posts from the past %d days", len(posts), days)
    return posts


def _is_generic_sentence(text: str) -> bool:
    """Return True if the sentence is boilerplate / generic filler."""
    return bool(_GENERIC_PATTERNS.search(text))


def _sentence_score(text: str) -> int:
    """Score a sentence for informativeness. Higher = more valuable."""
    score = 0
    # Reward numeric data (prices, percentages, counts)
    nums = re.findall(r"\d+[.,]?\d*%?", text)
    score += len(nums) * 2
    # Reward insight keywords
    keywords = _INSIGHT_KEYWORDS.findall(text)
    score += len(keywords) * 3
    # Reward $ amounts
    score += len(re.findall(r"\$[\d,.]+[TBMK]?", text)) * 2
    # Penalise very short sentences
    if len(text) < 20:
        score -= 5
    return score


def extract_key_bullets(body: str, max_bullets: int = 3) -> List[str]:
    """Extract key bullet points from a post body.

    Prioritises sentences with numeric data, market insight keywords,
    and filters out generic / boilerplate filler.
    """
    if not body:
        return []

    # Strip HTML tags from body, replacing with spaces to avoid concatenation
    clean_body = re.sub(r"<[^>]+>", " ", body)
    # Collapse multiple spaces
    clean_body = re.sub(r" {2,}", " ", clean_body)

    # --- Strategy 1: "오늘의 핵심" or "핵심" section bullets ---
    core_match = re.search(r"##\s*(?:오늘의\s*)?핵심.*?\n((?:- .+\n?)+)", clean_body)
    if core_match:
        raw = core_match.group(1).strip()
        bullets = []
        for line in raw.split("\n"):
            line = line.strip().lstrip("- ").strip()
            if not line:
                continue
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            if _is_generic_sentence(clean):
                continue
            clean = smart_truncate(clean, 120)
            bullets.append(clean)
            if len(bullets) >= max_bullets:
                break
        if bullets:
            return bullets

    # --- Strategy 2: Collect candidate sentences and rank by score ---
    candidates: List[tuple] = []

    # Gather bullet points and paragraph sentences
    for line in clean_body.split("\n"):
        stripped = line.strip()
        # Skip headings, tables, empty, images, code fences
        if not stripped or stripped.startswith(("#", "|", "!", "---", ">", "```", "*본 분석")):
            continue
        # Handle bullet items
        if stripped.startswith("- "):
            text = stripped[2:].strip()
        else:
            text = stripped
        # Clean markdown formatting
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        text = text.strip()

        if len(text) < 15 or _is_generic_sentence(text):
            continue

        score = _sentence_score(text)
        candidates.append((score, text))

    # Sort by score descending, take top N
    candidates.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    bullets = []
    for _score, text in candidates:
        key = text[:40].lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(smart_truncate(text, 120))
        if len(bullets) >= max_bullets:
            break

    return bullets


def extract_journal_snapshot(post: Dict) -> List[str]:
    strategy = post.get("journal_strategy", "").strip()
    regime = post.get("journal_market_regime", "").strip()
    day_result = post.get("journal_day_result", "").strip()
    trade_count = post.get("journal_trade_count", "").strip()
    realized_pnl = post.get("journal_realized_pnl", "").strip()
    best_trade = post.get("journal_best_trade", "").strip()
    next_focus = post.get("journal_next_focus", "").strip()

    snapshot = []
    if strategy or regime or day_result:
        parts = []
        if strategy:
            parts.append(f"전략: {strategy}")
        if regime:
            parts.append(f"시장 상태: {regime}")
        if day_result:
            parts.append(f"당일 결과: {day_result}")
        snapshot.append(" | ".join(parts))
    if trade_count or realized_pnl:
        parts = []
        if trade_count:
            parts.append(f"거래 횟수: {trade_count}")
        if realized_pnl:
            parts.append(f"실현 손익: {realized_pnl}")
        snapshot.append(" | ".join(parts))
    if best_trade:
        snapshot.append(f"베스트 트레이드: {best_trade}")
    if next_focus:
        snapshot.append(f"다음 세션 포인트: {next_focus}")
    return [item for item in snapshot if item]


def build_journal_performance_section(posts: List[Dict]) -> List[str]:
    journal_posts = [
        post
        for post in posts
        if post.get("categories", "").strip("[]") in {"crypto-trading-journal", "stock-trading-journal"}
    ]
    if not journal_posts:
        return []

    lines = ["## 트레이딩 일지 성과\n"]
    lines.append("| 날짜 | 일지 | 전략 | 결과 | 거래 | 실현 손익 |")
    lines.append("|------|------|------|------|------|-----------|")

    for post in sorted(journal_posts, key=lambda x: x.get("file_date", ""), reverse=True)[:6]:
        category = post.get("categories", "").strip("[]")
        journal_name = "크립토" if category == "crypto-trading-journal" else "주식"
        strategy = smart_truncate(post.get("journal_strategy", "-") or "-", 30)
        result = post.get("journal_day_result", "-") or "-"
        trade_count = post.get("journal_trade_count", "-") or "-"
        realized = post.get("journal_realized_pnl", "-") or "-"
        lines.append(
            f"| {post.get('file_date', '-')} | {journal_name} | {strategy} | {result} | {trade_count} | {realized} |"
        )

        snapshot = extract_journal_snapshot(post)
        if snapshot:
            lines.append(f"- [{post.get('file_date', '-')}] {snapshot[0]}")
            if len(snapshot) > 1:
                lines.append(f"- {snapshot[1]}")
            if post.get("journal_best_trade"):
                lines.append(f"- 베스트 트레이드: {post.get('journal_best_trade')}")
            if post.get("journal_next_focus"):
                lines.append(f"- 다음 세션 포인트: {post.get('journal_next_focus')}")
            lines.append("")

    lines.append('<div class="journal-digest-grid">')
    for post in sorted(journal_posts, key=lambda x: x.get("file_date", ""), reverse=True)[:4]:
        category = post.get("categories", "").strip("[]")
        journal_name = "크립토 트레이딩 일지" if category == "crypto-trading-journal" else "주식 트레이딩 일지"
        excerpt = smart_truncate(post.get("excerpt", "") or post.get("journal_next_focus", ""), 120)
        permalink = post.get("permalink", "") or "#"
        image = post.get("image", "")
        lines.append(f'<a href="{permalink}" class="journal-digest-card">')
        if image:
            lines.append(f'  <img src="{image}" alt="{post.get("title", journal_name)}" class="journal-digest-thumb">')
        lines.append('  <div class="journal-digest-body">')
        lines.append(f'    <span class="journal-digest-kicker">{journal_name}</span>')
        lines.append(f"    <h4>{post.get('title', journal_name)}</h4>")
        lines.append(f"    <p>{excerpt}</p>")
        lines.append('    <div class="journal-digest-meta">')
        lines.append(f"      <span>{post.get('file_date', '-')}</span>")
        lines.append(f"      <span>{post.get('journal_day_result', '-')}</span>")
        lines.append(f"      <span>{post.get('journal_trade_count', '-')}</span>")
        lines.append("    </div>")
        lines.append("  </div>")
        lines.append("</a>")
    lines.append("</div>")

    return lines


def extract_market_data(posts: List[Dict]) -> Dict:
    """Extract market data from market-analysis posts."""
    data: Dict[str, list] = {
        "fear_greed": [],
        "btc_prices": [],
        "total_mcap": [],
        "kr_market": [],
    }

    for post in posts:
        cat = post.get("categories", "").strip("[]")
        body = post.get("body", "")
        date = post.get("file_date", "")

        if cat == "market-analysis":
            # Extract Fear & Greed Index
            fg_match = re.search(r"공포/탐욕 지수:\s*(\d+)/100", body)
            if not fg_match:
                # Also try stat-grid format: 공포/탐욕 (Extreme Fear)
                fg_match2 = re.search(r"stat-value[\"']>\s*(\d+)\s*</div>\s*<div[^>]*>\s*공포/탐욕", body)
                if fg_match2:
                    try:
                        data["fear_greed"].append({"date": date, "value": int(fg_match2.group(1))})
                    except ValueError:
                        pass
            else:
                data["fear_greed"].append({"date": date, "value": int(fg_match.group(1))})

            # Extract BTC price from stat-grid: $70,391 ... BTC (-1.1%)
            btc_stat = re.search(
                r"stat-value[\"']>\s*\$([0-9,]+(?:\.\d+)?)\s*</div>\s*<div[^>]*>\s*BTC\s*\(([^)]+)\)", body
            )
            if btc_stat:
                price_str = btc_stat.group(1).replace(",", "")
                change_str = btc_stat.group(2).strip()
                try:
                    data["btc_prices"].append({"date": date, "price": float(price_str), "change": change_str})
                except ValueError:
                    pass
            else:
                # Fallback: **Bitcoin** $XX,XXX
                btc_match = re.search(r"\*\*Bitcoin\*\*.*?\$([0-9,]+(?:\.\d+)?)", body)
                if btc_match:
                    price_str = btc_match.group(1).replace(",", "")
                    try:
                        data["btc_prices"].append({"date": date, "price": float(price_str), "change": ""})
                    except ValueError:
                        pass

            # Extract total market cap from stat-grid: $2.49T ... 총 시가총액
            mcap_stat = re.search(r"stat-value[\"']>\s*\$([0-9.]+)T\s*</div>\s*<div[^>]*>\s*총 시가총액", body)
            if mcap_stat:
                try:
                    data["total_mcap"].append({"date": date, "value": float(mcap_stat.group(1))})
                except ValueError:
                    pass
            else:
                mcap_match = re.search(r"총 시가총액\s*\|\s*\$([0-9.]+)T", body)
                if mcap_match:
                    try:
                        data["total_mcap"].append({"date": date, "value": float(mcap_match.group(1))})
                    except ValueError:
                        pass

        # Extract Korean market data from stock-news
        if cat == "stock-news":
            kospi_match = re.search(r"KOSPI\s+([0-9,]+(?:\.\d+)?)\s*\(([^)]+)\)", body)
            if kospi_match:
                try:
                    data["kr_market"].append(
                        {
                            "date": date,
                            "kospi": kospi_match.group(1),
                            "kospi_change": kospi_match.group(2),
                        }
                    )
                except (ValueError, IndexError):
                    pass

    return data


def _format_fear_greed_label(value: int) -> str:
    """Return Korean label for Fear & Greed index value."""
    if value <= 20:
        return "극도의 공포"
    if value <= 40:
        return "공포"
    if value <= 60:
        return "중립"
    if value <= 80:
        return "탐욕"
    return "극도의 탐욕"


def _build_dynamic_description(posts: List[Dict], market_data: Dict, categories: Dict[str, List[Dict]]) -> str:
    """Build a dynamic SEO description from actual weekly highlights."""
    parts: List[str] = []

    # BTC price highlight
    if market_data["btc_prices"]:
        latest = market_data["btc_prices"][-1]
        parts.append(f"BTC ${latest['price']:,.0f}")

    # Fear & Greed highlight
    if market_data["fear_greed"]:
        latest_fg = market_data["fear_greed"][-1]
        label = _format_fear_greed_label(latest_fg["value"])
        parts.append(f"{label}({latest_fg['value']})")

    # Korean market highlight
    if market_data["kr_market"]:
        latest_kr = market_data["kr_market"][-1]
        parts.append(f"KOSPI {latest_kr.get('kospi', '')}{latest_kr.get('kospi_change', '')}")

    # Total post count
    parts.append(f"{len(posts)}건 분석")

    desc = ", ".join(parts) + " 주간 다이제스트"

    # Ensure 80+ chars by padding with category info if needed
    if len(desc) < 80:
        cat_names = []
        for cat, cat_posts in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True)[:3]:
            cat_names.append(f"{CAT_NAMES.get(cat, cat)} {len(cat_posts)}건")
        desc += ". " + ", ".join(cat_names)

    return smart_truncate(desc, 160)


def generate_digest(posts: List[Dict]) -> tuple:
    """Generate comprehensive weekly digest content in Korean.

    Returns (content, description) tuple.
    """
    now = datetime.now(get_kst_timezone())
    week_start = (now - timedelta(days=7)).strftime("%m월 %d일")
    week_end = now.strftime("%m월 %d일")

    content_parts = [
        f"이번 주 ({week_start} ~ {week_end}) 투자 시장의 주요 동향과 핵심 이슈를 종합 분석합니다.\n",
    ]

    # Group posts by category
    categories: Dict[str, List[Dict]] = {}
    for post in posts:
        cat = post.get("categories", "기타").strip("[]")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(post)

    # ── 핵심 요약 (stat-grid) ──
    content_parts.append("## 핵심 요약\n")
    content_parts.append('<div class="stat-grid">')
    content_parts.append(
        f'<div class="stat-item"><span class="stat-value">{len(posts)}</span>'
        '<span class="stat-label">총 포스트</span></div>'
    )
    content_parts.append(
        f'<div class="stat-item"><span class="stat-value">{len(categories)}</span>'
        '<span class="stat-label">카테고리</span></div>'
    )
    content_parts.append(
        '<div class="stat-item"><span class="stat-value">7</span><span class="stat-label">분석 일수</span></div>'
    )
    # Top category
    top_cat = max(categories.items(), key=lambda x: len(x[1])) if categories else ("N/A", [])
    top_cat_name = CAT_NAMES.get(top_cat[0], top_cat[0]) if categories else "N/A"
    content_parts.append(
        f'<div class="stat-item"><span class="stat-value">{len(top_cat[1])}</span>'
        f'<span class="stat-label">{top_cat_name}</span></div>'
    )
    content_parts.append("</div>\n")

    # Extract market data for overview
    market_data = extract_market_data(posts)

    # ── Weekly Market Overview (structured table) ──
    content_parts.append("## 주간 시장 개요\n")

    overview_lines: List[str] = []

    # BTC price range with daily breakdown
    if market_data["btc_prices"]:
        prices = [d["price"] for d in market_data["btc_prices"]]
        overview_lines.append(f"| BTC 가격 범위 | ${min(prices):,.0f} ~ ${max(prices):,.0f} |")
        if len(prices) >= 2:
            weekly_change = ((prices[-1] - prices[0]) / prices[0]) * 100
            direction = "+" if weekly_change >= 0 else ""
            overview_lines.append(f"| BTC 주간 변동 | {direction}{weekly_change:.1f}% |")

    # Fear & Greed trend
    if market_data["fear_greed"]:
        fg_values = [d["value"] for d in market_data["fear_greed"]]
        fg_start = market_data["fear_greed"][0]
        fg_end = market_data["fear_greed"][-1]
        start_label = _format_fear_greed_label(fg_start["value"])
        end_label = _format_fear_greed_label(fg_end["value"])
        overview_lines.append(
            f"| 공포/탐욕 지수 | {fg_start['value']} ({start_label}) -> "
            f"{fg_end['value']} ({end_label}), 범위 {min(fg_values)}~{max(fg_values)} |"
        )

    # Total market cap
    if market_data["total_mcap"]:
        mcaps = [d["value"] for d in market_data["total_mcap"]]
        if len(mcaps) >= 2:
            mcap_change = ((mcaps[-1] - mcaps[0]) / mcaps[0]) * 100
            direction = "+" if mcap_change >= 0 else ""
            overview_lines.append(f"| 총 시가총액 | ${mcaps[-1]:.2f}T ({direction}{mcap_change:.1f}%) |")
        else:
            overview_lines.append(f"| 총 시가총액 | ${mcaps[-1]:.2f}T |")

    # Korean market
    if market_data["kr_market"]:
        latest_kr = market_data["kr_market"][-1]
        overview_lines.append(f"| KOSPI | {latest_kr.get('kospi', '-')} ({latest_kr.get('kospi_change', '-')}) |")

    if overview_lines:
        content_parts.append("| 지표 | 값 |")
        content_parts.append("|------|------|")
        content_parts.extend(overview_lines)
        content_parts.append("")

    # Daily BTC snapshot table (if multiple days of data)
    if len(market_data["btc_prices"]) >= 2:
        content_parts.append("### 일별 BTC 스냅샷\n")
        content_parts.append("| 날짜 | BTC 가격 | 변동 |")
        content_parts.append("|------|----------|------|")
        for entry in market_data["btc_prices"]:
            change_str = entry.get("change", "")
            if change_str:
                content_parts.append(f"| {entry['date']} | ${entry['price']:,.0f} | {change_str} |")
            else:
                content_parts.append(f"| {entry['date']} | ${entry['price']:,.0f} | - |")
        content_parts.append("")

    journal_lines = build_journal_performance_section(posts)
    if journal_lines:
        content_parts.extend(journal_lines)
        content_parts.append("")

    # ── Category Sections with Insights + Post Links ──

    # Priority order for categories
    cat_order = [
        "market-analysis",
        "crypto-news",
        "crypto-trading-journal",
        "stock-news",
        "stock-trading-journal",
        "regulatory-news",
        "security-alerts",
    ]

    for cat in cat_order:
        if cat not in categories:
            continue
        cat_posts = categories[cat]
        display_name = CAT_NAMES.get(cat, cat)

        content_parts.append(f"## {display_name} ({len(cat_posts)}건)\n")

        # Collect unique insights across all posts in this category
        seen_insights: set = set()
        insight_count = 0
        max_insights = 8  # Cap total insights per category

        for p in sorted(cat_posts, key=lambda x: x.get("file_date", ""), reverse=True):
            if insight_count >= max_insights:
                break
            date = p.get("file_date", "")
            title = p.get("title", "").strip()
            link = _get_post_link(p)

            if cat in {"crypto-trading-journal", "stock-trading-journal"}:
                bullets = extract_journal_snapshot(p)
            else:
                bullets = extract_key_bullets(p.get("body", ""))

            if bullets:
                for b in bullets:
                    if insight_count >= max_insights:
                        break
                    # Deduplicate by checking first 40 chars
                    key = b[:40].lower()
                    if key in seen_insights:
                        continue
                    seen_insights.add(key)
                    if link:
                        content_parts.append(f"- {date} [{title}]({link}) -- {b}")
                    else:
                        content_parts.append(f"- {date} {b}")
                    insight_count += 1
            elif link:
                # No bullets extracted but still link the post
                key = title[:40].lower()
                if key not in seen_insights:
                    seen_insights.add(key)
                    content_parts.append(f"- {date} [{title}]({link})")
                    insight_count += 1

        if insight_count == 0:
            content_parts.append(f"- {len(cat_posts)}건의 리포트가 수집되었습니다.")
        content_parts.append("")

    # Remaining categories - compact list with links
    for cat, cat_posts in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        if cat in cat_order:
            continue
        display_name = CAT_NAMES.get(cat, cat)
        content_parts.append(f"## {display_name} ({len(cat_posts)}건)\n")
        for p in sorted(cat_posts, key=lambda x: x.get("file_date", ""), reverse=True)[:5]:
            title = p.get("title", "제목 없음")
            date = p.get("file_date", "")
            link = _get_post_link(p)
            if link:
                content_parts.append(f"- {date} [{title}]({link})")
            else:
                content_parts.append(f"- {date} {title}")
        if len(cat_posts) > 5:
            content_parts.append(f"- 외 {len(cat_posts) - 5}건 추가")
        content_parts.append("")

    # ── Weekly Statistics ──
    content_parts.append("## 주간 통계\n")
    content_parts.append(f"- 총 포스트 수: **{len(posts)}건**")
    content_parts.append(f"- 카테고리: **{len(categories)}개**")
    content_parts.append(f"- 기간: {week_start} ~ {week_end}")

    # Post count by category
    content_parts.append("\n| 카테고리 | 포스트 수 |")
    content_parts.append("|----------|----------|")
    for cat, cat_posts in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        display_name = CAT_NAMES.get(cat, cat)
        content_parts.append(f"| {display_name} | {len(cat_posts)}건 |")

    content_parts.append("")
    content_parts.append(
        '<div class="wm-footer-meta">'
        f"생성 시각: {now.strftime('%Y-%m-%d %H:%M')} KST · "
        f"분석 기간: {week_start} ~ {week_end} · "
        "자동 생성 (투자 조언 아님)"
        "</div>"
    )

    content = "\n".join(content_parts)
    description = _build_dynamic_description(posts, market_data, categories)
    return content, description


def main():
    """Main weekly digest generation routine."""
    logger.info("=== Starting weekly digest generation ===")

    now = datetime.now(get_kst_timezone())
    gen = PostGenerator("market-analysis")

    posts = collect_weekly_posts(days=7)
    if not posts:
        logger.info("No posts found for the past week, skipping digest")
        return

    week_str = now.strftime("%Y년 %m월 %d일")
    title = f"주간 투자 다이제스트 - {week_str}"
    content, description = generate_digest(posts)

    filepath = gen.create_post(
        title=title,
        content=content,
        date=now,
        tags=["weekly-digest", "summary", "market-analysis"],
        source="auto-generated",
        lang="ko",
        slug=f"weekly-investment-digest-{now.strftime('%Y-%m-%d')}",
        extra_frontmatter={"description": description},
    )

    if filepath:
        logger.info("Created weekly digest: %s", filepath)
    else:
        logger.info("Weekly digest already exists or skipped")

    logger.info("=== Weekly digest generation complete ===")


if __name__ == "__main__":
    main()
