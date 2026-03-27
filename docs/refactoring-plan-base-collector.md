# BaseCollector ABC 리팩토링 계획

## 1. 현재 상태 분석

### 1.1 12개 수집기 목록

| 수집기 | 카테고리 | 패턴 유형 | 코드 라인수(약) | 복잡도 |
|--------|----------|-----------|----------------|--------|
| `collect_blockchain.py` | blockchain | 단일 포스트 (API 데이터 집계) | 337 | LOW |
| `collect_fmp_calendar.py` | market-analysis | 단일 포스트 (다중 API 집계) | 541 | MEDIUM |
| `collect_defi_llama.py` | (crypto 관련) | 단일 포스트 (API 데이터 집계) | ~1000 | MEDIUM |
| `collect_coinmarketcap.py` | (crypto) | 단일 포스트 (다중 API + 브라우저) | ~700+ | HIGH |
| `collect_crypto_news.py` | crypto-news, security-alerts | 다중 포스트 (RSS + API + 브라우저) | ~600+ | HIGH |
| `collect_stock_news.py` | stock-news | 단일 포스트 (RSS + API + 브라우저) | ~500+ | HIGH |
| `collect_regulatory.py` | regulatory-news | 단일 포스트 (다중 지역 RSS) | ~500+ | MEDIUM |
| `collect_social_media.py` | social-media | 단일 포스트 (텔레그램+트위터+RSS) | ~700+ | HIGH |
| `collect_political_trades.py` | (political) | 단일 포스트 (RSS + API) | ~400+ | MEDIUM |
| `collect_geopolitical.py` | worldmonitor | 단일 포스트 (Polymarket + GDELT + RSS) | ~900+ | HIGH |
| `collect_worldmonitor_news.py` | market-analysis | 단일 포스트 (WorldMonitor RSS) | ~950+ | HIGH |
| `collect_market_indicators.py` | (market) | 단일 포스트 (다중 API + RSS) | ~800+ | HIGH |

### 1.2 공통 패턴 (모든 수집기에서 반복)

#### main() 함수의 공통 흐름 (Template Method 패턴)

```
1. 로깅 시작: logger.info("=== Starting {name} collection ===")
2. 타이머 시작: started_at = time.monotonic()  # 또는 time.time()
3. DedupEngine 초기화: dedup = DedupEngine("{state_file}.json")
4. PostGenerator 초기화: gen = PostGenerator("{category}")
5. 날짜 설정: now = get_kst_now(); today = now.strftime("%Y-%m-%d")
6. 포스트 제목 생성: post_title = f"... - {today}"
7. 중복 검사: if dedup.is_duplicate_exact(post_title, source, today): → skip + log_collection_summary
8. 데이터 수집: fetch_*() 호출들 (수집기별 고유)
9. 빈 데이터 검사: if not items: → skip + log_collection_summary
10. 콘텐츠 빌드: content_parts 조합 (수집기별 고유)
11. 브리핑 이미지 생성 (선택): generate_news_briefing_card()
12. 포스트 생성: gen.create_post(title, content, date, tags, source, ...)
13. dedup 마킹: dedup.mark_seen() + dedup.save()
14. 메트릭 로깅: log_collection_summary(logger, collector=..., ...)
15. 로깅 종료: logger.info("=== ... collection complete ===")
```

#### 공통 임포트 패턴

모든 수집기가 공유하는 임포트:
```python
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.collector_metrics import log_collection_summary
from common.config import get_kst_now, setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator, build_dated_permalink
```

다수 수집기가 추가로 사용하는 모듈:
- `common.enrichment` (enrich_items) - 7개 수집기
- `common.rss_fetcher` (fetch_rss_feed, fetch_rss_feeds_concurrent) - 7개 수집기
- `common.markdown_utils` (markdown_table, markdown_link, html_reference_details 등) - 11개 수집기
- `common.translator` (get_display_title) - 5개 수집기
- `common.summarizer` (ThemeSummarizer) - 5개 수집기
- `common.utils` (request_with_retry, sanitize_string 등) - 8개 수집기
- `common.image_generator` (generate_news_briefing_card) - 동적 임포트, 7개 수집기

#### 중복 코드의 핵심 문제점

1. **초기화 보일러플레이트**: DedupEngine, PostGenerator, 날짜, 로거 설정이 모든 수집기에서 동일
2. **중복 검사 + 조기 종료 패턴**: `is_duplicate_exact` → `log_collection_summary` → `dedup.save()` → `return`이 모든 수집기에서 반복 (일부는 빈 데이터 경우까지 2-3회 반복)
3. **메트릭 로깅**: `log_collection_summary()` 호출이 수집기당 2-4회 (성공, 중복, 빈 데이터, 실패 각 분기마다)
4. **포스트 생성 후처리**: `mark_seen` → `save` → `log` 패턴 반복
5. **이미지 생성 try/except**: 거의 동일한 try/ImportError/Exception 블록이 7개 수집기에서 반복
6. **`time.monotonic()` vs `time.time()`**: 일관성 없음 (blockchain만 `time.time()` 사용)

---

## 2. 제안하는 BaseCollector ABC 인터페이스

### 2.1 데이터 클래스

```python
# scripts/common/base_collector.py

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from common.collector_metrics import log_collection_summary
from common.config import get_kst_now, setup_logging
from common.dedup import DedupEngine
from common.post_generator import PostGenerator, build_dated_permalink


@dataclass
class NewsItem:
    """수집된 뉴스 아이템의 표준 데이터 구조."""
    title: str
    link: str = ""
    source: str = ""
    description: str = ""
    description_ko: str = ""
    title_ko: str = ""
    published: str = ""
    tags: list[str] = field(default_factory=list)
    region: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """기존 dict 기반 코드와의 호환성을 위해 dict로 변환."""
        result = {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "description": self.description,
            "description_ko": self.description_ko,
            "title_ko": self.title_ko,
            "published": self.published,
            "tags": self.tags,
            "region": self.region,
        }
        result.update(self.extra)
        return result


@dataclass
class CollectionResult:
    """수집 결과를 표준화하는 데이터 구조."""
    items: list[dict[str, Any]] = field(default_factory=list)
    source_count: int = 0
    unique_items: int = 0
    post_created: int = 0
    extras: dict[str, Any] = field(default_factory=dict)
```

### 2.2 BaseCollector ABC

```python
class BaseCollector(ABC):
    """모든 수집기의 기반 추상 클래스.

    Template Method 패턴으로 run() 메서드가 전체 흐름을 관리하며,
    서브클래스는 fetch_data()와 build_content()만 구현하면 됩니다.

    Usage:
        class MyCollector(BaseCollector):
            def get_collector_name(self) -> str:
                return "collect_my_source"

            def get_category(self) -> str:
                return "my-category"

            def get_dedup_state_file(self) -> str:
                return "my_source_seen.json"

            def get_post_title(self, today: str) -> str:
                return f"내 소스 리포트 - {today}"

            def get_dedup_source_key(self) -> str:
                return "my_source"

            def fetch_data(self) -> CollectionResult:
                items = call_some_api()
                return CollectionResult(items=items, source_count=1)

            def build_content(self, result: CollectionResult) -> tuple[str, dict]:
                content = format_items(result.items)
                extra_fm = {"permalink": build_dated_permalink(...)}
                return content, extra_fm

        if __name__ == "__main__":
            MyCollector().run()
    """

    def __init__(self) -> None:
        self.logger = setup_logging(self.get_collector_name())
        self.now = get_kst_now()
        self.today = self.now.strftime("%Y-%m-%d")
        self.dedup = DedupEngine(self.get_dedup_state_file())
        self.generator = PostGenerator(self.get_category())
        self._started_at: float = 0.0

    # ── 추상 메서드 (서브클래스 필수 구현) ──

    @abstractmethod
    def get_collector_name(self) -> str:
        """수집기 이름 (로깅, 메트릭에 사용). 예: 'collect_blockchain'"""
        ...

    @abstractmethod
    def get_category(self) -> str:
        """PostGenerator 카테고리. 예: 'crypto-news', 'blockchain'"""
        ...

    @abstractmethod
    def get_dedup_state_file(self) -> str:
        """중복 검사용 상태 파일명. 예: 'blockchain_seen.json'"""
        ...

    @abstractmethod
    def get_post_title(self, today: str) -> str:
        """포스트 제목 생성. 예: f'블록체인 네트워크 리포트 - {today}'"""
        ...

    @abstractmethod
    def get_dedup_source_key(self) -> str:
        """dedup.is_duplicate_exact()에 전달할 source 키. 예: 'blockchain-metrics'"""
        ...

    @abstractmethod
    def fetch_data(self) -> CollectionResult:
        """데이터 수집 로직. API 호출, RSS 파싱 등을 수행.

        Returns:
            CollectionResult with items and source_count populated.
        """
        ...

    @abstractmethod
    def build_content(self, result: CollectionResult) -> tuple[str, dict[str, Any]]:
        """수집된 데이터를 마크다운 콘텐츠로 변환.

        Args:
            result: fetch_data()의 반환값

        Returns:
            (content_markdown, extra_frontmatter_dict) 튜플.
            extra_frontmatter에는 permalink, description, excerpt 등을 포함할 수 있음.
        """
        ...

    # ── 선택적 오버라이드 가능한 훅 메서드 ──

    def get_tags(self) -> list[str]:
        """포스트에 부여할 태그 목록. 기본값은 [카테고리명]."""
        return [self.get_category()]

    def get_slug(self) -> Optional[str]:
        """포스트 slug. None이면 PostGenerator가 자동 생성."""
        return None

    def get_lang(self) -> str:
        """포스트 언어. 기본값 'ko'."""
        return "ko"

    def get_image(self) -> str:
        """포스트 대표 이미지 경로. 기본값 빈 문자열."""
        return ""

    def get_source_for_post(self) -> str:
        """PostGenerator.create_post()에 전달할 source. 기본값은 dedup_source_key."""
        return self.get_dedup_source_key()

    def on_before_fetch(self) -> None:
        """데이터 수집 전 호출되는 훅. API 키 검증 등에 활용."""
        pass

    def on_after_fetch(self, result: CollectionResult) -> CollectionResult:
        """데이터 수집 후 가공 훅. enrichment, dedup_by_url 등에 활용.

        기본 구현은 result를 그대로 반환합니다.
        """
        return result

    def on_post_created(self, filepath: str) -> None:
        """포스트 생성 성공 후 호출되는 훅. 추가 처리에 활용."""
        pass

    def generate_briefing_image(self, result: CollectionResult) -> str:
        """브리핑 이미지를 생성하고 경로를 반환. 기본값: 빈 문자열 (이미지 없음).

        오버라이드하여 generate_news_briefing_card() 등을 호출하세요.
        이미 try/except 처리가 run()에서 수행되므로, 여기서는 예외를 그대로 발생시켜도 됩니다.
        """
        return ""

    def has_sufficient_data(self, result: CollectionResult) -> bool:
        """데이터가 포스트를 생성하기에 충분한지 검사. 기본값: items가 비어있지 않으면 True."""
        return bool(result.items)

    # ── 구체 메서드 (Template Method) ──

    def run(self) -> int:
        """수집기 실행의 전체 흐름을 관리하는 Template Method.

        Returns:
            0 = 성공 또는 정상 스킵, 1 = 실패
        """
        self._started_at = time.monotonic()
        collector_name = self.get_collector_name()
        self.logger.info("=== Starting %s ===", collector_name)

        post_title = self.get_post_title(self.today)

        # Step 1: 중복 검사
        if self.dedup.is_duplicate_exact(post_title, self.get_dedup_source_key(), self.today):
            self.logger.info("Post already exists for today, skipping")
            self._log_metrics(source_count=0, unique_items=0, post_created=0, extras={"status": "duplicate"})
            self.dedup.save()
            return 0

        # Step 2: 수집 전 훅
        self.on_before_fetch()

        # Step 3: 데이터 수집
        result = self.fetch_data()

        # Step 4: 수집 후 가공
        result = self.on_after_fetch(result)

        # Step 5: 충분한 데이터 검사
        if not self.has_sufficient_data(result):
            self.logger.warning("Insufficient data collected, skipping post")
            self._log_metrics(
                source_count=result.source_count,
                unique_items=0,
                post_created=0,
                extras={"status": "insufficient_data"},
            )
            self.dedup.save()
            return 0

        # Step 6: 콘텐츠 빌드
        content, extra_frontmatter = self.build_content(result)

        # Step 7: 브리핑 이미지 생성 (선택적)
        image_path = self.get_image()
        try:
            generated_image = self.generate_briefing_image(result)
            if generated_image:
                image_path = generated_image
        except ImportError as exc:
            self.logger.debug("Optional dependency unavailable: %s", exc)
        except Exception as exc:
            self.logger.warning("Briefing image generation failed: %s", exc)

        # Step 8: 포스트 생성
        filepath = self.generator.create_post(
            title=post_title,
            content=content,
            date=self.now,
            logical_date=self.today,
            tags=self.get_tags(),
            source=self.get_source_for_post(),
            lang=self.get_lang(),
            image=image_path,
            extra_frontmatter=extra_frontmatter,
            slug=self.get_slug(),
        )

        # Step 9: 결과 처리
        created = 0
        if filepath:
            created = 1
            self.dedup.mark_seen(post_title, self.get_dedup_source_key(), self.today)
            self.logger.info("Created post: %s", filepath)
            self.on_post_created(filepath)

        self.dedup.save()

        # Step 10: 메트릭 로깅
        unique_items = result.unique_items if result.unique_items else len(result.items)
        self._log_metrics(
            source_count=result.source_count,
            unique_items=unique_items,
            post_created=created,
            extras=result.extras,
        )

        self.logger.info("=== %s complete ===", collector_name)
        return 0

    def _log_metrics(
        self,
        source_count: int,
        unique_items: int,
        post_created: int,
        extras: Optional[dict[str, Any]] = None,
    ) -> None:
        """내부 메트릭 로깅 헬퍼."""
        log_collection_summary(
            self.logger,
            collector=self.get_collector_name(),
            source_count=source_count,
            unique_items=unique_items,
            post_created=post_created,
            started_at=self._started_at,
            extras=extras,
        )
```

### 2.3 다중 포스트 수집기를 위한 확장 (MultiPostCollector)

`collect_crypto_news.py`는 crypto-news와 security-alerts 두 개의 포스트를 생성합니다.
이런 경우를 위한 확장 클래스:

```python
@dataclass
class PostSpec:
    """하나의 포스트 생성에 필요한 명세."""
    title: str
    content: str
    category: str
    tags: list[str]
    source_key: str
    slug: Optional[str] = None
    extra_frontmatter: dict[str, Any] = field(default_factory=dict)
    image: str = ""


class MultiPostCollector(BaseCollector):
    """여러 포스트를 생성하는 수집기를 위한 확장 클래스.

    build_content() 대신 build_posts()를 구현하세요.
    """

    @abstractmethod
    def build_posts(self, result: CollectionResult) -> list[PostSpec]:
        """수집 결과에서 여러 포스트 명세를 생성."""
        ...

    def build_content(self, result: CollectionResult) -> tuple[str, dict[str, Any]]:
        """MultiPostCollector에서는 사용되지 않음. run()이 오버라이드됨."""
        raise NotImplementedError("Use build_posts() instead")

    def run(self) -> int:
        """다중 포스트 생성 흐름."""
        self._started_at = time.monotonic()
        collector_name = self.get_collector_name()
        self.logger.info("=== Starting %s ===", collector_name)

        self.on_before_fetch()
        result = self.fetch_data()
        result = self.on_after_fetch(result)

        if not self.has_sufficient_data(result):
            self.logger.warning("Insufficient data collected, skipping")
            self._log_metrics(source_count=result.source_count, unique_items=0, post_created=0)
            self.dedup.save()
            return 0

        posts = self.build_posts(result)
        created = 0

        for spec in posts:
            if self.dedup.is_duplicate_exact(spec.title, spec.source_key, self.today):
                self.logger.info("Post '%s' already exists, skipping", spec.title)
                continue

            gen = PostGenerator(spec.category)
            filepath = gen.create_post(
                title=spec.title,
                content=spec.content,
                date=self.now,
                logical_date=self.today,
                tags=spec.tags,
                source=spec.source_key,
                lang=self.get_lang(),
                image=spec.image,
                extra_frontmatter=spec.extra_frontmatter,
                slug=spec.slug,
            )

            if filepath:
                created += 1
                self.dedup.mark_seen(spec.title, spec.source_key, self.today)
                self.logger.info("Created post: %s", filepath)

        self.dedup.save()
        unique_items = result.unique_items if result.unique_items else len(result.items)
        self._log_metrics(
            source_count=result.source_count,
            unique_items=unique_items,
            post_created=created,
            extras=result.extras,
        )
        self.logger.info("=== %s complete ===", collector_name)
        return 0
```

---

## 3. 마이그레이션 전략

### 3.1 Phase 1: 기반 구축 (1-2일)

**목표**: BaseCollector ABC 생성 및 가장 단순한 수집기 1개 마이그레이션으로 검증

**작업 내용**:
1. `scripts/common/base_collector.py` 파일 생성
   - `NewsItem`, `CollectionResult`, `PostSpec` 데이터 클래스
   - `BaseCollector` ABC
   - `MultiPostCollector` 확장 클래스
2. `collect_blockchain.py`를 BaseCollector 기반으로 마이그레이션
   - 이유: 가장 단순한 구조 (단일 API 집계, 337줄, LOW 복잡도)
   - 기존 `main()` 함수는 `_legacy_main()`으로 보존 (롤백 가능)
3. 단위 테스트 작성: `tests/test_base_collector.py`

**수락 기준**:
- `python scripts/collect_blockchain.py` 실행 시 기존과 동일한 포스트 생성
- `python3 -m ruff check scripts/common/base_collector.py` 통과
- `_state/blockchain_seen.json` 상태 파일 호환성 유지

### 3.2 Phase 2: 단순 수집기 마이그레이션 (2-3일)

**목표**: API 데이터 집계형 수집기 3개 마이그레이션

**마이그레이션 대상** (복잡도 순):
1. `collect_fmp_calendar.py` - 다중 API, 단일 포스트, MEDIUM
2. `collect_defi_llama.py` - 단일 API, 단일 포스트, MEDIUM
3. `collect_political_trades.py` - RSS + API, 단일 포스트, MEDIUM

**각 수집기별 작업**:
- 기존 `main()` → `fetch_data()` + `build_content()` 분리
- 포맷팅 헬퍼 함수들은 그대로 유지 (수집기 파일 내 또는 common/formatters.py로 이동)
- `on_after_fetch()` 오버라이드: enrichment + dedup_by_url 적용

**수락 기준**:
- 각 수집기 실행 시 기존과 동일한 포스트 생성
- ruff check 통과
- 기존 상태 파일 호환성 유지

### 3.3 Phase 3: RSS 기반 수집기 마이그레이션 (2-3일)

**목표**: RSS 피드 + enrichment 패턴의 수집기 4개 마이그레이션

**마이그레이션 대상**:
1. `collect_regulatory.py` - 다중 지역 RSS, ThemeSummarizer 사용
2. `collect_worldmonitor_news.py` - WorldMonitor RSS, 복잡한 콘텐츠 빌드
3. `collect_geopolitical.py` - Polymarket + GDELT + RSS, 높은 복잡도
4. `collect_market_indicators.py` - 다중 API + RSS, BettaFishAnalyzer/SignalComposer

**주의사항**:
- ThemeSummarizer, BettaFishAnalyzer, SignalComposer 등 분석 모듈 사용 수집기는 `on_after_fetch()`에서 분석 결과를 `CollectionResult.extras`에 저장하는 패턴 활용
- `build_content()`에서 result.extras의 분석 결과를 참조하여 콘텐츠 생성

**수락 기준**:
- Phase 2와 동일 + ThemeSummarizer 연동 정상 작동 확인

### 3.4 Phase 4: 복잡 수집기 + MultiPostCollector (3-4일)

**목표**: 브라우저 세션 사용, 다중 포스트 생성 수집기 마이그레이션

**마이그레이션 대상**:
1. `collect_crypto_news.py` → **MultiPostCollector** (crypto-news + security-alerts)
2. `collect_stock_news.py` - BrowserSession 사용, 복잡한 데이터 수집
3. `collect_coinmarketcap.py` - 다중 API + BrowserSession + SignalComposer
4. `collect_social_media.py` - 텔레그램 + 트위터 + Reddit + RSS

**특별 처리**:
- `collect_crypto_news.py`: `MultiPostCollector` 사용. `build_posts()`에서 PostSpec 2개 반환
- BrowserSession 의존 수집기: `on_before_fetch()`에서 브라우저 세션 초기화, `fetch_data()` 내에서 사용
- SignalComposer/MindSpider: 선택적 임포트(`try/except ImportError`) 패턴 유지

**수락 기준**:
- `collect_crypto_news.py`가 crypto-news와 security-alerts 두 포스트 모두 정상 생성
- BrowserSession 미설치 환경에서도 fallback 정상 작동
- 기존 모든 수집기와 동일한 출력 생성

### 3.5 Phase 5: 정리 및 최적화 (1-2일)

**목표**: 레거시 코드 제거, 공통 유틸리티 정리

**작업 내용**:
1. 각 수집기의 `_legacy_main()` 제거
2. 중복된 포맷팅 함수를 `common/formatters.py`로 통합
   - `_fmt_number`, `_fmt_usd`, `_format_tvl` 등 여러 수집기에서 중복
3. `time.time()` → `time.monotonic()` 통일 (blockchain)
4. 공통 이미지 생성 로직을 `BaseCollector.generate_briefing_image()` 기본 구현으로 제공
5. 전체 ruff check + 통합 테스트 실행

**수락 기준**:
- `python3 -m ruff check scripts/` 전체 통과
- 모든 12개 수집기가 BaseCollector/MultiPostCollector 기반으로 작동
- 중복 포맷팅 함수가 `common/formatters.py`로 통합

---

## 4. 리스크 평가

### 4.1 높은 리스크

| 리스크 | 설명 | 완화 방안 |
|--------|------|-----------|
| **포스트 출력 변경** | 마이그레이션 중 HTML/마크다운 출력이 미묘하게 달라질 수 있음 | Phase별 before/after 출력 diff 비교 테스트. 기존 main()을 `_legacy_main()`으로 보존하여 A/B 비교 가능 |
| **상태 파일 호환성** | DedupEngine 상태 파일 경로/형식이 변경되면 중복 포스트 생성 | BaseCollector가 기존과 동일한 `DedupEngine(state_file)` 호출. 상태 파일 경로 변경 없음 |
| **브라우저 세션 수집기** | Playwright 의존 코드가 복잡하여 리팩토링 시 깨질 수 있음 | Phase 4로 후순위 배치. `on_before_fetch()`로 분리하되 내부 로직은 최소 변경 |

### 4.2 중간 리스크

| 리스크 | 설명 | 완화 방안 |
|--------|------|-----------|
| **다중 PostGenerator 인스턴스** | `collect_crypto_news.py`는 2개의 PostGenerator 사용 | MultiPostCollector에서 PostSpec별로 Generator 동적 생성 |
| **선택적 의존성** | SignalComposer, MindSpider, BettaFishAnalyzer의 `try/except ImportError` 패턴 | 각 수집기의 `fetch_data()` 내에서 기존 `try/except` 패턴 유지 |
| **GitHub Actions 크론** | 마이그레이션 중 크론 실행 시 오류 발생 가능 | Phase별 하나씩 마이그레이션. 실패 시 `_legacy_main()` 호출 fallback 추가 가능 |

### 4.3 낮은 리스크

| 리스크 | 설명 | 완화 방안 |
|--------|------|-----------|
| **임포트 경로 변경** | `sys.path.insert` 패턴 유지 필요 | BaseCollector 파일이 `scripts/common/` 내에 위치하므로 기존 경로 그대로 작동 |
| **타이머 불일치** | `time.time()` vs `time.monotonic()` | Phase 1에서 `time.monotonic()`으로 통일 |

---

## 5. 테스트 전략

### 5.1 단위 테스트 (Phase 1에서 작성)

```python
# tests/test_base_collector.py

class TestBaseCollector:
    """BaseCollector ABC의 계약 검증."""

    def test_abstract_methods_enforced(self):
        """추상 메서드 미구현 시 TypeError 발생 확인."""

    def test_run_skips_on_duplicate(self, tmp_path):
        """중복 포스트 감지 시 fetch_data() 호출 없이 스킵."""

    def test_run_skips_on_empty_data(self, tmp_path):
        """빈 데이터 수집 시 포스트 생성 없이 스킵."""

    def test_run_creates_post_on_success(self, tmp_path):
        """정상 수집 시 포스트 생성 및 dedup 마킹."""

    def test_run_logs_metrics(self, tmp_path):
        """모든 분기에서 log_collection_summary 호출 확인."""

    def test_hook_methods_called_in_order(self, tmp_path):
        """on_before_fetch → fetch_data → on_after_fetch → build_content 순서 검증."""

    def test_briefing_image_error_handled(self, tmp_path):
        """generate_briefing_image() 예외 시 포스트 생성은 계속 진행."""


class TestMultiPostCollector:
    """MultiPostCollector의 다중 포스트 생성 검증."""

    def test_creates_multiple_posts(self, tmp_path):
        """PostSpec 2개 반환 시 포스트 2개 생성."""

    def test_skips_duplicate_posts_individually(self, tmp_path):
        """개별 포스트 단위로 중복 검사 수행."""
```

### 5.2 마이그레이션 검증 테스트 (각 Phase에서)

```python
# tests/test_collector_migration.py

class TestCollectorMigrationParity:
    """마이그레이션된 수집기가 기존과 동일한 출력을 생성하는지 검증."""

    def test_blockchain_output_parity(self, mock_apis):
        """collect_blockchain.py: BaseCollector vs legacy 출력 비교."""

    def test_fmp_calendar_output_parity(self, mock_apis):
        """collect_fmp_calendar.py: BaseCollector vs legacy 출력 비교."""

    # ... 각 수집기별 테스트
```

### 5.3 통합 테스트 (Phase 5에서)

- 전체 12개 수집기 `--dry-run` 모드 실행 (API 모킹)
- `python3 -m ruff check scripts/` 전체 통과
- 기존 `_state/*.json` 파일과의 호환성 검증

---

## 6. 예상 효과

### 정량적 개선

| 지표 | 현재 | 마이그레이션 후 |
|------|------|----------------|
| 수집기당 보일러플레이트 코드 | 40-60줄 | 0줄 (BaseCollector에 통합) |
| 중복 log_collection_summary 호출 | 수집기당 2-4회 | 수집기당 0회 (BaseCollector.run()에서 관리) |
| 이미지 생성 try/except 블록 | 7개 수집기에서 반복 | 1곳 (BaseCollector.run()) |
| 새 수집기 추가 시 작성 코드 | ~100줄 보일러플레이트 + 비즈니스 로직 | ~10줄 메타데이터 + 비즈니스 로직만 |

### 정성적 개선

1. **일관성**: 모든 수집기가 동일한 흐름(초기화 → 중복검사 → 수집 → 검증 → 빌드 → 생성 → 로깅)을 따름
2. **테스트 용이성**: BaseCollector 테스트 한 번으로 공통 흐름 검증. 각 수집기는 fetch_data/build_content만 테스트
3. **확장성**: 새 수집기 추가 시 추상 메서드 5-6개만 구현하면 완료
4. **유지보수**: 메트릭 로깅 변경, 에러 처리 개선 등이 BaseCollector 한 곳에서 가능

---

## 7. 타임라인 요약

| Phase | 기간 | 작업 | 수집기 수 |
|-------|------|------|-----------|
| Phase 1 | 1-2일 | BaseCollector 생성 + blockchain 마이그레이션 | 1 |
| Phase 2 | 2-3일 | 단순 API 수집기 마이그레이션 | 3 |
| Phase 3 | 2-3일 | RSS 기반 수집기 마이그레이션 | 4 |
| Phase 4 | 3-4일 | 복잡 수집기 + MultiPostCollector | 4 |
| Phase 5 | 1-2일 | 정리 및 최적화 | - |
| **총합** | **9-14일** | | **12** |

---

## 8. 파일 구조 변경

```
scripts/common/
  base_collector.py        # NEW - BaseCollector ABC, MultiPostCollector, 데이터 클래스
  collector_metrics.py     # 기존 유지 (BaseCollector에서 호출)
  config.py                # 기존 유지
  dedup.py                 # 기존 유지
  formatters.py            # 기존 + 중복 포맷팅 함수 통합 (Phase 5)
  post_generator.py        # 기존 유지

tests/
  test_base_collector.py   # NEW - BaseCollector 단위 테스트
  test_collector_migration.py  # NEW - 마이그레이션 패리티 테스트
```

---

## 9. 마이그레이션 예시: collect_blockchain.py

### Before (현재)

```python
def main() -> int:
    started_at = time.time()
    now = get_kst_now()
    today = now.strftime("%Y-%m-%d")
    logger.info("=== Blockchain Network Report Collection Start (%s) ===", today)
    dedup = DedupEngine("blockchain_seen.json")
    gen = PostGenerator("blockchain")
    post_title = f"블록체인 네트워크 리포트 - {today}"
    if dedup.is_duplicate_exact(post_title, "blockchain-metrics", today):
        logger.info("Blockchain report already exists for %s, skipping", today)
        log_collection_summary(logger, collector="collect_blockchain", ...)
        return 0
    btc = fetch_btc_stats()
    eth = fetch_eth_stats()
    # ... 100줄의 보일러플레이트 + 비즈니스 로직 혼합
```

### After (리팩토링 후)

```python
from common.base_collector import BaseCollector, CollectionResult

class BlockchainCollector(BaseCollector):
    def get_collector_name(self) -> str:
        return "collect_blockchain"

    def get_category(self) -> str:
        return "blockchain"

    def get_dedup_state_file(self) -> str:
        return "blockchain_seen.json"

    def get_post_title(self, today: str) -> str:
        return f"블록체인 네트워크 리포트 - {today}"

    def get_dedup_source_key(self) -> str:
        return "blockchain-metrics"

    def get_tags(self) -> list[str]:
        return ["blockchain", "on-chain", "network-stats", "daily"]

    def get_slug(self) -> str:
        return "daily-blockchain-network-report"

    def fetch_data(self) -> CollectionResult:
        btc = fetch_btc_stats()
        eth = fetch_eth_stats()
        l2_projects = fetch_l2_summary()
        upgrade_news = fetch_upgrade_news()
        source_count = (1 if btc else 0) + (1 if eth else 0) + (1 if l2_projects else 0)
        return CollectionResult(
            items=[{"btc": btc, "eth": eth}],  # 최소 1개 아이템
            source_count=source_count,
            extras={"btc": btc, "eth": eth, "l2": l2_projects, "upgrade_news": upgrade_news},
        )

    def has_sufficient_data(self, result: CollectionResult) -> bool:
        return bool(result.extras.get("btc") or result.extras.get("eth"))

    def build_content(self, result: CollectionResult) -> tuple[str, dict]:
        btc = result.extras["btc"]
        eth = result.extras["eth"]
        l2 = result.extras.get("l2")
        news = result.extras.get("upgrade_news")
        content, description, excerpt = build_report_content(btc, eth, self.today, l2, news)
        permalink = build_dated_permalink("blockchain", self.today, "daily-blockchain-network-report")
        return content, {"permalink": permalink, "description": description, "excerpt": excerpt}

if __name__ == "__main__":
    raise SystemExit(BlockchainCollector().run())
```

**핵심 변화**: 보일러플레이트 40줄 제거, 비즈니스 로직만 남음. `build_report_content()` 함수는 그대로 유지.
