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
    ]),
    ("DeFi", "defi", "🟣", [
        "defi", "dex", "yield", "lending", "tvl", "liquidity",
        "aave", "uniswap", "compound", "staking",
    ]),
    ("비트코인", "bitcoin", "🟠", [
        "bitcoin", "btc", "mining", "halving", "비트코인", "채굴",
        "satoshi", "lightning network",
    ]),
    ("이더리움", "ethereum", "🔷", [
        "ethereum", "eth", "layer2", "rollup", "이더리움",
        "solidity", "evm", "l2",
    ]),
    ("AI/기술", "ai_tech", "🤖", [
        "ai", "artificial intelligence", "gpu", "인공지능",
        "machine learning", "chatgpt", "nvidia", "반도체",
    ]),
    ("매크로/금리", "macro", "📊", [
        "fed", "interest rate", "inflation", "금리", "한국은행",
        "gdp", "cpi", "fomc", "rate cut", "rate hike", "환율",
    ]),
    ("거래소", "exchange", "🏦", [
        "binance", "coinbase", "exchange", "listing", "거래소",
        "upbit", "bithumb", "bybit", "okx",
    ]),
    ("보안/해킹", "security", "🔴", [
        "hack", "exploit", "vulnerability", "security", "해킹",
        "breach", "phishing", "scam", "rug pull",
    ]),
    ("정치/정책", "politics", "🏛️", [
        "trump", "이재명", "election", "policy", "정책",
        "tariff", "sanction", "congress", "의회", "관세",
    ]),
    ("NFT/Web3", "nft_web3", "🎨", [
        "nft", "metaverse", "web3", "opensea", "메타버스",
        "digital collectible",
    ]),
    ("가격/시장", "price_market", "📈", [
        "price", "rally", "crash", "surge", "plunge", "시세",
        "상승", "하락", "급등", "급락", "폭락", "반등",
    ]),
]

TOP_THEMES_COUNT = 5
ARTICLES_PER_THEME = 5
BAR_WIDTH = 18


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

    def generate_distribution_chart(self) -> str:
        """Generate an ASCII bar chart showing issue distribution.

        Returns empty string if fewer than 5 items.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        total = sum(count for _, _, _, count in top_themes)
        if total == 0:
            return ""

        lines = ["## 이슈 분포 현황\n", "```"]
        max_name_len = max(len(name) for name, _, _, _ in top_themes)

        for name, _key, _emoji, count in top_themes:
            pct = count / max(len(self.items), 1) * 100
            filled = int(pct / 100 * BAR_WIDTH)
            bar = "█" * filled + "░" * (BAR_WIDTH - filled)
            lines.append(f"{name:<{max_name_len}}  {bar}  {pct:4.0f}%  ({count}건)")

        lines.append("```")
        lines.append(f"\n*총 {len(self.items)}건의 뉴스 수집 완료*")
        return "\n".join(lines)

    def generate_themed_news_sections(self, max_articles: int = ARTICLES_PER_THEME) -> str:
        """Generate theme-based news sections with tables.

        Each theme gets its own subsection with a news table.
        Returns empty string if fewer than 5 items.
        """
        if len(self.items) < 5:
            return ""

        top_themes = self.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 카테고리별 주요 뉴스\n"]

        for name, key, emoji, count in top_themes:
            articles = self._theme_articles.get(key, [])
            lines.append(f"### {emoji} {name} ({count}건)\n")
            lines.append("| 제목 | 출처 |")
            lines.append("|------|------|")

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
                    lines.append(f"| [{title}]({link}) | {source} |")
                else:
                    lines.append(f"| {title} | {source} |")
                shown += 1
                if shown >= max_articles:
                    break

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
