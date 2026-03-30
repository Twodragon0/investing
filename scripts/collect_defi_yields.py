#!/usr/bin/env python3
"""Collect DeFi yield/APY data from DeFi Llama Yields API and generate Jekyll posts.

Sources:
- DeFi Llama Yields API (https://yields.llama.fi):
  - GET /pools - All yield pools with APY data (pool, chain, project, symbol, tvlUsd, apy, etc.)
"""

import os
import sys
import time
from typing import Any, Dict, List

import requests

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.base_collector import BaseCollector
from common.collector_config import get_collector_config, get_limit, get_threshold
from common.config import REQUEST_TIMEOUT
from common.markdown_utils import html_reference_details, markdown_link, markdown_table
from common.post_generator import build_dated_permalink
from common.utils import request_with_retry

# collectors.yml에서 설정 로드 (없으면 하드코딩 기본값으로 폴백)
_yields_cfg = get_collector_config("defi_yields")
BASE_URL = _yields_cfg.get("urls", {}).get("base", "https://yields.llama.fi")
POOLS_ENDPOINT = _yields_cfg.get("urls", {}).get("pools_endpoint", "/pools")
SITE_URL = _yields_cfg.get("urls", {}).get("site", "https://defillama.com/yields")

TOP_STABLECOIN_LIMIT = get_limit("defi_yields", "top_stablecoin", 10)
TOP_ETH_LIMIT = get_limit("defi_yields", "top_eth", 10)
TOP_BTC_LIMIT = get_limit("defi_yields", "top_btc", 10)
TOP_OVERALL_LIMIT = get_limit("defi_yields", "top_overall", 15)

MIN_TVL = float(get_threshold("defi_yields", "min_tvl", 1_000_000.0))
MIN_APY = float(get_threshold("defi_yields", "min_apy", 0.1))


def _format_tvl(tvl: float) -> str:
    """Format TVL value as human-readable string."""
    if tvl >= 1_000_000_000:
        return f"${tvl / 1_000_000_000:.2f}B"
    elif tvl >= 1_000_000:
        return f"${tvl / 1_000_000:.1f}M"
    elif tvl >= 1_000:
        return f"${tvl / 1_000:.1f}K"
    return f"${tvl:.0f}"


def fetch_pools(verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """Fetch all yield pools from DeFi Llama Yields API.

    Returns list of dicts with keys: pool, chain, project, symbol, tvlUsd, apy,
    apyBase, apyReward, stablecoin, etc.
    """
    url = f"{BASE_URL}{POOLS_ENDPOINT}"
    try:
        resp = request_with_retry(url, timeout=REQUEST_TIMEOUT, verify_ssl=verify_ssl)
        data = resp.json()

        # API returns {"status": "success", "data": [...]}
        if isinstance(data, dict):
            pools = data.get("data", [])
        elif isinstance(data, list):
            pools = data
        else:
            return []

        if not isinstance(pools, list):
            return []

        return pools
    except requests.exceptions.RequestException:
        return []
    except (ValueError, KeyError):
        return []


def _filter_pools(pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter pools by minimum TVL and APY thresholds."""
    filtered = []
    for p in pools:
        if not isinstance(p, dict):
            continue
        tvl = p.get("tvlUsd") or 0
        apy = p.get("apy") or 0
        if tvl >= MIN_TVL and apy >= MIN_APY:
            filtered.append(p)
    return filtered


def categorize_pools(
    pools: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize pools into stablecoin, ETH, BTC, and overall buckets."""
    stablecoin_pools = []
    eth_pools = []
    btc_pools = []

    for p in pools:
        symbol = (p.get("symbol") or "").upper()
        is_stable = bool(p.get("stablecoin"))

        if is_stable:
            stablecoin_pools.append(p)

        if "ETH" in symbol or "WETH" in symbol:
            eth_pools.append(p)

        if "BTC" in symbol or "WBTC" in symbol:
            btc_pools.append(p)

    # Sort each category
    stablecoin_pools.sort(key=lambda x: x.get("apy") or 0, reverse=True)
    eth_pools.sort(key=lambda x: x.get("apy") or 0, reverse=True)
    btc_pools.sort(key=lambda x: x.get("apy") or 0, reverse=True)

    # Overall: sorted by TVL descending
    overall_pools = sorted(pools, key=lambda x: x.get("tvlUsd") or 0, reverse=True)

    return {
        "stablecoin": stablecoin_pools[:TOP_STABLECOIN_LIMIT],
        "eth": eth_pools[:TOP_ETH_LIMIT],
        "btc": btc_pools[:TOP_BTC_LIMIT],
        "overall": overall_pools[:TOP_OVERALL_LIMIT],
    }


def _build_pool_table(pool_list: List[Dict[str, Any]]) -> str:
    """Build a markdown table for a list of pools."""
    rows = []
    for i, p in enumerate(pool_list, 1):
        project = p.get("project") or "Unknown"
        chain = p.get("chain") or "Unknown"
        symbol = p.get("symbol") or "Unknown"
        apy = p.get("apy") or 0
        tvl = p.get("tvlUsd") or 0

        # Link project to DeFi Llama yields page
        project_url = f"https://defillama.com/yields?project={project.lower()}"
        project_cell = markdown_link(project, project_url)

        rows.append((i, project_cell, chain, symbol, f"{apy:.2f}%", _format_tvl(tvl)))

    return markdown_table(
        ["#", "프로토콜", "체인", "자산", "APY(%)", "TVL"],
        rows,
        aligns=["right", "left", "left", "left", "right", "right"],
    )


def build_post_content(
    categories: Dict[str, List[Dict[str, Any]]],
    all_pools: List[Dict[str, Any]],
    today: str,
    now,
) -> str:
    """Build the Jekyll post markdown content."""
    content_parts = []

    stablecoin_pools = categories["stablecoin"]
    eth_pools = categories["eth"]
    btc_pools = categories["btc"]
    overall_pools = categories["overall"]

    total_pools = len(all_pools)
    avg_apy = sum(p.get("apy") or 0 for p in all_pools) / total_pools if total_pools > 0 else 0
    max_apy_pool = max(all_pools, key=lambda x: x.get("apy") or 0) if all_pools else None
    max_apy_project = (max_apy_pool.get("project") or "Unknown") if max_apy_pool else "Unknown"
    max_apy_val = (max_apy_pool.get("apy") or 0) if max_apy_pool else 0

    # Introduction
    content_parts.append(
        f"**{today}** DeFi Llama Yields API 기준 주요 DeFi 수익률(APY) 현황을 정리합니다. "
        f"TVL $1M 이상, APY 0.1% 이상 풀 **{total_pools}개** 기준이며, "
        f"스테이블코인·ETH·BTC 카테고리별 상위 수익률과 전체 TOP TVL 풀을 포함합니다.\n"
    )

    # Alert-box with summary stats
    briefing_items = [
        f"<li>📊 <strong>총 풀 수</strong>: {total_pools:,}개 (TVL $1M↑, APY 0.1%↑)</li>",
        f"<li>📈 <strong>평균 APY</strong>: {avg_apy:.2f}%</li>",
        f"<li>🏆 <strong>최고 APY 프로토콜</strong>: {max_apy_project} — {max_apy_val:.2f}%</li>",
    ]
    if stablecoin_pools:
        top_stable = stablecoin_pools[0]
        briefing_items.append(
            f"<li>💵 <strong>스테이블코인 TOP</strong>: "
            f"{top_stable.get('project', 'Unknown')} ({top_stable.get('symbol', '')}) "
            f"— {top_stable.get('apy', 0):.2f}%</li>"
        )
    content_parts.append(
        f'<div class="alert-box alert-info">'
        f"<strong>DeFi 수익률 요약 ({today})</strong>"
        f"<ul>{''.join(briefing_items)}</ul>"
        f"</div>"
    )

    # ── Section 1: 스테이블코인 수익률 ──
    content_parts.append(f"\n## 스테이블코인 수익률 TOP {len(stablecoin_pools)}\n")
    content_parts.append(
        "USDC, USDT, DAI 등 스테이블코인 기반 풀을 APY 기준으로 정렬한 결과입니다. "
        "원금 가치 보존을 원하는 투자자에게 적합합니다.\n"
    )
    if stablecoin_pools:
        content_parts.append(_build_pool_table(stablecoin_pools))
    else:
        content_parts.append("*스테이블코인 풀 데이터를 불러오지 못했습니다.*")

    # ── Section 2: ETH 수익률 ──
    content_parts.append(f"\n## ETH 수익률 TOP {len(eth_pools)}\n")
    content_parts.append(
        "ETH, WETH 등 이더리움 기반 자산 풀을 APY 기준으로 정렬한 결과입니다. "
        "스테이킹, 리퀴드 스테이킹(LSDfi), DEX LP 등 다양한 전략이 포함됩니다.\n"
    )
    if eth_pools:
        content_parts.append(_build_pool_table(eth_pools))
    else:
        content_parts.append("*ETH 풀 데이터를 불러오지 못했습니다.*")

    # ── Section 3: BTC 수익률 ──
    content_parts.append(f"\n## BTC 수익률 TOP {len(btc_pools)}\n")
    content_parts.append(
        "BTC, WBTC 등 비트코인 기반 자산 풀을 APY 기준으로 정렬한 결과입니다. "
        "래핑 BTC 기반 DeFi 전략의 수익률을 확인하세요.\n"
    )
    if btc_pools:
        content_parts.append(_build_pool_table(btc_pools))
    else:
        content_parts.append("*BTC 풀 데이터를 불러오지 못했습니다.*")

    # ── Section 4: 전체 TOP TVL 수익률 ──
    content_parts.append(f"\n## 전체 TOP {len(overall_pools)} 수익률 (TVL 기준)\n")
    content_parts.append("TVL 기준 상위 풀 목록입니다. 유동성이 크고 검증된 프로토콜 위주로 정렬됩니다.\n")
    if overall_pools:
        content_parts.append(_build_pool_table(overall_pools))
    else:
        content_parts.append("*전체 풀 데이터를 불러오지 못했습니다.*")

    # Disclaimer
    content_parts.append(
        "\n> *본 리포트는 DeFi Llama Yields API의 자동 수집 데이터를 기반으로 생성되었으며, "
        "투자 조언이 아닙니다. APY는 시장 상황에 따라 변동되며, "
        "모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다.*"
    )

    # References
    refs = [
        {
            "title": "DeFi Llama Yields",
            "link": SITE_URL,
            "source": "DeFi Llama",
        },
        {
            "title": "DeFi Llama Yields API",
            "link": "https://yields.llama.fi/pools",
            "source": "DeFi Llama",
        },
    ]
    # Add top 5 overall projects
    seen_projects: set = set()
    for p in overall_pools[:5]:
        project = p.get("project") or ""
        if project and project not in seen_projects:
            seen_projects.add(project)
            project_url = f"https://defillama.com/yields?project={project.lower()}"
            refs.append({"title": project, "link": project_url, "source": "DeFi Llama"})

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
    content_parts.append(
        '\n<div class="wm-footer-meta">'
        f"<span>수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST</span>"
        "<span>소스: DeFi Llama Yields (yields.llama.fi)</span>"
        "</div>"
    )

    return "\n".join(content_parts)


class DefiYieldsCollector(BaseCollector):
    """DeFi 수익률 수집기.

    DeFi Llama Yields API에서 풀 데이터를 수집하고
    카테고리별 APY 리포트를 생성합니다.
    """

    name = "defi_yields"
    category = "defi"
    state_file = "defi_yields_seen.json"

    def fetch(self) -> List[Dict[str, Any]]:
        """DeFi Llama에서 풀 데이터를 가져옵니다."""
        raw_pools = fetch_pools(verify_ssl=self.verify_ssl)
        self.logger.info("DeFi Yields API: fetched %d raw pools", len(raw_pools))
        return raw_pools

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """TVL/APY 기준으로 풀을 필터링합니다."""
        pools = _filter_pools(items)
        self.logger.info("DeFi Yields: %d pools after filtering (raw: %d)", len(pools), len(items))
        return pools

    def build_content(self, items: List[Dict[str, Any]]) -> str:
        """카테고리별 수익률 리포트 본문을 생성합니다."""
        categories = categorize_pools(items)
        return build_post_content(categories, items, self.today, self.now)

    def build_title(self, items: List[Dict[str, Any]]) -> str:
        """포스트 제목을 생성합니다."""
        return f"DeFi 수익률 리포트 - {self.today}"

    def default_tags(self) -> List[str]:
        """기본 태그 목록을 반환합니다."""
        return ["defi", "yield", "apy", "crypto", "daily-digest"]

    def run(self) -> None:
        """메인 실행 파이프라인 — 중복 검사 후 리포트 생성."""
        self.logger.info("=== Starting %s collection ===", self.name)
        self._started_at = time.monotonic()

        post_title = self.build_title([])

        # Early duplicate check
        if self.is_duplicate_exact(post_title, "defi-yields"):
            self.logger.info("Post already created today, skipping: %s", post_title)
            self.save_state()
            self.log_summary([])
            return

        # Fetch and process
        raw_pools = self.fetch()

        if not raw_pools:
            self.logger.warning("No yield pools collected from DeFi Llama, skipping post creation")
            self.save_state()
            self.log_summary([], extras={"raw_pools": 0, "filtered_pools": 0})
            return

        pools = self.process(raw_pools)

        # Categorize
        categories = categorize_pools(pools)
        stablecoin_count = len(categories["stablecoin"])
        eth_count = len(categories["eth"])
        btc_count = len(categories["btc"])

        self.logger.info(
            "DeFi Yields categories: stablecoin=%d, eth=%d, btc=%d, overall=%d",
            stablecoin_count,
            eth_count,
            btc_count,
            len(categories["overall"]),
        )

        # Build post content
        content = build_post_content(categories, pools, self.today, self.now)

        # Data-driven description
        top_stable_project = categories["stablecoin"][0].get("project", "") if categories["stablecoin"] else ""
        top_stable_apy = categories["stablecoin"][0].get("apy", 0) if categories["stablecoin"] else 0
        avg_apy = sum(p.get("apy") or 0 for p in pools) / len(pools) if pools else 0

        _desc_ko = (
            f"DeFi 수익률 리포트: TVL $1M 이상 풀 {len(pools)}개 기준. "
            f"스테이블코인 TOP APY {top_stable_apy:.1f}% ({top_stable_project}), "
            f"전체 평균 APY {avg_apy:.1f}%. "
            "스테이블코인·ETH·BTC 카테고리별 최고 수익률 프로토콜을 분석합니다."
        )

        # Create post via PostGenerator directly (need source_url param)
        filepath = self.post_gen.create_post(
            title=post_title,
            content=content,
            date=self.now,
            logical_date=self.today,
            tags=self.default_tags(),
            source="defi-yields",
            source_url=SITE_URL,
            lang="ko",
            extra_frontmatter={
                "permalink": build_dated_permalink("defi", self.today, "daily-defi-yields-report"),
                "description_ko": _desc_ko,
            },
            slug="daily-defi-yields-report",
        )

        if filepath:
            self._created_count += 1
            self.mark_seen(post_title, "defi-yields")
            self.logger.info("Created DeFi Yields report post: %s", filepath)

        self.save_state()
        self.logger.info("=== DeFi Yields collection complete: %d posts created ===", self._created_count)
        self.log_summary(
            pools,
            extras={
                "raw_pools": len(raw_pools),
                "filtered_pools": len(pools),
                "stablecoin": stablecoin_count,
                "eth": eth_count,
                "btc": btc_count,
            },
        )


def main():
    """Main collection routine for DeFi yields data."""
    collector = DefiYieldsCollector()
    collector.run()


if __name__ == "__main__":
    main()
