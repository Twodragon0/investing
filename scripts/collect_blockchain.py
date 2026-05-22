#!/usr/bin/env python3
"""Collect blockchain network metrics and generate a daily report.

Sources:
- Blockchain.com API: BTC network stats (hash rate, difficulty, transactions)
- Etherscan V2 API: ETH gas prices, supply (optional API key)

Generates a single daily post in the ``blockchain`` category.
"""

import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.base_collector import BaseCollector
from common.blockchain_api import (
    fetch_btc_stats,
    fetch_eth_stats,
    fetch_l2_summary,
    fetch_upgrade_news,
)
from common.markdown_utils import markdown_table
from common.post_generator import build_dated_permalink

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_hash_rate(ehs: float) -> str:
    """Format hash rate in EH/s."""
    if ehs >= 1000:
        return f"{ehs / 1000:.2f} ZH/s"
    return f"{ehs:.1f} EH/s"


def _fmt_difficulty(diff: float) -> str:
    """Format difficulty with T suffix."""
    return f"{diff / 1e12:.2f}T"


def _fmt_number(n: int | float) -> str:
    """Format large numbers with comma separators."""
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _fmt_usd(amount: float) -> str:
    """Format USD amount."""
    if amount >= 1e9:
        return f"${amount / 1e9:.2f}B"
    if amount >= 1e6:
        return f"${amount / 1e6:.2f}M"
    return f"${amount:,.0f}"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report_content(
    btc: dict,
    eth: dict,
    today: str,
    l2_projects: list | None = None,
    upgrade_news: list | None = None,
) -> tuple[str, str, str]:
    """Build markdown report content from collected data.

    Returns (content, description, excerpt).
    """
    parts: list[str] = []
    stats_collected = 0

    # ── BTC Section ──
    if btc:
        stats_collected += 1
        parts.append("## Bitcoin 네트워크 현황\n")

        btc_rows = [
            ["해시레이트", _fmt_hash_rate(btc.get("hash_rate_ehs", 0))],
            ["난이도", _fmt_difficulty(btc.get("difficulty", 0))],
            ["일일 트랜잭션", _fmt_number(btc.get("n_tx", 0))],
            ["평균 블록 시간", f"{btc.get('block_time_min', 0):.1f}분"],
            ["총 블록 수", _fmt_number(btc.get("blocks_total", 0))],
        ]
        if btc.get("mempool_size"):
            btc_rows.append(["멤풀 크기", f"{_fmt_number(btc['mempool_size'])} tx"])
        if btc.get("market_price_usd"):
            btc_rows.append(["BTC 가격", _fmt_usd(btc["market_price_usd"])])

        parts.append(markdown_table(["지표", "값"], btc_rows))
        parts.append("")

        # BTC insight
        block_time = btc.get("block_time_min", 10)
        if block_time < 9:
            parts.append(
                f"> 평균 블록 생성 시간 **{block_time:.1f}분**으로 목표(10분)보다 빠르며, 해시레이트 증가를 반영합니다.\n"
            )
        elif block_time > 11:
            parts.append(
                f"> 평균 블록 생성 시간 **{block_time:.1f}분**으로 목표(10분)보다 느리며, 채굴 난이도 조정이 예상됩니다.\n"
            )
    else:
        parts.append("## Bitcoin 네트워크 현황\n")
        parts.append("*BTC 네트워크 데이터를 가져올 수 없습니다.*\n")

    # ── ETH Section ──
    if eth:
        stats_collected += 1
        parts.append("## Ethereum 네트워크 현황\n")

        eth_rows = []
        if eth.get("gas_safe"):
            eth_rows.append(["가스 가격 (Safe)", f"{float(eth['gas_safe']):.2f} Gwei"])
        if eth.get("gas_propose"):
            eth_rows.append(["가스 가격 (Standard)", f"{float(eth['gas_propose']):.2f} Gwei"])
        if eth.get("gas_fast"):
            eth_rows.append(["가스 가격 (Fast)", f"{float(eth['gas_fast']):.2f} Gwei"])
        if eth.get("eth_supply"):
            supply_m = eth["eth_supply"] / 1e6
            eth_rows.append(["총 공급량", f"{supply_m:.2f}M ETH"])
        if eth.get("eth_price_usd"):
            eth_rows.append(["ETH 가격", f"${eth['eth_price_usd']:,.2f}"])

        if eth_rows:
            parts.append(markdown_table(["지표", "값"], eth_rows))
            parts.append("")

            # Gas insight
            gas_fast = float(eth.get("gas_fast", 0))
            if gas_fast > 100:
                parts.append(
                    f"> 가스 가격 **{gas_fast} Gwei**로 네트워크 혼잡 상태입니다. 트랜잭션 비용 상승에 유의하세요.\n"
                )
            elif gas_fast < 10:
                parts.append(
                    f"> 가스 가격 **{gas_fast} Gwei**로 네트워크가 한산합니다. 트랜잭션 실행에 유리한 시점입니다.\n"
                )
    else:
        parts.append("## Ethereum 네트워크 현황\n")
        parts.append(
            "*ETH 네트워크 데이터를 가져올 수 없습니다. `ETHERSCAN_API_KEY` 환경변수를 설정하면 상세 데이터를 확인할 수 있습니다.*\n"
        )

    # ── L2 Section ──
    l2 = l2_projects or []
    if l2:
        stats_collected += 1
        parts.append("## Layer 2 네트워크 활동\n")

        l2_rows = []
        for proj in l2[:8]:
            tvl = proj.get("tvl", 0)
            tvl_str = _fmt_usd(tvl) if tvl else "N/A"
            stage = proj.get("stage", "")
            stage_str = stage if isinstance(stage, str) else str(stage)
            l2_rows.append([proj.get("name", ""), tvl_str, stage_str])

        parts.append(markdown_table(["네트워크", "TVL", "Stage"], l2_rows))
        parts.append("")
        parts.append(f"> L2Beat 기준 상위 {len(l2_rows)}개 L2 네트워크의 TVL 현황입니다.\n")

    # ── Upgrade News Section ──
    news = upgrade_news or []
    if news:
        parts.append("## 주요 네트워크 업데이트\n")
        for item in news[:5]:
            title = item.get("title", "").strip()
            link = item.get("link", "")
            source = item.get("source_name", item.get("source", ""))
            if title and link:
                parts.append(f"- [{title}]({link}) — {source}")
            elif title:
                parts.append(f"- {title} — {source}")
        parts.append("")

    # ── Summary stats ──
    stat_items = []
    if btc:
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{_fmt_hash_rate(btc.get("hash_rate_ehs", 0))}</div>'
            f'<div class="stat-label">BTC 해시레이트</div></div>'
        )
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{_fmt_number(btc.get("n_tx", 0))}</div>'
            f'<div class="stat-label">BTC 일일 트랜잭션</div></div>'
        )
    if eth and eth.get("gas_propose"):
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{float(eth["gas_propose"]):.2f} Gwei</div>'
            f'<div class="stat-label">ETH 가스 (Standard)</div></div>'
        )
    if eth and eth.get("eth_supply"):
        stat_items.append(
            f'<div class="stat-item"><div class="stat-value">{eth["eth_supply"] / 1e6:.1f}M</div>'
            f'<div class="stat-label">ETH 공급량</div></div>'
        )

    stat_grid = ""
    if stat_items:
        stat_grid = '<div class="stat-grid">' + "".join(stat_items) + "</div>\n\n"

    # ── Lead paragraph (becomes page.excerpt → post-summary) ──
    # stat-grid HTML alone yields raw numbers after strip_html, so emit a
    # natural-language sentence before it. Values are pulled from the same
    # source dicts so the lead stays in lockstep with the grid.
    lead_bits: list[str] = []
    if btc:
        _hr = _fmt_hash_rate(btc.get("hash_rate_ehs", 0))
        _tx = _fmt_number(btc.get("n_tx", 0))
        lead_bits.append(f"BTC 해시레이트 **{_hr}**, 일일 트랜잭션 **{_tx}건**")
    if eth and eth.get("gas_propose"):
        _gas = float(eth["gas_propose"])
        if eth.get("eth_price_usd"):
            lead_bits.append(f"ETH 가스 **{_gas:.2f} Gwei**, ETH **${eth['eth_price_usd']:,.0f}**")
        else:
            lead_bits.append(f"ETH 가스 **{_gas:.2f} Gwei**")
    if lead_bits:
        lead_text = (
            f"**{today}** 블록체인 네트워크 현황: "
            + " · ".join(lead_bits)
            + ". 채굴/네트워크 활성도와 가스비 추이를 정리합니다.\n\n"
        )
    else:
        lead_text = ""

    # ── Footer ──
    sources = []
    if btc:
        sources.append("Blockchain.com")
    if eth:
        sources.append("Etherscan")
    source_str = ", ".join(sources) if sources else "N/A"

    parts.append("---\n")
    parts.append(
        f'<div class="wm-footer-meta"><span>수집 시각: {today} KST</span><span>소스: {source_str}</span></div>'
    )

    content = lead_text + stat_grid + "\n".join(parts)

    # Description/excerpt
    desc_parts = []
    if btc:
        desc_parts.append(
            f"BTC 해시레이트 {_fmt_hash_rate(btc.get('hash_rate_ehs', 0))}, "
            f"일일 트랜잭션 {_fmt_number(btc.get('n_tx', 0))}건"
        )
    if eth and eth.get("gas_propose"):
        desc_parts.append(f"ETH 가스 {float(eth['gas_propose']):.2f} Gwei")
    description = ". ".join(desc_parts) if desc_parts else "블록체인 네트워크 일일 리포트"
    excerpt = description[:200] + "…" if len(description) > 200 else description

    return content, description, excerpt


# ---------------------------------------------------------------------------
# BaseCollector subclass
# ---------------------------------------------------------------------------


class BlockchainCollector(BaseCollector):
    """블록체인 네트워크 메트릭 수집기."""

    name = "blockchain"
    category = "blockchain"
    state_file = "blockchain_seen.json"

    def fetch(self) -> List[Dict[str, Any]]:
        """BTC/ETH/L2 데이터를 수집합니다."""
        btc = fetch_btc_stats()
        eth = fetch_eth_stats()
        l2_projects = fetch_l2_summary()
        upgrade_news = fetch_upgrade_news()

        # 데이터를 단일 리스트로 래핑 (파이프라인 호환)
        items: List[Dict[str, Any]] = []
        if btc or eth:
            items.append(
                {
                    "title": f"블록체인 네트워크 리포트 - {self.today}",
                    "source": "blockchain-metrics",
                    "btc": btc,
                    "eth": eth,
                    "l2_projects": l2_projects,
                    "upgrade_news": upgrade_news,
                }
            )
        return items

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """이미 정제된 API 데이터이므로 그대로 반환합니다."""
        return items

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """마크다운 리포트 본문을 생성합니다."""
        if not items:
            return ""
        data = items[0]
        content, _desc, _excerpt = build_report_content(
            data.get("btc", {}),
            data.get("eth", {}),
            self.today,
            data.get("l2_projects"),
            data.get("upgrade_news"),
        )
        return content

    def run(self) -> None:
        """커스텀 파이프라인 — 단일 일일 리포트 생성."""
        self.logger.info("=== Starting %s collection ===", self.name)
        self._started_at = time.monotonic()

        post_title = f"블록체인 네트워크 리포트 - {self.today}"

        if self.is_duplicate_exact(post_title, "blockchain-metrics"):
            self.logger.info("Blockchain report already exists for %s, skipping", self.today)
            self.log_summary([])
            return

        # Collect data from APIs
        btc = fetch_btc_stats()
        eth = fetch_eth_stats()
        l2_projects = fetch_l2_summary()
        upgrade_news = fetch_upgrade_news()

        if not btc and not eth:
            self.logger.warning("No blockchain data collected, skipping post")
            self.log_summary([])
            return

        source_count = (1 if btc else 0) + (1 if eth else 0) + (1 if l2_projects else 0)

        # Build report
        content, description, excerpt = build_report_content(btc, eth, self.today, l2_projects, upgrade_news)

        # Create post
        permalink = build_dated_permalink("blockchain", self.today, "daily-blockchain-network-report")
        tags = ["blockchain", "on-chain", "network-stats", "daily"]
        if btc:
            tags.append("bitcoin")
        if eth:
            tags.append("ethereum")

        _desc_parts_bc = []
        if btc:
            _desc_parts_bc.append("BTC 네트워크 지표")
        if eth:
            _desc_parts_bc.append("ETH 네트워크 지표")
        if l2_projects:
            _desc_parts_bc.append(f"L2 프로젝트 {len(l2_projects)}개")
        _desc_ko = f"블록체인 네트워크 통계 {source_count}개 소스 수집. "
        if _desc_parts_bc:
            _desc_ko += f"{', '.join(_desc_parts_bc)} 포함. "
        if btc and btc.get("hashrate"):
            _desc_ko += f"BTC 해시레이트: {btc['hashrate']}."
        elif eth and eth.get("gas_price"):
            _desc_ko += f"ETH 가스: {eth['gas_price']} Gwei."
        _desc_ko = _desc_ko[:160]

        post_path = self.create_post(
            title=post_title,
            content=content,
            tags=tags,
            source="blockchain-metrics",
            slug="daily-blockchain-network-report",
            extra_frontmatter={
                "permalink": permalink,
                "description": description,
                "excerpt": excerpt,
                "description_ko": _desc_ko,
            },
        )

        if post_path:
            self.mark_seen(post_title, "blockchain-metrics")
            self.logger.info("Created blockchain report: %s", post_path)
        else:
            self.logger.warning("Failed to create blockchain report post")

        self.save_state()

        # Build items list for log_summary
        items: List[Dict[str, Any]] = []
        if btc:
            items.append({"title": "BTC stats", "source": "Blockchain.com"})
        if eth:
            items.append({"title": "ETH stats", "source": "Etherscan"})
        if l2_projects:
            items.append({"title": "L2 summary", "source": "L2Beat"})

        self.logger.info("=== Blockchain Network Report Collection Complete ===")
        self.log_summary(items)


# ---------------------------------------------------------------------------
# Main (하위 호환성)
# ---------------------------------------------------------------------------


def main() -> int:
    collector = BlockchainCollector()
    collector.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
