# DeFi TVL History 데이터 품질 가드 설계

> **작성일**: 2026-04-17 | **상태**: 설계안(Draft) | **범위**: `_state/*.json` 시계열 상태 파일 정합성
> **트리거**: `_state/defi_tvl_history.json`에서 `2026-04-11 total_tvl=0` 오염 발견 → `scripts/fix_defi_tvl_history.py`로 일회성 정리 완료. 재발 방지 가드 필요.

---

## 1. 현황 분석

### 1-1. 오염 재현 — 증거 수집

| 근거 위치 | 관찰 내용 |
|-----------|-----------|
| `scripts/collect_defi_llama.py:139-166` | `_check_tvl_staleness()`가 `_save_tvl_history()`를 호출 내부에서 직접 수행. 분석 함수와 부수효과(파일 쓰기)가 한 함수에 결합됨 |
| `scripts/collect_defi_llama.py:144` | `total_tvl = round(sum(p.get("tvl", 0) or 0 for p in protocols), 2)` — `protocols=[]`이면 `total_tvl=0`이 되고, 이 값이 **어떤 검증도 없이** `history.append()`됨 |
| `scripts/collect_defi_llama.py:149-151` | 동일 `today` 중복은 제거하지만, **타임스탬프 정렬은 보장되지 않음**. 과거 날짜를 재실행하면 리스트 끝에 삽입됨 |
| `scripts/collect_defi_llama.py:1050-1058` | `run()`에서 `if not protocols and not chains: return`만 확인. `protocols=[]`이고 `chains=[...]`인 부분 실패 경로에서는 `build_post_content`가 호출되고 line 798에서 `_check_tvl_staleness(protocols, today)`가 여전히 실행되어 `total_tvl=0`이 기록됨 |
| `_state/defi_tvl_history.json` | 2026-03-19 ~ 2026-04-17 전 구간이 **동일한 값(247985919043.14)** 으로 채워져 있음 — API 스테일/캐시 문제는 별도 존재. 본 설계 범위는 구조적 오염(0/음수/순서/중복) 방어 |
| `scripts/fix_defi_tvl_history.py:32-53` | 이미 `clean_history()`가 `total_tvl<=0 제거 → dedupe → 정렬` 세 단계를 수행. 이 로직이 쓰기 경로에도 동일하게 적용되어야 함 |

### 1-2. 시계열 상태 파일 식별

```
_state/defi_tvl_history.json   — list[{date, total_tvl}]          (scripts/collect_defi_llama.py)
_state/signal_history.json     — list[SignalSnapshot+accuracy]    (scripts/common/signal_tracker.py)
```

`_state/*_seen.json` 계열(`crypto_news_seen`, `fmp_calendar_seen` 등)은 **dict-of-hash 맵**이므로 시계열 정렬/영값 개념이 없음 → 본 가드 범위 외. `DedupEngine`(`scripts/common/dedup.py`)이 `_prune()`으로 이미 커버.

### 1-3. 재사용 가능한 자산

- `scripts/common/signal_tracker.py:109-123` `_save_history()` — 원자적 쓰기(`os.replace`) 패턴 확립.
- `scripts/common/signal_tracker.py:126-131` `_prune_old_entries()` — TTL 기반 정제 존재. 유효성 검증만 누락.
- `scripts/common/config.py` — `setup_logging()`, `get_env()` 표준 진입점.
- `scripts/fix_defi_tvl_history.py:32-53` — 정제 로직의 **참조 구현**. 검증/마이그레이션에서 재사용.

---

## 2. 문제 모델링 (오염 유형 분류)

| ID | 유형 | 원인 | 현재 탐지 여부 | 심각도 |
|----|------|------|----------------|--------|
| **C1** | Zero/음수 값 | API 부분 실패 시 `sum([])=0` 기록 | 탐지 안 됨 | High |
| **C2** | 타임스탬프 역순 삽입 | 과거 날짜 수동 재실행, 타임존 경계 | 탐지 안 됨 | Medium |
| **C3** | 동일 날짜 중복 | 6시간 주기 cron → 중복 제거 로직 부분 존재 | `_check_tvl_staleness` line 149 부분 존재 | Low |
| **C4** | 스키마 위반 | 필수 필드 누락 (`date`/`total_tvl`) | 탐지 안 됨(런타임 KeyError) | Medium |
| **C5** | 상한 초과 / 이상치 | API 버그로 폭등 | 탐지 안 됨 | Low |
| **C6** | 정적 값 고착(staleness) | API 캐시(현재 발생 중) | `_check_tvl_staleness`가 경고만, 기록은 막지 않음 | Medium |
| **C7** | 비원자적 쓰기 JSON 깨짐 | 프로세스 킬, 디스크 풀 | `os.replace()` 사용 → 완화됨 | Low |

**본 설계 1차 타깃**: C1~C4 (구조적 오염). C5는 warning 로그만, C6은 별도 이슈, C7은 현 상태 유지.

---

## 3. 아키텍처 옵션

### 옵션 A — BaseCollector에 `TimeSeriesStateMixin` 추가 (통합형)

**장점**: 기존 BaseCollector 생태계 자연스럽게 통합, 신규 시계열 추가 시 클래스 변수만 선언.
**단점**: `signal_tracker.py`는 collector가 아니라 단독 사용 불가, 기존 top-level 함수(`_save_tvl_history`)를 전부 메서드로 리팩터해야 함.

### 옵션 B — 독립 `common/time_series_state.py` 모듈 (헬퍼형, **권장**)

수집기 상속 구조와 무관한 순수 함수 + 경량 클래스 모듈.

```
scripts/common/time_series_state.py
    ├── @dataclass TimeSeriesSchema  (필수 필드, 검증자 주입)
    ├── class TimeSeriesStore
    │     ├── load(validate=True) -> list[dict]
    │     ├── append(record, *, on_invalid="skip") -> AppendResult
    │     ├── compact() -> CompactionReport
    │     └── validate(records) -> list[ValidationIssue]
    └── CLI: python -m common.time_series_state --check <file>
```

**장점**: collector와 common 헬퍼 모두 동일 API 사용, 단일 테스트 타깃, CI에서 CLI 직접 호출 가능, `fix_defi_tvl_history.py` 로직을 그대로 흡수.
**단점**: 수집기 측에 "한 줄 추가" 보일러플레이트 잔존.

### 옵션 C — CI 전용 검증 (쓰기 경로 유지)

**부결**: "쓰기 시점 방어" 요구사항 위반, 재발 방지 불가.

### 권장: **옵션 B 채택**. Collector는 `TimeSeriesStore`를 직접 인스턴스화해 사용.

---

## 4. 권장안

### 4-1. 모듈 구조

```python
# scripts/common/time_series_state.py  (신규 ~180 lines)

@dataclass
class Bounds:
    min_exclusive: float | None = None
    max_exclusive: float | None = None

@dataclass
class TimeSeriesSchema:
    required_fields: list[str]
    numeric_fields: dict[str, Bounds]
    date_field: str = "date"
    date_format: str = "%Y-%m-%d"
    max_entries: int | None = None
    allow_null_fields: list[str] = field(default_factory=list)

@dataclass
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str  # "ZERO_VALUE" / "UNSORTED" / "DUPLICATE_DATE" / "MISSING_FIELD"
    index: int
    message: str

class TimeSeriesStore:
    def __init__(self, path: Path, schema: TimeSeriesSchema, logger=None): ...
    def load(self, *, validate: bool = True) -> list[dict]: ...
    def append(self, record: dict, *, on_invalid: Literal["skip","raise"] = "skip") -> AppendResult: ...
    def compact(self) -> CompactionReport: ...
    def validate(self, records: list[dict]) -> list[ValidationIssue]: ...
```

### 4-2. 쓰기 시점(write-time) 방어 — C1, C2, C4 차단

**원칙**: 검증 실패 = 해당 시도만 스킵, 기존 히스토리 유지 (graceful degradation).

```python
# scripts/collect_defi_llama.py (변경 지점: line 139-166)
_TVL_SCHEMA = TimeSeriesSchema(
    required_fields=["date", "total_tvl"],
    numeric_fields={"total_tvl": Bounds(min_exclusive=0)},
    date_field="date",
    max_entries=30,
)
_TVL_STORE = TimeSeriesStore(_TVL_HISTORY_PATH, _TVL_SCHEMA, logger)

def _check_tvl_staleness(protocols, today):
    total_tvl = round(sum(p.get("tvl", 0) or 0 for p in protocols), 2)
    appended = _TVL_STORE.append({"date": today, "total_tvl": total_tvl}, on_invalid="skip")
    if not appended.ok:
        logger.warning("TVL 기록 스킵: %s", appended.reason)
        return None
    history = _TVL_STORE.load(validate=False)
    return _compute_staleness_warning(history, _TVL_STALE_DAYS)
```

**전략 선택**:
- 검증 실패 시 재시도 금지 — cron(`'52 */6 * * *'`)이 자연 재실행
- `last_valid_repeat` 모드 **미도입** — 동일 값 반복 기록이 staleness 오탐 유발

### 4-3. 읽기 시점(read-time) 가드

`load(validate=True)`가 `validate()`를 수행:
- **error 레벨**: 로그 경고 + 원본 보존 + in-memory 필터링 뷰 반환
- **warning 레벨**: 로그만

**파일 자동 수정은 읽기 경로에서 수행하지 않음** — race condition 회피, 수정은 CLI(`--fix`) 또는 CI에서만.

### 4-4. 범위 확장

| 파일 | 관리 코드 | 우선순위 |
|------|-----------|----------|
| `_state/defi_tvl_history.json` | `collect_defi_llama.py:113-166` | **P0** (실제 오염) |
| `_state/signal_history.json` | `signal_tracker.py:93-131` | P1 (`btc_price:null` 백필 스크립트 존재) |
| 향후 신규 시계열 | - | P2 |

### 4-5. CI / 워크플로우 통합

**신규 워크플로우는 만들지 않음**. 기존 `.github/workflows/code-quality.yml`에 스텝 추가:

```yaml
- name: Validate time-series state files
  run: |
    python -m common.time_series_state --check _state/defi_tvl_history.json
    python -m common.time_series_state --check _state/signal_history.json
```

**실패 정책**:
- error → 워크플로우 실패(exit 1), PR 머지 차단
- warning → `::warning::` 어노테이션, exit 0
- 자동 복구 없음 — main 브랜치 직접 쓰기 금지

추가: `continuous-improvement-loop.yml`에 `--check --dry-run` 조기 경보.

### 4-6. 테스트 전략

- **레이어 1 (단위)**: `tests/test_time_series_state.py` — `ValidationIssue.code`별 1개, `append`의 `on_invalid` 분기, `compact()` 멱등성
- **레이어 2 (property-based, hypothesis)**: "append가 성공/실패 무관하게 파일은 항상 유효 스키마" 불변식
- **레이어 3 (회귀 fixture)**: 실제 오염 스냅샷(`tests/fixtures/corrupted_defi_tvl_history.json`) → `compact()` 결과가 `fix_defi_tvl_history.py`와 동일
- **레이어 4 (하위 호환)**: `tests/test_fix_defi_tvl_history.py`는 래퍼 버전에서도 통과

### 4-7. 마이그레이션

1. 1회성 정제: `python -m common.time_series_state --fix _state/defi_tvl_history.json --apply`
2. `fix_defi_tvl_history.py` → 신규 모듈로 위임하는 얇은 래퍼로 재작성 (하위 호환, 테스트 보존)
3. `signal_history.json`도 동일 CLI로 1회 검증
4. 한 달 고정값 문제(API 캐시)는 **본 설계 범위 외** — 별도 이슈

---

## 5. 구현 단계

### Phase 1 — 모듈 뼈대
- [ ] `scripts/common/time_series_state.py` 작성
- [ ] `tests/test_time_series_state.py` 레이어 1+2
- [ ] `ruff check` 통과

### Phase 2 — defi_llama 이주
- [ ] `collect_defi_llama.py:104-166` 리팩터 (`TimeSeriesStore` 사용)
- [ ] `_save_tvl_history`, `_load_tvl_history` 제거
- [ ] 회귀 테스트 추가

### Phase 3 — signal_tracker 이주
- [ ] `signal_tracker.py:93-131` 교체
- [ ] `btc_price` nullable 허용 (`allow_null_fields`)

### Phase 4 — CI 통합
- [ ] `code-quality.yml`에 validate 스텝
- [ ] `continuous-improvement-loop.yml`에 dry-run 조기 경보

### Phase 5 — 정제 스크립트 일원화
- [ ] `fix_defi_tvl_history.py` → 래퍼 축소
- [ ] `test_fix_defi_tvl_history.py` 통과 유지
- [ ] `CLAUDE.md` "Important Notes" 업데이트

---

## 6. 리스크 및 완화책

| # | 리스크 | 영향 | 완화책 |
|---|--------|------|--------|
| R1 | `append` 실패로 staleness 경고가 며칠간 사라짐 | 중 | collector 로그 `WARNING` 명시, `continuous-improvement-loop`에서 24h `append` 실패율 집계 |
| R2 | 정제 시 과거 포스트 재현 불가 | 낮 | 정제 전 `defi_tvl_history.json.bak.YYYYMMDD` 백업 커밋 |
| R3 | CI 검증 실패로 핫픽스 지연 | 중 | `[skip time-series-check]` escape hatch + 주간 감사 |
| R4 | `signal_history`의 `btc_price:null` 허용이 `total_tvl`에 잘못 적용 | 중 | 스키마를 **파일별 분리**, 공유 복붙 금지 |
| R5 | `load(validate=True)` 비용으로 수집기 지연 | 낮 | O(n log n), 최대 30 entries → 무시 가능 |
| R6 | hypothesis 의존성 추가 | 낮 | `requirements-dev.txt`에만 추가 |
| R7 | 오염된 파일 위 `append` 실패로 무한 경고 | 중 | `load(validate=True)`는 in-memory 필터만, 파일 수정은 CLI로만 |

---

## 7. 오픈 질문

1. **Q1**: `_check_tvl_staleness`가 `sum=0` 자체를 경고로 쓰나? → **아니오**, 스테일 검사에만 사용. 필터링 채택.
2. **Q2**: "30 entries" 제한을 Schema로 끌어올리나? → **Yes**. 단일 정의점.
3. **Q3**: Phase 2에서 `run()` 가드를 `or`로 변경? → **미변경**. 수정 포인트는 `_check_tvl_staleness` 내부의 `store.append`만.
4. **Q4**: CI escape hatch가 security rule에 저촉되나? → 자격증명 아니므로 직접 충돌 없음, 주간 감사로 남용 방지.
5. **Q5**: `signal_history.json`의 nested `accuracy` 필드 1차 지원? → **No**. `extra_fields_allowed=True`로 통과, Phase 6에서 확장.
6. **Q6**: dedup 정책 "나중 우선" 유지? → **Yes**. 최신 API 응답 신뢰도 우선. `tests/test_fix_defi_tvl_history.py:43-52`에 계약 문서화.

---

## References

- `scripts/collect_defi_llama.py:139-166` — 오염 발생 경로
- `scripts/collect_defi_llama.py:144` — `sum([])=0` 생성 지점
- `scripts/collect_defi_llama.py:1050-1058` — 부분 실패 가드(AND 조건 우회 가능)
- `scripts/fix_defi_tvl_history.py:32-53` — 정제 3단계 참조 구현
- `scripts/common/signal_tracker.py:109-123` — 원자적 쓰기 재사용 대상
- `scripts/common/signal_tracker.py:126-131` — TTL 기반 정제(활용)
- `scripts/common/base_collector.py:42-80` — BaseCollector 계약
- `scripts/common/dedup.py:49-60` — 원자적 저장/상태 로드 참고
- `.github/workflows/code-quality.yml:177-181` — validate 스텝 삽입 위치
- `.github/workflows/collect-defi-llama.yml:3-6` — `'52 */6 * * *'` 주기
- `tests/test_fix_defi_tvl_history.py:13-81` — 유지해야 할 기존 계약
- `_state/defi_tvl_history.json` — 오염 증거
- `scripts/common/config.py:171-178` — `setup_logging()` 표준
