"""`scripts/generate_weekly_digest.py` 의 수집·추출·조립·main 경로 테스트.

기존 `tests/test_generate_weekly_digest.py` 는 저널 관련 3건만 덮는다(30%). 이 파일은
나머지를 덮는다 — front matter 파싱, 주간 수집 창, 불릿 추출 2전략, 시장 데이터 정규식,
동적 description, 다이제스트 조립, `main()`.

## 이 모듈이 조용히 틀릴 수 있는 지점

주간 다이제스트는 크론이 만들고 아무도 즉시 읽지 않는다. 아래가 깨져도 워크플로우는
성공으로 끝난다:

- **수집 창** — 문자열 날짜 비교(`file_date < cutoff_str`)라 하루만 밀려도 포스트가 샌다
- **시장 데이터 정규식** — 렌더러 마크업이 바뀌면 조용히 0건이 되고 description 이 빈약해진다
  (같은 저장소에서 `enrich_existing_posts` 가 정확히 이 방식으로 5개월간 no-op 이었다)
- **불릿 추출 우선순위** — "핵심" 섹션 전략이 실패하면 점수 기반 전략으로 넘어가는데,
  그 폴백이 조용히 항상 쓰이면 요약 품질이 떨어진 채 유지된다
- **generic 필터** — 너무 넓으면 실제 내용을 버리고, 너무 좁으면 보일러플레이트를 싣는다

## 격리

`POSTS_DIR` 은 임포트 시점에 `__file__` 로부터 계산되고 `collect_weekly_posts` 가 그걸
읽는다. `main()` 은 `PostGenerator.create_post` 로 **파일을 쓴다.** 프로덕션 상수를
임포트하지 않고 monkeypatch 로 tmp 를 주입하고, `create_post` 는 대역으로 바꾼다.
시각은 `datetime` 을 고정하지 않고 **파일명 날짜를 현재 기준으로 생성**해 결정성을 얻는다.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import Any, Dict

import pytest

wd = importlib.import_module("generate_weekly_digest")


def _now():
    return datetime.now(wd.get_kst_timezone())


@pytest.fixture
def posts_dir(tmp_path, monkeypatch):
    """`POSTS_DIR` 을 tmp 로 돌린다 — 실제 `_posts/` 를 읽으면 결과가 매일 바뀐다."""
    d = tmp_path / "_posts"
    d.mkdir()
    monkeypatch.setattr(wd, "POSTS_DIR", str(d))
    return d


def _write_post(
    posts_dir, *, days_ago: int = 1, slug: str = "daily-crypto-news-digest", front: str = "", body: str = "본문"
) -> str:
    """`YYYY-MM-DD-slug.md` 를 현재 기준 상대일로 만든다."""
    date = (_now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    name = f"{date}-{slug}.md"
    (posts_dir / name).write_text(f"---\n{front}---\n{body}\n", encoding="utf-8")
    return name


# ---------------------------------------------------------------------------
# parse_post_frontmatter
# ---------------------------------------------------------------------------


class TestParsePostFrontmatter:
    def test_parses_all_standard_fields(self, tmp_path) -> None:
        f = tmp_path / "p.md"
        f.write_text(
            "---\n"
            'title: "제목입니다"\n'
            "date: 2026-08-20 09:00:00 +0900\n"
            "categories: [market-analysis]\n"
            'tags: ["a", "b"]\n'
            'excerpt: "요약문"\n'
            'image: "/assets/x.png"\n'
            'permalink: "/market-analysis/2026/08/20/slug/"\n'
            "---\n"
            "본문 내용\n",
            encoding="utf-8",
        )
        r = wd.parse_post_frontmatter(str(f))
        assert r["title"] == "제목입니다"
        assert r["categories"] == "[market-analysis]"
        assert r["tags"] == ["a", "b"]
        assert r["excerpt"] == "요약문"
        assert r["image"] == "/assets/x.png"
        assert r["permalink"] == "/market-analysis/2026/08/20/slug/"
        assert r["body"] == "본문 내용"

    def test_missing_frontmatter_returns_defaults_without_body(self, tmp_path) -> None:
        """front matter 가 없으면 기본 dict 를 낸다 — `body` 키가 아예 없다."""
        f = tmp_path / "p.md"
        f.write_text("front matter 없는 본문\n", encoding="utf-8")
        r = wd.parse_post_frontmatter(str(f))
        assert r["title"] == ""
        assert "body" not in r

    def test_unreadable_file_is_logged_and_returns_defaults(self, tmp_path, caplog) -> None:
        with caplog.at_level("WARNING"):
            r = wd.parse_post_frontmatter(str(tmp_path / "없는파일.md"))
        assert r["title"] == ""
        assert any("Failed to parse" in rec.message for rec in caplog.records)

    def test_empty_tags_yield_empty_list(self, tmp_path) -> None:
        f = tmp_path / "p.md"
        f.write_text("---\ntags: []\n---\n본문\n", encoding="utf-8")
        assert wd.parse_post_frontmatter(str(f))["tags"] == []

    def test_journal_fields_are_parsed(self, tmp_path) -> None:
        f = tmp_path / "p.md"
        f.write_text(
            "---\n"
            'journal_strategy: "추세추종"\n'
            'journal_market_regime: "상승"\n'
            'journal_day_result: "+1.2%"\n'
            'journal_trade_count: "5"\n'
            'journal_realized_pnl: "+120만원"\n'
            'journal_best_trade: "BTC 롱"\n'
            'journal_next_focus: "리스크 관리"\n'
            "---\n본문\n",
            encoding="utf-8",
        )
        r = wd.parse_post_frontmatter(str(f))
        assert r["journal_strategy"] == "추세추종"
        assert r["journal_next_focus"] == "리스크 관리"

    def test_value_after_first_colon_is_kept(self, tmp_path) -> None:
        """`split(":", 1)` — 값 안의 콜론이 잘리지 않는다."""
        f = tmp_path / "p.md"
        f.write_text('---\ntitle: "속보: 시장 급변"\n---\n본문\n', encoding="utf-8")
        assert wd.parse_post_frontmatter(str(f))["title"] == "속보: 시장 급변"


# ---------------------------------------------------------------------------
# _get_post_link
# ---------------------------------------------------------------------------


class TestGetPostLink:
    def test_permalink_wins(self) -> None:
        post = {"permalink": "/a/b/", "filename": "2026-08-20-slug.md", "categories": "[x]"}
        assert wd._get_post_link(post) == "/a/b/"

    def test_derives_from_filename_and_category(self) -> None:
        post = {"filename": "2026-08-20-daily-digest.md", "categories": "[market-analysis]"}
        assert wd._get_post_link(post) == "/market-analysis/2026/08/20/daily-digest/"

    def test_missing_category_falls_back_to_posts(self) -> None:
        post = {"filename": "2026-08-20-daily-digest.md", "categories": ""}
        assert wd._get_post_link(post) == "/posts/2026/08/20/daily-digest/"

    def test_unparseable_filename_returns_empty(self) -> None:
        assert wd._get_post_link({"filename": "about.md", "categories": "[x]"}) == ""

    def test_no_data_returns_empty(self) -> None:
        assert wd._get_post_link({}) == ""

    def test_whitespace_only_permalink_is_ignored(self) -> None:
        post = {"permalink": "   ", "filename": "2026-08-20-s.md", "categories": "[c]"}
        assert wd._get_post_link(post) == "/c/2026/08/20/s/"


# ---------------------------------------------------------------------------
# collect_weekly_posts
# ---------------------------------------------------------------------------


class TestCollectWeeklyPosts:
    def test_missing_dir_warns_and_returns_empty(self, tmp_path, monkeypatch, caplog) -> None:
        monkeypatch.setattr(wd, "POSTS_DIR", str(tmp_path / "없음"))
        with caplog.at_level("WARNING"):
            assert wd.collect_weekly_posts() == []
        assert any("Posts directory not found" in r.message for r in caplog.records)

    def test_collects_posts_inside_the_window(self, posts_dir) -> None:
        _write_post(posts_dir, days_ago=1, slug="a")
        _write_post(posts_dir, days_ago=6, slug="b")
        names = {p["filename"] for p in wd.collect_weekly_posts(days=7)}
        assert len(names) == 2

    def test_excludes_posts_older_than_the_window(self, posts_dir) -> None:
        _write_post(posts_dir, days_ago=1, slug="recent")
        _write_post(posts_dir, days_ago=30, slug="old")
        names = [p["filename"] for p in wd.collect_weekly_posts(days=7)]
        assert len(names) == 1
        assert "recent" in names[0]

    def test_window_size_is_honoured(self, posts_dir) -> None:
        _write_post(posts_dir, days_ago=10, slug="ten")
        assert wd.collect_weekly_posts(days=7) == []
        assert len(wd.collect_weekly_posts(days=14)) == 1

    def test_non_markdown_and_undated_files_are_skipped(self, posts_dir) -> None:
        (posts_dir / "notes.txt").write_text("x", encoding="utf-8")
        (posts_dir / "about-page.md").write_text("---\n---\n본문\n", encoding="utf-8")
        assert wd.collect_weekly_posts() == []

    def test_filename_and_file_date_are_attached(self, posts_dir) -> None:
        name = _write_post(posts_dir, days_ago=1, slug="a")
        (post,) = wd.collect_weekly_posts()
        assert post["filename"] == name
        assert post["file_date"] == name[:10]


# ---------------------------------------------------------------------------
# _is_generic_sentence / _sentence_score
# ---------------------------------------------------------------------------


class TestSentenceScoring:
    def test_numbers_raise_the_score(self) -> None:
        assert wd._sentence_score("비트코인이 5% 상승하며 70,000달러를 넘어섰습니다") > wd._sentence_score(
            "비트코인이 상승하며 좋은 흐름을 보였습니다"
        )

    def test_dollar_amounts_raise_the_score(self) -> None:
        with_amt = wd._sentence_score("총 시가총액이 $2.49T 규모로 확대되었습니다")
        without = wd._sentence_score("총 시가총액이 크게 확대되었습니다")
        assert with_amt > without

    def test_short_sentences_are_penalised(self) -> None:
        assert wd._sentence_score("짧다") < 0

    def test_score_is_an_integer(self) -> None:
        assert isinstance(wd._sentence_score("비트코인 5% 상승"), int)

    def test_generic_filter_flags_boilerplate(self) -> None:
        """실제 보일러플레이트 문구가 걸러지는지 — 패턴이 좁아지면 red."""
        flagged = [
            s
            for s in ("자세한 내용은 원문을 확인하세요", "본 분석은 투자 조언이 아닙니다")
            if wd._is_generic_sentence(s)
        ]
        assert flagged, "generic 패턴이 아무 보일러플레이트도 잡지 못한다"

    def test_generic_filter_keeps_substantive_text(self) -> None:
        assert wd._is_generic_sentence("비트코인이 5% 상승해 70,000달러를 회복했습니다") is False


# ---------------------------------------------------------------------------
# extract_key_bullets
# ---------------------------------------------------------------------------


class TestExtractKeyBullets:
    def test_empty_body(self) -> None:
        assert wd.extract_key_bullets("") == []

    def test_core_section_wins_over_scoring(self) -> None:
        """전략 1(핵심 섹션)이 성공하면 점수 기반 전략은 돌지 않는다."""
        body = (
            "## 오늘의 핵심\n"
            "- 비트코인이 5% 상승해 70,000달러를 회복했습니다\n"
            "- 이더리움도 3% 오르며 동반 상승했습니다\n"
            "\n"
            "## 기타\n"
            "총 시가총액이 $9.99T 로 폭증하며 사상 최대를 기록했습니다\n"
        )
        bullets = wd.extract_key_bullets(body)
        assert bullets[0].startswith("비트코인이 5% 상승")
        assert not any("9.99T" in b for b in bullets), "핵심 섹션이 있는데 점수 전략이 돌았다"

    def test_core_section_respects_max_bullets(self) -> None:
        body = "## 핵심\n" + "".join(f"- 비트코인이 {i}% 상승하며 신고가를 기록했습니다\n" for i in range(1, 6))
        assert len(wd.extract_key_bullets(body, max_bullets=2)) == 2

    def test_core_section_skips_dash_only_lines(self) -> None:
        """`- -` 는 `- .+` 에 매칭되지만 `lstrip("- ")` 후 빈 문자열이 된다."""
        body = "## 핵심\n- -\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        assert wd.extract_key_bullets(body) == ["비트코인이 5% 급등하며 70,000달러를 돌파했습니다"]

    def test_core_section_drops_generic_bullets(self) -> None:
        """핵심 섹션 안에 있어도 보일러플레이트는 버린다."""
        body = "## 핵심\n- 자동 수집된 데이터입니다\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        bullets = wd.extract_key_bullets(body)
        assert bullets == ["비트코인이 5% 급등하며 70,000달러를 돌파했습니다"]
        assert not any("자동 수집" in b for b in bullets)

    def test_core_section_drops_stat_enumerations(self) -> None:
        """`sanitize_summary_bullet` 이 빈 문자열을 내면 그 불릿은 버려진다.

        통계 나열("20 총이슈 3 테마수 …")은 generic 패턴에는 안 걸리지만 산문이
        아니므로 sanitize 단계에서 제거된다. 두 필터는 서로 다른 것을 잡는다.
        """
        body = "## 핵심\n- 20 총이슈 3 테마수 2 출처수 5 안보이슈\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        assert wd.extract_key_bullets(body) == ["비트코인이 5% 급등하며 70,000달러를 돌파했습니다"]

    def test_scoring_strategy_drops_stat_enumerations(self) -> None:
        """폴백 전략에도 같은 sanitize 게이트가 걸린다 — 길이 15 를 넘어도 버린다."""
        body = "20 총이슈 3 테마수 2 출처수 5 안보이슈\n비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        bullets = wd.extract_key_bullets(body)
        assert bullets == ["비트코인이 5% 급등하며 70,000달러를 돌파했습니다"]

    def test_falls_back_to_scoring_when_no_core_section(self) -> None:
        body = "평범한 도입 문장이 여기에 들어갑니다\n비트코인이 5% 상승해 $70,000 선을 회복하며 반등했습니다\n"
        bullets = wd.extract_key_bullets(body)
        assert bullets, "폴백 전략이 아무것도 뽑지 못했다"
        assert any("70,000" in b or "5%" in b for b in bullets)

    def test_scoring_prefers_numeric_sentences(self) -> None:
        body = (
            "시장 참여자들은 신중한 태도를 유지하고 있는 것으로 보입니다\n"
            "비트코인이 5% 상승해 $70,000 을 회복하며 급등했습니다\n"
        )
        assert "70,000" in wd.extract_key_bullets(body, max_bullets=1)[0]

    def test_headings_tables_images_are_skipped(self) -> None:
        body = (
            "## 제목\n"
            "| 표 | 값 |\n"
            "![이미지](x.png)\n"
            "> 인용문\n"
            "```code```\n"
            "*본 분석은 참고용입니다\n"
            "비트코인이 5% 상승해 $70,000 을 회복했습니다\n"
        )
        bullets = wd.extract_key_bullets(body)
        assert len(bullets) == 1
        assert "70,000" in bullets[0]

    def test_html_tags_are_stripped_without_concatenation(self) -> None:
        """태그를 공백으로 치환한다 — 빈 문자열로 지우면 단어가 붙어버린다."""
        body = "<div>비트코인이</div><div>5% 상승해 $70,000 을 회복했습니다</div>\n"
        joined = " ".join(wd.extract_key_bullets(body))
        assert "비트코인이5%" not in joined

    def test_short_lines_are_dropped(self) -> None:
        assert wd.extract_key_bullets("짧다\n또짧다\n") == []

    def test_near_duplicate_bullets_are_deduped(self) -> None:
        line = "비트코인이 5% 상승해 $70,000 선을 회복하며 강한 반등을 보였습니다"
        body = f"{line}\n{line} (반복)\n"
        assert len(wd.extract_key_bullets(body, max_bullets=3)) == 1

    def test_markdown_links_are_unwrapped(self) -> None:
        body = "[비트코인 5% 상승으로 $70,000 회복](https://example.com/a) 소식입니다\n"
        joined = " ".join(wd.extract_key_bullets(body))
        assert "https://example.com" not in joined
        assert "비트코인" in joined

    def test_bullets_are_truncated(self) -> None:
        body = "- " + ("비트코인이 5% 상승했습니다 " * 30) + "\n"
        for b in wd.extract_key_bullets(body):
            assert len(b) <= 121, len(b)


# ---------------------------------------------------------------------------
# extract_market_data
# ---------------------------------------------------------------------------


def _ma_post(body: str, date: str = "2026-08-20") -> Dict[str, Any]:
    return {"categories": "[market-analysis]", "body": body, "file_date": date}


class TestExtractMarketData:
    def test_no_posts_yields_empty_lists(self) -> None:
        assert wd.extract_market_data([]) == {
            "fear_greed": [],
            "btc_prices": [],
            "total_mcap": [],
            "kr_market": [],
        }

    def test_fear_greed_plain_format(self) -> None:
        data = wd.extract_market_data([_ma_post("공포/탐욕 지수: 27/100 입니다")])
        assert data["fear_greed"] == [{"date": "2026-08-20", "value": 27}]

    def test_fear_greed_stat_grid_fallback(self) -> None:
        body = '<div class="stat-value">35</div><div class="stat-label"> 공포/탐욕 (Fear)</div>'
        assert wd.extract_market_data([_ma_post(body)])["fear_greed"][0]["value"] == 35

    def test_btc_stat_grid_format(self) -> None:
        body = '<div class="stat-value"> $70,391 </div><div class="stat-label"> BTC (-1.1%)</div>'
        (entry,) = wd.extract_market_data([_ma_post(body)])["btc_prices"]
        assert entry["price"] == pytest.approx(70391.0)
        assert entry["change"] == "-1.1%"

    def test_btc_bold_fallback(self) -> None:
        body = "**Bitcoin** 가격은 $68,500 수준입니다"
        (entry,) = wd.extract_market_data([_ma_post(body)])["btc_prices"]
        assert entry["price"] == pytest.approx(68500.0)
        assert entry["change"] == ""

    def test_total_mcap_stat_grid(self) -> None:
        body = '<div class="stat-value"> $2.49T </div><div class="stat-label"> 총 시가총액</div>'
        assert wd.extract_market_data([_ma_post(body)])["total_mcap"][0]["value"] == pytest.approx(2.49)

    def test_total_mcap_table_fallback(self) -> None:
        body = "| 총 시가총액 | $3.11T |"
        assert wd.extract_market_data([_ma_post(body)])["total_mcap"][0]["value"] == pytest.approx(3.11)

    def test_kospi_only_from_stock_news_category(self) -> None:
        body = "KOSPI 2,650.12 (+0.8%) 마감"
        from_stock = wd.extract_market_data([{"categories": "[stock-news]", "body": body, "file_date": "2026-08-20"}])
        assert from_stock["kr_market"] == [{"date": "2026-08-20", "kospi": "2,650.12", "kospi_change": "+0.8%"}]
        assert wd.extract_market_data([_ma_post(body)])["kr_market"] == []

    def test_other_categories_are_ignored(self) -> None:
        body = "공포/탐욕 지수: 27/100"
        assert (
            wd.extract_market_data([{"categories": "[crypto-news]", "body": body, "file_date": "d"}])["fear_greed"]
            == []
        )

    def test_entries_keep_post_order(self) -> None:
        posts = [
            _ma_post("공포/탐욕 지수: 20/100", "2026-08-18"),
            _ma_post("공포/탐욕 지수: 55/100", "2026-08-20"),
        ]
        values = [e["value"] for e in wd.extract_market_data(posts)["fear_greed"]]
        assert values == [20, 55], "마지막 항목을 최신으로 쓰므로 순서가 뒤집히면 description 이 틀린다"

    def test_unparseable_numbers_are_skipped_not_raised(self) -> None:
        """정규식은 통과하지만 float 변환이 실패하는 값에 대해 예외를 내지 않는다."""
        body = '<div class="stat-value"> $0.0.0T </div><div class="stat-label"> 총 시가총액</div>'
        assert wd.extract_market_data([_ma_post(body)])["total_mcap"] == []

    def test_btc_stat_grid_comma_only_amount_is_skipped(self) -> None:
        """`[0-9,]+` 는 `,` 하나에도 매칭된다 — 쉼표를 지우면 빈 문자열이라 float 이 깨진다.

        정규식이 통과했는데 변환이 실패하는 경우이므로, 매칭 자체가 없는 것과는
        다른 경로다(`except ValueError`).
        """
        body = '<div class="stat-value"> $, </div><div class="stat-label"> BTC (-1.1%)</div>'
        assert wd.extract_market_data([_ma_post(body)])["btc_prices"] == []

    def test_btc_bold_fallback_comma_only_amount_is_skipped(self) -> None:
        assert wd.extract_market_data([_ma_post("**Bitcoin** 가격은 $, 입니다")])["btc_prices"] == []

    def test_total_mcap_table_fallback_unparseable_is_skipped(self) -> None:
        """stat-grid 가 아니라 표 폴백 쪽 `except ValueError` 경로."""
        assert wd.extract_market_data([_ma_post("| 총 시가총액 | $0.0.0T |")])["total_mcap"] == []


# ---------------------------------------------------------------------------
# _format_fear_greed_label
# ---------------------------------------------------------------------------


class TestFearGreedLabel:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "극도의 공포"),
            (20, "극도의 공포"),
            (21, "공포"),
            (40, "공포"),
            (41, "중립"),
            (60, "중립"),
            (61, "탐욕"),
            (80, "탐욕"),
            (81, "극도의 탐욕"),
            (100, "극도의 탐욕"),
        ],
    )
    def test_thresholds(self, value: int, expected: str) -> None:
        assert wd._format_fear_greed_label(value) == expected


# ---------------------------------------------------------------------------
# _build_dynamic_description
# ---------------------------------------------------------------------------


class TestBuildDynamicDescription:
    def _empty_market(self) -> Dict[str, list]:
        return {"fear_greed": [], "btc_prices": [], "total_mcap": [], "kr_market": []}

    def test_uses_latest_entries(self) -> None:
        market = self._empty_market()
        market["btc_prices"] = [{"price": 60000.0}, {"price": 70391.0}]
        market["fear_greed"] = [{"value": 80}, {"value": 27}]
        market["kr_market"] = [
            {"kospi": "2,600.00", "kospi_change": "(+0.1%)"},
            {"kospi": "2,650.12", "kospi_change": "(+0.8%)"},
        ]
        desc = wd._build_dynamic_description([{}] * 42, market, {})
        assert "BTC $70,391" in desc
        assert "공포(27)" in desc
        assert "KOSPI 2,650.12(+0.8%)" in desc
        assert "2,600.00" not in desc, "KOSPI 는 마지막(최신) 항목을 써야 한다"
        assert "42건 분석" in desc
        assert "주간 다이제스트" in desc

    def test_pads_with_category_info_when_short(self) -> None:
        """80자 미만이면 카테고리 정보로 채운다 — SEO description 최소 길이."""
        cats = {"market-analysis": [{}] * 5, "crypto-news": [{}] * 3, "stock-news": [{}] * 2}
        desc = wd._build_dynamic_description([{}] * 3, self._empty_market(), cats)
        assert len(desc) >= 40
        assert "건" in desc

    def test_result_is_truncated_to_160(self) -> None:
        cats = {f"cat-{i}": [{}] * (10 - i) for i in range(3)}
        market = self._empty_market()
        market["btc_prices"] = [{"price": 70391.0}]
        desc = wd._build_dynamic_description([{}] * 999, market, cats)
        assert len(desc) <= 160

    def test_post_count_always_present(self) -> None:
        desc = wd._build_dynamic_description([{}] * 7, self._empty_market(), {})
        assert "7건 분석" in desc


# ---------------------------------------------------------------------------
# generate_digest
# ---------------------------------------------------------------------------


class TestGenerateDigest:
    def _post(self, cat: str, *, body: str = "본문", title: str = "제목", **extra: Any) -> Dict[str, Any]:
        base = {
            "categories": f"[{cat}]",
            "body": body,
            "title": title,
            "file_date": "2026-08-20",
            "filename": "2026-08-20-slug.md",
            "permalink": "/x/2026/08/20/slug/",
        }
        base.update(extra)
        return base

    def test_returns_content_and_description(self) -> None:
        content, desc = wd.generate_digest([self._post("market-analysis")])
        assert isinstance(content, str) and isinstance(desc, str)
        assert content and desc

    def test_summary_section_counts_posts_and_categories(self) -> None:
        posts = [self._post("market-analysis"), self._post("crypto-news"), self._post("crypto-news")]
        content, _ = wd.generate_digest(posts)
        assert "## 핵심 요약" in content
        assert '<span class="stat-value">3</span>' in content
        assert '<span class="stat-value">2</span>' in content

    def test_empty_post_list_still_produces_content(self) -> None:
        content, desc = wd.generate_digest([])
        assert "## 핵심 요약" in content
        assert "0건 분석" in desc

    def test_week_range_appears_in_lead(self) -> None:
        content, _ = wd.generate_digest([self._post("market-analysis")])
        assert "이번 주 (" in content
        assert "~" in content.split("\n")[0]

    def test_market_data_flows_into_description(self) -> None:
        body = '<div class="stat-value"> $70,391 </div><div class="stat-label"> BTC (-1.1%)</div>'
        _content, desc = wd.generate_digest([self._post("market-analysis", body=body)])
        assert "BTC $70,391" in desc

    def test_uncategorised_posts_are_grouped(self) -> None:
        content, _ = wd.generate_digest([self._post("")])
        assert "## 핵심 요약" in content


# ---------------------------------------------------------------------------
# generate_digest — 시장 개요 테이블
#
# 이 표는 `extract_market_data` 의 출력에서만 만들어진다. 수집이 조용히 0건이
# 되면 표가 통째로 사라지는데 워크플로우는 그대로 성공한다. 각 행이 실제로
# 나오는지, 그리고 계산(주간 변동률)이 맞는지 붙잡아 둔다.
# ---------------------------------------------------------------------------


def _ma_body(*, btc: str = "", fg: str = "", mcap: str = "") -> str:
    """`market-analysis` 본문에 stat-grid 조각을 조립한다."""
    parts = []
    if fg:
        parts.append(f'<div class="stat-value">{fg}</div><div class="stat-label"> 공포/탐욕 (Fear)</div>')
    if btc:
        parts.append(f'<div class="stat-value"> ${btc} </div><div class="stat-label"> BTC (+1.0%)</div>')
    if mcap:
        parts.append(f'<div class="stat-value"> ${mcap}T </div><div class="stat-label"> 총 시가총액</div>')
    return "".join(parts)


class TestMarketOverviewTable:
    def _ma(self, body: str, date: str) -> Dict[str, Any]:
        return {
            "categories": "[market-analysis]",
            "body": body,
            "title": "시장 분석",
            "file_date": date,
            "filename": f"{date}-market.md",
            "permalink": f"/market-analysis/{date.replace('-', '/')}/market/",
        }

    def test_no_market_data_omits_the_table(self) -> None:
        content, _ = wd.generate_digest([self._ma("특별한 수치가 없는 본문입니다", "2026-08-20")])
        assert "| 지표 | 값 |" not in content

    def test_btc_range_and_weekly_change(self) -> None:
        posts = [
            self._ma(_ma_body(btc="60,000"), "2026-08-18"),
            self._ma(_ma_body(btc="66,000"), "2026-08-20"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "| BTC 가격 범위 | $60,000 ~ $66,000 |" in content
        assert "| BTC 주간 변동 | +10.0% |" in content

    def test_negative_weekly_change_has_no_plus_sign(self) -> None:
        posts = [
            self._ma(_ma_body(btc="70,000"), "2026-08-18"),
            self._ma(_ma_body(btc="63,000"), "2026-08-20"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "| BTC 주간 변동 | -10.0% |" in content

    def test_single_btc_day_omits_weekly_change(self) -> None:
        content, _ = wd.generate_digest([self._ma(_ma_body(btc="70,000"), "2026-08-20")])
        assert "BTC 가격 범위" in content
        assert "BTC 주간 변동" not in content, "하루치로 주간 변동을 계산하면 안 된다"

    def test_fear_greed_row_shows_start_end_and_range(self) -> None:
        posts = [
            self._ma(_ma_body(fg="15"), "2026-08-18"),
            self._ma(_ma_body(fg="55"), "2026-08-19"),
            self._ma(_ma_body(fg="72"), "2026-08-20"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "| 공포/탐욕 지수 | 15 (극도의 공포) -> 72 (탐욕), 범위 15~72 |" in content

    def test_total_mcap_with_change_when_multiple_days(self) -> None:
        posts = [
            self._ma(_ma_body(mcap="2.00"), "2026-08-18"),
            self._ma(_ma_body(mcap="2.50"), "2026-08-20"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "| 총 시가총액 | $2.50T (+25.0%) |" in content

    def test_total_mcap_without_change_when_single_day(self) -> None:
        content, _ = wd.generate_digest([self._ma(_ma_body(mcap="2.49"), "2026-08-20")])
        assert "| 총 시가총액 | $2.49T |" in content

    def test_kospi_row_uses_latest_entry(self) -> None:
        posts = [
            {
                "categories": "[stock-news]",
                "body": "KOSPI 2,600.00 (+0.1%) 마감",
                "title": "증시",
                "file_date": "2026-08-18",
                "filename": "2026-08-18-a.md",
            },
            {
                "categories": "[stock-news]",
                "body": "KOSPI 2,650.12 (+0.8%) 마감",
                "title": "증시",
                "file_date": "2026-08-20",
                "filename": "2026-08-20-b.md",
            },
        ]
        content, _ = wd.generate_digest(posts)
        assert "| KOSPI | 2,650.12 (+0.8%) |" in content
        assert "2,600.00" not in content.split("| KOSPI |")[1].split("\n")[0]

    def test_daily_btc_snapshot_table_needs_two_days(self) -> None:
        one, _ = wd.generate_digest([self._ma(_ma_body(btc="70,000"), "2026-08-20")])
        assert "### 일별 BTC 스냅샷" not in one

        posts = [
            self._ma(_ma_body(btc="60,000"), "2026-08-18"),
            self._ma(_ma_body(btc="66,000"), "2026-08-20"),
        ]
        two, _ = wd.generate_digest(posts)
        assert "### 일별 BTC 스냅샷" in two
        assert "| 2026-08-18 | $60,000 | +1.0% |" in two

    def test_snapshot_shows_dash_when_change_is_missing(self) -> None:
        """`**Bitcoin** $X` 폴백은 변동률이 없다 — 빈칸이 아니라 `-` 로 채운다."""
        posts = [
            self._ma("**Bitcoin** 가격은 $60,000 입니다", "2026-08-18"),
            self._ma("**Bitcoin** 가격은 $66,000 입니다", "2026-08-20"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "| 2026-08-18 | $60,000 | - |" in content


# ---------------------------------------------------------------------------
# generate_digest — 카테고리 섹션
#
# 인사이트 추출·중복 제거·상한(8건)·링크 폴백이 모두 여기 모여 있다. 조용히
# 틀리면 다이제스트가 링크만 나열하거나 같은 문장을 반복한다.
# ---------------------------------------------------------------------------


class TestCategorySections:
    def _post(self, cat: str, *, body: str, title: str, date: str = "2026-08-20") -> Dict[str, Any]:
        return {
            "categories": f"[{cat}]",
            "body": body,
            "title": title,
            "file_date": date,
            "filename": f"{date}-slug.md",
            "permalink": f"/{cat}/2026/08/20/slug/",
        }

    def test_bullets_are_rendered_with_title_and_link(self) -> None:
        body = "## 핵심\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        content, _ = wd.generate_digest([self._post("crypto-news", body=body, title="암호화폐 급등")])
        assert "- 2026-08-20 [암호화폐 급등](/crypto-news/2026/08/20/slug/) -- 비트코인이 5% 급등" in content

    def test_bullet_without_link_falls_back_to_date_only(self) -> None:
        post = self._post(
            "crypto-news", body="## 핵심\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n", title="t"
        )
        post["permalink"] = ""
        post["filename"] = "링크불가.md"
        content, _ = wd.generate_digest([post])
        assert "- 2026-08-20 비트코인이 5% 급등" in content

    def test_post_without_bullets_is_still_linked(self) -> None:
        content, _ = wd.generate_digest([self._post("crypto-news", body="짧다", title="제목만 있는 글")])
        assert "- 2026-08-20 [제목만 있는 글](/crypto-news/2026/08/20/slug/)" in content

    def test_post_with_neither_bullets_nor_link_yields_count_line(self) -> None:
        post = self._post("crypto-news", body="짧다", title="t")
        post["permalink"] = ""
        post["filename"] = "링크불가.md"
        content, _ = wd.generate_digest([post])
        assert "- 1건의 리포트가 수집되었습니다." in content

    def test_identical_bullets_across_posts_are_deduped(self) -> None:
        body = "## 핵심\n- 비트코인이 5% 급등하며 70,000달러를 돌파했습니다\n"
        posts = [
            self._post("crypto-news", body=body, title="첫 글", date="2026-08-20"),
            self._post("crypto-news", body=body, title="둘째 글", date="2026-08-19"),
        ]
        content, _ = wd.generate_digest(posts)
        assert content.count("비트코인이 5% 급등하며 70,000달러를 돌파했습니다") == 1

    def test_bullets_sharing_a_40_char_prefix_are_deduped(self) -> None:
        """중복 판정 키는 **앞 40자**다 — 뒷부분만 다른 문장은 같은 것으로 본다.

        전체 문자열 비교로 바꾸면 이 둘이 모두 실린다. 동일 문장 두 개로만
        테스트하면 그 차이를 못 잡으므로, 접두사만 겹치는 쌍을 쓴다.
        """
        first = "비트코인이 5% 급등하며 70,000달러를 강하게 돌파했고 시장 전반이 강세를 보였습니다"
        second = "비트코인이 5% 급등하며 70,000달러를 강하게 돌파했고 시장 전반이 약세로 돌아섰습니다"
        assert first[:40] == second[:40] and first != second, "테스트 전제가 깨졌다"

        posts = [
            self._post("crypto-news", body=f"## 핵심\n- {first}\n", title="첫 글", date="2026-08-20"),
            self._post("crypto-news", body=f"## 핵심\n- {second}\n", title="둘째 글", date="2026-08-19"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "강세를 보였습니다" in content
        assert "약세로 돌아섰습니다" not in content, "앞 40자가 같은데 둘 다 실렸다 — 중복 제거 키가 무력화됐다"

    def test_duplicate_titles_without_bullets_are_deduped(self) -> None:
        posts = [
            self._post("crypto-news", body="짧다", title="같은 제목", date="2026-08-20"),
            self._post("crypto-news", body="짧다", title="같은 제목", date="2026-08-19"),
        ]
        content, _ = wd.generate_digest(posts)
        assert content.count("[같은 제목]") == 1

    def test_distinct_titles_without_bullets_are_all_listed(self) -> None:
        """제목 기반 중복 제거가 **서로 다른** 글까지 삼키면 안 된다.

        위 테스트만 있으면 "무조건 하나만 남긴다" 는 버그를 통과시킨다.
        """
        posts = [
            self._post("crypto-news", body="짧다", title="첫 번째 제목", date="2026-08-20"),
            self._post("crypto-news", body="짧다", title="두 번째 제목", date="2026-08-19"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "[첫 번째 제목]" in content
        assert "[두 번째 제목]" in content

    def test_insights_are_capped_at_eight_per_category(self) -> None:
        posts = [
            self._post(
                "crypto-news",
                body=f"## 핵심\n- {i}번 코인이 {i}% 급등하며 신고가 {i}0,000달러를 돌파했습니다\n",
                title=f"글 {i}",
                date=f"2026-08-{10 + i:02d}",
            )
            for i in range(1, 12)
        ]
        content, _ = wd.generate_digest(posts)
        section = content.split("## 암호화폐 뉴스")[1].split("\n## ")[0]
        assert len([line for line in section.split("\n") if line.startswith("- 2026-")]) == 8

    def test_cap_can_land_mid_post_and_truncates_that_post(self) -> None:
        """상한(8건)은 포스트 경계가 아니라 **불릿 단위**로 걸린다.

        1불릿짜리 7개 뒤에 3불릿짜리 하나가 오면, 마지막 포스트는 첫 불릿만
        실리고 나머지 둘은 잘린다. 포스트 단위로만 끊으면 9건이 실린다.
        """
        posts = [
            self._post(
                "crypto-news",
                body=f"## 핵심\n- {i}번 코인이 {i}% 급등하며 신고가 {i}0,000달러를 돌파했습니다\n",
                title=f"글 {i}",
                date=f"2026-08-{13 + i:02d}",
            )
            for i in range(1, 8)
        ]
        posts.append(
            self._post(
                "crypto-news",
                body=(
                    "## 핵심\n"
                    "- 알파코인이 11% 급등하며 신고가 11,000달러를 돌파했습니다\n"
                    "- 베타코인이 22% 급락하며 지지선 22,000달러가 깨졌습니다\n"
                    "- 감마코인이 33% 반등하며 저항선 33,000달러를 넘었습니다\n"
                ),
                title="마지막 글",
                date="2026-08-10",
            )
        )
        content, _ = wd.generate_digest(posts)
        section = content.split("## 암호화폐 뉴스")[1].split("\n## ")[0]
        assert len([line for line in section.split("\n") if line.startswith("- 2026-")]) == 8
        assert "알파코인" in section, "마지막 포스트의 첫 불릿은 상한 안에 들어간다"
        assert "베타코인" not in section, "상한을 넘은 불릿이 실렸다"
        assert "감마코인" not in section

    def test_journal_categories_use_snapshot_extractor(self, monkeypatch) -> None:
        """저널 카테고리는 `extract_journal_snapshot` 을 쓴다 — 일반 불릿 추출이 아니다."""
        called: Dict[str, Any] = {}

        def _fake(post):
            called["post"] = post
            return ["저널 스냅샷 한 줄"]

        monkeypatch.setattr(wd, "extract_journal_snapshot", _fake)
        content, _ = wd.generate_digest(
            [self._post("crypto-trading-journal", body="## 핵심\n- 무시되어야 합니다\n", title="저널")]
        )
        assert called, "저널 카테고리인데 extract_journal_snapshot 이 호출되지 않았다"
        assert "저널 스냅샷 한 줄" in content

    def test_unordered_categories_are_listed_compactly(self) -> None:
        """`cat_order` 밖 카테고리는 **최대 5건만** 나열하고 나머지는 건수로 요약한다.

        "외 N건 추가" 줄만 확인하면 부족하다 — 그 줄은 `len(cat_posts) > 5` 라는
        별도 조건에서 나오므로, 나열 자체가 5건을 넘어도 그대로 붙는다. 실제
        나열 줄 수를 세야 상한이 지켜지는지 알 수 있다.
        """
        posts = [
            self._post("defi-news", body="짧다", title=f"디파이 {i}", date=f"2026-08-{10 + i:02d}") for i in range(1, 8)
        ]
        content, _ = wd.generate_digest(posts)
        assert "## defi-news (7건)" in content

        section = content.split("## defi-news (7건)")[1].split("\n## ")[0]
        listed = [line for line in section.split("\n") if line.startswith("- 2026-")]
        assert len(listed) == 5, f"5건까지만 나열해야 하는데 {len(listed)}건이 실렸다"
        assert "- 외 2건 추가" in section
        assert "디파이 7" in section and "디파이 1" not in section, "최신순 5건이어야 한다"

    def test_unordered_category_without_link_shows_plain_title(self) -> None:
        post = self._post("defi-news", body="짧다", title="링크 없는 글")
        post["permalink"] = ""
        post["filename"] = "링크불가.md"
        content, _ = wd.generate_digest([post])
        assert "- 2026-08-20 링크 없는 글" in content

    def test_weekly_statistics_section_reports_totals(self) -> None:
        posts = [
            self._post("crypto-news", body="짧다", title="a"),
            self._post("stock-news", body="짧다", title="b"),
        ]
        content, _ = wd.generate_digest(posts)
        assert "## 주간 통계" in content
        assert "- 총 포스트 수: **2건**" in content
        assert "- 카테고리: **2개**" in content


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture
    def fake_generator(self, monkeypatch, tmp_path):
        """`PostGenerator` 를 대역으로 바꿔 실제 `_posts/` 쓰기를 막는다."""
        captured: Dict[str, Any] = {}
        written = tmp_path / "fake-digest.md"

        class _Fake:
            def __init__(self, category: str) -> None:
                captured["category"] = category

            def create_post(self, **kwargs):
                captured.update(kwargs)
                return str(written)

        monkeypatch.setattr(wd, "PostGenerator", _Fake)
        return captured

    def test_no_posts_skips_generation(self, posts_dir, fake_generator, caplog) -> None:
        with caplog.at_level("INFO"):
            wd.main()
        assert "title" not in fake_generator, "포스트가 없는데 생성을 시도했다"
        assert any("No posts found" in r.message for r in caplog.records)

    def test_creates_digest_with_expected_metadata(self, posts_dir, fake_generator, caplog) -> None:
        _write_post(posts_dir, days_ago=1, slug="daily-crypto-news-digest", front="categories: [crypto-news]\n")
        with caplog.at_level("INFO"):
            wd.main()

        assert fake_generator["category"] == "market-analysis"
        assert fake_generator["title"].startswith("주간 투자 다이제스트 - ")
        assert fake_generator["tags"] == ["weekly-digest", "summary", "market-analysis"]
        assert fake_generator["source"] == "auto-generated"
        assert fake_generator["lang"] == "ko"
        assert fake_generator["slug"].startswith("weekly-investment-digest-")
        assert "description" in fake_generator["extra_frontmatter"]
        assert any("Created weekly digest" in r.message for r in caplog.records)

    def test_skip_path_is_logged_when_create_post_returns_falsy(self, posts_dir, monkeypatch, caplog) -> None:
        class _Fake:
            def __init__(self, category: str) -> None:
                pass

            def create_post(self, **_kwargs):
                return ""

        monkeypatch.setattr(wd, "PostGenerator", _Fake)
        _write_post(posts_dir, days_ago=1, slug="a")
        with caplog.at_level("INFO"):
            wd.main()
        assert any("already exists or skipped" in r.message for r in caplog.records)

    def test_slug_and_title_share_the_same_date(self, posts_dir, fake_generator) -> None:
        _write_post(posts_dir, days_ago=1, slug="a")
        wd.main()
        date = fake_generator["date"].strftime("%Y-%m-%d")
        assert fake_generator["slug"] == f"weekly-investment-digest-{date}"
