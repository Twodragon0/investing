# 본문 blurb 언어 파이프라인

카드 본문의 per-URL blurb(`<p class="news-desc">`, `<span class="p0-desc">`)가 한국어로
유지되도록 하는 층들과, 아직 남은 모집단을 근거 수치와 함께 정리한다.

**측정 기준일: 2026-09-09.** 수치는 그날 실측이며, 재현 명령을 각 절에 적어 둔다.

---

## 왜 별도 문서가 필요한가

프론트매터 `description` 지표는 오래 **real content 100% / ASCII-heavy 0%** 를 읽고 있었다.
같은 시점 본문 blurb 층에서는 영어가 새고 있었다 — 두 층이 서로 다른 데이터를 보고
서로 다른 검출기를 쓰기 때문이다. 2026-09-04 실측: `_generate_title_based_desc` 가 만든
blurb 260건 중 252건이 `"<영어 헤드라인>. <엔티티> — <한국어 맥락>"` 형태로 158개
포스트에 남아 있었고, chrome 검사에 걸린 건 그중 **2건**이었다. `is_boilerplate` 도
제목-중복 검사도 **언어를 묻지 않는다.**

---

## 현재 상태

| 지표 | 값 | 재현 |
|---|---|---|
| 영어 blurb | **318 / 6,340 (5.02%)**, 영향 포스트 178 | `check_description_quality.count_blurb_language` |
| `_is_bad` flagged | 2,603 (Google News 2,292 = 88.1%) | `fix_post_url_summaries.collect_targets` |
| └ 제목-중복 / 크롬 / 영어 | 1,546 / 807 / 250 | 같음 |
| 삭제 적격 | 234 | `_is_droppable` |
| 총 포스트 | 2,784 | — |
| 유입률(#1283 이후 신규 27건) | **1 / 74 (1.35%)** | `scripts/tools/measure_blurb_inflow.py` |

`_is_bad` 의 구성비가 중요하다 — 제목-중복이 **59.4%** 로 최대 모집단이고, 삭제 술어는
영어 누출에만 범위가 잡혀 있어(`_is_droppable` 의 첫 게이트가 `contains_english_clause`)
그 1,546건은 재수집으로만 닿는다.

유입률 1.35% 는 아직 **판정 불가**다. 수정 전 일별 범위가 0.0%~12.9%(2026-09-02~07,
crypto/stock digest 기준)여서 값이 그 안에 들어간다. 게이트는 `n≥200` 이고 현재 74다.

---

## 언어 판정의 단일 근거

`common/summary_quality.py` 가 SSoT다. **두 번째 리터럴 복사본을 만들면 한쪽만 움직인다.**

- `ASCII_RATIO_THRESHOLD` (0.70) / `is_ascii_dominant` / `is_ascii_heavy`
- `contains_english_clause` / `longest_hangul_free_word_run`,
  `ENGLISH_CLAUSE_MIN_WORDS = 6`

### 혼합 언어에는 비율 판정이 통하지 않는다

누출 형태 `"<영어 헤드라인>. <한국어 맥락>"` 에는 **한글이 있고** 전체 ASCII 비율은
한국어 꼬리에 눌린다. 실측: whole-string `is_ascii_dominant` 는 실제 누출 4건 중 **1건만**
잡았다. 그래서 한글 없는 구간의 영어 단어 수(`longest_hangul_free_word_run`)를 본다.

임계값 6은 blurb 6,219건 전수로 보정했다. **잔여 오탐이 0이 아니다** — 영어 고유명사가
길게 박힌 한국어 산문이 걸린다:

```
Mario Tama/Getty Images John Rapley는 The Globe and Mail…
Financial Times의 보고서에 따르면 비트코인의 가명 제작자인 나카모토 사토시(Satoshi Nakamoto)의…
```

하이브리드 279건 중 **21건(7.5%)** 이 이 부류다. 삭제 술어가 이걸 지키지 않으면 실제
콘텐츠를 파괴한다(아래 참조).

---

## 예방 (수집 시점) — 2층

### L1. 상류 번역 — `common/enrichment.py` 번역 패스

렌더러는 `description_ko or description` 폴백이므로(`themed_news_renderer.py:296`),
`description_ko` 가 안 붙으면 영어 원문이 그대로 렌더된다. 그 필드를 붙이는 게이트에
결함이 두 개 있었다(#1283에서 수정):

1. **게이트가 whole-string 이었다.** `detect_language(desc) == "en"` 은 하이브리드에
   대해 `ko` 를 반환한다(실측). 즉 겨냥한 모집단이 번역에 **진입조차 못 했다.**
   → `or contains_english_clause(desc)` 로 **확장**. 교체가 아닌 이유: 6단어 하한 때문에
   `"English description text."`(3단어) 같은 짧은 순수 영어가 누락된다.
2. **번역 결과를 검사하지 않았다.** `if ko_desc != desc` 는 진짜 번역과 망가진 echo 를
   구별하지 못하고 `translate_to_korean` 은 fail-open 이다.
   → `contains_english_clause` 로 재검사. `select_korean_headline` 과 같은 계약.

**남는 경로(설계상)**: 재검사에서 거부하면 `description_ko` 가 비고, 렌더러가 영어 원문으로
폴백한다. 완전 차단은 렌더러 가드가 필요하지만 **채택하지 않았다**(아래).

### L2. 합성기 — `summarizer._generate_title_based_desc`

`is_ascii_dominant(title)` 이면 `""` 를 반환한다. 한국어 렌디션이 없는 항목에 한국어
꼬리를 붙여 내보내지 않는다. 판정은 `re.search(r"[가-힣]")` 이 아니라 SSoT 를 쓴다 —
한글 한 토큰이 섞인 영어 제목도 걸러야 한다.

렌더러 배선도 같은 축이다: `_render_featured_card` 는 fallback 합성기에 `title`
(= `title_ko` 있으면 그것)을 넘긴다. 원문 `orig_title` 을 넘기면 카드 앵커가 이미 한국어로
보여준 헤드라인이 바로 아래에 영어로 다시 찍힌다 — 누출 252건 중 **235건(93%)** 이 이것이었다.

### 렌더러 가드는 채택하지 않았다

`_render_featured_card` 에 `contains_english_clause` 를 두면 누출이 완전히 닫힌다.
스크래치 적용 실측: 골든 blurb 70개 중 **52개(74%) 제거**, 1개는 한국어 제목 폴백으로
대체. 테스트 영향 8건(골든 7 + 단위 1).

**기각 근거**: 렌더러는 수집 시점에만 돌고(`collect_stock_news.py:726`,
`collect_crypto_news.py:1234`) 발행분을 재렌더하는 경로가 없다 —
`improve_existing_posts.py` 는 `news-desc`/`p0-desc` 를 전혀 건드리지 않는다. 즉 **예방
전용**이다. 그런데 #1283 이후 남은 유일한 누출 1건을 추적해 보니 게이트 결함이 아니라
**일시적 번역 실패**였고(생성 커밋 시점 캐시에 그 항목이 없었음), 같은 문자열이 재시도에서
성공해 캐시에 정상 한국어로 들어 있었다. 그 blurb 은 백필 flagged 이고 direct URL 이라
매일 도는 job 의 복구 대상이다.

작동하는 복구 경로가 있는 실패 모드에 가드는 콘텐츠 **영구 삭제**로 대응한다 —
"일시적으로 영어"를 "영구히 없음"과 교환하는 거래라 채택하지 않았다.

---

## 복구 (발행분) — 3경로

### R1. `fix_post_url_summaries.py` — 재수집 → 번역 → (합성)

`_is_bad` 가 chrome·제목중복·영어 절 중 하나면 표시한다. 소싱 순서는 수집 파이프라인을
그대로 따라, 복구된 blurb 가 잘 수집된 blurb 와 구별되지 않게 한다.

**`--skip-synthetic` 은 선택이 아니다.** 합성 폴백은 품질을 떨어뜨린다 — 실측:

```
before: 포트폴리오를 다양화하고 싶으신가요? 고려해야 할 1가지 암호화폐는 다음과 같습니다. 급락 관련 보도.
after : … 주요 키워드: 포트폴리오, 싶으신가요, 고려해야.
```

`싶으신가요`·`고려해야`·`일어난` 은 키워드가 아니라 어미다. `korean_keywords` 의 서술어
어미 필터를 코퍼스 4,652개 제목 전수로 보강해 junk 토큰 인스턴스를 **~165 → 0** 으로
줄였다(`-된` 은 폐기가 아니라 정규화: `토큰화된` → `토큰화`, 21→0 / 8→29).

그래도 `improve_existing_posts.py` 가 `주요 키워드:` 꼬리를 **결함으로 보고 제거**한다.
라벨은 `KEYWORD_TAIL_LABEL` 상수로 통일했다(생산 1곳 + 제거 3곳). 2026-09-09 결론:
**합성 폴백은 재활성화하지 않고 `--skip-synthetic` 을 유지한다** — 이유와 재활성화
선행조건은 아래 「미해결 3」에 있다.

### R2. 일일 자동 백필 — `.github/workflows/backfill-url-summaries.yml`

cron `10 17 * * *`,
`--apply --skip-synthetic --workers 6 --limit 200 --order least-recently-tried`.

**리졸버 스로틀이 상한이다.** 2026-08-06 연속 실행에서 재수집 수율이 `523 → 71 → 0` 으로
붕괴하고 3회차엔 모든 링크가 빈 값이었다. 같은 시점 직접 퍼블리셔 URL 은 정상이었으므로
상한은 도구가 아니라 리다이렉트 리졸버다. **실패한 요청은 공짜가 아니라 차단을 연장한다.**

일일 실측(2026-09-07): 대상 200 / 재수집 31(15.5%) / 적용 27.

디코딩 자체는 건강하다 — `gnewsdecoder` 표본 100/100 해소(평균 1.16~1.50s). 실패는
디코딩 **이후** 단계(페이지 fetch, 제목 관련성, 번역)다. base64 무네트워크 경로는 고유
URL 1,896건 **전부 실패**(신형 protobuf)이므로 `googlenewsdecoder` 가 유일한 경로다.
`config.GNEWS_DECODE_INTERVAL_SEC`(기본 0 = 비활성)가 조여올 때의 레버다 — 워크플로우의
`--limit` 이 아니라 이 값을 올린다.

워크플로우 불변식 7개는 `tests/test_backfill_url_summaries_workflow_guard.py` 가 고정한다
(`--skip-synthetic` 고정, `--limit` 상한 400, 하루 1회, 수율 0 은 red 아님, `--direct-only`
는 스케줄 기본값 아님, `--order least-recently-tried` 고정, 시도 기록은 캐시로 왕복하고
`save` 는 `if: always()`). 가드는 `run:` 을 **셸 주석 제거 후** 매칭한다 — 주석이 플래그를
이름으로 언급하므로 원문 매칭은 인자 삭제 후에도 자기 문서에 걸려 green 이 된다.

### R3. 번역 재시도 — `scripts/tools/fix_untranslated_body.py`

`translate_to_korean` 은 fail-open 이고 **실패는 캐시되지 않는다** — 그게 재시도를 가능하게
하는 설계다. 대량 스윕은 결과가 0 이 될 때까지 재실행해야 한다(실측: 151→13→0).

---

## 삭제 (`--drop-unresolvable`)

교체로는 닿지 않는 모집단이 있다. `apply_repairs` 는 `if text:` 일 때만 쓰므로 재수집·번역이
영구 실패하면 영어 blurb 가 그대로 남는다.

### 술어가 안전의 핵심

세 조건을 **모두** 만족할 때만 삭제한다: ① `_is_bad` flagged, ② 재수집·번역 둘 다
실패(`unresolved`), ③ 형태 기준 적격.

| 입력 | 판정 |
|---|---|
| 영어 절 없음 | 대상 아님 — 한국어 blurb 는 여기서 삭제되지 않는다 |
| 한글 있음 + 잔여가 필러(`is_generic_desc`/`is_boilerplate`) | 삭제 |
| **한글 있음 + 잔여가 실질 내용** | **보존** ← 위 7.5% 오탐을 지키는 조건 |
| 한글 없음 + 크롬·제목중복·제목겹침 ≥ 0.5 | 삭제 |
| **한글 없음 + 실질 영어 콘텐츠** | **보존** — 번역 대상이지 삭제 대상이 아니다 |

`skipped` 는 `unresolved` 와 다르다 — "이번 런에서 시도 안 함"(`--direct-only`)이라
리졸버가 본 적조차 없는 blurb 를 지우게 된다.

### 다른 안전 장치

- **런당 상한 `_MAX_DROPS_PER_RUN = 60`.** 삭제에는 항목별 검수 단계가 없으므로 술어 회귀와
  대량 삭제 사이에 남는 유일한 경계다.
- **기본값 off.** `build_parser()` 를 노출해 그 기본값을 실제로 단언한다.
- **엘리먼트 통째 제거.** inner text 만 비우면 `<p class="news-desc"></p>` 가 남아 카드에
  빈 틈으로 렌더된다. 인수 조건: `news-desc`·`</p>` 가 정확히 N 감소하고
  `news-card-item`/`news-card-body`/`</div>`/`news-title` 은 불변.
- **앵커 모호 거부.** 한 포스트의 동일 사본은 서로 다른 기사를 가리킨다.
- **스케줄 진입 금지.** `workflow_dispatch` 수동만. 백필 자신의 롤아웃 이력(`--limit 20`
  2회 검수 중 **다른 기사 요약으로 덮은 오염 1건 발견**)을 따른다.

### 정렬이 곧 선택 정책이다

`--limit` 은 `collect_targets` 가 돌려준 순서를 자른다. 기본 `newest` 는 일일 job 이
의존하는 순서이므로 바뀌면 안 된다. 그런데 **작은 `--limit` 과 함께 쓰면 `--days` 가
무효**다 — 최신 60건은 어떤 창에도 들어가므로 90/180/365일이 동일한 60건을 고른다.

레거시 모집단은 2026-03~05 에 있어 최신 끝에서는 닿지 않는다. `--order droppable-first`
가 그걸 해소한다(실측):

| `--limit` | `newest` 적격 | `droppable-first` 적격 |
|---:|---:|---:|
| 20 | 0 | 20 |
| 60 | 11 | 60 |

리졸버 비용은 변하지 않는다 — Google News 비율이 적격 86.3% / 비적격 88.9% 로 거의 같다.
`droppable-first` 는 `--drop-unresolvable` 을 요구한다: 단독으로 쓰면 최신 포스트의 실질
콘텐츠 blurb 가 `--limit` 밖으로 밀려 복구 임무를 굶긴다.

정렬은 **안정적**이다(그룹 내 최신순 유지) — 불안정하면 회차마다 슬라이스가 달라져 단계적
검수가 불가능하다.

---

## 측정

`scripts/tools/measure_blurb_inflow.py` 는 각 포스트의 **생성 커밋 blob** 에서 센다.
`check_description_quality.py` 는 워킹트리를 보므로 백필이 같은 포스트를 고친 뒤에는
유입이 아니라 **복구를 세게 된다.**

생성 blob 기반이라 측정이 소급 가능하고 이후 복구에 면역이다 — 특정 날짜의 값은 그날 재도,
한 달 뒤에 재도 같다. 그래서 크론으로 로그에 쌓을 필요가 없다(run 로그는 90일 후 만료).

```
python scripts/tools/measure_blurb_inflow.py [--since <ref>] [--json]
```

`rate_at_birth` 는 blurb 0건일 때 `0.0` 이 아니라 `None` 이다 — "발행된 blurb 이 없다" 와
"영어 blurb 이 없다" 는 다른 발견이다.

---

## 미해결

1. **렌더러 폴백 경로** — L1 재검사가 거부하면 영어 원문이 렌더된다. 가드는 기각했고
   (위), 대신 R2/R3 복구에 의존한다.
2. **차단 요인은 스로틀이 아니라 선택 창이었다 — 원인 수정 완료(`#1298`), 소진은
   진행 중** (2026-09-09 재진단). 종전 서술은
   "Google News 리다이렉트 88.1%(스로틀), 재수집 영구 실패, 앵커 모호" 였는데 스로틀은
   **수율**을 정하고 **모집단 도달**을 막는 건 다른 것이다.

   수정 전 상태: 일일 job 은 `newest --limit 200` 이었고 그 창은 **2026-08-06 ~ 09-09**
   만 덮었다 — 200번째보다 오래된 **2,403건은 수율과 무관하게 영구히 도달 불가**였다.
   게다가 도구에 **시도 기록이 없었다**(`_state` 사용 0건). 영구 실패가 창 상단에 남아
   매일 200 요청 예산을 다시 썼다. 신규 유입은 하루 ~6건뿐이라 창 구성은 sticky 실패가
   지배했다 — 2026-09-07 런이 200 중 173건 실패했고, 그 시점 창 200건 중 150건이 8월
   포스트였다.

   **정렬로는 안 풀린다** (실측). 35건(2026-09-09에 `#1296` 으로 새로 보이게 된
   제목-중복)의 순위:

   | 정렬 | min / median / max | `--limit 200` 도달 |
   |---|---|---:|
   | `newest` (종전 일일 job 순서) | 100 / 1219 / 1875 | 5 / 36 |
   | `droppable-first` | 333 / 1375 / 1986 | 0 |
   | `title-dup-first` (가정) | 66 / 746 / 1134 | 7 / 36 |

   제목-중복 모집단이 1,546건이므로 그 축으로 정렬해도 특정 35건은 그 안에서 66~1134위다.
   `--limit` 을 1,875 이상으로 올리는 일회성 런은 리졸버를 붕괴시킨다(위 R2 절의 실측
   523 → 71 → 0).

   **해법은 시도 기록이고, `#1298` 에서 구현했다.** `_state/url_summary_attempts.json`
   에 `(post, url)` 해시 → `{tried, outcome, post}` 를 남기고,
   `--order least-recently-tried` 가 미시도 우선 → 오래된 시도 순으로 정렬한다. 일일
   job 이 이 정렬을 쓴다. 회차 시뮬레이션(실코퍼스, 매 회차 200건 전부 실패 가정):

   | 회차 | `newest` 창 / 누적 | `least-recently-tried` 창 / 누적 |
   |---:|---|---|
   | 1 | 08-06 ~ 09-09 · 197 | 08-06 ~ 09-09 · 197 |
   | 2 | 08-06 ~ 09-09 · **197** | 07-20 ~ 08-06 · **384** |
   | 4 | 08-06 ~ 09-09 · **197** | 06-27 ~ 07-09 · **773** |
   | 6 | 08-06 ~ 09-09 · **197** | 06-02 ~ 06-14 · **1160** |

   `newest` 는 1회차 이후 새로 보는 건이 **0** 이다. 새 정렬은 회차당 ~190건 전진하므로
   2,603건 전수는 약 14회차(≈2주)다.

   설계상 유의점 셋:
   - **빈 기록은 `newest` 와 동일하게 동작한다.** CI 캐시 미스의 요구 동작이다.
   - **`skipped` 는 기록하지 않는다.** `--direct-only` 는 요청조차 안 보내므로 이를
     시도로 세면 리졸버가 본 적 없는 blurb 이 뒤로 밀린다 — `--drop-unresolvable` 이
     쓰는 것과 같은 구분이다.
   - **기록은 커밋하지 않는다.** 커밋 스텝은 `git add _posts/` 만 하므로
     `actions/cache` 로 런 간 유지하며, `save` 는 `if: always()` 다(수율 0 인 날이
     기록이 가장 필요한 날이다).

   불변식은 `tests/test_backfill_url_summaries_workflow_guard.py` 가 6·7번 항목으로
   고정한다.
3. **합성 폴백 재활성화 여부 — 결론: 재활성화하지 않는다** (2026-09-09).
   `--skip-synthetic` 을 유지한다. "생산자를 없앨지 제거 규칙을 없앨지" 는 잘못 놓인
   질문이었다.

   `generate_synthetic_description` 은
   `if analysis and analysis != title and len(analysis) > 20: return analysis` 로
   게이트하고, **`주요 키워드:` 꼬리가 바로 그 `analysis != title` 을 만족시키는
   물건**이다. 꼬리만 빼면 게이트가 무너진다. 고유 카드 제목 4,704건 중 그 분기로
   떨어지는 **1,032건(21.94%)** 을 대상으로 분기만 격리해 실측:

   | 분기 제거 후 | 건수 |
   |---|---:|
   | 제목 그대로 반환 → 제목-중복 결함 | 617 (59.8%) |
   | 래퍼 폴스루 → `<제목>.. 부문은, 연준으로 관련 보도.` | 415 (40.2%) |
   | `_is_desc_duplicate_of_title` 판정 | 680 (65.9%) |

   폴스루 쪽은 중복 마침표와 조사 붙은 토큰(`부문은`, `연준으로`)을 낸다 — 현행 꼬리보다
   나쁘고, `..` 는 `normalize_blurb` 가 고치려고 존재하는 아티팩트다.

   제거 규칙이 옳다는 건 확정이다. `kr_entities = korean_keywords(title)`
   (`enrichment_synthetic.py:732`, 이 모듈의 유일한 호출처)이므로 꼬리는 제목 밖 정보를
   담을 수 **구조적으로** 없다. 2026-09-07 의 junk-token 수정은 서술어 어미를 잡았고
   부사·조사 조각·제목 관형어는 남아 있다 — `주요 키워드: 헐값, 거래, 어떻게` / `등에`.

   **방치 비용이 0이다.** 코퍼스에 `주요 키워드:` 는 포스트 1개·2건만 남았고,
   `--skip-synthetic` 은 워크플로우(`backfill-url-summaries.yml`)와
   `tests/test_backfill_url_summaries_workflow_guard.py` 가 고정한다. 이 항목은
   재활성화를 원할 때만 load-bearing 해진다.

   **재활성화 선행조건**: 생산자 제거가 아니라 **폴스루 체인이 그 22% 에 대해 `""` 를
   반환하게** 만드는 것. 꼬리 제거를 단독 커밋으로 내면 40.2% 가 악화된다.

   재현 (저장소 루트에서, 위 네 수치를 모두 낸다):
   ```python
   python - <<'PY'
   import html, pathlib, re, sys
   sys.path.insert(0, "scripts")
   import common.enrichment_synthetic as es
   from common.enrichment_synthetic import KEYWORD_TAIL_LABEL as L
   from common.enrichment_synthetic import generate_synthetic_description as gen

   TITLE = re.compile(r'class="news-title"[^>]*>(.*?)</a>', re.S)
   titles = sorted({
       html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
       for p in pathlib.Path("_posts").glob("*.md")
       for m in TITLE.finditer(p.read_text(encoding="utf-8", errors="replace"))
   } - {""})
   tail = [t for t in titles if L in (gen(t, "", None) or "")]
   print(f"고유 제목 {len(titles)} / keyword-tail 분기 {len(tail)}")

   es.korean_keywords = lambda title, limit=3: []  # 호출처는 L732 한 곳뿐이라 격리된다
   after = [gen(t, "", None) or "" for t in tail]
   fell = sum(1 for o in after if "관련 보도" in o or ".." in o)
   print(f"분기 제거 후: 제목만 {len(after) - fell} / 폴스루 {fell}")
   PY
   ```

   `korean_keywords` 를 통째로 스텁하면 래퍼의 정당한 폴스루가 스텁 누출처럼 보인다 —
   호출처가 `_analyze_korean_title` 한 곳뿐임을 먼저 확인하고 두 갈래를 분리해 세라.
4. ~~**미인식 사이트 크롬 2건**~~ — **해결** (`#1294`, 2026-09-09 머지).
   Investorideas 태그라인과 TradingView 블로그 유도를 `_BOILERPLATE_DESC_PHRASES` 에
   정확 리터럴로 추가했다. 패턴 추측이 아니라 리터럴이어야 하는 이유는 그대로다 —
   추측은 삭제 권한을 줄 수 없다. 새로 미인식 크롬이 나오면 같은 방식으로 처리한다.
5. **유입률 판정** — n=37 로는 수정 전 범위와 구별되지 않는다. `n≥200`(약 2026-09-14)에
   측정 도구를 다시 돌린다.
