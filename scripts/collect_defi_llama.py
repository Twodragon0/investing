#!/usr/bin/env python3
"""Collect DeFi TVL data from DeFi Llama and generate Jekyll posts.

Sources:
- DeFi Llama API (https://api.llama.fi):
  - GET /v2/protocols - Top protocols by TVL (id, name, symbol, category, tvl, chainTvls, mcap)
  - GET /v2/chains - Chain TVL data (name, tvl, tokenSymbol)
"""

import sys
import os
import json
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.config import setup_logging, get_ssl_verify, REQUEST_TIMEOUT
from common.dedup import DedupEngine
from common.post_generator import PostGenerator
from common.collector_metrics import log_collection_summary
from common.markdown_utils import (
    markdown_link,
    markdown_table,
    html_reference_details,
    html_source_tag,
)

logger = setup_logging("collect_defi_llama")

VERIFY_SSL = get_ssl_verify()
BASE_URL = "https://api.llama.fi"

TOP_PROTOCOLS_LIMIT = 20
TOP_CHAINS_LIMIT = 15


def _format_tvl(tvl: float) -> str:
    """Format TVL value as human-readable string."""
    if tvl >= 1_000_000_000:
        return f"${tvl / 1_000_000_000:.2f}B"
    elif tvl >= 1_000_000:
        return f"${tvl / 1_000_000:.1f}M"
    elif tvl >= 1_000:
        return f"${tvl / 1_000:.1f}K"
    return f"${tvl:.0f}"


def _format_mcap(mcap: Optional[float]) -> str:
    """Format market cap as human-readable string."""
    if mcap is None:
        return "N/A"
    return _format_tvl(mcap)


# Korean vowel endings (모음으로 끝나는 경우)
_KOREAN_VOWEL_ENDINGS = set("aeiouAEIOUyY")
# Korean jamo vowel codepoints: 가(0xAC00) ~ 힣(0xD7A3), check if final consonant (받침) is absent
_HANGUL_START = 0xAC00
_HANGUL_END = 0xD7A3


def _has_batchim(char: str) -> bool:
    """Return True if the Korean syllable has a final consonant (받침)."""
    code = ord(char)
    if _HANGUL_START <= code <= _HANGUL_END:
        return (code - _HANGUL_START) % 28 != 0
    return False


def _korean_ro(word: str) -> str:
    """Return '로' or '으로' postposition based on the last character of *word*.

    Rule:
    - Ends with a vowel → '로'
    - Ends with 'ㄹ' final consonant (받침 ㄹ) → '로'
    - Ends with any other consonant → '으로'
    - English word ending in vowel letter → '로'
    - English word ending in consonant letter → '으로'
    """
    if not word:
        return "으로"
    last = word[-1]
    code = ord(last)
    if _HANGUL_START <= code <= _HANGUL_END:
        if not _has_batchim(last):
            return "로"
        # Check if final consonant is ㄹ (offset 8 in jamo table)
        if (code - _HANGUL_START) % 28 == 8:
            return "로"
        return "으로"
    # ASCII / Latin letters
    if last.lower() in _KOREAN_VOWEL_ENDINGS:
        return "로"
    return "으로"


# ─── TVL staleness tracking ────────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TVL_HISTORY_PATH = os.path.join(_REPO_ROOT, "_state", "defi_tvl_history.json")
_TVL_STALE_DAYS = 3  # warn if total TVL unchanged for this many days


def _load_tvl_history() -> List[Dict[str, Any]]:
    """Load TVL history from state file."""
    if not os.path.exists(_TVL_HISTORY_PATH):
        return []
    try:
        with open(_TVL_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_tvl_history(history: List[Dict[str, Any]]) -> None:
    """Persist TVL history (keep last 30 entries)."""
    os.makedirs(os.path.dirname(_TVL_HISTORY_PATH), exist_ok=True)
    tmp = _TVL_HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history[-30:], f, ensure_ascii=False, indent=2)
        os.replace(tmp, _TVL_HISTORY_PATH)
    except OSError as e:
        logger.warning("Failed to save TVL history: %s", e)


def _check_tvl_staleness(protocols: List[Dict[str, Any]], today: str) -> Optional[str]:
    """Check if total protocol TVL has been identical for _TVL_STALE_DAYS or more.

    Returns a warning string if data appears cached/stale, otherwise None.
    """
    total_tvl = round(sum(p.get("tvl", 0) or 0 for p in protocols), 2)
    history = _load_tvl_history()

    # Update history with today's value
    # Avoid duplicate entries for the same date
    history = [e for e in history if e.get("date") != today]
    history.append({"date": today, "total_tvl": total_tvl})
    _save_tvl_history(history)

    if len(history) < _TVL_STALE_DAYS:
        return None

    # Check last _TVL_STALE_DAYS entries for identical TVL
    recent = sorted(history, key=lambda e: e.get("date", ""), reverse=True)[
        :_TVL_STALE_DAYS
    ]
    unique_values = {e.get("total_tvl") for e in recent}
    if len(unique_values) == 1:
        dates_str = ", ".join(
            e["date"] for e in sorted(recent, key=lambda e: e["date"])
        )
        return (
            f"> **데이터 캐시 경고**: 최근 {_TVL_STALE_DAYS}일({dates_str}) 동안 "
            f"총 TVL이 동일한 값({_format_tvl(total_tvl)})으로 기록되었습니다. "
            "DeFi Llama API 데이터가 캐시되어 있을 수 있으니 참고 바랍니다.\n"
        )
    return None


def fetch_protocols() -> List[Dict[str, Any]]:
    """Fetch top protocols by TVL from DeFi Llama.

    Returns list of dicts with keys: id, name, symbol, category, tvl, chainTvls, mcap, gecko_id
    """
    url = f"{BASE_URL}/v2/protocols"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Unexpected protocols response type: %s", type(data))
            return []

        # Sort by TVL descending and take top N
        protocols = sorted(
            [p for p in data if isinstance(p, dict) and p.get("tvl") is not None],
            key=lambda x: x.get("tvl", 0),
            reverse=True,
        )[:TOP_PROTOCOLS_LIMIT]

        logger.info("DeFi Llama protocols: fetched %d protocols", len(protocols))
        return protocols
    except requests.exceptions.RequestException as e:
        logger.warning("DeFi Llama protocols fetch failed: %s", e)
        return []
    except (ValueError, KeyError) as e:
        logger.warning("DeFi Llama protocols parse failed: %s", e)
        return []


def fetch_chains() -> List[Dict[str, Any]]:
    """Fetch chain TVL data from DeFi Llama.

    Returns list of dicts with keys: name, tvl, tokenSymbol, gecko_id
    """
    url = f"{BASE_URL}/v2/chains"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Unexpected chains response type: %s", type(data))
            return []

        # Sort by TVL descending and take top N
        chains = sorted(
            [c for c in data if isinstance(c, dict) and c.get("tvl") is not None],
            key=lambda x: x.get("tvl", 0),
            reverse=True,
        )[:TOP_CHAINS_LIMIT]

        logger.info("DeFi Llama chains: fetched %d chains", len(chains))
        return chains
    except requests.exceptions.RequestException as e:
        logger.warning("DeFi Llama chains fetch failed: %s", e)
        return []
    except (ValueError, KeyError) as e:
        logger.warning("DeFi Llama chains parse failed: %s", e)
        return []


def generate_tvl_chart_image(
    protocols: List[Dict[str, Any]],
    chains: List[Dict[str, Any]],
    date_str: str,
) -> Optional[str]:
    """Generate a TVL summary dashboard chart image."""
    try:
        from common.image_generator import (
            _MPL_AVAILABLE,
            _FONT_FAMILY,
            COLORS,
            IMAGES_DIR,
            _ensure_dir,
        )

        if not _MPL_AVAILABLE:
            return None

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        _ensure_dir()

        top_protocols = protocols[:10]
        top_chains = chains[:10]

        if not top_protocols and not top_chains:
            return None

        n_rows = max(len(top_protocols), len(top_chains))
        fig_height = 4.5 + n_rows * 0.5
        fig, ax = plt.subplots(figsize=(14, fig_height))
        fig.patch.set_facecolor(COLORS["bg"])
        ax.set_facecolor(COLORS["bg"])
        ax.set_xlim(0, 14)
        ax.set_ylim(0, fig_height)
        ax.axis("off")

        # Title
        ax.text(
            7,
            fig_height - 0.5,
            "DeFi TVL Dashboard",
            ha="center",
            va="center",
            fontsize=20,
            fontweight="bold",
            color=COLORS["text"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            7,
            fig_height - 1.05,
            f"{date_str}  |  Source: DeFi Llama",
            ha="center",
            va="center",
            fontsize=10,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )

        # Total TVL summary badges
        total_tvl = sum(p.get("tvl", 0) or 0 for p in protocols)
        total_chain_tvl = sum(c.get("tvl", 0) or 0 for c in chains)

        # Left badge
        badge_l = mpatches.FancyBboxPatch(
            (0.3, fig_height - 2.0),
            5.8,
            0.6,
            boxstyle="round,pad=0.05",
            facecolor="#1a2332",
            edgecolor=COLORS["blue"],
            linewidth=1.2,
        )
        ax.add_patch(badge_l)
        ax.text(
            3.2,
            fig_height - 1.65,
            f"Protocol TVL: {_format_tvl(total_tvl)}",
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=COLORS["blue"],
            fontfamily=_FONT_FAMILY,
        )

        # Right badge
        badge_r = mpatches.FancyBboxPatch(
            (7.9, fig_height - 2.0),
            5.8,
            0.6,
            boxstyle="round,pad=0.05",
            facecolor="#1a2510",
            edgecolor=COLORS["orange"],
            linewidth=1.2,
        )
        ax.add_patch(badge_r)
        ax.text(
            10.8,
            fig_height - 1.65,
            f"Chain TVL: {_format_tvl(total_chain_tvl)}",
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=COLORS["orange"],
            fontfamily=_FONT_FAMILY,
        )

        y_start = fig_height - 2.7

        # ── Left panel: Top 10 Protocols ──
        ax.text(
            0.3,
            y_start,
            "Top 10 Protocols by TVL",
            fontsize=12,
            fontweight="bold",
            color=COLORS["blue"],
            fontfamily=_FONT_FAMILY,
        )

        y_header = y_start - 0.38
        ax.text(
            0.5,
            y_header,
            "#",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="center",
        )
        ax.text(
            0.85,
            y_header,
            "Protocol",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            3.5,
            y_header,
            "TVL",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="right",
        )
        ax.text(
            4.5,
            y_header,
            "Category",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )
        ax.plot(
            [0.3, 6.4],
            [y_header - 0.14, y_header - 0.14],
            color=COLORS["border"],
            linewidth=0.5,
        )

        for i, protocol in enumerate(top_protocols):
            y = y_header - 0.35 - i * 0.45

            name = (protocol.get("name") or "Unknown")[:16]
            tvl = protocol.get("tvl") or 0
            category = (protocol.get("category") or "")[:14]

            if i % 2 == 0:
                rect = mpatches.FancyBboxPatch(
                    (0.25, y - 0.15),
                    6.15,
                    0.38,
                    boxstyle="round,pad=0.03",
                    facecolor=COLORS["bg_inner"],
                    edgecolor="none",
                    alpha=0.5,
                )
                ax.add_patch(rect)

            rank_colors = {0: COLORS["gold"], 1: COLORS["silver"], 2: COLORS["bronze"]}
            rank_color = rank_colors.get(i, COLORS["text_secondary"])
            ax.text(
                0.5,
                y,
                str(i + 1),
                fontsize=9,
                fontweight="bold",
                color=rank_color,
                ha="center",
                fontfamily=_FONT_FAMILY,
            )
            ax.text(
                0.85, y, name, fontsize=9, color=COLORS["text"], fontfamily=_FONT_FAMILY
            )
            ax.text(
                3.5,
                y,
                _format_tvl(tvl),
                fontsize=9,
                color=COLORS["text"],
                ha="right",
                fontfamily=_FONT_FAMILY,
                fontweight="bold",
            )
            ax.text(
                4.5,
                y,
                category,
                fontsize=8,
                color=COLORS["text_secondary"],
                fontfamily=_FONT_FAMILY,
            )

        # ── Right panel: Top 10 Chains ──
        ax.text(
            7.5,
            y_start,
            "Top 10 Chains by TVL",
            fontsize=12,
            fontweight="bold",
            color=COLORS["orange"],
            fontfamily=_FONT_FAMILY,
        )

        y_header2 = y_start - 0.38
        ax.text(
            7.7,
            y_header2,
            "#",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="center",
        )
        ax.text(
            8.05,
            y_header2,
            "Chain",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
        )
        ax.text(
            10.8,
            y_header2,
            "TVL",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="right",
        )
        ax.text(
            11.5,
            y_header2,
            "Share",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="center",
        )
        ax.text(
            12.6,
            y_header2,
            "Token",
            fontsize=8,
            fontweight="bold",
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            ha="center",
        )
        ax.plot(
            [7.4, 13.7],
            [y_header2 - 0.14, y_header2 - 0.14],
            color=COLORS["border"],
            linewidth=0.5,
        )

        for i, chain in enumerate(top_chains):
            y = y_header2 - 0.35 - i * 0.45

            name = (chain.get("name") or "Unknown")[:16]
            tvl = chain.get("tvl") or 0
            token = (chain.get("tokenSymbol") or "")[:6]
            share = (tvl / total_chain_tvl * 100) if total_chain_tvl > 0 else 0

            if i % 2 == 0:
                rect = mpatches.FancyBboxPatch(
                    (7.4, y - 0.15),
                    6.3,
                    0.38,
                    boxstyle="round,pad=0.03",
                    facecolor=COLORS["bg_inner"],
                    edgecolor="none",
                    alpha=0.5,
                )
                ax.add_patch(rect)

            rank_colors = {0: COLORS["gold"], 1: COLORS["silver"], 2: COLORS["bronze"]}
            rank_color = rank_colors.get(i, COLORS["text_secondary"])
            ax.text(
                7.7,
                y,
                str(i + 1),
                fontsize=9,
                fontweight="bold",
                color=rank_color,
                ha="center",
                fontfamily=_FONT_FAMILY,
            )
            ax.text(
                8.05, y, name, fontsize=9, color=COLORS["text"], fontfamily=_FONT_FAMILY
            )
            ax.text(
                10.8,
                y,
                _format_tvl(tvl),
                fontsize=9,
                color=COLORS["text"],
                ha="right",
                fontfamily=_FONT_FAMILY,
                fontweight="bold",
            )
            ax.text(
                11.5,
                y,
                f"{share:.1f}%",
                fontsize=8,
                color=COLORS["text_secondary"],
                ha="center",
                fontfamily=_FONT_FAMILY,
            )
            ax.text(
                12.6,
                y,
                token,
                fontsize=8,
                color=COLORS["text_secondary"],
                ha="center",
                fontfamily=_FONT_FAMILY,
            )

        # Footer
        ax.text(
            7,
            0.2,
            "Investing Dragon | DeFi Llama Data | Auto-generated",
            ha="center",
            fontsize=8,
            color=COLORS["text_secondary"],
            fontfamily=_FONT_FAMILY,
            style="italic",
        )

        filename = f"defi-tvl-dashboard-{date_str}.png"
        filepath = os.path.join(IMAGES_DIR, filename)

        plt.tight_layout(pad=0.5)
        plt.savefig(
            filepath,
            dpi=150,
            facecolor=COLORS["bg"],
            edgecolor="none",
            bbox_inches="tight",
        )
        plt.close(fig)

        logger.info("Generated DeFi TVL dashboard: %s", filename)
        return f"/assets/images/generated/{filename}"

    except ImportError:
        logger.info("image_generator not available, skipping chart")
        return None
    except Exception as e:
        logger.warning("DeFi TVL chart generation failed: %s", e)
        return None


def build_post_content(
    protocols: List[Dict[str, Any]],
    chains: List[Dict[str, Any]],
    today: str,
    now: datetime,
    chart_path: Optional[str],
) -> str:
    """Build the Jekyll post markdown content."""
    content_parts = []
    sorted_cats: List[Tuple[str, float]] = []

    total_protocol_tvl = sum(p.get("tvl", 0) or 0 for p in protocols)
    total_chain_tvl = sum(c.get("tvl", 0) or 0 for c in chains)

    # Introduction
    content_parts.append(
        f"**{today}** DeFi Llama 기준 DeFi 생태계 TVL(Total Value Locked, 총 예치 자산) 현황을 정리합니다. "
        f"상위 {len(protocols)}개 프로토콜의 총 TVL은 **{_format_tvl(total_protocol_tvl)}**이며, "
        f"상위 {len(chains)}개 체인의 총 TVL은 **{_format_tvl(total_chain_tvl)}**입니다.\n"
    )

    content_parts.append("## 전체 뉴스 요약\n")
    content_parts.append(
        f"- 총 **{len(protocols)}개 프로토콜**, **{len(chains)}개 체인** 데이터를 분석했습니다."
    )
    if protocols:
        top_p = protocols[0]
        top_p_name = top_p.get("name") or "Unknown"
        top_p_tvl = top_p.get("tvl") or 0
        content_parts.append(
            f"- **최상위 프로토콜**: {top_p_name} (TVL {_format_tvl(top_p_tvl)})"
        )
    if chains:
        top_c = chains[0]
        top_c_name = top_c.get("name") or "Unknown"
        top_c_tvl = top_c.get("tvl") or 0
        content_parts.append(
            f"- **최상위 체인**: {top_c_name} (TVL {_format_tvl(top_c_tvl)})"
        )
    content_parts.append("")

    # Chart image
    if chart_path:
        web_path = "{{ '" + chart_path + "' | relative_url }}"
        content_parts.append(f"\n![DeFi TVL Dashboard]({web_path})\n")

    # ── Section 1: Top Protocols ──
    content_parts.append(f"\n## 상위 {len(protocols)}개 프로토콜 TVL 순위\n")

    if protocols:
        protocol_rows = []
        for i, p in enumerate(protocols, 1):
            name = p.get("name") or "Unknown"
            tvl = p.get("tvl") or 0
            mcap = p.get("mcap")
            category = p.get("category") or ""
            symbol = p.get("symbol") or ""

            # Build DeFi Llama protocol URL
            protocol_slug = name.lower().replace(" ", "-")
            url = f"https://defillama.com/protocol/{protocol_slug}"
            name_cell = markdown_link(name, url)

            tvl_str = _format_tvl(tvl)
            mcap_str = _format_mcap(mcap)

            protocol_rows.append((i, name_cell, symbol, tvl_str, category, mcap_str))

        content_parts.append(
            markdown_table(
                ["#", "프로토콜", "심볼", "TVL", "카테고리", "시가총액"],
                protocol_rows,
                aligns=["right", "left", "left", "right", "left", "right"],
            )
        )
    else:
        content_parts.append("*프로토콜 데이터를 불러오지 못했습니다.*")

    # ── Section 2: Top Chains ──
    content_parts.append(f"\n## 상위 {len(chains)}개 체인 TVL 순위\n")

    if chains:
        chain_rows = []
        for i, c in enumerate(chains, 1):
            name = c.get("name") or "Unknown"
            tvl = c.get("tvl") or 0
            token = c.get("tokenSymbol") or ""
            share = (tvl / total_chain_tvl * 100) if total_chain_tvl > 0 else 0

            chain_rows.append((i, name, token, _format_tvl(tvl), f"{share:.1f}%"))

        content_parts.append(
            markdown_table(
                ["#", "체인", "네이티브 토큰", "TVL", "점유율"],
                chain_rows,
                aligns=["right", "left", "left", "right", "right"],
            )
        )
    else:
        content_parts.append("*체인 데이터를 불러오지 못했습니다.*")

    # ── Section 3: Category Analysis ──
    if protocols:
        content_parts.append("\n## 카테고리별 TVL 분석\n")

        category_tvl: Dict[str, float] = {}
        for p in protocols:
            cat = p.get("category") or "기타"
            tvl = p.get("tvl") or 0
            category_tvl[cat] = category_tvl.get(cat, 0) + tvl

        sorted_cats = sorted(category_tvl.items(), key=lambda x: x[1], reverse=True)
        cat_rows = [
            (
                cat,
                _format_tvl(tvl),
                f"{(tvl / total_protocol_tvl * 100):.1f}%"
                if total_protocol_tvl > 0
                else "N/A",
            )
            for cat, tvl in sorted_cats
        ]
        content_parts.append(
            markdown_table(
                ["카테고리", "TVL", "비중"],
                cat_rows,
                aligns=["left", "right", "right"],
            )
        )

    # ── TVL staleness warning ──
    stale_warning = _check_tvl_staleness(protocols, today)
    if stale_warning:
        content_parts.append(f"\n{stale_warning}")

    # ── Section 4: Insights ──
    content_parts.append("\n## DeFi 시장 인사이트\n")

    insight_lines = []

    # Top protocol highlight
    if protocols:
        top_p = protocols[0]
        top_p_name = top_p.get("name") or "Unknown"
        top_p_tvl = top_p.get("tvl") or 0
        share_of_total = (
            (top_p_tvl / total_protocol_tvl * 100) if total_protocol_tvl > 0 else 0
        )
        ro = _korean_ro(top_p_name)
        insight_lines.append(
            f"현재 DeFi 생태계에서 가장 큰 프로토콜은 **{top_p_name}**{ro}, "
            f"TVL **{_format_tvl(top_p_tvl)}** ({share_of_total:.1f}%)를 차지합니다."
        )

    # Top chain highlight
    if chains:
        top_c = chains[0]
        top_c_name = top_c.get("name") or "Unknown"
        top_c_tvl = top_c.get("tvl") or 0
        chain_share = (top_c_tvl / total_chain_tvl * 100) if total_chain_tvl > 0 else 0
        ro = _korean_ro(top_c_name)
        insight_lines.append(
            f"\n가장 많은 TVL을 보유한 체인은 **{top_c_name}**{ro}, "
            f"**{_format_tvl(top_c_tvl)}** ({chain_share:.1f}%) 수준입니다."
        )

    # Category concentration insight
    if protocols:
        top_cat_name, top_cat_tvl = sorted_cats[0] if sorted_cats else ("", 0)
        if top_cat_name and total_protocol_tvl > 0:
            cat_pct = top_cat_tvl / total_protocol_tvl * 100
            insight_lines.append(
                f"\n카테고리별로는 **{top_cat_name}** 섹터가 TVL {_format_tvl(top_cat_tvl)} "
                f"({cat_pct:.1f}%)로 가장 큰 비중을 차지하고 있습니다."
            )

    insight_lines.append("")
    insight_lines.append(
        "> *본 리포트는 DeFi Llama API의 자동 수집 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )
    content_parts.extend(insight_lines)

    # ── References ──
    refs = [
        {
            "title": "DeFi Llama - DeFi Dashboard",
            "link": "https://defillama.com",
            "source": "DeFi Llama",
        },
        {
            "title": "DeFi Llama API Documentation",
            "link": "https://defillama.com/docs/api",
            "source": "DeFi Llama",
        },
        {
            "title": "DeFi Llama - Chains",
            "link": "https://defillama.com/chains",
            "source": "DeFi Llama",
        },
    ]
    # Add top 5 protocol links
    for p in protocols[:5]:
        name = p.get("name") or ""
        if name:
            protocol_slug = name.lower().replace(" ", "-")
            url = f"https://defillama.com/protocol/{protocol_slug}"
            refs.append({"title": name, "link": url, "source": "DeFi Llama"})

    content_parts.append("\n---\n")
    content_parts.append(
        html_reference_details(
            "참고 링크",
            refs,
            limit=10,
            title_max_len=80,
        )
    )

    # Footer
    content_parts.append("\n---\n")
    content_parts.append(
        f"**데이터 수집 시각**: {now.strftime('%Y-%m-%d %H:%M')} UTC  \n"
        f"**데이터 출처**: {html_source_tag('DeFi Llama')} (https://defillama.com)"
    )

    return "\n".join(content_parts)


def main():
    """Main collection routine for DeFi Llama TVL data."""
    logger.info("=== Starting DeFi Llama TVL collection ===")
    started_at = time.monotonic()

    dedup = DedupEngine("defi_llama_seen.json")
    gen = PostGenerator("crypto-news")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    post_title = f"DeFi TVL 리포트 - {today}"
    created_count = 0

    # Early duplicate check
    if dedup.is_duplicate_exact(post_title, "defi-llama", today):
        logger.info("Post already created today, skipping: %s", post_title)
        log_collection_summary(
            logger,
            collector="collect_defi_llama",
            source_count=0,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        return

    # Fetch data
    protocols = fetch_protocols()
    chains = fetch_chains()

    if not protocols and not chains:
        logger.warning("No data collected from DeFi Llama, skipping post creation")
        log_collection_summary(
            logger,
            collector="collect_defi_llama",
            source_count=2,
            unique_items=0,
            post_created=0,
            started_at=started_at,
        )
        return

    # Generate chart image
    chart_path = generate_tvl_chart_image(protocols, chains, today)

    # Build post content
    content = build_post_content(protocols, chains, today, now, chart_path)

    # Create post
    image_frontmatter = chart_path if chart_path else ""
    filepath = gen.create_post(
        title=post_title,
        content=content,
        date=now,
        tags=["defi", "tvl", "crypto", "blockchain", "daily-digest"],
        source="defi-llama",
        source_url="https://defillama.com",
        lang="ko",
        image=image_frontmatter,
        slug="daily-defi-tvl-report",
    )

    if filepath:
        dedup.mark_seen(post_title, "defi-llama", today)
        created_count += 1
        logger.info("Created DeFi TVL report post: %s", filepath)

    dedup.save()

    unique_items = len(protocols) + len(chains)
    logger.info(
        "=== DeFi Llama collection complete: %d posts created ===", created_count
    )
    log_collection_summary(
        logger,
        collector="collect_defi_llama",
        source_count=2,
        unique_items=unique_items,
        post_created=created_count,
        started_at=started_at,
        extras={"protocols": len(protocols), "chains": len(chains)},
    )


if __name__ == "__main__":
    main()
