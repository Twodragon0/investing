---
layout: post
title: "DeFi TVL 집계 기준 변경 공지 - 2026-04-20"
date: 2026-04-20 16:00:00 +0900
categories: [defi, announcements]
tags: ["notice", "defi-llama", "tvl"]
keywords: "notice, defi-llama, tvl, migration"
source: "자체 공지"
lang: "ko"
image: "/assets/images/generated/news-briefing-defillama-v1-migration-notice-2026-04-20.png"
permalink: "/defi/2026/04/20/defillama-v1-migration-notice/"
description: "DeFi TVL 수집을 DefiLlama /v2/protocols → /protocols (v1)로 전환합니다. CEX 필터링 유지하에 실시간 업데이트를 보장하며, 기존 일일 리포트의 수치가 v1 집계로 조정됩니다."
image_alt: "DeFi TVL 공지 - 집계 기준 변경"
excerpt: "2026-03-22부터 약 한 달간 일일 DeFi TVL 리포트의 상위 20개 프로토콜 총합이 $247 - Investing Dragon 자동 수집 분석 리포트."
---

## 배경

## 전체 뉴스 요약

- - 엔드포인트: /v2/protocols → /protocols (v1) - CEX 제외 필터링 유지 (기존과 동일한 "DeFi 전용" 스코프) - TVL 수치는 v1 실시간 집계로 갱신. v1은 v2 대비 LST/derivative 집계 방식 차이로 Lido·AAVE 등 주요…
- - 2026-04-20 이후 생성되는 일일 DeFi TVL 리포트부터 v1 수치 반영 - 과거 포스트의 TVL 수치는 변경되지 않음 (기록 보존) - 같은 _state/defi_tvl_history.json에 이어 기록되므로 시계열 차트 상 일시적 단차 발생 가능. 추후 차트 해석…


## 변경

- 엔드포인트: `/v2/protocols` → `/protocols` (v1)
- CEX 제외 필터링 유지 (기존과 동일한 "DeFi 전용" 스코프)
- TVL 수치는 v1 실시간 집계로 갱신. v1은 v2 대비 LST/derivative 집계 방식 차이로 Lido·AAVE 등 주요 프로토콜의 값이 **수십 퍼센트 조정** 가능
- 예: Lido TVL $33.9B(v2 스테일) → $21.6B(v1 실시간, 2026-04-20 기준)

## 영향

- 2026-04-20 이후 생성되는 일일 DeFi TVL 리포트부터 v1 수치 반영
- 과거 포스트의 TVL 수치는 변경되지 않음 (기록 보존)
- 같은 `_state/defi_tvl_history.json`에 이어 기록되므로 **시계열 차트 상 일시적 단차** 발생 가능. 추후 차트 해석 시 2026-04-20을 전환 시점으로 참고

## 데이터 출처

- [DefiLlama API 문서](https://defillama.com/docs/api)
- 수집 코드: `scripts/collect_defi_llama.py`
- 품질 가드: `scripts/common/time_series_state.py` (Phase 1~5 설계)
