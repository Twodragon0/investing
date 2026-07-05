# summary_sections.py 분기 커버리지 리포트 (2026-07-03)

## 측정 방법

```bash
python3 -m pytest tests/test_generate_daily_summary.py tests/test_module_extraction_boundaries.py \
  -o addopts="" --cov=common.summary_sections --cov-branch --cov-report=term-missing
```

## 요약

| 지표 | 최초(2026-07-03) | 갱신(2026-07-05) |
|------|------------------|------------------|
| Statements miss | 60 | **10** |
| Branch partial | 53 | **31** |
| **Line+Branch Cover** | 87% | **96%** |
| 구동 테스트 | 220 | 233 |

**갱신 내역(2026-07-05):** 골든마스터 케이스 4(titles-only + relation) 추가 +
`_build_market_signal_section`·`_build_overview_section`·순수 헬퍼(row builder /
dedup / top_signal noise) assert 유닛 테스트로 그룹 A/B/C 대부분 해소.

골든마스터 4종(happy / empty-titles / no-data / titles-relation)이 카테고리
렌더·방어 fallback·교차자산 relation을 결정적으로 고정한다. 아래 3그룹 분류는
최초 측정 시점 기준이며, 대부분 커버 완료됐다.

### 잔여 미커버 (96%, 의도적 비커버)

- **도달 불가**: `889->963`, `914->920` — `_coverage_warnings` 는 summary_map 에
  `market` 키가 없으면 항상 경고를 반환하는데 두 섹션 빌더는 `market` 키를 넣지
  않으므로 교차자산 섹션 skip 엣지에 도달 불가.
- **contrived false-edge**: `506->508`·`520->522`·`531->533`·`543->545`·`555->557`
  등 `if best_non_noise_title(...):` 의 falsy 엣지 — 타이틀 존재하면서 대표 타이틀만
  falsy인 인위적 입력 필요. 회귀 위험 낮아 비커버 유지.
- **잔여 stock dedup skip**(`1033->1031` 등)·`1010`(테마 커버리지 falsy) — 동일.

---

## 그룹 A — 의도적 미테스트 함수 (골든 스코프 밖)

골든마스터는 `_build_briefing_section` + `_build_priority_and_category_sections`만
구동한다. 아래 두 함수는 골든에서 호출되지 않아 통째로 미커버에 가깝다.

| 함수 | 미커버 라인 | 성격 |
|------|------------|------|
| `_build_market_signal_section` (54-190) | 65-67, 81→97, 136→141, 142-144, 147-149, 151→157, 159-161, 164→190, 170-188 | 엔티티 빈도·연관 클러스터·예외 폴백. all_news_items 엔티티 추출 경로 |
| `_build_overview_section` (263-353) | 289, 291, 293, 295, 297, 336, 346→348 | count_parts(보안/규제/소셜/월드/정치) 누적, 테마 서사 else, P0/P1 신호 |

- **판정**: 별도 단위 테스트로 커버하는 것이 적합(골든에 끼워넣으면 입력이 비대해짐).
- 우선순위: 중 (`_build_market_signal_section`은 엔티티 로직 회귀 위험 있음).

---

## 그룹 B — 방어 fallback / 데이터 조건부 잔여 분기

케이스 3(no-data)로 대부분 덮었으나, 아래는 "타이틀 존재 + 특정 필드 조합"이
동시에 필요해 남은 분기다.

| 라인 | 위치 | 조건 |
|------|------|------|
| 219 | `top_signal` | highlights가 `^[\d,]+건` noise → skip |
| 227→231 | `top_signal` | titles 있으나 noise/짧음 → Priority 4로 폴백 |
| 401 | briefing | `legacy_briefing` elif (구 파일명 이미지만 존재) |
| 445→447, 447→449 | briefing | sentiment pos/neg examples 유무 |
| 481→487, 506→508 | briefing | per-category figures/titles + crypto_detail titles |
| 519-521 | briefing | stock: titles만 있고 market_data/figures 없음 |
| 531-558 | briefing | reg/social/worldmonitor titles-only detail |
| 632 | briefing | sentiment.ratio ≤ 35 (공포 구간 메모) |
| 990 | category | P1 링크 없는 항목 → `_headline_for_korean_summary` else |
| 1010 | category | crypto themes 있으나 커버리지 계산 falsy → else |
| 1040 | category | stock figures fig_str 렌더 |
| 1033→1031, 1044→1043, 1051→1049 | category | stock seen_stock dedup skip 경로 |

- **판정**: 케이스 1/2/3에 필드 조합을 추가하면 다수 동시 커버 가능.
  단, 골든 해시가 매번 재캡처되므로 신규 4번째 케이스로 묶는 편이 깔끔.
- 우선순위: 중.

---

## 그룹 C — 교차자산 연관성 섹션 (relation/coverage 조건부)

`_build_priority_and_category_sections`의 교차자산 블록(886-958)은
`relation_rows`/`coverage_notes` 실데이터가 있어야 진입한다.

| 라인 | 조건 |
|------|------|
| 889→963 | relation_rows·coverage_notes 모두 없음 → 섹션 전체 skip |
| 909 | 높은 연관 3쌍 이상 → 시스템 리스크 경고 |
| 914→920 | coverage_notes 렌더 |
| 925-931, 932→938 | high/mid pairs 체크리스트 분기 |
| 947, 955 | 암호화폐↔규제 / 정치인 특정 패턴 |
| 833 | P0 desc(설명 > 15자) 렌더 |
| 864→878 | indicator_rows / yield_section 파싱 분기 |

기타 헬퍼:
| 라인 | 위치 |
|------|------|
| 655 | `_iter_priority_items` dedup(norm in seen) skip |
| 687-688 | `_worldmonitor_issue_rows` len≥3(짧은 행) |
| 697→695 | `_security_incident_rows` len<3 skip |
| 789→794 | `_render_category_section` 표 rows 빈 경우 / figures |

- **판정**: `_relation_rows`가 반환하는 실제 형태의 summary_map 픽스처가 필요.
  기존 `TestBuildPriorityAndCategorySections` 클래스에 relation 픽스처 추가가 적합.
- 우선순위: 하 (동적 서사라 회귀 위험 상대적으로 낮음).

---

## 권고

1. **그룹 A 우선** — `_build_market_signal_section` 엔티티/클러스터 단위 테스트 추가
   (엔티티 로직 회귀가 사용자 노출 콘텐츠에 직접 영향).
2. **그룹 B는 4번째 골든 케이스** — "titles-only + relation" 조합으로 다수 분기 동시 고정.
3. **그룹 C는 relation 픽스처** 기반 유닛 테스트 — 골든보다 assert 기반이 유지보수 유리.

현재 87%는 핵심 렌더/방어 경로가 결정적으로 고정된 상태이며,
잔여는 대부분 "특정 데이터 조합"이 필요한 조건부 분기다.
