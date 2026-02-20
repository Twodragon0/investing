# 지속적 개선 우선순위

## P0 - 안정성 (이번 주)

1. **CI 워크플로우 안정성 유지**
   - `classify-workflow-failures.yml` 자동 실패 분류 활성 상태 유지
   - 네트워크 vs 코드 오류 분류 결과를 Slack 알림에 포함
   - 재시도 결과를 이슈 본문에 기록하여 디버깅 가속화

2. **워크플로우 품질 게이트 강화**
   - `actionlint` 어노테이션 + PR 코멘트 upsert 유지
   - 워크플로우 문법 오류 발견 시 즉시 실패 처리

3. **포스트 렌더링 일관성 유지**
   - `scripts/common/markdown_utils.py` 헬퍼로 소스 태그/참조 생성
   - 수집기에서 직접 인라인 `<span class="source-tag">...` 사용 금지

4. **GitHub App 연동 가시성 강화**
   - Vercel/Sentry GitHub App 설치 및 연결 상태 확인
   - 배포/알림 흐름에서 웹훅 누락 또는 권한 이슈 점검

## P1 - 관측성 (다음)

1. **수집기 완료 로그 표준화**
   - 공통 로그 스키마: `source_count`, `unique_items`, `post_created`, `duration`
   - 모든 수집기에 적용: crypto, stock, social, regulatory, political, worldmonitor, coinmarketcap, defi_llama

2. **워크플로우 실패 분류 개선**
   - 중복 키 (`workflow + run + sha`) 유지, 분류 근거 스니펫 첨부
   - 이슈 본문에 재실행 결과 추적하여 디버깅 가속

3. **배포 검증 로깅**
   - 배포 후 간단 확인 요약 추가 (최신 포스트 URL + 렌더링 상태)

## P2 - 콘텐츠 품질 (P0/P1 이후)

1. **생성 포스트 구조 검증**
   - 섹션 순서 및 필수 블록 검증 (요약/테이블/참조/푸터)
   - 엣지 케이스 테스트 확대 (긴 링크, 혼합 소스, 빈 참조)

2. **과거 포스트 일관성 유지**
   - 생성기 포맷 변경 시 주요 반복 포스트 유형 재생성
   - 핫픽스 필요 시 외에는 수동 포스트 편집 금지

## 운영 규칙

- 유틸리티/함수 재사용 우선, 스크립트별 인라인 HTML 조립 금지
- 푸시 전 `py_compile + fixture smoke + jekyll build` 검증
- 커밋은 작고 목적에 집중 (롤백 용이)
- 운영/보안/UI/UX는 루프 리포트의 멀티 에이전트 포럼 항목에서 병렬 검토
