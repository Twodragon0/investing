# 트레이딩 일지 개선 메모

`~/Desktop/crypto/crypto-monitoring/dashboard/static/index.html`, `~/Desktop/crypto/crypto-monitoring/dashboard/static/js/dashboard.js`, `~/Desktop/crypto/crypto-monitoring/trading_journal.py` 를 참고해 Investing Dragon의 트레이딩 일지 페이지와 포스트에 반영할 개선 방향을 정리합니다.

## 목표

- 일지 한 편만 봐도 시장 상황, 포지션 상태, 실행 근거를 빠르게 파악
- 뉴스/리포트 사이트인 `investing` 의 맥락을 유지하면서도 대시보드 수준의 요약성 확보
- `tech.2twodragon.com` 과 겹칠 수 있는 DevOps 운영 내용은 배제하고, 매매 의사결정과 성과 기록에 집중

## 우선순위 제안

### P1. 일지 상단 요약 카드 도입

현재 템플릿의 텍스트형 요약을 대시보드식 카드로 보강합니다.

- 핵심 지표: 당일 손익, 승률, 총 거래 횟수, 최대 손실, 최대 수익
- 시장 상태: 공포탐욕, BTC/ETH 변동률, 원/달러, KOSPI/KOSDAQ 또는 관련 시장 대표 지표
- 상태 배지: `관망`, `분할매수`, `리스크 축소`, `추세 추종` 같은 하루 전략 상태
- 데이터 신선도: 일지 생성 시각, 사용한 시장 데이터 기준 시각

참고 포인트:
- 크립토 대시보드의 metric row
- 연결 상태/마지막 업데이트 뱃지 패턴

### P1. 매매 기록 표를 포지션 맥락형으로 확장

현재 거래 로그 표를 단순 체결 기록에서 "의사결정 로그" 로 확장합니다.

- 컬럼 추가: 진입/청산 구분, 포지션 상태, 리스크 예산, 손절/익절 계획, 실제 결과
- 태그 추가: `추세`, `반등`, `뉴스`, `이벤트`, `헤지`, `오버나이트`
- 시그널 점수 외에 신뢰도 레벨(`low/medium/high`) 또는 색상 배지 제공
- 부분 청산과 재진입이 한 눈에 보이도록 거래 묶음 그룹화

참고 포인트:
- 대시보드 트레이딩 탭의 signal/position 구조
- `trading_journal.py` 의 `signal_score`, `reason`, `pnl`, `pnl_pct` 필드

### P1. 시장 인사이트 블록을 일지 안으로 흡수

매매 후기를 서술형 회고만 두지 말고, 대시보드의 insight 카드처럼 구조화합니다.

- 오늘 잘된 점 2~3개
- 오늘 놓친 점 2~3개
- 시장 환경과 실제 매매가 일치했는지 체크
- 다음 세션 액션 아이템 3개 제한

권장 형식:
- `잘한 판단`
- `실수 또는 잡음`
- `다음 세션 체크포인트`

### P2. 종목/자산별 미니 성과 시각화

포스트 본문에 작은 바 또는 밴드 시각화를 추가합니다.

- 종목별 손익 막대
- 계획 대비 실제 체결 품질
- 매수/매도 밀집 시간대 요약
- 1일 누적 손익 curve 또는 단계별 포지션 변화

참고 포인트:
- 크립토 대시보드의 bar chart, dominance chart, signal band 스타일
- 너무 큰 차트보다 포스트 안에 들어가는 compact block 우선

### P2. 저널-리포트 연결 강화

일지와 당일 리포트/뉴스를 양방향으로 연결합니다.

- 일지 상단에 관련 리포트 링크: 시장 요약, 규제, 소셜, 보안
- 어떤 기사/이벤트가 실제 진입 사유였는지 링크 첨부
- 주간 digest 에서 일지 핵심 성과를 자동 인용할 수 있도록 front matter 표준화

### P3. 검색/필터 관점의 메타데이터 정비

카테고리 랜딩 페이지에서 일지를 더 잘 찾도록 front matter 를 보강합니다.

- `trade_side`, `market_regime`, `confidence`, `holding_period`, `asset_group` 같은 메타데이터
- crypto/stock 공통 메타 스키마 유지
- 월간 리뷰 포스트에서 재집계 가능한 필드 우선

## 구현 메모

1. `scripts/common/post_generator.py` 의 front matter 확장 포인트를 활용해 일지 전용 메타데이터를 넣기 쉽게 만들기
2. 일지 템플릿 포스트(`_posts/2026-02-10-crypto-trading-journal-template.md`, `_posts/2026-02-10-stock-trading-journal-template.md`)를 카드형 구조로 개편하기
3. `_layouts/post.html` 또는 일지 전용 include 를 만들어 카드/배지/시그널 밴드를 재사용하기
4. 주간 digest 생성기가 일지의 핵심 지표를 재인용할 수 있도록 필드명을 표준화하기

## 추천 실행 순서

1. 일지 템플릿 개편 + 상단 요약 카드
2. 매매 기록 표 확장 + 포지션 상태 배지
3. 일지용 메타데이터 스키마 추가
4. 주간 digest 연동
5. 소형 시각화 블록 추가
