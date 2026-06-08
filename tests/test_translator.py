"""Tests for translator post-processing (scripts/common/translator.py)."""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.translator import (
    TERM_OVERRIDES,
    _apply_term_overrides,
    _cache_key,
    _load_cache,
    _postprocess_translation,
    _restore_terms,
    _save_cache,
    _should_translate_body_line,
    get_display_description,
    get_display_title,
    save_translation_cache,
    translate_batch,
    translate_to_korean,
    translate_untranslated_body,
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


class TestEuropeanNumberFormat:
    """European-style number formatting fixes (BTC$71.018,21 → BTC $71,018.21)."""

    def test_ticker_prefix_basic(self):
        # "BTC$71.018,21 및" → "BTC $71,018.21 및"
        result = _postprocess_translation("BTC$71.018,21 및")
        assert result == "BTC $71,018.21 및"

    def test_ticker_prefix_eth(self):
        # ETH ticker variant
        result = _postprocess_translation("ETH$3.456,78")
        assert result == "ETH $3,456.78"

    def test_no_ticker_prefix(self):
        # Standalone "$71.018,21" without ticker prefix
        result = _postprocess_translation("가격은 $71.018,21 수준입니다")
        assert result == "가격은 $71,018.21 수준입니다"

    def test_no_ticker_prefix_standalone(self):
        # Standalone at end of string
        result = _postprocess_translation("총액: $1.234,56")
        assert result == "총액: $1,234.56"

    def test_already_us_format_unchanged(self):
        # Already correct US format must not be double-converted
        result = _postprocess_translation("가격 $71,018.21 확인")
        assert result == "가격 $71,018.21 확인"

    def test_ticker_five_chars(self):
        # Up to 5-char ticker (e.g. MATIC)
        result = _postprocess_translation("MATIC$2.345,67")
        assert result == "MATIC $2,345.67"


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


class TestTranslateUntranslatedBody:
    def test_detects_english_prose_line(self):
        assert _should_translate_body_line("Bitcoin rises as traders watch ETF approval news closely.")

    def test_skips_markdown_link_line(self):
        assert not _should_translate_body_line("**1. [Bitcoin rises](https://example.com)**")

    def test_skips_korean_line(self):
        assert not _should_translate_body_line("비트코인이 ETF 기대감으로 상승했습니다.")

    def test_translates_plain_english_lines_only(self):
        content = "## 전체 뉴스 요약\n\nBitcoin rises as traders watch ETF approval news closely.\n\n- Market volatility remains elevated after Powell comments.\n\n**1. [Linked title](https://example.com)**"
        with patch(
            "common.translator.translate_batch",
            return_value=[
                "비트코인이 ETF 승인 기대감으로 상승했습니다.",
                "시장 변동성은 파월 발언 이후 높은 수준을 유지했습니다.",
            ],
        ):
            result = translate_untranslated_body(content)
        assert "비트코인이 ETF 승인 기대감으로 상승했습니다." in result
        assert "- 시장 변동성은 파월 발언 이후 높은 수준을 유지했습니다." in result
        assert "[Linked title](https://example.com)" in result

    def test_preserves_original_when_no_targets(self):
        content = "## 전체 뉴스 요약\n\n비트코인이 상승했습니다."
        assert translate_untranslated_body(content) == content


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


class TestDeFiProjectTermOverrides:
    """DeFi 프로젝트 고유명사 보호 + 흔한 단어 오탐 방지 회귀 가드."""

    def test_defi_proper_nouns_protected(self):
        # 신규 고유명사는 placeholder로 보호되어 MT 변형을 받지 않아야 한다.
        for term in ["Lido", "Arbitrum", "PancakeSwap", "Wormhole", "Hyperliquid"]:
            modified, replacements = _apply_term_overrides(f"{term} suffered an exploit")
            assert term not in modified, f"{term} should be protected"
            assert len(replacements) >= 1

    def test_multiword_form_protected(self):
        # 다단어 형태는 통째로 보호된다.
        modified, replacements = _apply_term_overrides("Cetus Protocol was hacked")
        assert "Cetus Protocol" not in modified
        assert any(kr == "Cetus Protocol" for _, kr in replacements)

    def test_ambiguous_common_words_not_matched(self):
        # 흔한 영어 단어와 충돌하는 프로젝트명은 추가하지 않았으므로,
        # 이 문장들은 어떤 용어도 치환하지 않아야 한다 (#1006-1009 품질 회귀 방지).
        for text in [
            "market optimism remains high",
            "the yield curve steepened",
            "a load balancer failure",
            "compound interest grows over time",
            "investors yearn for higher returns",
        ]:
            _, replacements = _apply_term_overrides(text)
            assert replacements == [], f"unexpected term match in: {text!r} → {replacements}"

    def test_bare_curve_not_matched_but_curve_finance_is(self):
        # bare "Curve"는 미보호(흔한 단어), "Curve Finance"만 보호.
        _, bare = _apply_term_overrides("the curve flattened")
        assert bare == []
        modified, full = _apply_term_overrides("Curve Finance exploit drained funds")
        assert "Curve Finance" not in modified
        assert any(kr == "Curve Finance" for _, kr in full)


class TestGetDisplayTitle:
    """Tests for get_display_title()."""

    def test_returns_ko_title_if_present(self):
        item = {"title": "Bitcoin news", "title_ko": "비트코인 뉴스"}
        assert get_display_title(item) == "비트코인 뉴스"

    def test_falls_back_to_title(self):
        item = {"title": "Bitcoin news", "title_ko": ""}
        assert get_display_title(item) == "Bitcoin news"

    def test_no_ko_key_returns_title(self):
        item = {"title": "Bitcoin news"}
        assert get_display_title(item) == "Bitcoin news"

    def test_empty_item_returns_empty(self):
        assert get_display_title({}) == ""


class TestGetDisplayDescription:
    """Tests for get_display_description()."""

    def test_returns_ko_description_if_present(self):
        item = {"description": "Bitcoin news", "description_ko": "비트코인 뉴스 설명"}
        assert get_display_description(item) == "비트코인 뉴스 설명"

    def test_falls_back_to_description(self):
        item = {"description": "Bitcoin news", "description_ko": ""}
        assert get_display_description(item) == "Bitcoin news"

    def test_no_ko_key_returns_description(self):
        item = {"description": "Some description"}
        assert get_display_description(item) == "Some description"

    def test_empty_item_returns_empty(self):
        assert get_display_description({}) == ""


class TestTranslateToKorean:
    """Tests for translate_to_korean() with mocks."""

    def test_empty_string_returned_as_is(self):
        assert translate_to_korean("") == ""
        assert translate_to_korean("   ") == "   "

    def test_translation_disabled_returns_original(self):
        with patch("common.translator.TRANSLATION_ENABLED", False):
            result = translate_to_korean("Bitcoin rises")
            assert result == "Bitcoin rises"

    def test_returns_string(self):
        # With translation disabled, just verify the return type
        with patch("common.translator.TRANSLATION_ENABLED", False):
            result = translate_to_korean("Hello world")
            assert isinstance(result, str)

    def test_cached_result_returned(self):
        test_text = "test_cached_translation_12345xyz"
        test_key = _cache_key(test_text)
        mock_cache = {test_key: "캐시된 번역 결과"}
        with (
            patch("common.translator._load_cache", return_value=mock_cache),
            patch("common.translator.TRANSLATION_ENABLED", True),
        ):
            result = translate_to_korean(test_text)
            assert result == "캐시된 번역 결과"


class TestTranslateBatch:
    """Tests for translate_batch()."""

    def test_empty_list_returns_empty(self):
        assert translate_batch([]) == []

    def test_translation_disabled_returns_originals(self):
        with patch("common.translator.TRANSLATION_ENABLED", False):
            texts = ["Bitcoin", "Ethereum", "Solana"]
            result = translate_batch(texts)
            assert result == texts

    def test_returns_list_of_same_length(self):
        with patch("common.translator.TRANSLATION_ENABLED", False):
            texts = ["a", "b", "c"]
            result = translate_batch(texts)
            assert len(result) == len(texts)

    def test_empty_strings_in_batch_unchanged(self):
        with patch("common.translator.TRANSLATION_ENABLED", False):
            texts = ["Bitcoin", "", "Ethereum"]
            result = translate_batch(texts)
            assert result[1] == ""

    def test_cached_items_returned_from_cache(self):
        text = "cached_unique_test_99999"
        key = _cache_key(text)
        mock_cache = {key: "캐시결과"}
        with (
            patch("common.translator._load_cache", return_value=mock_cache),
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._save_cache"),
        ):
            result = translate_batch([text])
            assert result[0] == "캐시결과"


class TestLoadCache:
    """Tests for _load_cache()."""

    def test_returns_dict(self, tmp_path):
        import common.translator as tr_mod

        # Reset cache to force reload by pointing to a non-existent path
        tr_mod._cache = None
        nonexistent = tmp_path / "nonexistent_cache.json"
        with patch.object(tr_mod, "_CACHE_PATH", nonexistent):
            cache = _load_cache()
        assert isinstance(cache, dict)
        tr_mod._cache = None  # cleanup

    def test_loads_valid_json_cache(self):
        import common.translator as tr_mod

        tr_mod._cache = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"abc123": "번역결과"}, f)
            tmp_path = Path(f.name)

        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            cache = _load_cache()
        assert "abc123" in cache
        tr_mod._cache = None  # cleanup
        tmp_path.unlink(missing_ok=True)

    def test_returns_empty_on_invalid_json(self):
        import common.translator as tr_mod

        tr_mod._cache = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("not valid json {{{")
            tmp_path = Path(f.name)

        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            cache = _load_cache()
        assert isinstance(cache, dict)
        tr_mod._cache = None  # cleanup
        tmp_path.unlink(missing_ok=True)

    def test_returns_cached_instance_on_second_call(self):
        import common.translator as tr_mod

        # Pre-set cache
        tr_mod._cache = {"existing": "value"}
        cache = _load_cache()
        assert cache is tr_mod._cache
        tr_mod._cache = None  # cleanup


class TestSaveCache:
    """Tests for _save_cache() and save_translation_cache()."""

    def test_no_op_when_not_dirty(self):
        import common.translator as tr_mod

        tr_mod._cache = {"key": "val"}
        tr_mod._cache_dirty = False
        # Should do nothing when not dirty
        _save_cache()  # Should not raise

    def test_saves_to_disk_when_dirty(self):
        import common.translator as tr_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "_state" / "test_cache.json"
            original_cache = tr_mod._cache
            original_dirty = tr_mod._cache_dirty

            tr_mod._cache = {"test_key": "test_value"}
            tr_mod._cache_dirty = True

            with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
                _save_cache()

            assert tmp_path.exists()
            data = json.loads(tmp_path.read_text(encoding="utf-8"))
            assert data.get("test_key") == "test_value"

            # Restore
            tr_mod._cache = original_cache
            tr_mod._cache_dirty = original_dirty

    def test_save_translation_cache_calls_save(self):
        with patch("common.translator._save_cache") as mock_save:
            save_translation_cache()
            mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Additional tests targeting missed lines
# ---------------------------------------------------------------------------


class TestLoadCacheCleaning:
    """_load_cache() cache artifact-cleaning logic (lines 176, 178-179, 181-182)."""

    def test_dirty_flag_set_when_artifacts_cleaned(self):
        """If cached entries have artifacts, _cache_dirty is set to True (line 181)."""
        import common.translator as tr_mod

        # Provide a cache entry that _postprocess_translation will change
        # "PAIrs" → "Pairs" is a known artifact fix
        dirty_cache_data = {"abc123": "PAIrs and SOLution"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(dirty_cache_data, f)
            tmp_path = Path(f.name)

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            cache = tr_mod._load_cache()

        # The artifact should have been cleaned
        assert cache["abc123"] == "Pairs and Solution"
        # _cache_dirty should be True after cleaning (line 181)
        assert tr_mod._cache_dirty is True

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        tmp_path.unlink(missing_ok=True)

    def test_cache_entry_value_replaced_after_fix(self):
        """Fixed value is stored back in cache (lines 178-179)."""
        import common.translator as tr_mod

        dirty_data = {"key1": "gAIns 상승", "key2": "정상 텍스트"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(dirty_data, f)
            tmp_path = Path(f.name)

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            cache = tr_mod._load_cache()

        assert cache["key1"] == "gains 상승"
        assert cache["key2"] == "정상 텍스트"  # unchanged entry stays

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        tmp_path.unlink(missing_ok=True)

    def test_no_dirty_flag_when_cache_is_clean(self):
        """_cache_dirty stays False when all cached values are already clean (line 180 NOT taken)."""
        import common.translator as tr_mod

        clean_data = {"k1": "정상 번역입니다", "k2": "비트코인 상승"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(clean_data, f)
            tmp_path = Path(f.name)

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            tr_mod._load_cache()

        assert tr_mod._cache_dirty is False

        tr_mod._cache = None
        tmp_path.unlink(missing_ok=True)


class TestSaveCacheEviction:
    """_save_cache() eviction and OSError handling (lines 196-200, 209-210)."""

    def test_eviction_when_over_limit(self):
        """Oldest entries evicted when cache exceeds _MAX_CACHE_ENTRIES (lines 196-200)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty
        original_max = tr_mod._MAX_CACHE_ENTRIES

        # Build a cache that exceeds the limit by 3
        limit = 10
        tr_mod._MAX_CACHE_ENTRIES = limit
        large_cache = {f"key{i:04d}": f"val{i}" for i in range(limit + 3)}
        tr_mod._cache = large_cache
        tr_mod._cache_dirty = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "_state" / "cache.json"
            with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
                tr_mod._save_cache()

            saved = json.loads(tmp_path.read_text(encoding="utf-8"))
            # After eviction exactly _MAX_CACHE_ENTRIES entries remain
            assert len(saved) == limit
            # The first 3 keys (oldest) should be gone
            assert "key0000" not in saved
            assert "key0001" not in saved
            assert "key0002" not in saved
            # Newer keys survive
            assert "key0003" in saved

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty
        tr_mod._MAX_CACHE_ENTRIES = original_max

    def test_oserror_on_save_logged_not_raised(self):
        """OSError during atomic write is caught and logged, not re-raised (lines 209-210)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty

        tr_mod._cache = {"k": "v"}
        tr_mod._cache_dirty = True

        with (
            patch("common.translator.tempfile.mkstemp", side_effect=OSError("disk full")),
            patch("common.translator._CACHE_PATH") as mock_path,
        ):
            mock_path.parent.mkdir = lambda **kw: None
            # Should NOT raise even when mkstemp fails
            tr_mod._save_cache()

        # _cache_dirty stays True since save failed
        assert tr_mod._cache_dirty is True

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty


class TestTranslateToKoreanDeepTranslator:
    """translate_to_korean() with deep_translator import path (lines 431-455)."""

    def test_successful_translation_via_deep_translator(self):
        """Happy path: deep_translator returns a string (lines 431-451)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty
        tr_mod._cache = {}
        tr_mod._cache_dirty = False

        class MockGoogleTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                return "모의 번역 결과"

        mock_module = type("deep_translator", (), {"GoogleTranslator": MockGoogleTranslator})

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch.dict("sys.modules", {"deep_translator": mock_module}),
            patch("common.translator._save_cache"),
        ):
            result = tr_mod.translate_to_korean("Bitcoin rises today")

        assert isinstance(result, str)
        # Should contain the mock translation result (term overrides applied)
        assert result != ""

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty

    def test_translation_result_cached(self):
        """Translated result is stored in cache (lines 446-449)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty
        tr_mod._cache = {}
        tr_mod._cache_dirty = False

        test_text = "unique_translate_cache_test_xyz123"

        class MockGoogleTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                return "캐시저장테스트"

        mock_module = type("deep_translator", (), {"GoogleTranslator": MockGoogleTranslator})

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch.dict("sys.modules", {"deep_translator": mock_module}),
            patch("common.translator._save_cache"),
        ):
            result = tr_mod.translate_to_korean(test_text)

        assert result == "캐시저장테스트"
        # Check cache was populated
        key = tr_mod._cache_key(test_text)
        assert tr_mod._cache.get(key) == "캐시저장테스트"
        assert tr_mod._cache_dirty is True

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty

    def test_returns_original_when_translated_is_falsy(self):
        """If translator returns None/empty, fallback to original text (line 452+)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty
        tr_mod._cache = {}
        tr_mod._cache_dirty = False

        test_text = "fallback_test_text_abc987"

        class MockGoogleTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                return None  # simulate empty result

        mock_module = type("deep_translator", (), {"GoogleTranslator": MockGoogleTranslator})

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch.dict("sys.modules", {"deep_translator": mock_module}),
        ):
            result = tr_mod.translate_to_korean(test_text)

        assert result == test_text  # fallback to original

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty

    def test_exception_during_translation_returns_original(self):
        """Exception in deep_translator is caught; returns original text (lines 452-454)."""
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty
        tr_mod._cache = {}
        tr_mod._cache_dirty = False

        test_text = "exception_fallback_test_text_999"

        class MockGoogleTranslator:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                raise RuntimeError("API error")

        mock_module = type("deep_translator", (), {"GoogleTranslator": MockGoogleTranslator})

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch.dict("sys.modules", {"deep_translator": mock_module}),
        ):
            result = tr_mod.translate_to_korean(test_text)

        assert result == test_text

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty


class TestTranslateBatchMissedLines:
    """translate_batch() missed lines: 474, 479, 485-496."""

    def test_empty_string_items_skipped(self):
        """Empty/whitespace strings are skipped (line 474)."""
        import common.translator as tr_mod

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value={}),
            patch("common.translator.translate_to_korean", side_effect=lambda t: t),
            patch("common.translator._save_cache"),
        ):
            result = tr_mod.translate_batch(["", "  ", "hello"])

        # Empty entries stay empty
        assert result[0] == ""
        assert result[1] == "  "
        assert result[2] == "hello"

    def test_cached_items_filled_from_cache(self):
        """Cached texts are resolved from cache, not re-translated (line 477)."""
        import common.translator as tr_mod

        text = "cached_batch_item"
        key = tr_mod._cache_key(text)
        mock_cache = {key: "캐시된배치항목"}

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value=mock_cache),
            patch("common.translator._save_cache"),
            patch("common.translator.translate_to_korean") as mock_t,
        ):
            result = tr_mod.translate_batch([text])

        assert result[0] == "캐시된배치항목"
        mock_t.assert_not_called()

    def test_uncached_items_appended_to_translate(self):
        """Non-cached, non-empty texts are appended to to_translate list (line 479)."""
        import common.translator as tr_mod

        texts = ["first_unique_xyz", "second_unique_xyz"]

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value={}),
            patch("common.translator._save_cache"),
            patch(
                "common.translator.translate_to_korean",
                side_effect=lambda t: f"번역_{t}",
            ),
        ):
            result = tr_mod.translate_batch(texts)

        assert result[0] == "번역_first_unique_xyz"
        assert result[1] == "번역_second_unique_xyz"

    def test_batch_processing_multiple_batches(self):
        """Processes items in batches with sleep between batches (lines 485-493)."""

        import common.translator as tr_mod

        # Create more texts than _BATCH_SIZE (5) to trigger multi-batch logic
        texts = [f"item_{i}" for i in range(7)]

        sleep_calls = []

        def fake_sleep(n):
            sleep_calls.append(n)

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value={}),
            patch("common.translator._save_cache"),
            patch(
                "common.translator.translate_to_korean",
                side_effect=lambda t: f"번_{t}",
            ),
            patch("common.translator.time.sleep", side_effect=fake_sleep),
        ):
            result = tr_mod.translate_batch(texts)

        # 7 items / batch_size 5 = 2 batches → 1 sleep between them
        assert len(sleep_calls) == 1
        assert len(result) == 7
        for i, text in enumerate(texts):
            assert result[i] == f"번_{text}"

    def test_save_cache_called_at_end(self):
        """_save_cache is called after processing all batches (line 495)."""
        import common.translator as tr_mod

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value={}),
            patch("common.translator.translate_to_korean", side_effect=lambda t: t),
            patch("common.translator._save_cache") as mock_save,
        ):
            tr_mod.translate_batch(["some_text_abc"])

        mock_save.assert_called_once()

    def test_all_cached_returns_without_translation(self):
        """If all texts are cached, to_translate is empty and returns early (line 481-482)."""
        import common.translator as tr_mod

        texts = ["cached_a", "cached_b"]
        mock_cache = {
            tr_mod._cache_key("cached_a"): "번역A",
            tr_mod._cache_key("cached_b"): "번역B",
        }

        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch("common.translator._load_cache", return_value=mock_cache),
            patch("common.translator.translate_to_korean") as mock_t,
        ):
            result = tr_mod.translate_batch(texts)

        assert result == ["번역A", "번역B"]
        mock_t.assert_not_called()


# ---------------------------------------------------------------------------
# Tests targeting the final 8 missing lines
# ---------------------------------------------------------------------------


class TestIsMojibakeEmptyPath:
    """_is_mojibake() returns False for empty/None input (line 232)."""

    def test_empty_string_returns_false(self):
        from common.translator import _is_mojibake

        assert _is_mojibake("") is False

    def test_none_returns_false(self):
        from common.translator import _is_mojibake

        assert _is_mojibake(None) is False

    def test_clean_korean_returns_false(self):
        from common.translator import _is_mojibake

        assert _is_mojibake("비트코인 상승") is False

    def test_latin1_run_returns_true(self):
        from common.translator import _is_mojibake

        # Three consecutive Latin-1 extended chars (U+00C0–U+00FF)
        assert _is_mojibake("\u00c0\u00c1\u00c2") is True


class TestLoadCacheMojibakeRemoval:
    """_load_cache() removes mojibake-corrupted entries (lines 260, 262-263)."""

    def test_mojibake_entries_removed_from_cache(self):
        import common.translator as tr_mod

        # Value containing 3+ Latin-1 extended chars = mojibake
        mojibake_value = "\u00c0\u00c1\u00c2 corrupted"
        dirty_data = {
            "good_key": "정상 번역",
            "bad_key": mojibake_value,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(dirty_data, f)
            tmp_path = Path(f.name)

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            cache = tr_mod._load_cache()

        assert "bad_key" not in cache
        assert "good_key" in cache
        assert tr_mod._cache_dirty is True

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        tmp_path.unlink(missing_ok=True)

    def test_no_mojibake_dirty_flag_stays_false(self):
        import common.translator as tr_mod

        clean_data = {"k1": "정상", "k2": "번역"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(clean_data, f)
            tmp_path = Path(f.name)

        tr_mod._cache = None
        tr_mod._cache_dirty = False
        with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
            tr_mod._load_cache()

        # No mojibake, no artifact fixes → dirty flag stays False
        assert tr_mod._cache_dirty is False

        tr_mod._cache = None
        tmp_path.unlink(missing_ok=True)


class TestSaveCacheMojibakeStripping:
    """_save_cache() strips mojibake entries inserted this session (lines 303, 305)."""

    def test_mojibake_entries_not_written_to_disk(self):
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty

        mojibake_value = "\u00c0\u00c1\u00c2 bad value"
        tr_mod._cache = {
            "good_key": "정상값",
            "bad_key": mojibake_value,
        }
        tr_mod._cache_dirty = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "_state" / "cache.json"
            with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
                tr_mod._save_cache()

            saved = json.loads(tmp_path.read_text(encoding="utf-8"))
            assert "bad_key" not in saved
            assert "good_key" in saved
            assert saved["good_key"] == "정상값"

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty

    def test_all_mojibake_cache_writes_empty_dict(self):
        import common.translator as tr_mod

        original_cache = tr_mod._cache
        original_dirty = tr_mod._cache_dirty

        tr_mod._cache = {
            "k1": "\u00c0\u00c1\u00c2\u00c3",
            "k2": "\u00d0\u00d1\u00d2\u00d3",
        }
        tr_mod._cache_dirty = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "_state" / "cache.json"
            with patch.object(tr_mod, "_CACHE_PATH", tmp_path):
                tr_mod._save_cache()

            saved = json.loads(tmp_path.read_text(encoding="utf-8"))
            assert saved == {}

        tr_mod._cache = original_cache
        tr_mod._cache_dirty = original_dirty


class TestTranslateUntranslatedBodyDisabledAndEmptyPayload:
    """translate_untranslated_body() disabled path (line 710) and empty payload skip (line 723)."""

    def test_returns_content_unchanged_when_disabled(self):
        from common.translator import translate_untranslated_body

        content = "Bitcoin rises as traders watch ETF approval news closely."
        with patch("common.translator.TRANSLATION_ENABLED", False):
            result = translate_untranslated_body(content)
        assert result == content

    def test_returns_empty_string_unchanged_when_disabled(self):
        from common.translator import translate_untranslated_body

        with patch("common.translator.TRANSLATION_ENABLED", False):
            result = translate_untranslated_body("")
        assert result == ""

    def test_line_with_only_marker_skipped(self):
        """A list marker line whose payload is empty after stripping is skipped (line 723).

        _LEADING_MARKER_RE is patched to consume the full line so that the
        payload becomes empty — the only way to reach the dead branch given
        that _should_translate_body_line already requires 4+ English words.
        """
        import re

        import common.translator as tr_mod

        # A regex that matches the ENTIRE line (greedy .*) forces payload == ""
        greedy_re = re.compile(r"^(.*)")

        content = "Bitcoin rises as traders watch market sentiment and price movements today."
        with (
            patch("common.translator.TRANSLATION_ENABLED", True),
            patch.object(tr_mod, "_LEADING_MARKER_RE", greedy_re),
            patch("common.translator.translate_batch") as mock_batch,
        ):
            result = translate_untranslated_body(content)

        # translate_batch must NOT have been called — payload was empty, line skipped
        mock_batch.assert_not_called()
        # Content is returned unchanged (no payloads collected → early return)
        assert result == content
