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

    def generate_executive_summary(self, category_type: str = "general",
                                    extra_data: Dict[str, Any] | None = None) -> str:
        """Generate a TL;DR executive summary section for the top of blog posts.

        Args:
            category_type: One of "crypto", "stock", "regulatory", "social", "market", "security"
            extra_data: Optional dict with market data, region counts, etc.

        Returns:
            Markdown string with blockquote summary + key points table.
        """
        if len(self.items) < 3:
            return ""

        top_themes = self.get_top_themes()
        extra = extra_data or {}
        total = len(self.items)

        # Build narrative summary
        theme_names = [t[0] for t in top_themes[:3]] if top_themes else []
        themes_str = ", ".join(theme_names[:2]) if theme_names else "다양한 이슈"

        # Category-specific opening
        openers = {
            "crypto": f"오늘 암호화폐 시장은 **{themes_str}** 중심으로 {total}건의 뉴스가 수집되었습니다.",
            "stock": f"오늘 주식 시장은 **{themes_str}** 이슈가 부각되며 {total}건의 뉴스가 분석되었습니다.",
            "regulatory": f"글로벌 규제 동향에서 **{themes_str}** 관련 {total}건의 소식이 수집되었습니다.",
            "social": f"소셜 미디어에서 **{themes_str}** 관련 {total}건의 트렌드가 포착되었습니다.",
            "security": f"블록체인 보안 분야에서 {total}건의 사건이 보고되었습니다.",
            "market": f"시장 전반에 걸쳐 **{themes_str}** 이슈가 주도하고 있습니다.",
        }
        opener = openers.get(category_type, f"총 {total}건의 뉴스가 수집되었습니다. **{themes_str}** 관련 이슈가 주목됩니다.")

        lines = ["\n## 한눈에 보기\n"]
        lines.append(f"> {opener}\n")

        # Key points table
        lines.append("| 구분 | 내용 |")
        lines.append("|------|------|")
        lines.append(f"| 수집 건수 | {total}건 |")

        if theme_names:
            lines.append(f"| 주요 테마 | {', '.join(theme_names)} |")

        # Add theme article counts
        if top_themes:
            top_theme = top_themes[0]
            lines.append(f"| 최다 이슈 | {top_theme[2]} {top_theme[0]} ({top_theme[3]}건) |")

        # Category-specific extra rows
        if category_type == "stock" and extra.get("kr_market"):
            kr = extra["kr_market"]
            for name, info in kr.items():
                lines.append(f"| {name} | {info['price']} ({info['change_pct']}) |")

        if category_type == "regulatory" and extra.get("region_counts"):
            regions = extra["region_counts"]
            region_str = ", ".join(f"{r} {c}건" for r, c in regions.most_common())
            lines.append(f"| 지역별 | {region_str} |")

        if category_type == "social" and extra.get("top_keywords"):
            kw_str = ", ".join(f"{kw}({cnt})" for kw, cnt in extra["top_keywords"][:5])
            lines.append(f"| 핫 키워드 | {kw_str} |")

        if category_type == "crypto" and extra.get("top_keywords"):
            kw_str = ", ".join(f"{kw}({cnt})" for kw, cnt in extra["top_keywords"][:5])
            lines.append(f"| 핫 키워드 | {kw_str} |")

        lines.append("")
        return "\n".join(lines)
