"""`scripts/backfill_post_summaries.py` 의 합성·I/O 경로 테스트.

`tests/test_backfill_post_summaries.py` 는 순수 유틸(파싱·정규화)을 덮는다. 이 파일은
그 위에 쌓인 **조립 함수와 디스크를 만지는 경로**를 덮는다:

- `summarize_from_title` 의 주제·카테고리 분기 (제목 하나가 어느 요약 틀로 가는가)
- `extract_links` 의 look-ahead 규칙 (설명·출처를 어디까지 훑는가)
- `build_summary` / `build_content_analysis` / `build_social_summary` 조립
- `insert_*` / `remove_existing_*` 삽입 위치 규칙
- `reorder_worldmonitor_table` 정렬 + 게이트
- `process_post` / `main` 의 파일 읽기·쓰기

## 격리

이 모듈은 임포트 시점에 `REPO_ROOT` / `POSTS_DIR` 을 `__file__` 로부터 계산하고,
`remove_missing_local_images` · `list_zero_byte_images` · `main` 이 그 경로를 읽거나
쓴다. 저장소 트리를 만지면 hermetic 가드가 red 가 되므로:

- 프로덕션 상수를 **임포트하지 않는다**. 테스트가 쓰는 루트는 `monkeypatch.setattr`
  로 tmp 를 주입한 값이다.
- 파일을 쓰는 경로(`process_post`, `main --zero-image-report`)는 전부 `tmp_path`
  안에서만 돌린다.

## 덮지 않은 2줄 (다음 사람이 쫓지 않도록)

`scripts/backfill_post_summaries.py` 는 이 파일과 짝 파일을 합쳐 99% 다. 남은 2줄은
테스트가 부족한 게 아니라 **도달할 수 없다**:

| 줄 | 내용 | 근거 |
|---|---|---|
| 146 | `normalize_summary` 의 `if not sentence: return ""` | 139번 줄에서 `text` 가 비어있지 않음이 보장되고, 분할 패턴이 전부 lookbehind 라 첫 조각은 위치 0 에서 끊기지 않는다. 4자 전수 탐색(`. ! ? 공백 다 니 가 A`)에서 첫 조각이 빈 입력 0건 |
| 1231 | `main()` (`__main__` 가드 본문) | 임포트로는 실행되지 않는 엔트리포인트 |

이전에 세 번째 항목이던 `normalized.lstrip("/")`(도달 불가)과 그 위의 동일-본문
`if/else` 는 2026-08-27 에 제거됐다. 남은 `lstrip("./")` 은 장식이 아니라
**절대경로 방어**다 — `TestLocalImagePathStaysInsideRepo` 가 그 역할을 고정한다.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.backfill_post_summaries as bps  # noqa: E402

# ---------------------------------------------------------------------------
# summarize_from_title — 주제(subject) 추출
# ---------------------------------------------------------------------------


class TestSummarizeFromTitleSubject:
    """주제 키워드가 한국어 주제어로 매핑되는지.

    영문 제목이고 가격/카테고리 키워드가 없으면 `f"{subject} — {제목}"` 틀로 떨어진다
    (`if subject:` 폴백). 그래서 이 틀의 접두사가 주제 매핑의 **관측 지점**이다.
    """

    @pytest.mark.parametrize(
        ("title", "expected_subject"),
        [
            ("BTC market analysis", "비트코인"),
            ("Bitcoin network report", "비트코인"),
            ("ETH staking report", "이더리움"),
            ("Ethereum roadmap report", "이더리움"),
            ("XRP token report", "XRP"),
            ("Ripple case report", "XRP"),
            ("Solana ecosystem report", "솔라나"),
            ("Nasdaq index report", "나스닥"),
            ("S&P index report", "S&P 500"),
            ("Dow index report", "다우존스"),
            ("KOSPI index report", "코스피"),
            ("KOSDAQ index report", "코스닥"),
            ("FOMC meeting report", "미 연준"),
            ("SEC filing report", "규제 당국"),
            ("ETF fund report", "ETF"),
            ("Binance platform report", "거래소"),
            ("DXY index report", "환율"),
            ("Crypto market report", "암호화폐"),
            ("CPI data report", "거시 지표"),
            ("Trump statement report", "트럼프"),
            ("Gold market report", "금"),
            ("Oil market report", "원유"),
        ],
    )
    def test_subject_prefix(self, title: str, expected_subject: str) -> None:
        result = bps.summarize_from_title(title)
        assert result.startswith(f"{expected_subject} — "), (
            f"{title!r} → {result!r}: 주제 접두사가 {expected_subject!r} 가 아니다"
        )

    def test_sol_uses_word_boundary_not_substring(self) -> None:
        """`\\bsol\\b` 분기 — 'sol' 이 단어로 있을 때만 솔라나다."""
        assert bps.summarize_from_title("SOL token report").startswith("솔라나 — ")

    def test_subject_precedence_is_first_match_wins(self) -> None:
        """if/elif 사슬이므로 앞 분기가 이긴다 — 우선순위가 조용히 바뀌면 잡힌다."""
        result = bps.summarize_from_title("Bitcoin and Ethereum report")
        assert result.startswith("비트코인 — "), result


# ---------------------------------------------------------------------------
# summarize_from_title — 가격 방향
# ---------------------------------------------------------------------------


class TestSummarizeFromTitlePriceDirection:
    def test_up_with_subject(self) -> None:
        assert bps.summarize_from_title("Bitcoin rises to new high").startswith("비트코인 상승 — ")

    def test_down_with_subject(self) -> None:
        assert bps.summarize_from_title("Bitcoin falls below support").startswith("비트코인 하락 — ")

    def test_up_without_subject(self) -> None:
        assert bps.summarize_from_title("Stocks rally after data").startswith("시장 상승 — ")

    def test_down_without_subject(self) -> None:
        assert bps.summarize_from_title("Stocks tumble after data").startswith("시장 하락 — ")

    def test_bare_up_matches_on_word_boundary(self) -> None:
        assert bps.summarize_from_title("Bitcoin up 5% today").startswith("비트코인 상승 — ")

    def test_bare_down_matches_on_word_boundary(self) -> None:
        assert bps.summarize_from_title("Bitcoin down 5% today").startswith("비트코인 하락 — ")

    @pytest.mark.parametrize("title", ["Bitcoin pump incoming", "Bitcoin setup forming"])
    def test_up_substring_is_not_a_false_positive(self, title: str) -> None:
        """'pump' / 'setup' 안의 'up' 은 상승이 아니다 — 경계 매칭이 사라지면 red."""
        result = bps.summarize_from_title(title)
        assert "상승" not in result, f"{title!r} → {result!r}: 부분문자열 'up' 을 상승으로 오판"

    def test_down_substring_is_not_a_false_positive(self) -> None:
        result = bps.summarize_from_title("Bitcoin countdown begins")
        assert "하락" not in result, result


# ---------------------------------------------------------------------------
# summarize_from_title — 카테고리 분기
# ---------------------------------------------------------------------------


class TestSummarizeFromTitleCategory:
    @pytest.mark.parametrize(
        ("title", "expected_prefix"),
        [
            ("New tariff measures announced by officials", "무역·관세 — "),
            ("Investor panic spreads across markets", "시장 심리 — "),
            ("Protocol exploit drains user funds", "보안 이슈 — "),
            ("Regulator lawsuit targets the firm", "법적 분쟁 — "),
            ("New listing goes live on the venue", "상장·상폐 — "),
            ("Whale wallet transfer spotted", "온체인 이동 — "),
        ],
    )
    def test_category_prefix(self, title: str, expected_prefix: str) -> None:
        result = bps.summarize_from_title(title)
        assert result.startswith(expected_prefix), f"{title!r} → {result!r}"

    def test_announcement_without_subject_uses_placeholder(self) -> None:
        result = bps.summarize_from_title("Company will launch a new service")
        assert result.startswith("신규 발표 — "), result

    def test_announcement_with_subject_uses_subject(self) -> None:
        result = bps.summarize_from_title("Nasdaq will launch a new product")
        assert result.startswith("나스닥 발표 — "), result

    def test_trade_without_subject_uses_placeholder(self) -> None:
        result = bps.summarize_from_title("Firm will acquire a large stake")
        assert result.startswith("기관 매수·매도 — "), result

    def test_regulation_prefix(self) -> None:
        result = bps.summarize_from_title("New regulatory framework proposed")
        assert result.startswith("규제·정책 — "), result

    def test_default_falls_back_to_shortened_title(self) -> None:
        """주제도 카테고리도 없으면 제목 그대로(축약)."""
        result = bps.summarize_from_title("Quiet trading session continues")
        assert result.startswith("Quiet trading session"), result
        assert " — " not in result, f"틀이 붙었다: {result!r}"


# ---------------------------------------------------------------------------
# summarize_from_title — 한국어 조기 반환 & 연결 제목 분리
# ---------------------------------------------------------------------------


class TestSummarizeFromTitleKorean:
    def test_long_korean_title_returned_directly(self) -> None:
        """한글이 있고 15자를 넘으면 틀을 씌우지 않고 제목을 그대로 쓴다."""
        title = "비트코인 현물 ETF 자금 유입이 사상 최대치를 기록했다"
        result = bps.summarize_from_title(title)
        assert result.startswith("비트코인 현물 ETF"), result
        assert not result.startswith("비트코인 — "), f"조기 반환이 사라졌다: {result!r}"

    def test_short_korean_title_still_gets_template(self) -> None:
        """15자 이하 한글 제목은 조기 반환을 타지 않아 틀이 붙는다."""
        result = bps.summarize_from_title("비트코인 급등")
        assert result.startswith("비트코인 상승 — "), result

    def test_concatenated_title_is_split_at_case_boundary(self) -> None:
        """'New ListingCheck out...' 처럼 붙은 제목은 소문자→대문자 경계에서 자른다."""
        result = bps.summarize_from_title("New ListingCheck out the latest updates")
        assert "Check out" not in result, f"연결 제목이 분리되지 않았다: {result!r}"


# ---------------------------------------------------------------------------
# _shorten_title_for_summary
# ---------------------------------------------------------------------------


class TestShortenTitleForSummaryTrailingWords:
    def test_short_title_is_untouched(self) -> None:
        assert bps._shorten_title_for_summary("Short title", 80) == "Short title"

    def test_long_title_is_ellipsized(self) -> None:
        title = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda"
        result = bps._shorten_title_for_summary(title, 30)
        assert result.endswith("...")
        assert len(result) <= 34, result

    def test_trailing_stopwords_are_dropped(self) -> None:
        """축약 끝이 관사·전치사로 끝나면 의미가 없으므로 떨어뜨린다."""
        title = "Alpha Beta Gamma Delta Epsilon of the"
        result = bps._shorten_title_for_summary(title, 34)
        assert not result.rstrip(".").endswith(("of", "the")), result

    def test_never_pops_below_three_words(self) -> None:
        """while 조건의 `len(words) > 3` — 전부 stopword 여도 3단어는 남는다.

        하한이 없으면 stopword 만으로 된 축약이 빈 문자열("...")이 되어, 호출부
        (`build_url_summary`)가 요약 없는 항목을 만들어낸다.
        """
        title = "the of the of the of the of"
        result = bps._shorten_title_for_summary(title, 20)
        assert len(result.rstrip(".").split()) == 3, result


# ---------------------------------------------------------------------------
# extract_links — look-ahead 규칙
# ---------------------------------------------------------------------------


class TestExtractLinksLookahead:
    """링크 다음 최대 4줄을 훑어 설명·출처를 붙인다. 그 규칙이 이 클래스의 대상이다."""

    def test_description_taken_from_next_line(self) -> None:
        lines = ["- [제목](https://example.com/a)", "  본문 설명 문장입니다."]
        assert bps.extract_links(lines) == [("제목", "https://example.com/a", "본문 설명 문장입니다.", "")]

    def test_source_tag_is_captured_separately(self) -> None:
        lines = [
            "- [제목](https://example.com/a)",
            '<span class="source-tag">Reuters</span>',
            "설명 문장입니다.",
        ]
        title, url, desc, source = bps.extract_links(lines)[0]
        assert source == "Reuters"
        assert desc == "설명 문장입니다.", desc

    def test_heading_stops_the_lookahead(self) -> None:
        lines = ["- [제목](https://example.com/a)", "## 다음 섹션", "섹션 본문"]
        assert bps.extract_links(lines)[0][2] == "", "heading 을 넘어 설명을 가져왔다"

    def test_next_link_stops_the_lookahead(self) -> None:
        lines = [
            "- [첫째](https://example.com/a)",
            "- [둘째](https://example.com/b)",
        ]
        results = bps.extract_links(lines)
        assert [r[0] for r in results] == ["첫째", "둘째"]
        assert results[0][2] == "", "다음 링크 줄을 설명으로 삼았다"

    def test_image_line_is_skipped_not_used_as_description(self) -> None:
        lines = [
            "- [제목](https://example.com/a)",
            "![그림](/assets/x.png)",
            "실제 설명입니다.",
        ]
        assert bps.extract_links(lines)[0][2] == "실제 설명입니다."

    def test_html_tag_line_is_skipped(self) -> None:
        lines = ["- [제목](https://example.com/a)", "<div>", "실제 설명입니다."]
        assert bps.extract_links(lines)[0][2] == "실제 설명입니다."

    def test_blank_line_before_description_is_skipped(self) -> None:
        lines = ["- [제목](https://example.com/a)", "", "설명입니다."]
        assert bps.extract_links(lines)[0][2] == "설명입니다."

    def test_blank_line_after_description_stops_lookahead(self) -> None:
        lines = ["- [제목](https://example.com/a)", "첫 설명입니다.", "", "무시될 문장."]
        assert bps.extract_links(lines)[0][2] == "첫 설명입니다."

    def test_lookahead_window_is_bounded(self) -> None:
        """창은 `range(1, 5)` = 링크 다음 4줄. 5번째 줄은 보지 않는다."""
        within = ["- [제목](https://example.com/a)", "<a>", "<b>", "<c>", "네 번째 줄."]
        assert bps.extract_links(within)[0][2] == "네 번째 줄.", "창 안쪽을 놓쳤다"

        beyond = ["- [제목](https://example.com/a)", "<a>", "<b>", "<c>", "<d>", "다섯 번째 줄."]
        assert bps.extract_links(beyond)[0][2] == "", "창을 넘어선 줄을 설명으로 가져왔다"

    def test_lookahead_stops_at_end_of_document(self) -> None:
        assert bps.extract_links(["- [제목](https://example.com/a)"])[0][2] == ""

    def test_html_anchor_form_is_supported(self) -> None:
        lines = ['<a href="https://example.com/a" target="_blank">HTML 제목</a>']
        assert bps.extract_links(lines)[0][:2] == ("HTML 제목", "https://example.com/a")

    def test_html_entities_are_unescaped(self) -> None:
        lines = ["- [A &amp; B](https://example.com/a?x=1&amp;y=2)"]
        title, url, _, _ = bps.extract_links(lines)[0]
        assert title == "A & B"
        assert url == "https://example.com/a?x=1&y=2"

    def test_duplicate_urls_are_deduped_keeping_first(self) -> None:
        lines = [
            "- [첫 제목](https://example.com/same)",
            "- [둘째 제목](https://example.com/same)",
        ]
        results = bps.extract_links(lines)
        assert len(results) == 1
        assert results[0][0] == "첫 제목"

    def test_lines_without_links_are_skipped(self) -> None:
        assert bps.extract_links(["일반 문장", "## 제목", ""]) == []

    def test_multiple_links_on_one_line(self) -> None:
        lines = ["[A](https://example.com/a) 그리고 [B](https://example.com/b)"]
        assert [r[0] for r in bps.extract_links(lines)] == ["A", "B"]


# ---------------------------------------------------------------------------
# build_url_summary
# ---------------------------------------------------------------------------


class TestBuildUrlSummary:
    def test_uses_description_when_meaningful(self) -> None:
        lines = [
            "- [비트코인 ETF 소식](https://example.com/a)",
            "기관 자금이 사상 최대 규모로 유입되었다고 전해진다.",
        ]
        result = bps.build_url_summary(lines)
        assert len(result) == 1
        assert "기관 자금이" in result[0]
        assert result[0].startswith("- [비트코인 ETF 소식](https://example.com/a) — ")

    def test_description_equal_to_title_is_discarded(self) -> None:
        """설명이 제목과 같으면 정보가 없다 — 제목 기반 요약으로 대체한다."""
        lines = [
            "- [Bitcoin rises to new high](https://example.com/a)",
            "Bitcoin rises to new high",
        ]
        result = bps.build_url_summary(lines)
        assert "비트코인 상승" in result[0], result

    def test_noise_description_is_discarded(self) -> None:
        lines = ["- [Bitcoin rises to new high](https://example.com/a)", "*총 25건 수집*"]
        result = bps.build_url_summary(lines)
        assert "25건" not in result[0], result

    def test_non_korean_summary_is_replaced_by_title_summary(self) -> None:
        """요약에 한글이 하나도 없으면 제목 기반 요약으로 다시 만든다."""
        lines = [
            "- [Bitcoin rises to new high](https://example.com/a)",
            "Institutional inflows hit a record high this week.",
        ]
        result = bps.build_url_summary(lines)
        assert "비트코인 상승" in result[0], result

    def test_output_line_format(self) -> None:
        lines = ["- [Gold market report](https://example.com/g)"]
        (line,) = bps.build_url_summary(lines)
        assert line.startswith("- [Gold market report](https://example.com/g) — 금 — ")

    def test_empty_input(self) -> None:
        assert bps.build_url_summary([]) == []


# ---------------------------------------------------------------------------
# 섹션 추출
# ---------------------------------------------------------------------------


class TestExtractSectionBullets:
    def test_missing_section(self) -> None:
        assert bps.extract_section_bullets(["## 다른 섹션"], "핵심 요약") == []

    def test_collects_bullets_until_limit(self) -> None:
        lines = [
            "## 핵심 요약",
            "- 첫째 항목",
            "* 둘째 항목",
            "- 셋째 항목",
            "- 넷째 항목",
        ]
        assert bps.extract_section_bullets(lines, "핵심 요약", limit=3) == [
            "첫째 항목",
            "둘째 항목",
            "셋째 항목",
        ]

    def test_stops_at_next_section(self) -> None:
        lines = ["## 핵심 요약", "- 안쪽", "## 다음", "- 바깥쪽"]
        assert bps.extract_section_bullets(lines, "핵심 요약") == ["안쪽"]

    def test_noise_bullets_are_dropped(self) -> None:
        lines = ["## 핵심 요약", "- *총 25건 수집*", "- 실제 항목"]
        assert bps.extract_section_bullets(lines, "핵심 요약") == ["실제 항목"]

    def test_markdown_is_cleaned(self) -> None:
        lines = ["## 핵심 요약", "- **강조** 항목과 [링크](https://example.com)"]
        assert bps.extract_section_bullets(lines, "핵심 요약") == ["강조 항목과 링크"]


class TestExtractSectionSentences:
    def test_missing_section(self) -> None:
        assert bps.extract_section_sentences(["## 다른"], "시장 개요") == []

    def test_collects_paragraph_lines(self) -> None:
        lines = ["## 시장 개요", "첫 문장입니다.", "둘째 문장입니다.", "셋째 문장입니다."]
        assert bps.extract_section_sentences(lines, "시장 개요", limit=2) == [
            "첫 문장입니다.",
            "둘째 문장입니다.",
        ]

    def test_skips_bullets_tables_and_markup(self) -> None:
        lines = [
            "## 시장 개요",
            "- 불릿은 제외",
            "| 표 | 제외 |",
            "![이미지](x.png)",
            "<div>태그</div>",
            "> 인용",
            "본문 문장입니다.",
        ]
        assert bps.extract_section_sentences(lines, "시장 개요") == ["본문 문장입니다."]

    def test_leading_blank_lines_are_skipped(self) -> None:
        lines = ["## 시장 개요", "", "", "본문 문장입니다."]
        assert bps.extract_section_sentences(lines, "시장 개요") == ["본문 문장입니다."]

    def test_blank_line_after_content_stops_collection(self) -> None:
        lines = ["## 시장 개요", "첫 문장입니다.", "", "둘째 단락입니다."]
        assert bps.extract_section_sentences(lines, "시장 개요", limit=2) == ["첫 문장입니다."]

    def test_long_sentence_is_truncated(self) -> None:
        long_text = "가" * 300
        result = bps.extract_section_sentences(["## 시장 개요", long_text], "시장 개요")
        assert len(result[0]) <= 160, len(result[0])


class TestExtractThemeNames:
    def test_reads_theme_snapshot_table(self) -> None:
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 지정학/안보 | 5 |",
            "| 에너지 | 3 |",
        ]
        assert bps.extract_theme_names(lines) == ["지정학/안보", "에너지"]

    def test_table_limit_is_three(self) -> None:
        names = ["지정학/안보", "에너지", "금융시장", "정책/법률", "사회/기타"]
        lines = ["## 테마 스냅샷", "| 테마 | 건수 |", "| --- | --- |"] + [f"| {n} | 1 |" for n in names]
        assert bps.extract_theme_names(lines) == names[:3]

    def test_rows_starting_with_theme_are_kept(self) -> None:
        """'테마'로 시작하는 실제 행이 헤더로 오인되지 않는다.

        예전 판별(`"| 테마" in line`)은 이 행을 버렸다. 이제 첫 파이프 줄만 헤더로
        보고 구분선은 셀 구조로 가려낸다.
        """
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 테마파크 관련주 | 3 |",
            "| 에너지 | 2 |",
        ]
        assert bps.extract_theme_names(lines) == ["테마파크 관련주", "에너지"]

    @pytest.mark.parametrize("sep", ["| --- | --- |", "| :---: | ---: |", "|---|---|"])
    def test_separator_variants_are_skipped(self, sep: str) -> None:
        """정렬 표기가 붙은 구분선도 셀이 `-`/`:` 뿐이므로 걸러진다."""
        lines = ["## 테마 스냅샷", "| 테마 | 건수 |", sep, "| 에너지 | 2 |"]
        assert bps.extract_theme_names(lines) == ["에너지"]

    def test_row_whose_cell_looks_like_a_dash_is_not_mistaken_for_separator(self) -> None:
        """일부 셀만 `-` 인 행은 구분선이 아니다 — 전 셀이 `-`/`:` 여야 건너뛴다."""
        lines = ["## 테마 스냅샷", "| 테마 | 건수 |", "| --- | --- |", "| 에너지 | - |"]
        assert bps.extract_theme_names(lines) == ["에너지"]

    def test_duplicate_themes_are_deduped(self) -> None:
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 에너지 | 3 |",
            "| 에너지 | 2 |",
            "| 금융시장 | 1 |",
        ]
        assert bps.extract_theme_names(lines) == ["에너지", "금융시장"]

    def test_non_table_lines_in_section_are_ignored(self) -> None:
        lines = ["## 테마 스냅샷", "설명 문장", "| 테마 | 건수 |", "| --- | --- |", "| 에너지 | 3 |"]
        assert bps.extract_theme_names(lines) == ["에너지"]

    def test_falls_back_to_theme_label_markup(self) -> None:
        lines = ['<span class="theme-label">규제</span>', '<span class="theme-label">거래소</span>']
        assert bps.extract_theme_names(lines) == ["규제", "거래소"]

    def test_theme_label_limit_is_three(self) -> None:
        lines = [f'<span class="theme-label">라벨{i}</span>' for i in range(1, 6)]
        assert bps.extract_theme_names(lines) == ["라벨1", "라벨2", "라벨3"]

    def test_no_themes(self) -> None:
        assert bps.extract_theme_names(["일반 문장"]) == []


# ---------------------------------------------------------------------------
# build_content_analysis
# ---------------------------------------------------------------------------


class TestBuildContentAnalysis:
    def test_total_and_themes(self) -> None:
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 에너지 | 3 |",
            "| 금융시장 | 2 |",
        ]
        body = "총 42건 수집"
        (first, *_rest) = bps.build_content_analysis(lines, body)
        assert "총 42건" in first
        assert "에너지, 금융시장" in first

    def test_total_without_themes(self) -> None:
        (first, *_rest) = bps.build_content_analysis([], "총 42건 수집")
        assert first == "총 42건의 뉴스를 수집하여 주요 이슈를 정리했습니다."

    def test_urgent_count_line(self) -> None:
        body = "긴급 알림\n<ul><li>A</li><li>B</li></ul>"
        result = bps.build_content_analysis([], body)
        assert any("긴급 이슈 2건" in line for line in result), result

    def test_section_composition_line(self) -> None:
        lines = ["## 핵심 요약", "내용", "## 시장 개요", "내용"]
        result = bps.build_content_analysis(lines, "")
        assert any("2개 섹션" in line for line in result), result

    def test_link_density_line(self) -> None:
        lines = [f"- [제목{i}](https://example.com/{i})" for i in range(6)]
        result = bps.build_content_analysis(lines, "")
        assert any("6개의 출처 링크" in line for line in result), result

    def test_link_density_needs_more_than_five(self) -> None:
        lines = [f"- [제목{i}](https://example.com/{i})" for i in range(5)]
        result = bps.build_content_analysis(lines, "")
        assert not any("출처 링크" in line for line in result), result

    def test_fallback_when_nothing_found(self) -> None:
        assert bps.build_content_analysis([], "") == ["핵심 이슈를 중심으로 요약과 링크를 정리했습니다."]

    def test_result_is_capped_at_three(self) -> None:
        lines = ["## 핵심 요약", "내용", "## 시장 개요", "내용"] + [
            f"- [제목{i}](https://example.com/{i})" for i in range(10)
        ]
        body = "총 42건 수집\n긴급 알림\n<ul><li>A</li></ul>"
        assert len(bps.build_content_analysis(lines, body)) == 3


# ---------------------------------------------------------------------------
# extract_intro_bullets
# ---------------------------------------------------------------------------


class TestExtractIntroBullets:
    def test_collects_first_two_paragraphs(self) -> None:
        lines = ["첫 단락 문장입니다.", "", "둘째 단락 문장입니다.", "", "셋째 단락 문장입니다."]
        assert bps.extract_intro_bullets(lines) == ["첫 단락 문장입니다.", "둘째 단락 문장입니다."]

    def test_joins_consecutive_lines_into_one_paragraph(self) -> None:
        lines = ["앞 줄", "뒷 줄"]
        assert bps.extract_intro_bullets(lines) == ["앞 줄 뒷 줄"]

    def test_skips_markup_and_separators(self) -> None:
        lines = ["## 제목", "| 표 |", "![이미지](x.png)", "<div>", "> 인용", "---", "본문 문장입니다."]
        assert bps.extract_intro_bullets(lines) == ["본문 문장입니다."]

    def test_limit_is_respected(self) -> None:
        lines = ["첫 단락입니다.", "", "둘째 단락입니다."]
        assert bps.extract_intro_bullets(lines, limit=1) == ["첫 단락입니다."]

    def test_noise_paragraph_is_dropped(self) -> None:
        assert bps.extract_intro_bullets(["*총 25건 수집*"]) == []

    def test_empty_input(self) -> None:
        assert bps.extract_intro_bullets([]) == []


# ---------------------------------------------------------------------------
# 소셜 미디어 경로
# ---------------------------------------------------------------------------


class TestSocialHelpers:
    def test_extract_social_counts(self) -> None:
        body = "총 30건 · 텔레그램 12건 · 소셜 미디어 10건 · 정치·경제 8건"
        assert bps._extract_social_counts(body) == {
            "total": "30",
            "telegram": "12",
            "social": "10",
            "political": "8",
        }

    def test_extract_social_counts_partial(self) -> None:
        assert bps._extract_social_counts("총 30건") == {"total": "30"}

    def test_extract_social_themes(self) -> None:
        body = "<strong>규제</strong> (5건) <strong>거래소</strong> (3건)"
        assert bps._extract_social_themes(body) == ["규제", "거래소"]

    def test_extract_social_themes_dedupes_and_limits(self) -> None:
        body = "<strong>규제</strong> (5건) <strong>규제</strong> (2건) " + " ".join(
            f"<strong>테마{i}</strong> (1건)" for i in range(5)
        )
        result = bps._extract_social_themes(body, limit=3)
        assert result[0] == "규제"
        assert len(result) == 3
        assert len(set(result)) == 3

    def test_urgent_count_zero_when_absent(self) -> None:
        assert bps._extract_urgent_count("평범한 본문") == 0

    def test_urgent_count_counts_list_items(self) -> None:
        assert bps._extract_urgent_count("긴급 알림<ul><li>A</li><li>B</li><li>C</li></ul>") == 3

    def test_urgent_count_defaults_to_one_without_block(self) -> None:
        assert bps._extract_urgent_count("긴급 알림 있음") == 1

    def test_urgent_count_is_at_least_one_when_block_has_no_items(self) -> None:
        assert bps._extract_urgent_count("긴급 알림<ul></ul>") == 1


class TestBuildSocialSummary:
    def test_uses_extracted_counts_and_themes(self) -> None:
        body = (
            "총 30건 · 텔레그램 12건 · 소셜 미디어 10건 · 정치·경제 8건\n"
            "<strong>규제</strong> (5건) <strong>거래소</strong> (3건)\n"
            "긴급 알림<ul><li>A</li></ul>"
        )
        lines = bps.build_social_summary(body)
        assert "총 30건" in lines[0]
        assert "텔레그램 12건" in lines[0]
        assert "규제 및 거래소" in lines[0]
        assert lines[2] == "**핵심 신호 정리**"
        assert lines[3] == "- 주요 테마: 규제, 거래소"
        assert lines[4] == "- 긴급 알림 1건에 대한 선별 모니터링"

    def test_defaults_when_nothing_extracted(self) -> None:
        lines = bps.build_social_summary("본문 없음")
        assert "총 0건" in lines[0]
        assert "다양한" in lines[0]
        assert lines[3] == "- 주요 테마: 다양한 이슈"
        assert lines[4] == "- 긴급 알림 없음에 대한 선별 모니터링"


class TestIsSocialMediaPostExclusions:
    def test_pinned_market_analysis_is_excluded(self) -> None:
        front = {"pin": "true", "categories": ["market-analysis"], "tags": ["social-media"]}
        assert bps.is_social_media_post(front, "소셜 미디어 텔레그램") is False

    def test_daily_summary_tag_is_excluded(self) -> None:
        front = {"tags": ["일일요약", "social-media"]}
        assert bps.is_social_media_post(front, "소셜 미디어 텔레그램") is False

    def test_daily_summary_title_is_excluded(self) -> None:
        front = {"title": "일일 뉴스 종합", "tags": ["social-media"]}
        assert bps.is_social_media_post(front, "") is False

    def test_social_media_tag_matches(self) -> None:
        assert bps.is_social_media_post({"tags": ["social-media"]}, "") is True

    def test_title_matches(self) -> None:
        assert bps.is_social_media_post({"title": "소셜 미디어 동향"}, "") is True

    def test_body_heuristic_needs_both_keywords(self) -> None:
        assert bps.is_social_media_post({}, "소셜 미디어 이야기") is False
        assert bps.is_social_media_post({}, "소셜 미디어 그리고 텔레그램") is True


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_total_and_themes_come_first(self) -> None:
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 에너지 | 3 |",
        ]
        result = bps.build_summary(lines, "총 42건 수집")
        assert result[0] == "총 **42건** 수집"
        assert result[1] == "주요 테마: 에너지"

    def test_pulls_bullets_from_priority_sections(self) -> None:
        lines = ["## 핵심 요약", "- 첫 항목", "- 둘째 항목"]
        assert bps.build_summary(lines, "")[:2] == ["첫 항목", "둘째 항목"]

    def test_intro_fallback_does_not_restate_already_used_bullets(self) -> None:
        """폴백이 이미 요약에 쓴 불릿을 중복으로 덧붙이지 않는다.

        `extract_intro_bullets` 가 불릿 줄을 걸러내지 않던 동안에는 결과가
        `["첫 항목", "둘째 항목", "- 첫 항목 - 둘째 항목"]` 이었다. 합쳐진 문자열은
        개별 불릿과 다른 값이라 `used` 집합으로도 막히지 않았다.
        """
        lines = ["## 핵심 요약", "- 첫 항목", "- 둘째 항목"]
        assert bps.build_summary(lines, "") == ["첫 항목", "둘째 항목"]

    def test_priority_order_is_followed(self) -> None:
        """`SECTION_PRIORITY` 순서대로 훑는다 — 문서 순서가 아니다."""
        lines = ["## 시장 개요", "- 나중 항목", "## 핵심 요약", "- 먼저 항목"]
        assert bps.build_summary(lines, "")[0] == "먼저 항목"

    def test_result_is_capped_at_four(self) -> None:
        lines = ["## 핵심 요약"] + [f"- 항목{i}" for i in range(10)]
        assert len(bps.build_summary(lines, "")) <= 4

    def test_duplicate_bullets_are_skipped(self) -> None:
        lines = ["## 핵심 요약", "- 같은 항목", "## 시장 개요", "- 같은 항목"]
        assert bps.build_summary(lines, "").count("같은 항목") == 1

    def test_bullet_restating_the_total_is_skipped(self) -> None:
        lines = ["## 핵심 요약", "- 총 42건 수집 완료", "- 실제 내용 항목"]
        result = bps.build_summary(lines, "총 42건 수집")
        assert "총 42건 수집 완료" not in result, result
        assert "실제 내용 항목" in result

    def test_falls_back_to_section_sentences(self) -> None:
        lines = ["## 핵심 요약", "불릿이 아닌 본문 문장입니다."]
        assert bps.build_summary(lines, "") == ["불릿이 아닌 본문 문장입니다."]

    def test_falls_back_to_intro_bullets(self) -> None:
        lines = ["도입부 문장입니다.", "", "둘째 도입 문장입니다."]
        result = bps.build_summary(lines, "")
        assert "도입부 문장입니다." in result

    def test_empty_input(self) -> None:
        assert bps.build_summary([], "") == []


# ---------------------------------------------------------------------------
# insert_* / remove_existing_*
# ---------------------------------------------------------------------------


class TestInsertSummary:
    def test_empty_summary_is_a_noop(self) -> None:
        lines = ["본문"]
        assert bps.insert_summary(lines, []) is lines

    def test_inserted_after_existing_overview_section(self) -> None:
        lines = ["## 한눈에 보기", "- 기존", "## 다음 섹션", "내용"]
        result = bps.insert_summary(lines, ["새 요약"])
        assert result.index(f"## {bps.SUMMARY_TITLE}") > result.index("- 기존")
        assert result.index(f"## {bps.SUMMARY_TITLE}") < result.index("## 다음 섹션")
        assert "- 새 요약" in result

    def test_anchor_priority_is_tuple_order_not_document_order(self) -> None:
        """앵커 탐색은 `("한눈에 보기", "핵심 요약")` 순서다 — 문서에 먼저 나온 쪽이 아니다.

        문서에서 '핵심 요약' 이 앞서더라도 '한눈에 보기' 섹션 뒤에 삽입된다.
        """
        lines = ["## 핵심 요약", "- A", "## 한눈에 보기", "- B"]
        result = bps.insert_summary(lines, ["새 요약"])
        assert result.index(f"## {bps.SUMMARY_TITLE}") > result.index("- B"), result

    def test_inserted_after_leading_paragraph_when_no_anchor(self) -> None:
        lines = ["", "도입 문단 첫 줄", "도입 문단 둘째 줄", "", "## 나머지"]
        result = bps.insert_summary(lines, ["새 요약"])
        assert result.index(f"## {bps.SUMMARY_TITLE}") > result.index("도입 문단 둘째 줄")
        assert result.index(f"## {bps.SUMMARY_TITLE}") < result.index("## 나머지")

    def test_bullets_are_prefixed(self) -> None:
        result = bps.insert_summary(["본문"], ["A", "B"])
        assert "- A" in result and "- B" in result


class TestInsertSocialSummary:
    def test_empty_summary_is_a_noop(self) -> None:
        lines = ["본문"]
        assert bps.insert_social_summary(lines, []) is lines

    def test_lines_are_inserted_verbatim(self) -> None:
        """소셜 요약은 이미 서식이 있으므로 `- ` 접두사를 붙이지 않는다."""
        result = bps.insert_social_summary(["본문"], ["**핵심 신호 정리**", "- 주요 테마: 규제"])
        assert "**핵심 신호 정리**" in result
        assert "- - 주요 테마: 규제" not in result

    def test_inserted_after_existing_overview_section(self) -> None:
        lines = ["## 핵심 요약", "- 기존", "## 다음", "내용"]
        result = bps.insert_social_summary(lines, ["요약"])
        assert result.index(f"## {bps.SUMMARY_TITLE}") < result.index("## 다음")


class TestRemoveExisting:
    def test_removes_url_summary_section(self) -> None:
        lines = [f"## {bps.URL_SUMMARY_TITLE}", "- 링크", "## 다음", "내용"]
        result, removed = bps.remove_existing_url_summary(lines)
        assert removed is True
        assert result == ["## 다음", "내용"]

    def test_url_summary_absent(self) -> None:
        lines = ["## 다음"]
        assert bps.remove_existing_url_summary(lines) == (lines, False)

    def test_removes_analysis_section(self) -> None:
        lines = [f"## {bps.ANALYSIS_TITLE}", "- 분석", "## 다음", "내용"]
        result, removed = bps.remove_existing_analysis(lines)
        assert removed is True
        assert result == ["## 다음", "내용"]

    def test_analysis_absent(self) -> None:
        lines = ["## 다음"]
        assert bps.remove_existing_analysis(lines) == (lines, False)

    def test_removal_at_end_of_document(self) -> None:
        lines = ["내용", f"## {bps.ANALYSIS_TITLE}", "- 분석"]
        result, removed = bps.remove_existing_analysis(lines)
        assert removed is True
        assert result == ["내용"]


class TestInsertAnalysis:
    def test_empty_is_a_noop(self) -> None:
        lines = ["본문"]
        assert bps.insert_analysis(lines, []) is lines

    def test_inserted_after_summary_section(self) -> None:
        lines = [f"## {bps.SUMMARY_TITLE}", "- 요약", "## 다음", "내용"]
        result = bps.insert_analysis(lines, ["분석"])
        assert result.index(f"## {bps.ANALYSIS_TITLE}") < result.index("## 다음")

    def test_appended_when_no_summary_section(self) -> None:
        result = bps.insert_analysis(["본문"], ["분석"])
        assert result[0] == "본문"
        assert f"## {bps.ANALYSIS_TITLE}" in result
        assert result.index(f"## {bps.ANALYSIS_TITLE}") > 0


class TestInsertUrlSummary:
    def test_empty_is_a_noop(self) -> None:
        lines = ["본문"]
        assert bps.insert_url_summary(lines, []) is lines

    def test_prefers_analysis_anchor(self) -> None:
        lines = [
            f"## {bps.SUMMARY_TITLE}",
            "- 요약",
            f"## {bps.ANALYSIS_TITLE}",
            "- 분석",
            "## 다음",
        ]
        result = bps.insert_url_summary(lines, ["- 링크"])
        assert result.index(f"## {bps.URL_SUMMARY_TITLE}") > result.index("- 분석")

    def test_falls_back_to_summary_anchor(self) -> None:
        lines = [f"## {bps.SUMMARY_TITLE}", "- 요약", "## 다음"]
        result = bps.insert_url_summary(lines, ["- 링크"])
        assert result.index(f"## {bps.URL_SUMMARY_TITLE}") < result.index("## 다음")

    def test_falls_back_to_leading_paragraph(self) -> None:
        lines = ["", "도입 문단", "", "## 나머지"]
        result = bps.insert_url_summary(lines, ["- 링크"])
        assert result.index(f"## {bps.URL_SUMMARY_TITLE}") < result.index("## 나머지")


# ---------------------------------------------------------------------------
# normalize_worldmonitor_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeWorldmonitorSnapshot:
    def test_no_marker_is_a_noop(self) -> None:
        lines = ["평범한 본문"]
        assert bps.normalize_worldmonitor_snapshot(lines) is lines

    def test_already_normalized_on_same_line_is_a_noop(self) -> None:
        lines = ['<div class="alert-box alert-info"><strong>오늘의 글로벌 리스크 스냅샷</strong>']
        assert bps.normalize_worldmonitor_snapshot(lines) is lines

    def test_already_normalized_on_previous_line_is_a_noop(self) -> None:
        lines = ['<div class="alert-box alert-info">', "오늘의 글로벌 리스크 스냅샷"]
        assert bps.normalize_worldmonitor_snapshot(lines) is lines

    def test_converts_plain_lines_to_alert_box(self) -> None:
        lines = [
            "## 오늘의 글로벌 리스크 스냅샷",
            "**총 수집:** 42건",
            "**핵심 테마:** 지정학/안보",
            "**집중 출처:** Reuters",
            "",
            "## 다음 섹션",
        ]
        result = bps.normalize_worldmonitor_snapshot(lines)
        assert result[0].startswith('<div class="alert-box alert-info">')
        assert "<li>총 수집: 42건</li>" in result
        assert "<li>핵심 테마: 지정학/안보</li>" in result
        assert "<li>집중 출처: Reuters</li>" in result
        assert result[4] == "</ul></div>"
        assert "## 다음 섹션" in result

    def test_bullet_prefixed_fields_are_not_recognized(self) -> None:
        """필드 판별이 `cleaned.startswith("총 수집:")` 이라 `- ` 불릿은 매칭되지 않는다.

        스냅샷 블록이 불릿으로 쓰이면 값이 전부 N/A 로 떨어진다 — 현재 계약이
        "접두사 없는 줄" 임을 고정한다.
        """
        lines = ["## 오늘의 글로벌 리스크 스냅샷", "- **총 수집:** 42건", ""]
        result = bps.normalize_worldmonitor_snapshot(lines)
        assert "<li>총 수집: N/A</li>" in result, result

    def test_missing_fields_become_na(self) -> None:
        result = bps.normalize_worldmonitor_snapshot(["## 오늘의 글로벌 리스크 스냅샷", ""])
        assert "<li>총 수집: N/A</li>" in result
        assert "<li>핵심 테마: N/A</li>" in result
        assert "<li>집중 출처: N/A</li>" in result

    def test_next_heading_bounds_the_replacement(self) -> None:
        lines = ["오늘의 글로벌 리스크 스냅샷", "## 다음 섹션", "보존되어야 하는 내용"]
        result = bps.normalize_worldmonitor_snapshot(lines)
        assert result[-2:] == ["## 다음 섹션", "보존되어야 하는 내용"]


# ---------------------------------------------------------------------------
# _parse_table / reorder_worldmonitor_table
# ---------------------------------------------------------------------------


class TestParseTable:
    def test_parses_rows(self) -> None:
        lines = ["| A | B |", "| --- | --- |", "| 1 | 2 |", "| 3 | 4 |", "본문"]
        end, rows = bps._parse_table(lines, 0)
        assert rows == [["1", "2"], ["3", "4"]]
        assert lines[end] == "본문"

    def test_start_beyond_end(self) -> None:
        assert bps._parse_table([], 0) == (0, [])

    def test_non_table_header(self) -> None:
        assert bps._parse_table(["본문"], 0) == (0, [])

    def test_header_without_separator(self) -> None:
        assert bps._parse_table(["| A | B |", "본문"], 0) == (0, [])

    def test_header_at_end_of_document(self) -> None:
        assert bps._parse_table(["| A | B |"], 0) == (0, [])

    def test_stops_at_blank_line(self) -> None:
        lines = ["| A |", "| --- |", "| 1 |", "", "| 2 |"]
        _end, rows = bps._parse_table(lines, 0)
        assert rows == [["1"]]


class TestReorderWorldmonitorTable:
    HEADER = "| 순번 | 주요 이슈 | 테마 | 시장 영향 | 출처 |"
    SEP = "| :---: | --- | :---: | :---: | --- |"

    def _table(self) -> list[str]:
        return [
            "## 주요 이슈",
            self.HEADER,
            self.SEP,
            "| 1 | 낮은 이슈 | 사회/기타 | 낮음~중간 | S1 |",
            "| 2 | 높은 이슈 | 지정학/안보 | 높음 | S2 |",
            "| 3 | 중간 이슈 | 에너지 | 중간 | S3 |",
        ]

    def test_missing_heading_is_a_noop(self) -> None:
        lines = ["본문"]
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["worldmonitor"]}) is lines

    def test_non_worldmonitor_post_is_a_noop(self) -> None:
        lines = self._table()
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["crypto"]}) is lines

    @pytest.mark.parametrize(
        "front",
        [
            {"tags": ["worldmonitor"]},
            {"title": "WorldMonitor 리포트"},
            {"title": "월드모니터 리포트"},
        ],
    )
    def test_gate_accepts_any_worldmonitor_marker(self, front: dict) -> None:
        result = bps.reorder_worldmonitor_table(self._table(), front)
        assert "높은 이슈" in result[3], result[3]

    def test_rows_sorted_by_impact_then_theme(self) -> None:
        result = bps.reorder_worldmonitor_table(self._table(), {"tags": ["worldmonitor"]})
        body_rows = [ln for ln in result if ln.startswith("| ") and "이슈 |" in ln and "주요 이슈" not in ln]
        assert [r.split("|")[2].strip() for r in body_rows] == ["높은 이슈", "중간 이슈", "낮은 이슈"]

    def test_sequence_numbers_are_renumbered(self) -> None:
        result = bps.reorder_worldmonitor_table(self._table(), {"tags": ["worldmonitor"]})
        body_rows = [ln for ln in result if ln.startswith("| ") and "이슈 |" in ln and "주요 이슈" not in ln]
        assert [r.split("|")[1].strip() for r in body_rows] == ["1", "2", "3"]

    def test_date_gate_from(self) -> None:
        front = {"tags": ["worldmonitor"], "date": "2026-01-01"}
        lines = self._table()
        assert bps.reorder_worldmonitor_table(lines, front, wm_from="2026-02-01") is lines

    def test_date_gate_to(self) -> None:
        front = {"tags": ["worldmonitor"], "date": "2026-03-01"}
        lines = self._table()
        assert bps.reorder_worldmonitor_table(lines, front, wm_to="2026-02-01") is lines

    def test_date_inside_range_is_processed(self) -> None:
        front = {"tags": ["worldmonitor"], "date": "2026-02-15"}
        result = bps.reorder_worldmonitor_table(self._table(), front, wm_from="2026-02-01", wm_to="2026-03-01")
        assert "높은 이슈" in result[3]

    def test_heading_before_table_aborts(self) -> None:
        lines = ["## 주요 이슈", "본문", "## 다른 섹션", self.HEADER, self.SEP, "| 1 | A | B | C | D |"]
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["worldmonitor"]}) is lines

    def test_no_table_after_heading_aborts(self) -> None:
        lines = ["## 주요 이슈", "본문만 있다"]
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["worldmonitor"]}) is lines

    def test_wrong_header_columns_abort(self) -> None:
        lines = ["## 주요 이슈", "| A | B |", "| --- | --- |", "| 1 | 2 |"]
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["worldmonitor"]}) is lines

    def test_empty_table_body_aborts(self) -> None:
        lines = ["## 주요 이슈", self.HEADER, self.SEP]
        assert bps.reorder_worldmonitor_table(lines, {"tags": ["worldmonitor"]}) is lines


# ---------------------------------------------------------------------------
# 디스크를 만지는 경로 — REPO_ROOT / POSTS_DIR 을 tmp 로 주입한다
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """`REPO_ROOT` / `POSTS_DIR` 를 tmp 로 갈아끼운 가짜 저장소.

    프로덕션 상수를 **읽지 않고** 문자열로 덮어쓴다. 이 주입이 없으면 아래 테스트들이
    실제 `_posts/` 와 `assets/` 를 읽고, `process_post` 는 실제 포스트를 덮어쓴다.
    """
    posts = tmp_path / "_posts"
    posts.mkdir()
    (tmp_path / "assets" / "images" / "generated").mkdir(parents=True)
    monkeypatch.setattr(bps, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(bps, "POSTS_DIR", str(posts))
    return tmp_path


class TestExtractLocalImagePath:
    @pytest.mark.parametrize(
        "raw",
        ["https://cdn.example.com/a.png", "http://cdn.example.com/a.png", "data:image/png;base64,AAA"],
    )
    def test_remote_and_data_uris_are_not_local(self, raw: str) -> None:
        assert bps._extract_local_image_path(raw) == ""

    def test_liquid_relative_url_is_unwrapped(self) -> None:
        raw = "{{ '/assets/images/generated/a.png' | relative_url }}"
        assert bps._extract_local_image_path(raw) == "/assets/images/generated/a.png"

    def test_plain_path_passes_through(self) -> None:
        assert bps._extract_local_image_path("  /assets/a.png  ") == "/assets/a.png"


class TestRemoveMissingLocalImagesWithFakeRoot:
    def _write_image(self, fake_repo, name: str, size: int = 10) -> str:
        path = fake_repo / "assets" / "images" / "generated" / name
        path.write_bytes(b"x" * size)
        return f"/assets/images/generated/{name}"

    def test_existing_image_is_kept(self, fake_repo) -> None:
        rel = self._write_image(fake_repo, "present.png")
        lines = [f"![alt]({rel})"]
        assert bps.remove_missing_local_images(lines) == lines

    def test_missing_image_line_is_dropped(self, fake_repo) -> None:
        lines = ["![alt](/assets/images/generated/gone.png)", "본문"]
        assert bps.remove_missing_local_images(lines) == ["본문"]

    def test_zero_byte_image_line_is_dropped(self, fake_repo) -> None:
        rel = self._write_image(fake_repo, "empty.png", size=0)
        assert bps.remove_missing_local_images([f"![alt]({rel})", "본문"]) == ["본문"]

    def test_html_img_tag_is_handled(self, fake_repo) -> None:
        lines = ['<img src="/assets/images/generated/gone.png" alt="x">', "본문"]
        assert bps.remove_missing_local_images(lines) == ["본문"]

    def test_remote_image_is_always_kept(self, fake_repo) -> None:
        lines = ["![alt](https://cdn.example.com/a.png)"]
        assert bps.remove_missing_local_images(lines) == lines

    def test_liquid_path_is_resolved(self, fake_repo) -> None:
        self._write_image(fake_repo, "liquid.png")
        kept = ["![alt]({{ '/assets/images/generated/liquid.png' | relative_url }})"]
        assert bps.remove_missing_local_images(kept) == kept
        dropped = ["![alt]({{ '/assets/images/generated/nope.png' | relative_url }})"]
        assert bps.remove_missing_local_images(dropped) == []

    def test_lines_without_images_pass_through(self, fake_repo) -> None:
        lines = ["본문", "## 제목"]
        assert bps.remove_missing_local_images(lines) == lines


class TestListZeroByteImages:
    def test_missing_directory_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(bps, "REPO_ROOT", str(tmp_path))
        assert bps.list_zero_byte_images() == []

    def test_finds_only_zero_byte_files_sorted(self, fake_repo) -> None:
        gen = fake_repo / "assets" / "images" / "generated"
        (gen / "b-empty.png").write_bytes(b"")
        (gen / "a-empty.png").write_bytes(b"")
        (gen / "full.png").write_bytes(b"data")
        assert bps.list_zero_byte_images() == [
            "assets/images/generated/a-empty.png",
            "assets/images/generated/b-empty.png",
        ]

    def test_walks_subdirectories(self, fake_repo) -> None:
        sub = fake_repo / "assets" / "images" / "generated" / "sub"
        sub.mkdir()
        (sub / "empty.png").write_bytes(b"")
        assert bps.list_zero_byte_images() == ["assets/images/generated/sub/empty.png"]


# ---------------------------------------------------------------------------
# process_post
# ---------------------------------------------------------------------------


class TestProcessPost:
    def _post(self, fake_repo, name: str, content: str):
        path = fake_repo / "_posts" / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_body_without_frontmatter_is_skipped(self, fake_repo) -> None:
        path = self._post(fake_repo, "2026-01-01-a.md", "")
        assert bps.process_post(str(path)) is False

    def test_summary_is_inserted_and_written(self, fake_repo) -> None:
        content = (
            "---\ntitle: 테스트 포스트\ntags: [crypto]\n---\n도입 문단입니다.\n\n## 시장 개요\n- 첫 항목\n- 둘째 항목\n"
        )
        path = self._post(fake_repo, "2026-01-01-a.md", content)
        assert bps.process_post(str(path)) is True
        written = path.read_text(encoding="utf-8")
        assert f"## {bps.SUMMARY_TITLE}" in written
        assert written.startswith("---\ntitle: 테스트 포스트"), "front matter 가 보존되지 않았다"

    def test_existing_summary_section_is_not_duplicated(self, fake_repo) -> None:
        content = "---\ntitle: T\n---\n## 핵심 요약\n- 이미 있는 요약\n"
        path = self._post(fake_repo, "2026-01-01-b.md", content)
        bps.process_post(str(path))
        assert path.read_text(encoding="utf-8").count(f"## {bps.SUMMARY_TITLE}") == 0

    def test_social_post_uses_social_summary(self, fake_repo) -> None:
        content = "---\ntitle: 소셜 미디어 동향\ntags: [social-media]\n---\n총 30건 · 텔레그램 12건\n"
        path = self._post(fake_repo, "2026-01-01-c.md", content)
        assert bps.process_post(str(path)) is True
        assert "**핵심 신호 정리**" in path.read_text(encoding="utf-8")

    def test_no_change_returns_false_and_leaves_file_alone(self, fake_repo) -> None:
        content = "---\ntitle: T\n---\n## 핵심 요약\n- 이미 있는 요약\n"
        path = self._post(fake_repo, "2026-01-01-d.md", content)
        before = path.read_text(encoding="utf-8")
        assert bps.process_post(str(path)) is False
        assert path.read_text(encoding="utf-8") == before

    def test_clean_images_only_removes_missing_image(self, fake_repo) -> None:
        content = "---\ntitle: T\n---\n본문\n![alt](/assets/images/generated/gone.png)\n"
        path = self._post(fake_repo, "2026-01-01-e.md", content)
        assert bps.process_post(str(path), clean_images_only=True) is True
        written = path.read_text(encoding="utf-8")
        assert "gone.png" not in written
        assert f"## {bps.SUMMARY_TITLE}" not in written, "clean_images_only 인데 요약을 넣었다"

    def test_clean_images_only_returns_false_when_nothing_to_remove(self, fake_repo) -> None:
        content = "---\ntitle: T\n---\n본문만 있다\n"
        path = self._post(fake_repo, "2026-01-01-f.md", content)
        assert bps.process_post(str(path), clean_images_only=True) is False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run(self, monkeypatch, argv: list[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["backfill_post_summaries.py", *argv])
        bps.main()

    def test_missing_posts_dir_warns_and_returns(self, tmp_path, monkeypatch, caplog) -> None:
        monkeypatch.setattr(bps, "POSTS_DIR", str(tmp_path / "nope"))
        with caplog.at_level("WARNING"):
            self._run(monkeypatch, [])
        assert any("Posts directory not found" in r.message for r in caplog.records)

    def test_processes_posts_and_logs_counts(self, fake_repo, monkeypatch, caplog) -> None:
        (fake_repo / "_posts" / "2026-01-01-a.md").write_text(
            "---\ntitle: T\n---\n도입 문단입니다.\n\n## 시장 개요\n- 항목\n", encoding="utf-8"
        )
        (fake_repo / "_posts" / "notes.txt").write_text("무시됨", encoding="utf-8")
        with caplog.at_level("INFO"):
            self._run(monkeypatch, [])
        assert any("Checked 1 posts, updated 1" in r.message for r in caplog.records), [
            r.message for r in caplog.records
        ]

    def test_date_filters_exclude_posts(self, fake_repo, monkeypatch, caplog) -> None:
        for name in ("2026-01-01-a.md", "2026-06-01-b.md", "2026-12-01-c.md"):
            (fake_repo / "_posts" / name).write_text(
                "---\ntitle: T\n---\n도입 문단입니다.\n\n## 시장 개요\n- 항목\n", encoding="utf-8"
            )
        with caplog.at_level("INFO"):
            self._run(monkeypatch, ["--from-date", "2026-05-01", "--to-date", "2026-07-01"])
        assert any("Checked 1 posts" in r.message for r in caplog.records), [r.message for r in caplog.records]

    def test_zero_image_report_lists_files(self, fake_repo, monkeypatch) -> None:
        (fake_repo / "assets" / "images" / "generated" / "empty.png").write_bytes(b"")
        report = fake_repo / "reports" / "zero.txt"
        self._run(monkeypatch, ["--zero-image-report", str(report)])
        text = report.read_text(encoding="utf-8")
        assert "Zero-byte images" in text
        assert "- assets/images/generated/empty.png" in text

    def test_zero_image_report_says_none_when_clean(self, fake_repo, monkeypatch) -> None:
        report = fake_repo / "reports" / "zero.txt"
        self._run(monkeypatch, ["--zero-image-report", str(report)])
        assert "None" in report.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 남은 분기 — 스킵 경로와 예외 경로
# ---------------------------------------------------------------------------


class TestIsNoiseTextRemainingBranches:
    @pytest.mark.parametrize(
        "text",
        [
            "assets/images/generated/news-briefing-crypto.png",
            "source-distribution 차트",
            "market-heatmap-cmc 이미지",
        ],
    )
    def test_generated_chart_filenames_are_noise(self, text: str) -> None:
        assert bps.is_noise_text(text) is True

    def test_collection_footer_is_noise(self) -> None:
        assert bps.is_noise_text("데이터 수집 시각: 09:00 KST") is True


class TestBuildUrlSummarySkipPaths:
    def test_item_without_any_summary_is_skipped(self) -> None:
        """제목이 정규화 후 비면 요약을 만들 수 없어 항목 자체를 버린다."""
        assert bps.build_url_summary(["- [...](https://example.com/a)"]) == []

    def test_item_with_summary_but_empty_title_is_skipped(self) -> None:
        lines = ["- [...](https://example.com/a)", "설명은 있으나 제목이 비어 있습니다."]
        assert bps.build_url_summary(lines) == []

    def test_numbered_summary_is_regenerated_from_title(self) -> None:
        """설명이 '1. [' 로 시작하면 목록 조각이므로 제목 기반 요약으로 다시 만든다."""
        lines = [
            "- [Gold market report](https://example.com/g)",
            "1. [잘린 목록 조각이 설명 자리에 들어왔습니다.",
        ]
        (line,) = bps.build_url_summary(lines)
        assert "1. [" not in line, line
        assert "금 — " in line, line


class TestBuildSummaryEarlyReturns:
    def test_returns_immediately_when_bullets_fill_the_quota(self) -> None:
        """총계·테마가 2칸을 채운 뒤 불릿 2개로 4가 되면 그 자리에서 반환한다.

        `extract_section_bullets` 의 limit 이 3 이므로 불릿만으로는 4에 닿지 못한다 —
        조기 반환 지점을 밟으려면 앞선 두 줄이 필요하다.
        """
        lines = [
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 에너지 | 3 |",
            "## 핵심 요약",
            "- 첫 항목",
            "- 둘째 항목",
            "- 셋째 항목",
            "## 시장 인사이트",
            "- 도달하면 안 되는 항목",
        ]
        result = bps.build_summary(lines, "총 42건 수집")
        assert result == ["총 **42건** 수집", "주요 테마: 에너지", "첫 항목", "둘째 항목"], result
        assert "셋째 항목" not in result, "조기 반환이 사라졌다"

    def test_returns_as_soon_as_four_items_collected_via_sentences(self) -> None:
        lines = [
            "## 핵심 요약",
            "첫 문장입니다.",
            "둘째 문장입니다.",
            "",
            "## 시장 인사이트",
            "셋째 문장입니다.",
            "넷째 문장입니다.",
        ]
        result = bps.build_summary(lines, "")
        assert len(result) == 4, result

    def test_duplicate_sentence_across_sections_is_skipped(self) -> None:
        lines = ["## 핵심 요약", "같은 문장입니다.", "", "## 시장 인사이트", "같은 문장입니다."]
        assert bps.build_summary(lines, "").count("같은 문장입니다.") == 1


class TestInsertSocialSummaryFallback:
    def test_leading_blank_lines_are_skipped_before_insertion(self) -> None:
        lines = ["", "", "도입 문단", "", "## 나머지"]
        result = bps.insert_social_summary(lines, ["요약"])
        assert result.index(f"## {bps.SUMMARY_TITLE}") > result.index("도입 문단")
        assert result.index(f"## {bps.SUMMARY_TITLE}") < result.index("## 나머지")


class TestRemoveMissingLocalImagesNonAssetPath:
    def test_path_outside_assets_is_resolved_against_repo_root(self, fake_repo) -> None:
        """`assets/` 로 시작하지 않는 경로도 REPO_ROOT 기준으로 해석된다."""
        (fake_repo / "images").mkdir()
        (fake_repo / "images" / "present.png").write_bytes(b"x")
        kept = ["![alt](images/present.png)"]
        assert bps.remove_missing_local_images(kept) == kept
        assert bps.remove_missing_local_images(["![alt](images/gone.png)"]) == []


class TestListZeroByteImagesErrorPath:
    def test_unreadable_entry_is_skipped(self, fake_repo) -> None:
        """`os.path.getsize` 가 OSError 를 내면 그 항목만 건너뛴다.

        깨진 심볼릭 링크로 실제 OSError 를 만든다 — 예외를 mock 으로 주입하면
        `except OSError` 가 정말 그 자리에 있는지 확인하지 못한다.
        """
        gen = fake_repo / "assets" / "images" / "generated"
        (gen / "broken.png").symlink_to(gen / "does-not-exist.png")
        (gen / "empty.png").write_bytes(b"")
        assert bps.list_zero_byte_images() == ["assets/images/generated/empty.png"]


# ---------------------------------------------------------------------------
# 결함 수정 회귀 (2026-08-27)
# ---------------------------------------------------------------------------


class TestIntroBulletsTreatListAsBoundary:
    """`extract_intro_bullets` 에서 불릿은 단락이 아니라 **단락 경계**다."""

    def test_bullet_lines_are_not_paragraphs(self) -> None:
        assert bps.extract_intro_bullets(["- 첫 항목", "* 둘째 항목"]) == []

    def test_bullet_list_ends_the_preceding_paragraph(self) -> None:
        """목록 앞뒤 텍스트가 하나로 합쳐지지 않는다."""
        lines = ["앞 단락입니다.", "- 목록 항목", "뒤 단락입니다."]
        assert bps.extract_intro_bullets(lines) == ["앞 단락입니다.", "뒤 단락입니다."]

    def test_paragraph_before_a_list_is_still_collected(self) -> None:
        assert bps.extract_intro_bullets(["도입 문단입니다.", "- 목록 항목"]) == ["도입 문단입니다."]


class TestLocalImagePathStaysInsideRepo:
    """죽은 조건을 지우면서 `lstrip("./")` 의 절대경로 방어가 남아 있는지.

    `os.path.join` 은 두 번째 인자가 절대경로면 첫 인자를 버린다. 정규화가 사라지면
    포스트에 적힌 `/etc/...` 같은 경로를 저장소 밖에서 조회하게 된다.
    """

    def test_absolute_looking_path_is_resolved_under_repo_root(self, fake_repo) -> None:
        outside = fake_repo.parent / "outside.png"
        outside.write_bytes(b"x")
        # 저장소 밖 실제 파일을 가리키는 것처럼 보이는 경로 — 저장소 안에서 찾아야 하고,
        # 거기에 없으므로 줄이 제거되어야 한다.
        assert bps.remove_missing_local_images([f"![alt]({outside})"]) == []

    def test_parent_traversal_is_flattened(self, fake_repo) -> None:
        (fake_repo / "escape.png").write_bytes(b"x")
        # "../escape.png" 의 선행 './' 문자가 벗겨져 REPO_ROOT/escape.png 로 해석된다.
        kept = ["![alt](../escape.png)"]
        assert bps.remove_missing_local_images(kept) == kept


class TestBuildSummaryIntroFallbackQuota:
    def test_intro_fallback_stops_at_four_items(self) -> None:
        """총계·테마 2칸 + 도입 단락 2개로 4가 되면 폴백 루프가 멈춘다.

        `extract_intro_bullets` 는 `paragraphs[:2]` 로 하드캡되어 있어 도입에서
        얻을 수 있는 항목은 최대 2개다. 불릿 스킵을 넣은 뒤로는 이 조합만이 폴백
        안에서 상한에 닿는 경로다.
        """
        lines = [
            "첫 도입 단락입니다.",
            "",
            "둘째 도입 단락입니다.",
            "",
            "## 테마 스냅샷",
            "| 테마 | 건수 |",
            "| --- | --- |",
            "| 에너지 | 3 |",
        ]
        result = bps.build_summary(lines, "총 42건 수집")
        assert result == [
            "총 **42건** 수집",
            "주요 테마: 에너지",
            "첫 도입 단락입니다.",
            "둘째 도입 단락입니다.",
        ], result
