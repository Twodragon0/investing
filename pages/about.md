---
layout: default
title: "About"
permalink: /about/
---

# About Investing

Investing은 암호화폐 및 주식 시장의 뉴스를 자동으로 수집하고 분석하는 사이트입니다.

## 기능

- **암호화폐 뉴스**: CryptoPanic, NewsAPI, Google News RSS 등 다중 소스에서 자동 수집
- **주식 뉴스**: NewsAPI, Yahoo Finance, KRX 뉴스 자동 수집
- **트레이딩 일지**: 일일 거래 기록 및 손익 분석
- **보안 알림**: 해킹, 취약점, Rekt News 자동 수집
- **시장 분석**: 일일 시장 요약, 매크로 지표 분석

## 데이터 소스

| 소스 | 유형 | 업데이트 주기 |
|------|------|--------------|
| CryptoPanic | 암호화폐 뉴스 | 6시간 |
| NewsAPI | 뉴스 전반 | 6시간 |
| Google News RSS | 뉴스 | 6시간 |
| Yahoo Finance | 주식 데이터 | 6시간 |
| Rekt News | 보안 사고 | 6시간 |
| FRED | 매크로 지표 | 1일 |
| CoinGecko | 크립토 가격 | 1일 |
| Fear & Greed Index | 시장 심리 | 1일 |

## 기술 스택

- **사이트**: Jekyll + GitHub Pages
- **수집**: Python scripts + GitHub Actions
- **배포**: 자동 (push 시 GitHub Pages 빌드)

---

[GitHub Repository](https://github.com/Twodragon0/investing)
