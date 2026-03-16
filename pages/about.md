---
layout: default
title: "About"
permalink: /about/
description: "Investing Dragon 프로젝트 소개 - 암호화폐 및 주식 뉴스 자동 수집, AI 분석 플랫폼"
---

# About Investing Dragon

Investing Dragon은 암호화폐와 주식 시장의 뉴스를 **자동으로 수집하고 분석**하는 투자 정보 플랫폼입니다. GitHub Actions 기반 CI/CD 파이프라인으로 24시간 자동 운영되며, 12개 이상의 데이터 소스에서 최신 시장 정보를 통합 제공합니다.

## 주요 기능

### 뉴스 수집
- **암호화폐 뉴스**: CryptoPanic, NewsAPI, Google News RSS 등 다중 소스에서 자동 수집
- **주식 뉴스**: Google News, Yahoo Finance, NASDAQ/Tech, Fed/Bond, 한국 반도체/수급/금리 뉴스
- **소셜 미디어 동향**: Telegram, Reddit(r/CryptoCurrency, r/Bitcoin), Google News 소셜 트렌드
- **규제 동향**: 글로벌 규제 변화, SEC, 금융위원회 관련 뉴스

### 시장 분석
- **일일 종합 리포트**: 미국 시장, 한국 시장, 암호화폐, 매크로 지표 통합 분석
- **주간 다이제스트**: 매주 자동 생성되는 주간 시장 요약
- **시장 지표**: Fear & Greed Index, DeFi TVL, 섹터별 히트맵
- **정치인 거래**: 미국 의회 및 SEC 내부자 거래 추적

### 시각화
- **자동 생성 차트**: 시장 히트맵, 공포/탐욕 게이지, 코인 순위 카드
- **OG 이미지**: 소셜 미디어 공유용 카테고리별 이미지 자동 생성
- **WebP 최적화**: 빠른 페이지 로딩을 위한 자동 이미지 변환

## 데이터 소스

| 소스 | 유형 | 업데이트 주기 |
|------|------|--------------|
| CryptoPanic | 암호화폐 뉴스 | 6시간 |
| NewsAPI | 뉴스 전반 | 6시간 |
| Google News RSS | 뉴스 (EN/KR, 20+ 피드) | 6~12시간 |
| Yahoo Finance | 주식 데이터 | 6시간 |
| yfinance | 미국/한국 시장 데이터 | 1일 |
| Reddit | 크립토 커뮤니티 | 12시간 |
| Rekt News | 보안 사고 | 6시간 |
| Alpha Vantage | 미국 시장 데이터 | 1일 |
| FRED | 매크로 경제 지표 | 1일 |
| CoinGecko | 크립토 가격/시총 | 1일 |
| Fear & Greed Index | 시장 심리 지수 | 1일 |
| CoinMarketCap | 시가총액 순위 | 6시간 |
| DeFi Llama | DeFi TVL 데이터 | 1일 |
| FMP Calendar | 경제 캘린더 | 1일 |

## 자동화 스케줄

| 작업 | 주기 | 시간 (KST) |
|------|------|-----------|
| 암호화폐 뉴스 수집 | 6시간 | 09:00, 15:00, 21:00, 03:00 |
| 주식 뉴스 수집 | 6시간 | 09:30, 15:30, 21:30, 03:30 |
| 소셜 미디어 수집 | 12시간 | 09:00, 21:00 |
| 시장 지표 수집 | 1일 | 09:10 |
| 일일 시장 리포트 | 1일 | 23:00 |
| 주간 다이제스트 | 매주 | 일요일 자정 |

## 기술 스택

| 영역 | 기술 |
|------|------|
| 사이트 | Jekyll (Ruby) + GitHub Pages |
| 수집 엔진 | Python 3 (11개 수집 스크립트) |
| 자동화 | GitHub Actions (25개 워크플로우) |
| 데이터 | yfinance, CoinGecko API, Google News RSS |
| 시각화 | matplotlib, Pillow (히트맵, 차트, 게이지) |
| 중복 방지 | SHA256 해시 + Fuzzy Matching (>80%) |
| 이미지 최적화 | 자동 WebP 변환 (quality=80) |
| SEO | jekyll-seo-tag, JSON-LD 구조화 데이터 |

## 면책 조항

> 본 사이트에서 제공하는 모든 정보는 **자동 수집된 데이터**를 기반으로 생성되었으며, **투자 조언이 아닙니다**. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다. 뉴스의 정확성은 원본 소스에 따르며, 수집 과정에서 오류가 발생할 수 있습니다.

---

[GitHub Repository](https://github.com/Twodragon0/investing)
