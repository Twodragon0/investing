---
layout: post
title: "Investing Dragon CI/CD 파이프라인 구조 분석"
date: 2026-03-15 10:00:00 +0900
categories: devops
description: "25개 GitHub Actions 워크플로우로 구성된 자동화 파이프라인의 구조와 운영 방식을 살펴봅니다."
tags:
  - CI/CD
  - GitHub Actions
  - 자동화
  - 인프라
---

## 프로젝트 자동화 구조

Investing Dragon 프로젝트는 25개의 GitHub Actions 워크플로우를 통해 뉴스 수집부터 배포까지 전 과정을 자동화하고 있습니다.

### 수집 파이프라인

11개의 수집 스크립트가 각각 독립적인 워크플로우로 실행됩니다.

| 수집기 | 대상 | 주기 |
|--------|------|------|
| `collect_crypto_news.py` | CryptoPanic, NewsAPI, Google News RSS | 2시간 |
| `collect_stock_news.py` | 주식 시장 뉴스 | 4시간 |
| `collect_social_media.py` | Reddit, Twitter/X | 3시간 |
| `collect_coinmarketcap.py` | CoinMarketCap 시세 | 6시간 |
| `collect_regulatory.py` | 규제 동향 | 6시간 |
| `collect_political_trades.py` | 미국 의회 거래 | 12시간 |
| `collect_worldmonitor.py` | 글로벌 이슈 | 4시간 |
| `collect_geopolitical.py` | 지정학적 리스크 | 6시간 |
| `collect_defi_llama.py` | DeFi TVL | 6시간 |
| `collect_fmp_calendar.py` | 경제 지표 | 12시간 |
| `collect_market_indicators.py` | Fear & Greed 등 | 4시간 |

### 동시성 관리

모든 수집 워크플로우는 `collect-data` 동시성 그룹으로 묶여 순차 실행됩니다. 이를 통해 Git 충돌을 방지하고 상태 파일의 일관성을 유지합니다.

```yaml
concurrency:
  group: collect-data
  cancel-in-progress: false
```

### 중복 방지 시스템

`scripts/common/dedup.py` 모듈이 SHA256 해시와 fuzzy matching(임계값 80%)을 조합해 중복 포스트를 걸러냅니다. `SequenceMatcher.quick_ratio()` 사전 필터로 비교 성능도 최적화했습니다.

### 요약 생성

수집된 데이터를 기반으로 5개 생성기가 분석 리포트를 만듭니다.

- **일일 요약** (`generate_daily_summary.py`): 하루 수집된 뉴스 종합
- **마켓 요약** (`generate_market_summary.py`): 시장 데이터 기반 분석
- **주간 다이제스트** (`generate_weekly_digest.py`): 한 주 핵심 정리
- **OG 이미지** (`generate_og_images.py`): SNS 공유용 이미지 자동 생성
- **운영 다이제스트** (`generate_ops_10am_digest.py`): 오전 10시 Slack 운영 리포트

### 배포

Jekyll 정적 사이트로 빌드되어 자동 배포됩니다. `fetch-depth: 1`로 CI 클론 성능을 최적화하고, 불필요한 Playwright 설치를 제거해 빌드 시간을 단축했습니다.
