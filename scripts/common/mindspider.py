"""MindSpider — 투자 뉴스 토픽/키워드 추출 모듈.

MiroFish의 MindSpider 개념에서 영감을 받아, 이미 수집된 뉴스 데이터에서
트렌딩 토픽과 키워드를 추출하고 시장 센티먼트를 분석합니다.
외부 NLP 라이브러리 없이 순수 Python으로 구현.
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from scripts.common.config import setup_logging

logger = setup_logging("mindspider")

# ── 감성 키워드 사전 ──────────────────────────────────────────────────────────

BULLISH_KEYWORDS_KO = {
    "상승",
    "급등",
    "돌파",
    "신고가",
    "호재",
    "매수",
    "강세",
    "반등",
    "승인",
    "유입",
    "상장",
    "성장",
    "확대",
    "기대",
    "긍정",
    "호황",
    "상향",
    "회복",
    "돌파구",
    "급반등",
}

BEARISH_KEYWORDS_KO = {
    "하락",
    "급락",
    "폭락",
    "매도",
    "약세",
    "규제",
    "해킹",
    "제재",
    "유출",
    "하방",
    "위험",
    "손실",
    "붕괴",
    "위기",
    "경고",
    "불안",
    "하향",
    "매물",
    "공매도",
    "금지",
}

BULLISH_KEYWORDS_EN = {
    "rally",
    "surge",
    "breakout",
    "bull",
    "bullish",
    "approval",
    "approved",
    "growth",
    "gain",
    "gains",
    "rise",
    "rising",
    "record",
    "high",
    "buy",
    "inflow",
    "adoption",
    "launch",
    "positive",
    "recovery",
}

BEARISH_KEYWORDS_EN = {
    "crash",
    "dump",
    "bear",
    "bearish",
    "hack",
    "hacked",
    "ban",
    "banned",
    "sanction",
    "outflow",
    "sell",
    "selloff",
    "drop",
    "fall",
    "falling",
    "risk",
    "warning",
    "loss",
    "fear",
    "collapse",
}

# 불용어 (한국어 + 영어)
STOPWORDS_KO = {
    "이",
    "가",
    "은",
    "는",
    "을",
    "를",
    "의",
    "에",
    "에서",
    "으로",
    "로",
    "와",
    "과",
    "도",
    "만",
    "이다",
    "있다",
    "하다",
    "되다",
    "그",
    "저",
    "것",
    "수",
    "등",
    "및",
    "또",
    "더",
    "이번",
    "지난",
    "오늘",
    "내일",
    "현재",
    "이후",
    "통해",
    "따라",
    "위해",
    "대한",
    "관련",
    "대해",
    "에게",
    "부터",
    "까지",
    "위",
    "아래",
    "사이",
    "약",
    "중",
    "전",
    "후",
    "년",
    "월",
    "일",
    "시",
    "분",
}

STOPWORDS_EN = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "about",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "from",
    "up",
    "down",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "and",
    "but",
    "or",
    "nor",
    "so",
    "yet",
    "both",
    "either",
    "neither",
    "not",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "just",
    "its",
    "it",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "they",
    "their",
    "what",
    "which",
    "who",
    "whom",
    "how",
    "when",
    "where",
    "why",
    "all",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "said",
    "says",
    "new",
}


# ── 엔티티 사전 ──────────────────────────────────────────────────────────────

# (canonical_name) -> (entity_type, [aliases...])
_KNOWN_ENTITIES: dict[str, tuple[str, list[str]]] = {
    # Asset/Currency — 상위 크립토
    "비트코인": ("Asset", ["BTC", "bitcoin", "btc"]),
    "이더리움": ("Asset", ["ETH", "ethereum", "eth"]),
    "솔라나": ("Asset", ["SOL", "solana", "sol"]),
    "리플": ("Asset", ["XRP", "ripple", "xrp"]),
    "바이낸스코인": ("Asset", ["BNB", "bnb", "binance coin"]),
    "에이다": ("Asset", ["ADA", "cardano", "ada"]),
    "아발란체": ("Asset", ["AVAX", "avalanche", "avax"]),
    "도지코인": ("Asset", ["DOGE", "dogecoin", "doge"]),
    "폴리곤": ("Asset", ["MATIC", "polygon", "matic"]),
    "체인링크": ("Asset", ["LINK", "chainlink", "link"]),
    "유니스왑": ("Asset", ["UNI", "uniswap", "uni"]),
    "라이트코인": ("Asset", ["LTC", "litecoin", "ltc"]),
    "앱토스": ("Asset", ["APT", "aptos", "apt"]),
    "수이": ("Asset", ["SUI", "sui"]),
    "아비트럼": ("Asset", ["ARB", "arbitrum", "arb"]),
    "옵티미즘": ("Asset", ["OP", "optimism"]),
    "셀레스티아": ("Asset", ["TIA", "celestia", "tia"]),
    "이더리움클래식": ("Asset", ["ETC", "ethereum classic", "etc"]),
    "비트코인캐시": ("Asset", ["BCH", "bitcoin cash", "bch"]),
    "스텔라": ("Asset", ["XLM", "stellar", "xlm"]),
    # 주요 주식/지수
    "테슬라": ("Asset", ["TSLA", "tesla", "tsla"]),
    "애플": ("Asset", ["AAPL", "apple", "aapl"]),
    "엔비디아": ("Asset", ["NVDA", "nvidia", "nvda"]),
    "마이크로소프트": ("Asset", ["MSFT", "microsoft", "msft"]),
    "구글": ("Asset", ["GOOGL", "google", "googl", "알파벳"]),
    "메타": ("Asset", ["META", "meta", "facebook", "페이스북"]),
    "아마존": ("Asset", ["AMZN", "amazon", "amzn"]),
    # Regulator
    "SEC": ("Regulator", ["미국 증권거래위원회", "securities and exchange commission"]),
    "연준": ("Regulator", ["Fed", "Federal Reserve", "FOMC", "연방준비제도", "연방준비위원회"]),
    "금감원": ("Regulator", ["금융감독원", "fss"]),
    "FSC": ("Regulator", ["금융위원회", "financial services commission"]),
    "CFTC": ("Regulator", ["상품선물거래위원회", "commodity futures trading commission"]),
    "재무부": ("Regulator", ["기획재정부", "treasury", "treasury department"]),
    "바이든": ("Regulator", ["biden", "행정부"]),
    "트럼프": ("Person", ["Trump", "도널드 트럼프", "donald trump"]),
    # Organization/Exchange
    "바이낸스": ("Exchange", ["Binance", "binance"]),
    "코인베이스": ("Exchange", ["Coinbase", "coinbase"]),
    "업비트": ("Exchange", ["Upbit", "upbit"]),
    "빗썸": ("Exchange", ["Bithumb", "bithumb"]),
    "크라켄": ("Exchange", ["Kraken", "kraken"]),
    "OKX": ("Exchange", ["okx", "okex"]),
    "바이비트": ("Exchange", ["Bybit", "bybit"]),
    "후오비": ("Exchange", ["Huobi", "huobi"]),
    "블랙록": ("Organization", ["BlackRock", "blackrock"]),
    "그레이스케일": ("Organization", ["Grayscale", "grayscale"]),
    "피델리티": ("Organization", ["Fidelity", "fidelity"]),
    "ARK": ("Organization", ["ARK Invest", "ark invest", "아크인베스트"]),
    "마이크로스트래티지": ("Organization", ["MicroStrategy", "microstrategy"]),
    "JP모건": ("Organization", ["JPMorgan", "jpmorgan", "jp morgan"]),
    "골드만삭스": ("Organization", ["Goldman Sachs", "goldman sachs"]),
    "테더": ("Organization", ["Tether", "tether", "USDT"]),
    "써클": ("Organization", ["Circle", "circle", "USDC"]),
    # Person
    "일론 머스크": ("Person", ["Elon Musk", "elon musk", "머스크", "musk"]),
    "게리 겐슬러": ("Person", ["Gary Gensler", "gary gensler", "겐슬러", "gensler"]),
    "비탈릭 부테린": ("Person", ["Vitalik Buterin", "vitalik buterin", "비탈릭", "vitalik"]),
    "사토시": ("Person", ["Satoshi Nakamoto", "satoshi", "사토시 나카모토"]),
    "마이클 세일러": ("Person", ["Michael Saylor", "michael saylor", "세일러", "saylor"]),
    "CZ": ("Person", ["창펑 자오", "Changpeng Zhao", "changpeng zhao"]),
    "샘 뱅크먼프리드": ("Person", ["Sam Bankman-Fried", "sbf", "SBF", "뱅크먼프리드"]),
    # MediaOutlet
    "CoinDesk": ("MediaOutlet", ["코인데스크", "coindesk"]),
    "Bloomberg": ("MediaOutlet", ["블룸버그", "bloomberg"]),
    "Reuters": ("MediaOutlet", ["로이터", "reuters"]),
    "CNBC": ("MediaOutlet", ["cnbc"]),
    "CoinTelegraph": ("MediaOutlet", ["코인텔레그래프", "cointelegraph"]),
    "The Block": ("MediaOutlet", ["더블록", "theblock", "the block"]),
}

# 엔티티 타입 한국어 매핑
_ENTITY_TYPE_KO: dict[str, str] = {
    "Person": "인물",
    "Organization": "기관/기업",
    "Regulator": "규제기관",
    "Asset": "자산",
    "Exchange": "거래소",
    "MediaOutlet": "미디어",
}

# 관계 감지 키워드
_RELATION_KEYWORDS: dict[str, list[str]] = {
    "SUPPORTS": ["지지", "승인", "찬성", "투자", "매수", "지원", "support", "approve", "invest", "back", "advocate"],
    "OPPOSES": ["반대", "제재", "소송", "고발", "비판", "부정", "oppose", "ban", "sue", "reject", "criticize"],
    "REGULATES": ["규제", "감독", "조사", "벌금", "규정", "단속", "regulate", "investigate", "fine", "enforce"],
    "INVESTS_IN": ["투자", "매수", "인수", "펀딩", "보유", "축적", "invest", "acquire", "fund", "buy", "hold"],
    "AFFECTS": ["영향", "변동", "충격", "파급", "촉발", "견인", "affect", "impact", "drive", "trigger", "influence"],
    "COMMENTS_ON": ["언급", "발언", "코멘트", "트윗", "성명", "발표", "mention", "comment", "tweet", "announce"],
}

# 관계 타입 한국어 매핑
_RELATION_TYPE_KO: dict[str, str] = {
    "SUPPORTS": "지지",
    "OPPOSES": "반대/제재",
    "REGULATES": "규제",
    "INVESTS_IN": "투자",
    "AFFECTS": "영향",
    "COMMENTS_ON": "언급",
}


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────


@dataclass
class FinancialEntity:
    """뉴스에서 추출된 금융 엔티티 (인물, 기관, 자산 등)."""

    name: str
    """엔티티명 (예: 'SEC', '비트코인', '일론 머스크')"""

    entity_type: str
    """Person | Organization | Regulator | Asset | Exchange | MediaOutlet"""

    mentions: int
    """언급 횟수"""

    sentiment_bias: float
    """문맥 기반 감성 편향 (-1.0 ~ 1.0)"""

    stance: str
    """supportive | opposing | neutral | observer"""

    related_entities: list[str] = field(default_factory=list)
    """공동 언급된 관련 엔티티명"""


@dataclass
class EntityRelation:
    """두 엔티티 간의 관계."""

    source: str
    """소스 엔티티"""

    target: str
    """타겟 엔티티"""

    relation_type: str
    """SUPPORTS | OPPOSES | REGULATES | INVESTS_IN | AFFECTS | COMMENTS_ON"""

    fact: str
    """관계 설명 (뉴스 제목/설명에서 추출)"""

    sentiment: float
    """관계 감성 (-1.0 ~ 1.0)"""


@dataclass
class TopicCluster:
    """관련 뉴스를 묶은 토픽 클러스터."""

    topic_name: str
    """주제명 (예: '비트코인 ETF 승인')"""

    keywords: list[str]
    """관련 키워드 목록"""

    news_count: int
    """관련 기사 수"""

    sentiment_score: float
    """감성 점수: -1.0(부정) ~ 0.0(중립) ~ 1.0(긍정)"""

    representative_title: str
    """대표 기사 제목"""

    summary: str
    """주제 요약 (1-2줄)"""

    news_items: list[dict] = field(default_factory=list, repr=False)
    """클러스터에 포함된 원본 뉴스 아이템"""


# ── MindSpider 메인 클래스 ────────────────────────────────────────────────────


class MindSpider:
    """투자 뉴스에서 토픽/키워드를 추출하는 분석 엔진.

    TF-IDF 기반 키워드 추출, 키워드 중복 기반 토픽 클러스터링,
    한국어/영어 금융 감성 분석을 수행합니다.

    사용 예시::

        spider = MindSpider()
        keywords = spider.extract_keywords(news_items, top_n=15)
        clusters = spider.cluster_topics(news_items, max_topics=5)
        summary_md = spider.generate_topic_summary(clusters)
        signals = spider.detect_market_signals(news_items)
    """

    def __init__(self) -> None:
        self._bullish_all = BULLISH_KEYWORDS_KO | BULLISH_KEYWORDS_EN
        self._bearish_all = BEARISH_KEYWORDS_KO | BEARISH_KEYWORDS_EN
        self._stopwords = STOPWORDS_KO | STOPWORDS_EN

    # ── 토크나이저 ────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        """텍스트를 토큰 리스트로 변환.

        한국어 어절 단위 + 영어 단어 단위로 분리.
        숫자 전용 토큰과 1자 이하 토큰은 제거.
        """
        if not text:
            return []

        text = text.lower()

        # 영어 단어 추출 (2자 이상)
        en_tokens = re.findall(r"[a-z]{2,}", text)

        # 한국어 토큰 추출 (2자 이상 한글)
        ko_tokens = re.findall(r"[가-힣]{2,}", text)

        tokens = en_tokens + ko_tokens
        return [t for t in tokens if t not in self._stopwords]

    def _tokenize_items(self, news_items: list[dict]) -> list[list[str]]:
        """뉴스 아이템 목록을 문서별 토큰 리스트로 변환."""
        docs = []
        for item in news_items:
            title = item.get("title", "")
            desc = item.get("description", "")
            combined = f"{title} {desc}"
            docs.append(self._tokenize(combined))
        return docs

    # ── TF-IDF 계산 ───────────────────────────────────────────────────────────

    def _compute_tfidf(self, docs: list[list[str]]) -> dict[str, float]:
        """문서 집합에서 각 토큰의 TF-IDF 점수를 계산.

        TF: 문서 전체에서 해당 토큰의 비율 (총합 정규화)
        IDF: log(총 문서 수 / 해당 토큰이 등장한 문서 수 + 1) + 1
        최종 점수 = TF * IDF (모든 문서에 걸쳐 합산)
        """
        if not docs:
            return {}

        n_docs = len(docs)

        # 전체 TF (문서 구분 없이 합산)
        total_tf: Counter = Counter()
        for doc in docs:
            total_tf.update(doc)

        # DF: 각 토큰이 등장하는 문서 수
        df: Counter = Counter()
        for doc in docs:
            for token in set(doc):
                df[token] += 1

        total_tokens = sum(total_tf.values()) or 1

        scores: dict[str, float] = {}
        for token, tf_count in total_tf.items():
            tf = tf_count / total_tokens
            idf = math.log(n_docs / (df[token] + 1)) + 1
            scores[token] = tf * idf

        return scores

    # ── 감성 판별 ─────────────────────────────────────────────────────────────

    def _get_token_sentiment(self, token: str) -> str:
        """토큰의 감성을 반환: 'bullish' | 'bearish' | 'neutral'."""
        if token in self._bullish_all:
            return "bullish"
        if token in self._bearish_all:
            return "bearish"
        return "neutral"

    def _score_sentiment(self, tokens: list[str]) -> float:
        """토큰 목록의 감성 점수 계산 (-1.0 ~ 1.0).

        bullish 토큰 수 - bearish 토큰 수를 전체 유의미 토큰 수로 나눔.
        """
        bullish = sum(1 for t in tokens if t in self._bullish_all)
        bearish = sum(1 for t in tokens if t in self._bearish_all)
        total = bullish + bearish
        if total == 0:
            return 0.0
        return (bullish - bearish) / total

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def extract_keywords(self, news_items: list[dict], top_n: int = 15) -> list[dict]:
        """뉴스 아이템에서 상위 키워드를 추출합니다.

        Args:
            news_items: 뉴스 아이템 목록. 각 아이템은
                ``title``, ``description``, ``category`` 키를 가질 수 있습니다.
            top_n: 반환할 상위 키워드 수.

        Returns:
            키워드 정보 딕셔너리 목록::

                [
                    {
                        "keyword": str,
                        "count": int,
                        "score": float,       # TF-IDF 점수
                        "sentiment": str,     # "bullish" | "bearish" | "neutral"
                        "categories": list[str],
                    },
                    ...
                ]
        """
        if not news_items:
            logger.warning("extract_keywords: 빈 뉴스 목록")
            return []

        docs = self._tokenize_items(news_items)
        tfidf_scores = self._compute_tfidf(docs)

        if not tfidf_scores:
            return []

        # 토큰별 등장 횟수
        token_counter: Counter = Counter()
        for doc in docs:
            token_counter.update(doc)

        # 토큰별 카테고리 수집
        token_categories: dict[str, set] = defaultdict(set)
        for item, doc in zip(news_items, docs, strict=False):
            cat = item.get("category", "unknown")
            for token in set(doc):
                token_categories[token].add(cat)

        # TF-IDF 점수 기준 상위 키워드 선정
        sorted_tokens = sorted(tfidf_scores.keys(), key=lambda t: tfidf_scores[t], reverse=True)

        results = []
        for token in sorted_tokens[:top_n]:
            results.append(
                {
                    "keyword": token,
                    "count": token_counter[token],
                    "score": round(tfidf_scores[token], 6),
                    "sentiment": self._get_token_sentiment(token),
                    "categories": sorted(token_categories[token]),
                }
            )

        logger.info("키워드 추출 완료: %d개 (전체 %d개 중)", len(results), len(news_items))
        return results

    def cluster_topics(self, news_items: list[dict], max_topics: int = 5) -> list[TopicCluster]:
        """뉴스 아이템을 키워드 중복도 기반으로 토픽 클러스터로 그룹화합니다.

        알고리즘:
        1. 각 뉴스 아이템의 키워드 집합 계산
        2. 가장 많은 뉴스와 키워드를 공유하는 시드를 중심으로 클러스터 형성
        3. 자카드 유사도 ≥ 0.15인 뉴스를 클러스터에 병합
        4. 클러스터 대표 키워드와 감성 점수 계산

        Args:
            news_items: 뉴스 아이템 목록.
            max_topics: 최대 클러스터(토픽) 수.

        Returns:
            :class:`TopicCluster` 목록 (뉴스 수 내림차순).
        """
        if not news_items:
            logger.warning("cluster_topics: 빈 뉴스 목록")
            return []

        docs = self._tokenize_items(news_items)

        # 각 문서를 키워드 집합으로 변환 (불용어 제거 완료된 토큰)
        doc_sets: list[set[str]] = [set(doc) for doc in docs]

        assigned = [False] * len(news_items)
        clusters: list[TopicCluster] = []

        for _ in range(max_topics):
            # 아직 미할당 아이템 중에서 시드 선택 (다른 미할당 아이템과 가장 많이 겹치는 것)
            unassigned_indices = [i for i, a in enumerate(assigned) if not a]
            if not unassigned_indices:
                break

            best_seed = self._find_best_seed(unassigned_indices, doc_sets)

            seed_keywords = doc_sets[best_seed]
            if not seed_keywords:
                assigned[best_seed] = True
                continue

            # 자카드 유사도 ≥ 0.15인 뉴스 병합
            cluster_indices = []
            for i in unassigned_indices:
                intersection = len(seed_keywords & doc_sets[i])
                union = len(seed_keywords | doc_sets[i])
                jaccard = intersection / union if union > 0 else 0.0
                if jaccard >= 0.15:
                    cluster_indices.append(i)
                    assigned[i] = True

            if not cluster_indices:
                assigned[best_seed] = True
                continue

            cluster_items = [news_items[i] for i in cluster_indices]
            cluster_docs = [docs[i] for i in cluster_indices]

            # 클러스터 공통 키워드 추출 (빈도 상위)
            cluster_token_counter: Counter = Counter()
            for doc in cluster_docs:
                cluster_token_counter.update(doc)

            top_keywords = [kw for kw, _ in cluster_token_counter.most_common(8)]

            # 감성 점수
            all_tokens: list[str] = []
            for doc in cluster_docs:
                all_tokens.extend(doc)
            sentiment_score = self._score_sentiment(all_tokens)

            # 대표 기사: 가장 많은 상위 키워드를 포함하는 기사
            representative = self._find_representative(cluster_items, cluster_docs, top_keywords)

            # 토픽명: 상위 2개 키워드로 구성
            topic_name = " ".join(top_keywords[:2]) if top_keywords else "기타"

            # 요약: 대표 기사 제목 + 감성 설명
            summary = self._build_summary(cluster_items, top_keywords, sentiment_score)

            cluster = TopicCluster(
                topic_name=topic_name,
                keywords=top_keywords,
                news_count=len(cluster_items),
                sentiment_score=round(sentiment_score, 3),
                representative_title=representative,
                summary=summary,
                news_items=cluster_items,
            )
            clusters.append(cluster)

        # 뉴스 수 내림차순 정렬
        clusters.sort(key=lambda c: c.news_count, reverse=True)
        logger.info(
            "토픽 클러스터링 완료: %d개 클러스터 (입력 %d건)",
            len(clusters),
            len(news_items),
        )
        return clusters

    def generate_topic_summary(self, clusters: list[TopicCluster]) -> str:
        """클러스터 목록으로부터 Jekyll 포스트용 마크다운 섹션을 생성합니다.

        Args:
            clusters: :meth:`cluster_topics` 반환값.

        Returns:
            마크다운 문자열. 클러스터가 없으면 빈 문자열 반환.
        """
        if not clusters:
            return ""

        lines: list[str] = ["## 주요 토픽 분석", ""]

        for idx, cluster in enumerate(clusters, 1):
            sentiment_label = self._sentiment_label(cluster.sentiment_score)
            header = f"### {idx}. {cluster.topic_name} (관련 기사 {cluster.news_count}건, {sentiment_label})"
            lines.append(header)
            lines.append(cluster.summary)
            if cluster.keywords:
                kw_str = ", ".join(cluster.keywords[:6])
                lines.append(f"**관련 키워드**: {kw_str}")
            lines.append("")

        return "\n".join(lines)

    def detect_market_signals(self, news_items: list[dict]) -> dict:
        """뉴스 아이템에서 시장 신호(bullish/bearish/trending)를 감지합니다.

        Args:
            news_items: 뉴스 아이템 목록.

        Returns:
            신호 딕셔너리::

                {
                    "bullish_keywords": list[str],   # 상승 신호 키워드 (빈도순)
                    "bearish_keywords": list[str],   # 하락 신호 키워드 (빈도순)
                    "trending": list[str],            # 감성 무관 최다 등장 키워드
                    "overall_sentiment": str,         # "bullish" | "bearish" | "neutral"
                    "sentiment_score": float,         # -1.0 ~ 1.0
                    "bullish_count": int,
                    "bearish_count": int,
                }
        """
        if not news_items:
            logger.warning("detect_market_signals: 빈 뉴스 목록")
            return {
                "bullish_keywords": [],
                "bearish_keywords": [],
                "trending": [],
                "overall_sentiment": "neutral",
                "sentiment_score": 0.0,
                "bullish_count": 0,
                "bearish_count": 0,
            }

        docs = self._tokenize_items(news_items)

        all_tokens: list[str] = []
        for doc in docs:
            all_tokens.extend(doc)

        token_counter = Counter(all_tokens)

        bullish_found: Counter = Counter()
        bearish_found: Counter = Counter()
        for token, count in token_counter.items():
            if token in self._bullish_all:
                bullish_found[token] = count
            elif token in self._bearish_all:
                bearish_found[token] = count

        sentiment_score = self._score_sentiment(all_tokens)

        if sentiment_score > 0.1:
            overall = "bullish"
        elif sentiment_score < -0.1:
            overall = "bearish"
        else:
            overall = "neutral"

        # 트렌딩: 감성 무관 상위 10개
        trending = [
            kw for kw, _ in token_counter.most_common(20) if kw not in self._bullish_all and kw not in self._bearish_all
        ][:10]

        result = {
            "bullish_keywords": [kw for kw, _ in bullish_found.most_common(10)],
            "bearish_keywords": [kw for kw, _ in bearish_found.most_common(10)],
            "trending": trending,
            "overall_sentiment": overall,
            "sentiment_score": round(sentiment_score, 3),
            "bullish_count": sum(bullish_found.values()),
            "bearish_count": sum(bearish_found.values()),
        }

        logger.info(
            "시장 신호 감지: %s (점수 %.3f), bullish=%d bearish=%d",
            overall,
            sentiment_score,
            result["bullish_count"],
            result["bearish_count"],
        )
        return result

    # ── 엔티티 추출 (MiroFish 패턴) ───────────────────────────────────────────

    def _build_entity_lookup(self) -> dict[str, str]:
        """alias → canonical_name 역방향 매핑 테이블 생성."""
        lookup: dict[str, str] = {}
        for canonical, (_, aliases) in _KNOWN_ENTITIES.items():
            lookup[canonical.lower()] = canonical
            for alias in aliases:
                lookup[alias.lower()] = canonical
        return lookup

    def _scan_text_for_entities(self, text: str, lookup: dict[str, str]) -> list[str]:
        """텍스트에서 알려진 엔티티 canonical name 목록 반환 (중복 포함)."""
        text_lower = text.lower()
        found: list[str] = []
        for alias, canonical in lookup.items():
            # 단어 경계를 고려한 매칭 (영문은 단어 단위, 한글은 포함 여부)
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", text_lower):
                found.append(canonical)
        return found

    def extract_entities(self, news_items: list[dict]) -> list[FinancialEntity]:
        """뉴스 아이템에서 금융 엔티티를 추출하고 빈도/감성을 계산합니다.

        Args:
            news_items: 뉴스 아이템 목록 (``title``, ``description`` 키 포함).

        Returns:
            :class:`FinancialEntity` 목록 (언급 횟수 내림차순).
        """
        if not news_items:
            logger.warning("extract_entities: 빈 뉴스 목록")
            return []

        lookup = self._build_entity_lookup()

        # 엔티티별 통계 수집
        entity_mentions: Counter = Counter()
        entity_sentiment_tokens: dict[str, list[str]] = defaultdict(list)
        # 엔티티가 등장한 기사 인덱스 → 함께 등장한 엔티티 추적
        article_entities: list[list[str]] = []

        for item in news_items:
            title = item.get("title", "")
            desc = item.get("description", "")
            combined = f"{title} {desc}"

            found_in_article = list(set(self._scan_text_for_entities(combined, lookup)))
            article_entities.append(found_in_article)

            for canonical in found_in_article:
                entity_mentions[canonical] += 1

            # 감성 토큰 수집 (각 엔티티에 기사 전체 토큰 귀속)
            tokens = self._tokenize(combined)
            for canonical in found_in_article:
                entity_sentiment_tokens[canonical].extend(tokens)

        if not entity_mentions:
            logger.info("extract_entities: 알려진 엔티티 없음")
            return []

        # 엔티티별 공동 언급 관계 계산
        co_occurrence: dict[str, Counter] = defaultdict(Counter)
        for entities_in_article in article_entities:
            for ent_a in entities_in_article:
                for ent_b in entities_in_article:
                    if ent_a != ent_b:
                        co_occurrence[ent_a][ent_b] += 1

        results: list[FinancialEntity] = []
        for canonical, count in entity_mentions.most_common():
            entity_type = _KNOWN_ENTITIES[canonical][0]
            tokens = entity_sentiment_tokens[canonical]
            sentiment_bias = self._score_sentiment(tokens)

            # 입장 분류
            if sentiment_bias > 0.15:
                stance = "supportive"
            elif sentiment_bias < -0.15:
                stance = "opposing"
            elif entity_type in ("Regulator",):
                stance = "observer"
            else:
                stance = "neutral"

            # 상위 5개 관련 엔티티
            related = [e for e, _ in co_occurrence[canonical].most_common(5)]

            results.append(
                FinancialEntity(
                    name=canonical,
                    entity_type=entity_type,
                    mentions=count,
                    sentiment_bias=round(sentiment_bias, 3),
                    stance=stance,
                    related_entities=related,
                )
            )

        logger.info("엔티티 추출 완료: %d개 엔티티 (입력 %d건)", len(results), len(news_items))
        return results

    def detect_relations(
        self,
        news_items: list[dict],
        entities: list[FinancialEntity],
    ) -> list[EntityRelation]:
        """뉴스 아이템에서 엔티티 간 관계를 감지합니다.

        같은 기사에 두 엔티티가 공동 등장하고,
        관계 키워드가 포함된 경우 관계로 판단합니다.

        Args:
            news_items: 뉴스 아이템 목록.
            entities: :meth:`extract_entities` 반환값.

        Returns:
            :class:`EntityRelation` 목록.
        """
        if not news_items or not entities:
            return []

        lookup = self._build_entity_lookup()
        entity_names = {e.name for e in entities}

        relations: dict[tuple[str, str, str], EntityRelation] = {}

        for item in news_items:
            title = item.get("title", "")
            desc = item.get("description", "")
            combined = f"{title} {desc}"
            combined_lower = combined.lower()

            found_in_article = list(set(self._scan_text_for_entities(combined, lookup)))
            # 알려진 엔티티만 필터링
            found_in_article = [e for e in found_in_article if e in entity_names]

            if len(found_in_article) < 2:
                continue

            # 관계 키워드 감지
            detected_relation = None
            for rel_type, keywords in _RELATION_KEYWORDS.items():
                if any(kw.lower() in combined_lower for kw in keywords):
                    detected_relation = rel_type
                    break

            if not detected_relation:
                detected_relation = "AFFECTS"  # 기본값: 공동 등장 시 영향 관계

            # 감성 계산
            tokens = self._tokenize(combined)
            sentiment = self._score_sentiment(tokens)

            # 모든 쌍에 대해 관계 추가 (첫 번째 → 두 번째)
            for i, src in enumerate(found_in_article):
                for tgt in found_in_article[i + 1 :]:
                    key = (src, tgt, detected_relation)
                    if key not in relations:
                        relations[key] = EntityRelation(
                            source=src,
                            target=tgt,
                            relation_type=detected_relation,
                            fact=title[:120],
                            sentiment=round(sentiment, 3),
                        )

        result_list = list(relations.values())
        logger.info("관계 감지 완료: %d개 관계 (입력 %d건)", len(result_list), len(news_items))
        return result_list

    def generate_entity_report(
        self,
        entities: list[FinancialEntity],
        relations: list[EntityRelation],
        top_n: int = 10,
    ) -> str:
        """엔티티와 관계 목록으로부터 Jekyll 포스트용 마크다운 섹션을 생성합니다.

        Args:
            entities: :meth:`extract_entities` 반환값.
            relations: :meth:`detect_relations` 반환값.
            top_n: 표에 표시할 최대 엔티티 수.

        Returns:
            마크다운 문자열. 엔티티가 없으면 빈 문자열 반환.
        """
        if not entities:
            return ""

        lines: list[str] = ["### 핵심 엔티티 네트워크", ""]

        # 엔티티 테이블
        lines.append("| 엔티티 | 유형 | 언급 | 감성 | 입장 |")
        lines.append("|--------|------|------|------|------|")

        stance_ko = {
            "supportive": "긍정",
            "opposing": "부정",
            "neutral": "중립",
            "observer": "관찰",
        }

        for entity in entities[:top_n]:
            type_ko = _ENTITY_TYPE_KO.get(entity.entity_type, entity.entity_type)
            sentiment_str = f"{entity.sentiment_bias:+.2f}"
            stance_str = stance_ko.get(entity.stance, entity.stance)
            lines.append(f"| {entity.name} | {type_ko} | {entity.mentions}회 | {sentiment_str} | {stance_str} |")

        lines.append("")

        # 주요 관계
        if relations:
            lines.append("**주요 관계:**")
            # 감성 절대값 기준 상위 관계 정렬
            sorted_relations = sorted(relations, key=lambda r: abs(r.sentiment), reverse=True)
            for rel in sorted_relations[:8]:
                rel_ko = _RELATION_TYPE_KO.get(rel.relation_type, rel.relation_type)
                sentiment_str = f"{rel.sentiment:+.2f}"
                lines.append(f'- {rel.source} --[{rel_ko}]--> {rel.target} ({sentiment_str}): "{rel.fact}"')
            lines.append("")

        return "\n".join(lines)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _find_best_seed(self, indices: list[int], doc_sets: list[set[str]]) -> int:
        """미할당 인덱스 중 다른 문서들과 키워드 중복이 가장 많은 시드 선택."""
        best_idx = indices[0]
        best_overlap = -1

        for i in indices:
            overlap = 0
            for j in indices:
                if i != j:
                    overlap += len(doc_sets[i] & doc_sets[j])
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = i

        return best_idx

    def _find_representative(
        self,
        items: list[dict],
        docs: list[list[str]],
        top_keywords: list[str],
    ) -> str:
        """클러스터 대표 기사 제목을 반환 (상위 키워드 포함 수 기준)."""
        top_set = set(top_keywords)
        best_title = items[0].get("title", "") if items else ""
        best_score = -1

        for item, doc in zip(items, docs, strict=False):
            score = len(set(doc) & top_set)
            if score > best_score:
                best_score = score
                best_title = item.get("title", "")

        return best_title

    def _build_summary(
        self,
        items: list[dict],
        keywords: list[str],
        sentiment_score: float,
    ) -> str:
        """클러스터 요약 텍스트 생성."""
        if not items:
            return ""

        sources = list({item.get("source", "") for item in items if item.get("source")})
        source_str = ", ".join(sources[:3])
        kw_str = " · ".join(keywords[:3]) if keywords else ""
        sentiment_str = self._sentiment_label(sentiment_score)

        n = len(items)
        parts = []
        if kw_str:
            parts.append(f"{kw_str} 관련 뉴스 {n}건이 감지되었습니다.")
        else:
            parts.append(f"관련 뉴스 {n}건이 감지되었습니다.")
        if source_str:
            parts.append(f"주요 출처: {source_str}.")
        parts.append(f"시장 분위기: {sentiment_str}.")
        return " ".join(parts)

    def _sentiment_label(self, score: float) -> str:
        """감성 점수를 레이블 문자열로 변환."""
        if score > 0.2:
            return "긍정적"
        elif score > 0.05:
            return "다소 긍정적"
        elif score < -0.2:
            return "부정적"
        elif score < -0.05:
            return "다소 부정적"
        else:
            return "중립"


# ── 편의 함수 ─────────────────────────────────────────────────────────────────


def analyze_news(
    news_items: list[dict],
    top_n: int = 15,
    max_topics: int = 5,
    include_entities: bool = True,
) -> dict:
    """뉴스 아이템 목록을 분석하여 키워드, 클러스터, 시장 신호, 엔티티를 반환하는 편의 함수.

    Args:
        news_items: 뉴스 아이템 목록.
        top_n: 추출할 상위 키워드 수.
        max_topics: 최대 토픽 클러스터 수.
        include_entities: 엔티티 추출 및 관계 감지 포함 여부 (기본값: True).

    Returns:
        분석 결과 딕셔너리::

            {
                "keywords": list[dict],
                "clusters": list[TopicCluster],
                "topic_summary_md": str,
                "market_signals": dict,
                "entities": list[FinancialEntity],       # include_entities=True 시
                "relations": list[EntityRelation],        # include_entities=True 시
                "entity_report_md": str,                  # include_entities=True 시
            }
    """
    spider = MindSpider()
    keywords = spider.extract_keywords(news_items, top_n=top_n)
    clusters = spider.cluster_topics(news_items, max_topics=max_topics)
    topic_summary_md = spider.generate_topic_summary(clusters)
    market_signals = spider.detect_market_signals(news_items)

    result: dict = {
        "keywords": keywords,
        "clusters": clusters,
        "topic_summary_md": topic_summary_md,
        "market_signals": market_signals,
    }

    if include_entities:
        entities = spider.extract_entities(news_items)
        relations = spider.detect_relations(news_items, entities)
        entity_report_md = spider.generate_entity_report(entities, relations)
        result["entities"] = entities
        result["relations"] = relations
        result["entity_report_md"] = entity_report_md

    return result
