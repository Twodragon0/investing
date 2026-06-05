"""Unit tests for scripts/check_description_quality.py."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import check_description_quality as cdq


def _write_post(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_post(
    tmp_path: Path,
    filename: str,
    date_str: str,
    title: str = "Test Title",
    description: str = "Real content about Bitcoin prices reaching new highs in Q1 2026.",
    desc_field: str = "description_ko",
) -> Path:
    post = tmp_path / filename
    _write_post(
        post,
        f"---\ntitle: {title}\ndate: {date_str}\n{desc_field}: {description}\n---\nbody text\n",
    )
    return post


# ---------------------------------------------------------------------------
# _is_boilerplate
# ---------------------------------------------------------------------------


def test_is_boilerplate_returns_false_for_real_content():
    desc = "Bitcoin surged 15% in Q1 2026, reaching $85,000 amid institutional demand."
    assert cdq._is_boilerplate(desc) is False


def test_is_boilerplate_returns_false_for_empty_string():
    assert cdq._is_boilerplate("") is False


def test_is_boilerplate_detects_site_phrase():
    assert cdq._is_boilerplate("Motley Fool provides investment advice for individual investors.") is True


def test_is_boilerplate_detects_synthetic_marker():
    assert cdq._is_boilerplate("이 뉴스는 관련 시장 뉴스입니다.") is True


def test_is_boilerplate_detects_short_desc_with_no_article_specific_content():
    # Under 35 chars, no specific content identifiers
    assert cdq._is_boilerplate("최신 뉴스입니다.") is True


def test_is_boilerplate_detects_site_boilerplate_pattern():
    # Matches _SITE_BOILERPLATE_PATTERNS: "the world's leading..."
    assert cdq._is_boilerplate("The world's leading financial news provider.") is True


def test_is_boilerplate_ok_for_real_korean_content():
    desc = "삼성전자가 2026년 1분기 영업이익 10조 원을 달성했다고 발표했다."
    assert cdq._is_boilerplate(desc) is False


# ---------------------------------------------------------------------------
# _has_translation_issue
# ---------------------------------------------------------------------------


def test_has_translation_issue_returns_false_for_clean_text():
    assert cdq._has_translation_issue("Bitcoin prices rose sharply today.") is False


def test_has_translation_issue_returns_false_for_empty():
    assert cdq._has_translation_issue("") is False


def test_has_translation_issue_detects_mojibake():
    # 3+ consecutive Latin-1 supplement chars
    assert cdq._has_translation_issue("ÃÂÃ 가격이 상승했습니다.") is True


def test_has_translation_issue_detects_domain_suffix():
    # Korean text ending with a domain brand
    assert cdq._has_translation_issue("비트코인 가격이 급등했습니다 coindesk.") is True


def test_has_translation_issue_detects_source_leak():
    # Korean sentence ending with Korean media brand
    assert cdq._has_translation_issue("비트코인 가격이 크게 올랐습니다 야후.") is True


# ---------------------------------------------------------------------------
# _is_title_repeat
# ---------------------------------------------------------------------------


def test_is_title_repeat_returns_false_for_empty_inputs():
    assert cdq._is_title_repeat("", "Some Title") is False
    assert cdq._is_title_repeat("Some description", "") is False


def test_is_title_repeat_detects_near_identical_overlap():
    title = "Bitcoin Price Reaches New High"
    desc = "Bitcoin Price Reaches New High in 2026"
    assert cdq._is_title_repeat(desc, title) is True


def test_is_title_repeat_returns_false_for_unrelated_content():
    title = "Fed Rate Decision"
    desc = "Samsung Electronics reported strong earnings for Q1 2026."
    assert cdq._is_title_repeat(desc, title) is False


def test_is_title_repeat_returns_false_for_partial_overlap():
    title = "Global Markets Weekly Summary Report Analysis"
    desc = "Oil prices dropped sharply."
    assert cdq._is_title_repeat(desc, title) is False


# ---------------------------------------------------------------------------
# _extract_front_matter
# ---------------------------------------------------------------------------


def test_extract_front_matter_reads_description_ko():
    text = "---\ntitle: My Title\ndate: 2026-04-17\ndescription_ko: Korean description text\n---\n"
    desc, title = cdq._extract_front_matter(text)
    assert desc == "Korean description text"
    assert title == "My Title"


def test_extract_front_matter_falls_back_to_description():
    text = "---\ntitle: My Title\ndate: 2026-04-17\ndescription: English description text\n---\n"
    desc, title = cdq._extract_front_matter(text)
    assert desc == "English description text"
    assert title == "My Title"


def test_extract_front_matter_returns_empty_when_no_match():
    text = "---\ndate: 2026-04-17\n---\nbody only\n"
    desc, title = cdq._extract_front_matter(text)
    assert desc == ""
    assert title == ""


def test_extract_front_matter_strips_quotes():
    text = '---\ntitle: "Quoted Title"\ndescription_ko: "Quoted desc"\n---\n'
    desc, title = cdq._extract_front_matter(text)
    assert desc == "Quoted desc"
    assert title == "Quoted Title"


# ---------------------------------------------------------------------------
# _post_date
# ---------------------------------------------------------------------------


def test_post_date_parses_valid_date():
    text = "---\ndate: 2026-04-17\ntitle: Test\n---\n"
    result = cdq._post_date(text)
    assert result is not None
    assert result.year == 2026
    assert result.month == 4
    assert result.day == 17


def test_post_date_returns_none_when_no_date_field():
    text = "---\ntitle: No date here\n---\n"
    assert cdq._post_date(text) is None


def test_post_date_returns_none_for_invalid_format():
    # _DATE_RE requires YYYY-MM-DD; partial match still parses if valid digits
    text = "---\ndate: not-a-date\n---\n"
    assert cdq._post_date(text) is None


# ---------------------------------------------------------------------------
# collect_posts
# ---------------------------------------------------------------------------


def test_collect_posts_includes_recent_posts(tmp_path):
    today = datetime.now(UTC).date()
    _make_post(
        tmp_path,
        f"{today}-recent.md",
        str(today),
        title="Recent Post",
        description="Bitcoin hit $90,000 today in a remarkable rally.",
    )
    results = cdq.collect_posts(tmp_path, days=3)
    assert len(results) == 1
    assert results[0]["title"] == "Recent Post"


def test_collect_posts_excludes_old_posts(tmp_path):
    today = datetime.now(UTC).date()
    old_date = today - timedelta(days=10)
    _make_post(
        tmp_path,
        f"{old_date}-old.md",
        str(old_date),
    )
    results = cdq.collect_posts(tmp_path, days=3)
    assert len(results) == 0


def test_collect_posts_filters_by_days_boundary(tmp_path):
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    too_old = today - timedelta(days=5)

    _make_post(tmp_path, f"{today}-a.md", str(today), title="Today")
    _make_post(tmp_path, f"{yesterday}-b.md", str(yesterday), title="Yesterday")
    _make_post(tmp_path, f"{too_old}-c.md", str(too_old), title="OldPost")

    results = cdq.collect_posts(tmp_path, days=2)
    titles = [r["title"] for r in results]
    assert "Today" in titles
    assert "Yesterday" in titles
    assert "OldPost" not in titles


def test_collect_posts_returns_empty_for_empty_dir(tmp_path):
    assert cdq.collect_posts(tmp_path, days=7) == []


# ---------------------------------------------------------------------------
# classify_posts
# ---------------------------------------------------------------------------


def _make_post_dict(desc: str, title: str = "Some Title", body: str = "") -> dict:
    return {
        "file": "test-post.md",
        "date": datetime.now(UTC).date(),
        "description": desc,
        "title": title,
        "body": body or f"---\ntitle: {title}\n---\n{desc}",
    }


def test_classify_posts_counts_real_content():
    posts = [_make_post_dict("Bitcoin surged 20% to $90,000 amid institutional buying in Q1 2026.")]
    stats = cdq.classify_posts(posts)
    assert len(stats["real"]) == 1
    assert stats["total"] == 1
    assert len(stats["boilerplate"]) == 0


def test_classify_posts_counts_boilerplate():
    posts = [_make_post_dict("Motley Fool provides investment insights for individual investors.")]
    stats = cdq.classify_posts(posts)
    assert len(stats["boilerplate"]) == 1
    assert len(stats["real"]) == 0


def test_classify_posts_counts_title_repeat():
    title = "Bitcoin Price Surges"
    posts = [_make_post_dict("Bitcoin Price Surges Today", title=title)]
    stats = cdq.classify_posts(posts)
    assert len(stats["title_repeat"]) == 1


def test_classify_posts_counts_no_desc():
    posts = [_make_post_dict("")]
    stats = cdq.classify_posts(posts)
    assert len(stats["no_desc"]) == 1
    assert len(stats["real"]) == 0


def test_classify_posts_detects_translation_issue():
    posts = [_make_post_dict("비트코인 가격이 급등했습니다 coindesk.")]
    stats = cdq.classify_posts(posts)
    assert len(stats["translation_issues"]) == 1


def test_classify_posts_detects_mojibake_in_body():
    body = "---\ntitle: Test\n---\nÃÂÃ body corruption here"
    posts = [_make_post_dict("Normal description with real content today.", body=body)]
    stats = cdq.classify_posts(posts)
    assert len(stats["mojibake"]) == 1


def test_classify_posts_mixed_set():
    posts = [
        _make_post_dict("Bitcoin reached $100,000 for the first time in 2026."),
        _make_post_dict("Motley Fool is a premier financial media brand for investors."),
        _make_post_dict(""),
    ]
    stats = cdq.classify_posts(posts)
    assert stats["total"] == 3
    assert len(stats["real"]) == 1
    assert len(stats["boilerplate"]) == 1
    assert len(stats["no_desc"]) == 1


# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------


def test_pct_returns_percentage_string():
    assert cdq._pct(1, 4) == "25.0%"


def test_pct_returns_zero_when_total_is_zero():
    assert cdq._pct(0, 0) == "0.0%"


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


def test_format_text_smoke():
    stats = {
        "total": 5,
        "real": [_make_post_dict("Real content for BTC rally 2026.")],
        "boilerplate": [],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_text(stats, days=7)
    assert "Description Quality Report" in output
    assert "Posts scanned" in output
    assert "5" in output


def test_format_text_includes_boilerplate_section():
    post = _make_post_dict("Motley Fool investment content for everyday investors.")
    post["file"] = "2026-04-17-bp.md"
    stats = {
        "total": 1,
        "real": [],
        "boilerplate": [post],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_text(stats, days=1)
    assert "Boilerplate posts:" in output
    assert "2026-04-17-bp.md" in output


def test_format_text_includes_title_repeat_section():
    post = _make_post_dict("Bitcoin Price Surges Today", title="Bitcoin Price Surges")
    post["file"] = "2026-04-17-tr.md"
    stats = {
        "total": 1,
        "real": [],
        "boilerplate": [],
        "title_repeat": [post],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_text(stats, days=1)
    assert "Title-repeat posts:" in output


def test_format_text_includes_translation_issue_section():
    post = _make_post_dict("비트코인 급등 coindesk.")
    post["file"] = "2026-04-17-ti.md"
    stats = {
        "total": 1,
        "real": [post],
        "boilerplate": [],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [post],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_text(stats, days=1)
    assert "Translation-issue posts:" in output


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------


def test_format_markdown_smoke():
    stats = {
        "total": 3,
        "real": [_make_post_dict("Real BTC 2026 content here is good.")],
        "boilerplate": [],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_markdown(stats, days=7)
    assert "## " in output
    assert "Description Quality Report" in output
    assert "| 전체 포스트 |" in output


def test_format_markdown_shows_warning_when_boilerplate_high():
    # Force bp_pct >= 30: 2 boilerplate out of 2
    posts = [
        _make_post_dict("Seeking Alpha financial analysis for portfolio management."),
        _make_post_dict("Motley Fool investment insights for retail investors today."),
    ]
    stats = {
        "total": 2,
        "real": [],
        "boilerplate": posts,
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_markdown(stats, days=1)
    assert "경고" in output or "⚠️" in output


def test_format_markdown_uses_checkmark_when_clean():
    stats = {
        "total": 10,
        "real": [_make_post_dict(f"Real content {i} with Bitcoin $90k rally 2026.") for i in range(10)],
        "boilerplate": [],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [],
    }
    output = cdq.format_markdown(stats, days=7)
    assert "✅" in output


def test_format_markdown_uses_error_icon_when_mojibake():
    post = _make_post_dict("Good content here about markets 2026.")
    stats = {
        "total": 1,
        "real": [post],
        "boilerplate": [],
        "title_repeat": [],
        "no_desc": [],
        "translation_issues": [],
        "ascii_ratio_high": [],
        "mojibake": [post],
    }
    output = cdq.format_markdown(stats, days=1)
    assert "❌" in output


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


def test_main_returns_3_when_no_posts_in_range(tmp_path, monkeypatch, capsys):
    """Zero posts analyzed must exit non-zero (code 3) with a clear error message.

    Even if --days N is given and no posts fall within the window, that is still
    a failure — not a clean result.  The old code returned 0 (0% boilerplate)
    which masked the 2026-04-21~23 silent collector outage for three days.
    """
    # tmp_path exists but has no .md files → collect_posts returns []
    monkeypatch.setattr(sys, "argv", ["cdq", "--posts-dir", str(tmp_path), "--days", "7"])
    result = cdq.main()
    assert result != 0, "exit code must be non-zero when no posts are analyzed"
    assert result == 3
    err = capsys.readouterr().err
    assert "no posts" in err.lower() or "no post" in err.lower()


def test_main_returns_2_when_posts_dir_missing(tmp_path, monkeypatch):
    missing = tmp_path / "nonexistent"
    monkeypatch.setattr(sys, "argv", ["cdq", "--posts-dir", str(missing)])
    assert cdq.main() == 2


def test_main_returns_0_for_clean_posts(tmp_path, monkeypatch, capsys):
    today = datetime.now(UTC).date()
    _make_post(
        tmp_path,
        f"{today}-clean.md",
        str(today),
        title="비트코인 2026년 1분기 랠리",
        description="비트코인은 2026년 1분기에 강력한 기관 수요로 $90,000까지 상승했습니다.",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cdq", "--posts-dir", str(tmp_path), "--days", "1"],
    )
    result = cdq.main()
    assert result == 0
    out = capsys.readouterr().out
    assert "Description Quality Report" in out


def test_main_returns_1_when_boilerplate_exceeds_threshold(tmp_path, monkeypatch):
    today = datetime.now(UTC).date()
    # All 2 posts are boilerplate -> 100% boilerplate > 30%
    for i in range(2):
        _make_post(
            tmp_path,
            f"{today}-bp{i}.md",
            str(today),
            description="Motley Fool delivers premier investment insights for all investors.",
        )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cdq", "--posts-dir", str(tmp_path), "--days", "1"],
    )
    assert cdq.main() == 1


def test_main_returns_1_when_mojibake_found(tmp_path, monkeypatch):
    today = datetime.now(UTC).date()
    post = tmp_path / f"{today}-mj.md"
    _write_post(
        post,
        f"---\ntitle: Mojibake Post\ndate: {today}\ndescription_ko: Good real content for BTC 2026.\n---\nÃÂÃ body corruption here\n",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cdq", "--posts-dir", str(tmp_path), "--days", "1"],
    )
    assert cdq.main() == 1


def test_main_markdown_format(tmp_path, monkeypatch, capsys):
    today = datetime.now(UTC).date()
    _make_post(
        tmp_path,
        f"{today}-md.md",
        str(today),
        description="비트코인은 2026년 ETF 자금 유입에 힘입어 $95,000 사상 최고치를 기록했습니다.",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cdq", "--posts-dir", str(tmp_path), "--days", "1", "--format", "markdown"],
    )
    result = cdq.main()
    assert result == 0
    out = capsys.readouterr().out
    assert "## " in out
    assert "| 전체 포스트 |" in out


# ---------------------------------------------------------------------------
# Body description artifact detection (news-desc / p0-desc segments)
# ---------------------------------------------------------------------------

_NEWS_DESC = '<p class="news-desc">{}</p>'
_P0_DESC = '<span class="p0-desc">{}</span>'


def test_segment_has_artifact_trailing_ad_tail():
    assert cdq._segment_has_artifact("다우 가격이 더 높아졌습니다. 관련 광고.") is True


def test_segment_has_artifact_mangled_related_info():
    assert cdq._segment_has_artifact("가격이 폭락했습니다. 등급락 관련정보.") is True


def test_segment_has_artifact_misleading_bare_number():
    # "$73,000" present and a contradictory bare "($73)" annotation.
    assert cdq._segment_has_artifact("$73,000에 고정되었습니다. ($73)") is True


def test_segment_has_artifact_clean_segment_false():
    assert cdq._segment_has_artifact("비트코인이 사상 최고가를 경신했습니다.") is False


def test_segment_no_artifact_for_lone_bare_number():
    # A bare "($73)" with no richer number is not flagged (could be legitimate).
    assert cdq._segment_has_artifact("가격이 $73 수준입니다. ($73)") is False


def test_segment_no_artifact_for_two_distinct_figures():
    # "$73,000" and an unrelated "($500)" are distinct — not a truncation.
    assert cdq._segment_has_artifact("가격은 $73,000이고 수수료는 ($500)입니다.") is False


def test_misleading_number_k_suffix_flagged():
    # "$73K" with a contradictory bare "($73)" annotation is misleading.
    assert cdq._is_misleading_number("$73K 부근입니다. ($73)") is True


def test_segment_no_artifact_for_legit_보도_suffix():
    # Legitimate synthetic suffix must not be treated as a body artifact.
    assert cdq._segment_has_artifact("비트코인 급락 관련 보도.") is False


def test_segment_artifact_for_address_tail():
    assert cdq._segment_has_artifact("폭락을 경고했습니다. 급락 관련 주소.") is True


def test_count_body_artifacts_counts_each_segment():
    body = (
        _NEWS_DESC.format("가격이 폭락했습니다. 등급락 관련정보.")
        + "\n"
        + _P0_DESC.format("$73,000에 고정되었습니다. ($73)")
        + "\n"
        + _NEWS_DESC.format("정상적인 한국어 요약 문장입니다.")
    )
    assert cdq._count_body_artifacts(body) == 2


def test_count_body_artifacts_ignores_cross_tag_mismatch():
    # A malformed <p ...>...</span> must NOT be extracted as a valid segment.
    body = '<p class="news-desc">가격이 폭락했습니다. 관련 광고.</span>'
    assert cdq._count_body_artifacts(body) == 0


def test_classify_posts_collects_body_artifacts():
    body = _NEWS_DESC.format("가격이 폭락했습니다. 등급락 관련정보.")
    posts = [_make_post_dict("정상 요약입니다.", body=body)]
    stats = cdq.classify_posts(posts)
    assert len(stats["body_artifacts"]) == 1
    assert stats["body_artifacts"][0]["artifact_count"] == 1


def test_main_fails_on_body_artifacts(tmp_path, monkeypatch, capsys):
    post = tmp_path / "2026-06-02-x.md"
    today = datetime.now(UTC).date().isoformat()
    body_seg = _NEWS_DESC.format("가격이 폭락했습니다. 등급락 관련정보.")
    real_desc = "비트코인이 기관 매수세에 힘입어 9만 달러를 돌파하며 2026년 1분기 최고가를 기록했습니다."
    _write_post(
        post,
        f"---\ntitle: T\ndate: {today}\ndescription_ko: {real_desc}\n---\n{body_seg}\n",
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--days", "1", "--posts-dir", str(tmp_path)])
    assert cdq.main() == 1
    assert "body description artifact" in capsys.readouterr().err.lower()
