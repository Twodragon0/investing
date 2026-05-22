# `scripts/common/post_html.py` — 일일 리포트 HTML 빌더 가이드

> 7개 daily-report collector가 공통으로 사용하는 HTML 블록 빌더 모음. 단일 소스
> 도입으로 stat-grid / alert-box / footer-meta / lead 문장 컨벤션이 한 군데에서
> 결정되도록 설계되었다.

## 함수 요약

| 함수 | 출력 |
|------|------|
| `stat_grid(items)` | `<div class="stat-grid">` + N개 `<div class="stat-item">` |
| `alert_box(title, bullets, variant)` | `<div class="alert-box alert-{variant}">` + SVG 아이콘 + `<ul>` |
| `summary_intro(date, label, headline, *, tag, detail)` | 마크다운 lead 문장 (post-summary excerpt) |
| `footer_meta(timestamp, sources)` | `<div class="wm-footer-meta">` (수집 시각 + 소스) |

## `summary_intro` — lead 문장

```python
post_html.summary_intro(
    date="2026-05-22",
    label="지정학 핵심 이슈",
    headline="Trump Warns Iran of Renewed Military Action",
    tag="GDELT",
    detail="주요 테마는 **군사/분쟁**이며, Polymarket 0건·GDELT 30건·뉴스 0건을 종합 분석했습니다",
)
# → "**2026-05-22** 지정학 핵심 이슈: **Trump Warns Iran of Renewed Military Action** (GDELT). 주요 테마는 **군사/분쟁**이며 ...\n"
```

### `tag` 슬롯 의미 가이드

`tag`는 헤드라인 뒤 괄호 안에 표기되는 **단일 컨텍스트 태그**다. 의미는 의도적으로
generic — collector마다 가장 의미 있는 단일 한정자를 매핑한다.

| collector | tag 의미 | 예시 |
|-----------|---------|------|
| `geopolitical` | 데이터 소스 (Polymarket / GDELT / Google News) | `tag="GDELT"` |
| `worldmonitor` | top theme classification | `tag="지정학/안보"` |
| `fmp_calendar` | secondary 시그널 (top earnings) | `tag="실적: NVDA/NVIDIA"` |
| `crypto_news` | 미사용 (헤드라인만으로 충분) | `tag=None` |
| `political_trades` | 미사용 | `tag=None` |
| `regulatory` | 미사용 | `tag=None` |
| `social_media` | 미사용 | `tag=None` |

**선택 기준** (어떤 값을 tag에 둘지)
- 헤드라인이 출처에 따라 신뢰도가 다르면 → **데이터 소스** (geopolitical)
- 헤드라인이 광범위한 카테고리 중 하나라면 → **테마** (worldmonitor)
- 1개 헤드라인 + 1개 보조 시그널이 있으면 → **보조 시그널** (fmp_calendar)
- 그 외에는 `None` (생략)

### 헤드라인 없을 때 폴백

```python
post_html.summary_intro("2026-05-22", "암호화폐 시장", None, detail="93건 분석")
# → "**2026-05-22** 암호화폐 시장 — 93건 분석\n"

post_html.summary_intro("2026-05-22", "오늘 보고", None)
# → "**2026-05-22** 오늘 보고.\n"
```

## `stat_grid` — 통계 그리드

```python
post_html.stat_grid([
    ("930.3 EH/s", "BTC 해시레이트"),
    ("600,100", "BTC 일일 트랜잭션"),
    ("0.12 Gwei", "ETH 가스"),
])
# → <div class="stat-grid">
#      <div class="stat-item"><div class="stat-value">930.3 EH/s</div><div class="stat-label">BTC 해시레이트</div></div>
#      ...
#    </div>
```

**컨벤션**
- 3~4개 stat 권장 (5개 초과 시 모바일에서 줄바꿈 빈번)
- "데이터 소스 N개" 같은 메타 stat은 footer_meta로 이동
- value는 단위 포함 (예: `"$76,354"`, `"0.12 Gwei"`)

## `alert_box` — 콜아웃 박스

```python
post_html.alert_box(
    "오늘의 글로벌 리스크 스냅샷",
    ["총 수집: <strong>20건</strong>", "핵심 테마: <strong>지정학/안보</strong>"],
    variant="info",
)
# → <div class="alert-box alert-info"><strong><svg ...>ℹ</svg> 오늘의 글로벌 리스크 스냅샷</strong>
#      <ul><li>...</li><li>...</li></ul>
#    </div>
```

### Variant 의미 가이드

| variant | 색상 | 의미 | 사용처 |
|---------|------|------|--------|
| `info` | 파랑 | 데이터 집계 결과, 일반 요약 | 일상 스냅샷 (worldmonitor, coinmarketcap 24h, political_trades) |
| `warning` | 황금 | 리스크 판단 / 레벨 평가 포함 | 지정학 리스크 스냅샷 (geopolitical) |
| `urgent` | 빨강 | P0 긴급 이벤트, 즉각 조치 권고 | summarizer P0 alert (crypto_news 등 P0 이슈 발생 시) |

### 접근성 (WCAG 1.1.1 / 1.4.1)

- variant별 인라인 SVG 아이콘이 자동 prepend됨 (이모지 의존성 X)
- SVG는 `aria-hidden="true"` — 의미는 title이 전달
- `fill="currentColor"` 로 다크/라이트 자동 적응
- 색상 외 식별 신호: 좌측 border-color + SVG 아이콘 모양 → 색맹 사용자도 식별 가능

## `footer_meta` — 포스트 푸터

```python
post_html.footer_meta(
    "2026-05-22 12:30 KST",
    ["Blockchain.com", "Etherscan"],   # 또는 "Blockchain.com, Etherscan" 문자열 직접
)
# → <div class="wm-footer-meta">
#      <span>수집 시각: 2026-05-22 12:30 KST</span>
#      <span>소스: Blockchain.com, Etherscan</span>
#    </div>
```

- `sources`는 list/tuple 또는 string 모두 수용 (list는 자동 ", " join)
- 빈 list/string → "소스: N/A"로 폴백

## 사용 예시 — 일반 collector 구조

```python
from common import post_html

def build_content(today: str, items: list[dict]) -> str:
    # 1. Lead (becomes page.excerpt → post-summary section)
    top_headline = (items[0].get("title_ko") or items[0].get("title", ""))[:80] if items else ""
    lead = post_html.summary_intro(
        today,
        "오늘의 핵심" if top_headline else "오늘 보고",
        top_headline or None,
        detail=f"총 {len(items)}건 정리",
    )

    # 2. Stat grid (한눈에 보기)
    grid = post_html.stat_grid([
        (str(len(items)), "수집 건수"),
        # ...
    ])

    # 3. Alert callout
    alert = post_html.alert_box(
        "오늘의 요약",
        [f"건수: <strong>{len(items)}</strong>건"],
        variant="info",
    )

    # 4. Body sections (대문자/번호식 ## 1. ## 2. ... 자체 구현)
    # ...

    # 5. Footer
    footer = post_html.footer_meta(
        f"{today} KST",
        ["Source A", "Source B"],
    )

    return "\n\n".join([lead, grid, alert, "## 1. 본문 ...", footer])
```

## 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-05-22 | 모듈 신설 (stat_grid / alert_box / footer_meta) |
| 2026-05-22 | summary_intro 추가, 6 collector 마이그레이션 |
| 2026-05-22 | alert_box variant별 이모지 prefix 추가 |
| 2026-05-23 | 이모지 → 인라인 SVG, source → tag rename |
| 2026-05-23 | summarizer P0 alert도 alert_box(variant="urgent")로 통합 |
