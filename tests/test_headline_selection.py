"""Tests for the shared Korean-headline selector (scripts/common/headline.py).

Collectors lead their ``description_ko`` with the top item's headline. Every call
site did the same ``title_ko or title_translated or title`` lookup, which falls
back to the untranslated English title without anyone noticing the language
changed — that fallback produced the ASCII-heavy descriptions reported by
``scripts/check_description_quality.py``.
"""

from unittest.mock import patch

from common.headline import select_korean_headline
from common.summary_quality import ASCII_RATIO_THRESHOLD, ascii_ratio, is_ascii_dominant, is_ascii_heavy

_KOREAN = "비트코인 현물 ETF 순유입 3거래일 연속 확대"
_ENGLISH = "Bitcoin spot ETF inflows extend for a third straight session"


class TestSelectKoreanHeadline:
    def test_prefers_title_ko(self):
        item = {"title_ko": _KOREAN, "title_translated": "다른 번역", "title": _ENGLISH}
        assert select_korean_headline(item) == _KOREAN

    def test_falls_back_to_title_translated(self):
        """``get_display_title`` (translator.py) never read ``title_translated``,
        so items translated into that key silently lost their translation."""
        item = {"title_translated": _KOREAN, "title": _ENGLISH}
        assert select_korean_headline(item) == _KOREAN

    def test_english_title_is_translated(self):
        item = {"title": _ENGLISH}
        with patch("common.headline.translate_to_korean", return_value=_KOREAN) as mock_tr:
            assert select_korean_headline(item) == _KOREAN
        mock_tr.assert_called_once_with(_ENGLISH)

    def test_returns_empty_when_translation_fails_open(self):
        """``translate_to_korean`` returns the input unchanged on failure
        (translator.py fail-open). The caller must not treat that as Korean."""
        item = {"title": _ENGLISH}
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            assert select_korean_headline(item) == ""

    def test_returns_empty_when_no_title(self):
        assert select_korean_headline({}) == ""
        assert select_korean_headline({"title": "   "}) == ""

    def test_korean_title_is_not_translated(self):
        item = {"title_ko": _KOREAN}
        with patch("common.headline.translate_to_korean") as mock_tr:
            select_korean_headline(item)
        mock_tr.assert_not_called()

    def test_short_english_title_is_still_rejected(self):
        """``is_ascii_heavy`` skips strings under 30 chars; a headline must be
        language-checked regardless of length, so the helper uses the
        length-independent detector."""
        item = {"title": "Fed holds rates"}
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            assert select_korean_headline(item) == ""

    def test_korean_lead_quoting_english_is_kept(self):
        """A Korean sentence that quotes an English proper noun is Korean."""
        item = {"title_ko": "미국 SEC, 비트코인 현물 ETF 승인 발표"}
        assert select_korean_headline(item) == "미국 SEC, 비트코인 현물 ETF 승인 발표"


class TestAsciiDetectorsShareOneThreshold:
    """The headline helper and ``check_description_quality`` must not drift apart.

    Both read ``ASCII_RATIO_THRESHOLD`` from ``common.summary_quality``; a second
    literal copy elsewhere would let one side move without the other.
    """

    def test_checker_imports_the_shared_threshold(self):
        import check_description_quality as cdq

        assert cdq._ASCII_RATIO_THRESHOLD is ASCII_RATIO_THRESHOLD

    def test_no_duplicate_threshold_literal_in_checker(self):
        from pathlib import Path

        src = Path(cdq_path()).read_text(encoding="utf-8")
        assert "0.70" not in src, "threshold literal re-introduced; import it from common.summary_quality"

    def test_ratio_is_zero_without_letters(self):
        assert ascii_ratio("123 !!! ...") == 0.0

    def test_is_ascii_heavy_keeps_min_length_guard(self):
        short_english = "Fed holds"
        assert is_ascii_dominant(short_english)
        assert not is_ascii_heavy(short_english)


def cdq_path() -> str:
    import check_description_quality as cdq

    return cdq.__file__


class TestAcronymHeadlinesSurvive:
    """Economic-indicator and ticker labels are not English prose.

    ``CPI`` / ``FOMC`` / ``GDP`` are used verbatim in Korean copy and machine
    translation returns them unchanged, so the translate-or-drop rule would
    delete the summary's only concrete token. `collect_fmp_calendar.py` leads
    with exactly these names.
    """

    def test_acronym_event_names_are_kept(self):
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            for acronym in ("CPI", "FOMC", "GDP", "PMI", "AAPL"):
                assert select_korean_headline({"title": acronym}) == acronym

    def test_multiword_english_is_still_dropped(self):
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            for prose in ("Nonfarm Payrolls", "Treasury Sec Bessent Speaks", "ISM Manufacturing PMI"):
                assert select_korean_headline({"title": prose}) == ""
