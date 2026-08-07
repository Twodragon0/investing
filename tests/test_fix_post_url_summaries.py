"""Tests for scripts/fix_post_url_summaries.py — per-URL summary backfill.

Network paths are stubbed throughout: the value under test is the parsing,
gating, and rewriting logic, not the fetcher (which `tests/test_enrichment*.py`
already covers).

Paths are derived from ``__file__`` rather than imported from the module under
test — importing production ``REPO_ROOT`` / ``POSTS_DIR`` into a test trips the
hermetic-writes guard.
"""

from __future__ import annotations

from pathlib import Path

import fix_post_url_summaries as mod
import pytest

# A post body shaped like the real generated cards: anchor, severity badge and
# source tag in between, then the blurb.
_CARD_POST = """---
title: "테스트 포스트"
---

<div class="news-card-item">
<span class="news-severity news-severity-med">MED</span>
<a href="https://news.google.com/rss/articles/ABC?oc=5" class="news-title" \
target="_blank" rel="noopener noreferrer">코스피 3% 상승, 반도체 주도</a>
<p class="news-desc">한겨레는 신뢰, 공정을 바탕으로 최신 뉴스와 심층 보도, 칼럼 등을 제공합니다. \
정치, 사회, 경제, 문화, 젠더, 기후변화 등 각 분야의 인사이트를 경험해보세요.</p>
<span class="source-tag">Google News KR</span>
</div>

<div class="news-card-item">
<a href="https://example.com/good" class="news-title">비트코인 8% 급등</a>
<p class="news-desc">비트코인이 24시간 동안 8% 오르며 시가총액 1조 달러를 회복했다고 거래소 데이터가 보여줍니다.</p>
</div>
"""

_P0_POST = """---
title: "알림 포스트"
---

<div class="alert-box alert-urgent"><strong>긴급</strong><ul>
<li><a href="https://example.com/p0">FBI 요원 암호화폐 절도 혐의</a> \
<span class="p0-desc">일시적인 문제가 발생했습니다. 이 페이지의 시장 데이터는 현재 지연되었습니다.</span></li>
</ul></div>
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_find_blurbs_extracts_card_url_title_and_desc(tmp_path: Path) -> None:
    path = _write(tmp_path, "2026-08-05-x.md", _CARD_POST)
    blurbs = mod.find_blurbs(path)

    assert len(blurbs) == 2
    first = blurbs[0]
    assert first.kind == "news-desc"
    assert first.url == "https://news.google.com/rss/articles/ABC?oc=5"
    assert first.title == "코스피 3% 상승, 반도체 주도"
    assert first.text.startswith("한겨레는 신뢰")


def test_find_blurbs_extracts_p0_alert_entries(tmp_path: Path) -> None:
    path = _write(tmp_path, "2026-08-05-y.md", _P0_POST)
    blurbs = [b for b in mod.find_blurbs(path) if b.kind == "p0-desc"]

    assert len(blurbs) == 1
    assert blurbs[0].url == "https://example.com/p0"
    assert "시장 데이터는 현재 지연" in blurbs[0].text


def test_plain_strips_tags_and_decodes_entities() -> None:
    assert mod._plain("<b>KCRG</b> &#124; 뉴스") == "KCRG | 뉴스"


def test_post_date_parses_filename() -> None:
    assert mod._post_date(Path("2026-08-05-daily.md")).isoformat() == "2026-08-05"


@pytest.mark.parametrize("name", ["no-date.md", "2026-13-45-bad.md"])
def test_post_date_returns_none_for_unparseable(name: str) -> None:
    assert mod._post_date(Path(name)) is None


# ---------------------------------------------------------------------------
# Flagging
# ---------------------------------------------------------------------------


def test_is_bad_flags_site_chrome() -> None:
    assert (
        mod._is_bad("일시적인 문제가 발생했습니다. 이 페이지의 시장 데이터는 현재 지연되었습니다.", "코스피 상승")
        is True
    )


def test_is_bad_flags_title_restatement() -> None:
    title = "코스피·코스닥, 오름세로 장 출발"
    assert mod._is_bad(f"{title} 한강타임즈", title) is True


def test_is_bad_passes_real_summary() -> None:
    desc = "비트코인이 24시간 동안 8% 오르며 시가총액 1조 달러를 회복했다고 거래소 데이터가 보여줍니다."
    assert mod._is_bad(desc, "비트코인 8% 급등") is False


def test_is_bad_flags_empty() -> None:
    assert mod._is_bad("", "제목") is True


def test_collect_targets_returns_only_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "2026-08-05-x.md", _CARD_POST)
    targets = mod.collect_targets(tmp_path, days=None)

    assert len(targets) == 1, "the well-formed second card must not be flagged"
    assert targets[0].title == "코스피 3% 상승, 반도체 주도"


def test_collect_targets_honours_days_window(tmp_path: Path) -> None:
    _write(tmp_path, "2020-01-01-old.md", _CARD_POST)
    assert mod.collect_targets(tmp_path, days=30) == []


# ---------------------------------------------------------------------------
# Rewriting
# ---------------------------------------------------------------------------


def test_replace_in_post_swaps_only_the_blurb_body() -> None:
    content = '<p class="news-desc">낡은 요약</p>'
    updated, ok = mod.replace_in_post(content, "낡은 요약", "새 요약입니다")

    assert ok is True
    assert updated == '<p class="news-desc">새 요약입니다</p>'


def test_replace_in_post_escapes_html_in_replacement() -> None:
    content = '<p class="news-desc">old</p>'
    updated, ok = mod.replace_in_post(content, "old", "삼성 & LG <b>급등</b>")

    assert ok is True
    assert "&amp;" in updated and "&lt;b&gt;" in updated
    assert "<b>" not in updated.replace('<p class="news-desc">', "")


def test_replace_in_post_refuses_ambiguous_anchor() -> None:
    """A blurb repeated verbatim must not be rewritten from one URL's fetch."""
    content = '<p class="news-desc">dup</p><p class="news-desc">dup</p>'
    updated, ok = mod.replace_in_post(content, "dup", "새 요약")

    assert ok is False
    assert updated == content


def test_apply_repairs_writes_only_resolved_blurbs(tmp_path: Path) -> None:
    path = _write(tmp_path, "2026-08-05-x.md", _CARD_POST)
    blurbs = mod.find_blurbs(path)
    repairs = [
        (blurbs[0], "코스피가 3% 올라 2,900선을 회복했다고 거래소가 밝혔습니다.", "refetch"),
        (blurbs[1], "", "unresolved"),
    ]

    written, posts = mod.apply_repairs(repairs)
    updated = path.read_text(encoding="utf-8")

    assert (written, posts) == (1, 1)
    assert "코스피가 3% 올라" in updated
    assert "한겨레는 신뢰" not in updated
    assert "비트코인이 24시간 동안 8%" in updated, "untouched blurb must survive"


def test_apply_repairs_is_a_noop_without_resolutions(tmp_path: Path) -> None:
    path = _write(tmp_path, "2026-08-05-x.md", _CARD_POST)
    before = path.read_text(encoding="utf-8")

    assert mod.apply_repairs([(mod.find_blurbs(path)[0], "", "unresolved")]) == (0, 0)
    assert path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Sourcing gates (network stubbed)
# ---------------------------------------------------------------------------


def _blurb(url: str = "https://example.com/a", title: str = "코스피 3% 상승") -> mod.Blurb:
    return mod.Blurb(Path("x.md"), "news-desc", url, title, "old", "old")


def test_refetch_rejects_boilerplate_from_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # The full observed string — the shortened form does not carry the
    # five-item section list the outlet-blurb detector pairs with the verb.
    chrome = (
        "한겨레는 신뢰, 공정을 바탕으로 최신 뉴스와 심층 보도, 칼럼 등을 제공합니다. "
        "정치, 사회, 경제, 문화, 젠더, 기후변화 등 각 분야의 폭 넓은 인사이트를 경험해보세요."
    )
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": chrome})
    assert mod.refetch(_blurb()) == ""


def test_refetch_rejects_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": "짧음"})
    assert mod.refetch(_blurb()) == ""


def test_refetch_accepts_related_korean_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    good = "코스피가 3% 올라 2,900선을 회복했으며 반도체 업종이 상승을 주도했다고 거래소가 밝혔습니다."
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": good})
    assert mod.refetch(_blurb()) == good


def test_refetch_translates_non_korean_result(monkeypatch: pytest.MonkeyPatch) -> None:
    english = "The KOSPI index rose 3% on Tuesday as semiconductor shares led broad gains across the market."
    korean = "코스피 지수가 화요일 3% 상승했으며 반도체주가 시장 전반의 상승을 이끌었습니다."
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": english})
    monkeypatch.setattr(mod, "translate_to_korean", lambda text: korean)
    monkeypatch.setattr(mod, "_is_title_related_description", lambda title, desc: True)

    assert mod.refetch(_blurb()) == korean


def test_refetch_returns_empty_when_google_news_link_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_resolve_google_news_url", lambda url: "")

    def _boom(url, title=""):  # pragma: no cover - must never be reached
        raise AssertionError("unresolved link must not be fetched")

    monkeypatch.setattr(mod, "fetch_page_metadata", _boom)
    assert mod.refetch(_blurb(url="https://news.google.com/rss/articles/ABC")) == ""


def test_refetch_survives_fetch_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url, title=""):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(mod, "fetch_page_metadata", _raise)
    assert mod.refetch(_blurb()) == ""


def test_repair_one_falls_back_to_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "refetch", lambda blurb: "")
    monkeypatch.setattr(mod, "synthesize", lambda blurb: "코스피가 3% 상승하며 2,900선을 회복했습니다.")

    _blurb_out, text, source = mod._repair_one(_blurb())
    assert source == "synthetic"
    assert text.startswith("코스피가 3%")


def test_repair_one_reports_unresolved_when_synthesis_is_bad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "refetch", lambda blurb: "")
    monkeypatch.setattr(mod, "synthesize", lambda blurb: "관련 소식입니다.")

    _blurb_out, text, source = mod._repair_one(_blurb())
    assert (text, source) == ("", "unresolved")


def test_synthesize_survives_generator_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(title, source, context_map):
        raise ValueError("bad title")

    monkeypatch.setattr(mod, "generate_synthetic_description", _raise)
    assert mod.synthesize(_blurb()) == ""


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_format_report_counts_each_outcome() -> None:
    repairs = [
        (_blurb(), "새 요약 A", "refetch"),
        (_blurb(), "새 요약 B", "synthetic"),
        (_blurb(), "", "unresolved"),
    ]
    report = mod.format_report(repairs, applied=False)

    assert "대상 블러브   : 3" in report
    assert "재수집 성공   : 1" in report
    assert "합성 대체     : 1" in report
    assert "해결 실패     : 1" in report
    assert "(dry-run)" in report


def test_format_report_marks_applied_runs() -> None:
    assert "적용" in mod.format_report([(_blurb(), "x", "refetch")], applied=True)


def test_repair_one_skips_synthesis_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--skip-synthetic` keeps the original blurb rather than degrading it.

    Measured on the corpus before this flag existed: the synthesis fallback
    appended source suffixes and stop-word "주요 키워드" tails, producing output
    worse than the title restatement it replaced. Re-fetch is a clear win;
    synthesis is not, so it must be switchable off.
    """
    monkeypatch.setattr(mod, "refetch", lambda blurb: "")

    def _never(blurb):  # pragma: no cover - must not be reached
        raise AssertionError("synthesis must be skipped")

    monkeypatch.setattr(mod, "synthesize", _never)

    _blurb_out, text, source = mod._repair_one(_blurb(), allow_synthesis=False)
    assert (text, source) == ("", "unresolved")


# ---------------------------------------------------------------------------
# Defects found by the first apply run (2026-08-06), reverted before commit
# ---------------------------------------------------------------------------


def test_refetch_unescapes_entities_before_storing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`&hellip;` must become `…`, not survive to be re-escaped as `&amp;hellip;`.

    The first apply wrote `&amp;hellip;` into a card, which renders as the
    literal string `&hellip;` — the entity named a character the reader never saw.
    """
    fetched = "코스피가 3% 올라 2,900선을 회복했습니다&hellip; 반도체가 상승을 주도했다고 거래소가 밝혔습니다."
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": fetched})
    monkeypatch.setattr(mod, "_is_title_related_description", lambda title, desc: True)

    result = mod.refetch(_blurb())
    assert "…" in result
    assert "&hellip;" not in result and "&amp;" not in result


def test_refetch_trims_article_bodies_to_a_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page with no meta description yields its whole body — cards want a sentence.

    The first apply put 400-800 character walls of text into cards sized for
    one or two sentences.
    """
    body = " ".join(f"{i}일 코스피가 3% 올라 2,900선을 회복했다고 한국거래소가 발표했습니다." for i in range(1, 20))
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": body})
    monkeypatch.setattr(mod, "_is_title_related_description", lambda title, desc: True)

    result = mod.refetch(_blurb())
    assert len(result) <= mod._MAX_DESC_LEN
    assert result.endswith(("다.", "…")), "trim must land on a sentence boundary or mark the cut"


def test_trim_to_sentence_keeps_short_text_untouched() -> None:
    text = "코스피가 3% 올라 2,900선을 회복했습니다."
    assert mod._trim_to_sentence(text) == text


def test_trim_to_sentence_hard_cuts_a_run_on() -> None:
    """A single sentence longer than the cap still has to be cut somewhere."""
    result = mod._trim_to_sentence("가" * 500)
    assert len(result) <= mod._MAX_DESC_LEN + 1
    assert result.endswith("…")


def test_refetch_strips_advertising_tails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ad copy rides along with fetched text and must not land in a card."""
    monkeypatch.setattr(
        mod,
        "fetch_page_metadata",
        lambda url, title="": {
            "description": "코스피가 3% 올라 2,900선을 회복했다고 한국거래소가 발표했습니다. 관련 광고 홍보."
        },
    )
    monkeypatch.setattr(mod, "_is_title_related_description", lambda title, desc: True)

    assert "관련 광고" not in mod.refetch(_blurb())


def test_refetch_rejects_institutional_slogan(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regulator's own slogan strip is not a description of its press release."""
    monkeypatch.setattr(
        mod,
        "fetch_page_metadata",
        lambda url, title="": {"description": "혁신적 금융, 포용적 금융, 신뢰받는 금융, 금융위원회 입니다."},
    )
    assert mod.refetch(_blurb(title="긴급 금융시장상황 점검회의 개최")) == ""


def test_apply_repairs_counts_only_posts_actually_written(tmp_path: Path) -> None:
    """A post whose every anchor was ambiguous is not a changed post.

    The first apply run reported "블러브 50건 / 포스트 62개" — more posts than
    blurbs, because the count included posts where every replacement was
    skipped as ambiguous.
    """
    body = '---\ntitle: T\n---\n<p class="news-desc">dup</p><p class="news-desc">dup</p>\n'
    path = tmp_path / "2026-08-05-dup.md"
    path.write_text(body, encoding="utf-8")

    blurb = mod.Blurb(path, "news-desc", "https://example.com/a", "제목", "dup", "dup")
    assert mod.apply_repairs([(blurb, "코스피가 3% 올라 2,900선을 회복했습니다.", "refetch")]) == (0, 0)
    assert path.read_text(encoding="utf-8") == body


def test_direct_only_skips_google_news_without_fetching(monkeypatch: pytest.MonkeyPatch) -> None:
    """While the redirect resolver is throttled, don't spend requests on it.

    Failed resolves are not free — they keep the block alive. `--direct-only`
    lets a run make progress on publisher URLs, which kept working throughout
    the throttling.
    """

    def _never(blurb):  # pragma: no cover - must not be reached
        raise AssertionError("google news link must not be fetched under --direct-only")

    monkeypatch.setattr(mod, "refetch", _never)

    blurb = _blurb(url="https://news.google.com/rss/articles/ABC")
    assert mod._repair_one(blurb, direct_only=True) == (blurb, "", "skipped")


def test_direct_only_still_processes_publisher_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "refetch", lambda blurb: "코스피가 3% 올라 2,900선을 회복했습니다.")

    _out, text, source = mod._repair_one(_blurb(url="https://cointelegraph.com/x"), direct_only=True)
    assert (text, source) == ("코스피가 3% 올라 2,900선을 회복했습니다.", "refetch")


def test_is_google_news_classifies_both_forms() -> None:
    assert mod.is_google_news(_blurb(url="https://news.google.com/rss/articles/A")) is True
    assert mod.is_google_news(_blurb(url="https://www.cnbc.com/a")) is False


def test_is_google_news_matches_on_host_not_substring() -> None:
    """A publisher URL that merely mentions the host in its path is an article.

    Substring matching here was flagged by CodeQL
    (`py/incomplete-url-substring-sanitization`) and would also misroute such a
    URL through the redirect resolver, which cannot resolve it.
    """
    assert mod.is_google_news(_blurb(url="https://news.google.com/rss/articles/A")) is True
    assert mod.is_google_news(_blurb(url="https://rss.news.google.com/articles/A")) is True
    assert mod.is_google_news(_blurb(url="https://evil.example.com/?next=news.google.com")) is False
    assert mod.is_google_news(_blurb(url="https://example.com/news.google.com/story")) is False


def test_resolve_passes_through_non_google_urls() -> None:
    assert mod._resolve("https://www.cnbc.com/a") == "https://www.cnbc.com/a"


# ---------------------------------------------------------------------------
# Text-only pass (no network)
# ---------------------------------------------------------------------------


def test_clean_text_strips_source_suffix() -> None:
    """The card already shows the outlet in its own tag; repeating it is noise."""
    text = "S&P500·나스닥 급락; 원유·가스·금·은 급등; 비트코인 $67K 근처로 후퇴 - The Sunday Guardian"
    assert mod.clean_text(text) == "S&P500·나스닥 급락; 원유·가스·금·은 급등; 비트코인 $67K 근처로 후퇴"


def test_clean_text_collapses_a_doubled_period() -> None:
    assert mod.clean_text("이더리움 및 XRP 가격이 하락한 이유.. 가격 동향 분석") == (
        "이더리움 및 XRP 가격이 하락한 이유. 가격 동향 분석"
    )


def test_clean_text_preserves_an_ellipsis() -> None:
    """`...` is deliberate Korean punctuation, `..` is the defect — so: no change."""
    assert mod.clean_text("비트코인·알트코인 '장중 급락'...주요 변수는 금리와 환율입니다") == ""


def test_clean_text_keeps_informative_tail() -> None:
    """A tail carrying figures is the story, so no change is proposed."""
    assert mod.clean_text("삼성전자 - 2분기 영업이익 14조 원으로 32% 증가했습니다") == ""


def test_clean_text_refuses_to_gut_a_short_blurb() -> None:
    """Stripping must not leave less than a sentence behind — so: no change."""
    assert mod.clean_text("코스피 상승 - 한국경제") == ""


def test_clean_text_returns_empty_when_nothing_to_do() -> None:
    """A no-op signals "leave this blurb alone" rather than rewriting it."""
    assert mod.clean_text("코스피가 3% 올라 2,900선을 회복했다고 거래소가 발표했습니다.") == ""


def test_collect_text_targets_finds_every_dirty_blurb(tmp_path: Path) -> None:
    """Unlike the re-fetch pass, this one looks at *all* blurbs, not just flagged ones."""
    body = (
        "---\ntitle: T\n---\n"
        '<a href="https://a.example/1" class="news-title">비트코인 후퇴</a>'
        '<p class="news-desc">S&P500·나스닥 급락; 비트코인 $67K 근처로 후퇴 - The Sunday Guardian</p>\n'
        '<a href="https://a.example/2" class="news-title">코스피 상승</a>'
        '<p class="news-desc">코스피가 3% 올라 2,900선을 회복했다고 거래소가 발표했습니다.</p>\n'
    )
    (tmp_path / "2026-08-05-x.md").write_text(body, encoding="utf-8")

    targets = mod.collect_text_targets(tmp_path, days=None)
    assert len(targets) == 1
    assert targets[0][1] == "S&P500·나스닥 급락; 비트코인 $67K 근처로 후퇴"


def test_replace_in_post_rewrites_all_copies_for_the_text_pass() -> None:
    """A pure-text rewrite is correct for every identical copy.

    The re-fetch pass must not do this — its copies point at different articles
    — but the text pass derives the replacement from the text alone.
    """
    content = '<p class="news-desc">dup</p><p class="news-desc">dup</p>'
    updated, ok = mod.replace_in_post(content, "dup", "새 요약", all_copies=True)

    assert ok is True
    assert updated.count("새 요약") == 2
    assert "dup" not in updated


def test_replace_in_post_still_refuses_duplicates_by_default() -> None:
    content = '<p class="news-desc">dup</p><p class="news-desc">dup</p>'
    assert mod.replace_in_post(content, "dup", "새 요약") == (content, False)


def test_replace_in_post_reports_missing_anchor() -> None:
    content = '<p class="news-desc">something</p>'
    assert mod.replace_in_post(content, "absent", "새 요약", all_copies=True) == (content, False)


# ---------------------------------------------------------------------------
# Bare-domain links (2026-08-07): re-fetching a homepage returns another story
# ---------------------------------------------------------------------------


def test_refetch_refuses_bare_domain_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """A link with no path is a homepage, and its content is whatever is on it today.

    The first scheduled-workflow run replaced an accurate p0 blurb with a
    summary of an entirely different article, because the stored link was
    `https://www.sedaily.com` — the publisher's front page. 155 of 2272 backfill
    targets carry such links, all `p0-desc`.
    """

    def _never(url, title=""):  # pragma: no cover - must not be reached
        raise AssertionError("a bare-domain link must not be fetched")

    monkeypatch.setattr(mod, "fetch_page_metadata", _never)

    for url in ("https://www.sedaily.com", "https://thehill.com/", "http://example.com"):
        assert mod.refetch(_blurb(url=url)) == "", url


def test_refetch_still_accepts_article_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    good = "코스피가 3% 올라 2,900선을 회복했다고 한국거래소가 발표했습니다."
    monkeypatch.setattr(mod, "fetch_page_metadata", lambda url, title="": {"description": good})
    monkeypatch.setattr(mod, "_is_title_related_description", lambda title, desc: True)

    assert mod.refetch(_blurb(url="https://www.sedaily.com/NewsView/2ABCDEF")) == good


def test_has_article_path_classification() -> None:
    assert mod._has_article_path("https://example.com/news/1") is True
    assert mod._has_article_path("https://example.com") is False
    assert mod._has_article_path("https://example.com/") is False
    # A query-only link still identifies a specific item.
    assert mod._has_article_path("https://example.com?id=42") is True


# ---------------------------------------------------------------------------
# p0 homepage link recovery (2026-08-07)
# ---------------------------------------------------------------------------


def test_recover_p0_links_uses_exact_title_match(tmp_path: Path) -> None:
    """A p0 alert whose link is a homepage can borrow the card's article link.

    `<source url>` overwrote the item's real link before render, so the article
    URL survives only where the same story also appears as a theme card in the
    same post. Matching is exact-title only: prefix matching added just 1 more
    recovery across the corpus and risks pairing the wrong story.
    """
    body = (
        "---\ntitle: T\n---\n"
        '<div class="alert-box alert-urgent"><ul>'
        '<li><a href="https://www.sedaily.com">코스피 3% 급등</a> '
        '<span class="p0-desc">요약</span></li></ul></div>\n'
        '<a href="https://news.google.com/rss/articles/ABC" class="news-title">코스피 3% 급등</a>'
        '<p class="news-desc">본문 요약입니다.</p>\n'
    )
    path = tmp_path / "2026-08-05-x.md"
    path.write_text(body, encoding="utf-8")

    assert mod.recover_p0_links(path) == 1
    assert 'href="https://www.sedaily.com"' not in path.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").count("news.google.com/rss/articles/ABC") == 2


def test_recover_p0_links_leaves_unmatched_titles_alone(tmp_path: Path) -> None:
    body = (
        "---\ntitle: T\n---\n"
        '<div class="alert-box alert-urgent"><ul>'
        '<li><a href="https://www.sedaily.com">코스피 3% 급등</a> '
        '<span class="p0-desc">요약</span></li></ul></div>\n'
        '<a href="https://news.google.com/rss/articles/ABC" class="news-title">전혀 다른 제목</a>'
        '<p class="news-desc">본문 요약입니다.</p>\n'
    )
    path = tmp_path / "2026-08-05-y.md"
    path.write_text(body, encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    assert mod.recover_p0_links(path) == 0
    assert path.read_text(encoding="utf-8") == before


def test_recover_p0_links_skips_links_that_already_work(tmp_path: Path) -> None:
    """Only homepage links are candidates; a real article link is left as is."""
    body = (
        "---\ntitle: T\n---\n"
        '<div class="alert-box alert-urgent"><ul>'
        '<li><a href="https://www.sedaily.com/NewsView/1">코스피 3% 급등</a> '
        '<span class="p0-desc">요약</span></li></ul></div>\n'
        '<a href="https://news.google.com/rss/articles/ABC" class="news-title">코스피 3% 급등</a>'
        '<p class="news-desc">본문 요약입니다.</p>\n'
    )
    path = tmp_path / "2026-08-05-z.md"
    path.write_text(body, encoding="utf-8")

    assert mod.recover_p0_links(path) == 0
    assert "sedaily.com/NewsView/1" in path.read_text(encoding="utf-8")
