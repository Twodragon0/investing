---
layout: default
title: "About"
permalink: /about/
---

# About Investing Dragon

Investing Dragon은 암호화폐 및 주식 시장의 뉴스를 **자동으로 수집하고 분석**하는 플랫폼입니다. GitHub Actions를 통해 24시간 자동으로 운영되며, 다양한 소스에서 최신 정보를 제공합니다.

## 주요 기능

- **암호화폐 뉴스**: CryptoPanic, NewsAPI, Google News RSS 등 다중 소스에서 자동 수집
- **주식 뉴스**: Google News, Yahoo Finance, NASDAQ/Tech, Fed/Bond, 한국 반도체/수급/금리 뉴스
- **소셜 미디어 동향**: 텔레그램, Reddit(r/CryptoCurrency, r/Bitcoin), Google News 소셜 트렌드
- **정치·경제 동향**: 트럼프 경제정책, 이재명 경제정책, Fed 정책, 한국은행 금리, 증시 수급
- **보안 알림**: Rekt News, 블록체인 해킹/취약점 자동 수집
- **시장 분석**: 일일 종합 리포트 (미국 시장, 한국 시장, 암호화폐, 매크로 지표)
- **주간 다이제스트**: 매주 자동 생성되는 주간 시장 요약
- **트레이딩 일지**: 암호화폐/주식 매매 기록 및 손익 분석

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

## 자동화 스케줄

| 작업 | 주기 | 시간 (KST) |
|------|------|-----------|
| 암호화폐 뉴스 수집 | 6시간 | 09:00, 15:00, 21:00, 03:00 |
| 주식 뉴스 수집 | 6시간 | 09:30, 15:30, 21:30, 03:30 |
| 소셜 미디어 수집 | 12시간 | 09:00, 21:00 |
| 일일 시장 리포트 | 1일 | 23:00 |
| 주간 다이제스트 | 매주 | 일요일 자정 |

## 기술 스택

- **사이트**: Jekyll + GitHub Pages
- **수집**: Python 3 스크립트
- **자동화**: GitHub Actions (CI/CD)
- **데이터**: yfinance, CoinGecko API, Google News RSS
- **시각화**: matplotlib, Pillow (히트맵, 차트)
- **배포**: 자동 (push 시 GitHub Pages 빌드)

## 면책 조항

> 본 사이트에서 제공하는 모든 정보는 **자동 수집된 데이터**를 기반으로 생성되었으며, **투자 조언이 아닙니다**. 모든 투자 결정은 개인의 판단과 책임 하에 이루어져야 합니다. 뉴스의 정확성은 원본 소스에 따르며, 수집 과정에서 오류가 발생할 수 있습니다.

---

[GitHub Repository](https://github.com/Twodragon0/investing)
