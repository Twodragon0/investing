# W41 주간 성과 보고서 (2026-10-05 ~ 2026-10-11)

## 커밋/변경 통계

| 지표 | 값 |
|------|-----|
| 총 커밋 수 | 154 |
| 변경 파일 수 | 29,539 |
| 코드 추가 | +49,130 lines |
| 코드 삭제 | -29,807 lines |
| 병합 PR 수 | 1 |
| 생성 포스트 수 | 102 |

## 주요 PR 및 기능

- Merge branch 'main' of https://github.com/Twodragon0/investing

## 수집기 현황

| 카테고리 | 포스트 수 |
|----------|-----------|
| 기타 | 28 |
| DeFi | 7 |
| 암호화폐 뉴스 | 7 |
| DeFi TVL | 7 |
| 글로벌 이슈 | 7 |
| 소셜 미디어 | 7 |
| 주식 시장 | 7 |
| 지정학 리스크 | 7 |
| 정치인 거래 | 7 |
| 경제 캘린더 | 7 |
| 블록체인 | 6 |
| 시장 지표 | 5 |
| **합계** | **102** |

## 이미지 거부 패턴 통계

- 기간: 2026-04-23T08:54:23 ~ 2026-10-11T15:06:37

| 패밀리 | 버킷 | 건수 |
|--------|------|------|
| bad_image | ext:gif | 2707 |
| bad_image | default-image | 1989 |
| bad_image | placeholder | 561 |
| bad_image | ext:ico | 196 |
| bad_image | ext:svg | 164 |
| bad_image | tracker | 160 |
| bad_image | blank. | 105 |
| bad_image | beacon | 38 |
| bad_image | no-image | 17 |
| bad_image | pixel | 8 |
| bad_image | gravatar.com/avatar | 5 |
| bad_image | wp-content/plugins | 2 |

## 버그 수정 및 개선

### 수정된 버그
- `tests/test_auto_lint_hook_guard.py`: 로컬 가상환경(`.venv`) 내 `ruff` 자동 탐색 및 PATH 폴백 지원 (테스트 하네스 에러 해결)
- `scripts/collect_regulatory.py`: 규제 리포트 메타 설명문(`_desc_ko`) 최빈 지역과 실제 기사 매핑 불일치 수정 및 영문 원문 노출 차단
- `scripts/collect_political_trades.py` & `scripts/collect_regulatory.py`: 뉴스 카드 렌더링 시 미번역 영문 본문(`contains_english_clause`) 노출 방지 및 안전 번역 가드 적용
- `scripts/common/summary_sections.py`: 일일 요약의 정치인 워치 섹션 내 미번역 영문 절 노출 방지

### 새로 추가된 기능
- 번역 누락 차단 파이프라인 가드: `contains_english_clause` 기반 사전 필터링 및 번역 fallback 체계 구축

## CI/CD 상태

CI/CD 상태는 GitHub Actions 대시보드에서 확인하세요: https://github.com/Twodragon0/investing/actions

주요 체크 항목:
- Jekyll Deploy
- Lighthouse CI
- Code Quality (ruff)
- Description Quality
- Coverage (87.7% 달성)

## 다음 주 계획 (W42)

1. `post-quality.yml` 워크플로우의 미번역 본문 상한 및 복구 안정화 모니터링
2. Google Translate rate-limit 대응을 위한 번역 캐시 프리로딩 및 백오프 딜레이 고도화
3. 일일 규제/정치인 거래/소셜 뉴스 수집기 데이터 품질 및 한국어 요약 완성도 추적

---

*자동 생성: 2026-10-12 00:06 KST*