# i18n 다국어 토글 Playwright E2E 자동화 설계

작성: 2026-05-08 / 상태: 설계 (구현 미착수)

## 1. 배경

`_includes/google-translate.html` + `assets/js/google-translate.js`는 Google Translate 위젯을 호버 시점에 프리로드(`__preloadGoogleTranslate`)하고, 클릭 시점에 in-place 전환(reload 없음)하는 경로를 제공한다. 이 인터랙션은 외부 SDK + 쿠키 + DOM mutation이 얽혀 회귀가 잦은 영역이므로, Playwright 기반 E2E로 회귀를 가드한다.

핵심 셀렉터: `#lang-toggle`, `#lang-dropdown`, `.lang-option[data-lang="..."]`, `#current-lang`, `script[src*="translate_a/element.js"]`, 쿠키 `googtrans`, `localStorage.preferredLang`.

## 2. 테스트 시나리오 매트릭스

| ID | 시나리오 | 트리거 | 검증 핵심 |
|----|---------|--------|----------|
| S1 | 호버 → 클릭 정상 경로 (EN/JA/zh-CN/ES 각 1) | `hover(#lang-toggle)` → `click(.lang-option[data-lang=X])` | in-place 전환, reload 0, `#current-lang` = LANG_MAP |
| S2 | 호버 후 즉시 클릭 (race) | `hover` 직후 50ms 내 `click` | `script[src*="translate_a/element.js"]` count == 1 |
| S3 | 호버 없이 직접 클릭 (touch/키보드) | `tab → enter` 또는 `tap` | 폴백 reload 경로 정상, 쿠키 `googtrans=/ko/X` |
| S4 | 한국어 복귀 | EN 상태에서 `data-lang=ko` 클릭 | 쿠키 `googtrans` 삭제, `#current-lang=KO`, body top 리셋 |
| S5 | 시크릿/쿠키 차단 | `context.addCookies` 차단 / storage 비활성 컨텍스트 | reload 폴백 동작, 본문 텍스트 변경 또는 graceful degrade |
| S6 | 모바일 viewport | iPhone SE / iPad / Pixel 5 디바이스 프리셋 | 드롭다운 표시, `tap` 동작, 가독성 |
| S7 | 다크/라이트 테마 | `prefers-color-scheme` emulate | 셀렉터 정합 (테마 영향 받지 않음) |
| S8 | localStorage 자동 적용 | `preferredLang=en` set 후 새 페이지 | 진입 시 자동 EN 전환, `#current-lang=EN` |
| S9 | 더블클릭 시스템 복귀 | EN 상태에서 `dblclick(#lang-toggle)` | `preferredLang=system`, 시스템 언어로 복귀 |

각 시나리오는 한 페이지(`/`)와 포스트 한 건(`/posts/...` 최신)에서 반복하여 레이아웃 차이를 가드한다.

## 3. 검증 지표 (assertions)

- **프리로드 타이밍**: 호버 후 1500ms 이내 `script[src*="translate_a/element.js"]` 1개 출현 (`page.wait_for_selector`).
- **본문 변경**: 클릭 후 5000ms 이내 헤더 대표 문자열 매핑 검증 (`expect(locator).to_have_text(...)` with regex per lang). 매핑 표는 `tests/i18n/fixtures/lang_strings.json`로 분리.
- **쿠키 set/delete**: `context.cookies()`로 `googtrans` 값/부재 검증.
- **`#current-lang` 텍스트**: KO/EN/JA/CN/ES 정합.
- **reload 측정**: `page.on("framenavigated")` 카운터로 in-place 경로(S1, S2)는 0회, 폴백 경로(S3, S5)는 ≤1회.
- **콘솔 에러 0**: `page.on("pageerror")`/`console` error level 수집, 알려진 GT 경고는 화이트리스트.

의사코드:
```python
page.hover("#lang-toggle")
page.wait_for_selector('script[src*="translate_a/element.js"]', timeout=1500)
page.click('.lang-option[data-lang="en"]')
expect(page.locator("#current-lang")).to_have_text("EN", timeout=5000)
expect(page.locator("header h1")).to_contain_text(re.compile(r"Investing|Crypto", re.I))
assert nav_count == 0  # in-place
```

## 4. 프레임워크 선택

권장: **`pytest-playwright` (Python)**. 근거: `tests/`가 이미 pytest 기반(`conftest.py`, 60+ 테스트)이고 CI는 Python 3.11 셋업을 재사용 가능. Node 런타임을 새로 도입할 비용 대비 정합성 이득이 명확.

대안: Playwright Test (Node)는 trace viewer/병렬화 UX가 우수하지만, 본 저장소에는 Node 테스트 러너가 없어 도입 비용이 더 크다.

## 5. CI 통합 전략

파일: `.github/workflows/i18n-e2e.yml` (신규, `reports-e2e.yml` 패턴 차용).

- **트리거**: `push` (paths: `_includes/google-translate.html`, `assets/js/google-translate.js`, `_layouts/default.html`, `tests/i18n/**`), `pull_request` 동일 paths, `workflow_dispatch`.
- **동시성**: `group: i18n-e2e-${{ github.ref }}`, `cancel-in-progress: true` — `collect-data` 그룹과 분리.
- **단계**:
  1. checkout → Ruby 3.2 + Python 3.11 setup (캐시)
  2. `pip install pytest pytest-playwright && playwright install --with-deps chromium`
  3. `bundle exec jekyll build` (JEKYLL_ENV=production)
  4. `bundle exec jekyll serve --skip-initial-build --port 4000` 백그라운드 + `wait-on` 헬스체크
  5. `pytest tests/i18n/ --browser chromium --tracing retain-on-failure --screenshot only-on-failure`
  6. 실패 시 `playwright-traces/`, `screenshots/` 아티팩트 업로드 (retention 7d)
- **타임아웃**: job 15분, per-test 30s.
- **재시도**: `--reruns 1` (flaky GT 외부 호출 대비), 2회 연속 실패만 빨간불.
- **외부 호출**: 기본은 실제 `translate.google.com` 호출 (사용자 경로 충실), 별도 `@pytest.mark.offline` 마크는 `route.fulfill`로 모킹하여 빌드 셀프체크용 fast lane 제공.

## 6. 단계별 구현 순서

**Phase 1 — 인프라 (commit d34c2029, 2026-05-08)** ✅
- [x] `tests/i18n/` 디렉토리 + `conftest.py` (base_url, lang_strings, browser_context_args) 추가
- [x] `requirements-dev.txt`에 `pytest-playwright` 추가
- [x] `i18n-e2e.yml` 워크플로우 골격 (S1 EN 단일 시나리오) 도입
- [x] verifier 게이트: run 25533527291 success + trace 아티팩트 confirmed

**Phase 2 — 핵심 시나리오 (commits 4d4262f4 + 08e9b986 + a1c08c2c, 2026-05-08)** ✅
- [x] S1 EN/JA/zh-CN/ES 4개 언어 파라미터화
- [x] S2 race condition (네트워크 요청 카운트 + redirected_from 필터)
- [x] S4 KO 복귀 (쿠키 삭제)
- [x] S8 localStorage 자동 적용
- [x] verifier 게이트: run 25535029430 success (수동 트리거)
- 학습: HTTP→HTTPS 리다이렉트가 `request` 이벤트 두 개 만듦 → `redirected_from is None` 필터 필수.
  DOM script 카운트는 GT가 초기화 후 정리하므로 timing-dependent → 네트워크 요청 카운트로 대체.

**Phase 3 — 회귀 + 모바일 (2~3 PR)** 🔄
- [ ] S6 모바일 디바이스 매트릭스 (`devices["iPhone SE"]` 등) 파라미터화
- [ ] S3 키보드/터치 폴백, S5 시크릿 컨텍스트, S9 더블클릭 복귀
- [ ] 콘솔 에러 0 가드 + S7 테마 emulate
- [ ] verifier 게이트: matrix 전체 green + 평균 실행 시간 ≤ 5분

## 7. 위험 + 완화책

- **GT flakiness**: 외부 SDK 응답이 느릴 수 있음 → ① `--reruns 1` ② `wait_for_selector` 타임아웃 여유 ③ offline lane (`route.fulfill`)을 PR fast feedback에 사용, full lane은 main push에서만.
- **CI 비용**: 브라우저 부팅 ~20s × 시나리오 N → chromium 단일 브라우저 + 시나리오 그룹 fixture로 컨텍스트 재사용. 풀 매트릭스는 nightly로 분리 검토.
- **동시성 충돌**: `collect-data` 그룹과 별도 group을 사용. Jekyll 포트 4000 충돌 방지를 위해 워크플로우 내 단일 잡 유지.
- **셀렉터 취약성**: Google Translate가 DOM(font 태그)을 변형 → 검증은 항상 `data-lang` 기반 + `notranslate` 영역 셀렉터(`#current-lang`)를 우선 사용.
- **언어별 매핑 스트링**: 사이트 콘텐츠 변경 시 깨질 수 있음 → 헤더 한 줄 + nav 하나만 매핑, fixture JSON 한 곳에서 관리.

## 8. 참고

- 기존 패턴: `.github/workflows/reports-e2e.yml`, `tests/conftest.py`, `tests/test_reports_page.py`
- 관련 가이드: `.claude/rules/testing.md`, `.claude/rules/news-collector.md`
- 후속: 본 설계 승인 후 Phase 1 구현은 `/oh-my-claudecode:start-work i18n-e2e-plan` 으로 진행
