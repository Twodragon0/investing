"""Keyword-based theme summarizer for collected news items.

Classifies news items into predefined themes using keyword matching
and generates markdown summary sections including:
- Issue distribution ASCII bar chart
- Theme-based news grouping with articles per theme
- Top keyword analysis

No LLM or external dependencies required.
"""

import re
import logging
from collections import Counter
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Theme definitions: (theme_name_ko, theme_key, emoji, keywords)
THEMES = [
    ("규제/정책", "regulation", "🔵", [
        "sec", "cftc", "fca", "regulation", "regulatory", "compliance",
        "규제", "금융위", "금감원", "mica", "esma", "mas", "법안", "bill",
        "enforcement", "lawsuit", "소송", "제재",
    ]),
    ("DeFi", "defi", "🟣", [
        "defi", "dex", "yield", "lending", "tvl", "liquidity",
        "aave", "uniswap", "compound", "staking",
        "restaking", "bridge", "swap", "pool", "vault",
    ]),
    ("비트코인", "bitcoin", "🟠", [
        "bitcoin", "btc", "mining", "halving", "비트코인", "채굴",
        "satoshi", "lightning network",
        "ordinals", "runes", "etf",
    ]),
    ("이더리움", "ethereum", "🔷", [
        "ethereum", "eth", "layer2", "rollup", "이더리움",
        "solidity", "evm", "l2",
        "blob", "dencun", "arbitrum", "optimism", "base", "zksync",
    ]),
    ("AI/기술", "ai_tech", "🤖", [
        "ai", "artificial intelligence", "gpu", "인공지능",
        "machine learning", "chatgpt", "nvidia", "반도체",
        "엔비디아", "테슬라", "애플", "마이크로소프트", "구글",
        "openai", "anthropic", "semiconductor", "tsmc",
    ]),
    ("매크로/금리", "macro", "📊", [
        "fed", "interest rate", "inflation", "금리", "한국은행",
        "gdp", "cpi", "fomc", "rate cut", "rate hike", "환율",
        "물가", "실업률", "고용", "소비자물가", "pce",
        "기준금리", "양적완화", "양적긴축", "treasury", "채권",
    ]),
    ("거래소", "exchange", "🏦", [
        "binance", "coinbase", "exchange", "listing", "거래소",
        "upbit", "bithumb", "bybit", "okx",
        "kraken", "상장", "상장폐지", "delisting",
    ]),
    ("보안/해킹", "security", "🔴", [
        "hack", "exploit", "vulnerability", "security", "해킹",
        "breach", "phishing", "scam", "rug pull",
        "drain", "flash loan", "oracle", "재진입",
    ]),
    ("정치/정책", "politics", "🏛️", [
        "trump", "이재명", "election", "policy", "정책",
        "tariff", "sanction", "congress", "의회", "관세",
        "백악관", "대통령", "executive order", "행정명령",
    ]),
    ("NFT/Web3", "nft_web3", "🎨", [
        "nft", "metaverse", "web3", "opensea", "메타버스",
        "digital collectible",
        "gamefi", "socialfi", "creator",
    ]),
    ("가격/시장", "price_market", "📈", [
        "price", "rally", "crash", "surge", "plunge", "시세",
        "상승", "하락", "급등", "급락", "폭락", "반등",
        "bull", "bear", "bullish", "bearish", "강세", "약세",
        "조정", "correction", "코스피", "코스닥", "나스닥",
        "다우존스", "금", "원유", "달러",
    ]),
]

TOP_THEMES_COUNT = 5
ARTICLES_PER_THEME = 5
BAR_WIDTH = 18

# Priority classification keywords
PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    "P0": [
        "crash", "폭락", "hack", "해킹", "executive order", "행정명령",
        "rate decision", "금리 결정", "파산", "bankruptcy", "emergency",
        "긴급", "bank run", "뱅크런", "exploit", "rug pull",
    ],
    "P1": [
        "regulation", "규제", "etf", "approval", "fomc", "tariff", "관세",
        "earnings", "실적", "sanctions", "제재", "indictment", "기소",
        "sec filing", "listing", "상장", "delisting", "상장폐지",
    ],
    "P2": [
        "partnership", "upgrade", "launch", "airdrop", "report",
        "update", "integration", "collaboration", "제휴", "출시",
        "업그레이드", "에어드롭", "리포트",
    ],
}


class ThemeSummarizer:
    """Classify news items into themes and generate markdown summary sections."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self._theme_scores: Dict[str, int] = {}
        self._theme_articles: Dict[str, List[Dict[str, Any]]] = {}
        self._scored = False

    def _ensure_scored(self):
        """Score themes lazily on first access."""
        if self._scored:
            return
        self._score_themes()
        self._scored = True

    def _score_themes(self):
        """Score each theme by keyword frequency across all items."""
        all_text = " ".join(
            (item.get("title", "") + " " + item.get("description", ""))
            for item in self.items
        ).lower()

        token_freq = Counter(re.findall(r"[a-z가-힣]+", all_text))

        for theme_name, theme_key, _emoji, keywords in THEMES:
            score = sum(token_freq.get(kw, 0) for kw in keywords)
            for kw in keywords:
                if " " in kw:
                    score += all_text.count(kw)
            self._theme_scores[theme_key] = score

        # Match articles to themes (each article to its best-matching theme)
        article_assigned: Dict[int, str] = {}
        for theme_name, theme_key, _emoji, keywords in THEMES:
            matched = []
            kw_set = set(keywords)
            for idx, item in enumerate(self.items):
                item_text = (item.get("title", "") + " " + item.get("description", "")).lower()
                if any(kw in item_text for kw in kw_set):
                    matched.append(item)
                    if idx not in article_assigned:
                        article_assigned[idx] = theme_key
            self._theme_articles[theme_key] = matched

    def get_top_themes(self) -> List[Tuple[str, str, str, int]]:
        """Return top themes as (name, key, emoji, article_count) tuples."""
        self._ensure_scored()
        theme_lookup = {key: (name, emoji) for name, key, emoji, _ in THEMES}
        ranked = sorted(self._theme_scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for key, score in ranked:
            if score <= 0:
                continue
            name, emoji = theme_lookup.get(key, (key, ""))
            count = len(self._theme_articles.get(key, []))
            if count > 0:
                result.append((name, key, emoji, count))
            if len(result) >= TOP_THEMES_COUNT:
                break
        return result

    def classify_priority(self) -> Dict[str, List[Dict[str, Any]]]:
        """Classify items into priority buckets (P0, P1, P2).

        Returns dict with keys "P0", "P1", "P2" mapping to lists of items.
        Items are matched by keyword presence in title + description.
        Each item is assigned to only its highest priority bucket.
        """
        result: Dict[str, List[Dict[str, Any]]] = {"P0": [], "P1": [], "P2": []}
        assigned: set = set()

        for priority in ["P0", "P1", "P2"]:
            keywords = PRIORITY_KEYWORDS[priority]
            for idx, item in enumerate(self.items):
                if idx in assigned:
                    continue
                text = (item.get("title", "") + " " + item.get("description", "")).lower()
                if any(kw in text for kw in keywords):
                    result[priority].append(item)
                    assigned.add(idx)

        return result

    # Color classes for theme distribution bars
    _BAR_COLORS = [
        "bar-fill-orange", "bar-fill-blue", "bar-fill-purple",
        "bar-fill-green", "bar-fill-red",
    ]

    def generate_distribution_chart(self) -> str:
        """Generate HTML progress bars for issue distribution.

        Returns empty string if fewer than 5 items.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        total_items = max(len(self.items), 1)

        lines = ['<div class="theme-distribution">']
        for i, (name, _key, emoji, count) in enumerate(top_themes):
            pct = count / total_items * 100
            color = self._BAR_COLORS[i % len(self._BAR_COLORS)]
            lines.append(
                f'<div class="theme-row">'
                f'<span class="theme-label">{emoji} {name}</span>'
                f'<div class="bar-track">'
                f'<div class="{color} bar-fill" style="width:{pct:.0f}%"></div>'
                f'</div>'
                f'<span class="theme-count">{count}건 ({pct:.0f}%)</span>'
                f'</div>'
            )
        lines.append('</div>')
        lines.append(f"\n*총 {len(self.items)}건 수집*\n")
        return "\n".join(lines)

    def generate_themed_news_sections(self, max_articles: int = ARTICLES_PER_THEME,
                                      featured_count: int = 3) -> str:
        """Generate theme-based news sections with description cards.

        Top articles per theme include description summaries in card format.
        Remaining articles are shown in a collapsible <details> block.
        Returns empty string if fewer than 5 items.

        Args:
            max_articles: Maximum total articles to show per theme.
            featured_count: Number of articles to show with full description.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 주요 뉴스\n"]

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            briefing = self._generate_single_theme_briefing(key, articles)
            lines.append(f"### {emoji} {name} ({count}건)\n")
            if briefing:
                lines.append(f"*{briefing}*\n")

            shown = 0
            seen_titles: set = set()
            remaining_links = []
            for article in articles:
                title = article.get("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = article.get("link", "")
                source = article.get("source", "")
                description = article.get("description", "").strip()

                if shown < featured_count:
                    if link:
                        lines.append(f"**{shown + 1}. [{title}]({link})**")
                    else:
                        lines.append(f"**{shown + 1}. {title}**")
                    if description and description != title:
                        desc_text = description[:150]
                        if len(description) > 150:
                            desc_text += "..."
                        lines.append(desc_text)
                    if source:
                        lines.append(
                            f'<span class="source-tag">{source}</span>\n'
                        )
                    else:
                        lines.append("")
                else:
                    if link:
                        remaining_links.append(f'<a href="{link}">{title}</a>')
                    else:
                        remaining_links.append(title)

                shown += 1
                if shown >= max_articles:
                    break

            overflow = len([
                a for a in articles
                if a.get("title") and a["title"] not in seen_titles
            ])
            remaining_count = len(remaining_links) + overflow
            if remaining_links:
                lines.append(
                    f'<details><summary>그 외 {remaining_count}건 보기</summary>'
                    f'<div class="details-content">'
                )
                for link_html in remaining_links[:15]:
                    lines.append(link_html)
                if remaining_count > 15:
                    lines.append(f"<em>...외 {remaining_count - 15}건</em>")
                lines.append('</div></details>\n')

            lines.append("")

        return "\n".join(lines)

    # Stop words to exclude from theme briefing keywords
    _STOP_WORDS = {
        # English
        "stock", "market", "today", "will", "this", "that", "with", "from",
        "have", "been", "were", "what", "when", "where", "which", "while",
        "more", "than", "also", "just", "into", "over", "some", "most",
        "here", "they", "their", "them", "there", "these", "those",
        "about", "after", "before", "could", "would", "should", "other",
        "news", "says", "said", "like", "amid", "near", "latest", "first",
        "last", "next", "week", "year", "days", "time", "back", "still",
        "even", "very", "much", "many", "each", "every", "make", "made",
        "does", "know", "take", "come", "look", "show", "close", "closes",
        "gains", "little", "changed", "under", "posts", "surprise",
        "better", "despite", "price", "update", "updates", "live",
        "report", "check", "according", "report", "following", "based",
        # Korean common
        "관련", "이슈", "뉴스", "시장", "오늘", "최근", "현재",
        "전일", "대비", "분야", "주요", "방안부터", "전망까지", "주요뉴스",
    }

    def _generate_single_theme_briefing(self, theme_key: str,
                                         articles: List[Dict[str, Any]]) -> str:
        """Generate a 1-sentence briefing for a single theme from descriptions."""
        if not articles:
            return ""

        # Collect keywords from top article descriptions
        keywords: List[str] = []
        top_desc = ""
        for article in articles[:5]:
            desc = article.get("description", "").strip()
            title = article.get("title", "")
            text = desc if desc and desc != title else title
            if not top_desc and text:
                top_desc = text[:80]
            # Extract meaningful words (4+ chars), skip stop words
            words = re.findall(r"[a-zA-Z가-힣]{4,}", text)
            words = [w for w in words if w.lower() not in self._STOP_WORDS]
            keywords.extend(words[:3])

        if not keywords:
            return ""

        # Get top 3 unique keywords
        kw_counts = Counter(keywords)
        top_kws = [kw for kw, _ in kw_counts.most_common(8)][:3]
        if not top_kws:
            return ""

        theme_lookup = {key: name for name, key, _, _ in THEMES}
        theme_name = theme_lookup.get(theme_key, theme_key)
        kw_str = ", ".join(top_kws)

        return f"{theme_name} 분야에서 {kw_str} 관련 이슈가 부각되고 있습니다."

    def generate_theme_briefing(self) -> str:
        """Generate combined theme briefings for all top themes.

        Returns a section with 1-2 sentence briefings per theme,
        based on article descriptions.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 브리핑\n"]
        has_content = False

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            briefing = self._generate_single_theme_briefing(key, articles)
            if briefing:
                lines.append(f"- {emoji} **{name}**: {briefing}")
                has_content = True

        if not has_content:
            return ""

        lines.append("")
        return "\n".join(lines)

    def generate_summary_section(self) -> str:
        """Generate a concise markdown theme summary section.

        Returns empty string if fewer than 5 items are available.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["\n## 주요 테마 분석\n"]

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            lines.append(f"### {emoji} {name} ({count}건)\n")

            shown = 0
            seen_titles: set = set()
            for article in articles:
                title = article.get("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = article.get("link", "")
                source = article.get("source", "")
                if link:
                    lines.append(f"- [{title}]({link}) — {source}")
                else:
                    lines.append(f"- {title} — {source}")
                shown += 1
                if shown >= 3:
                    break

            lines.append("")

        return "\n".join(lines)

    def generate_executive_summary(self, category_type: str = "general",
                                    extra_data: Dict[str, Any] | None = None) -> str:
        """Generate an enhanced TL;DR executive summary with HTML components.

        Uses stat grid, theme briefings, and styled P0 alerts.

        Args:
            category_type: One of "crypto", "stock", "regulatory", "social",
                           "market", "security"
            extra_data: Optional dict with market data, region counts, etc.

        Returns:
            Markdown/HTML string with stat grid, briefings, and alerts.
        """
        if len(self.items) < 3:
            return ""

        top_themes = self.get_top_themes()
        extra = extra_data or {}
        total = len(self.items)

        theme_names = [t[0] for t in top_themes[:3]] if top_themes else []
        themes_str = ", ".join(theme_names[:2]) if theme_names else "다양한 이슈"

        openers = {
            "crypto": f"암호화폐 시장 **{themes_str}** 중심 {total}건 분석",
            "stock": f"주식 시장 **{themes_str}** 부각 {total}건 분석",
            "regulatory": f"글로벌 규제 **{themes_str}** 관련 {total}건 수집",
            "social": f"소셜 미디어 **{themes_str}** 관련 {total}건 포착",
            "security": f"보안 분야 {total}건 보고",
            "market": f"시장 전반 **{themes_str}** 주도",
        }
        opener = openers.get(
            category_type,
            f"**{themes_str}** 관련 {total}건 수집",
        )

        lines = ["\n## 한눈에 보기\n"]

        # Stat grid
        stat_items = []
        stat_items.append(
            f'<div class="stat-item">'
            f'<div class="stat-value">{total}</div>'
            f'<div class="stat-label">수집 건수</div></div>'
        )
        if top_themes:
            t = top_themes[0]
            stat_items.append(
                f'<div class="stat-item">'
                f'<div class="stat-value">{t[2]} {t[3]}</div>'
                f'<div class="stat-label">{t[0]}</div></div>'
            )
        # Category-specific stats
        if category_type == "stock" and extra.get("kr_market"):
            kr = extra["kr_market"]
            for mkt_name, info in list(kr.items())[:2]:
                pct = info.get("change_pct", "")
                stat_items.append(
                    f'<div class="stat-item">'
                    f'<div class="stat-value">{info["price"]}</div>'
                    f'<div class="stat-label">{mkt_name} {pct}</div></div>'
                )
        if extra.get("top_keywords"):
            top_kw = extra["top_keywords"][0]
            stat_items.append(
                f'<div class="stat-item">'
                f'<div class="stat-value">{top_kw[0]}</div>'
                f'<div class="stat-label">핫 키워드 ({top_kw[1]}회)</div></div>'
            )
        if category_type == "regulatory" and extra.get("region_counts"):
            regions = extra["region_counts"]
            top_r = regions.most_common(1)[0] if regions else None
            if top_r:
                stat_items.append(
                    f'<div class="stat-item">'
                    f'<div class="stat-value">{top_r[1]}</div>'
                    f'<div class="stat-label">{top_r[0]}</div></div>'
                )

        lines.append(f'<div class="stat-grid">{"".join(stat_items)}</div>\n')

        # Theme briefings as info callout
        briefing_items = []
        for name, key, emoji, count in top_themes[:4]:
            articles = self._theme_articles.get(key, [])
            if not articles:
                continue
            top_desc = ""
            for art in articles[:3]:
                desc = art.get("description", "").strip()
                title = art.get("title", "")
                if desc and desc != title and len(desc) > 20:
                    top_desc = desc[:100]
                    if len(desc) > 100:
                        top_desc += "..."
                    break
            if top_desc:
                briefing_items.append(
                    f"<li>{emoji} <strong>{name}</strong> ({count}건): {top_desc}</li>"
                )
            else:
                briefing_items.append(
                    f"<li>{emoji} <strong>{name}</strong>: {count}건 수집</li>"
                )

        if briefing_items:
            lines.append(
                f'<div class="alert-box alert-info">'
                f'<strong>{opener}</strong>'
                f'<ul>{"".join(briefing_items)}</ul>'
                f'</div>\n'
            )

        # P0 urgent alerts as red callout
        priority_items = self.classify_priority()
        if priority_items.get("P0"):
            p0_items = []
            for item in priority_items["P0"][:3]:
                title = item.get("title", "")
                link = item.get("link", "")
                if link:
                    p0_items.append(f'<li><a href="{link}">{title}</a></li>')
                else:
                    p0_items.append(f"<li>{title}</li>")
            if p0_items:
                lines.append(
                    f'<div class="alert-box alert-urgent">'
                    f'<strong>긴급 알림</strong>'
                    f'<ul>{"".join(p0_items)}</ul>'
                    f'</div>\n'
                )

        return "\n".join(lines)
