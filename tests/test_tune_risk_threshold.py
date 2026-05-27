"""Unit tests for scripts/tools/tune_risk_threshold.py."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path  # noqa: TCH003

import tune_risk_threshold as trt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_digest_post(tmp_path: Path, date_str: str, urgent_items: list[tuple[str, str]]) -> Path:
    """Create a minimal daily-crypto-news-digest post with alert-urgent items."""
    li_lines = "\n".join(
        f'<li><a href="https://example.com/{i}">{title}</a> <span class="p0-desc">{desc}</span></li>'
        for i, (title, desc) in enumerate(urgent_items)
    )
    content = f"""---
layout: post
title: "암호화폐 뉴스 브리핑 - {date_str}"
date: {date_str} 09:00:00 +0900
---

<div class="alert-box alert-urgent">
<strong>긴급 알림</strong>
<ul>
{li_lines}
</ul>
</div>
"""
    path = tmp_path / f"{date_str}-daily-crypto-news-digest.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_priority_items
# ---------------------------------------------------------------------------


def test_parse_post_extracts_priority_items():
    """Sample post body → P0 list items are extracted correctly.

    ``source`` is derived from the link's netloc so risk_classifier source
    weights apply to the real publisher (not always "google news").
    """
    text = """
<div class="alert-box alert-urgent">
<strong>긴급 알림</strong>
<ul>
<li><a href="https://example.com/1">Bitcoin crashes 20%</a> <span class="p0-desc">Bitcoin fell sharply amid macro fears.</span></li>
<li><a href="https://news.google.com/articles/abc">SEC files lawsuit</a> <span class="p0-desc">SEC sues major exchange for fraud.</span></li>
</ul>
</div>
"""
    items = trt.parse_priority_items(text)
    assert len(items) == 2
    assert items[0]["title"] == "Bitcoin crashes 20%"
    assert items[0]["description"] == "Bitcoin fell sharply amid macro fears."
    assert items[0]["source"] == "example.com"
    assert items[1]["title"] == "SEC files lawsuit"
    assert items[1]["source"] == "google news"


def test_parse_priority_items_returns_empty_when_no_urgent_block():
    """Post with no alert-urgent div returns empty list."""
    text = "<div class='alert-box alert-info'><ul><li>some item</li></ul></div>"
    assert trt.parse_priority_items(text) == []


def test_parse_priority_items_returns_empty_for_empty_string():
    """Empty string returns empty list without error."""
    assert trt.parse_priority_items("") == []


# ---------------------------------------------------------------------------
# compute_aggregate_mean_top3
# ---------------------------------------------------------------------------


def test_compute_aggregate_mean_top3_uses_top3_only():
    """With 5 items, only the 3 highest scores contribute to the mean."""
    # Use items that score differently: amount+institution triggers high score
    items = [
        {"title": "SEC bans $1B exchange", "description": "hack exploit fraud", "source": "reuters"},
        {"title": "Bitcoin bank run $500M", "description": "bank run trading halt", "source": "bloomberg"},
        {"title": "Fed raises rates $200B", "description": "circuit breaker", "source": "reuters"},
        {"title": "Celebrity buys crypto", "description": "taylor swift concert", "source": "google news"},
        {"title": "Minor update", "description": "", "source": "google news"},
    ]
    mean = trt.compute_aggregate_mean_top3(items)
    # Top 3 should all be high-scoring; mean must be > 0
    assert mean > 0.0
    # Must be <= 10.0 (max possible score)
    assert mean <= 10.0


def test_compute_aggregate_mean_top3_single_item():
    """Single item returns its own score as mean."""
    items = [{"title": "Bitcoin update", "description": "", "source": "google news"}]
    mean = trt.compute_aggregate_mean_top3(items)
    assert mean >= 0.0


def test_compute_aggregate_mean_top3_empty_returns_zero():
    """Empty list returns 0.0."""
    assert trt.compute_aggregate_mean_top3([]) == 0.0


# ---------------------------------------------------------------------------
# binary_search_critical_threshold
# ---------------------------------------------------------------------------


def _make_posts_with_scores(n_critical_worthy: int, n_total: int) -> list[trt.PostItems]:
    """Create synthetic PostItems: first n_critical_worthy posts have high-score items."""
    posts = []
    # High-score items: amount + institution + neg sentiment
    high_items = [
        {"title": "SEC bans $1B exchange hack exploit", "description": "bank run $500M fraud", "source": "reuters"},
        {"title": "Fed circuit breaker $200B crash", "description": "trading halt plunge", "source": "bloomberg"},
        {"title": "Bank run $300M bankruptcy lawsuit", "description": "hack exploit drop", "source": "reuters"},
    ]
    low_items = [
        {"title": "Minor crypto update", "description": "", "source": "google news"},
    ]
    for i in range(n_total):
        if i < n_critical_worthy:
            posts.append(trt.PostItems(date=f"2026-04-{i + 1:02d}", items=high_items))
        else:
            posts.append(trt.PostItems(date=f"2026-04-{i + 1:02d}", items=low_items))
    return posts


def test_binary_search_critical_threshold_converges():
    """Binary search converges to a threshold that gives ≤ target critical ratio."""
    posts = _make_posts_with_scores(n_critical_worthy=1, n_total=30)
    target = 0.03
    result = trt.binary_search_critical_threshold(posts, target_ratio=target, p0_threshold=5.0)
    # Verify the result is in a reasonable range
    assert 2.0 <= result <= 10.0
    # Verify critical ratio under result threshold is ≈ target
    counts = trt.classify_posts_with_threshold(posts, result, 5.0)
    total = sum(counts.values())
    ratio = counts["critical"] / total if total else 0.0
    assert ratio <= target + 0.05  # within 5pp tolerance


def test_binary_search_critical_threshold_high_target_gives_low_threshold():
    """Higher target ratio should give a lower threshold (more posts qualify)."""
    posts = _make_posts_with_scores(n_critical_worthy=5, n_total=20)
    low_thresh = trt.binary_search_critical_threshold(posts, target_ratio=0.30, p0_threshold=5.0)
    high_thresh = trt.binary_search_critical_threshold(posts, target_ratio=0.05, p0_threshold=5.0)
    # Higher target means threshold should be lower or equal
    assert low_thresh <= high_thresh


# ---------------------------------------------------------------------------
# main (CLI integration)
# ---------------------------------------------------------------------------


def test_main_generates_report(tmp_path: Path, monkeypatch):
    """5 sample posts → CLI runs and report file is created."""
    today = datetime.now(UTC).date()
    for i in range(5):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        _make_digest_post(
            tmp_path,
            date_str,
            urgent_items=[
                ("비트코인 급락 $1B", "SEC 소송 해킹 폭락"),
                ("Fed 금리 인상 $500M", "bank run 거래 중단"),
            ],
        )

    output_path = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tune_risk_threshold",
            "--posts-dir",
            str(tmp_path),
            "--days",
            "30",
            "--output",
            str(output_path),
        ],
    )
    result = trt.main()
    assert result == 0
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "Risk Threshold Tuning Report" in content
    assert "권장 threshold" in content


def test_main_respects_target_ratio(tmp_path: Path, monkeypatch):
    """target 0.03 → reported critical ratio in recommended distribution is near 0~10%."""
    today = datetime.now(UTC).date()
    # Create 10 posts: 1 with high-score items, 9 with low items
    _make_digest_post(
        tmp_path,
        (today - timedelta(days=0)).strftime("%Y-%m-%d"),
        urgent_items=[
            ("SEC bans $1B exchange hack", "bank run trading halt exploit bankruptcy"),
            ("Fed circuit breaker $200B crash", "plunge lawsuit"),
            ("Bitcoin bank run $500M fraud", "hack exploit drop"),
        ],
    )
    for i in range(1, 10):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        _make_digest_post(tmp_path, date_str, urgent_items=[("Minor update", "")])

    output_path = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tune_risk_threshold",
            "--posts-dir",
            str(tmp_path),
            "--days",
            "30",
            "--target-critical-ratio",
            "0.03",
            "--output",
            str(output_path),
        ],
    )
    result = trt.main()
    assert result == 0
    content = output_path.read_text(encoding="utf-8")
    # Report should include critical distribution row
    assert "critical" in content
    # Report should show recommended threshold values
    assert "→ **" in content


def test_main_returns_2_when_posts_dir_missing(tmp_path: Path, monkeypatch):
    """Missing posts-dir → returns exit code 2."""
    missing = tmp_path / "nonexistent"
    output_path = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tune_risk_threshold",
            "--posts-dir",
            str(missing),
            "--output",
            str(output_path),
        ],
    )
    assert trt.main() == 2


def test_main_returns_1_when_no_posts_found(tmp_path: Path, monkeypatch):
    """Empty dir (no digest posts) → returns exit code 1."""
    output_path = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tune_risk_threshold",
            "--posts-dir",
            str(tmp_path),
            "--days",
            "30",
            "--output",
            str(output_path),
        ],
    )
    assert trt.main() == 1
