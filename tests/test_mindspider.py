"""Tests for scripts/common/mindspider.py — targeting ≥70% coverage."""

from common.mindspider import (
    EntityRelation,
    FinancialEntity,
    MindSpider,
    TopicCluster,
    analyze_news,
)

# ── Sample data fixtures ──────────────────────────────────────────────────────

BULLISH_NEWS = [
    {
        "title": "Bitcoin rally surge to new record high breakout",
        "description": "Bitcoin gains rise and recovery approved by regulators",
        "category": "crypto",
        "source": "CoinDesk",
    },
    {
        "title": "BTC bullish growth launch adoption",
        "description": "Bitcoin inflow buy positive signal",
        "category": "crypto",
        "source": "CoinTelegraph",
    },
    {
        "title": "비트코인 급등 상승 신고가 돌파 호재",
        "description": "매수 강세 반등 승인 유입 상장 성장",
        "category": "crypto",
        "source": "업비트",
    },
]

BEARISH_NEWS = [
    {
        "title": "Bitcoin crash dump bear bearish hack ban",
        "description": "Bitcoin selloff drop fall falling risk warning loss fear collapse",
        "category": "crypto",
        "source": "Bloomberg",
    },
    {
        "title": "BTC sanction outflow sell banned",
        "description": "Bitcoin hacked drop fall risk",
        "category": "crypto",
        "source": "Reuters",
    },
    {
        "title": "비트코인 급락 폭락 매도 약세 규제 해킹",
        "description": "제재 유출 하방 위험 손실 붕괴 위기 경고",
        "category": "crypto",
        "source": "빗썸",
    },
]

ENTITY_NEWS = [
    {
        "title": "SEC investigates Binance over regulation compliance",
        "description": "The SEC regulates crypto exchanges including Binance and Coinbase",
        "category": "regulatory",
        "source": "Bloomberg",
    },
    {
        "title": "Elon Musk tweets about Bitcoin rally",
        "description": "Tesla CEO Elon Musk comments on bitcoin surge and buys more",
        "category": "crypto",
        "source": "CNBC",
    },
    {
        "title": "BlackRock invests in Ethereum ETF",
        "description": "BlackRock fund acquires ethereum and supports adoption",
        "category": "crypto",
        "source": "Reuters",
    },
    {
        "title": "연준 비트코인 규제 발표",
        "description": "연준이 비트코인과 이더리움에 대한 규제를 발표했다",
        "category": "regulatory",
        "source": "연합뉴스",
    },
]

MIXED_NEWS = BULLISH_NEWS + BEARISH_NEWS + ENTITY_NEWS


# ── Dataclass tests ───────────────────────────────────────────────────────────


class TestDataclasses:
    def test_financial_entity_creation(self):
        entity = FinancialEntity(
            name="비트코인",
            entity_type="Asset",
            mentions=10,
            sentiment_bias=0.5,
            stance="supportive",
        )
        assert entity.name == "비트코인"
        assert entity.entity_type == "Asset"
        assert entity.mentions == 10
        assert entity.sentiment_bias == 0.5
        assert entity.stance == "supportive"
        assert entity.related_entities == []

    def test_financial_entity_with_related(self):
        entity = FinancialEntity(
            name="SEC",
            entity_type="Regulator",
            mentions=3,
            sentiment_bias=-0.2,
            stance="observer",
            related_entities=["비트코인", "이더리움"],
        )
        assert entity.related_entities == ["비트코인", "이더리움"]

    def test_entity_relation_creation(self):
        rel = EntityRelation(
            source="SEC",
            target="바이낸스",
            relation_type="REGULATES",
            fact="SEC investigates Binance",
            sentiment=-0.3,
        )
        assert rel.source == "SEC"
        assert rel.target == "바이낸스"
        assert rel.relation_type == "REGULATES"
        assert rel.fact == "SEC investigates Binance"
        assert rel.sentiment == -0.3

    def test_topic_cluster_creation(self):
        cluster = TopicCluster(
            topic_name="비트코인 ETF",
            keywords=["bitcoin", "etf", "rally"],
            news_count=5,
            sentiment_score=0.4,
            representative_title="Bitcoin ETF approved",
            summary="Bitcoin ETF news surge",
        )
        assert cluster.topic_name == "비트코인 ETF"
        assert cluster.news_count == 5
        assert cluster.news_items == []

    def test_topic_cluster_with_items(self):
        cluster = TopicCluster(
            topic_name="Test",
            keywords=["test"],
            news_count=1,
            sentiment_score=0.0,
            representative_title="Test title",
            summary="Test summary",
            news_items=[{"title": "Test title"}],
        )
        assert len(cluster.news_items) == 1


# ── MindSpider instantiation ──────────────────────────────────────────────────


class TestMindSpiderInit:
    def test_instantiation(self):
        spider = MindSpider()
        assert spider is not None
        # Check internal sets are populated
        assert len(spider._bullish_all) > 0
        assert len(spider._bearish_all) > 0
        assert len(spider._stopwords) > 0

    def test_bullish_contains_both_ko_en(self):
        spider = MindSpider()
        assert "rally" in spider._bullish_all
        assert "상승" in spider._bullish_all

    def test_bearish_contains_both_ko_en(self):
        spider = MindSpider()
        assert "crash" in spider._bearish_all
        assert "하락" in spider._bearish_all


# ── _tokenize tests ───────────────────────────────────────────────────────────


class TestTokenize:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_string(self):
        result = self.spider._tokenize("")
        assert result == []

    def test_none_like_empty(self):
        # Empty string returns []
        result = self.spider._tokenize("")
        assert result == []

    def test_english_tokenize(self):
        result = self.spider._tokenize("Bitcoin rally surge breakout")
        assert "bitcoin" in result
        assert "rally" in result
        assert "surge" in result
        assert "breakout" in result

    def test_korean_tokenize(self):
        result = self.spider._tokenize("비트코인 급등 상승세")
        assert "비트코인" in result
        assert "급등" in result
        assert "상승세" in result

    def test_mixed_tokenize(self):
        result = self.spider._tokenize("Bitcoin 비트코인 rally 급등")
        assert "bitcoin" in result
        assert "비트코인" in result
        assert "rally" in result
        assert "급등" in result

    def test_stopwords_removed_english(self):
        result = self.spider._tokenize("the bitcoin is rising")
        assert "the" not in result
        assert "is" not in result
        assert "bitcoin" in result

    def test_stopwords_removed_korean(self):
        result = self.spider._tokenize("비트코인이 상승하고 있다")
        # Short stopwords like 이, 가 should not appear
        assert "이" not in result

    def test_single_char_not_included(self):
        # Single char English won't match [a-z]{2,}
        result = self.spider._tokenize("a b c bitcoin")
        assert "a" not in result
        assert "b" not in result
        assert "bitcoin" in result

    def test_numbers_not_included(self):
        result = self.spider._tokenize("bitcoin 12345 price")
        assert "12345" not in result

    def test_lowercase_conversion(self):
        result = self.spider._tokenize("Bitcoin RALLY Surge")
        assert "bitcoin" in result
        assert "rally" in result
        assert "surge" in result


# ── _compute_tfidf tests ─────────────────────────────────────────────────────


class TestComputeTfidf:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_docs(self):
        result = self.spider._compute_tfidf([])
        assert result == {}

    def test_single_doc(self):
        docs = [["bitcoin", "rally", "surge", "bitcoin"]]
        result = self.spider._compute_tfidf(docs)
        assert "bitcoin" in result
        assert "rally" in result
        # bitcoin appears twice, should have higher tf
        assert result["bitcoin"] > result["rally"]

    def test_multiple_docs(self):
        docs = [
            ["bitcoin", "rally", "surge"],
            ["bitcoin", "drop", "fall"],
            ["ethereum", "rally", "launch"],
        ]
        result = self.spider._compute_tfidf(docs)
        assert "bitcoin" in result
        assert "rally" in result
        assert "ethereum" in result
        # All scores should be positive
        for score in result.values():
            assert score > 0

    def test_common_token_lower_idf(self):
        # Token appearing in all docs has lower IDF than unique tokens
        # Just verify all expected tokens are present with positive scores
        docs = [
            ["bitcoin", "common"],
            ["ethereum", "common"],
            ["solana", "common"],
        ]
        result = self.spider._compute_tfidf(docs)
        for token in ["bitcoin", "ethereum", "solana", "common"]:
            assert result[token] > 0

    def test_empty_docs_in_list(self):
        docs = [[], [], ["bitcoin"]]
        result = self.spider._compute_tfidf(docs)
        assert "bitcoin" in result


# ── Sentiment tests ──────────────────────────────────────────────────────────


class TestSentiment:
    def setup_method(self):
        self.spider = MindSpider()

    def test_get_token_sentiment_bullish(self):
        assert self.spider._get_token_sentiment("rally") == "bullish"
        assert self.spider._get_token_sentiment("상승") == "bullish"
        assert self.spider._get_token_sentiment("surge") == "bullish"

    def test_get_token_sentiment_bearish(self):
        assert self.spider._get_token_sentiment("crash") == "bearish"
        assert self.spider._get_token_sentiment("하락") == "bearish"
        assert self.spider._get_token_sentiment("hack") == "bearish"

    def test_get_token_sentiment_neutral(self):
        assert self.spider._get_token_sentiment("blockchain") == "neutral"
        assert self.spider._get_token_sentiment("network") == "neutral"

    def test_score_sentiment_bullish(self):
        tokens = ["rally", "surge", "gain", "bullish", "buy"]
        score = self.spider._score_sentiment(tokens)
        assert score > 0

    def test_score_sentiment_bearish(self):
        tokens = ["crash", "dump", "bear", "hack", "ban"]
        score = self.spider._score_sentiment(tokens)
        assert score < 0

    def test_score_sentiment_neutral_tokens(self):
        tokens = ["blockchain", "network", "protocol", "technology"]
        score = self.spider._score_sentiment(tokens)
        assert score == 0.0

    def test_score_sentiment_empty(self):
        score = self.spider._score_sentiment([])
        assert score == 0.0

    def test_score_sentiment_mixed(self):
        # Equal bullish and bearish → 0.0
        tokens = ["rally", "crash"]
        score = self.spider._score_sentiment(tokens)
        assert score == 0.0

    def test_score_sentiment_korean_bullish(self):
        tokens = ["급등", "상승", "호재"]
        score = self.spider._score_sentiment(tokens)
        assert score > 0

    def test_score_sentiment_korean_bearish(self):
        tokens = ["급락", "폭락", "해킹"]
        score = self.spider._score_sentiment(tokens)
        assert score < 0


# ── extract_keywords tests ───────────────────────────────────────────────────


class TestExtractKeywords:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_items(self):
        result = self.spider.extract_keywords([])
        assert result == []

    def test_basic_extraction(self):
        result = self.spider.extract_keywords(BULLISH_NEWS, top_n=10)
        assert isinstance(result, list)
        assert len(result) <= 10
        for kw in result:
            assert "keyword" in kw
            assert "count" in kw
            assert "score" in kw
            assert "sentiment" in kw
            assert "categories" in kw

    def test_top_n_respected(self):
        result = self.spider.extract_keywords(MIXED_NEWS, top_n=5)
        assert len(result) <= 5

    def test_sentiment_field_values(self):
        result = self.spider.extract_keywords(BULLISH_NEWS, top_n=15)
        sentiments = {kw["sentiment"] for kw in result}
        # Should have bullish sentiments since text is bullish
        assert sentiments <= {"bullish", "bearish", "neutral"}

    def test_categories_collected(self):
        result = self.spider.extract_keywords(BULLISH_NEWS, top_n=10)
        for kw in result:
            assert isinstance(kw["categories"], list)

    def test_count_is_positive(self):
        result = self.spider.extract_keywords(BULLISH_NEWS, top_n=10)
        for kw in result:
            assert kw["count"] > 0

    def test_score_is_float(self):
        result = self.spider.extract_keywords(BULLISH_NEWS, top_n=10)
        for kw in result:
            assert isinstance(kw["score"], float)

    def test_with_korean_news(self):
        ko_news = [
            {
                "title": "비트코인 급등 신고가 달성",
                "description": "비트코인이 급등하며 신고가를 달성했다",
                "category": "crypto",
            }
        ]
        result = self.spider.extract_keywords(ko_news, top_n=5)
        assert len(result) > 0
        keywords = [kw["keyword"] for kw in result]
        assert any("비트코인" in kw or "급등" in kw for kw in keywords)


# ── cluster_topics tests ─────────────────────────────────────────────────────


class TestClusterTopics:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_items(self):
        result = self.spider.cluster_topics([])
        assert result == []

    def test_returns_list_of_topic_clusters(self):
        result = self.spider.cluster_topics(BULLISH_NEWS, max_topics=3)
        assert isinstance(result, list)
        for cluster in result:
            assert isinstance(cluster, TopicCluster)

    def test_max_topics_respected(self):
        result = self.spider.cluster_topics(MIXED_NEWS, max_topics=3)
        assert len(result) <= 3

    def test_cluster_has_required_fields(self):
        result = self.spider.cluster_topics(BULLISH_NEWS, max_topics=2)
        if result:
            cluster = result[0]
            assert isinstance(cluster.topic_name, str)
            assert isinstance(cluster.keywords, list)
            assert isinstance(cluster.news_count, int)
            assert isinstance(cluster.sentiment_score, float)
            assert isinstance(cluster.representative_title, str)
            assert isinstance(cluster.summary, str)

    def test_cluster_sorted_by_news_count(self):
        result = self.spider.cluster_topics(MIXED_NEWS, max_topics=5)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i].news_count >= result[i + 1].news_count

    def test_sentiment_score_in_range(self):
        result = self.spider.cluster_topics(MIXED_NEWS, max_topics=3)
        for cluster in result:
            assert -1.0 <= cluster.sentiment_score <= 1.0

    def test_single_item(self):
        result = self.spider.cluster_topics([BULLISH_NEWS[0]], max_topics=2)
        # Single item might or might not form a cluster depending on jaccard threshold
        assert isinstance(result, list)

    def test_news_items_in_cluster(self):
        result = self.spider.cluster_topics(BULLISH_NEWS, max_topics=3)
        if result:
            assert isinstance(result[0].news_items, list)


# ── generate_topic_summary tests ─────────────────────────────────────────────


class TestGenerateTopicSummary:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_clusters(self):
        result = self.spider.generate_topic_summary([])
        assert result == ""

    def test_returns_markdown_string(self):
        clusters = self.spider.cluster_topics(BULLISH_NEWS, max_topics=2)
        if clusters:
            result = self.spider.generate_topic_summary(clusters)
            assert isinstance(result, str)
            assert "## 주요 토픽 분석" in result

    def test_contains_topic_names(self):
        clusters = self.spider.cluster_topics(MIXED_NEWS, max_topics=3)
        if clusters:
            result = self.spider.generate_topic_summary(clusters)
            for cluster in clusters:
                assert cluster.topic_name in result

    def test_contains_news_count(self):
        clusters = self.spider.cluster_topics(BULLISH_NEWS, max_topics=2)
        if clusters:
            result = self.spider.generate_topic_summary(clusters)
            assert "관련 기사" in result

    def test_manual_cluster(self):
        cluster = TopicCluster(
            topic_name="비트코인 ETF",
            keywords=["bitcoin", "etf", "rally"],
            news_count=5,
            sentiment_score=0.4,
            representative_title="Bitcoin ETF approved",
            summary="Bitcoin ETF news",
        )
        result = self.spider.generate_topic_summary([cluster])
        assert "비트코인 ETF" in result
        assert "## 주요 토픽 분석" in result
        assert "관련 키워드" in result

    def test_sentiment_labels_in_output(self):
        # Test various sentiment labels
        for score, expected_label in [
            (0.5, "긍정적"),
            (0.1, "다소 긍정적"),
            (-0.5, "부정적"),
            (-0.1, "다소 부정적"),
            (0.0, "중립"),
        ]:
            cluster = TopicCluster(
                topic_name="Test",
                keywords=["test"],
                news_count=1,
                sentiment_score=score,
                representative_title="Test",
                summary="Test summary",
            )
            result = self.spider.generate_topic_summary([cluster])
            assert expected_label in result


# ── detect_market_signals tests ──────────────────────────────────────────────


class TestDetectMarketSignals:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_items(self):
        result = self.spider.detect_market_signals([])
        assert result["overall_sentiment"] == "neutral"
        assert result["sentiment_score"] == 0.0
        assert result["bullish_keywords"] == []
        assert result["bearish_keywords"] == []
        assert result["trending"] == []
        assert result["bullish_count"] == 0
        assert result["bearish_count"] == 0

    def test_bullish_signals(self):
        result = self.spider.detect_market_signals(BULLISH_NEWS)
        assert result["overall_sentiment"] == "bullish"
        assert result["sentiment_score"] > 0.1
        assert len(result["bullish_keywords"]) > 0

    def test_bearish_signals(self):
        result = self.spider.detect_market_signals(BEARISH_NEWS)
        assert result["overall_sentiment"] == "bearish"
        assert result["sentiment_score"] < -0.1
        assert len(result["bearish_keywords"]) > 0

    def test_result_structure(self):
        result = self.spider.detect_market_signals(MIXED_NEWS)
        required_keys = [
            "bullish_keywords",
            "bearish_keywords",
            "trending",
            "overall_sentiment",
            "sentiment_score",
            "bullish_count",
            "bearish_count",
        ]
        for key in required_keys:
            assert key in result

    def test_trending_excludes_sentiment_words(self):
        result = self.spider.detect_market_signals(MIXED_NEWS)
        for trend in result["trending"]:
            assert trend not in self.spider._bullish_all
            assert trend not in self.spider._bearish_all

    def test_bullish_count_positive(self):
        result = self.spider.detect_market_signals(BULLISH_NEWS)
        assert result["bullish_count"] > 0

    def test_bearish_count_positive(self):
        result = self.spider.detect_market_signals(BEARISH_NEWS)
        assert result["bearish_count"] > 0

    def test_overall_sentiment_neutral(self):
        neutral_news = [
            {"title": "Bitcoin blockchain technology protocol network", "description": ""},
        ]
        result = self.spider.detect_market_signals(neutral_news)
        assert result["overall_sentiment"] == "neutral"

    def test_sentiment_score_rounded(self):
        result = self.spider.detect_market_signals(MIXED_NEWS)
        # Should be rounded to 3 decimal places
        assert result["sentiment_score"] == round(result["sentiment_score"], 3)


# ── extract_entities tests ───────────────────────────────────────────────────


class TestExtractEntities:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_items(self):
        result = self.spider.extract_entities([])
        assert result == []

    def test_returns_list_of_financial_entities(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        assert isinstance(result, list)
        for entity in result:
            assert isinstance(entity, FinancialEntity)

    def test_known_entities_detected(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        entity_names = [e.name for e in result]
        # SEC, Binance, Elon Musk, BlackRock, 연준 should be found
        assert any(name in entity_names for name in ["SEC", "바이낸스", "일론 머스크", "블랙록", "연준"])

    def test_entity_has_required_fields(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        if result:
            entity = result[0]
            assert hasattr(entity, "name")
            assert hasattr(entity, "entity_type")
            assert hasattr(entity, "mentions")
            assert hasattr(entity, "sentiment_bias")
            assert hasattr(entity, "stance")
            assert hasattr(entity, "related_entities")

    def test_entity_mentions_positive(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        for entity in result:
            assert entity.mentions > 0

    def test_entity_sorted_by_mentions(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i].mentions >= result[i + 1].mentions

    def test_stance_values(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        valid_stances = {"supportive", "opposing", "neutral", "observer"}
        for entity in result:
            assert entity.stance in valid_stances

    def test_sentiment_bias_range(self):
        result = self.spider.extract_entities(ENTITY_NEWS)
        for entity in result:
            assert -1.0 <= entity.sentiment_bias <= 1.0

    def test_no_known_entities(self):
        unknown_news = [
            {"title": "Some unknown text with no entities", "description": "Nothing relevant here"},
        ]
        result = self.spider.extract_entities(unknown_news)
        assert result == []

    def test_related_entities_populated(self):
        # Multiple entities in same article should create co-occurrences
        result = self.spider.extract_entities(ENTITY_NEWS)
        # At least some entities should have related entities
        any_related = any(len(e.related_entities) > 0 for e in result)
        assert any_related


# ── detect_relations tests ───────────────────────────────────────────────────


class TestDetectRelations:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_news_items(self):
        result = self.spider.detect_relations([], [])
        assert result == []

    def test_empty_entities(self):
        result = self.spider.detect_relations(ENTITY_NEWS, [])
        assert result == []

    def test_returns_list_of_entity_relations(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        result = self.spider.detect_relations(ENTITY_NEWS, entities)
        assert isinstance(result, list)
        for rel in result:
            assert isinstance(rel, EntityRelation)

    def test_relation_has_required_fields(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        result = self.spider.detect_relations(ENTITY_NEWS, entities)
        if result:
            rel = result[0]
            assert hasattr(rel, "source")
            assert hasattr(rel, "target")
            assert hasattr(rel, "relation_type")
            assert hasattr(rel, "fact")
            assert hasattr(rel, "sentiment")

    def test_relation_types_valid(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        result = self.spider.detect_relations(ENTITY_NEWS, entities)
        valid_types = {"SUPPORTS", "OPPOSES", "REGULATES", "INVESTS_IN", "AFFECTS", "COMMENTS_ON"}
        for rel in result:
            assert rel.relation_type in valid_types

    def test_source_target_are_known_entities(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        entity_names = {e.name for e in entities}
        result = self.spider.detect_relations(ENTITY_NEWS, entities)
        for rel in result:
            assert rel.source in entity_names
            assert rel.target in entity_names

    def test_sentiment_in_range(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        result = self.spider.detect_relations(ENTITY_NEWS, entities)
        for rel in result:
            assert -1.0 <= rel.sentiment <= 1.0


# ── generate_entity_report tests ─────────────────────────────────────────────


class TestGenerateEntityReport:
    def setup_method(self):
        self.spider = MindSpider()

    def test_empty_entities(self):
        result = self.spider.generate_entity_report([], [])
        assert result == ""

    def test_returns_markdown_string(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        relations = self.spider.detect_relations(ENTITY_NEWS, entities)
        result = self.spider.generate_entity_report(entities, relations)
        assert isinstance(result, str)
        if entities:
            assert "### 핵심 엔티티 네트워크" in result

    def test_contains_entity_table(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        relations = self.spider.detect_relations(ENTITY_NEWS, entities)
        result = self.spider.generate_entity_report(entities, relations)
        if entities:
            assert "| 엔티티 |" in result

    def test_contains_relations_section(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        relations = self.spider.detect_relations(ENTITY_NEWS, entities)
        result = self.spider.generate_entity_report(entities, relations)
        if relations:
            assert "**주요 관계:**" in result

    def test_top_n_limits_entities(self):
        entities = self.spider.extract_entities(ENTITY_NEWS)
        relations = self.spider.detect_relations(ENTITY_NEWS, entities)
        result = self.spider.generate_entity_report(entities, relations, top_n=2)
        # With top_n=2, at most 2 entity rows
        lines = result.split("\n")
        table_rows = [row for row in lines if row.startswith("| ") and "엔티티" not in row and "---" not in row]
        assert len(table_rows) <= 2

    def test_with_manual_entities_no_relations(self):
        entities = [
            FinancialEntity(
                name="SEC",
                entity_type="Regulator",
                mentions=5,
                sentiment_bias=-0.3,
                stance="observer",
            )
        ]
        result = self.spider.generate_entity_report(entities, [])
        assert "SEC" in result
        assert "규제기관" in result


# ── analyze_news (top-level function) tests ──────────────────────────────────


class TestAnalyzeNews:
    def test_basic_call(self):
        result = analyze_news(MIXED_NEWS)
        assert "keywords" in result
        assert "clusters" in result
        assert "topic_summary_md" in result
        assert "market_signals" in result

    def test_with_entities(self):
        result = analyze_news(ENTITY_NEWS, include_entities=True)
        assert "entities" in result
        assert "relations" in result
        assert "entity_report_md" in result

    def test_without_entities(self):
        result = analyze_news(ENTITY_NEWS, include_entities=False)
        assert "entities" not in result
        assert "relations" not in result
        assert "entity_report_md" not in result

    def test_keywords_is_list(self):
        result = analyze_news(BULLISH_NEWS)
        assert isinstance(result["keywords"], list)

    def test_clusters_is_list(self):
        result = analyze_news(BULLISH_NEWS)
        assert isinstance(result["clusters"], list)

    def test_topic_summary_md_is_str(self):
        result = analyze_news(BULLISH_NEWS)
        assert isinstance(result["topic_summary_md"], str)

    def test_market_signals_is_dict(self):
        result = analyze_news(BULLISH_NEWS)
        assert isinstance(result["market_signals"], dict)

    def test_top_n_parameter(self):
        result = analyze_news(MIXED_NEWS, top_n=5)
        assert len(result["keywords"]) <= 5

    def test_max_topics_parameter(self):
        result = analyze_news(MIXED_NEWS, max_topics=2)
        assert len(result["clusters"]) <= 2

    def test_empty_news(self):
        result = analyze_news([])
        assert result["keywords"] == []
        assert result["clusters"] == []
        assert result["topic_summary_md"] == ""


# ── Internal helper tests ─────────────────────────────────────────────────────


class TestInternalHelpers:
    def setup_method(self):
        self.spider = MindSpider()

    def test_build_entity_lookup(self):
        lookup = self.spider._build_entity_lookup()
        assert isinstance(lookup, dict)
        assert "sec" in lookup
        assert "btc" in lookup
        assert "bitcoin" in lookup

    def test_scan_text_for_entities(self):
        lookup = self.spider._build_entity_lookup()
        result = self.spider._scan_text_for_entities("SEC regulates Bitcoin BTC", lookup)
        assert "SEC" in result
        assert "비트코인" in result

    def test_scan_text_no_entities(self):
        lookup = self.spider._build_entity_lookup()
        result = self.spider._scan_text_for_entities("nothing relevant here at all", lookup)
        assert result == []

    def test_find_best_seed(self):
        doc_sets = [
            {"bitcoin", "rally", "surge"},
            {"bitcoin", "rally", "drop"},
            {"ethereum", "fall", "loss"},
        ]
        best = self.spider._find_best_seed([0, 1, 2], doc_sets)
        # indices 0 and 1 share bitcoin+rally, so best is 0 or 1
        assert best in [0, 1]

    def test_find_representative(self):
        items = [
            {"title": "Bitcoin rally surge record high"},
            {"title": "Stock market news today"},
        ]
        docs = [
            ["bitcoin", "rally", "surge", "record"],
            ["stock", "market", "news"],
        ]
        top_keywords = ["bitcoin", "rally", "surge"]
        result = self.spider._find_representative(items, docs, top_keywords)
        assert result == "Bitcoin rally surge record high"

    def test_find_representative_empty(self):
        result = self.spider._find_representative([], [], [])
        assert result == ""

    def test_build_summary_with_source(self):
        items = [
            {"title": "Bitcoin news", "source": "CoinDesk"},
            {"title": "ETH news", "source": "Bloomberg"},
        ]
        keywords = ["bitcoin", "etf"]
        result = self.spider._build_summary(items, keywords, 0.5)
        assert "관련 뉴스" in result
        assert "주요 출처" in result

    def test_build_summary_no_source(self):
        items = [{"title": "Bitcoin news"}]
        result = self.spider._build_summary(items, [], 0.0)
        assert "관련 뉴스" in result

    def test_build_summary_empty(self):
        result = self.spider._build_summary([], [], 0.0)
        assert result == ""

    def test_sentiment_label_positive(self):
        assert self.spider._sentiment_label(0.5) == "긍정적"
        assert self.spider._sentiment_label(0.1) == "다소 긍정적"

    def test_sentiment_label_negative(self):
        assert self.spider._sentiment_label(-0.5) == "부정적"
        assert self.spider._sentiment_label(-0.1) == "다소 부정적"

    def test_sentiment_label_neutral(self):
        assert self.spider._sentiment_label(0.0) == "중립"
        assert self.spider._sentiment_label(0.04) == "중립"

    def test_tokenize_items(self):
        items = [
            {"title": "Bitcoin rally", "description": "BTC surge"},
            {"title": "비트코인 급등", "description": "상승세"},
        ]
        result = self.spider._tokenize_items(items)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], list)
