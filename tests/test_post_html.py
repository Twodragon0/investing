"""Unit tests for scripts/common/post_html.py shared HTML builders."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from common.post_html import alert_box, footer_meta, stat_grid, summary_intro  # noqa: F401


class TestStatGrid:
    def test_renders_div_based_stats(self):
        out = stat_grid([("930.3 EH/s", "BTC 해시레이트"), ("600,100", "BTC 일일 트랜잭션")])
        assert '<div class="stat-grid">' in out
        assert '<div class="stat-value">930.3 EH/s</div>' in out
        assert '<div class="stat-label">BTC 해시레이트</div>' in out
        # Single closing div for the wrapper
        assert out.endswith("</div></div>")

    def test_empty_returns_empty_string(self):
        assert stat_grid([]) == ""

    def test_single_item(self):
        out = stat_grid([("47", "총 수집")])
        assert out.count('<div class="stat-item">') == 1


class TestAlertBox:
    def test_info_variant(self):
        out = alert_box("오늘 요약", ["수집: 20건", "주요: BTC"], variant="info")
        assert 'class="alert-box alert-info"' in out
        assert "<strong>오늘 요약</strong>" in out
        assert "<li>수집: 20건</li>" in out
        assert "<li>주요: BTC</li>" in out

    def test_warning_and_urgent_variants(self):
        assert "alert-warning" in alert_box("Warn", ["x"], variant="warning")
        assert "alert-urgent" in alert_box("Urgent", ["x"], variant="urgent")

    def test_empty_bullets_returns_empty(self):
        assert alert_box("Title", []) == ""

    def test_bullets_can_contain_inline_html(self):
        out = alert_box("T", ["🔴 <strong>BTC</strong>: -5%"])
        assert "🔴 <strong>BTC</strong>: -5%" in out


class TestSummaryIntro:
    def test_with_headline_and_source(self):
        out = summary_intro(
            "2026-05-22",
            "지정학 핵심 이슈",
            "Trump Warns Iran",
            source="GDELT",
            detail="총 30건 분석",
        )
        assert out == "**2026-05-22** 지정학 핵심 이슈: **Trump Warns Iran** (GDELT). 총 30건 분석\n"

    def test_with_headline_no_source(self):
        out = summary_intro("2026-05-22", "암호화폐 핵심 뉴스", "ETF 승인", detail="93건 분석")
        assert out == "**2026-05-22** 암호화폐 핵심 뉴스: **ETF 승인**. 93건 분석\n"

    def test_headline_missing_fallback(self):
        out = summary_intro("2026-05-22", "암호화폐 시장", None, detail="93건 분석 — 핵심 테마: 비트코인")
        assert out == "**2026-05-22** 암호화폐 시장 — 93건 분석 — 핵심 테마: 비트코인\n"

    def test_headline_missing_no_detail(self):
        out = summary_intro("2026-05-22", "오늘 보고", None)
        assert out == "**2026-05-22** 오늘 보고.\n"

    def test_trailing_newline(self):
        # Callers can prepend without extra spacing
        out = summary_intro("d", "l", "h", detail="x")
        assert out.endswith("\n")


class TestFooterMeta:
    def test_string_sources(self):
        out = footer_meta("2026-05-22 12:30 KST", "Blockchain.com, Etherscan")
        assert 'class="wm-footer-meta"' in out
        assert "수집 시각: 2026-05-22 12:30 KST" in out
        assert "소스: Blockchain.com, Etherscan" in out

    def test_iterable_sources_joined_with_comma(self):
        out = footer_meta("ts", ["Reuters", "Bloomberg", "GDELT"])
        assert "Reuters, Bloomberg, GDELT" in out

    def test_iterable_sources_skip_empty(self):
        out = footer_meta("ts", ["Reuters", "", "Bloomberg"])
        assert "Reuters, Bloomberg" in out
        assert "Reuters, , Bloomberg" not in out

    def test_no_sources_renders_na(self):
        out = footer_meta("ts", [])
        assert "소스: N/A" in out
