"""Tests for the shared encoding guard (scripts/common/encoding_guard.py)."""

from types import SimpleNamespace

from common.encoding_guard import (
    force_utf8_if_mislabelled,
    is_mojibake,
    sanitize_mojibake,
)


class TestIsMojibake:
    def test_empty(self):
        assert is_mojibake("") is False

    def test_clean_korean(self):
        assert is_mojibake("한국은행 기준금리 동결") is False

    def test_detects_corrupted_run(self):
        assert is_mojibake("ì£¼ëì ììì ì íê³ CPBC") is True


class TestSanitizeMojibake:
    def test_passthrough_clean_korean(self):
        t = "한국은행이 기준금리 2.5%를 7회 연속 동결했다."
        assert sanitize_mojibake(t) == t

    def test_passthrough_english(self):
        t = "Bitcoin hits $70,000 amid strong ETF inflows"
        assert sanitize_mojibake(t) == t

    def test_empty(self):
        assert sanitize_mojibake("") == ""

    def test_roundtrip_recovery(self):
        # UTF-8 bytes misinterpreted as Latin-1 — the most common mojibake.
        original = "한국 경제 뉴스"
        corrupted = original.encode("utf-8").decode("latin-1")
        assert corrupted != original
        assert sanitize_mojibake(corrupted) == original

    def test_unrecoverable_dropped(self):
        # The CPBC string that leaked into _posts/2026-04-11-political-trades.
        corrupted = "ì£¼ëì ê¸°ì ììì ì íê³ ì¸ìì ë³μìíë¥¼ ìí´ ì²ì£¼êμê° ì¤ë¦½í ê°í¨ë¦ ì¬íì»¤ë®¤ëì¼ì´ì ë§¤ì²´ CPBC"
        assert sanitize_mojibake(corrupted) == ""

    def test_french_accent_not_flagged(self):
        t = "Café société française à Paris"
        assert sanitize_mojibake(t) == t

    def test_german_umlaut_not_flagged(self):
        t = "Bundesbank erhöht Leitzins"
        assert sanitize_mojibake(t) == t


class TestForceUtf8IfMislabelled:
    def test_latin1_label_switches_to_utf8(self):
        resp = SimpleNamespace(encoding="iso-8859-1")
        force_utf8_if_mislabelled(resp)
        assert resp.encoding == "utf-8"

    def test_latin_1_variant(self):
        resp = SimpleNamespace(encoding="latin-1")
        force_utf8_if_mislabelled(resp)
        assert resp.encoding == "utf-8"

    def test_ascii_label_switches(self):
        resp = SimpleNamespace(encoding="ASCII")
        force_utf8_if_mislabelled(resp)
        assert resp.encoding == "utf-8"

    def test_utf8_left_alone(self):
        resp = SimpleNamespace(encoding="utf-8")
        force_utf8_if_mislabelled(resp)
        assert resp.encoding == "utf-8"

    def test_none_encoding_left_alone(self):
        resp = SimpleNamespace(encoding=None)
        force_utf8_if_mislabelled(resp)
        assert resp.encoding is None

    def test_cp949_left_alone(self):
        # Legitimate Korean Windows encoding — not in the mislabel set, leave it.
        resp = SimpleNamespace(encoding="cp949")
        force_utf8_if_mislabelled(resp)
        assert resp.encoding == "cp949"
