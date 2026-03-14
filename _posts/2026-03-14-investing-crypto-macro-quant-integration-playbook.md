---
layout: post
title: "investing-crypto 연계 거시경제 퀀트 트레이딩 운영 플레이북"
date: 2026-03-14 21:30:00 +0900
categories: [market-analysis]
tags: [macro, quant, crypto, dashboard, workflow, playbook]
keywords: "거시경제 퀀트 트레이딩, crypto dashboard, investing 연계, 매크로 시그널, 리스크 관리"
source: "manual-research"
lang: "ko"
image: "/assets/images/generated/news-briefing-investing-crypto-playbook-2026-03-14.png"
image_alt: "investing-crypto 연계 거시경제 퀀트 트레이딩 운영 플레이북 대표 이미지"
description: "~/Desktop/investing의 뉴스·매크로 포스팅과 ~/Desktop/crypto의 대시보드 모니터링을 연결해 주식·크립토 거시경제 퀀트 트레이딩을 개선하는 운영 플레이북입니다."
excerpt: "investing 포스트 파이프라인과 crypto-monitoring 대시보드를 연결해 매크로 레짐 판정, 포지션 조절, 알림, 회고 루프를 구성하는 방법"
pin: false
---

> 이 문서는 같은 머신에 있는 `~/Desktop/investing`와 `~/Desktop/crypto`를 **운영 관점에서 연결**해,
> 뉴스/포스트 생산과 실시간 대시보드 모니터링이 서로 따로 놀지 않도록 만드는 실전 플레이북입니다.

## 목표

- `~/Desktop/investing`는 **거시경제 해석과 콘텐츠 기록 허브**로 사용합니다.
- `~/Desktop/crypto`는 **실시간 대시보드, 백테스트, 시그널 모니터링 허브**로 사용합니다.
- 두 시스템을 연결해 **거시경제 레짐 변화 → 크립토/주식 포지션 관리 → 포스팅/회고 업데이트**까지 하나의 루프로 묶습니다.

---

## 현재 확인된 핵심 구성

### investing 쪽
- `scripts/collect_market_indicators.py`: VIX, DXY, 금리, 공포탐욕 등 리스크 대시보드 생성
- `scripts/generate_market_summary.py`: FRED 기반 거시경제 지표 + BTC ETF + 퀀트 시그널 요약
- `scripts/collect_worldmonitor_news.py`: 지정학, 에너지, 매크로 시그널 결합
- `scripts/common/signal_composer.py`: 매크로/모멘텀/심리 시그널 가중 합성
- `scripts/common/bettafish_analyzer.py`: 거시 판정(`강세/중립/약세`)과 서사 생성

### crypto 쪽
- `~/Desktop/crypto/crypto-monitoring/economic_collector.py`: FRED/ECOS 기반 경제지표 수집
- `~/Desktop/crypto/crypto-monitoring/market_intelligence.py`: investing 포스트와 외부 API를 읽어 구조화된 신호로 변환
- `~/Desktop/crypto/crypto-monitoring/dashboard/app.py`: 대시보드 앱
- `~/Desktop/crypto/crypto-monitoring/scripts/run_live_quant_cycle.sh`: 라이브 퀀트 사이클 실행
- `~/Desktop/crypto/crypto-monitoring/scripts/intraday_live_tracker.py`: 장중 추적
- `~/Desktop/crypto/docs/trading-strategy-crypto-macro-2026.md`: 매크로-크립토 전략 정리

핵심은 이미 두 저장소가 **같은 문제를 다른 층위에서 풀고 있다**는 점입니다.
- `investing`는 해석, 기록, 공개 요약에 강하고
- `crypto-monitoring`은 수집, 추적, 백테스트, 실행 제어에 강합니다.

---

## 권장 운영 구조

### 1. Macro Research Layer — investing
`investing`는 다음 역할에 집중합니다.

- 매일 아침 **거시경제 환경 요약**
- 장 전후 **시장 리스크 서사 정리**
- 주식/크립토 공통으로 보는 **DXY, 10Y, VIX, Fed, ETF flows** 해석
- 포스트로 남는 기록을 통해 **나중에 회고 가능한 텍스트 데이터베이스** 생성

즉, `investing`는 "지금 왜 이런 장세인지"를 설명하는 레이어입니다.

### 2. Execution Monitoring Layer — crypto
`crypto-monitoring`은 다음 역할에 집중합니다.

- 대시보드에서 **실시간 포지션/시그널 모니터링**
- 장중 알림과 라이브 루프 실행
- 백테스트와 전략 챔피언 모델 검증
- 거래 로그/체결 로그/시장 인텔리전스를 통한 **규칙 기반 실행 품질 관리**

즉, `crypto`는 "지금 무엇을 얼마나 실행할지"를 제어하는 레이어입니다.

### 3. Feedback Layer — 둘을 연결
이 레이어가 가장 중요합니다.

- `investing`가 생성한 거시 판정을 `crypto`의 포지션 제한 규칙에 반영
- `crypto` 대시보드의 라이브 상태/백테스트 결과를 `investing` 포스트의 회고 섹션에 반영
- 결과적으로 **서사와 실행이 분리되지 않도록** 합니다.

---

## 매크로 퀀트 트레이딩 개선용 Top 10 연계 규칙

### 1. DXY 상승 시 알트 노출 축소
- `investing/scripts/collect_market_indicators.py`는 이미 DXY를 수집합니다.
- `crypto-monitoring`에서는 DXY가 강달러 레짐이면:
  - 알트 비중 축소
  - BTC 중심 유지
  - 레버리지 상한 축소

### 2. 10년물 실질/명목 금리 상승 시 성장 베타 축소
- 금리 상승은 나스닥과 고베타 코인에 동시에 역풍일 수 있습니다.
- `crypto`의 전략 실행 계층에서 **브레이크아웃 전략 진입 조건을 더 엄격하게** 두는 것이 좋습니다.

### 3. VIX 급등 시 신규 진입보다 방어 우선
- `bettafish_analyzer.py`는 VIX를 이미 헤드윈드/테일윈드로 해석합니다.
- 이 판정이 약세일 때는:
  - 신규 진입 수 제한
  - 손절 폭 축소
  - 평균회귀 전략 비중 축소

### 4. Fed 완화 기대 회복 시 BTC/대형주 베타 확대
- `Fed금리 + DXY + 10Y` 조합이 완화 방향으로 변하면
  - BTC, ETH, 나스닥 리더주의 추세 전략 가중치 상향
  - 알트는 후행 확인 후 확장

### 5. ETF 자금 유입은 추세 확인 지표로만 사용
- `generate_market_summary.py`는 BTC ETF 흐름을 다룹니다.
- ETF 유입은 진입 신호가 아니라 **추세 지속 확인용**으로 쓰는 것이 좋습니다.

### 6. 월드모니터 지정학 리스크는 포지션 캡으로 연결
- `collect_worldmonitor_news.py`는 에너지/지정학/매크로를 같이 봅니다.
- 지정학 경보가 커지면:
  - 전체 gross exposure 상한 축소
  - 주말 보유 비중 축소

### 7. investing 포스트를 crypto 대시보드 입력 데이터로 재활용
- `market_intelligence.py`는 investing 플랫폼 포스트를 읽는 구조입니다.
- 따라서 `investing`의 포스트 품질이 곧 `crypto` 입력 품질입니다.
- 뉴스 요약 문장보다 **수치형 근거와 판정 문구를 일정한 형식으로 넣는 것**이 중요합니다.

### 8. 포스트와 대시보드의 판정 기준을 동일하게 유지
다음 기준은 두 저장소 모두에서 최대한 동일해야 합니다.

| 항목 | 공통 기준 예시 |
| --- | --- |
| 강달러 | DXY 105 이상 |
| 금리 부담 | 미국 10년물 4.5% 이상 |
| 공포 확대 | VIX 25 이상 |
| 유동성 우호 | Fed 완화 + DXY 하락 + 장기금리 안정 |

판정 기준이 다르면 포스팅은 강세인데 대시보드는 약세로 나오며 운영이 망가집니다.

### 9. 백테스트 결과를 포스트 회고 섹션에 연결
`~/Desktop/crypto/docs/backtest_results/`에는 BTC/ETH 전략 결과와 거래 JSON이 있습니다.
이 결과를 `investing` 쪽 주간/월간 회고 포스트에 연결하면,
- 어떤 거시 레짐에서 어떤 전략이 강했는지
- 브레이크아웃과 평균회귀 중 무엇이 유리했는지
- 알트/비트코인/현금 비중이 어땠는지
를 기록할 수 있습니다.

### 10. 운영 루프를 "포스팅 → 모니터링 → 회고"로 고정
추천 일일 루프:
1. `investing`에서 아침 매크로 요약 생성
2. `crypto` 대시보드에서 라이브 시그널/리스크 상태 점검
3. 장 마감 후 포지션/시그널 변화 기록
4. 다음 날 포스트에 회고 반영

---

## 추천 운영 시나리오

### 시나리오 A: 리스크 오프 장세
조건
- DXY 상승
- 10년물 상승
- VIX 상승
- 월드모니터 지정학 리스크 확대

행동
- BTC 외 알트 익스포저 축소
- 평균회귀 전략보다 현금 비중 확대
- 포스트 제목/요약도 "반등 기대"보다 "리스크 관리" 중심으로 작성

### 시나리오 B: 유동성 재확장 장세
조건
- DXY 하락
- 장기금리 안정 또는 하락
- VIX 안정
- ETF 자금 유입 증가

행동
- BTC/ETH 추세 전략 비중 확대
- 주식에선 나스닥 리더주/모멘텀 리더주 체크 강화
- 포스트는 "상승의 이유"보다 "상승이 유지되는 조건"을 구조화

### 시나리오 C: 박스권/혼조 장세
조건
- DXY, 금리, VIX 모두 방향성 애매
- ETF/온체인/거시가 서로 상충

행동
- 진입 빈도 축소
- 평균회귀 전략 중심
- 포스트는 강한 뷰 제시보다 관찰 포인트 중심으로 작성

---

## 실제 연결 포인트

### 로컬 경로 기준
```bash
~/Desktop/investing
~/Desktop/crypto/crypto-monitoring
```

### 운영자가 매일 보는 파일
```text
investing/scripts/collect_market_indicators.py
investing/scripts/generate_market_summary.py
investing/scripts/collect_worldmonitor_news.py
crypto/crypto-monitoring/economic_collector.py
crypto/crypto-monitoring/market_intelligence.py
crypto/crypto-monitoring/dashboard/app.py
crypto/crypto-monitoring/scripts/run_live_quant_cycle.sh
```

### 추천 실행 순서
```bash
# 1) investing 쪽 거시/시장 포스트 생성
cd ~/Desktop/investing
python3 scripts/collect_market_indicators.py
python3 scripts/generate_market_summary.py

# 2) crypto 쪽 대시보드/라이브 사이클 점검
cd ~/Desktop/crypto/crypto-monitoring
python3 economic_collector.py
python3 market_intelligence.py
bash scripts/run_live_quant_cycle.sh
```

---

## 포스팅 품질 개선 규칙

`investing` 포스트를 단순 뉴스 요약이 아니라, `crypto-monitoring`이 재사용할 수 있는 **운영 문서**로 만들려면 다음을 지키는 것이 좋습니다.

- 수치형 근거를 넣기
  - 예: DXY 105.2, 미국 10년물 4.48%, VIX 23.1
- 판정을 명시하기
  - 예: "오늘 매크로 판정은 중립-약세"
- 행동 규칙을 적기
  - 예: "알트 공격 비중 확대보다 BTC 중심 유지"
- 주식/크립토 공통 프레임을 유지하기
  - 예: 금리, 달러, 유동성, 변동성

이렇게 해야 포스트가 곧 대시보드 운영 매뉴얼이 됩니다.

---

## 결론

가장 좋은 구조는 다음입니다.

- `investing` = **왜 이런 장인지 설명하는 두뇌**
- `crypto-monitoring` = **지금 무엇을 실행할지 판단하는 손발**
- 둘 사이를 연결하는 것은 **공통 매크로 판정 기준 + 회고 루프**입니다

즉, 포스트는 단순 콘텐츠가 아니라 **거시경제 퀀트 트레이딩 운영 로그**가 되어야 하고, 대시보드는 단순 시각화가 아니라 **포스트의 실행 검증 장치**가 되어야 합니다.

이 구조가 잡히면 주식과 크립토를 따로 보지 않고,
**유동성 → 금리 → 달러 → 변동성 → 포지션 크기** 순서로 일관된 운영이 가능해집니다.
