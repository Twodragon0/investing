# 미등록 외부 API 키 영향 평가 + 등록 우선순위

작성: 2026-05-08 / 적용 범위: `scripts/` 수집기 5종 + `.github/workflows/`

본 보고서는 현재 GitHub Actions에 미등록 상태인 외부 API 키 5종(`CRYPTOPANIC_API_KEY`, `NEWSAPI_API_KEY`, `COINGECKO_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `TWITTER_BEARER_TOKEN`)이 운영 콘텐츠 품질에 미치는 영향을 코드·산출물·외부 API 정책 측면에서 평가하고, ROI 기준 등록 우선순위를 제시한다.

## 요약

- **즉시 등록 권장(P0)**: `TWITTER_BEARER_TOKEN` — social-media 카테고리가 사실상 비어 있는 가장 큰 결손 영역
- **등록 권장(P1)**: `CRYPTOPANIC_API_KEY`, `ALPHA_VANTAGE_API_KEY` — 명시 표기된 footer 소스 일관성 확보 + 데이터 보강
- **등록 보류(P2)**: `COINGECKO_API_KEY`, `NEWSAPI_API_KEY` — 전자는 현 부하에서 free tier로 충분, 후자는 코드 사용처 0건(레거시)

## 각 키 분석

### 1. `CRYPTOPANIC_API_KEY` — crypto news 수집

- **사용 위치**: `scripts/collect_crypto_news.py:765` → `fetch_cryptopanic()` (line 70~113)
- **부재 시 동작**: `if not api_key: ... return []` (line 72~74) — graceful skip. CoinDesk·Cointelegraph·Decrypt·Bitcoin Magazine·The Block RSS + Google News 브라우저 스크래핑 + Binance bapi가 자동 보강
- **콘텐츠 결손**: 중간 수준. CryptoPanic은 hot-news 큐레이션이 강점이지만 RSS 4종으로 본질적 커버리지는 유지됨. 다만 `collect_crypto_news.py:1174` footer가 "소스: CryptoPanic, ..."으로 표기되어 **실제 부재 시 표기 불일치** 발생
- **Free tier**: 일 200~500 req(2026 기준 상이, 확인 필요), 시간당 1회 cron으로 충분
- **등록 절차**: cryptopanic.com 가입 → Developer 페이지에서 token 복사 → `gh secret set CRYPTOPANIC_API_KEY`

### 2. `NEWSAPI_API_KEY` — 일반 뉴스 보강

- **사용 위치**: **코드 사용처 0건** (`grep -ir NEWSAPI scripts/` 결과 없음)
- **현황**: `collect_crypto_news.py:117` 주석에 "Fetch crypto news via Google News browser scraping (replaces NewsAPI)" 명시. NewsAPI는 이미 Google News 브라우저 스크래핑으로 대체됨
- **부재 시 동작**: 영향 없음. 단 `collect_stock_news.py:956` footer가 "소스: NewsAPI, ..."로 표기되어 **레거시 잔재**(실제 데이터 없음)
- **결론**: 등록 가치 없음. 오히려 footer 텍스트 정리(`scripts/collect_stock_news.py:956`)가 별도 후속 과제

### 3. `COINGECKO_API_KEY` — CoinGecko Pro tier

- **사용 위치**: **코드 사용처 0건** (`grep COINGECKO_API_KEY` 결과 없음). `scripts/common/crypto_api.py`는 free public 엔드포인트만 호출하며 요청 헤더 없음 (`x-cg-demo-api-key`/`x-cg-pro-api-key` 미설정)
- **현재 부하**: 매시간 `fetch_coingecko_top_coins/trending/global` 3회 + `generate_market_summary`에서 1회 = 시간당 4 req 수준. CoinGecko free tier는 분당 5~15회(공식 정책 시점에 따라 변동, 확인 필요)이므로 충분
- **등록 시 효과**: rate limit 완화 외 신규 데이터 없음. 키 인식 코드 추가 작업 필요(현재 헤더 미주입)
- **권장**: 보류. 트래픽이 분당 한도에 근접하기 전까지 ROI 낮음

### 4. `ALPHA_VANTAGE_API_KEY` — 주식 가격 보조

- **사용 위치**: `scripts/collect_stock_news.py:470` (`fetch_alpha_vantage_snapshot`, line 362~403) + `scripts/generate_market_summary.py:1115`
- **부재 시 동작**: `if not api_key: return []` (line 364~366) — SPY/QQQ/DIA 스냅샷 미수집. yfinance가 동일 ETF의 주가는 가져올 수 있으나 Alpha Vantage 전용 footer 표기 + 보조 카드는 사라짐
- **콘텐츠 결손**: 낮음~중간. `_posts/2026-05-09-daily-stock-news-digest.md` footer는 Alpha Vantage 표기 중이지만 실제 응답은 0건
- **Free tier**: 분당 5 req / 일 25 req (2026 기준, 확인 필요). 수집기 호출 3회/주기 → 안전
- **등록 절차**: alphavantage.co/support/#api-key 이메일 입력 → 즉시 발급 → `gh secret set ALPHA_VANTAGE_API_KEY`

### 5. `TWITTER_BEARER_TOKEN` — social_media 수집

- **사용 위치**: `scripts/collect_social_media.py:528` → `fetch_twitter_search()` (line 302~351). 6개 query 실행(bitcoin/crypto/Trump/이재명/코스피/비트코인 한국어)
- **부재 시 동작**: `if not bearer_token: return []` (line 304~306) — Twitter 데이터 전혀 수집 안 됨. Telegram·Reddit·정치 RSS·Google News Social KR로 부분 보강
- **콘텐츠 결손**: **현 시점 가장 큰 결손**. `_posts/2026-05-09-daily-social-media-digest.md`는 텔레그램 0건, 소셜 1건(Google News만), 정치·경제 10건 — 사실상 정치 뉴스 클립 수준이고 "social"이라는 제목이 무색
- **외부 정책 위험**: X API v2의 free tier는 2023~2024 사이 대폭 축소. Basic plan $200/월 필요할 가능성(2026-05 기준 정확한 가격은 확인 필요). free read-only tier 잔존 시에도 월 1500 tweet/일 제한 가능
- **등록 절차**: developer.twitter.com 신청 → 승인 후 Bearer Token 발급 → `gh secret set TWITTER_BEARER_TOKEN`

## 우선순위 매트릭스

| 키 | 가치 | 비용 | 위험 | 우선순위 | 근거 |
|----|-----|-----|-----|---------|------|
| `TWITTER_BEARER_TOKEN` | High | Med ($0~200/월, 확인 필요) | Med (정책 변동, 한도 축소) | **P0** | social-media 카테고리 결손이 가장 큼. free read-only tier 가능 시 즉시 등록 |
| `CRYPTOPANIC_API_KEY` | Med | 무료(추정 일 200req+) | Low | **P1** | RSS로 커버되지만 footer 표기 일관성 + hot-news 큐레이션 가치 |
| `ALPHA_VANTAGE_API_KEY` | Med | 무료 25req/일 | Low | **P1** | yfinance 보강이지만 Alpha Vantage footer 정합성 + 분 단위 시세 |
| `COINGECKO_API_KEY` | Low | 무료 demo / $129+/월 Pro | Low | **P2 보류** | 현 부하에서 free tier 충분, 키 인식 코드 추가 필요 |
| `NEWSAPI_API_KEY` | Zero | 무료 100req/일 | Low | **P2 폐지** | 코드 사용처 0건, footer 텍스트만 잔재 |

## 권장 액션

**P0 즉시 등록 (1건)**:
```bash
echo -n "$TWITTER_BEARER_TOKEN" | gh secret set TWITTER_BEARER_TOKEN
```
- 사전 확인: developer.twitter.com에서 free read-only access 가능 여부, 월 한도 적합성

**P1 검토 후 등록 (2건)**:
```bash
echo -n "$CRYPTOPANIC_API_KEY" | gh secret set CRYPTOPANIC_API_KEY
echo -n "$ALPHA_VANTAGE_API_KEY" | gh secret set ALPHA_VANTAGE_API_KEY
```
- 등록 후 다음 cron 실행에서 `_posts/...crypto-news-digest.md`, `...stock-news-digest.md` 본문에 신규 항목 등장 여부로 검증

**P2 보류 (2건)**:
- `COINGECKO_API_KEY`: 분 단위 rate limit 경보 발생 시 재평가
- `NEWSAPI_API_KEY`: 등록 불필요. 별도 후속으로 `collect_stock_news.py:956` footer 텍스트 정리 권장

## Follow-up

1. **footer 텍스트 정합성**: `collect_crypto_news.py:1174`, `collect_stock_news.py:956`의 정적 소스 표기를 실제 호출 결과 기반으로 동적 생성하도록 개선 (별도 PR)
2. **외부 API 정책 가격 검증**: 본 보고서의 free tier 한도/가격은 2026-05 일반 통념 기반. 등록 전 각 발급 사이트에서 최종 확인
3. **키 회전**: `docs/env-setup.md` § "키 회전"의 90일 주기를 따른다. 등록 시점을 `_state/` 외부 메모(예: 1Password)에 기록
4. **Twitter 대안 검토**: free tier 가격이 부적절하면 Reddit 강화·Mastodon API·Bluesky API 등 대안 평가 (별도 ralplan)
