"""Unit tests for scripts/common/text_lang.is_supported_language."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from common.text_lang import is_supported_language


class TestIsSupportedLanguage:
    def test_korean_passes(self):
        assert is_supported_language("비트코인 가격 분석 보고서") is True

    def test_english_passes(self):
        assert is_supported_language("Trump Warns of Renewed Military Action") is True

    def test_chinese_cjk_dropped(self):
        assert is_supported_language("伊朗 高浓缩铀留境 声明对原油市场冲击有限") is False

    def test_japanese_with_kanji_dropped(self):
        # Kanji-only fragments collide with CJK ideograph block
        assert is_supported_language("中国経済の減速") is False

    def test_russian_dropped(self):
        assert is_supported_language("Еврокомиссия предполагает, что конфликт") is False

    def test_indonesian_dropped(self):
        assert is_supported_language("Keandalan Perang Asimetris di Timur Tengah") is False

    def test_turkish_dropped(self):
        assert is_supported_language("Trump anlasma olmazsa savas yeniden baslar dedi Iran") is False

    def test_korean_with_latin_brand_passes(self):
        # Mixed Korean + English brand name should pass via Hangul gate
        assert is_supported_language("Trump 정책 미국 의회 반발 SEC 조사 진행") is True

    def test_empty_dropped(self):
        assert is_supported_language("") is False

    def test_whitespace_only_dropped(self):
        assert is_supported_language("   \n\t") is False
