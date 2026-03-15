from pathlib import Path

from scripts.generate_weekly_digest import (
    build_journal_performance_section,
    extract_journal_snapshot,
    parse_post_frontmatter,
)


def test_parse_post_frontmatter_extracts_journal_metadata(tmp_path: Path):
    post = tmp_path / "journal.md"
    post.write_text(
        """---
title: \"크립토 트레이딩 일지 - 2026-02-10\"
date: 2026-02-10 09:00:00 +0900
categories: [crypto-trading-journal]
tags: [trading, crypto, journal]
journal_strategy: \"BTC 눌림목 재진입\"
journal_market_regime: \"변동성 확대\"
journal_day_result: \"+1.8%\"
journal_trade_count: \"4회\"
journal_realized_pnl: \"+₩184,000\"
journal_best_trade: \"BTC 재진입\"
journal_next_focus: \"CPI 전 노출 축소\"
---

본문
""",
        encoding="utf-8",
    )

    data = parse_post_frontmatter(str(post))

    assert data["categories"] == "[crypto-trading-journal]"
    assert data["tags"] == ["trading", "crypto", "journal"]
    assert data["journal_strategy"] == "BTC 눌림목 재진입"
    assert data["journal_day_result"] == "+1.8%"
    assert data["journal_next_focus"] == "CPI 전 노출 축소"


def test_extract_journal_snapshot_builds_digest_lines():
    snapshot = extract_journal_snapshot(
        {
            "journal_strategy": "반도체 선별 매수",
            "journal_market_regime": "반등 시도",
            "journal_day_result": "+0.9%",
            "journal_trade_count": "3회",
            "journal_realized_pnl": "+₩126,000",
            "journal_best_trade": "반도체 대형주 분할 진입",
            "journal_next_focus": "환율과 미국 선물 확인",
        }
    )

    assert snapshot[0] == "전략: 반도체 선별 매수 | 시장 상태: 반등 시도 | 당일 결과: +0.9%"
    assert snapshot[1] == "거래 횟수: 3회 | 실현 손익: +₩126,000"
    assert snapshot[2] == "베스트 트레이드: 반도체 대형주 분할 진입"
    assert snapshot[3] == "다음 세션 포인트: 환율과 미국 선물 확인"


def test_build_journal_performance_section_renders_table_and_notes():
    lines = build_journal_performance_section(
        [
            {
                "file_date": "2026-03-15",
                "categories": "[crypto-trading-journal]",
                "title": "크립토 트레이딩 일지 - 2026-03-15",
                "excerpt": "BTC 중심 전략과 세션 보드를 정리한 일지입니다.",
                "image": "/assets/images/generated/og-crypto-trading-journal-2026-03-15.png",
                "permalink": "/crypto-journal/2026/03/15/crypto-trading-journal/",
                "journal_strategy": "BTC 추세 추종",
                "journal_day_result": "+1.4%",
                "journal_trade_count": "4회",
                "journal_realized_pnl": "+₩210,000",
                "journal_best_trade": "BTC 재진입",
                "journal_next_focus": "FOMC 전 노출 축소",
            }
        ]
    )

    joined = "\n".join(lines)
    assert "## 트레이딩 일지 성과" in joined
    assert "| 2026-03-15 | 크립토 | BTC 추세 추종 | +1.4% | 4회 | +₩210,000 |" in joined
    assert "베스트 트레이드: BTC 재진입" in joined
    assert '<a href="/crypto-journal/2026/03/15/crypto-trading-journal/" class="journal-digest-card">' in joined
    assert 'class="journal-digest-thumb"' in joined
