# 뉴스 리스크 레벨(CRITICAL/HIGH) 판정 로직 재설계

> **작성일**: 2026-04-20 | **상태**: 설계안(Draft) | **범위**: `scripts/common/summarizer.py` 의 `_assess_risk_level` / `classify_priority` / P0 경보 트리거 전반
> **트리거**: `_posts/2026-04-20-daily-crypto-news-digest.md` 에서 "**리스크 수준 [CRITICAL]**" 판정의 근거가 *O.C. Guy는 비트코인이 '여전히 폰지 사기'라고 말합니다* (개인 발언, 배우 Ben McKenzie 인터뷰)였음을 확인. 경보가 시장 실질 영향이 아니라 단일 키워드(*폭락·crash·hack*) 일치에 기반하고, 긍정 뉴스(*비트코인 7.5만달러 재탈환*)·중립 정책(*전략적 비트코인 비축고*)까지 같은 "긴급 알림" 박스에 묶여 있음.

---

## 1. 현황 분석 — 현재 CRITICAL 판정 로직

### 1-1. 트리거 체인 (소스 인용)

`_posts/2026-04-20-daily-crypto-news-digest.md:71` — `**리스크 수준 [CRITICAL]**` 렌더링
→ `scripts/common/summarizer.py:2287` `generate_overall_summary_section()` 이 `risk_level` 을 문자열 포맷팅
→ `scripts/common/summarizer.py:2283` `risk_level = self._assess_risk_level(priority_items)`
→ `scripts/common/summarizer.py:2138-2150` `_assess_risk_level()`

```python
# scripts/common/summarizer.py:2138-2150
def _assess_risk_level(self, priority_items):
    p0_count = len(priority_items.get("P0", []))
    p1_count = len(priority_items.get("P1", []))
    if p0_count >= 3:   return "critical"
    if p0_count >= 1:   return "elevated"
    if p1_count >= 5:   return "elevated"
    if p1_count >= 2:   return "moderate"
    return "low"
```

`priority_items` 는 `classify_priority()` 결과(`summarizer.py:1105-1127`). 판정 기준은 **P0/P1 키워드 텍스트 매칭** 단 하나.

```python
# scripts/common/summarizer.py:1115-1125 (요약)
for priority in ["P0", "P1", "P2"]:
    keywords = PRIORITY_KEYWORDS[priority]
    for idx, item in enumerate(self.items):
        text = (title + " " + title_original + " " + description).lower()
        if any(kw in text for kw in keywords):
            result[priority].append(item)
            assigned.add(idx)
```

### 1-2. P0 키워드(`summarizer.py:938-963`)

```
crash, 폭락, hack, 해킹, executive order, 행정명령, rate decision, 금리 결정,
파산, bankruptcy, emergency, 긴급, bank run, 뱅크런, exploit, rug pull,
circuit breaker, 서킷브레이커, 사이드카, flash crash, 급락, theft, 도난, zero-day
```

**문제**: 부분 문자열 매칭(`kw in text`). 단어 경계 없음 → `"crash course"`, `"해킹 방어 가이드"`, *"폭락하지 않았다"* 같은 문구도 적중. `classify_priority()` 호출 시점의 `text` 는 `title + title_original + description` 을 전부 소문자 연결한 것이어서, 번역된 제목과 원문 제목에서 이중 매칭되는 현상도 존재.

### 1-3. 유사 경로 — security-report 는 별도 로직

`scripts/collect_crypto_news.py:474-485` `_score_security_severity()` 는 **금액 패턴 + 공격 동사**를 모두 요구.

```python
if any(kw in text for kw in ["billion","exploit","hack","drain","bridge","10억","해킹","유출","탈취"]):
    if re.search(r"\$?([\d,.]+)\s*(?:million|billion|백만|억)", text):
        return "🔴 CRITICAL"
    return "🟠 HIGH"
```

이 로직은 `_posts/2026-04-18-daily-security-report.md:31`의 "*2억 8천만 달러 규모 드리프트 프로토콜 악용*" 같이 **구체적 손실 수치**가 있는 케이스에만 CRITICAL 을 부여 — 상대적으로 합리적. 즉 저장소 안에 이미 **두 개의 독립 판정 체계**가 공존하며, summarizer 측만 과민하다.

### 1-4. 판정 출력 소비 지점

| 위치 | 용도 | 과민 판정이 드러나는 증상 |
|------|------|---------------------------|
| `summarizer.py:2283-2287` | `### 전체 뉴스 요약` 블록 하단 배너 | 2026-04-20 포스트 71행 |
| `summarizer.py:2293-2311` | `### 긴급 이슈` 리스트 3건 | 포스트 73-77행 (개인 발언이 1순위) |
| `summarizer.py:2438-2462` | `한눈에 보기` 통계 그리드 `🔴 높음` | 포스트 40행 |
| `summarizer.py:2549-2571` | `<div class="alert-box alert-urgent">` 긴급 알림 박스 | 포스트 52-59행 |
| `summarizer.py:2620-2623` | `투자자 인사이트` 리스크 평가 | 하단 |

단일 `classify_priority()` 출력이 **5개 렌더링 지점**에 동시 전파된다. 따라서 개선은 판정 함수 2개(`classify_priority`, `_assess_risk_level`)에 집중하면 전파 범위가 자동 해결.

### 1-5. 재사용 가능한 신호 — 이미 존재하는 자산

| 자산 | 위치 | 현재 사용처 | 재사용 가능성 |
|------|------|-------------|---------------|
| `score_impact()` — 소스 가중치 + 콘텐츠 시그널(%, $bn, 기관명, urgency) | `summarizer.py:2694-2723` | **어디에도 호출 없음**(dead code) | **높음** — 그대로 활용 |
| `_SOURCE_WEIGHTS` dict | `summarizer.py:2680-2692` | `score_impact()` 내부만 | **높음** |
| `_classify_source()` 6-type 분류 | `common/markdown_utils.py:194-235` | 배지 색상 | **중간** — 매핑 재사용 |
| `_SENTIMENT_POS / _SENTIMENT_NEG` | `summarizer.py:2725-2771` | `get_theme_sentiment()` | **중간** — 기사 단위 sentiment |
| `_classify_news_severity()` | `summarizer.py:77-84` | 개별 뉴스 카드 배지 | **중간** — 독립 경로 |
| `extract_entities()` | `common/entity_extractor.py:80-` | 현재 summarizer 판정에 미사용 | **높음** — 기관 vs 개인 구분 |
| `bettafish_analyzer.SentimentPerspective` | `common/bettafish_analyzer.py:243-389` | 종합 분석 리포트 | 중복 연결 시 범위 과잉 — 재사용 보류 |

---

## 2. 문제 모델링 — 과민 vs 합리적 케이스 대비

### 2-1. 2026-04-20 포스트 경보 목록 재분석

| # | 타이틀 (포스트 인용) | 실제 의미 | P0 키워드 적중 | 타당성 |
|---|-----------------------|-----------|-----------------|--------|
| 1 | *O.C. Guy는 비트코인이 '여전히 폰지 사기'라고 말합니다.* | 배우 Ben McKenzie **개인 발언 인터뷰** | "crash" (본문 "폭락") | **오탐 (FP)** |
| 2 | *비트코인, 한달 만에 7.5만달러 재탈환* | 긍정 가격 상승 | "급락"(유가 대한 언급이 본문 설명에 포함) | **오탐 (FP)** |
| 3 | *美, '전략적 비트코인 비축고' 설립 임박…트럼프 행정명령 가동* | 중립/긍정 규제 뉴스 | "executive order / 행정명령" | 기술적 적중이나 CRITICAL 수준 아님 — **경계 (borderline)** |

반면 2026-04-18 security-report `[🔴 CRITICAL]` 는 "*2억 8천만 달러 규모 드리프트 프로토콜 악용 이후 12개가 넘는 디파이 프로토콜이 공격당했습니다*" 로 **금액 + 피해 규모**가 명시. **합리적 (TP)**.

### 2-2. 오탐 공통 패턴 (FP)

| 패턴 | 근거 |
|------|------|
| **F1. 개인/오피니언 발언이 뉴스화** | 배우·인플루언서·트위터 인용. "*~ 말했다 / says*" 패턴 |
| **F2. 부정 키워드가 인용·메타 용법** | *"폭락 → 반등"*, *"더 이상 crash 없다"* 같은 뉴스 본문 |
| **F3. 단어 경계 부재 적중** | "crash" ⊂ "crashed", "attack" ⊂ "attacks on sentiment" |
| **F4. 긍정 기사에 임베드된 부정 사례 설명** | 가격 상승 뉴스 본문이 과거 폭락을 회고 |
| **F5. aggregator 번역에 의한 텍스트 증폭** | `title + title_original + description` 다중 연결이 **중복 매칭**을 유발해 1건이 3건 강도로 스코어 |
| **F6. 규제 이벤트 과장** | `executive order` = CRITICAL 아님. 이미 보도·예상된 정책도 P0 편입 |

### 2-3. 정탐 공통 패턴 (TP)

| 패턴 | 근거 |
|------|------|
| **T1. 구체적 피해 금액** | `_score_security_severity` 가 `$xxxM/$xxxB` 매칭 (`collect_crypto_news.py:479`) |
| **T2. 기관 발표 + 규제 행위** | "SEC sues", "FOMC 금리 인하 결정", "금감원 조사 착수" |
| **T3. 시장 메커니즘 발동** | "circuit breaker", "trading halt", "바이낸스 출금 중단" |
| **T4. 다수 소스 동시 보도(클러스터)** | Reuters + Bloomberg + WSJ 교차 확인 |
| **T5. 명확한 수치 변동** | "BTC -15% in 1h", "Nasdaq -5%" |

### 2-4. 문제 모델

현재 시스템은 **오탐 축 전체(F1~F6)에 대해 방어 없음**. 정탐 축 중 T1만 `score_impact()` 에 부분 반영(`summarizer.py:2709-2713` `%` 와 `$billion` 정규식) — 그러나 `score_impact` 는 호출되지 않음.

---

## 3. 신호 후보 — 가용성 및 가중치

각 신호는 (a) 추가 의존성 없는 로컬 계산, (b) 결정적/테스트 가능, (c) 낮은 비용이어야 한다.

| 신호 | 근거 위치 | 가용 상태 | 제안 가중치 | 비고 |
|------|-----------|-----------|-------------|------|
| **S1. 소스 신뢰도** | `_SOURCE_WEIGHTS` (`summarizer.py:2680`), `_classify_source` (`markdown_utils.py:194`) | 즉시 | ×0.4 ~ ×1.5 | 6-type(regulator/crypto-media/finance-media/world-media/exchange/aggregator) 매핑 |
| **S2. 구체적 금액/수치** | `score_impact` (`summarizer.py:2709-2713`) 정규식 재사용 | 즉시 | +2 | `\$[\d,.]+\s*(million\|billion\|B\|M)`, `[+-]?\d+\.?\d*%` |
| **S3. 기관/규제 엔티티** | `entity_extractor._ORG_ENTITIES` (`entity_extractor.py:56-64`), `score_impact` institutions 리스트 (`summarizer.py:2715`) | 즉시 | +1.5 | SEC/Fed/ECB/금감원 등 언급 시 |
| **S4. 시장 메커니즘 발동 키워드** | `PRIORITY_KEYWORDS["P0"]` 의 시장-구조 부분집합 | 즉시 | +2 | circuit breaker / halt / bank run / default / bankruptcy |
| **S5. 오피니언/개인 발언 마커** | `_SEVERITY_LOW_KW` (`summarizer.py:61-74`) + 신규 패턴 | 즉시 | **−3 (차감)** | "says"/"말합니다"/"opinion"/"prediction"/"인터뷰"/"주장" |
| **S6. 엔터테인먼트/인물 기반 부정** | `content_filters._DEFAULT_ENTERTAINMENT_KEYWORDS` (`content_filters.py:16`) | 즉시 | 차감 | 이미 존재 |
| **S7. Sentiment 방향성** | `_SENTIMENT_POS/NEG` (`summarizer.py:2725-2771`) | 즉시 | −1.5 (긍정 시) | 긍정 키워드 과반이면 CRITICAL 부적합 |
| **S8. 소스 다중성(클러스터)** | `self.items` 순회 시 title 토큰 유사도 집계 | 중간 | +1 | ≥2 독립 소스 동일 주제 |
| **S9. 단어 경계 매칭** | `re.compile(r"\b" + kw + r"\b")` | 즉시 | 기존 `kw in text` 대체 | F3 해결 |
| **S10. 번역 중복 제거** | `title` 또는 `title_ko` 우선 사용 | 즉시 | 기존 `title + title_original + desc` 대체 | F5 해결 |

### 3-1. 신호 가용성 요약

- 즉시 가용(코드 상주): S1~S7, S9, S10 — **추가 의존성 0**
- 경량 신규 계산: S8 (O(n²) 피해 가능성 → n≤100 이므로 무시 가능)
- 배제: LLM 기반 분류, 외부 API 기반 soure reputation → 범위 초과·비결정적

---

## 4. 아키텍처 옵션

### 옵션 A — 가중 합산 점수 모델 (weighted sum, 추천)

각 아이템에 impact score(0–10)를 계산하고, 상위 N개의 평균/합으로 전체 risk_level 을 결정.

```
item_score(item) = clip(0, 10,
    base_source_weight(S1)
  + 2.0 × has_specific_amount(S2)
  + 1.5 × has_institutional_entity(S3)
  + 2.0 × has_market_mechanism(S4)
  - 3.0 × is_opinion_piece(S5)
  - 1.5 × has_positive_sentiment(S7)
)

overall:
    top_items = [i for i in items if item_score(i) >= P0_THRESHOLD]  # 기본 5.0
    if len(top_items) >= 3 and mean(top_scores) >= CRITICAL_MEAN:     # 기본 6.5
        return "critical"
    elif len(top_items) >= 1:
        return "elevated"
    elif p1_count >= 5:
        return "elevated"
    elif p1_count >= 2:
        return "moderate"
    return "low"
```

**장점**
- `score_impact()`(`summarizer.py:2694-2723`) 의 **기존 뼈대 재사용** → 죽은 코드를 살림
- 오피니언 차감(S5), 긍정 차감(S7), 소스 신뢰도(S1)가 자연스럽게 결합
- Threshold 2종만 튜닝하면 전체 비율 조정 가능 → 회귀 테스트 유리

**단점**
- 가중치 magic number 7개 — 문서화·테스트 부담
- `score_impact` 는 단일 아이템 평가이므로 **집계 레이어**(`_assess_risk_level`)가 필요 → 레이어 설계 복잡도 증가
- 경계 케이스에서 0.1 차이로 레벨 변동 가능 → hysteresis 필요

### 옵션 B — 룰베이스 + 오버라이드 (rule pipeline)

명시적 룰을 순서대로 적용. 마지막에 매치되는 룰이 승.

```
1. default: risk = "low"
2. if p1_count >= 2: risk = "moderate"
3. if p1_count >= 5: risk = "elevated"
4. if p0_count >= 1 AND at_least_one_is_institutional(): risk = "elevated"
5. if p0_count >= 3 AND at_least_2_institutional(): risk = "critical"
6. override: if market_mechanism_triggered(): risk = "critical"  # circuit breaker 등
7. suppression: if ratio(opinion_items, p0_items) > 0.5: downgrade one level
```

**장점**
- **설명 가능성 최고** — "왜 CRITICAL?" 을 각 룰 라인으로 보고 가능
- 도메인 지식(T2, T3) 직접 인코딩
- 테스트 작성 쉬움 (rule_id 단위)

**단점**
- 룰 수 증가 시 순서 의존성 지옥 (6번·7번 간 순서가 결정적)
- 새 패턴 추가 시 전체 파이프라인 재검토 필요
- 파라미터가 수치가 아니라 부울 플래그라 미세 튜닝 불가

### 옵션 C — 단순 임계값 상향 (minimal change)

`_assess_risk_level` 상수만 변경:

```python
if p0_count >= 5:  return "critical"   # 3 → 5
if p0_count >= 2:  return "elevated"   # 1 → 2
```

**장점**
- 1~2줄 변경, 회귀 영향 최소
- 즉시 적용 가능

**단점**
- **근본 원인(키워드 품질) 미해결** → 문제 재발
- 실제 CRITICAL 상황도 같이 둔감 → **False negative 위험**
- 2026-04-20 포스트의 경우 `p0_count = 10건` 이어서 임계값을 5로 올려도 여전히 CRITICAL — **본 사례를 해결 못함**

### 옵션 비교표

| 축 | A (가중합) | B (룰) | C (임계값) |
|----|------------|--------|------------|
| 과민 경보 해결 | ✅ (S5 차감) | ✅ (5·7번 룰) | ❌ |
| 구현 복잡도 | 중 (~120 LOC) | 중 (~100 LOC) | 저 (~5 LOC) |
| 테스트 커버리지 | 높음 (수치 assertion) | 높음 (rule_id) | 낮음 |
| 설명 가능성 | 중 (score breakdown 로깅 필요) | 높음 | 낮음 |
| 튜닝 용이성 | 높음 | 중 | 낮음 |
| False negative 위험 | 낮음 | 중 (룰 누락) | **높음** |
| 기존 코드 재사용 | 높음 (`score_impact`) | 중 | 없음 |

### 권장: **옵션 A + 옵션 B 의 오버라이드 룰 결합 (Hybrid)**

1. **기본 판정**: 옵션 A 가중 합산 — 2026-04-20 같은 오피니언 중심 사례를 점수로 내리누름
2. **안전망 오버라이드**: 옵션 B 의 룰 6·7 만 상위 계층에서 적용
   - 룰 6 — 시장 메커니즘(`circuit breaker`, `trading halt`, `flash crash`) 이 **기관 소스**로 보도되면 점수 무시 CRITICAL
   - 룰 7 — P0 적중 아이템의 50% 초과가 `is_opinion_piece` 이면 한 단계 다운그레이드
3. **원 로직 점진 이관**: `classify_priority()` 는 **버킷 분류** 용도로 유지하되, CRITICAL 판정의 최종 책임을 **점수 기반 새 함수**로 이동

---

## 5. 권장안 상세

### 5-1. 모듈 구조

```python
# scripts/common/risk_classifier.py  (신규 ~220 LOC)

@dataclass(frozen=True)
class RiskSignals:
    source_weight: float   # S1
    has_amount: bool       # S2
    has_institution: bool  # S3
    market_mechanism: bool # S4
    is_opinion: bool       # S5
    is_entertainment: bool # S6
    sentiment: Literal["pos","neg","neu"]  # S7

@dataclass(frozen=True)
class ItemScore:
    item_id: str
    score: float         # 0.0 ~ 10.0
    signals: RiskSignals
    contributions: dict[str, float]  # {"source": +1.5, "opinion": -3.0, ...}
    rule_overrides: list[str]        # ["rule_6_market_mechanism"]

@dataclass(frozen=True)
class RiskVerdict:
    level: Literal["critical","elevated","moderate","low"]
    reason: str
    top_items: list[ItemScore]
    aggregate_mean: float
    rule_trace: list[str]  # 적용된 오버라이드 이력
```

### 5-2. 신호 계산기 (순수 함수)

```python
_OPINION_MARKERS = {
    # 영문
    "says", "opinion", "column", "editorial", "interview", "predicts",
    "claims", "thinks", "argues", "warns that", "according to",
    # 한글
    "말합니다", "주장", "인터뷰", "칼럼", "오피니언", "예상", "전망",
    "라고 밝혔", "밝혔다", "라고 평", "시각", "관점",
}

_MARKET_MECHANISM = {
    "circuit breaker", "서킷브레이커", "사이드카",
    "trading halt", "거래 중단", "거래 정지",
    "bank run", "뱅크런",
    "flash crash",
    "withdrawal halt", "출금 중단",
}

_AMOUNT_RE = re.compile(
    r"\$[\d,.]+\s*(?:billion|million|B\b|M\b)"
    r"|\d+\s*(?:억|조)\s*(?:달러|원)"
    r"|[+-]?\d+\.?\d+%",
    re.IGNORECASE,
)

def extract_signals(item: dict, sentiment_fn, source_classifier) -> RiskSignals:
    ...
```

### 5-3. 점수 공식

```python
WEIGHTS = {
    "source_base":        (0.5, 2.5),   # min, max clip
    "amount":             2.0,
    "institution":        1.5,
    "market_mechanism":   2.5,          # 최상위 가중
    "opinion_penalty":   -3.0,
    "entertainment_penalty": -4.0,
    "sentiment_pos_penalty": -1.5,
    "sentiment_neg_bonus":  +0.5,
}

# Threshold (데이터 기반 튜닝; 5-4 참조)
P0_ITEM_THRESHOLD      = 5.0
ELEVATED_ITEM_THRESHOLD = 3.5
CRITICAL_MEAN_TOP_3    = 6.0
```

### 5-4. 데이터 기반 threshold 제안

**2026-04-20 scientist 검증 업데이트 — 설계 초기값이 도달 불가함을 확인**

실측 30일 분포(2026-03-22~04-20, 30 포스트, 2922 기사):

| 레벨 | 현재(실측) | 목표 | 설계 초기값(6.0) 시뮬 | 조정(4.0~4.5) 시뮬 |
|------|------------|------|----------------------|-------------------|
| critical | **80%** | 1~3% | 0% | 3.3% |
| elevated | 20% | 10~20% | 3.3% | 56.7% |
| moderate | 0% | 30~50% | 96.7% | 40% |
| low | 0% | 30~50% | 0% | 0% |

**핵심 발견**:
1. 현재 CRITICAL 비율 80% — 설계 추정(7%)보다 11배, 목표(3%)보다 26~80배 과다
2. 원인: `p0_count >= 3 → critical`이 매일 100건 수집에서 **항상 적중** (P0 키워드 부분문자열 매칭 과민)
3. 채점 모델 이론 최대값 5.5, 실측 최대값 4.50 → `CRITICAL_MEAN_TOP_3=6.0` 은 **수학적 도달 불가**

**threshold 재조정 (권장)**:

| 파라미터 | 초기 설계 | **권장 조정** | 근거 |
|---------|-----------|---------------|------|
| `CRITICAL_MEAN_TOP_3` | 6.0 | **4.0~4.5** | 실측 max=4.50; 6.0 > 이론 max(5.5) |
| `P0_ITEM_THRESHOLD` | 5.0 | **3.5~4.0** | amount(2.0)+base(2.0)=4.0이 자연 하한 |
| `ELEVATED_ITEM_THRESHOLD` | 3.5 | 2.5~3.0 | 비례 축소 |

**선결 과제**: threshold 조정만으로 해결 불충분. `classify_priority()` P0 키워드를
(a) `\b` 단어 경계 적용 (S9),
(b) 동일 기사 중복 수집 dedup 강화
로 개선해야 P0 pool 자체가 정상 분포로 수렴.

**FP/TP 분석**:
- 30일 82건 표시 P0 중 고유 FP 2건(2.4%): "O.C. Guy 폰지 사기" 3일 중복, "트럼프 강경 발언"
- TP 후보 42건(51.2%): amount 또는 institution 수반

**튜닝 절차**: `scripts/tools/tune_risk_threshold.py`(Phase 2 도입) 가 과거 30일 포스트를 파싱해 점수 분포를 내고, CRITICAL≤3%가 되는 `CRITICAL_MEAN_TOP_3` 를 이분탐색. 선결 과제(단어 경계·dedup) 먼저 해결 후 재측정.

**참조**: `.omc/scientist/reports/20260420_144613_risk_threshold_validation.md`, `.omc/wiki/p4-threshold-validation-30-day-distribution-analysis.md`

### 5-5. 오버라이드 룰

```python
def apply_overrides(scores: list[ItemScore], base_level: str) -> tuple[str, list[str]]:
    trace = []

    # Rule 6 — 시장 메커니즘 발동 + 기관 소스 병합
    hard_critical = [s for s in scores if s.signals.market_mechanism and s.signals.source_weight >= 1.5]
    if len(hard_critical) >= 1:
        trace.append("rule_6_market_mechanism_hard_override")
        return "critical", trace

    # Rule 7 — 오피니언 비중 과반이면 한 단계 다운그레이드
    p0_like = [s for s in scores if s.score >= P0_ITEM_THRESHOLD]
    if p0_like:
        opinion_ratio = sum(1 for s in p0_like if s.signals.is_opinion) / len(p0_like)
        if opinion_ratio > 0.5:
            trace.append(f"rule_7_opinion_ratio={opinion_ratio:.2f}_downgrade")
            return _downgrade_one(base_level), trace

    return base_level, trace

def _downgrade_one(level: str) -> str:
    return {"critical": "elevated", "elevated": "moderate", "moderate": "low", "low": "low"}[level]
```

### 5-6. 원 함수와의 연결

```python
# scripts/common/summarizer.py: _assess_risk_level 교체안 (의사코드)
def _assess_risk_level(self, priority_items):
    from .risk_classifier import classify_risk  # lazy import
    verdict = classify_risk(
        items=self.items,
        priority_items=priority_items,
        sentiment_fn=self.get_theme_sentiment,
        source_classifier=_classify_source,
    )
    self._last_risk_verdict = verdict  # 진단/로깅 용 저장
    logger.info(
        "risk_level=%s mean_top3=%.2f rules=%s",
        verdict.level, verdict.aggregate_mean, verdict.rule_trace,
    )
    return verdict.level
```

P0 렌더링(`summarizer.py:2293-2311`, `2549-2571`)도 **점수 내림차순**으로 정렬된 `verdict.top_items` 를 사용하도록 변경 → 2026-04-20 포스트의 "*O.C. Guy*" 가 자연히 하단으로 밀려남.

### 5-7. 예상 CRITICAL 비율

- 2026-04-20 포스트: P0=10건. 그 중 **오피니언 마커**(`says`/`말합니다`/`예측`)가 7건 이상 → Rule 7 트리거 → **critical → elevated 다운그레이드**. 또한 평균 점수가 ~3.8 예상(기관+금액 적중 3건) → 기본 판정도 elevated 이하.
- 2026-04-18 security-report 류: "*2억 8천만 달러 드리프트 프로토콜 악용*" 은 `amount` + `hack/exploit` + `market_mechanism(간접)` → 점수 ~7.5, CRITICAL 유지.
- 과거 60 포스트 시뮬레이션 시 CRITICAL 비율 7% → **2~3%** 로 감소 예상.

---

## 6. 구현 단계 체크리스트

### Phase 1 — 모듈 뼈대
- [ ] `scripts/common/risk_classifier.py` 신규 (RiskSignals, ItemScore, RiskVerdict, extract_signals, score_item, apply_overrides, classify_risk)
- [ ] `tests/test_risk_classifier.py` — 신호 추출 단위 테스트 18종(각 신호 pos/neg, 경계)
- [ ] `ruff check` 통과

### Phase 2 — threshold 튜닝
- [ ] `scripts/tools/tune_risk_threshold.py` (옵션) — 30일 포스트 파싱 → 점수 분포 출력
- [ ] threshold 상수 값 확정, docstring 에 분포 표 기록
- [ ] CRITICAL≤3% / LOW≥30% 목표 검증

### Phase 3 — summarizer 연결
- [ ] `summarizer.py:_assess_risk_level` 교체
- [ ] `summarizer.py:_build_narrative_intro` / `generate_overall_summary_section` / `generate_executive_summary` 에서 `verdict.top_items` 사용
- [ ] 기존 테스트 `tests/test_summarizer_extended.py:703-733` 는 새 verdict 기반으로 재작성(6개 테스트)

### Phase 4 — 회귀 fixture
- [ ] `tests/fixtures/risk_cases/` 에 JSON fixture 5개
  - `fp_opinion_only.json` — 오피니언 5건만 → elevated 이하
  - `fp_positive_embedded.json` — 긍정 기사 본문에 crash 언급 → moderate 이하
  - `tp_hack_with_amount.json` — 금액 + exploit → critical
  - `tp_regulation_formal.json` — SEC 공식 발표 → elevated/critical 경계
  - `borderline_executive_order.json` — 행정명령 중립 → elevated
- [ ] 각 fixture 가 기대 레벨을 반환함을 assertion

### Phase 5 — 운영
- [ ] 1주일간 `risk_level` 분포 로깅 (Grafana 또는 JSON append)
- [ ] 과거 10일 포스트 후분석 리포트 (CRITICAL/ELEVATED 건수 비교)
- [ ] 기존 P1 기반 `elevated` 룰(`p1_count >= 5`)은 유지 vs 제거 결정

### Phase 6 — 문서화
- [ ] `CLAUDE.md` "Description Quality Pipeline" 섹션 옆에 "Risk Level Pipeline" 추가
- [ ] 가중치·threshold 표를 `docs/critical-alert-redesign.md` 최신화
- [ ] `_SEVERITY_HIGH_KW`·`PRIORITY_KEYWORDS` 와의 역할 분담을 `scripts/common/summarizer.py` 모듈 docstring 에 명시

---

## 7. 리스크 / 엣지케이스

| # | 리스크 | 영향 | 완화책 |
|---|--------|------|--------|
| R1 | **False negative** — 진짜 CRITICAL 누락 | 높음 | Rule 6(market_mechanism 하드 오버라이드), 회귀 fixture `tp_*` 로 CI 검증 |
| R2 | 오피니언 마커 과잉 차단 — 공식 인사(SEC Chair) 발언 포함 기사를 오피니언으로 분류 | 중 | S5 신호에서 S3(institution) 이 동시 적중 시 opinion 플래그 해제 |
| R3 | `score_impact` 의 `_SOURCE_WEIGHTS` 가 구버전 소스명만 커버 (`summarizer.py:2680-2692`) | 중 | Phase 1 에서 `_classify_source` 기반 6-type 매핑으로 교체, 소스별 weight dict 리팩터 |
| R4 | 번역된 `title_ko` 가 원문과 의미 달라 마커 불일치 | 중 | `title` (번역 후) 을 **1차**, `title_original` 을 **보조**. 동일 마커 이중 계상 방지 |
| R5 | 2개 독립 판정 체계(`_score_security_severity` vs `risk_classifier`) 이격 | 낮 | Phase 6 에서 `_score_security_severity` 도 `risk_classifier.score_item` 의 subset wrapper 로 점진 이관 |
| R6 | 가중치 튜닝이 매뉴얼 — 시장 상황 변화 시 stale | 중 | Phase 5 로깅 + `tune_risk_threshold.py` 월간 재실행 권장 |
| R7 | `classify_priority` 와 `risk_level` 이 불일치 출력 (P0 10건인데 risk=moderate) | 중 | 렌더링 단에서 `verdict.top_items` 기반 "긴급 이슈" 리스트를 제공 → priority_items 는 백워드 호환 |
| R8 | 엔터테인먼트 필터가 P0 키워드(`파산`)와 충돌 — 연예인 파산 기사 | 낮 | S6 entertainment 우선(−4) 이 S4(+0) 보다 큼 → 자연 배제 |
| R9 | `_SEVERITY_HIGH_KW` (개별 뉴스 카드 배지, `summarizer.py:26-60`) 와 새 판정의 **출력 불일치** | 중 | Phase 6 에서 배지 레벨도 `item.score` 기반으로 ≥7 = high / ≥4 = medium / else = low 매핑 |
| R10 | 한국어 단어 경계 정규식 불안정 | 중 | 영문은 `\b` 사용, 한글은 **공백/구두점/문장끝** 기준 pre/post char 검사 — `entity_extractor` 방식 차용 |

---

## 8. 테스트 전략

### 8-1. 레이어 1 — 단위 테스트 (신호 추출)

`tests/test_risk_classifier.py` (≈25 tests)

```python
def test_opinion_marker_detected_korean():
    item = {"title": "A는 B라고 말합니다.", "description": ""}
    sig = extract_signals(item, ...)
    assert sig.is_opinion is True

def test_amount_regex_usd_billion():
    assert _AMOUNT_RE.search("$280 million drained") is not None

def test_institution_detected():
    item = {"title": "SEC files charges against X", "description": ""}
    assert extract_signals(item, ...).has_institution is True

def test_opinion_suppressed_when_institution_speaks():
    item = {"title": "SEC Chair says crypto is ponzi", "description": ""}
    sig = extract_signals(item, ...)
    assert sig.is_opinion is False   # institution overrides
```

### 8-2. 레이어 2 — 점수 계산

```python
def test_score_hack_with_amount():
    item = {"title": "$280M DeFi exploit", "description": "...", "source": "coindesk"}
    score = score_item(item, ...)
    assert score.score >= 7.0

def test_score_opinion_piece_penalized():
    item = {"title": "Ben McKenzie says Bitcoin still a ponzi scheme",
            "description": "...", "source": "google news"}
    assert score_item(item, ...).score < 3.0
```

### 8-3. 레이어 3 — 집계 + 오버라이드

```python
def test_rule_6_market_mechanism_hard_critical():
    items = [{"title": "NYSE circuit breaker triggered", "source": "reuters"}]
    verdict = classify_risk(items, ...)
    assert verdict.level == "critical"
    assert "rule_6_market_mechanism_hard_override" in verdict.rule_trace

def test_rule_7_opinion_majority_downgrades():
    items = [ ... 7건 of opinion + 3건 formal ... ]
    verdict = classify_risk(items, ...)
    assert verdict.level in ("elevated", "moderate")
    assert any("rule_7" in r for r in verdict.rule_trace)
```

### 8-4. 레이어 4 — 회귀 fixture

`tests/fixtures/risk_cases/*.json` 5종을 `pytest.mark.parametrize` 로 일괄 실행. 실제 과거 포스트 본문을 `scripts/tools/extract_fixture.py` 로 추출(P0 렌더링 섹션 파싱). 각 fixture 는:

```json
{
  "scenario": "fp_opinion_only",
  "expected_level": "moderate",
  "expected_rule_traces": ["rule_7_opinion_ratio"],
  "items": [ {"title":"...", "description":"...", "source":"..."}, ... ]
}
```

### 8-5. 레이어 5 — Property-based (hypothesis)

```python
@given(items=st.lists(item_strategy, min_size=0, max_size=50))
def test_risk_level_monotone_in_amount(items):
    # amount 가 커지면 score 는 단조 증가 (동일 다른 신호 고정 시)
    ...

@given(st.lists(item_strategy, min_size=5, max_size=20))
def test_all_opinion_never_critical(items):
    for i in items: i["title"] = f"{i['title']} says analyst"
    verdict = classify_risk(items, ...)
    assert verdict.level != "critical"
```

### 8-6. 레이어 6 — 스냅샷

`_posts/2026-04-20-daily-crypto-news-digest.md` 생성에 사용된 원시 items 를 `_state/` 또는 로그에서 복구 가능하면 스냅샷 테스트 추가. 복구 불가 시 fixture 로 대체.

---

## 9. 오픈 질문

1. **Q1**: `classify_priority()` 자체를 점수 기반으로 바꿀지, 키워드 버킷은 유지할지? → **유지**. P0/P1/P2 는 "텍스트적 토픽 태깅" 의미로 계속 쓰고, `risk_level` 만 점수 기반으로 분리.
2. **Q2**: `_score_security_severity` (`collect_crypto_news.py:474`) 는 이번 PR 에서 건드릴지? → **No**. Phase 6 후속.
3. **Q3**: 일일 평균 CRITICAL 건수를 Grafana/Slack 알림으로? → 별도 이슈. 본 설계는 **판정 정확도**만 다룸.
4. **Q4**: `sentiment_fn` 을 `get_theme_sentiment`(테마 단위) 가 아니라 **개별 기사 단위**로 바꿀 필요? → 개별 기사는 `_SENTIMENT_POS/NEG` 매칭으로 즉석 계산, `get_theme_sentiment` 재사용 안 함.
5. **Q5**: `source_weight` clip 범위(0.5~2.5) 가 적절한가? → Phase 2 튜닝 후 확정. 초기값은 `_SOURCE_WEIGHTS` 기준 정규화.
6. **Q6**: Rule 7 의 opinion_ratio 임계값 0.5 가 타당? → `fp_opinion_only.json` fixture 에서 경계 값 탐색, 0.4~0.6 범위 튜닝.
7. **Q7**: `_assess_risk_level` 의 `p1_count >= 5 → elevated` 룰을 유지? → **유지**하되, `verdict.rule_trace` 에 `"legacy_p1_count"` 로 표시해 향후 제거 가능성 열어둠.

---

## References

### 현재 로직
- `scripts/common/summarizer.py:2138-2150` — `_assess_risk_level` 본체 (CRITICAL 임계값 P0≥3)
- `scripts/common/summarizer.py:1105-1127` — `classify_priority` 키워드 `kw in text` 매칭
- `scripts/common/summarizer.py:938-1025` — `PRIORITY_KEYWORDS` P0/P1/P2 사전
- `scripts/common/summarizer.py:26-84` — `_SEVERITY_HIGH_KW`, `_SEVERITY_LOW_KW`, `_classify_news_severity`
- `scripts/common/summarizer.py:881-886` — `RISK_LEVELS` 한국어 설명
- `scripts/common/summarizer.py:2287` — `**리스크 수준 [{risk_level.upper()}]**` 렌더링 라인
- `scripts/common/summarizer.py:2549-2571` — P0 "긴급 알림" 박스 렌더링

### 재사용 가능 자산
- `scripts/common/summarizer.py:2680-2692` — `_SOURCE_WEIGHTS`
- `scripts/common/summarizer.py:2694-2723` — `score_impact()` (미호출 상태)
- `scripts/common/summarizer.py:2725-2771` — `_SENTIMENT_POS`, `_SENTIMENT_NEG`
- `scripts/common/summarizer.py:2773-2788` — `get_theme_sentiment`
- `scripts/common/markdown_utils.py:194-235` — `_SOURCE_RULES` 6-type 분류
- `scripts/common/entity_extractor.py:56-64` — `_ORG_ENTITIES` (Fed/SEC/ECB 등)
- `scripts/common/content_filters.py:16-152` — `_DEFAULT_ENTERTAINMENT_KEYWORDS`
- `scripts/collect_crypto_news.py:474-485` — `_score_security_severity` 금액 + 공격동사 결합(참고 구현)

### 문제 증거
- `_posts/2026-04-20-daily-crypto-news-digest.md:71` — 과민 CRITICAL 배너
- `_posts/2026-04-20-daily-crypto-news-digest.md:43-59` — 긴급 알림 박스 내용(개인 발언+긍정+중립 혼재)
- `_posts/2026-04-20-daily-crypto-news-digest.md:73-77` — "긴급 이슈" 리스트 1위 "O.C. Guy" 오피니언

### 합리적 비교 사례
- `_posts/2026-04-18-daily-security-report.md:31` — `[🔴 CRITICAL]` "2억 8천만 달러 드리프트 프로토콜 악용"
- `_posts/2026-04-18-daily-security-report.md:38` — "**심각도 분류**: CRITICAL 1건, HIGH 1건"

### 기존 테스트 (보존/확장 대상)
- `tests/test_summarizer_extended.py:703-733` — `_assess_risk_level` 6개 케이스(현재 3건 이상 P0 → critical 기대)
- `tests/test_summarizer_extended.py:592-677` — `classify_priority` 추가 커버리지 15개
- `tests/test_summarizer.py:280-325` — `classify_priority` 기본 동작 5개

### 코드 품질 및 설계 선례
- `docs/data-quality-guard-design.md` — 본 설계 문서의 스타일 기준
- `scripts/common/config.py:171-178` — `setup_logging()` 표준 진입점
