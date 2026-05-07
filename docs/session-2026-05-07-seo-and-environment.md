# Session 2026-05-06~07: SEO 가속 + 환경 셋팅 + i18n 수정

## 개요

GSC 색인 미생성 605건 (404=1, Discovered=536, Crawled=68) 대응 + lang-toggle 5개 언어 지원 + Claude Code/OMC 환경 베이스라인 구축.

**총 18개 커밋, 9개 dependabot PR 머지, 3개 신규 도구 추가, 2개 신규 훅 활성화.**

---

## 1. SEO 인프라 강화

### 1.1 커스텀 Sitemap (`d5ca9dab`)
| Before | After |
|--------|-------|
| jekyll-sitemap 자동 생성 (974 URL, lastmod만) | 커스텀 `sitemap.xml` (1054 URL, priority+changefreq+last_modified_at) |

티어링:
- 홈 1.0 / daily
- 카테고리 0.9 / daily
- 최근 7일 0.9 / weekly
- 최근 30일 0.8 / weekly
- 최근 6개월 0.7 / monthly
- 그 외 0.5 / monthly

### 1.2 IndexNow 자동 제출 (`d5ca9dab`)
- 키 파일: `f71a0af133e16771baeeb3c5e137d8df.txt` (사이트 루트)
- CLI: `scripts/tools/indexnow_submit.py` (350줄, stdlib-only)
- 워크플로우: `.github/workflows/indexnow-submit.yml` (배포 후 최근 30개 포스트 자동 ping)
- 검증: HTTP 202 실측

### 1.3 GSC 자동 sitemap 제출 (`d5ca9dab` + `ee0f564c`)
- 도구: `scripts/tools/gsc_api.py` (URL Inspection / Search Analytics / sitemap submit)
- 도구: `scripts/tools/gsc_index_audit.py` (URL 일괄 감사 → 상태별 분류 + 카테고리 집계)
- deploy-pages.yml에 `submit-sitemap` 잡 추가
- `GSC_SERVICE_ACCOUNT_JSON` 시크릿 미설정 시 graceful skip

### 1.4 로컬 sitemap 무결성 검사 (`d5ca9dab`)
- `scripts/tools/check_sitemap_local.py`: 1054 URL → 빌드 산출물 매핑 검증

### 1.5 Description Boilerplate 동적 치환

**HIGH priority 9건 (`66e170eb`)** — `description_ko` 정적 suffix → 동적 데이터:

| 파일 | Before | After |
|------|--------|-------|
| `collect_fmp_calendar.py:552` | "FMP API 기반 ... 정리합니다." | 다음 경제 이벤트 / 실적 회사명 |
| `collect_defi_llama.py:1084` | "프로토콜별 예치 자산..." | 선두 체인 이름 |
| `collect_blockchain.py:338` | "온체인 데이터 기반..." | BTC 해시레이트 / ETH 가스 |
| `collect_political_trades.py:510` | "의회·SEC 내부자..." | 최다 거래 종목 (Counter) |
| `collect_market_indicators.py:1290` | "공포탐욕지수·VIX..." | 미국 10년물 금리 |
| `collect_geopolitical.py:918` | "분쟁·제재·무역..." | top Polymarket 시장 질문 |
| `collect_defi_yields.py:384` | "스테이블코인·ETH·BTC..." | ETH TOP 프로토콜 |
| `collect_coinmarketcap.py:1243` | "크립토 시장 리포트" (정적) | 총 시가총액 fallback |
| `collect_worldmonitor_news.py:1054` | "GDELT·Polymarket..." | 주요 출처명 |

모든 description 160자 cap, 빈 리스트/누락 키 edge case 가드.

**MEDIUM 6건 + LOW 3건 (`f9ff2c28`)** — body openings + section labels.

**Boilerplate 근원 3종 (`1a5421c3`)** — collect_crypto_news.py:855, collect_social_media.py:655+1099, collect_regulatory.py:430+808.

**top_title 한국어 번역 (`b5ac0998`)** — 영문 dominant 날 mixed-language 이슈 해소. 기존 `common.translator.translate_to_korean` 재사용.

### 1.6 URL 이미지 추출 강화 (`8ef84894`)
- `fetch_images_concurrent` 예산 60 → 120 (디지스트 카드 ~150건 커버)
- `_fetch_og_image` head 스캔 30KB → 60KB (modern 사이트 대응)
- JSON-LD `"image"` fallback 추가

### 1.7 Favicon 품질 개선 (`e6c37136`)
- favicon 해상도 64 → 128 (retina 선명도)
- `_best_favicon_link` 신규 헬퍼: `item['original_url']` 우선 → 진짜 publisher 도메인 favicon (cnbc.com 등)
- `enrichment.fetch_*_concurrent`: Google News URL 해석 결과를 `item['original_url']`에 저장 → 다음 단계에서 재사용

---

## 2. lang-toggle 5개 언어 지원

### 2.1 누락된 JS 파일 추가 (`6c9cf65f`)
- `_includes/google-translate.html`이 `/assets/js/google-translate.js` 로드 시도하지만 파일 없었음 → 클릭 무반응
- tech-blog 검증된 구현 832줄 이식
- 5개 언어: ko/en/ja/zh-CN/es

### 2.2 CSP 1차 수정 (`62f86db3`)
- 기존 CSP가 cdn.jsdelivr.net만 허용 → Google Translate 스크립트 차단
- script-src/script-src-elem/connect-src/style-src/font-src/frame-src에 Google Translate 도메인 추가
- script-src에 `'unsafe-eval'` 추가 (Google Translate 내부 동적 코드)

### 2.3 CSP 2차 수정 (`78987ef3`)
- 영어는 작동하나 中/日/ES는 여전히 차단 → frame-src 위반
- `frame-src 'self' https://translate.google.com https://translate.googleapis.com` (self-frame 허용)
- `child-src` 추가 (구형 브라우저)
- `X-Frame-Options: DENY` 유지 → 외부 사이트의 우리 frame 차단 (clickjacking 방지)

### 2.4 robots.txt + IndexNow 키 캐시 헤더 (`9bda528c`)
- 사이트 루트의 모든 `*.txt` 파일에 `Cache-Control: public, max-age=3600, s-maxage=86400` + `Content-Type: text/plain; charset=utf-8`

---

## 3. Claude Code / OMC 환경 베이스라인

### 3.1 팀 공유 settings.json (`185eebbb`)
- 기존: `.claude/hooks/*.sh` 3개 파일이 어떤 settings에서도 호출 안 됨 (사실상 미동작)
- 신규 `.claude/settings.json` (커밋됨, 팀 공유):
  - 권한 allow 16개: 프로젝트 스크립트, ruff, jekyll, git read-only, gh
  - 권한 deny 6개: `_state/`, `.env`, `_site/` 편집 차단
  - 훅 등록: protect-files / memory-guard / auto-lint-python

### 3.2 신규 훅 2개 (`3cbe5b2f`)
- `pre-commit-state-guard.sh`: `git commit` 명령에서 `_state/` 스테이지 감지 시 차단 (PreToolUse Bash matcher)
- `yaml-syntax-check.sh`: `.yml/.yaml` 편집 후 자동 syntax 검증 (PostToolUse, non-blocking warning)

### 3.3 Agent 정의 정규화 (`b61d9d28`, `6b66bedc`)
- `name:` 필드와 파일명 불일치 2건 수정 (architect, test-engineer)
- `vibe:` 필드 9개 모두 큰따옴표로 일관성 표준화
- `reports/agent-audit-2026-05-07.md`에 전체 감사 보고서

### 3.4 환경 README (`185eebbb`)
- `.claude/README.md` 신규 (237줄): 디렉토리 구조 + 9 agents + 8 skills + 7 rules + 5 hooks + 사용 패턴 + 자주 쓰이는 명령

### 3.5 도구 import 우회 (`6dae478b`)
- `scripts/common/__init__.py`가 crypto_api 등을 eager import해서 IndexNow 워크플로우가 ModuleNotFoundError(requests)로 실패
- `scripts/tools/*.py` 4개 파일에서 sys.path를 `scripts/common/`로 직접 가리켜 `config.py`만 stdlib로 import
- 영향 파일: indexnow_submit.py, gsc_api.py, gsc_index_audit.py, check_sitemap_local.py

---

## 4. 미완 작업 / 사용자 액션 필요

### 4.1 Vercel 봇 보호 (가장 큰 SEO 임팩트)
- 모든 IP/UA 조합에서 `HTTP/2 429 + x-vercel-mitigated: challenge`
- 대시보드: Settings → Security 탭에서 Bot Protection / Firewall 룰 검토
- 진단: GSC URL Inspection의 라이브 테스트 결과 + Vercel Firewall 로그가 필요 (curl 결과는 신뢰성 낮음)

### 4.2 GSC 서비스 계정 시크릿
- GitHub repo secret `GSC_SERVICE_ACCOUNT_JSON` 등록 필요
- 등록 후 `submit-sitemap` 잡이 자동 실행 (현재는 graceful skip)

### 4.3 1주일 후 색인 추이 측정
```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  python scripts/tools/gsc_index_audit.py \
    --from-sitemap \
    --output reports/gsc-audit-2026-05-14.md
```

### 4.4 수동 브라우저 검증
1. https://investing.2twodragon.com 강력 새로고침 (Cmd+Shift+R)
2. 글로브 → 中/日/ES 각각 클릭 후 본문 번역 확인
3. 콘솔 에러 없는지 확인

---

## 5. 머지된 dependabot PRs (9건)

| PR | 변경 |
|----|------|
| #819 | actions/setup-node 6.3 → 6.4 |
| #820 | certifi >=2026.1.4 → >=2026.4.22 |
| #822 | matplotlib 3.10.8 → 3.10.9 |
| #818 | pyyaml 6.0 → 6.0.3 |
| #816 | dependabot/fetch-metadata 3.0 → 3.1 |
| #821 | stefanzweifel/git-auto-commit-action 6.0 → 7.1 (major) |
| #823 | actions/github-script 7.0 → 9.0 (major skip v8) |
| #814 | py-cov-action/python-coverage-comment-action 3.40 → 3.41 |
| #815 | cachetools 5.3 → 7.1 (major) |

**미머지 1건**: #817 (pillow 12.1.1 → 12.2.0) — merge conflict, dependabot rebase 요청됨.

---

## 6. 검증 결과

### 6.1 Description 품질 (7일, 96 포스트)
| 지표 | 값 |
|------|---|
| 실제 콘텐츠 | 100.0% |
| Boilerplate | 0.0% |
| 제목 중복 | 0.0% |
| Mojibake | 0.0% |
| 번역 이슈 | 2.1% (영문 헤드라인 노출, fix `b5ac0998`로 다음 cycle부터 해소) |

### 6.2 코드 품질
- `python3 -m ruff check scripts/` → All checks passed (이번 세션 변경 19개 파일)
- JSON/YAML 검증 → vercel.json, .claude/settings.json, workflows 모두 OK

### 6.3 Sitemap 무결성
- 1054 URL 모두 빌드 산출물에 매핑됨 (`check_sitemap_local.py` 통과)

---

## 7. 핵심 커밋 (시간 역순)

```
e6c37136  feat(thumb): favicon 품질 개선 — 진짜 도메인 + 128px 해상도
78987ef3  fix(csp): frame-src에 'self' 추가 — 다국어 번역 활성
6b66bedc  chore(claude): vibe 필드 일관성 표준화
b61d9d28  chore(claude): agent .md frontmatter 일관성 정규화 (OMC 4.13.x)
3cbe5b2f  chore(claude): Wave 2 훅 추가 — pre-commit state guard + YAML 검증
185eebbb  chore(claude): 팀 공유 settings.json + README 추가 (Wave 1)
62f86db3  fix(csp): Google Translate 스크립트/리소스 허용 — lang-toggle 번역
9bda528c  fix(vercel): /*.txt 캐시 헤더 + Content-Type 명시
6c9cf65f  fix(i18n): 누락된 google-translate.js 추가 — lang-toggle 정상화
b5ac0998  feat(seo): top_title 한국어 번역 후 description_ko 노출
8ef84894  feat(enrichment): URL 이미지 추출 강화 — favicon 폴백 비율 감소
ee0f564c  fix(ci): GSC 시크릿 미설정 시 graceful skip + collector audit
6dae478b  fix(tools): GSC/IndexNow 도구 import 우회 — common/__init__.py 회피
f9ff2c28  feat(seo): MEDIUM 6건 + LOW 3건 정적 boilerplate 동적 치환
66e170eb  feat(seo): description_ko 정적 boilerplate 9건 동적 치환 (HIGH)
1a5421c3  feat(seo): 일일 다이제스트 description boilerplate 동적 치환
d5ca9dab  feat(seo): GSC 색인 가속 패키지 (sitemap + IndexNow + GSC submit)
```

---

## 8. 후속 작업 후보

| 작업 | 우선순위 | 트리거 |
|------|----------|--------|
| Vercel 봇 보호 검토 | HIGH | GSC URL Inspection 결과 |
| GSC 시크릿 등록 | HIGH | 사용자 액션 |
| Google News 디코더 강화 | MEDIUM | favicon 비율 측정 후 |
| favicon placeholder UX | MEDIUM | 시각적 다양성 |
| 7일 색인 추이 측정 | LOW | 1주일 후 자동 |
| `summarizer.generate_executive_summary` 동적화 | LOW | 추가 측정 후 |
