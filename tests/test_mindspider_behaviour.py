"""mindspider 동작 고정(behaviour-pinning) 테스트.

기존 ``tests/test_mindspider.py`` 는 ``isinstance`` / ``hasattr`` /
``in {valid_set}`` / ``> 0`` 위주라 라인은 실행하되 동작은 고정하지 못한다.
이 파일은 ``scripts/collect_coinmarketcap.py`` 가 포스트로 발행하는
토픽 요약·엔티티 리포트의 **값**을 직접 고정한다.

주의: ``_scan_text_for_entities`` 결과가 ``list(set(...))`` 를 거치므로
동률(mentions 동일) 엔티티의 **순서**는 PYTHONHASHSEED 에 따라 달라진다.
따라서 순서 대신 집합/딕셔너리 조회로 단언한다.
"""

import pytest

from common.mindspider import EntityRelation, FinancialEntity, MindSpider

# ── 테스트 전용 픽스처 ────────────────────────────────────────────────────────

# 'halving' 은 1개 문서에 3회(희소·고빈도) → TF-IDF 최상위,
# 'protocol'/'network' 는 1회씩 → 최하위. 정렬 방향이 뒤집히면 순위가 역전된다.
KEYWORD_RANK_NEWS = [
    {"title": "halving halving halving blockchain", "description": "", "category": "crypto"},
    {"title": "blockchain protocol", "description": "", "category": "crypto"},
    {"title": "blockchain network", "description": "", "category": "stocks"},
]

# 알려진 엔티티 별칭(op/ada/link/apt)이 단어 **내부**에만 나타나는 문장.
# 단어 경계가 사라지면 opinion→옵티미즘, adaptation→에이다/앱토스,
# linkedin→체인링크 로 유령 엔티티가 발행된다.
PHANTOM_ALIAS_TEXT = "Analysts published an opinion about adaptation and linkedin profiles"

# 정확히 2개 엔티티 + 관계 키워드 0개 → 기본값 AFFECTS 경로.
TWO_ENTITY_TITLE = "Bitcoin and Ethereum headline today"
TWO_ENTITY_NEWS = [{"title": TWO_ENTITY_TITLE, "description": "", "category": "crypto"}]

# OPPOSES('sue') 가 COMMENTS_ON('comment') 보다 _RELATION_KEYWORDS 에서 앞선다.
FIRST_MATCH_TITLE = "SEC sues Binance as analysts comment"
FIRST_MATCH_NEWS = [{"title": FIRST_MATCH_TITLE, "description": "", "category": "regulatory"}]

# 공유 토큰 1개(blockchain), 고유 토큰 각 5개 → jaccard = 1/11 ≈ 0.0909.
# 실제 임계값 0.15 미만이므로 별개 클러스터여야 한다.
DISJOINT_NEWS = [
    {"title": "halving mining hashrate difficulty adjustment blockchain", "description": ""},
    {"title": "dividend earnings guidance revenue buyback blockchain", "description": ""},
]


@pytest.fixture
def spider():
    return MindSpider()


# ── :618 키워드 정렬 방향 ─────────────────────────────────────────────────────


class TestKeywordRanking:
    def test_keywords_sorted_by_descending_tfidf(self, spider):
        """TF-IDF **내림차순** 고정.

        이 단언이 없으면 ``reverse=True`` 가 사라져도 통과한다 —
        발행되는 키워드 목록이 최상위가 아니라 **최하위** 토큰으로 채워져
        노이즈가 그대로 포스트에 실린다.
        """
        result = spider.extract_keywords(KEYWORD_RANK_NEWS, top_n=10)

        assert [kw["keyword"] for kw in result] == ["halving", "blockchain", "protocol", "network"]
        scores = [kw["score"] for kw in result]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] > scores[-1]

    def test_keyword_row_values_are_exact(self, spider):
        """count/score/sentiment/categories 의 실제 값 고정 (구조 검사 대체)."""
        result = spider.extract_keywords(KEYWORD_RANK_NEWS, top_n=10)
        rows = {kw["keyword"]: kw for kw in result}

        assert rows["halving"]["count"] == 3
        assert rows["halving"]["categories"] == ["crypto"]
        assert rows["halving"]["sentiment"] == "neutral"
        # blockchain 은 3개 문서 전부에 등장 → 두 카테고리 모두 수집
        assert rows["blockchain"]["count"] == 3
        assert rows["blockchain"]["categories"] == ["crypto", "stocks"]

    def test_sentiment_labels_are_value_pinned(self, spider):
        """감성 라벨을 **값**으로 고정.

        ``sentiments <= {"bullish","bearish","neutral"}`` 는 codomain 전체라
        항상 참인 항진명제다. 실제 매핑이 뒤집혀도 잡지 못한다.
        """
        news = [{"title": "Bitcoin rally crash blockchain", "description": "", "category": "crypto"}]
        rows = {kw["keyword"]: kw["sentiment"] for kw in spider.extract_keywords(news, top_n=10)}

        assert rows["rally"] == "bullish"
        assert rows["crash"] == "bearish"
        assert rows["blockchain"] == "neutral"
        assert rows["bitcoin"] == "neutral"


# ── :858 별칭 단어 경계 ───────────────────────────────────────────────────────


class TestEntityAliasWordBoundary:
    def test_substring_aliases_do_not_match(self, spider):
        """별칭은 단어 경계에서만 매칭된다.

        경계 lookbehind/lookahead 가 사라지면 opinion/adaptation/linkedin 이
        옵티미즘·에이다·앱토스·체인링크로 잡혀 엔티티 표에 유령 행이 발행된다.
        """
        lookup = spider._build_entity_lookup()
        assert spider._scan_text_for_entities(PHANTOM_ALIAS_TEXT, lookup) == []

    def test_phantom_entities_absent_from_published_path(self, spider):
        """발행 경로(extract_entities)까지 유령 엔티티가 없어야 한다."""
        result = spider.extract_entities([{"title": PHANTOM_ALIAS_TEXT, "description": ""}])
        assert result == []

    def test_real_aliases_still_match(self, spider):
        """경계 조건이 과하게 좁아지지 않았는지 반대 방향으로 확인."""
        lookup = spider._build_entity_lookup()
        found = set(spider._scan_text_for_entities("Cardano and OP rally with LINK", lookup))
        assert found == {"에이다", "옵티미즘", "체인링크"}


# ── :888 기사당 언급 중복 제거 ───────────────────────────────────────────────


class TestEntityMentionDedup:
    def test_repeated_aliases_count_once_per_article(self, spider):
        """한 기사에서 같은 엔티티는 1회만 집계된다.

        기사별 ``set()`` 중복 제거가 사라지면 별칭 수만큼 부풀려져
        (bitcoin + btc = 2회) 발행 표의 '언급' 열이 과장된다.
        """
        news = [{"title": "Bitcoin BTC bitcoin BTC news", "description": ""}]
        result = spider.extract_entities(news)

        assert [(e.name, e.mentions) for e in result] == [("비트코인", 1)]

    def test_mentions_count_articles_not_occurrences(self, spider):
        """2개 기사에 각각 여러 별칭이 나와도 언급 수는 기사 수(2)."""
        news = [
            {"title": "Bitcoin BTC surge", "description": "bitcoin btc"},
            {"title": "BTC bitcoin update", "description": "Bitcoin"},
        ]
        result = spider.extract_entities(news)
        assert [(e.name, e.mentions) for e in result] == [("비트코인", 2)]


# ── :918 / :922 stance 분기 ──────────────────────────────────────────────────


class TestEntityStance:
    def test_positive_bias_is_supportive(self, spider):
        """bullish 2 / bearish 1 → bias 0.333 → supportive.

        임계값(0.15)이 올라가면 이 종목이 'neutral' 로 발행된다.
        """
        result = spider.extract_entities([{"title": "Bitcoin rally surge crash", "description": ""}])
        assert [(e.name, e.sentiment_bias, e.stance) for e in result] == [("비트코인", 0.333, "supportive")]

    def test_negative_bias_is_opposing(self, spider):
        """bearish 2 / bullish 1 → bias -0.333 → opposing."""
        result = spider.extract_entities([{"title": "Ethereum crash dump rally", "description": ""}])
        assert [(e.name, e.sentiment_bias, e.stance) for e in result] == [("이더리움", -0.333, "opposing")]

    def test_regulator_is_observer_and_asset_is_neutral(self, spider):
        """중립 편향일 때 Regulator 는 observer, 그 외 타입은 neutral.

        ``Regulator → observer`` 매핑이 깨지면 규제기관 행의 '입장' 열이
        '관찰'이 아니라 '중립'으로 잘못 발행된다.
        """
        result = spider.extract_entities([{"title": "SEC and Solana joint statement", "description": ""}])
        by_name = {e.name: e for e in result}

        assert set(by_name) == {"SEC", "솔라나"}
        assert (by_name["SEC"].entity_type, by_name["SEC"].sentiment_bias, by_name["SEC"].stance) == (
            "Regulator",
            0.0,
            "observer",
        )
        assert (by_name["솔라나"].entity_type, by_name["솔라나"].sentiment_bias, by_name["솔라나"].stance) == (
            "Asset",
            0.0,
            "neutral",
        )


# ── :928 관련 엔티티 상위 5개 제한 ───────────────────────────────────────────


class TestRelatedEntityCap:
    def test_related_entities_capped_at_five(self, spider):
        """공동 등장 엔티티가 6개여도 상위 5개까지만 보관한다.

        ``[:5]`` 가 사라지면 관련 엔티티가 6개로 늘어 표가 넘친다.
        """
        news = [{"title": "Bitcoin Ethereum Solana Ripple Cardano Avalanche Dogecoin session", "description": ""}]
        result = spider.extract_entities(news)

        assert len(result) == 7
        for entity in result:
            # 자기 자신을 제외한 후보는 6개지만 상위 5개만 남아야 한다
            assert len(entity.related_entities) == 5
            assert entity.name not in entity.related_entities


# ── :979 / :987 / :990 / :1005 관계 감지 ─────────────────────────────────────


class TestRelationDetectionBehaviour:
    def test_two_entity_article_yields_one_relation(self, spider):
        """엔티티 2개 기사(가장 흔한 형태)는 관계를 **반드시** 생성한다.

        ``len(found) < 2`` 가 ``< 3`` 으로 바뀌면 2개짜리 기사가 전부
        건너뛰어져 발행 포스트의 '주요 관계' 블록이 통째로 비게 된다.
        """
        entities = spider.extract_entities(TWO_ENTITY_NEWS)
        result = spider.detect_relations(TWO_ENTITY_NEWS, entities)

        assert len(result) == 1
        rel = result[0]
        assert {rel.source, rel.target} == {"비트코인", "이더리움"}

    def test_unclassified_relation_defaults_to_affects(self, spider):
        """관계 키워드가 없으면 기본값은 AFFECTS.

        기본값이 바뀌면 분류되지 않은 모든 관계가 '언급' 등으로 오표기된다.
        """
        entities = spider.extract_entities(TWO_ENTITY_NEWS)
        result = spider.detect_relations(TWO_ENTITY_NEWS, entities)

        assert [r.relation_type for r in result] == ["AFFECTS"]

    def test_first_matching_relation_type_wins(self, spider):
        """복수 키워드 매칭 시 _RELATION_KEYWORDS 의 **첫** 타입이 이긴다.

        detection 루프의 ``break`` 가 사라지면 마지막 매칭이 이겨
        'SEC가 바이낸스를 제소'(OPPOSES)가 COMMENTS_ON 으로 발행된다.
        """
        entities = spider.extract_entities(FIRST_MATCH_NEWS)
        result = spider.detect_relations(FIRST_MATCH_NEWS, entities)

        assert len(result) == 1
        assert result[0].relation_type == "OPPOSES"
        assert {result[0].source, result[0].target} == {"SEC", "바이낸스"}

    def test_fact_keeps_full_title_when_short(self, spider):
        """fact 는 제목 전문을 보존한다(120자 이하).

        슬라이스 길이가 줄면 발행 불릿의 인용 근거가 토막 문자열이 된다.
        """
        entities = spider.extract_entities(TWO_ENTITY_NEWS)
        result = spider.detect_relations(TWO_ENTITY_NEWS, entities)

        assert result[0].fact == TWO_ENTITY_TITLE
        assert len(result[0].fact) == 35

    def test_fact_truncated_at_120_chars(self, spider):
        """120자 초과 제목은 정확히 120자로 잘린다."""
        long_title = "Bitcoin and Ethereum " + ("x" * 200)
        news = [{"title": long_title, "description": ""}]
        entities = spider.extract_entities(news)
        result = spider.detect_relations(news, entities)

        assert len(result) == 1
        assert result[0].fact == long_title[:120]
        assert len(result[0].fact) == 120

    def test_relation_sentiment_is_exact(self, spider):
        """관계 감성은 기사 토큰 기반 실제 값으로 고정."""
        news = [{"title": "Bitcoin Ethereum rally surge crash", "description": ""}]
        entities = spider.extract_entities(news)
        result = spider.detect_relations(news, entities)

        assert len(result) == 1
        assert result[0].sentiment == 0.333


# ── :810 / :813 시장 신호 임계값 ─────────────────────────────────────────────


class TestMarketSignalThresholds:
    def test_moderately_bullish_batch_is_bullish(self, spider):
        """점수 0.333(0.1 < s < 0.6) 배치는 bullish 로 발행된다.

        임계값이 0.6 으로 올라가면 명백히 강세인 배치가 'neutral' 로 발행된다.
        """
        result = spider.detect_market_signals([{"title": "rally surge crash", "description": ""}])

        assert result["sentiment_score"] == 0.333
        assert result["overall_sentiment"] == "bullish"
        assert result["bullish_count"] == 2
        assert result["bearish_count"] == 1
        assert result["bullish_keywords"] == ["rally", "surge"]
        assert result["bearish_keywords"] == ["crash"]

    def test_moderately_bearish_batch_is_bearish(self, spider):
        """점수 -0.333 배치는 bearish 로 발행된다."""
        result = spider.detect_market_signals([{"title": "crash dump rally", "description": ""}])

        assert result["sentiment_score"] == -0.333
        assert result["overall_sentiment"] == "bearish"
        assert result["bullish_count"] == 1
        assert result["bearish_count"] == 2

    def test_zero_score_is_neutral(self, spider):
        """강세/약세 동수(0.0)는 neutral — 임계값 부호 방향 고정."""
        result = spider.detect_market_signals([{"title": "rally crash", "description": ""}])

        assert result["sentiment_score"] == 0.0
        assert result["overall_sentiment"] == "neutral"


# ── :682 자카드 임계값 ───────────────────────────────────────────────────────


class TestClusterSeparation:
    def test_low_overlap_articles_stay_in_separate_clusters(self, spider):
        """자카드 0.0909(< 0.15) 기사쌍은 병합되지 않는다.

        임계값이 낮아지면 서로 무관한 기사가 하나의 클러스터로 뭉쳐
        '주요 토픽 분석'이 구분 없는 단일 덩어리로 발행된다.
        """
        clusters = spider.cluster_topics(DISJOINT_NEWS, max_topics=5)

        assert len(clusters) == 2
        assert [c.news_count for c in clusters] == [1, 1]
        assert {c.topic_name for c in clusters} == {"halving mining", "dividend earnings"}

    def test_high_overlap_articles_merge(self, spider):
        """반대 방향: 자카드가 충분히 높으면 실제로 병합된다."""
        news = [
            {"title": "halving mining hashrate difficulty", "description": ""},
            {"title": "halving mining hashrate adjustment", "description": ""},
        ]
        clusters = spider.cluster_topics(news, max_topics=5)

        assert len(clusters) == 1
        assert clusters[0].news_count == 2


# ── :1078 / :1097 최댓값 스캔 동률 처리 ──────────────────────────────────────


class TestMaxScanTieBreaking:
    def test_find_best_seed_keeps_first_maximum(self, spider):
        """동률일 때 **먼저** 나온 인덱스를 유지한다(``>`` 이지 ``>=`` 가 아님).

        기존 테스트는 ``best in [0, 1]`` 이라 두 동작을 모두 허용해 무력했다.
        """
        doc_sets = [{"a", "b", "c"}, {"a", "b", "d"}, {"x", "y", "z"}]
        assert spider._find_best_seed([0, 1, 2], doc_sets) == 0

    def test_find_best_seed_picks_strict_maximum(self, spider):
        """동률이 아닐 때는 중복이 가장 많은 인덱스를 고른다."""
        doc_sets = [{"x", "y"}, {"a", "b", "c"}, {"a", "b", "c"}]
        assert spider._find_best_seed([0, 1, 2], doc_sets) == 1

    def test_find_representative_keeps_first_maximum(self, spider):
        """대표 기사도 동률이면 첫 기사를 유지한다."""
        items = [{"title": "First tied title"}, {"title": "Second tied title"}]
        docs = [["alpha", "beta"], ["alpha", "beta"]]
        assert spider._find_representative(items, docs, ["alpha", "beta"]) == "First tied title"


# ── :1057 엔티티 리포트 관계 정렬 ────────────────────────────────────────────


class TestEntityReportOrdering:
    def test_relations_sorted_by_absolute_sentiment_desc(self, spider):
        """관계 불릿은 감성 절댓값 **내림차순**으로 발행된다."""
        entities = [
            FinancialEntity(
                name="SEC",
                entity_type="Regulator",
                mentions=3,
                sentiment_bias=0.0,
                stance="observer",
            )
        ]
        relations = [
            EntityRelation(source="SEC", target="바이낸스", relation_type="REGULATES", fact="weak", sentiment=0.05),
            EntityRelation(source="SEC", target="비트코인", relation_type="AFFECTS", fact="strong", sentiment=-0.9),
            EntityRelation(source="SEC", target="이더리움", relation_type="SUPPORTS", fact="middle", sentiment=0.4),
        ]

        md = spider.generate_entity_report(entities, relations)
        bullets = [line for line in md.split("\n") if line.startswith("- SEC")]

        assert bullets == [
            '- SEC --[영향]--> 비트코인 (-0.90): "strong"',
            '- SEC --[지지]--> 이더리움 (+0.40): "middle"',
            '- SEC --[규제]--> 바이낸스 (+0.05): "weak"',
        ]

    def test_entity_table_row_is_exact(self, spider):
        """엔티티 표 행 포맷(유형/언급/감성/입장 한국어 매핑) 고정."""
        entities = [
            FinancialEntity(
                name="SEC",
                entity_type="Regulator",
                mentions=3,
                sentiment_bias=-0.25,
                stance="observer",
            )
        ]
        md = spider.generate_entity_report(entities, [])

        assert "| SEC | 규제기관 | 3회 | -0.25 | 관찰 |" in md
