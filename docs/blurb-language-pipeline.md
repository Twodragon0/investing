# 본문 blurb 언어 파이프라인

카드 본문의 per-URL blurb(`<p class="news-desc">`, `<span class="p0-desc">`)가 한국어로
유지되도록 하는 층들과, 아직 남은 모집단을 근거 수치와 함께 정리한다.

**측정 기준일: 2026-09-08.** 수치는 그날 실측이며, 재현 명령을 각 절에 적어 둔다.

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
| 영어 blurb | **398 / 6,358 (6.26%)**, 영향 포스트 193 | `check_description_quality.count_blurb_language` |
| `_is_bad` flagged | 2,639 (Google News 2,339 = 88.6%) | `fix_post_url_summaries.collect_targets` |
| 삭제 적격 | 291 | `_is_droppable` |
| 총 포스트 | 2,771 | — |
| 유입률(#1283 이후 신규 14건) | **1 / 37 (2.70%)** | `scripts/tools/measure_blurb_inflow.py` |

유입률 2.70% 는 아직 **판정 불가**다. 수정 전 일별 범위가 0.0%~12.9%(2026-09-02~07,
crypto/stock digest 기준)여서 하루치 값이 그 안에 들어간다. `n≥200`(약 2026-09-14)이면
범위 밖 여부가 갈린다.

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
라벨은 `KEYWORD_TAIL_LABEL` 상수로 통일했지만(생산 1곳 + 제거 3곳), **생산자를 없앨지
제거 규칙을 없앨지는 미결정**이다. 그때까지 합성 폴백은 실질적으로 재활성화되지 않는다.

### R2. 일일 자동 백필 — `.github/workflows/backfill-url-summaries.yml`

cron `10 17 * * *`, `--apply --skip-synthetic --workers 6 --limit 200`.

**리졸버 스로틀이 상한이다.** 2026-08-06 연속 실행에서 재수집 수율이 `523 → 71 → 0` 으로
붕괴하고 3회차엔 모든 링크가 빈 값이었다. 같은 시점 직접 퍼블리셔 URL 은 정상이었으므로
상한은 도구가 아니라 리다이렉트 리졸버다. **실패한 요청은 공짜가 아니라 차단을 연장한다.**

일일 실측(2026-09-07): 대상 200 / 재수집 31(15.5%) / 적용 27.

디코딩 자체는 건강하다 — `gnewsdecoder` 표본 100/100 해소(평균 1.16~1.50s). 실패는
디코딩 **이후** 단계(페이지 fetch, 제목 관련성, 번역)다. base64 무네트워크 경로는 고유
URL 1,896건 **전부 실패**(신형 protobuf)이므로 `googlenewsdecoder` 가 유일한 경로다.
`config.GNEWS_DECODE_INTERVAL_SEC`(기본 0 = 비활성)가 조여올 때의 레버다 — 워크플로우의
`--limit` 이 아니라 이 값을 올린다.

워크플로우 불변식 5개는 `tests/test_backfill_url_summaries_workflow_guard.py` 가 고정한다
(`--skip-synthetic` 고정, `--limit` 상한 400, 하루 1회, 수율 0 은 red 아님, `--direct-only`
는 스케줄 기본값 아님). 가드는 `run:` 을 **셸 주석 제거 후** 매칭한다 — 주석이 플래그를
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
2. **잔여 398건의 차단 요인** — Google News 리다이렉트 88.6%(스로틀), 재수집 영구 실패,
   앵커 모호. 삭제 적격 291건은 `--order droppable-first` 로 회차당 최대 60건씩 처리 가능.
3. **합성 폴백 재활성화 여부** — `korean_keywords` 품질은 고쳤지만
   `improve_existing_posts` 가 여전히 그 산출물을 제거한다. 생산자/제거 규칙 중 하나를
   없애는 결정이 남았다.
4. **미인식 사이트 크롬 2건** — Investorideas 태그라인, TradingView 블로그 유도.
   `_BOILERPLATE_DESC_PHRASES` 에 정확 리터럴로 추가하는 것이 해법이며(패턴 추측은 삭제
   권한을 줄 수 없다), 현재는 보수적으로 보존 중이다.
5. **유입률 판정** — n=37 로는 수정 전 범위와 구별되지 않는다. `n≥200`(약 2026-09-14)에
   측정 도구를 다시 돌린다.
