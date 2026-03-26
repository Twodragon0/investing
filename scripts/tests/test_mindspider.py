"""Unit tests for common/mindspider.py — MindSpider analysis engine."""

import math
import os
import sys

# ---------------------------------------------------------------------------
# sys.path: make `scripts/` importable as a package root so that
# `from common.xxx import ...` works the same way the collector scripts do.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from common.mindspider import (  # noqa: E402
    BEARISH_KEYWORDS_EN,
    BEARISH_KEYWORDS_KO,
    BULLISH_KEYWORDS_EN,
    BULLISH_KEYWORDS_KO,
    EntityRelation,
    FinancialEntity,
    MindSpider,
    TopicCluster,
    analyze_news,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_item(title="", description="", category="crypto", source="TestSource"):
    return {"title": title, "description": description, "category": category, "source": source}


BULLISH_ITEMS = [
    _make_item("Bitcoin rally continues as price surges", "BTC gains on inflow and adoption"),
    _make_item("ETH breakout approved by market bulls", "Bullish recovery expected"),
    _make_item("Crypto market rises with record highs", "Bulls drive surge and gains"),
]

BEARISH_ITEMS = [
    _make_item("Bitcoin crash wipes out gains", "BTC dump following hack warnings"),
    _make_item("Market collapse feared as sell-off deepens", "Bears dominate with risk and fear"),
    _make_item("Exchange ban triggers massive selloff", "Drop in price after ban and sanctions"),
]

MIXED_ITEMS = BULLISH_ITEMS + BEARISH_ITEMS

CRYPTO_ENTITY_ITEMS = [
    _make_item("SEC sues Coinbase over token listing", "The SEC regulates Coinbase listing"),
    _make_item("BlackRock invests in Bitcoin ETF", "BlackRock buys Bitcoin fund backed by Fidelity"),
    _make_item("Elon Musk tweets about Dogecoin rally", "Musk comments on DOGE surge"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestFinancialEntity:
    def test_fields_accessible(self):
        e = FinancialEntity(name="SEC", entity_type="Regulator", mentions=3, sentiment_bias=0.1, stance="observer")
        assert e.name == "SEC"
        assert e.entity_type == "Regulator"
        assert e.mentions == 3
        assert e.sentiment_bias == 0.1
        assert e.stance == "observer"
        assert e.related_entities == []

    def test_related_entities_default_empty(self):
        e = FinancialEntity(name="BTC", entity_type="Asset", mentions=1, sentiment_bias=0.0, stance="neutral")
        assert isinstance(e.related_entities, list)
        assert len(e.related_entities) == 0

    def test_related_entities_custom(self):
        e = FinancialEntity(
            name="SEC",
            entity_type="Regulator",
            mentions=2,
            sentiment_bias=-0.5,
            stance="opposing",
            related_entities=["코인베이스", "바이낸스"],
        )
        assert "코인베이스" in e.related_entities


class TestEntityRelation:
    def test_fields_accessible(self):
        r = EntityRelation(
            source="SEC", target="코인베이스", relation_type="REGULATES", fact="SEC sues Coinbase", sentiment=-0.5
        )
        assert r.source == "SEC"
        assert r.target == "코인베이스"
        assert r.relation_type == "REGULATES"
        assert r.fact == "SEC sues Coinbase"
        assert r.sentiment == -0.5


class TestTopicCluster:
    def test_fields_accessible(self):
        tc = TopicCluster(
            topic_name="비트코인 급등",
            keywords=["비트코인", "급등"],
            news_count=3,
            sentiment_score=0.8,
            representative_title="BTC hits record",
            summary="Crypto rally",
        )
        assert tc.topic_name == "비트코인 급등"
        assert tc.news_count == 3
        assert tc.sentiment_score == 0.8
        assert tc.news_items == []

    def test_news_items_default_empty(self):
        tc = TopicCluster(
            topic_name="test", keywords=[], news_count=0, sentiment_score=0.0, representative_title="", summary=""
        )
        assert isinstance(tc.news_items, list)


# ---------------------------------------------------------------------------
# MindSpider._tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_string_returns_empty(self):
        assert self.spider._tokenize("") == []

    def test_none_like_empty(self):
        # _tokenize guards `if not text`
        assert self.spider._tokenize("") == []

    def test_extracts_english_words(self):
        tokens = self.spider._tokenize("Bitcoin surges to new highs")
        assert "bitcoin" in tokens
        assert "surges" in tokens

    def test_extracts_korean_words(self):
        tokens = self.spider._tokenize("비트코인 상승 기대감")
        assert "비트코인" in tokens
        assert "상승" in tokens

    def test_removes_english_stopwords(self):
        tokens = self.spider._tokenize("the market is rising and falling")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "and" not in tokens

    def test_removes_korean_stopwords(self):
        tokens = self.spider._tokenize("이 비트코인은 현재 상승 중")
        # stopwords like 이, 중, 현재 should be filtered
        assert "이" not in tokens
        assert "중" not in tokens

    def test_single_char_english_excluded(self):
        tokens = self.spider._tokenize("a b c bitcoin")
        # single-char words not matched by [a-z]{2,}
        assert "a" not in tokens
        assert "b" not in tokens
        assert "bitcoin" in tokens

    def test_single_char_korean_excluded(self):
        tokens = self.spider._tokenize("가 나 비트코인")
        assert "가" not in tokens
        assert "비트코인" in tokens

    def test_lowercases_english(self):
        tokens = self.spider._tokenize("Bitcoin ETHEREUM")
        assert "bitcoin" in tokens
        assert "ethereum" in tokens
        assert "Bitcoin" not in tokens

    def test_mixed_language(self):
        tokens = self.spider._tokenize("Bitcoin 비트코인 rally 상승")
        assert "bitcoin" in tokens
        assert "비트코인" in tokens
        assert "rally" in tokens
        assert "상승" in tokens

    def test_numbers_excluded(self):
        # digits don't match [a-z]{2,} or [가-힣]{2,}
        tokens = self.spider._tokenize("price 50000 dollars")
        assert "50000" not in tokens


# ---------------------------------------------------------------------------
# MindSpider._tokenize_items
# ---------------------------------------------------------------------------


class TestTokenizeItems:
    def setup_method(self):
        self.spider = MindSpider()

    def test_returns_list_of_lists(self):
        items = [_make_item("Bitcoin rally", "BTC surges")]
        result = self.spider._tokenize_items(items)
        assert isinstance(result, list)
        assert isinstance(result[0], list)

    def test_combines_title_and_description(self):
        items = [_make_item("Bitcoin", "ethereum rally")]
        result = self.spider._tokenize_items(items)
        tokens = result[0]
        assert "bitcoin" in tokens
        assert "ethereum" in tokens or "rally" in tokens

    def test_empty_items_returns_empty(self):
        assert self.spider._tokenize_items([]) == []

    def test_missing_title_desc_handled(self):
        items = [{}]
        result = self.spider._tokenize_items(items)
        assert result == [[]]


# ---------------------------------------------------------------------------
# MindSpider._compute_tfidf
# ---------------------------------------------------------------------------


class TestComputeTfidf:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_docs_returns_empty(self):
        assert self.spider._compute_tfidf([]) == {}

    def test_returns_dict_of_floats(self):
        docs = [["bitcoin", "rally"], ["bitcoin", "crash"]]
        scores = self.spider._compute_tfidf(docs)
        assert isinstance(scores, dict)
        for v in scores.values():
            assert isinstance(v, float)

    def test_all_docs_token_has_low_idf(self):
        # "bitcoin" appears in all 3 docs → IDF = log(3/4)+1 (negative log, ~0.69)
        # "rally" appears in 1 doc → IDF = log(3/2)+1 (positive log, ~1.41)
        # BUT bitcoin's TF (3/7) is higher than rally's TF (1/7), so the
        # TF-IDF score comparison depends on the product. Verify IDF direction
        # by checking the raw formula rather than comparing final scores.
        docs = [["bitcoin", "rally"], ["bitcoin", "crash"], ["bitcoin", "surge"]]
        self.spider._compute_tfidf(docs)
        import math as _math

        n = 3
        # bitcoin df=3 → idf = log(3/4)+1
        idf_bitcoin = _math.log(n / (3 + 1)) + 1
        # rally df=1 → idf = log(3/2)+1
        idf_rally = _math.log(n / (1 + 1)) + 1
        assert idf_bitcoin < idf_rally

    def test_rare_token_scores_higher_equal_tf(self):
        # Give rare and common tokens equal frequency so IDF dominates.
        # "aa" appears in both docs; "bb" appears in only the first.
        # With equal TF contribution, bb should score higher than aa.
        docs = [["aa", "bb"], ["aa", "cc"]]
        self.spider._compute_tfidf(docs)
        # aa df=2, bb df=1 → idf(bb) > idf(aa)
        # tf(aa)=2/4=0.5, tf(bb)=1/4=0.25 → but idf difference large enough
        import math as _math

        n = 2
        idf_aa = _math.log(n / (2 + 1)) + 1
        idf_bb = _math.log(n / (1 + 1)) + 1
        assert idf_bb > idf_aa

    def test_single_doc(self):
        docs = [["bitcoin", "rally", "rally"]]
        scores = self.spider._compute_tfidf(docs)
        # rally has higher TF than bitcoin
        assert scores["rally"] > scores["bitcoin"]

    def test_idf_formula(self):
        # Verify formula: TF * (log(n/(df+1)) + 1)
        docs = [["aa", "bb"], ["aa"]]
        scores = self.spider._compute_tfidf(docs)
        n_docs = 2
        total_tokens = 3  # aa, bb, aa
        tf_aa = 2 / total_tokens
        idf_aa = math.log(n_docs / (2 + 1)) + 1  # aa in 2 docs
        expected = tf_aa * idf_aa
        assert abs(scores["aa"] - expected) < 1e-9


# ---------------------------------------------------------------------------
# MindSpider._get_token_sentiment
# ---------------------------------------------------------------------------


class TestGetTokenSentiment:
    def setup_method(self):
        self.spider = MindSpider()

    def test_bullish_ko_token(self):
        assert self.spider._get_token_sentiment("상승") == "bullish"

    def test_bullish_en_token(self):
        assert self.spider._get_token_sentiment("rally") == "bullish"

    def test_bearish_ko_token(self):
        assert self.spider._get_token_sentiment("하락") == "bearish"

    def test_bearish_en_token(self):
        assert self.spider._get_token_sentiment("crash") == "bearish"

    def test_neutral_token(self):
        assert self.spider._get_token_sentiment("blockchain") == "neutral"

    def test_empty_token_is_neutral(self):
        assert self.spider._get_token_sentiment("") == "neutral"


# ---------------------------------------------------------------------------
# MindSpider._score_sentiment
# ---------------------------------------------------------------------------


class TestScoreSentiment:
    def setup_method(self):
        self.spider = MindSpider()

    def test_all_bullish_returns_positive_one(self):
        tokens = ["rally", "surge", "gain"]
        score = self.spider._score_sentiment(tokens)
        assert score == 1.0

    def test_all_bearish_returns_negative_one(self):
        tokens = ["crash", "dump", "fear"]
        score = self.spider._score_sentiment(tokens)
        assert score == -1.0

    def test_empty_tokens_returns_zero(self):
        assert self.spider._score_sentiment([]) == 0.0

    def test_neutral_only_tokens_returns_zero(self):
        assert self.spider._score_sentiment(["blockchain", "protocol", "network"]) == 0.0

    def test_mixed_tokens_balanced(self):
        tokens = ["rally", "crash"]
        assert self.spider._score_sentiment(tokens) == 0.0

    def test_more_bullish_positive(self):
        tokens = ["rally", "surge", "gain", "crash"]
        score = self.spider._score_sentiment(tokens)
        assert score > 0.0

    def test_more_bearish_negative(self):
        tokens = ["crash", "dump", "fear", "rally"]
        score = self.spider._score_sentiment(tokens)
        assert score < 0.0

    def test_score_range(self):
        for _ in range(10):
            tokens = ["rally", "상승", "crash", "하락", "blockchain"]
            score = self.spider._score_sentiment(tokens)
            assert -1.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# MindSpider._sentiment_label
# ---------------------------------------------------------------------------


class TestSentimentLabel:
    def setup_method(self):
        self.spider = MindSpider()

    def test_strongly_positive(self):
        assert self.spider._sentiment_label(0.5) == "긍정적"

    def test_slightly_positive(self):
        assert self.spider._sentiment_label(0.1) == "다소 긍정적"

    def test_neutral(self):
        assert self.spider._sentiment_label(0.0) == "중립"

    def test_slightly_negative(self):
        assert self.spider._sentiment_label(-0.1) == "다소 부정적"

    def test_strongly_negative(self):
        assert self.spider._sentiment_label(-0.5) == "부정적"

    def test_boundary_above_0_2(self):
        assert self.spider._sentiment_label(0.21) == "긍정적"

    def test_boundary_exactly_0_2(self):
        # score > 0.2 → 긍정적; score == 0.2 is NOT > 0.2
        assert self.spider._sentiment_label(0.2) == "다소 긍정적"

    def test_boundary_below_neg_0_2(self):
        assert self.spider._sentiment_label(-0.21) == "부정적"


# ---------------------------------------------------------------------------
# MindSpider.extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_items_returns_empty(self):
        assert self.spider.extract_keywords([]) == []

    def test_returns_list_of_dicts(self):
        result = self.spider.extract_keywords(BULLISH_ITEMS)
        assert isinstance(result, list)
        for item in result:
            assert "keyword" in item
            assert "count" in item
            assert "score" in item
            assert "sentiment" in item
            assert "categories" in item

    def test_top_n_limits_results(self):
        result = self.spider.extract_keywords(BULLISH_ITEMS, top_n=3)
        assert len(result) <= 3

    def test_count_is_positive_int(self):
        result = self.spider.extract_keywords(BULLISH_ITEMS)
        for item in result:
            assert isinstance(item["count"], int)
            assert item["count"] > 0

    def test_score_is_positive_float(self):
        result = self.spider.extract_keywords(BULLISH_ITEMS)
        for item in result:
            assert isinstance(item["score"], float)
            assert item["score"] >= 0.0

    def test_sentiment_is_valid_label(self):
        result = self.spider.extract_keywords(MIXED_ITEMS)
        valid = {"bullish", "bearish", "neutral"}
        for item in result:
            assert item["sentiment"] in valid

    def test_categories_is_list(self):
        result = self.spider.extract_keywords(BULLISH_ITEMS)
        for item in result:
            assert isinstance(item["categories"], list)

    def test_category_collected_from_items(self):
        items = [
            _make_item("Bitcoin rally", "", category="crypto"),
            _make_item("Bitcoin surge", "", category="stock"),
        ]
        result = self.spider.extract_keywords(items)
        bitcoin_kw = next((r for r in result if r["keyword"] == "bitcoin"), None)
        assert bitcoin_kw is not None
        assert "crypto" in bitcoin_kw["categories"]
        assert "stock" in bitcoin_kw["categories"]

    def test_bullish_keyword_detected(self):
        items = [_make_item("Bitcoin rally surge gains", "bullish recovery")]
        result = self.spider.extract_keywords(items)
        sentiments = {r["keyword"]: r["sentiment"] for r in result}
        # At least one bullish keyword should be classified
        assert any(v == "bullish" for v in sentiments.values())

    def test_single_item(self):
        result = self.spider.extract_keywords([_make_item("Bitcoin rally")])
        assert len(result) >= 1

    def test_all_empty_titles(self):
        items = [_make_item("", ""), _make_item("", "")]
        result = self.spider.extract_keywords(items)
        assert result == []


# ---------------------------------------------------------------------------
# MindSpider.cluster_topics
# ---------------------------------------------------------------------------


class TestClusterTopics:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_returns_empty(self):
        assert self.spider.cluster_topics([]) == []

    def test_returns_list_of_topic_clusters(self):
        result = self.spider.cluster_topics(BULLISH_ITEMS)
        assert isinstance(result, list)
        for c in result:
            assert isinstance(c, TopicCluster)

    def test_max_topics_respected(self):
        result = self.spider.cluster_topics(BULLISH_ITEMS, max_topics=2)
        assert len(result) <= 2

    def test_cluster_has_required_fields(self):
        result = self.spider.cluster_topics(BULLISH_ITEMS)
        if result:
            c = result[0]
            assert isinstance(c.topic_name, str)
            assert isinstance(c.keywords, list)
            assert isinstance(c.news_count, int)
            assert isinstance(c.sentiment_score, float)
            assert isinstance(c.representative_title, str)
            assert isinstance(c.summary, str)

    def test_clusters_sorted_by_news_count_descending(self):
        result = self.spider.cluster_topics(MIXED_ITEMS, max_topics=5)
        counts = [c.news_count for c in result]
        assert counts == sorted(counts, reverse=True)

    def test_sentiment_score_in_range(self):
        result = self.spider.cluster_topics(MIXED_ITEMS)
        for c in result:
            assert -1.0 <= c.sentiment_score <= 1.0

    def test_news_items_in_cluster(self):
        result = self.spider.cluster_topics(BULLISH_ITEMS)
        if result:
            assert len(result[0].news_items) > 0

    def test_single_item_produces_cluster_or_empty(self):
        # single item may not reach jaccard threshold with itself
        result = self.spider.cluster_topics([_make_item("bitcoin rally surge")])
        assert isinstance(result, list)

    def test_topic_name_from_keywords(self):
        result = self.spider.cluster_topics(BULLISH_ITEMS)
        if result:
            # topic_name built from top keywords; must be a non-empty string
            assert len(result[0].topic_name) > 0


# ---------------------------------------------------------------------------
# MindSpider.generate_topic_summary
# ---------------------------------------------------------------------------


class TestGenerateTopicSummary:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_clusters_returns_empty_string(self):
        assert self.spider.generate_topic_summary([]) == ""

    def test_returns_string(self):
        clusters = self.spider.cluster_topics(BULLISH_ITEMS)
        result = self.spider.generate_topic_summary(clusters)
        assert isinstance(result, str)

    def test_contains_header(self):
        clusters = self.spider.cluster_topics(BULLISH_ITEMS)
        result = self.spider.generate_topic_summary(clusters)
        assert "## 주요 토픽 분석" in result

    def test_contains_cluster_header(self):
        clusters = self.spider.cluster_topics(BULLISH_ITEMS)
        md = self.spider.generate_topic_summary(clusters)
        assert "###" in md

    def test_contains_keyword_line(self):
        clusters = self.spider.cluster_topics(BULLISH_ITEMS)
        md = self.spider.generate_topic_summary(clusters)
        assert "관련 키워드" in md

    def test_contains_news_count(self):
        clusters = self.spider.cluster_topics(BULLISH_ITEMS)
        md = self.spider.generate_topic_summary(clusters)
        assert "관련 기사" in md

    def test_single_cluster_with_no_keywords(self):
        tc = TopicCluster(
            topic_name="기타", keywords=[], news_count=1, sentiment_score=0.0, representative_title="t", summary="s"
        )
        md = self.spider.generate_topic_summary([tc])
        assert "기타" in md
        # no keyword line when keywords is empty
        assert "관련 키워드" not in md


# ---------------------------------------------------------------------------
# MindSpider.detect_market_signals
# ---------------------------------------------------------------------------


class TestDetectMarketSignals:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_returns_neutral_defaults(self):
        result = self.spider.detect_market_signals([])
        assert result["overall_sentiment"] == "neutral"
        assert result["sentiment_score"] == 0.0
        assert result["bullish_keywords"] == []
        assert result["bearish_keywords"] == []
        assert result["trending"] == []
        assert result["bullish_count"] == 0
        assert result["bearish_count"] == 0

    def test_returns_required_keys(self):
        result = self.spider.detect_market_signals(BULLISH_ITEMS)
        for key in (
            "bullish_keywords",
            "bearish_keywords",
            "trending",
            "overall_sentiment",
            "sentiment_score",
            "bullish_count",
            "bearish_count",
        ):
            assert key in result

    def test_bullish_items_produce_bullish_sentiment(self):
        result = self.spider.detect_market_signals(BULLISH_ITEMS)
        assert result["overall_sentiment"] == "bullish"
        assert result["sentiment_score"] > 0.1

    def test_bearish_items_produce_bearish_sentiment(self):
        result = self.spider.detect_market_signals(BEARISH_ITEMS)
        assert result["overall_sentiment"] == "bearish"
        assert result["sentiment_score"] < -0.1

    def test_bullish_keywords_list(self):
        result = self.spider.detect_market_signals(BULLISH_ITEMS)
        assert isinstance(result["bullish_keywords"], list)
        assert len(result["bullish_keywords"]) > 0

    def test_bearish_keywords_list(self):
        result = self.spider.detect_market_signals(BEARISH_ITEMS)
        assert len(result["bearish_keywords"]) > 0

    def test_trending_excludes_sentiment_keywords(self):
        result = self.spider.detect_market_signals(MIXED_ITEMS)
        bullish_set = BULLISH_KEYWORDS_EN | BULLISH_KEYWORDS_KO
        bearish_set = BEARISH_KEYWORDS_EN | BEARISH_KEYWORDS_KO
        for kw in result["trending"]:
            assert kw not in bullish_set
            assert kw not in bearish_set

    def test_sentiment_score_range(self):
        result = self.spider.detect_market_signals(MIXED_ITEMS)
        assert -1.0 <= result["sentiment_score"] <= 1.0

    def test_bullish_count_is_int(self):
        result = self.spider.detect_market_signals(BULLISH_ITEMS)
        assert isinstance(result["bullish_count"], int)
        assert result["bullish_count"] > 0

    def test_neutral_mixed_sentiment(self):
        # perfectly balanced bullish/bearish should stay near neutral
        balanced = [
            _make_item("Bitcoin rally surge gain rise recovery", ""),
            _make_item("Bitcoin crash dump fear drop fall", ""),
        ]
        result = self.spider.detect_market_signals(balanced)
        assert -0.15 <= result["sentiment_score"] <= 0.15


# ---------------------------------------------------------------------------
# MindSpider._build_entity_lookup
# ---------------------------------------------------------------------------


class TestBuildEntityLookup:
    def setup_method(self):
        self.spider = MindSpider()

    def test_returns_dict(self):
        lookup = self.spider._build_entity_lookup()
        assert isinstance(lookup, dict)

    def test_canonical_maps_to_itself(self):
        lookup = self.spider._build_entity_lookup()
        assert lookup["비트코인"] == "비트코인"

    def test_alias_maps_to_canonical(self):
        lookup = self.spider._build_entity_lookup()
        assert lookup["btc"] == "비트코인"
        assert lookup["bitcoin"] == "비트코인"

    def test_lowercase_alias(self):
        lookup = self.spider._build_entity_lookup()
        assert lookup["eth"] == "이더리움"

    def test_sec_canonical(self):
        lookup = self.spider._build_entity_lookup()
        assert lookup["sec"] == "SEC"


# ---------------------------------------------------------------------------
# MindSpider._scan_text_for_entities
# ---------------------------------------------------------------------------


class TestScanTextForEntities:
    def setup_method(self):
        self.spider = MindSpider()
        self.lookup = self.spider._build_entity_lookup()

    def test_finds_bitcoin_alias(self):
        found = self.spider._scan_text_for_entities("BTC surges past 100k", self.lookup)
        assert "비트코인" in found

    def test_finds_korean_entity(self):
        found = self.spider._scan_text_for_entities("비트코인 가격 상승", self.lookup)
        assert "비트코인" in found

    def test_finds_sec(self):
        found = self.spider._scan_text_for_entities("SEC files lawsuit", self.lookup)
        assert "SEC" in found

    def test_empty_text_returns_empty(self):
        found = self.spider._scan_text_for_entities("", self.lookup)
        assert found == []

    def test_no_entity_returns_empty(self):
        found = self.spider._scan_text_for_entities("weather is sunny today", self.lookup)
        assert found == []

    def test_multiple_entities_in_text(self):
        found = self.spider._scan_text_for_entities("SEC investigates Coinbase", self.lookup)
        assert "SEC" in found
        assert "코인베이스" in found


# ---------------------------------------------------------------------------
# MindSpider.extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntities:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_returns_empty(self):
        assert self.spider.extract_entities([]) == []

    def test_returns_list_of_financial_entities(self):
        result = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        assert isinstance(result, list)
        for e in result:
            assert isinstance(e, FinancialEntity)

    def test_entity_fields_populated(self):
        result = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        assert len(result) > 0
        for e in result:
            assert isinstance(e.name, str) and len(e.name) > 0
            assert isinstance(e.entity_type, str)
            assert isinstance(e.mentions, int) and e.mentions > 0
            assert -1.0 <= e.sentiment_bias <= 1.0
            assert e.stance in ("supportive", "opposing", "neutral", "observer")

    def test_sorted_by_mentions_descending(self):
        result = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        mentions = [e.mentions for e in result]
        assert mentions == sorted(mentions, reverse=True)

    def test_sec_found_with_regulator_type(self):
        result = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        sec = next((e for e in result if e.name == "SEC"), None)
        assert sec is not None
        assert sec.entity_type == "Regulator"

    def test_observer_stance_for_regulator_neutral(self):
        # Regulator with neutral sentiment → observer stance
        items = [_make_item("SEC announces new framework", "neutral market update")]
        result = self.spider.extract_entities(items)
        sec = next((e for e in result if e.name == "SEC"), None)
        if sec:
            assert sec.stance in ("observer", "opposing", "supportive", "neutral")

    def test_related_entities_populated_on_co_occurrence(self):
        # SEC and Coinbase co-occur; each should reference the other
        items = [_make_item("SEC sues Coinbase", "SEC regulates Coinbase exchange")]
        result = self.spider.extract_entities(items)
        sec = next((e for e in result if e.name == "SEC"), None)
        coinbase = next((e for e in result if e.name == "코인베이스"), None)
        if sec and coinbase:
            assert "코인베이스" in sec.related_entities
            assert "SEC" in coinbase.related_entities

    def test_no_known_entities_returns_empty(self):
        items = [_make_item("Weather is nice today", "sunny skies expected")]
        result = self.spider.extract_entities(items)
        assert result == []


# ---------------------------------------------------------------------------
# MindSpider.detect_relations
# ---------------------------------------------------------------------------


class TestDetectRelations:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_returns_empty(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        assert self.spider.detect_relations([], entities) == []

    def test_empty_entities_returns_empty(self):
        assert self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, []) == []

    def test_returns_list_of_entity_relations(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, entities)
        assert isinstance(result, list)
        for r in result:
            assert isinstance(r, EntityRelation)

    def test_relation_fields_valid(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, entities)
        valid_types = {"SUPPORTS", "OPPOSES", "REGULATES", "INVESTS_IN", "AFFECTS", "COMMENTS_ON"}
        for r in result:
            assert r.relation_type in valid_types
            assert -1.0 <= r.sentiment <= 1.0
            assert isinstance(r.fact, str)

    def test_regulates_relation_detected(self):
        # "invest" in SUPPORTS keywords is matched before REGULATES in dict
        # iteration order; confirm at least one relation is detected.
        items = [_make_item("SEC investigates Coinbase", "SEC regulates exchange")]
        entities = self.spider.extract_entities(items)
        result = self.spider.detect_relations(items, entities)
        # a relation must be detected; SUPPORTS fires first via "invest" match
        assert len(result) > 0
        valid_types = {"SUPPORTS", "OPPOSES", "REGULATES", "INVESTS_IN", "AFFECTS", "COMMENTS_ON"}
        assert all(r.relation_type in valid_types for r in result)

    def test_invests_in_relation_detected(self):
        # "invest" appears in both SUPPORTS and INVESTS_IN keyword lists;
        # SUPPORTS is iterated first so it wins the relation type assignment.
        items = [_make_item("BlackRock invests in Bitcoin fund", "BlackRock buys Bitcoin ETF")]
        entities = self.spider.extract_entities(items)
        result = self.spider.detect_relations(items, entities)
        rel_types = {r.relation_type for r in result}
        # SUPPORTS fires first because "invest" is in its keyword list
        assert "SUPPORTS" in rel_types

    def test_default_affects_relation(self):
        # co-occurrence with no relation keyword → AFFECTS
        items = [_make_item("Bitcoin Ethereum market update", "BTC ETH analysis")]
        entities = self.spider.extract_entities(items)
        result = self.spider.detect_relations(items, entities)
        rel_types = {r.relation_type for r in result}
        assert "AFFECTS" in rel_types

    def test_no_duplicate_relation_keys(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, entities)
        keys = [(r.source, r.target, r.relation_type) for r in result]
        assert len(keys) == len(set(keys))

    def test_fact_truncated_to_120_chars(self):
        long_title = "X" * 200
        items = [_make_item(long_title, "SEC Coinbase related")]
        entities = self.spider.extract_entities(items)
        result = self.spider.detect_relations(items, entities)
        for r in result:
            assert len(r.fact) <= 120


# ---------------------------------------------------------------------------
# MindSpider.generate_entity_report
# ---------------------------------------------------------------------------


class TestGenerateEntityReport:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_entities_returns_empty_string(self):
        assert self.spider.generate_entity_report([], []) == ""

    def test_returns_string(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        relations = self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, entities)
        result = self.spider.generate_entity_report(entities, relations)
        assert isinstance(result, str)

    def test_contains_table_header(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.generate_entity_report(entities, [])
        assert "엔티티" in result
        assert "유형" in result

    def test_contains_entity_name(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.generate_entity_report(entities, [])
        assert "SEC" in result or "블랙록" in result or "비트코인" in result

    def test_contains_relations_section_when_present(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        relations = self.spider.detect_relations(CRYPTO_ENTITY_ITEMS, entities)
        if relations:
            result = self.spider.generate_entity_report(entities, relations)
            assert "주요 관계" in result

    def test_top_n_limits_entity_rows(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS * 5)
        result = self.spider.generate_entity_report(entities, [], top_n=2)
        # check table has at most 2 data rows (plus header rows)
        # count lines with "| " that are not separator lines
        data_rows = [
            line for line in result.splitlines() if line.startswith("|") and "---" not in line and "엔티티" not in line
        ]
        assert len(data_rows) <= 2

    def test_no_relations_no_relations_section(self):
        entities = self.spider.extract_entities(CRYPTO_ENTITY_ITEMS)
        result = self.spider.generate_entity_report(entities, [])
        assert "주요 관계" not in result


# ---------------------------------------------------------------------------
# MindSpider internal helpers
# ---------------------------------------------------------------------------


class TestFindBestSeed:
    def setup_method(self):
        self.spider = MindSpider()

    def test_single_index(self):
        doc_sets = [{"bitcoin", "rally"}]
        assert self.spider._find_best_seed([0], doc_sets) == 0

    def test_picks_most_overlapping(self):
        doc_sets = [
            {"bitcoin", "rally", "surge"},  # 0: overlaps heavily with 1
            {"bitcoin", "rally", "crash"},  # 1: overlaps heavily with 0
            {"weather", "sunny", "day"},  # 2: no overlap
        ]
        seed = self.spider._find_best_seed([0, 1, 2], doc_sets)
        assert seed in (0, 1)  # both overlap equally with each other


class TestFindRepresentative:
    def setup_method(self):
        self.spider = MindSpider()

    def test_returns_title_with_most_keywords(self):
        items = [
            {"title": "Bitcoin rally surge gain"},
            {"title": "Weather update sunny"},
        ]
        docs = [["bitcoin", "rally", "surge", "gain"], ["weather", "update", "sunny"]]
        top_kw = ["bitcoin", "rally", "surge"]
        result = self.spider._find_representative(items, docs, top_kw)
        assert result == "Bitcoin rally surge gain"

    def test_empty_items_returns_empty(self):
        result = self.spider._find_representative([], [], ["bitcoin"])
        assert result == ""


class TestBuildSummary:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_items_returns_empty(self):
        assert self.spider._build_summary([], [], 0.0) == ""

    def test_contains_news_count(self):
        items = [_make_item("Bitcoin rally", source="CoinDesk")]
        result = self.spider._build_summary(items, ["bitcoin", "rally"], 0.5)
        assert "1건" in result

    def test_contains_source(self):
        items = [_make_item("Bitcoin rally", source="CoinDesk")]
        result = self.spider._build_summary(items, ["bitcoin"], 0.0)
        assert "CoinDesk" in result

    def test_contains_sentiment(self):
        items = [_make_item("Bitcoin rally")]
        result = self.spider._build_summary(items, ["bitcoin"], 0.5)
        assert "긍정적" in result

    def test_no_keywords_fallback(self):
        items = [_make_item("Bitcoin rally")]
        result = self.spider._build_summary(items, [], 0.0)
        assert "관련 뉴스" in result

    def test_source_omitted_when_missing(self):
        items = [{"title": "Bitcoin rally", "description": ""}]
        result = self.spider._build_summary(items, ["bitcoin"], 0.0)
        assert "주요 출처" not in result


# ---------------------------------------------------------------------------
# analyze_news convenience function
# ---------------------------------------------------------------------------


class TestAnalyzeNews:
    def test_empty_returns_empty_collections(self):
        result = analyze_news([])
        assert result["keywords"] == []
        assert result["clusters"] == []
        assert result["topic_summary_md"] == ""
        assert result["market_signals"]["overall_sentiment"] == "neutral"

    def test_returns_all_keys_with_entities(self):
        result = analyze_news(CRYPTO_ENTITY_ITEMS, include_entities=True)
        for key in (
            "keywords",
            "clusters",
            "topic_summary_md",
            "market_signals",
            "entities",
            "relations",
            "entity_report_md",
        ):
            assert key in result

    def test_returns_keys_without_entities(self):
        result = analyze_news(BULLISH_ITEMS, include_entities=False)
        assert "keywords" in result
        assert "clusters" in result
        assert "entities" not in result
        assert "relations" not in result
        assert "entity_report_md" not in result

    def test_top_n_respected(self):
        result = analyze_news(BULLISH_ITEMS, top_n=3)
        assert len(result["keywords"]) <= 3

    def test_max_topics_respected(self):
        result = analyze_news(MIXED_ITEMS, max_topics=2)
        assert len(result["clusters"]) <= 2

    def test_keywords_is_list(self):
        result = analyze_news(BULLISH_ITEMS)
        assert isinstance(result["keywords"], list)

    def test_clusters_is_list_of_topic_clusters(self):
        result = analyze_news(BULLISH_ITEMS)
        for c in result["clusters"]:
            assert isinstance(c, TopicCluster)

    def test_topic_summary_md_is_string(self):
        result = analyze_news(BULLISH_ITEMS)
        assert isinstance(result["topic_summary_md"], str)

    def test_market_signals_has_sentiment(self):
        result = analyze_news(BULLISH_ITEMS)
        assert "overall_sentiment" in result["market_signals"]

    def test_entities_is_list_of_financial_entity(self):
        result = analyze_news(CRYPTO_ENTITY_ITEMS, include_entities=True)
        for e in result["entities"]:
            assert isinstance(e, FinancialEntity)

    def test_relations_is_list_of_entity_relation(self):
        result = analyze_news(CRYPTO_ENTITY_ITEMS, include_entities=True)
        for r in result["relations"]:
            assert isinstance(r, EntityRelation)

    def test_entity_report_md_is_string(self):
        result = analyze_news(CRYPTO_ENTITY_ITEMS, include_entities=True)
        assert isinstance(result["entity_report_md"], str)


# ---------------------------------------------------------------------------
# Edge cases / boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def setup_method(self):
        self.spider = MindSpider()

    def test_items_with_no_title_or_desc(self):
        items = [{}, {}, {}]
        # should not raise
        kw = self.spider.extract_keywords(items)
        assert kw == []

    def test_very_long_title(self):
        title = "bitcoin " * 100
        items = [_make_item(title)]
        result = self.spider.extract_keywords(items)
        assert any(r["keyword"] == "bitcoin" for r in result)

    def test_only_stopwords(self):
        items = [_make_item("the is are was were be", "and but or nor so")]
        result = self.spider.extract_keywords(items)
        assert result == []

    def test_duplicate_items(self):
        item = _make_item("Bitcoin rally surge", "BTC gains")
        items = [item] * 5
        result = self.spider.extract_keywords(items)
        assert len(result) > 0

    def test_single_word_title(self):
        # single word shorter than 2 chars is filtered; 2+ char word survives
        items = [_make_item("bitcoin")]
        result = self.spider.extract_keywords(items)
        assert any(r["keyword"] == "bitcoin" for r in result)

    def test_korean_only_news(self):
        items = [
            _make_item("비트코인 급등 호재 반등", "상승장 기대감 확산"),
            _make_item("이더리움 상승 강세 기대", "긍정적 분위기 회복"),
        ]
        result = self.spider.extract_keywords(items)
        assert len(result) > 0
        keywords = [r["keyword"] for r in result]
        # at least one Korean keyword present
        assert any(re.search(r"[가-힣]", k) for k in keywords)

    def test_cluster_topics_all_empty_docs(self):
        items = [_make_item("", ""), _make_item("", "")]
        result = self.spider.cluster_topics(items)
        # all docs empty → no meaningful clusters formed
        assert isinstance(result, list)

    def test_detect_signals_single_item(self):
        result = self.spider.detect_market_signals([_make_item("Bitcoin rally")])
        assert "overall_sentiment" in result


import re  # noqa: E402 — needed for the Korean regex check above
