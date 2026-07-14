# investing 기술부채 리팩토링 계획 (2026-07)

> 작성일: 2026-07-13 · 작성자: planner (코드 수정 없음, 계획 문서 전용)
> 스타일 참고: `docs/refactoring-plan-base-collector.md`
> 본 문서의 모든 수치는 실측(grep / pytest --cov)에 근거한다. 측정 시점 커밋: `a0335ed19`.

---

## 0. 측정 요약 (실측 근거)

세 항목을 실행하기 전, 저장소 현재 상태를 실측했다. **일부 항목은 원 지시의 가정과 다르므로 계획을 조정한다.**

| 대상 | 실측 값 | 명령 근거 |
|------|---------|-----------|
| `scripts/common/enrichment.py` | 1,186줄 / 커버리지 **98%** (528 stmt, 9 miss) | `wc -l`, `pytest --cov` |
| `scripts/common/bettafish_analyzer.py` | 1,625줄 / 커버리지 **100%** (646 stmt, 0 miss) | 동일 |
| 커버리지 게이트 | `--cov-fail-under=55` (`pyproject.toml:65`) | `grep` |
| **전체 커버리지 (TOTAL)** | **68%** (23,043 stmt, 7,427 miss) | `pytest --cov=scripts` |

### 실측이 뒤집은 가정 (중요)

1. **전체 커버리지가 이미 68%다.** 게이트 55는 실제보다 13%p 낮다. 즉 `55→60→65`는 **신규 테스트 없이 게이트만 올리는 "래칫(ratchet) 단계"**이고, 실질 신규 테스트가 필요한 구간은 **65→70뿐**이다.
2. **`bettafish_analyzer.py`는 이미 100% 커버리지다.** P2-B 분해의 테스트 리스크는 사실상 0이다 — 기존 테스트가 회귀를 즉시 잡는다.
3. **`summary_sections.py`는 이미 98% 커버리지다** (607 stmt, 10 miss). 원 지시가 P3 "미테스트 대형 모듈" 예시로 지목했으나, 실제 미테스트 대형 모듈은 **`og_visuals.py`(4%)** 다.

---

## 1. P2-A: `enrichment.py` 네트워크 코어 분리

### 1.1 현재 상태

`enrichment.py`(1,186줄)는 **이미 두 차례 분리를 거친 파사드**다. 상단에서 다음을 재-export 한다(패턴 확립됨):

```python
from .enrichment_images import (  # noqa: F401  (re-exported for backward compat)
    _is_valid_image_url, is_logo_like_url, match_bad_image_pattern, match_logo_pattern,
)
from .enrichment_synthetic import (  # noqa: F401  (re-exported for backward compat)
    _analyze_korean_title, _is_desc_duplicate_of_title, generate_synthetic_description, ...
)
```

- `enrichment_images.py` (135줄, 100% cov), `enrichment_synthetic.py` (763줄, 100% cov) — **본 분리의 정확한 템플릿.**
- `enrichment.py`에는 상단 `__all__`(12개 심볼)과 모듈 상수(`MAX_IMAGES_PER_DIGEST`, `_gnews_url_cache`, `_USER_AGENT`, `_BROWSER_UA`, `_IMAGE_META_PATTERNS`, `_EXCLUDE_CLASS_RE` 등)가 있다.

**남은 "네트워크 코어" 심볼과 내부 호출 그래프** (`enrichment.py:118-1186` 실측):

| 심볼 | 줄 | 호출 대상(내부) |
|------|-----|-----------------|
| `is_private_url` (→ utils.`is_private_url_target` 위임) | 129 | (leaf) |
| `_decode_google_news_base64` | 257 | (leaf) |
| `_resolve_google_news_url` / `_inner` | 291 / 314 | `is_private_url`, `_decode_google_news_base64`, `requests` |
| `_resolve_via_gnewsdecoder` | 413 | `is_private_url` |
| `_fetch_og_image` | 466 | `is_private_url`, `requests` |
| `_extract_og_metadata` | 695 | (leaf) |
| `_extract_via_readability` / `_bs4_article` / `_paragraphs` | 782 / 821 / 859 | (leaf) |
| `fetch_page_metadata` | 873 | `_resolve_google_news_url`, `_extract_*`, `requests` |
| `fetch_page_description` | 957 | `fetch_page_metadata` |
| `_fetch_and_parse_page` | 965 | `fetch_page_metadata` |

**파사드에 남을 오케스트레이터** (네트워크 코어를 호출):

- `fetch_images_concurrent` (542) → `_fetch_og_image`, `_resolve_google_news_url`
- `fetch_descriptions_concurrent` (620) → `fetch_page_metadata`, `_resolve_google_news_url`
- `enrich_item` (995) / `enrich_items` (1072) → 위 두 오케스트레이터 + `generate_synthetic_description`

### 1.2 난점: @patch 밀결합 (전 테스트 파일 실측)

`grep -rhoE 'common\.enrichment\.SYMBOL' tests/` 재확인 결과:

| patch 타깃 | 총 사용 횟수 (전 tests/) |
|-----------|--------------------------|
| `common.enrichment.requests` | **62** |
| `common.enrichment.is_private_url` | **21** |
| `common.enrichment._decode_google_news_base64` | 18 |
| `common.enrichment._resolve_via_gnewsdecoder` | 17 |
| `common.enrichment.fetch_page_metadata` | 16 |
| `common.enrichment._resolve_google_news_url` | 8 |
| `common.enrichment._fetch_og_image` | 8 |
| `common.enrichment.fetch_images_concurrent` | 4 |
| `common.enrichment.fetch_descriptions_concurrent` | 4 |
| `common.enrichment._fetch_and_parse_page` | 2 |
| `common.enrichment._extract_via_readability` | 2 |
| `common.enrichment.sanitize_mojibake` | 3 (이동 안 함 — encoding_guard 재-export) |

관련 테스트 파일: `test_enrichment.py`, `test_enrichment_bad_image.py`, `test_enrichment_logo.py`, `test_enrichment_utils.py`, `test_pattern_parity.py`, `test_rss_fetcher_extended.py`, `test_image_rejection_metrics.py`, `test_import_compatibility.py`.

**@patch 네임스페이스 함정 (본 작업의 핵심 리스크):**

`@patch("common.enrichment._resolve_google_news_url")`는 **`common.enrichment` 모듈 네임스페이스의 이름을 리바인딩**한다. 심볼을 `enrichment_network.py`로 옮기고 `from .enrichment_network import _resolve_google_news_url`로 재-export하면 `common.enrichment._resolve_google_news_url`는 여전히 존재해 patch 가능하지만 — **`enrichment_network` 내부의 다른 함수(예: `fetch_page_metadata`)가 호출하는 `_resolve_google_news_url`은 `enrichment_network` 네임스페이스에서 해석**되므로 `common.enrichment.*` patch가 가로채지 못한다.

따라서 재배치 규칙은 **"호출자가 사는 모듈"** 기준이다:
- 호출자가 파사드(`enrichment.py`)에 남는 오케스트레이터 → patch는 `common.enrichment.*` 유지 (재-import된 전역이므로 여전히 동작).
- 호출자가 이동한 함수 → patch를 `common.enrichment_network.*`로 재배치 필수.

### 1.3 외부 호출부 (재-export 계약 반드시 보존)

`is_private_url` / `_resolve_google_news_url` 외부 참조(실측): `scripts/common/rss_fetcher.py`(`:175`에서 `from .enrichment import is_private_url` **함수 내부 지연 import**), `browser.py`, `markdown_utils.py`, `utils.py`. 이들은 `from common.enrichment import ...` 계약에 의존 → `__all__` + 재-export를 **깨뜨리면 안 됨**.

### 1.4 단계별 실행 순서 (검증 게이트 포함)

> 원칙: leaf부터 이동, 한 배치마다 `python3 -m pytest tests/test_enrichment*.py tests/test_rss_fetcher_extended.py tests/test_pattern_parity.py tests/test_import_compatibility.py -q` 그린 확인 후 다음 배치. patch 재배치는 이동과 **같은 커밋**에서 처리(임시 red 방지).

- **0단계 — 스캐폴딩.** `scripts/common/enrichment_network.py` 신규 생성(모듈 docstring에 `enrichment_images.py` 스타일 재-export 설명). 아직 심볼 이동 없음.
  - 게이트: `python3 -m ruff check scripts/ tests/` + `ruff format --check`.

- **1단계 — leaf 이동.** `is_private_url`(래퍼), `_decode_google_news_base64`, `_extract_og_metadata`, `_extract_via_readability/_bs4_article/_paragraphs`, 관련 상수(`_USER_AGENT`, `_BROWSER_UA`, `_IMAGE_META_PATTERNS`, `_EXCLUDE_CLASS_RE`, `_gnews_url_cache`)를 network 모듈로 이동. `enrichment.py`는 `from .enrichment_network import (...) # noqa: F401` 재-export.
  - **patch 재배치**: `is_private_url`(21), `_decode_google_news_base64`(18), `_extract_via_readability`(2) 중 **테스트가 검증하는 상위 함수가 이동 대상일 때** `common.enrichment_network.*`로 변경. (leaf를 직접 검증하는 테스트는 `common.enrichment.*` 유지 가능하나, 혼선 방지를 위해 network 모듈 심볼은 원칙적으로 network 경로로 통일 권장.)
  - 게이트: 위 pytest 서브셋 그린.

- **2단계 — resolver 체인 이동.** `_resolve_google_news_url`(+`_inner`), `_resolve_via_gnewsdecoder`, `_fetch_og_image` 이동 + 재-export.
  - **patch 재배치**: `_resolve_google_news_url`(8), `_resolve_via_gnewsdecoder`(17), `_fetch_og_image`(8). 이들은 서로/leaf를 호출하므로 network 내부 호출은 `common.enrichment_network.*` 패치만 유효 → **전부 재배치**.
  - 게이트: pytest 서브셋 그린.

- **3단계 — 페이지 메타데이터 이동.** `fetch_page_metadata`, `fetch_page_description`, `_fetch_and_parse_page` 이동 + 재-export.
  - **patch 재배치**: `fetch_page_metadata`(16), `_fetch_and_parse_page`(2). 단, **`fetch_descriptions_concurrent`(파사드 잔류)가 `fetch_page_metadata`를 호출하는 테스트**는 재-import 전역이 존재하므로 `common.enrichment.fetch_page_metadata` 유지가 정답 — 테스트별로 "무엇을 exercise 하는지"로 판별. 판별 규칙을 리뷰 체크리스트에 명시.
  - 게이트: pytest 서브셋 그린.

- **4단계 — `requests` patch 재배치.** 62개 `common.enrichment.requests` 중 **network 함수를 직접 exercise하는** 테스트는 `common.enrichment_network.requests`로 변경. 오케스트레이터를 exercise하되 내부에서 network를 patch로 대체하는 테스트는 network 경로. (오케스트레이터 자체가 `requests`를 직접 쓰지 않으므로 사실상 대부분 network 경로로 이동.)
  - 게이트: **전체** `python3 -m pytest -q` 그린 + `pytest --cov=scripts/common/enrichment.py --cov=scripts/common/enrichment_network.py` 로 두 모듈 합산 커버리지 ≥ 기존 98% 확인.

- **5단계 — 정리.** `enrichment.py` `__all__` 유지 검증(`is_private_url`, `fetch_page_metadata` 등 여전히 노출), dead import 제거(ruff `F401` 예외 주석만 남김), `test_import_compatibility.py`로 `from common.enrichment import *` 계약 확인.
  - 게이트: `ruff check` + `ruff format --check` + 전체 pytest + `basedpyright`(옵셔널 import 함정 회피, MEMORY 참조).

### 1.5 리스크와 완화책

| 리스크 | 심각도 | 완화책 |
|--------|--------|--------|
| @patch 네임스페이스 오배치로 mock이 무력화 → 테스트가 **실제 네트워크 호출** (green이지만 flaky/느림) | 높음 | 배치마다 `-p no:cacheprovider`로 전체 실행; mock 미적용 시 `requests` 실호출을 감지하도록 network 함수 진입점에 이미 있는 `is_private_url` SSRF 가드가 예외를 던지는지 확인. CI에서 네트워크 차단 환경 권장 |
| 재-export 누락 → 외부 4개 모듈(`rss_fetcher` 등) ImportError | 중 | `test_import_compatibility.py` 게이트, `__all__` 불변 검증 |
| 로컬 ruff/pytest는 통과하나 CI red (basedpyright / format) | 중 | MEMORY 교훈(`feedback_basedpyright_optional_import`, 만성 워크플로우 실패) 반영 — 푸시 전 `basedpyright` + `ruff format --check` 필수 |
| `_gnews_url_cache` 전역 상태가 두 모듈에 흩어져 캐시 미스 | 낮음 | 캐시는 network 모듈로 완전 이동, 파사드는 참조 안 함 |

### 1.6 예상 규모

- 신규 파일 1개(`enrichment_network.py`, ~450-550줄 예상), 수정 파일: `enrichment.py`(축소) + 테스트 6-8개.
- **patch 재배치 사이트 약 130-160개** (requests 62 중 다수 + resolver/metadata 계열). 대부분 mechanical sed지만 3단계의 "호출자 판별"은 수동.
- 난이도: **높음** (코드 이동 자체는 쉬우나 patch 재배치 정확성이 전부). 규모 대비 테스트 diff가 큼.

---

## 2. P2-B: `bettafish_analyzer.py` (1,625줄) 분해

### 2.1 현재 상태

- 1,625줄, 커버리지 **100%** (646 stmt, 0 miss) — `test_bettafish_analyzer.py`가 공개 클래스를 **직접 생성자 import**로 검증(예: `from common.bettafish_analyzer import DataPerspective`). **@patch 밀결합 없음** → P2-A와 대조적으로 분해 리스크가 낮다.
- 외부 소비자(실측): `scripts/collect_market_indicators.py:25`, `scripts/collect_coinmarketcap.py:40` — 둘 다 `from common.bettafish_analyzer import BettaFishAnalyzer`. 그리고 모듈 내부 `:1342` 지연 self-import 존재(보존 필요).

### 2.2 책임 단위 분석 → 서브모듈 경계 (실측 줄 범위)

`grep -nE '^(class|def) '` 기준 클래스 지도:

| 서브모듈(신규) | 포함 심볼 | 줄 범위 | 대략 크기 | 의존 방향 |
|----------------|-----------|---------|-----------|-----------|
| `bettafish_models.py` | `ReportChapter`, `AnalysisReport` (dataclass) + 헬퍼 `_verdict_to_score`, `_score_to_verdict`, `_confidence_from_agreement`, `_format_list_inline` | 34-133 | ~100줄 | leaf |
| `bettafish_perspectives.py` | `DataPerspective`, `SentimentPerspective`, `MacroPerspective` | 134-663 | ~530줄 | models |
| `bettafish_insight.py` | `InsightForge` | 664-1101 | ~440줄 | models |
| `bettafish_synthesis.py` | `ForumSynthesis` | 1102-1332 | ~230줄 | models |
| `bettafish_analyzer.py` (파사드 잔류) | `BettaFishAnalyzer` + 모듈 함수 `analyze`/`generate_report_markdown`/`generate_brief_outlook` | 1333-끝 | ~290줄 | 위 전부 |

의존 그래프는 단방향 트리(models ← perspectives/insight/synthesis ← analyzer)로 순환 없음. `BettaFishAnalyzer.analyze()`가 세 perspective + InsightForge + ForumSynthesis를 인스턴스화하므로 파사드가 모두 import.

> 참고: perspectives 3개는 `_build_narrative` 패턴을 공유하고 합쳐도 ~530줄(coding-style 상한 800 이내)이라 **한 파일 유지**를 기본안으로 한다. 추후 필요 시 3분할 가능하나 현 시점 speculative 분할은 금지(karpathy-guidelines §2).

### 2.3 파사드 유지 전략

`bettafish_analyzer.py`가 계속 진입점이 되도록 상단에서 재-export (enrichment 패턴과 동일):

```python
from .bettafish_models import AnalysisReport, ReportChapter  # noqa: F401
from .bettafish_perspectives import (  # noqa: F401
    DataPerspective, MacroPerspective, SentimentPerspective,
)
from .bettafish_insight import InsightForge  # noqa: F401
from .bettafish_synthesis import ForumSynthesis  # noqa: F401
```

- `test_bettafish_analyzer.py`의 모든 import 경로(`from common.bettafish_analyzer import X`)가 **변경 없이 통과** → 테스트 diff 0을 목표.
- `:1342` self-import 및 외부 2개 collector import 계약 보존.

### 2.4 단계별 실행 순서 (검증 게이트 포함)

- **1단계**: `bettafish_models.py` 추출(leaf) + 파사드 재-export. 게이트: `pytest tests/test_bettafish_analyzer.py tests/test_import_compatibility.py -q` 그린.
- **2단계**: `bettafish_synthesis.py`(ForumSynthesis, models만 의존) 추출. 게이트: 동일.
- **3단계**: `bettafish_insight.py`(InsightForge) 추출. 게이트: 동일.
- **4단계**: `bettafish_perspectives.py`(3 perspective) 추출. 게이트: 동일 + `collect_market_indicators.py`/`collect_coinmarketcap.py` import 스모크(`python -c "import scripts.collect_market_indicators"` 상당).
- **5단계**: 정리 — 파사드 100% 커버리지 재확인(`pytest --cov=scripts/common/bettafish_analyzer.py --cov=scripts/common/bettafish_*` 합산 = 100% 유지), `ruff` + `basedpyright`.

### 2.5 리스크와 완화책

| 리스크 | 심각도 | 완화책 |
|--------|--------|--------|
| 재-export 누락 → 외부 collector 2개 + 테스트 import 실패 | 중 | 파사드 `__all__`/재-export, import 스모크 게이트 |
| 헬퍼 함수 순환 참조(perspectives ↔ synthesis가 같은 헬퍼 사용) | 낮음 | 헬퍼는 전부 models(leaf)로 격리, 하위 모듈은 models만 import |
| `from __future__ import annotations` 누락으로 타입 힌트 평가 오류 | 낮음 | 각 신규 파일 상단에 원본과 동일하게 선언 |

### 2.6 예상 규모

- 신규 파일 4개(models/perspectives/insight/synthesis), 파사드 1개 축소. **테스트 수정 0줄 목표**(재-export가 계약 흡수).
- 난이도: **중** (100% 커버리지 + @patch 없음 → 회귀 즉시 감지, P2-A보다 훨씬 안전).

---

## 3. P3: 커버리지 게이트 55 → 70 단계 상향

### 3.1 현재 상태 (실측)

- 게이트: `--cov-fail-under=55` (`pyproject.toml:65`).
- **실측 TOTAL = 68%** (23,043 stmt, 7,427 miss).
- 산술: 70% 도달 = miss ≤ `23043 × 0.30 = 6,913` → **추가로 ~514 stmt 커버 필요**. 60/65는 현재 68%로 **이미 충족**.

### 3.2 미달(저커버리지) 모듈 랭킹 — miss stmt 기준 상위

`scripts/common/`(공유·단위테스트 용이) 우선, 그다음 진입점 스크립트:

| 모듈 | 커버리지 | miss stmt | 성격 |
|------|----------|-----------|------|
| **`common/og_visuals.py`** | **4%** | **354** | 순수 렌더링 모듈, 최대 단일 레버 |
| `generate_og_images.py` | 51% | 135 | OG 이미지 진입점 |
| `common/og_compose.py` | 38% | 88 | OG 합성 헬퍼 |
| `common/og_image_formats.py` | 26% | 28 | 포맷 유틸 |
| `common/image_rejection_metrics.py` | 64% | 29 | 메트릭 |
| (진입점, 후순위) `backfill_post_summaries.py` 518 / `collect_geopolitical.py` 406 / `collect_social_media.py` 393 / `generate_weekly_digest.py` 334 … | 다양 | 대량 | `main()`/부작용 다수, ROI 낮음 |

> **핵심 통찰**: `og_visuals.py`(354) + `generate_og_images.py`(135) + `og_compose.py`(88) = **577 stmt > 필요 514**. 즉 **"OG 렌더링 계열" 집중 테스트 캠페인 하나로 70% 도달 가능**. 진입점 스크립트(수백 miss)는 건드리지 않아도 됨.

### 3.3 단계별 로드맵 (게이트 상향 + 신규 테스트)

- **P3-1: 55 → 60 (래칫, 신규 테스트 0).** `pyproject.toml:65`을 `--cov-fail-under=60`. 이미 68%라 즉시 그린. **목적: 기존 커버리지 잠금(회귀 방지 바닥 상향).**
  - 게이트: `pytest --cov=scripts -q` 통과(≥60).
  - 권장: `ci-config-guard` 스킬로 "게이트가 다시 낮아지면 실패"하는 회귀 가드 추가 검토.

- **P3-2: 60 → 65 (래칫, 신규 테스트 0).** `--cov-fail-under=65`. 68%라 즉시 그린.
  - 게이트: 동일(≥65).

- **P3-3: 65 → 70 (신규 테스트 필요 구간).** 목표 delta ~+2%p (~514 stmt).
  1. **`og_visuals.py` 신규 테스트** (최우선, 354 stmt / 4%): 각 draw/render 함수 단위 테스트. `test_bettafish_analyzer.py`처럼 순수 함수는 입력→출력, Pillow 렌더는 결정적 시드 + `_render_generated_image` 디스크 probe **patch로 고정**(MEMORY `feedback_golden_master_hermetic` 교훈 — 골든마스터 비-격리 함정 회피).
  2. **`generate_og_images.py`** (135 stmt / 51%): 렌더 경로 + graceful-skip 분기.
  3. **`og_compose.py` / `og_image_formats.py`** (88+28): 합성·포맷 유틸 단위 테스트.
  - 커버 순서상 (1)만으로도 ~354 stmt → TOTAL ≈ 69.5%, (2) 일부 추가 시 70% 돌파. **(1)+(2) 완료 후 게이트를 `--cov-fail-under=70`.**
  - 게이트: `pytest --cov=scripts --cov-report=term-missing -q` ≥70, 신규 테스트 파일 `test_og_visuals.py` 등 그린, `ruff`+`basedpyright`.

### 3.4 리스크와 완화책

| 리스크 | 심각도 | 완화책 |
|--------|--------|--------|
| Pillow 렌더 테스트가 폰트/OS 의존으로 로컬 통과·CI red | 높음 | 디스크 probe·폰트 로드를 patch로 고정, 시드 결정화. MEMORY 골든마스터 교훈 준수. 픽셀 완전일치 대신 "예외 없이 이미지 크기/모드 반환" 계약 검증 우선 |
| 게이트 상향 후 다른 PR이 저커버리지 코드 추가 → CI red 확산 | 중 | 단계별로 올리되 각 단계에서 **여유 마진 확인**(68%에서 60/65는 8/3%p 여유). 70은 여유가 얇으므로 (1)+(2) 초과 달성 후 상향 |
| 진입점 스크립트로 커버리지 채우려다 부작용/네트워크 테스트 남발 | 중 | 진입점은 P3 범위에서 **명시적 제외**. `common/` 순수 모듈만 대상 |
| P2-A/P2-B 리팩토링이 커버리지 총계 흔듦 | 낮음 | 두 작업 모두 재-export로 커버리지 보존 설계 → 순증 없음. P3는 P2 완료 후 재측정 |

### 3.5 예상 규모

- P3-1/P3-2: `pyproject.toml` 1줄 × 2회, 신규 테스트 0. 난이도 **낮음**.
- P3-3: 신규 테스트 파일 2-4개(`test_og_visuals.py` 중심), ~300-500줄 테스트. 난이도 **중** (Pillow 결정화가 관건).

---

## 4. 통합 우선순위 및 타임라인

의존성: 세 항목은 독립적이나, **P3 최종 측정은 P2 완료 후** 재실행 권장(총계 흔들림 방지).

| 순서 | 항목 | 난이도 | 신규/수정 | 근거 |
|------|------|--------|-----------|------|
| 1 | **P3-1/P3-2** (게이트 55→65 래칫) | 낮음 | pyproject 2줄 | 즉시 실행 가능, 회귀 바닥 잠금. **가장 높은 ROI** |
| 2 | **P2-B** (bettafish 분해) | 중 | 신규 4파일, 테스트 0 | 100% 커버·@patch 없음 → 안전. 파사드 패턴 검증 겸 |
| 3 | **P3-3** (og_visuals 테스트 → 게이트 70) | 중 | 신규 테스트 2-4파일 | 커버리지 실질 상향 |
| 4 | **P2-A** (enrichment 네트워크 분리) | 높음 | 신규 1파일 + patch 130-160사이트 | 리스크 최고 → 마지막, 앞선 작업으로 패턴 숙달 후 |

각 항목 완료 조건(공통 게이트): `python3 -m ruff check scripts/ tests/` + `ruff format --check` + 대상 pytest 서브셋 그린 + 푸시 전 `basedpyright`(옵셔널 import CI red 회피).

---

## 5. 범위 밖 (명시적 비목표)

- 진입점 스크립트(`collect_*`, `backfill_*`, `generate_weekly_*`) 커버리지 상향 — P3에서 제외(부작용·ROI 문제).
- `summary_sections.py`(98%), `bettafish_analyzer.py`(100%) 신규 테스트 — 이미 충분.
- perspectives 3-way 추가 분할 — 현 필요 없음(speculative 금지).
- 기존 동작/공개 API 변경 — 세 항목 전부 **행위 보존 리팩토링**. 재-export로 외부 계약 불변 유지.

---

## 부록 A. 재현 명령

```bash
# 전체 커버리지 (느림, i18n 제외 시 tests 서브셋 권장)
python3 -m pytest --cov=scripts --cov-report=term-missing -q -p no:cacheprovider

# P2-A patch 사이트 재확인
grep -rhoE 'common\.enrichment\.[a-zA-Z_]+' tests/ | sort | uniq -c | sort -rn

# 파일 크기/구조
wc -l scripts/common/enrichment.py scripts/common/bettafish_analyzer.py
grep -nE '^(class|def) ' scripts/common/bettafish_analyzer.py

# 게이트 위치
grep -n cov-fail-under pyproject.toml   # → 65:addopts = "--cov=scripts --cov-fail-under=55"
```
