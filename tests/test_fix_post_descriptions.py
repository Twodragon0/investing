"""tests/test_fix_post_descriptions.py — fix_post_descriptions 단위 테스트."""

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import fix_post_descriptions as fpd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _post_content(
    title: str = "Test Title",
    description: str = "The Federal Reserve raised rates by 50bps in April 2026 amid inflation concerns.",
    description_ko: str = "",
    date_str: str = "2026-04-17",
    source: str = "",
    body: str = "",
) -> str:
    lines = [
        "---",
        f"title: {title}",
        f'description: "{description}"',
        f"date: {date_str}",
    ]
    if description_ko:
        lines.append(f'description_ko: "{description_ko}"')
    if source:
        lines.append(f"source: {source}")
    lines.append("---")
    if body:
        lines.append(body)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# _strip_quotes
# ---------------------------------------------------------------------------


class TestStripQuotes:
    def test_strips_double_quotes(self):
        assert fpd._strip_quotes('"hello"') == "hello"

    def test_strips_single_quotes(self):
        assert fpd._strip_quotes("'hello'") == "hello"

    def test_strips_whitespace(self):
        assert fpd._strip_quotes("  hello  ") == "hello"

    def test_no_quotes_unchanged(self):
        assert fpd._strip_quotes("hello") == "hello"

    def test_empty_string(self):
        assert fpd._strip_quotes("") == ""


# ---------------------------------------------------------------------------
# _is_boilerplate
# ---------------------------------------------------------------------------


class TestIsBoilerplate:
    def test_empty_string_not_boilerplate(self):
        assert fpd._is_boilerplate("") is False

    def test_bloomberg_phrase_detected(self):
        assert fpd._is_boilerplate("bloomberg provides financial news and data") is True

    def test_coindesk_is_detected(self):
        assert fpd._is_boilerplate("coindesk is the leading crypto news site") is True

    def test_short_desc_no_specifics_is_boilerplate(self):
        assert fpd._is_boilerplate("짧은 내용") is True

    def test_synthetic_marker_detected(self):
        assert fpd._is_boilerplate("비트코인 관련 소식입니다") is True

    def test_real_content_not_boilerplate(self):
        desc = "Bitcoin surged 5% today as institutional investors increased their positions significantly."
        assert fpd._is_boilerplate(desc) is False

    def test_seeking_alpha_detected(self):
        assert fpd._is_boilerplate("seeking alpha covers this topic today") is True

    def test_motley_fool_detected(self):
        assert fpd._is_boilerplate("motley fool recommends these stocks") is True

    def test_world_leading_pattern(self):
        assert fpd._is_boilerplate("the world's leading provider of crypto news") is True

    def test_original_article_marker(self):
        assert fpd._is_boilerplate("원문에서 세부 내용을 확인하세요") is True

    def test_korean_real_content_not_boilerplate(self):
        desc = "비트코인이 2026년 4월 기준 $95,000를 돌파했으며 기관 투자자들의 매수세가 이어지고 있습니다."
        assert fpd._is_boilerplate(desc) is False


# ---------------------------------------------------------------------------
# _is_title_repeat
# ---------------------------------------------------------------------------


class TestIsTitleRepeat:
    def test_identical_strings_is_repeat(self):
        title = "Bitcoin ETF Approval"
        assert fpd._is_title_repeat(title, title) is True

    def test_empty_desc_returns_false(self):
        assert fpd._is_title_repeat("", "Bitcoin ETF") is False

    def test_empty_title_returns_false(self):
        assert fpd._is_title_repeat("Bitcoin ETF Approval Today", "") is False

    def test_different_content_not_repeat(self):
        desc = "가나다라마바사아자차카타파하"
        title = "qwerty uiop asdfghjkl zxcvbnm"
        assert fpd._is_title_repeat(desc, title) is False

    def test_near_duplicate_is_repeat(self):
        title = "비트코인 ETF 승인 소식"
        desc = "비트코인 ETF 승인 소식이 전해졌습니다"
        assert fpd._is_title_repeat(desc, title) is True


# ---------------------------------------------------------------------------
# _is_bad_description
# ---------------------------------------------------------------------------


class TestIsBadDescription:
    def test_boilerplate_is_bad(self):
        assert fpd._is_bad_description("bloomberg covers financial news", "Bitcoin ETF") is True

    def test_title_repeat_is_bad(self):
        title = "Bitcoin ETF Approval"
        assert fpd._is_bad_description(title, title) is True

    def test_good_description_not_bad(self):
        desc = "The SEC approved spot Bitcoin ETFs today, marking a major milestone for crypto adoption."
        title = "Bitcoin ETF Approved"
        assert fpd._is_bad_description(desc, title) is False


# ---------------------------------------------------------------------------
# _parse_front_matter
# ---------------------------------------------------------------------------


class TestParseFrontMatter:
    def test_valid_front_matter(self):
        text = "---\ntitle: Test\ndate: 2026-01-01\n---\nbody"
        start, end = fpd._parse_front_matter(text)
        assert start == 3
        assert end > start

    def test_no_front_matter_returns_minus1(self):
        text = "Just plain content."
        start, end = fpd._parse_front_matter(text)
        assert start == -1
        assert end == -1

    def test_unclosed_front_matter_returns_minus1(self):
        text = "---\ntitle: Test\nno closing delimiters"
        start, end = fpd._parse_front_matter(text)
        assert start == -1
        assert end == -1


# ---------------------------------------------------------------------------
# _get_field
# ---------------------------------------------------------------------------


class TestGetField:
    def test_extracts_description_field(self):
        text = 'title: My Post\ndescription: "Some description here"\ndate: 2026-01-01'
        result = fpd._get_field(text, fpd._DESC_RE)
        assert result == "Some description here"

    def test_missing_field_returns_empty(self):
        text = "title: My Post\ndate: 2026-01-01"
        result = fpd._get_field(text, fpd._DESC_RE)
        assert result == ""

    def test_extracts_title_field(self):
        text = "title: Bitcoin News\ndescription: test"
        result = fpd._get_field(text, fpd._TITLE_RE)
        assert result == "Bitcoin News"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        s = "Short text."
        assert fpd._truncate(s, 200) == s

    def test_truncates_at_sentence_boundary(self):
        s = "First sentence. " + "x" * 200
        result = fpd._truncate(s, 50)
        assert "First sentence" in result
        assert len(result) <= 53

    def test_truncates_with_ellipsis_when_no_boundary(self):
        s = "a" * 300
        result = fpd._truncate(s, 100)
        assert result.endswith("…")

    def test_truncates_at_exclamation(self):
        s = "Alert! " + "y" * 200
        result = fpd._truncate(s, 20)
        assert "!" in result

    def test_truncates_at_question_mark(self):
        s = "Is this right? " + "z" * 200
        result = fpd._truncate(s, 20)
        assert "?" in result

    def test_exact_length_unchanged(self):
        s = "a" * 50
        assert fpd._truncate(s, 50) == s


# ---------------------------------------------------------------------------
# _replace_description_in_text
# ---------------------------------------------------------------------------


class TestReplaceDescriptionInText:
    def _make_post(self, description):
        return f'---\ntitle: Test Post\ndescription: "{description}"\ndate: 2026-01-01\n---\nBody content here.'

    def test_replaces_description(self):
        content = self._make_post("Old description text here for testing purposes.")
        result = fpd._replace_description_in_text(content, "New description.")
        assert 'description: "New description."' in result

    def test_preserves_other_fields(self):
        content = self._make_post("Old description.")
        result = fpd._replace_description_in_text(content, "New description.")
        assert "title: Test Post" in result
        assert "date: 2026-01-01" in result

    def test_no_front_matter_unchanged(self):
        content = "No front matter at all."
        result = fpd._replace_description_in_text(content, "New value.")
        assert result == content

    def test_body_preserved(self):
        content = self._make_post("Old desc.")
        result = fpd._replace_description_in_text(content, "New desc.")
        assert "Body content here." in result

    def test_old_value_removed(self):
        content = self._make_post("Old boilerplate text.")
        result = fpd._replace_description_in_text(content, "New good text.")
        assert "Old boilerplate text." not in result


# ---------------------------------------------------------------------------
# _extract_worldmonitor_desc
# ---------------------------------------------------------------------------


class TestExtractWorldmonitorDesc:
    def _make_wm_post(self, total=42, themes="지정학·에너지", source="GDELT"):
        return (
            f'---\nsource: "worldmonitor"\n---\n'
            f'<div class="alert-box">'
            f"총 수집: <strong>{total}건</strong> "
            f"핵심 테마: <strong>{themes}</strong> "
            f"집중 출처: <strong>{source}</strong>"
            f"</div>"
        )

    def test_extracts_worldmonitor_desc(self):
        content = self._make_wm_post()
        result = fpd._extract_worldmonitor_desc(content)
        assert "42건" in result
        assert "지정학·에너지" in result

    def test_no_worldmonitor_source_returns_empty(self):
        content = "---\nsource: coindesk\n---\nSome content"
        result = fpd._extract_worldmonitor_desc(content)
        assert result == ""

    def test_missing_total_returns_empty(self):
        content = '---\nsource: "worldmonitor"\n---\n핵심 테마: <strong>지정학</strong>'
        result = fpd._extract_worldmonitor_desc(content)
        assert result == ""

    def test_source_included_in_desc(self):
        content = self._make_wm_post(source="Reuters")
        result = fpd._extract_worldmonitor_desc(content)
        assert "Reuters" in result

    def test_no_source_field_uses_gdelt_fallback(self):
        content = '---\nsource: "worldmonitor"\n---\n총 수집: <strong>10건</strong> 핵심 테마: <strong>에너지</strong>'
        result = fpd._extract_worldmonitor_desc(content)
        assert "GDELT" in result


# ---------------------------------------------------------------------------
# _extract_body_candidate
# ---------------------------------------------------------------------------


class TestExtractBodyCandidate:
    def test_extracts_news_desc_paragraph(self):
        content = (
            "---\ntitle: Test\n---\n"
            '<p class="news-desc">Bitcoin surged 10% today amid strong institutional demand and positive ETF news flow.</p>'
        )
        result = fpd._extract_body_candidate(content)
        assert "Bitcoin surged" in result

    def test_extracts_plain_paragraph(self):
        content = (
            "---\ntitle: Test\n---\n"
            "비트코인이 오늘 강한 상승세를 보이며 기관 투자자들의 매수세가 이어지고 있습니다. 시장 전망도 긍정적입니다."
        )
        result = fpd._extract_body_candidate(content)
        assert "비트코인" in result

    def test_no_content_returns_empty(self):
        content = "---\ntitle: Test\n---\n"
        result = fpd._extract_body_candidate(content)
        assert result == ""

    def test_skips_boilerplate_content(self):
        content = (
            "---\ntitle: Test\n---\n"
            "bloomberg is the world's leading financial information provider for institutional clients."
        )
        result = fpd._extract_body_candidate(content)
        assert result == ""

    def test_no_front_matter_treats_as_body(self):
        content = "비트코인 가격이 사상 최고가를 기록했습니다. 오늘 시장에서 강한 상승세가 포착되었으며 BTC는 $100K를 돌파했습니다."
        result = fpd._extract_body_candidate(content)
        assert "비트코인" in result

    def test_skips_lines_with_http(self):
        content = (
            "---\ntitle: Links\n---\n"
            "https://example.com/some-very-long-url-that-could-fool-the-extractor\n"
            "The actual content about Bitcoin reaching new highs due to institutional demand globally in 2026.\n"
        )
        result = fpd._extract_body_candidate(content)
        assert "http" not in result


# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------


class TestPct:
    def test_zero_total_returns_zero_pct(self):
        assert fpd._pct(0, 0) == "0.0%"

    def test_half_returns_50pct(self):
        assert fpd._pct(5, 10) == "50.0%"

    def test_full_returns_100pct(self):
        assert fpd._pct(10, 10) == "100.0%"

    def test_partial_decimal(self):
        result = fpd._pct(1, 3)
        assert "33." in result


# ---------------------------------------------------------------------------
# _format_text
# ---------------------------------------------------------------------------


class TestFormatText:
    def _make_posts(self):
        return [
            {
                "file": type("F", (), {"name": "2026-01-01-test.md"})(),
                "needs_fix": True,
                "replacement": "New description text.",
                "replacement_source": "body_extract",
                "description": "Old description text.",
            },
            {
                "file": type("F", (), {"name": "2026-01-02-ok.md"})(),
                "needs_fix": False,
                "replacement": "",
                "replacement_source": "",
                "description": "Good description.",
            },
        ]

    def test_contains_total_count(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "Total scanned" in result
        assert "2" in result

    def test_dry_run_label(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "DRY-RUN" in result

    def test_applied_label(self):
        result = fpd._format_text(self._make_posts(), applied=True, dry_run=False)
        assert "APPLIED" in result

    def test_shows_fixed_posts(self):
        result = fpd._format_text(self._make_posts(), applied=False, dry_run=True)
        assert "2026-01-01-test.md" in result

    def test_empty_list(self):
        result = fpd._format_text([], applied=False, dry_run=True)
        assert "Total scanned" in result
        assert "0" in result

    def test_unfixable_section_shown(self):
        posts = [
            {
                "file": type("F", (), {"name": "2026-01-01-bad.md"})(),
                "needs_fix": True,
                "replacement": "",
                "replacement_source": "",
                "description": "Old boilerplate text.",
            }
        ]
        result = fpd._format_text(posts, applied=False, dry_run=True)
        assert "Unfixable" in result


# ---------------------------------------------------------------------------
# _format_markdown
# ---------------------------------------------------------------------------


class TestFormatMarkdown:
    def _make_posts(self, needs_fix=True, has_replacement=True):
        return [
            {
                "file": type("F", (), {"name": "2026-01-01-test.md"})(),
                "needs_fix": needs_fix,
                "replacement": "New description." if has_replacement else "",
                "replacement_source": "body_extract",
                "description": "Old description.",
            }
        ]

    def test_contains_markdown_header(self):
        result = fpd._format_markdown(self._make_posts(), applied=False, dry_run=True)
        assert "##" in result

    def test_dry_run_label_present(self):
        result = fpd._format_markdown(self._make_posts(), applied=False, dry_run=True)
        assert "DRY-RUN" in result

    def test_ok_post_shows_checkmark_icon(self):
        result = fpd._format_markdown(self._make_posts(needs_fix=False), applied=False, dry_run=True)
        assert "✅" in result

    def test_unfixable_shows_warning_icon(self):
        result = fpd._format_markdown(self._make_posts(has_replacement=False), applied=False, dry_run=True)
        assert "❌" in result

    def test_fixable_shown_in_markdown(self):
        result = fpd._format_markdown(self._make_posts(), applied=False, dry_run=True)
        assert "2026-01-01-test.md" in result


# ---------------------------------------------------------------------------
# _post_date_from_text
# ---------------------------------------------------------------------------


class TestPostDateFromText:
    def test_extracts_date(self):
        text = "---\ndate: 2026-04-13\ntitle: Test\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is not None
        assert str(result) == "2026-04-13"

    def test_no_date_returns_none(self):
        text = "---\ntitle: Test\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is None

    def test_invalid_date_returns_none(self):
        text = "---\ndate: not-a-date\n---\nBody"
        result = fpd._post_date_from_text(text)
        assert result is None


# ---------------------------------------------------------------------------
# _analyze_post
# ---------------------------------------------------------------------------


class TestAnalyzePost:
    def test_good_description_no_fix_needed(self, tmp_path):
        content = _post_content(
            title="Fed Rate Decision 2026",
            description="The Federal Reserve raised rates by 50bps in April 2026 amid inflation concerns.",
        )
        p = _make_post(tmp_path, "2026-04-17-fed.md", content)
        result = fpd._analyze_post(p)
        assert result["needs_fix"] is False
        assert result["replacement"] == ""

    def test_boilerplate_description_triggers_fix(self, tmp_path):
        content = _post_content(
            title="Motley Fool Weekly",
            description="Motley Fool provides investment advice and stock recommendations.",
        )
        p = _make_post(tmp_path, "2026-04-17-motley.md", content)
        result = fpd._analyze_post(p)
        assert result["needs_fix"] is True

    def test_uses_description_ko_as_replacement(self, tmp_path):
        ko_desc = "비트코인 ETF 승인 후 BTC 가격이 2026년 4월 95,000달러에 도달했습니다."
        content = _post_content(
            title="BTC ATH",
            description="관련 소식입니다",
            description_ko=ko_desc,
        )
        p = _make_post(tmp_path, "2026-04-17-btc.md", content)
        result = fpd._analyze_post(p)
        assert result["needs_fix"] is True
        assert result["replacement"] == ko_desc
        assert result["replacement_source"] == "description_ko"

    def test_uses_body_extract_when_no_ko(self, tmp_path):
        body = (
            "Bitcoin reached $100,000 in April 2026 following institutional "
            "adoption by major Wall Street firms including BlackRock and Fidelity."
        )
        content = _post_content(
            title="Bitcoin ATH",
            description="관련 소식입니다",
            body=body,
        )
        p = _make_post(tmp_path, "2026-04-17-btc2.md", content)
        result = fpd._analyze_post(p)
        assert result["needs_fix"] is True
        assert result["replacement_source"] == "body_extract"

    def test_worldmonitor_source_uses_alert_box(self, tmp_path):
        content = (
            "---\n"
            "title: WorldMonitor Daily\n"
            'description: "관련 소식입니다"\n'
            "date: 2026-04-17\n"
            'source: "worldmonitor"\n'
            "---\n"
            "총 수집: <strong>63건</strong> "
            "핵심 테마: <strong>에너지·지정학</strong> "
            "집중 출처: <strong>Reuters·AP</strong>\n"
        )
        p = _make_post(tmp_path, "2026-04-17-wm.md", content)
        result = fpd._analyze_post(p)
        assert result["needs_fix"] is True
        assert result["replacement_source"] == "worldmonitor_alert"

    def test_returns_dict_with_expected_keys(self, tmp_path):
        content = _post_content()
        p = _make_post(tmp_path, "2026-04-17-keys.md", content)
        result = fpd._analyze_post(p)
        for key in (
            "file",
            "date",
            "title",
            "description",
            "needs_fix",
            "replacement",
            "replacement_source",
            "content",
        ):
            assert key in result

    def test_date_parsed_from_post(self, tmp_path):
        content = _post_content(date_str="2026-04-17")
        p = _make_post(tmp_path, "2026-04-17-dated.md", content)
        result = fpd._analyze_post(p)
        assert result["date"] == date(2026, 4, 17)


# ---------------------------------------------------------------------------
# collect_posts
# ---------------------------------------------------------------------------


class TestCollectPosts:
    def test_collects_recent_post(self, tmp_path):
        today = datetime.now(tz=UTC).date().isoformat()
        content = _post_content(date_str=today)
        _make_post(tmp_path, f"{today}-recent.md", content)
        results = fpd.collect_posts(tmp_path, days=7)
        assert len(results) == 1

    def test_excludes_old_post(self, tmp_path):
        old_date = (datetime.now(tz=UTC).date() - timedelta(days=60)).isoformat()
        content = _post_content(date_str=old_date)
        _make_post(tmp_path, f"{old_date}-old.md", content)
        results = fpd.collect_posts(tmp_path, days=7)
        assert len(results) == 0

    def test_excludes_post_without_date(self, tmp_path):
        content = "---\ntitle: No Date\ndescription: some desc\n---\nbody\n"
        _make_post(tmp_path, "2026-04-17-nodate.md", content)
        results = fpd.collect_posts(tmp_path, days=7)
        assert len(results) == 0

    def test_empty_dir_returns_empty_list(self, tmp_path):
        results = fpd.collect_posts(tmp_path, days=7)
        assert results == []

    def test_collects_multiple_posts(self, tmp_path):
        today = datetime.now(tz=UTC).date().isoformat()
        yesterday = (datetime.now(tz=UTC).date() - timedelta(days=1)).isoformat()
        _make_post(tmp_path, f"{today}-a.md", _post_content(date_str=today))
        _make_post(tmp_path, f"{yesterday}-b.md", _post_content(date_str=yesterday))
        results = fpd.collect_posts(tmp_path, days=7)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# apply_fixes
# ---------------------------------------------------------------------------


class TestApplyFixes:
    def test_fixes_are_written_to_file(self, tmp_path):
        content = '---\ntitle: Test Post\ndescription: "Motley Fool provides analysis"\ndate: 2026-04-17\n---\nbody\n'
        p = _make_post(tmp_path, "2026-04-17-fix.md", content)
        posts = [
            {
                "file": p,
                "needs_fix": True,
                "replacement": "Bitcoin reached $95,000 after ETF approval in 2026.",
                "replacement_source": "description_ko",
                "content": content,
            }
        ]
        count = fpd.apply_fixes(posts)
        assert count == 1
        updated = p.read_text(encoding="utf-8")
        assert "Bitcoin reached" in updated

    def test_no_fix_when_needs_fix_false(self, tmp_path):
        content = _post_content()
        p = _make_post(tmp_path, "2026-04-17-noop.md", content)
        original = p.read_text(encoding="utf-8")
        posts = [
            {
                "file": p,
                "needs_fix": False,
                "replacement": "Some replacement",
                "replacement_source": "body_extract",
                "content": content,
            }
        ]
        count = fpd.apply_fixes(posts)
        assert count == 0
        assert p.read_text(encoding="utf-8") == original

    def test_no_fix_when_no_replacement(self, tmp_path):
        content = _post_content()
        p = _make_post(tmp_path, "2026-04-17-noreplace.md", content)
        original = p.read_text(encoding="utf-8")
        posts = [
            {
                "file": p,
                "needs_fix": True,
                "replacement": "",
                "replacement_source": "",
                "content": content,
            }
        ]
        count = fpd.apply_fixes(posts)
        assert count == 0
        assert p.read_text(encoding="utf-8") == original

    def test_returns_zero_for_empty_list(self):
        assert fpd.apply_fixes([]) == 0

    def test_multiple_files_count(self, tmp_path):
        def make_fixable(name):
            c = '---\ntitle: T\ndescription: "관련 소식입니다"\ndate: 2026-04-17\n---\nbody\n'
            path = _make_post(tmp_path, name, c)
            return {
                "file": path,
                "needs_fix": True,
                "replacement": "Good replacement text here.",
                "replacement_source": "ko",
                "content": c,
            }

        posts = [make_fixable("2026-04-17-a.md"), make_fixable("2026-04-17-b.md")]
        count = fpd.apply_fixes(posts)
        assert count == 2


# ---------------------------------------------------------------------------
# main — CLI integration
# ---------------------------------------------------------------------------


class TestMain:
    def _make_posts_dir(self, tmp_path: Path) -> Path:
        posts_dir = tmp_path / "_posts"
        posts_dir.mkdir()
        return posts_dir

    def test_dry_run_does_not_modify_file(self, tmp_path, monkeypatch):
        posts_dir = self._make_posts_dir(tmp_path)
        today = datetime.now(tz=UTC).date().isoformat()
        content = f'---\ntitle: Test\ndescription: "관련 소식입니다"\ndate: {today}\n---\nbody\n'
        p = posts_dir / f"{today}-test.md"
        p.write_text(content, encoding="utf-8")
        original = p.read_text(encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--days", "7", "--posts-dir", str(posts_dir)],
        )
        result = fpd.main()
        assert result == 0
        assert p.read_text(encoding="utf-8") == original

    def test_apply_modifies_boilerplate_file(self, tmp_path, monkeypatch):
        posts_dir = self._make_posts_dir(tmp_path)
        today = datetime.now(tz=UTC).date().isoformat()
        ko_desc = "비트코인 ETF 승인 후 BTC 가격이 2026년 4월에 상승하였습니다."
        content = (
            f'---\ntitle: BTC\ndescription: "관련 소식입니다"\ndescription_ko: "{ko_desc}"\ndate: {today}\n---\nbody\n'
        )
        p = posts_dir / f"{today}-btc.md"
        p.write_text(content, encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--days", "7", "--apply", "--posts-dir", str(posts_dir)],
        )
        result = fpd.main()
        assert result == 0
        updated = p.read_text(encoding="utf-8")
        assert ko_desc in updated

    def test_missing_posts_dir_returns_2(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--posts-dir", str(tmp_path / "nonexistent")],
        )
        result = fpd.main()
        assert result == 2

    def test_empty_posts_dir_returns_0(self, tmp_path, monkeypatch, capsys):
        posts_dir = self._make_posts_dir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--days", "7", "--posts-dir", str(posts_dir)],
        )
        result = fpd.main()
        assert result == 0

    def test_markdown_format_flag(self, tmp_path, monkeypatch, capsys):
        posts_dir = self._make_posts_dir(tmp_path)
        today = datetime.now(tz=UTC).date().isoformat()
        content = _post_content(date_str=today)
        (posts_dir / f"{today}-test.md").write_text(content, encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fix_post_descriptions.py",
                "--days",
                "7",
                "--format",
                "markdown",
                "--posts-dir",
                str(posts_dir),
            ],
        )
        result = fpd.main()
        assert result == 0
        out = capsys.readouterr().out
        assert "| Category |" in out

    def test_single_file_mode(self, tmp_path, monkeypatch, capsys):
        posts_dir = self._make_posts_dir(tmp_path)
        today = datetime.now(tz=UTC).date().isoformat()
        content = _post_content(date_str=today)
        p = tmp_path / f"{today}-single.md"
        p.write_text(content, encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--file", str(p), "--posts-dir", str(posts_dir)],
        )
        result = fpd.main()
        assert result == 0

    def test_single_file_missing_returns_2(self, tmp_path, monkeypatch):
        posts_dir = self._make_posts_dir(tmp_path)
        missing = tmp_path / "nonexistent.md"
        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--file", str(missing), "--posts-dir", str(posts_dir)],
        )
        result = fpd.main()
        assert result == 2

    def test_text_format_output_has_scanned(self, tmp_path, monkeypatch, capsys):
        posts_dir = self._make_posts_dir(tmp_path)
        today = datetime.now(tz=UTC).date().isoformat()
        content = _post_content(date_str=today)
        (posts_dir / f"{today}-test.md").write_text(content, encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            ["fix_post_descriptions.py", "--days", "7", "--posts-dir", str(posts_dir)],
        )
        fpd.main()
        out = capsys.readouterr().out
        assert "Total scanned" in out


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------


class TestConstants:
    def test_site_boilerplate_phrases_non_empty(self):
        assert len(fpd._SITE_BOILERPLATE_PHRASES) > 0

    def test_synthetic_markers_non_empty(self):
        assert len(fpd._SYNTHETIC_MARKERS) > 0

    def test_site_boilerplate_patterns_non_empty(self):
        assert len(fpd._SITE_BOILERPLATE_PATTERNS) > 0

    # The canonical positive-signal pattern now lives in
    # ``common.summary_quality.ARTICLE_SPECIFIC_RE``. ``fix_post_descriptions``
    # binds the sibling module as ``_summary_quality_mod`` and accesses the
    # pattern lazily so the cross-module circular import resolves at call time.
    def test_article_specific_re_reachable_via_facade(self):
        assert fpd._summary_quality_mod.ARTICLE_SPECIFIC_RE is not None

    def test_article_specific_re_matches_dollar_amount(self):
        assert fpd._summary_quality_mod.ARTICLE_SPECIFIC_RE.search("$100 billion fund")

    def test_article_specific_re_matches_year(self):
        assert fpd._summary_quality_mod.ARTICLE_SPECIFIC_RE.search("In 2026 the market")

    def test_article_specific_re_matches_percentage(self):
        assert fpd._summary_quality_mod.ARTICLE_SPECIFIC_RE.search("15.5% gain today")
