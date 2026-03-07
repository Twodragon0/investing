# DragonQuant Platform Architecture

## 플랫폼 개요

DragonQuant는 **데이터 인텔리전스**와 **퀀트 트레이딩**을 결합한 AI 기반 투자 의사결정 플랫폼입니다.
두 개의 독립 저장소가 명확한 역할 분리와 데이터 연동을 통해 하나의 플랫폼으로 동작합니다.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DragonQuant Platform                                 │
│                                                                             │
│  ┌──────────────────────────────┐    ┌──────────────────────────────────┐   │
│  │   investing (Data Layer)     │    │   crypto (Trading Engine)        │   │
│  │                              │    │                                  │   │
│  │  "시장을 읽는다"              │───▶│  "시장에서 행동한다"              │   │
│  │                              │    │                                  │   │
│  │  - 뉴스/규제/정치 수집        │    │  - 14 MI + 7 TA 시그널 합성      │   │
│  │  - 소셜 미디어 감성 추적      │    │  - 동적 레짐 감지 자동매매 엔진       │   │
│  │  - 매크로 지표 모니터링       │    │  - CVaR + Drawdown Scaling 제어           │   │
│  │  - 일일/주간 요약 생성        │    │  - 보안 이벤트 실시간 감지       │   │
│  │  - OG 이미지/SEO 최적화       │    │  - 백테스팅 & 몬테카를로 검증    │   │
│  └──────────────────────────────┘    └──────────────────────────────────┘   │
│                                                                             │
│                         Output: B2C 구독 / B2B SaaS API                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## PSST 프레임워크 매핑

### Problem (문제 인식)

| 문제 | 현상 | 정량 근거 |
|:-----|:-----|:---------|
| 개인 투자자 뇌동매매 | 감정적 의사결정, 손익비 붕괴 | 개인 투자자 70%+ 손실 (금감원 2025) |
| 기존 봇의 보안 취약점 | API Key 탈취, 단일 지표 의존 | 2025년 거래소 해킹 피해 $2.1B (rekt.news) |
| 정보 비대칭 | 기관 대비 늦은 뉴스 반영 | 개인은 뉴스 반영까지 평균 4시간 지연 |
| 리스크 관리 부재 | 하락장에서 원금 전액 노출 | Buy & Hold MDD 63.58% vs 전략 MDD 6.93% |

### Solution (실현 방안)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DragonQuant Solution Stack                            │
│                                                                         │
│  Layer 1: Data Intelligence (investing repo)                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  20+ 데이터 소스 자동 수집 → 중복 제거 → 감성 분석 → 구조화 출력   │ │
│  │  8 Collectors | 3 Generators | SHA256+Fuzzy Dedup | OG/SEO 최적화  │ │
│  └──────────────────────────────┬─────────────────────────────────────┘ │
│                                 │ _posts/*.md (구조화된 시장 데이터)     │
│                                 ▼                                       │
│  Layer 2: Signal Synthesis (crypto repo)                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  StructuredPostParser → 14-Component Market Intelligence           │ │
│  │  + 7 Technical Indicators (VWAP 포함) → Composite Signal [-1, +1]  │ │
│  └──────────────────────────────┬─────────────────────────────────────┘ │
│                                 │                                       │
│                                 ▼                                       │
│  Layer 3: Risk-Controlled Execution (crypto repo)                       │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Quarter-Kelly Sizing | CVaR Tail Risk | Circuit Breaker           │ │
│  │  ATR Stop-Loss | Trailing Stop | Multi-TP | Drawdown Limit 20%    │ │
│  │  Exp Drawdown Scaling | Vol-of-Vol | Time-Decay Exit              │ │
│  └──────────────────────────────┬─────────────────────────────────────┘ │
│                                 │                                       │
│                                 ▼                                       │
│  Layer 4: Verification & Monitoring                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  DSR 과적합 검정 | Monte Carlo 500회 | IC/ICIR 시그널 품질 분석     │ │
│  │  FastAPI Dashboard | WebSocket 실시간 | Slack 4-Channel Alert       │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Scale-up (성장 전략)

| Phase | 기간 | 대상 | 모델 | 핵심 지표 |
|:------|:-----|:-----|:-----|:---------|
| **Phase 1 (MVP)** | 0-6개월 | 암호화폐 Top 5 (BTC, ETH, SOL, XRP, LINK) | B2C 구독 (Paper Trading 무료) | MAU, 구독 전환율 |
| **Phase 2** | 6-12개월 | 국내외 주식 확장 | B2B SaaS API (소형 펀드, 핀테크) | API 호출량, MRR |
| **Phase 3** | 12-18개월 | 멀티 에셋 (원자재, FX) | 엔터프라이즈 라이선스 | ARR, 기관 계약 수 |

### Team (팀 역량)

| 역할 | 담당 범위 | 기술 스택 |
|:-----|:---------|:---------|
| **Full-Cycle Engineer** | 인프라 → 데이터 → 매매 로직 → 검증 | AWS/GCP, Python, Docker, GitHub Actions |
| | DevSecOps 파이프라인 설계 및 운영 | Bandit, Trivy, CodeQL, OWASP Top 10 |
| | 백테스팅 엔진 및 통계 검증 | CPCV, Monte Carlo, DSR, IC/ICIR |

---

## 저장소별 역할 분리

### investing (데이터 인텔리전스 계층)

**목적**: 시장 데이터를 수집하고, 구조화하고, 공개 발행하는 파이프라인

```
GitHub: Twodragon0/investing
Live:   investing.2twodragon.com

역할:
├── 수집 (Collection)     → 20+ 소스에서 뉴스/지표 자동 수집
├── 정제 (Processing)     → 중복 제거, 감성 분석, 요약 생성
├── 발행 (Publishing)     → Jekyll 정적 사이트 + OG 이미지
└── 출력 (Output)         → _posts/*.md (crypto repo가 소비)
```

| 구성 요소 | 수량 | 설명 |
|:----------|:-----|:-----|
| 수집기 (Collectors) | 8개 | crypto, stock, regulatory, political, social, coinmarketcap, worldmonitor, defi_llama |
| 생성기 (Generators) | 5개 | daily_summary, market_summary, weekly_digest, og_images, ops_10am_digest |
| 공통 모듈 | 15개 | config, dedup, utils, post_generator, image_generator 등 |
| 데이터 소스 | 20+ | CryptoPanic, NewsAPI, FRED, CoinGecko, SEC, FSC 등 |
| GitHub Actions | 23개 | 수집 8 + 생성 5 + 운영 10 |
| 카테고리 페이지 | 9개 | crypto, stock, regulatory, political, social 등 |

### crypto (퀀트 트레이딩 엔진)

**목적**: investing repo의 구조화 데이터를 소비하여 매매 시그널을 생성하고 실행

```
GitHub: Twodragon0/crypto

역할:
├── 데이터 소비 (Intake)      → investing/_posts/ 파싱 + 외부 API 직접 수집
├── 시그널 합성 (Signal)      → 14-Component MI + 7 Technical Indicators (VWAP)
├── 매매 실행 (Execution)     → Upbit/Bithumb API, Paper/Live 모드
├── 리스크 제어 (Risk)        → Kelly, CVaR, Circuit Breaker
├── 보안 모니터링 (Security)  → Telegram/DCInside/Blockchain 실시간 감지
└── 검증 (Verification)       → Backtest, Monte Carlo, DSR, IC/ICIR
```

| 구성 요소 | 수량 | 설명 |
|:----------|:-----|:-----|
| 핵심 서비스 | 4개 | monitor, quant_trader, post_generator, dashboard |
| 데이터 수집기 | 9개 | economic, alternative, regulatory, onchain, cdp, cmc, polymarket, social_signal, worldmonitor |
| 트레이딩 모듈 | 7개 | swing_strategy, swing_indicators (VWAP 포함), paper_broker, state_cache 등 |
| 마켓 인텔리전스 컴포넌트 | 14개 | F&G, social, macro, funding 등 (가중치 합계 1.0) |
| 테스트 | 2,373개 (crypto) + 112개 (investing) = **2,485개** | 전체 모듈 커버리지 |
| GitHub Actions | 16개 | CI/CD, security scan, quant trader 실행 등 |

---

## 데이터 연동 아키텍처

두 저장소 간 데이터 흐름의 핵심은 `StructuredPostParser`입니다.

```
┌─────────────────────────────────────────────────────────────────────┐
│                   investing repo (Data Layer)                       │
│                                                                     │
│  [CryptoPanic] [NewsAPI] [SEC] [FRED] [CoinGecko] [Telegram] ...   │
│        │          │        │     │        │           │             │
│        ▼          ▼        ▼     ▼        ▼           ▼             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  8 Collectors → Dedup Engine → Post Generator               │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 │                                   │
│                                 ▼                                   │
│               ~/Desktop/investing/_posts/*.md                       │
│               (구조화된 Jekyll 포스트)                                │
│                                                                     │
│  포스트 예시:                                                        │
│  ├── 2026-03-07-daily-crypto-news-digest.md                        │
│  ├── 2026-03-07-daily-stock-news-digest.md                         │
│  ├── 2026-03-07-daily-political-trades-report.md                   │
│  ├── 2026-03-07-daily-regulatory-report.md                         │
│  └── 2026-03-07-daily-worldmonitor-briefing.md                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            │  StructuredPostParser
                            │  (정규식 기반 구조화 데이터 추출)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    crypto repo (Trading Engine)                      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  market_intelligence.py                                      │   │
│  │                                                              │   │
│  │  포스트에서 추출하는 데이터:                                    │   │
│  │  ├── BTC Dominance (%)      → btc_dom signal (weight 0.06)  │   │
│  │  ├── VIX Index              → vix signal (weight 0.08)      │   │
│  │  ├── KOSPI/KOSDAQ/USD-KRW   → korean signal (weight 0.07)  │   │
│  │  ├── Fear & Greed Index     → f&g signal (weight 0.17)     │   │
│  │  ├── Hack Amounts ($M)      → security signal (weight 0.07)│   │
│  │  ├── Political Keywords     → political signal (weight 0.08)│   │
│  │  ├── Regulatory Updates     → regulatory signal (weight 0.04)│  │
│  │  ├── Social Sentiment       → social signal (weight 0.12)  │   │
│  │  └── Trending Coins         → +10% signal boost            │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 │                                   │
│                                 ▼                                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  quant_trader.py                                             │   │
│  │                                                              │   │
│  │  Signal = base_ta * 0.75 + MI * 0.25 + bullish_offset(0.10) │   │
│  │  + swing_signal * 0.40 (Bithumb only)                       │   │
│  │  → Clamp [-1, +1]                                           │   │
│  │  → Dynamic Regime Detection (Bull/Bear/Sideways)             │   │
│  │  → BUY if > threshold | SELL if < threshold (레짐별 조정)    │   │
│  │  → Quarter-Kelly Position Sizing                             │   │
│  │  → CVaR Tail Risk + Exp Drawdown Scaling                    │   │
│  │  → Vol-of-Vol Penalty + Time-Decay Exit                     │   │
│  │  → Circuit Breaker (MDD 20%)                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 연동 데이터 흐름 요약

| 방향 | 소스 | 대상 | 데이터 | 방식 |
|:-----|:-----|:-----|:------|:-----|
| investing → crypto | `_posts/*.md` | `StructuredPostParser` | BTC Dom, VIX, 감성, 해킹 금액 등 | 파일 시스템 읽기 (정규식 파싱) |
| investing → crypto | `_posts/*.md` | `market_intelligence.py` | 뉴스 감성, 정치 리스크, 규제 시그널 | VADER + 키워드 분석 |
| crypto → investing | `posts/*.md` | `StructuredPostParser` | 일일 리포트, 보안 리포트 | 파일 시스템 읽기 |
| 공유 외부 API | FRED, CoinGecko 등 | 양쪽 모두 | 매크로 지표, 코인 가격 | 독립 호출 (캐시) |

---

## 기술 인프라

### DevSecOps 파이프라인

```
┌─────────────────────────────────────────────────────────────────┐
│                    CI/CD & Security Pipeline                     │
│                                                                 │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │  Lint   │  │  Test   │  │ Security │  │    Deploy        │  │
│  │         │  │         │  │          │  │                 │  │
│  │ ruff    │→│ pytest  │→│ Bandit   │→│ GitHub Pages    │  │
│  │ pyright │  │ 2,485  │  │ Trivy    │  │ Vercel          │  │
│  │ actionl │  │ tests  │  │ CodeQL   │  │ Docker          │  │
│  │         │  │         │  │ Gitleaks │  │                 │  │
│  └─────────┘  └─────────┘  └──────────┘  └─────────────────┘  │
│                                                                 │
│  동시성 제어: collect-data 그룹 (push 충돌 방지)                  │
│  워크플로우: investing 23개 + crypto 16개 = 39개                  │
└─────────────────────────────────────────────────────────────────┘
```

### 보안 계층

| 계층 | 구현 | 적용 범위 |
|:-----|:-----|:---------|
| **입력 검증** | `sanitize_string()`, `validate_url()` | 모든 외부 데이터 |
| **API 보호** | Rate Limiting, TTL 캐시, Circuit Breaker | 외부 API 호출 |
| **인증 격리** | `.env` + GitHub Secrets, IAM 최소 권한 | API 키/토큰 |
| **컨테이너 보안** | non-root, read-only FS, 리소스 제한 | Docker 런타임 |
| **트레이딩 보안** | Paper 모드 기본, 3중 확인, 일일 손실 상한 | 실매매 실행 |
| **의존성 검사** | pip-audit, Safety, Dependabot | 매주 자동 스캔 |
| **코드 분석** | Bandit, CodeQL, Gitleaks | PR/Push 자동 실행 |

### 클라우드 인프라 (예비창업패키지 자금 투입 계획)

| 항목 | 서비스 | 월 예상 비용 | 용도 |
|:-----|:------|:-----------|:-----|
| 컴퓨팅 | AWS EC2 (t3.large) | ~$60 | 퀀트 엔진 24/7 실행 |
| DB | AWS RDS PostgreSQL | ~$30 | 거래 이력, 시그널 로그 |
| 스토리지 | S3 | ~$5 | 백테스트 결과, 이미지 |
| CDN | CloudFront | ~$10 | 정적 사이트, API 캐시 |
| 모니터링 | Sentry + Slack | ~$30 | 에러 추적, 알림 |
| 데이터 API | FRED, NewsAPI 등 | ~$50 | 프리미엄 데이터 피드 |
| CI/CD | GitHub Actions | 무료 | 자동화 파이프라인 |
| **합계** | | **~$185/월** | |

---

## 백테스트 검증 결과

### 핵심 성과 지표 (2025-03-07 ~ 2026-03-06, 1년)

| 지표 | ATS 3.0 전략 | Buy & Hold | 비고 |
|:-----|:------------|:-----------|:-----|
| 총 수익률 | +0.12% | -25.38% | 하락장 방어 |
| 최대 낙폭 (MDD) | 6.93% | 63.58% | **9배 리스크 감소** |
| 최종 자본 | 10,011,888 KRW | 7,462,028 KRW | +2.55M 차이 |
| 초과수익 (Alpha) | +25.50%p | - | 벤치마크 대비 |
| Sharpe Ratio | 0.81 | - | |
| Sortino Ratio | 1.62 | - | 하방 리스크 대비 양호 |
| Omega Ratio | 1.66 | - | 손익 분포 양호 |
| 승률 | 45.76% | - | 평균수익 7.26% > 평균손실 3.13% |
| Monte Carlo 손실확률 | 0.0% | - | 500회 시뮬레이션 |

### 시그널 품질 (IC/ICIR)

| 지표 | IC | 방향 |
|:-----|:--|:-----|
| EMA | 0.0221 | + |
| MOMENTUM | 0.0216 | + |
| VOLUME | 0.0211 | + |
| BB | 0.0158 | + |
| RSI | 0.0122 | + |
| MACD | 0.0069 | + |

최적 Horizon: 3 candles (IC=0.0302)

### CVaR 꼬리위험

| 지표 | 값 |
|:-----|:--|
| VaR (95%) | 0.098% |
| Historical CVaR | 1.97% |
| Parametric CVaR | 7.97% |
| Tail Ratio | 20.12 |

---

## 로컬 개발 환경

### 필수 요건

- Python 3.10+
- Ruby 3.x + Bundler (investing repo)
- Docker (crypto repo, 선택)
- Git

### 빠른 시작

```bash
# 1. investing repo (데이터 파이프라인)
cd ~/Desktop/investing
bundle install
pip install -r scripts/requirements.txt
bundle exec jekyll serve          # http://localhost:4000

# 2. crypto repo (퀀트 엔진)
cd ~/Desktop/crypto/crypto-monitoring
cp .env.example .env              # API 키 설정
pip install -r requirements.txt
python quant_trader.py            # Paper Trading 시작

# 3. 대시보드
DASHBOARD_ENABLED=true python monitor.py  # http://localhost:8000
```

---

## 라이선스

MIT License
