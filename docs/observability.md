# Observability (관찰성)

> **작성일**: 2026-04-17 | **범위**: 수집기 건강성 모니터링, 캐시 효율 추적, 성능 튜닝

이 문서는 Investing Dragon 프로젝트의 **관찰성 구조**를 설명합니다. 관찰성이란 수집기가 정상 작동하는지, 성능이 저하되는 신호가 있는지를 **런타임 메트릭**으로 파악하는 능력입니다. 본 문서는 시간이 지남에 따라 다양한 관찰성 도구가 추가될 수 있도록 설계된 기반 문서입니다.

---

## 1. 목차

1. [개요](#개요)
2. [DNS SSRF 가드 캐시 스냅샷](#dns-ssrf-가드-캐시-스냅샷)
3. [튜닝 가이드](#튜닝-가이드)
4. [샘플 로그](#샘플-로그)
5. [CI/cron 통합](#cicron-통합)
6. [참조 문서](#참조-문서)

---

## 개요

Investing Dragon의 수집 파이프라인(`.github/workflows/` + `scripts/collect_*.py`)은 다음과 같은 건강 지표를 추적합니다:

- **수집 메트릭**: source_count, unique_items, post_created, duration
  - 위치: `scripts/common/collector_metrics.py`의 `log_collection_summary()`
  - 형식: 정구조화 로그(`collection-summary` 레이블)

- **DNS 캐시 상태**: 현재 SSRF 방어 캐시의 점유율, TTL, 용량
  - 위치: `scripts/common/utils.py:134-158`의 `dns_cache_snapshot()`
  - 용도: DNS rebinding 공격 방어 효율성 및 메모리 압력 모니터링

- **시계열 상태 정합성** (향후):
  - 위치: `scripts/common/time_series_state.py` (예정)
  - 용도: `_state/*.json` 시계열 파일의 오염 감지 및 자동 정제

---

## DNS SSRF 가드 캐시 스냅샷

### 함수 시그니처

```python
def dns_cache_snapshot() -> dict:
    """Return a point-in-time snapshot of the DNS SSRF guard cache.

    Intended for collector observability: log this dict (or inject into
    ``log_collection_summary`` extras) at the end of a collection run to
    track whether ``maxsize`` is saturated.

    Returns a dict with keys:
    - ``dns_cache_size``: number of entries currently cached (thread-safe read).
    - ``dns_cache_maxsize``: configured cache capacity.
    - ``dns_cache_ttl_seconds``: configured entry TTL.
    """
```

**반환값**:
- `dns_cache_size`: 현재 캐시된 항목 수 (정수)
- `dns_cache_maxsize`: 캐시 최대 용량 (기본값: 256)
- `dns_cache_ttl_seconds`: 항목 TTL (기본값: 300초 = 5분)

### 기본 사용 예시

**1단계: import**

```python
from common.utils import dns_cache_snapshot
```

**2단계: 수집기 끝에서 스냅샷 로깅**

```python
# scripts/collect_crypto_news.py (예시)

class CryptoNewsCollector(BaseCollector):
    # ...

    def run(self) -> None:
        self._started_at = time.monotonic()
        items = self.fetch()
        items = self.process(items)
        # ... 포스트 생성 ...

        # 수집 완료 시 DNS 캐시 상태 기록
        dns_snapshot = dns_cache_snapshot()
        logger.info("DNS cache snapshot: %s", dns_snapshot)
```

**3단계: 메트릭 요약에 주입**

`log_collection_summary()` 함수의 `extras` 파라미터에 DNS 스냅샷을 추가하면 정구조화 로그에 통합됩니다:

```python
from common.collector_metrics import log_collection_summary
from common.utils import dns_cache_snapshot

# ... 수집 작업 ...

dns_snapshot = dns_cache_snapshot()
log_collection_summary(
    logger,
    collector="crypto_news",
    source_count=100,
    unique_items=45,
    post_created=12,
    started_at=self._started_at,
    extras=dns_snapshot,  # DNS 캐시 메트릭 주입
)
```

이 방식으로 기록되면 로그에 다음과 같이 나타납니다:

```
INFO collection-summary collector=crypto_news source_count=100 unique_items=45 post_created=12 duration=2.34s dns_cache_size=42 dns_cache_maxsize=256 dns_cache_ttl_seconds=300
```

---

## 튜닝 가이드

DNS 캐시 구성 요소:

| 항목 | 기본값 | 범위 | 설명 |
|------|--------|-----|------|
| `maxsize` | 256 | 64~1024 | 동시 보관 가능 호스트명 수 |
| `ttl` | 300s | 60~3600s | 캐시 항목 유효 기간 (초) |

### 튜닝 시나리오

**시나리오 A: dns_cache_size가 지속적으로 매우 낮음**

```
지속 관찰: size < maxsize * 0.2 (예: 256 중 50 미만)
```

**원인**: 수집기가 접근하는 고유 호스트명이 적음
**판단**: 현재 크기 설정이 과다 할당됨 (하지만 메모리 비용 무시할 수준)
**권장 조치**: **조정 불필요** — 캐시는 경량이고 메모리 영향 미미

**시나리오 B: dns_cache_size가 지속적으로 높음**

```
지속 관찰: size >= maxsize * 0.8 (예: 256 중 205 이상)
```

**원인**: 수집 대상이 많은 고유 호스트명에서 데이터를 가져옴
**위험**: 정상 호스트명이 TTL 만료 전에 캐시에서 제거되어 불필요한 재 DNS 해석 비용 발생
**권장 조치**:
1. `scripts/common/utils.py:112`의 `maxsize` 값 상향 검토 (예: 256 → 512)
2. 변경 후 프로덕션 재배포 및 1주일 관찰
3. 여전히 높으면 1024로 조정

**시나리오 C: DNS 캐시 크기 정상, TTL 단축 고려**

```
TTL이 300초보다 짧아야 하는 경우:
- DNS rebinding 공격 우려가 매우 높음
- 상류 DNS에 TTL이 짧은 레코드 변경 추적 필요
```

**권장 조치**:
1. 보안 위험 평가
2. `ttl` 값 감소 (예: 300 → 120초)
3. 성능 영향 1주일 모니터링

---

## 샘플 로그

### JSON 로그 예시

수집기가 완료 시 기록하는 JSON 구조:

```json
{
  "dns_cache_size": 42,
  "dns_cache_maxsize": 256,
  "dns_cache_ttl_seconds": 300
}
```

### 정구조화 로그 예시 (GitHub Actions)

```
2026-04-17T06:30:45Z INFO [collect_crypto_news] collection-summary collector=crypto_news source_count=280 unique_items=45 post_created=12 duration=14.56s dns_cache_size=42 dns_cache_maxsize=256 dns_cache_ttl_seconds=300
```

### 로그 해석

| 필드 | 값 | 해석 |
|------|-----|------|
| `dns_cache_size` | 42 | 현재 280개 호스트명 중 42개가 캐시됨 (정상) |
| `dns_cache_maxsize` | 256 | 최대 256개까지 보관 가능 |
| `dns_cache_ttl_seconds` | 300 | 5분 후 자동 만료 |

---

## CI/cron 통합

### 1. 기존 수집기에 DNS 메트릭 추가

각 `scripts/collect_*.py` 끝부분을 다음과 같이 수정:

```python
from common.utils import dns_cache_snapshot
from common.collector_metrics import log_collection_summary

# ... 수집 및 포스트 생성 로직 ...

# 메트릭 로깅
dns_snapshot = dns_cache_snapshot()
log_collection_summary(
    self.logger,
    collector=self.name,
    source_count=len(items),
    unique_items=len(processed_items),
    post_created=self._created_count,
    started_at=self._started_at,
    extras=dns_snapshot,  # ← DNS 캐시 메트릭 추가
)
```

### 2. 주기적 모니터링 워크플로우

`.github/workflows/continuous-improvement-loop.yml` 또는 별도 `observe-dns-cache.yml`에서 DNS 메트릭 수집:

```yaml
name: Observe DNS Cache
on:
  schedule:
    - cron: '0 */6 * * *'  # 6시간마다 (수집 주기와 동일)
  workflow_dispatch:

jobs:
  monitor-dns-cache:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/python-collect
      - name: Run collectors with observability
        run: |
          python scripts/collect_crypto_news.py
          python scripts/collect_stock_news.py
          # ... 다른 수집기 ...
      - name: Extract DNS metrics from logs
        run: |
          grep "dns_cache_size=" logs/collection.log | tail -10
      - name: Alert on saturation
        if: failure()
        uses: 8398a7/action-slack@v3
        with:
          status: custom
          custom_payload: |
            DNS cache is approaching saturation (>80%). Review tuning guide.
```

### 3. 로그 분석 (로컬)

수집 완료 후 DNS 캐시 상태 확인:

```bash
# 최근 10회 수집의 DNS 캐시 메트릭 추출
grep "dns_cache_size=" logs/collection.log | tail -10

# 샘플 출력:
# INFO collection-summary collector=crypto_news ... dns_cache_size=42 dns_cache_maxsize=256 dns_cache_ttl_seconds=300
```

---

## 참조 문서

### 핵심 파일

| 파일 | 역할 | 라인 |
|------|------|------|
| `scripts/common/utils.py` | DNS 캐시 구현 및 스냅샷 함수 | 106–158 |
| `scripts/common/collector_metrics.py` | 메트릭 로깅 유틸리티 | 전체 |
| `scripts/common/base_collector.py` | 수집기 기반 클래스 | 전체 |

### 관련 PR & 이슈

- **PR #628**: DNS SSRF 가드 및 `dns_cache_snapshot()` 함수 추가
- **Issue**: DNS rebinding 공격 방어 (TTLCache 도입 배경)

### 확장 계획

향후 다음 관찰성 도구가 추가될 예정입니다:

1. **시계열 상태 검증** (`scripts/common/time_series_state.py`)
   - `_state/*.json` 오염 감지 및 자동 정제
   - 참조: `docs/data-quality-guard-design.md`

2. **포스트 생성 효율 메트릭**
   - 부분 실패 비율, enrichment 캐시 hit rate

3. **API 응답 시간 추적**
   - 느린 상류 API 식별

---

## 추가 문의

관찰성 기능 추가 시:
1. `scripts/common/` 아래 새 함수/클래스 추가
2. `scripts/common/collector_metrics.py`의 `log_collection_summary()` 또는 새 함수로 통합
3. 본 문서의 관련 섹션 업데이트
4. 테스트: `python3 -m ruff check scripts/`
