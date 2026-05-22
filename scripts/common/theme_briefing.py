"""Theme briefing generation extracted from ThemeSummarizer.

Holds the keyword-rich briefing line, description-snippet subtitle, and the
combined "테마별 브리핑" markdown section. ThemeSummarizer keeps thin
delegating wrappers so external callers (themed_news_renderer, tests that
patch the methods on the summarizer instance) keep the same surface.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import TYPE_CHECKING, Any, Dict, List

from .text_utils import _fix_mistranslations
from .themes import _THEME_NAME_KEYWORDS, THEMES

if TYPE_CHECKING:  # pragma: no cover
    from .summarizer import ThemeSummarizer


class ThemeBriefingGenerator:
    """Generate theme-level briefings backed by a ThemeSummarizer instance."""

    def __init__(self, summarizer: ThemeSummarizer) -> None:
        self._ts = summarizer

    def generate_single_theme_briefing(
        self, theme_key: str, articles: List[Dict[str, Any]]
    ) -> str:
        """Generate a keyword-rich 1-line briefing for a single theme.

        Strategy:
        1. Extract top keywords from article titles within this theme.
        2. Combine them into a comma-separated briefing line.
        3. Falls back to the best description snippet if keyword extraction
           yields too few results.
        """
        if not articles:
            return ""

        keywords = self._ts._extract_title_keywords(articles, max_keywords=7)

        filtered_kw: List[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in _THEME_NAME_KEYWORDS and kw_lower != theme_key.lower():
                current_theme_name = ""
                for t_name, t_key, _e, _k in THEMES:
                    if t_key == theme_key:
                        current_theme_name = t_name.lower()
                        break
                if kw_lower not in current_theme_name and kw_lower != theme_key:
                    continue
            filtered_kw.append(kw)
        keywords = filtered_kw

        if len(keywords) >= 2:
            display_kw = self._ts._prepare_display_keywords(keywords, max_keywords=3)
            if not display_kw:
                display_kw = keywords[:3]

            kw_str = ", ".join(display_kw)

            n_articles = len(articles)
            count_str = f"({n_articles}건)"

            _THEME_BRIEFING_CTX: dict[str, list[str]] = {
                "bitcoin": [
                    f"{kw_str} 가격 흐름과 온체인 지표 변화를 함께 확인하세요.",
                    f"{kw_str} 관련 {count_str} 보도 — 거래량과 펀딩비 추이에 주목할 구간입니다.",
                    f"{kw_str} 심리 지표가 변동 중이며, 주요 지지·저항선 근접 여부를 점검하세요.",
                ],
                "ethereum": [
                    f"{kw_str} 생태계 동향 {count_str} — 가스비·TVL 변화를 함께 확인하세요.",
                    f"{kw_str} 네트워크 업데이트와 L2 확장이 가격에 미칠 영향을 주시하세요.",
                ],
                "regulation": [
                    f"{kw_str} 규제 움직임 {count_str} — 시장 접근성과 유동성에 직접적 영향이 예상됩니다.",
                    f"{kw_str} 정책 변화가 감지되어, 관련 자산 규제 리스크를 재점검하세요.",
                ],
                "price_market": [
                    f"{kw_str} 가격 변동 {count_str} — 거래량 대비 변동폭을 확인하고 진입 타이밍을 점검하세요.",
                    f"{kw_str} 시장 흐름이 활발하며, 주요 가격대에서의 매물 분포를 살펴보세요.",
                ],
                "ai_tech": [
                    f"{kw_str} 기술 이슈 {count_str} — 반도체·AI 섹터 실적 영향과 밸류에이션을 점검하세요.",
                    f"{kw_str} 테크 동향이 시장 주도주 교체에 영향을 줄 수 있습니다.",
                ],
                "macro": [
                    f"{kw_str} 매크로 변수 {count_str} — 금리·환율 방향성이 자산 배분에 핵심 변수입니다.",
                    f"{kw_str} 거시경제 지표 발표에 따른 시장 변동성 확대에 대비하세요.",
                ],
                "defi": [
                    f"{kw_str} DeFi 동향 {count_str} — TVL 변화와 프로토콜 수익률을 비교 점검하세요.",
                    f"{kw_str} 탈중앙 금융 이슈가 부각되며 유동성 풀 리밸런싱 여부에 주목하세요.",
                ],
                "politics": [
                    f"{kw_str} 정치 이슈 {count_str} — 정책 불확실성이 시장 방향성에 영향을 줄 수 있습니다.",
                    f"{kw_str} 정치적 변수가 투자 심리에 작용하고 있어, 관련 섹터를 점검하세요.",
                ],
                "security": [
                    f"{kw_str} 보안 이슈 {count_str} — 해킹·사기 사건이 시장 신뢰에 미칠 영향을 확인하세요.",
                    f"{kw_str} 보안 사고가 보고되어, 관련 프로토콜·거래소의 대응을 주시하세요.",
                ],
            }

            today_str = _dt.datetime.now(tz=_dt.UTC).date().isoformat()

            theme_templates = _THEME_BRIEFING_CTX.get(theme_key)
            if theme_templates:
                seed = hash((today_str, theme_key, kw_str))
                return theme_templates[seed % len(theme_templates)]

            templates = [
                f"{kw_str} 흐름이 두드러지며, 추세 전환 신호를 주시할 구간입니다.",
                f"{kw_str} 이슈가 부각되며 해당 섹터의 단기 변동성 확대 가능성이 있습니다.",
                f"{kw_str} 관련 불확실성이 커지고 있어 리스크 관리에 유의하세요.",
                f"{kw_str} 관련 보도가 이어지고 있어 관련 포지션 점검이 필요합니다.",
                f"{kw_str} 이슈에 대한 시장 반응을 모니터링할 필요가 있습니다.",
                f"{kw_str} 관련 지표와 수급 흐름을 함께 확인하세요.",
                f"{kw_str} 동향이 포트폴리오 전략에 영향을 줄 수 있어 주시가 필요합니다.",
                f"{kw_str} 이슈가 시장 구조 변화의 신호일 수 있어 심층 분석이 권장됩니다.",
            ]
            seed = hash((today_str, theme_key, kw_str))
            return templates[seed % len(templates)]

        best_desc = ""
        for article in articles[:5]:
            desc = article.get("description", "").strip()
            title = article.get("title", "")
            text = desc if desc and desc != title and len(desc) > 30 else ""
            if text:
                sentences = re.split(r"(?<=[.!?。])\s+", text)
                snippet = sentences[0] if sentences else text
                if len(snippet) > 150:
                    snippet = snippet[:150].rsplit(" ", 1)[0]
                if len(snippet) > len(best_desc):
                    best_desc = snippet

        if best_desc:
            return best_desc

        for article in articles[:3]:
            title = article.get("title", "").strip()
            if title and len(title) > 15:
                return title

        if keywords:
            return f"주요 키워드: {', '.join(keywords)}"

        return ""

    def generate_theme_subtitle(
        self, theme_key: str, articles: List[Dict[str, Any]]
    ) -> str:
        """Generate a subtitle from the best article description for theme headings.

        Unlike generate_single_theme_briefing which uses keyword analysis,
        this returns a direct description snippet from the top article,
        giving readers a concrete preview of the most important story.
        """
        from .summarizer import _is_generic_desc

        if not articles:
            return ""

        for article in articles[:5]:
            desc = _fix_mistranslations(
                (article.get("description_ko") or article.get("description", "")).strip()
            )
            title = _fix_mistranslations(
                article.get("title_ko") or article.get("title", "")
            )
            if not desc or desc == title or len(desc) < 20:
                continue
            if _is_generic_desc(desc):
                continue
            sentences = re.split(r"(?<=[.!?。다요음])\s+", desc)
            snippet = sentences[0] if sentences else desc
            if len(snippet) > 120:
                snippet = snippet[:117].rsplit(" ", 1)[0] + "..."
            if len(snippet) >= 15:
                return snippet
        return ""

    def generate_theme_briefing(self) -> str:
        """Generate combined theme briefings for all top themes.

        Returns a section with 1-2 sentence briefings per theme,
        based on article descriptions.
        """
        if len(self._ts.items) < 5:
            return ""

        top_themes = self._ts.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 브리핑\n"]
        has_content = False

        for name, key, emoji, _count in top_themes:
            articles = self._ts.get_articles_for_theme(key)
            # Route through summarizer wrapper so tests that monkey-patch
            # ThemeSummarizer._generate_single_theme_briefing keep working.
            briefing = self._ts._generate_single_theme_briefing(key, articles)
            if briefing and briefing.strip() != name and len(briefing.strip()) > len(name):
                lines.append(f"- {emoji} **{name}**: {briefing}")
                has_content = True

        if not has_content:
            return ""

        lines.append("")
        return "\n".join(lines)
