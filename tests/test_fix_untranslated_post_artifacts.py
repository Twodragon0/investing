"""Tests for scripts/fix_untranslated_post_artifacts.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fix_untranslated_post_artifacts import clean_post, clean_post_body

if TYPE_CHECKING:
    from pathlib import Path


def test_clean_card_english_description():
    sample = (
        "**1. [Reformation (REF) Filing - Stock Titan](https://news.google.com/...)**\n"
        "A director's 200-share IPO buy was omitted from earlier report.\n"
        '<span class="source-tag" data-source-type="regulator">SEC</span>'
    )
    cleaned, removed = clean_post_body(sample)
    assert removed == 1
    assert "A director's 200-share IPO buy" not in cleaned
    assert "**1. [Reformation (REF) Filing - Stock Titan](https://news.google.com/...)**" in cleaned
    assert '<span class="source-tag"' in cleaned


def test_clean_unclosed_link():
    sample = "## 거래소 공지\n**1. [Binance Has Completed the Stargate Finance Token Merge\n- 소셜 20건 분석"
    cleaned, removed = clean_post_body(sample)
    assert removed == 1
    assert "Binance Has Completed" not in cleaned
    assert "- 소셜 20건 분석" in cleaned


def test_clean_form4_and_bullets():
    sample = (
        "## 정치인 워치\n"
        "- 1. Form 4\\ VerifyMe, Inc. Insider Trading Activity - Stock Titan [Form 4] VerifyMe, Inc.\n"
        "- [글로벌 동향] 정상적인 한글 리스트 항목입니다."
    )
    cleaned, removed = clean_post_body(sample)
    assert removed == 1
    assert "VerifyMe" not in cleaned
    assert "정상적인 한글 리스트 항목입니다." in cleaned


def test_preserves_korean_content():
    sample = (
        "## 요약\n"
        "한국은행 기준금리 동결 소식입니다.\n"
        "**1. [삼성전자 3분기 실적 발표](https://news.google.com/...)**\n"
        "반도체 부문 영업이익이 전년 대비 증가했습니다.\n"
        '<span class="source-tag">국내 뉴스</span>'
    )
    cleaned, removed = clean_post_body(sample)
    assert removed == 0
    assert cleaned == sample


def test_clean_post_idempotency(tmp_path: Path):
    file_path = tmp_path / "sample.md"
    content = (
        "---\n"
        "title: Test Post\n"
        "---\n"
        "**1. [Test Title](https://example.com)**\n"
        "This is an untranslated English description line without any Korean.\n"
        '<span class="source-tag">Source</span>\n'
    )
    file_path.write_text(content, encoding="utf-8")

    # Pass 1: cleans artifact
    before, after = clean_post(file_path, apply=True)
    assert before == 1
    assert after == 0

    # Pass 2: idempotent, no findings left
    before2, after2 = clean_post(file_path, apply=True)
    assert before2 == 0
    assert after2 == 0
