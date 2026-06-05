"""ThemedNewsRenderer — extracted from ThemeSummarizer.generate_themed_news_sections.

테마별 뉴스 섹션 마크다운/HTML 렌더링을 ThemeSummarizer로부터 분리한 클래스.
favicon 헬퍼는 ``common.summarizer`` 모듈을 통해 동적으로 호출하여 골든 테스트의
``monkeypatch.setattr("common.summarizer._favicon_url", ...)`` 패치가 그대로 적용되도록 한다.
"""

from typing import Any, Dict, List

from .enrichment import is_logo_like_url
from .markdown_utils import html_source_tag
from .severity import _SEV_BADGE_HTML, _classify_news_severity
from .text_utils import (
    _fix_mistranslations,
    _strip_trailing_artifacts,
    _truncate_sentence,
)
from .themes import ARTICLES_PER_THEME, OVERFLOW_PREVIEW_LIMIT


class ThemedNewsRenderer:
    """ThemeSummarizer.generate_themed_news_sections를 1:1 추출한 렌더러."""

    def __init__(self, items: List[Dict[str, Any]], theme_summarizer: Any):
        """
        Args:
            items: 사전 점수화된 article 리스트
            theme_summarizer: ThemeSummarizer 인스턴스 — _theme_articles, get_top_themes,
                              _generate_theme_subtitle 접근용
        """
        self.items = items
        self._summarizer = theme_summarizer

    def _render_theme_header(
        self,
        name: str,
        emoji: str,
        count: int,
        subtitle: str,
    ) -> List[str]:
        """Build the markdown header lines for a single theme section.

        Returns the list of lines (each already terminated with ``\\n``) so the
        caller can ``lines.extend(...)`` them 1:1 into the section buffer.
        """
        out = [f"### {emoji} {name} ({count}건)\n"]
        if subtitle:
            out.append(f"*{subtitle}*\n")
        return out

    def _render_featured_card(
        self,
        article: Dict[str, Any],
        *,
        num: int,
        title: str,
        description: str,
        orig_title: str,
        theme_key: str,
        sumr_module: Any,
    ) -> str:
        """Build the HTML markup for a single featured card.

        Extracted 1:1 from ``render()`` so the card-building logic stays a
        single side-effect-free function. ``sumr_module`` is the
        ``common.summarizer`` module passed in so ``monkeypatch.setattr`` in
        golden tests applies through the same module attribute lookups as the
        original inline code.
        """
        # Build HTML card for featured item
        link = article.get("link", "")
        source = article.get("source", "")
        from html import escape as _esc

        safe_title = _esc(title, quote=True)
        severity = _classify_news_severity(title, description or "")
        sev_badge = _SEV_BADGE_HTML[severity]
        card_parts = [
            f'<div class="news-card-item news-sev-{severity}">',
            f'<div class="news-card-num">{num}</div>',
        ]

        # Add thumbnail if image available and not a site logo/icon
        image_url = article.get("image", "")
        if image_url and not is_logo_like_url(image_url):
            safe_img = _esc(image_url, quote=True)
            onerr = "this.parentElement.style.display='none'"
            card_parts.append(
                f'<div class="news-card-thumb"><img src="{safe_img}" alt="" loading="lazy" onerror="{onerr}"></div>'
            )
        elif link:
            fav_link = sumr_module._best_favicon_link(article)
            fav = sumr_module._favicon_url(fav_link or link)
            if fav:
                safe_fav = _esc(fav, quote=True)
                card_parts.append(
                    f'<div class="news-card-thumb news-card-thumb--favicon">'
                    f'<img src="{safe_fav}" alt="" loading="lazy">'
                    f"</div>"
                )

        card_parts.append('<div class="news-card-body">')
        card_parts.append(sev_badge)
        if link:
            safe_link = _esc(link, quote=True)
            card_parts.append(
                f'<a href="{safe_link}" class="news-title" target="_blank" rel="noopener noreferrer">{safe_title}</a>'
            )
        else:
            card_parts.append(f'<span class="news-title">{safe_title}</span>')

        if description and description != title and not sumr_module._is_generic_desc(description):
            # Additional boilerplate check for translated descriptions
            if not sumr_module._is_boilerplate_desc(description):
                desc_text = _strip_trailing_artifacts(_truncate_sentence(description, max_len=300))
                if desc_text:
                    card_parts.append(f'<p class="news-desc">{_esc(desc_text, quote=True)}</p>')
        else:
            # Fallback: generate analytical description from title
            fallback_desc = sumr_module._generate_title_based_desc(orig_title, theme_key)
            if fallback_desc:
                card_parts.append(f'<p class="news-desc">{_esc(fallback_desc, quote=True)}</p>')

        if source:
            card_parts.append(html_source_tag(source))

        card_parts.append("</div>")  # close news-card-body
        card_parts.append("</div>")  # close news-card-item
        return "\n".join(card_parts)

    def _render_overflow_section(
        self,
        remaining_links: List[Dict[str, Any]],
        remaining_count: int,
        sumr_module: Any,
    ) -> List[str]:
        """Build the overflow ``<details><summary>...</summary><ol>...</ol></details>`` block.

        Returns the list of lines (each already terminated with ``\\n`` where the
        original inline code emitted ``\\n``) so the caller can ``lines.extend(...)``
        them 1:1 into the section buffer. ``sumr_module`` is the
        ``common.summarizer`` module passed in so ``monkeypatch.setattr`` in
        golden tests applies through the same module attribute lookups as the
        original inline code.
        """
        from html import escape as _esc

        out: List[str] = []
        out.append(
            f"<details><summary>그 외 {remaining_count}건 보기</summary>"
            f'<div class="details-content"><ol class="news-overflow-list">'
        )
        for item in remaining_links[:OVERFLOW_PREVIEW_LIMIT]:
            if isinstance(item, dict):
                t = _esc(item.get("title", ""), quote=True)
                lnk = item.get("link", "")
                img = item.get("image", "")
                src = item.get("source", "")
                thumb_html = ""
                if img and not is_logo_like_url(img):
                    safe_img = _esc(img, quote=True)
                    onerr = "this.parentElement.style.display='none'"
                    thumb_html = (
                        f'<span class="overflow-thumb">'
                        f'<img src="{safe_img}" alt="" loading="lazy"'
                        f' onerror="{onerr}"></span>'
                    )
                elif lnk:
                    fav_link = sumr_module._best_favicon_link(item)
                    fav = sumr_module._favicon_url(fav_link or lnk)
                    if fav:
                        safe_fav = _esc(fav, quote=True)
                        thumb_html = (
                            f'<span class="overflow-thumb overflow-thumb--favicon">'
                            f'<img src="{safe_fav}" alt="" loading="lazy">'
                            f"</span>"
                        )
                src_html = ""
                if src:
                    src_html = f'<span class="overflow-source">{_esc(src, quote=True)}</span>'
                if lnk:
                    safe_link = _esc(lnk, quote=True)
                    out.append(
                        f'<li class="overflow-preview">'
                        f"{thumb_html}"
                        f'<span class="overflow-body">'
                        f'<a href="{safe_link}" target="_blank" rel="noopener noreferrer">{t}</a>'
                        f"{src_html}</span></li>"
                    )
                else:
                    out.append(
                        f'<li class="overflow-preview">'
                        f"{thumb_html}"
                        f'<span class="overflow-body">'
                        f"<span>{t}</span>"
                        f"{src_html}</span></li>"
                    )
        if remaining_count > OVERFLOW_PREVIEW_LIMIT:
            out.append(f"<li><em>...외 {remaining_count - OVERFLOW_PREVIEW_LIMIT}건</em></li>")
        out.append("</ol></div></details>\n")
        return out

    @staticmethod
    def _to_overflow_entry(title: str, link: str, article: Dict[str, Any]) -> Dict[str, Any]:
        """Build overflow list entry dict with normalized keys.

        Extracted to avoid duplicate dict literals in render() (cross-theme demote
        path + featured cap overflow path).
        """
        return {
            "title": title,
            "link": link,
            "image": article.get("image", ""),
            "source": article.get("source", ""),
        }

    def render(
        self,
        max_articles: int = ARTICLES_PER_THEME,
        featured_count: int = 3,
    ) -> str:
        """Generate theme-based news sections with cross-theme deduplication.

        Top articles per theme include description summaries in card format.
        Articles already featured (top N) in a previous theme are skipped
        in subsequent themes to avoid repetitive #1 articles.
        Remaining articles are shown in a collapsible <details> block.
        Returns empty string if fewer than 5 items.

        Args:
            max_articles: Maximum total articles to show per theme.
            featured_count: Number of articles to show with full description.
        """
        # Lazy import to avoid circular dependency with summarizer.py and to
        # ensure ``monkeypatch.setattr("common.summarizer._favicon_url", ...)``
        # in golden tests applies — every call goes through the module attr.
        from . import summarizer as _sumr

        if len(self.items) < 5:
            return ""

        top_themes = self._summarizer.get_top_themes()
        if not top_themes:
            return ""

        lines = ["## 테마별 주요 뉴스\n"]

        # Cross-theme dedup: track titles that have been featured (top N)
        # across themes so the same article doesn't appear as #1 everywhere.
        cross_theme_featured: set = set()

        for name, key, emoji, count in top_themes:
            articles = self._summarizer.get_articles_for_theme(key)
            subtitle = self._summarizer._generate_theme_subtitle(key, articles)
            lines.extend(self._render_theme_header(name, emoji, count, subtitle))

            shown = 0
            seen_titles: set = set()
            remaining_links: List[Dict[str, Any]] = []
            for article in articles:
                orig_title = article.get("title", "")
                if not orig_title or orig_title in seen_titles:
                    continue
                if _sumr._NOISE_TITLE_RE.search(orig_title):
                    continue
                seen_titles.add(orig_title)
                title = _fix_mistranslations(article.get("title_ko") or orig_title)
                link = article.get("link", "")
                description = _fix_mistranslations(
                    (article.get("description_ko") or article.get("description", "")).strip()
                )

                # Skip articles already featured in previous themes
                if shown < featured_count and orig_title in cross_theme_featured:
                    # Demote to remaining links instead
                    remaining_links.append(self._to_overflow_entry(title, link, article))
                    continue

                if shown < featured_count:
                    card_html = self._render_featured_card(
                        article,
                        num=shown + 1,
                        title=title,
                        description=description,
                        orig_title=orig_title,
                        theme_key=key,
                        sumr_module=_sumr,
                    )
                    lines.append("")  # blank line before HTML block
                    lines.append(card_html)
                    lines.append("")  # blank line after HTML block
                    cross_theme_featured.add(orig_title)
                else:
                    remaining_links.append(self._to_overflow_entry(title, link, article))

                shown += 1
                # Featured cards stop at max_articles, but keep accumulating
                # remaining_links up to OVERFLOW_PREVIEW_LIMIT so the <details>
                # overflow section renders thumbnails for ~10 items instead of
                # collapsing to a bare "외 N건" stub.
                if shown >= max_articles and len(remaining_links) >= OVERFLOW_PREVIEW_LIMIT:
                    break

            overflow = len([a for a in articles if a.get("title") and a["title"] not in seen_titles])
            remaining_count = len(remaining_links) + overflow
            if remaining_links:
                lines.extend(self._render_overflow_section(remaining_links, remaining_count, _sumr))

            lines.append("")

        return "\n".join(lines)
