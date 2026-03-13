"""Tests for translator post-processing (scripts/common/translator.py)."""

import hashlib

from common.translator import (
    TERM_OVERRIDES,
    _apply_term_overrides,
    _cache_key,
    _postprocess_translation,
    _restore_terms,
)


class TestTokenArtifacts:
    """Token-name artifacts that leak into translated text."""

    def test_ai_artifacts_in_words(self):
        assert _postprocess_translation("PAIrs") == "Pairs"
        assert _postprocess_translation("gAIns") == "gains"
        assert _postprocess_translation("mAIntain") == "maintain"
        assert _postprocess_translation("agAInst") == "against"
        assert _postprocess_translation("trAIning") == "training"

    def test_ai_artifacts_case_sensitivity(self):
        assert _postprocess_translation("ChAInlink") == "Chainlink"
        assert _postprocess_translation("BrAIn") == "Brain"
        assert _postprocess_translation("brAIn") == "brain"
        assert _postprocess_translation("RAIse") == "Raise"
        assert _postprocess_translation("rAIse") == "raise"

    def test_sol_artifacts(self):
        assert _postprocess_translation("SOLution") == "Solution"
        assert _postprocess_translation("reSOLve") == "resolve"
        assert _postprocess_translation("conSOLidate") == "consolidate"
        assert _postprocess_translation("abSOLute") == "absolute"

    def test_xrp_eth_artifacts(self):
        assert _postprocess_translation("XRPected") == "Expected"
        assert _postprocess_translation("ETHical") == "Ethical"

    def test_artifact_in_sentence(self):
        text = "비트코인 gAIns가 mAIn 시장 trAIning에 agAInst"
        result = _postprocess_translation(text)
        assert "gAI" not in result
        assert "mAI" not in result
        assert "gains" in result
        assert "main" in result

    def test_multiple_artifacts_in_one_string(self):
        text = "PAIrs와 SOLution 그리고 BrAIn"
        result = _postprocess_translation(text)
        assert result == "Pairs와 Solution 그리고 Brain"


class TestMediaNameFixes:
    """Mistranslated media/source names."""

    def test_motley_fool_variants(self):
        assert "Motley Fool" in _postprocess_translation("가지각색의 바보에 따르면")
        assert "Motley Fool" in _postprocess_translation("잡다한 바보 보도")
        assert "Motley Fool" in _postprocess_translation("얼룩덜룩한 바보")

    def test_seeking_alpha(self):
        assert "Seeking Alpha" in _postprocess_translation("알파 추구에서 보도")
        assert "Seeking Alpha" in _postprocess_translation("알파를 추구")

    def test_crypto_media(self):
        assert "CoinDesk" in _postprocess_translation("동전 데스크에 따르면")
        assert "CoinTelegraph" in _postprocess_translation("동전 텔레그래프 보도")
        assert "Decrypt" in _postprocess_translation("해독에 따르면")
        assert "The Block" in _postprocess_translation("더 블록 보도")

    def test_finance_media(self):
        assert "Yahoo Finance" in _postprocess_translation("야후 재무 보도")
        assert "Yahoo Finance" in _postprocess_translation("야후 금융에 따르면")
        assert "Barron's" in _postprocess_translation("바론의 보도")
        assert "Benzinga" in _postprocess_translation("벤징가에 따르면")

    def test_media_name_in_context(self):
        text = "가지각색의 바보에 따르면, 비트코인이 알파 추구에서도 주목받고 있습니다"
        result = _postprocess_translation(text)
        assert "Motley Fool" in result
        assert "Seeking Alpha" in result
        assert "가지각색" not in result


class TestKoreanStyleFixes:
    """Awkward Korean patterns from machine translation."""

    def test_short_crash_to_natural(self):
        assert "단기 급락" in _postprocess_translation("비트코인의 짧은 붕괴")

    def test_question_style(self):
        result = _postprocess_translation("투자할 수 있습니까?")
        assert "할 수 있을까?" in result

    def test_news_question_style(self):
        result = _postprocess_translation("상승인가요?")
        assert "상승일까?" in result

    def test_dollar_amount_style(self):
        result = _postprocess_translation("100만 달러 상당의 투자")
        assert "달러 규모" in result

    def test_trailing_source_removed(self):
        result = _postprocess_translation("비트코인 상승 - 나스닥")
        assert "나스닥" not in result

    def test_double_spaces_collapsed(self):
        result = _postprocess_translation("비트코인이  상승했습니다")
        assert "  " not in result


class TestEdgeCases:
    def test_empty_string(self):
        assert _postprocess_translation("") == ""

    def test_none_returns_none(self):
        assert _postprocess_translation(None) is None

    def test_clean_text_unchanged(self):
        text = "비트코인이 10% 상승했습니다"
        assert _postprocess_translation(text) == text

    def test_only_korean_unchanged(self):
        text = "이더리움 네트워크 업그레이드 예정"
        assert _postprocess_translation(text) == text

    def test_whitespace_stripped(self):
        result = _postprocess_translation("  텍스트  ")
        assert result == "텍스트"


class TestCacheKey:
    """Tests for _cache_key() helper."""

    def test_returns_16_char_hex(self):
        key = _cache_key("hello")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_deterministic(self):
        assert _cache_key("bitcoin") == _cache_key("bitcoin")

    def test_different_inputs_different_keys(self):
        assert _cache_key("bitcoin") != _cache_key("ethereum")

    def test_empty_string(self):
        key = _cache_key("")
        assert len(key) == 16

    def test_matches_sha256_prefix(self):
        text = "test text"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        assert _cache_key(text) == expected


class TestApplyTermOverrides:
    """Tests for _apply_term_overrides()."""

    def test_known_term_replaced_with_placeholder(self):
        text = "Bitcoin price is up"
        modified, replacements = _apply_term_overrides(text)
        assert "Bitcoin" not in modified
        assert len(replacements) > 0
        # Check placeholder format
        assert any("__TERM" in ph for ph, _ in replacements)

    def test_korean_replacement_in_tuple(self):
        text = "Ethereum network upgrade"
        _, replacements = _apply_term_overrides(text)
        koreans = [kr for _, kr in replacements]
        assert "이더리움" in koreans

    def test_no_known_terms_unchanged(self):
        text = "some random text without any term"
        modified, replacements = _apply_term_overrides(text)
        assert modified == text
        assert replacements == []

    def test_multiple_terms_all_replaced(self):
        text = "Bitcoin and Ethereum both rally"
        modified, replacements = _apply_term_overrides(text)
        assert "Bitcoin" not in modified
        assert "Ethereum" not in modified
        assert len(replacements) >= 2

    def test_partial_word_not_matched(self):
        # "AI" should NOT match inside "gain"
        text = "market gain of 5%"
        modified, replacements = _apply_term_overrides(text)
        # "AI" inside "gain" should not be replaced
        assert "gain" in modified or len(replacements) == 0

    def test_etf_kept_as_etf(self):
        text = "Bitcoin ETF approval expected"
        _, replacements = _apply_term_overrides(text)
        koreans = [kr for _, kr in replacements]
        assert "ETF" in koreans  # ETF maps to ETF

    def test_case_insensitive_matching(self):
        # "bitcoin" (lowercase) should match "Bitcoin" term
        text = "bitcoin is rising"
        _, replacements = _apply_term_overrides(text)
        assert len(replacements) > 0


class TestRestoreTerms:
    """Tests for _restore_terms()."""

    def test_placeholder_restored(self):
        text = "__TERM0__ price is up"
        replacements = [("__TERM0__", "비트코인")]
        result = _restore_terms(text, replacements)
        assert result == "비트코인 price is up"

    def test_multiple_placeholders_restored(self):
        text = "__TERM0__ and __TERM1__ both rose"
        replacements = [("__TERM0__", "비트코인"), ("__TERM1__", "이더리움")]
        result = _restore_terms(text, replacements)
        assert result == "비트코인 and 이더리움 both rose"

    def test_empty_replacements(self):
        text = "some text"
        result = _restore_terms(text, [])
        assert result == text

    def test_roundtrip_apply_restore(self):
        original = "Bitcoin and Ethereum rally"
        modified, replacements = _apply_term_overrides(original)
        restored = _restore_terms(modified, replacements)
        # Restored should contain Korean equivalents
        assert "비트코인" in restored
        assert "이더리움" in restored


class TestTermOverridesData:
    """Validate TERM_OVERRIDES data structure."""

    def test_non_empty(self):
        assert len(TERM_OVERRIDES) > 0

    def test_bitcoin_mapped(self):
        assert TERM_OVERRIDES["Bitcoin"] == "비트코인"

    def test_ethereum_mapped(self):
        assert TERM_OVERRIDES["Ethereum"] == "이더리움"

    def test_etf_self_mapped(self):
        assert TERM_OVERRIDES["ETF"] == "ETF"

    def test_all_values_are_strings(self):
        for k, v in TERM_OVERRIDES.items():
            assert isinstance(v, str), f"Key {k!r} has non-str value"

    def test_no_empty_keys(self):
        for k in TERM_OVERRIDES:
            assert k != "", "Empty key found in TERM_OVERRIDES"
