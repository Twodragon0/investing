# W17 주간 성과 보고서 (2026-04-14 ~ 2026-04-20)

## 커밋/변경 통계

| 지표 | 값 |
|------|-----|
| 총 커밋 수 | 15 |
| 변경 파일 수 | 142 |
| 코드 추가 | +7,850 lines |
| 코드 삭제 | -1,230 lines |
| 병합 PR 수 | 5 |
| 생성 포스트 수 | 38 |

## 주요 PR 및 기능

### TimeSeriesStore 5-Phase 구현 (Phase 1~5 완료)
TimeSeriesStore는 시계열 데이터의 상태 관리, 검증, 마이그레이션을 담당하는 추상화 계층입니다.

- **Phase 1**: `scripts/common/time_series_state.py` (360줄, 48 tests, 6 issue codes, CLI 3종)
  - State 저장소 (JSON serialization, atomic write)
  - Validation 계층 (STALE, OUTLIER, MISSING, MISMATCH, FUTURE, UNKNOWN)
  - CLI: inspect, validate, migrate
  - 멱등성 보장 + rollback 지원

- **Phase 2**: `collect_defi_llama.py` 통합 (15 tests, rebase write-time 방어)
  - TimeSeriesStore와 수집기 연동
  - 중복 검사 + dedup 호환성
  - DeFi TVL 이력 자동 추적

- **Phase 3**: `signal_tracker.py` 이주 (29 tests, btc_price nullable)
  - 시장 신호 추적 (상관관계, 임계값)
  - Bitcoin 가격 선택적 필드 처리
  - 과거 데이터 마이그레이션

- **Phase 4**: CI 통합 (`code-quality.yml` + `continuous-improvement-loop.yml`)
  - 자동 품질 검사 (ruff format + type check)
  - 주간 개선 루프 연동
  - 에러 리포팅 및 Slack 알림

- **Phase 5**: `fix_defi_tvl_history.py` 래퍼 축소
  - 이전 마이그레이션 도구 → 유틸리티로 축소
  - TimeSeriesStore 기반 재구현

### DefiLlama 데이터 품질 개선 (P0)
DefiLlama의 최신 v2 API가 26일 동안 스테일 캐시를 사용 중으로 발견되어 v1 API로 마이그레이션합니다.

- `/v2/protocols` 스테일 문제 (26일) → `/protocols` v1 + CEX 필터 전환
  - 원인: v2 CDN 캐싱 정책 변경
  - 해결: v1 API 직접 호출 + CEX 제외 필터 추가
  
- 실증: $247.99B 고정값 → $145.17B 실시간 데이터 반영
  - Wrapped token 제외 후 순환 자산 중복 제거
  - DEX/Lending protocol만 포함
  
- 전환 공지 포스트 `_posts/2026-04-20-defillama-v1-migration-notice.md` 발행
  - 이용자 투명성 확보

### 포스트 설명 품질 개선 (P1)
Description Quality Pipeline을 개선하여 synthetic description 생성 품질을 향상시켰습니다.

- `description_ko` 중복 검출 62% → 0% (post_generator.py 수정)
  - 원인: enrichment.py의 _is_desc_duplicate_of_title() 로직 미적용
  - 수정: post_generator와 동기화, 제목 유사도 > 0.85 필터링

- Description Quality CI 체크: coverage 92% (check_description_quality)
  - 포스트 품질 측정 (실제 콘텐츠 > 90% 목표)
  - Boilerplate 검출 및 경고 (> 30%)

- 과거 포스트 보정 script: coverage 96% (fix_post_descriptions)
  - 이미 발행된 포스트 일괄 수정
  - Dry-run 모드 제공

### 시장 신호 테이블 개선 (P2~P3)
일일 마켓 서머리의 신호 테이블을 더 명확하고 덜 선동적으로 개선했습니다.

- 시간 프레임 라벨 추가 (`| 기간 |` 컬럼)
  - 1H, 4H, 1D, 1W 명시
  - 트레이더 이용성 향상

- 제목 낚시성 제거: 개별 altcoin 지표 → 대표 지표 전환
  - 제거: `HYPE -5.9%`, 가상 altcoin 지표
  - 추가: BTC, ETH, Alt Index 위주
  - 신호 신뢰도 향상

### 긴급 경보 시스템 설계 (P4)
현재 CRITICAL 경보가 80% 수준으로 과도하여 임계값을 재설계합니다.

- CRITICAL 판정 로직 재설계: threshold 6.0 도달 불가 → 4.0~4.5 재조정
  - 과거: 점수 계산 오류로 최고값 5.8만 도달
  - 현재: 5.0 점수 = 모든 신호 악화 (과도)
  - 목표: 4.0~4.5 = 2~3개 신호 동시 악화 시만 CRITICAL

- Scientist 분석: 현재 CRITICAL 80% → 목표 3%
  - 자동 분석 결과 반영
  - A/B 테스트 틀 준비 (W18)

- `risk_classifier.py` 모듈 기초 구현 (Phase 1)
  - 신호 가중치 로직 (signal_tracker 연동)
  - Threshold validation CLI

- 설계 문서: `critical-alert-redesign.md` (605줄)
  - 기존 문제점, 재설계 전략, 구현 계획

### 부수 개선
- DeFi TVL 차트 2026-04-20 v1 전환 annotation
  - 트레이더에게 데이터 출처 변경 알림
  
- signal_history accuracy 6건 백필
  - 과거 신호 재계산 및 검증
  
- CI 복구: ruff format 5회 연속 실패 → SUCCESS (7 files format 적용)
  - Python 코드 스타일 통일
  
- PR 정리: dependabot 5건 squash merge (697~701), #623 close (306 commits drift)
  - 의존성 업데이트 정리
  - 오래된 브랜치 정리

## 수집기 현황

| 카테고리 | 포스트 수 |
|----------|-----------|
| 기타 | 8 |
| 주식 시장 | 3 |
| 경제 캘린더 | 3 |
| DeFi TVL | 3 |
| 암호화폐 뉴스 | 3 |
| 지정학 리스크 | 3 |
| 정치인 거래 | 3 |
| 소셜 미디어 | 3 |
| 글로벌 이슈 | 2 |
| 블록체인 | 2 |
| **합계** | **38** |

## 버그 수정 및 개선

### 수정된 버그
- DefiLlama v2 API 스테일 데이터 문제 (26일 캐시)
- description_ko 중복 생성 로직 (post_generator.py)
- ruff format 대상 7개 파일 자동 포맷팅

### 새로 추가된 기능
- TimeSeriesStore 추상화 (state, validation, query 분리)
- Risk classifier 기초 모듈 (threshold 재조정 로직)
- DeFi signal_history 정확성 백필 (6건)

## 테스트 및 커버리지

| 항목 | 수치 |
|------|------|
| 신규 테스트 수 | 92 |
| 총 테스트 수 | 3,864 |
| TimeSeriesStore 테스트 | 48 |
| Description Quality 커버리지 | 92% |
| Fix Post Descriptions 커버리지 | 96% |

## 생성 문서

| 문서 | 줄 수 | 용도 |
|------|------|------|
| data-quality-guard-design.md | 268 | 데이터 품질 검증 파이프라인 |
| observability.md | 308 | 모니터링 및 추적 아키텍처 |
| critical-alert-redesign.md | 605 | 긴급 경보 임계값 재설계 |

## CI/CD 상태

CI/CD 상태는 GitHub Actions 대시보드에서 확인하세요: https://github.com/Twodragon0/investing/actions

주요 체크 항목:
- Jekyll Deploy
- Lighthouse CI
- Code Quality (ruff)
- Description Quality
- Coverage
- Continuous Improvement Loop

## 주요 설계 의사결정

### TimeSeriesStore 아키텍처
- 상태 저장소 (time_series_state.py): 1,948줄 이상 변경 시 데이터 무결성 보장
- 검증 계층 (validation): issue code 6종 (STALE, OUTLIER, MISSING 등)
- CLI 3종 도구 (inspect, validate, migrate)

### Risk Threshold 재조정
- 과거 threshold 6.0 → 현재 CRITICAL 80% (과도 경보)
- 재조정 목표: 4.0~4.5 (CRITICAL 3% 달성)
- Scientist 기반 데이터 분석으로 검증 중

### DefiLlama 마이그레이션 전략
- `/v2/protocols` → `/protocols` v1 + CEX 필터
- 현재 $247.99B (고정) → 향후 $145.17B+ (실시간)
- 공지 포스트 + 차트 annotation으로 투명성 확보

## 다음 주 계획 (W18)

1. Risk classifier Phase 2 구현 (임계값 검증 자동화, A/B 테스트 틀 구축)
2. DeFi signal_history 나머지 48건 백필 및 과거 데이터 정합성 검증
3. Critical alert redesign 최종 배포 (3% CRITICAL 달성 확인)

---

**위키 페이지** (OMC wiki 저장)
- session-log: W17 타임라인 및 의사결정 기록
- data-quality-guard-design: 품질 검증 아키텍처
- p4-threshold-validation: 긴급 경보 재설계 검증 로그

**참고 링크**
- Commit history: `git log --oneline | head -15`
- TimeSeriesStore PR: Phase 1~5 통합
- DefiLlama migration notice: `_posts/2026-04-20-defillama-v1-migration-notice.md`
- Critical alert design: `docs/critical-alert-redesign.md`

---

*작성: 2026-04-21 11:30 KST*