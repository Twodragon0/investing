# Collector Description Boilerplate Audit

Generated: 2026-05-06

## Summary

- Total files scanned: 13
- Fixed-boilerplate sites found: 18
- HIGH priority (description_ko static suffix on daily digest): 9
- MEDIUM priority (body opening with static phrase): 6
- LOW priority (section header / boilerplate label): 3
- Already fixed: 3 files / 5 sites (crypto_news:855, social_media:655+1099, regulatory:430+808)

---

## High Priority — description_ko static suffixes in daily digests

These suffixes are appended unconditionally and appear **identical in every daily post** for
that collector — identical text blocks that Google de-duplication heuristics will treat as thin
content.

---

### scripts/collect_fmp_calendar.py:552

- **Current:** `_desc_ko += "FMP API 기반 주요 경제 이벤트·실적·국채 금리를 정리합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 552):**
  - `earnings` list (length + company names e.g. `earnings[0]["name"]`)
  - `economic_events` list (high-impact events, `economic_events[0]["name"]`)
  - `indices` list (market index levels e.g. SPX value)
  - `ipo_data` list (company names + sizes)
  - `treasury_rates` (yield values for 2y/10y)
- **Proposed fix:** Replace static suffix with a data-driven tail. Example:
  ```python
  _next_event = economic_events[0]["name"][:30] if economic_events else ""
  _next_earn = earnings[0]["name"][:20] if earnings else ""
  if _next_event:
      _desc_ko += f"주목 이벤트: {_next_event}."
  elif _next_earn:
      _desc_ko += f"주목 실적: {_next_earn} 등."
  ```
  Fallback: omit the suffix entirely (count-only description is already informative).
- **Priority:** HIGH

---

### scripts/collect_defi_llama.py:1084

- **Current:** `_desc_ko += "프로토콜별 예치 자산과 체인 점유율을 분석합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 1080–1084):**
  - `protocols` list with `name`, `tvl` per protocol
  - `chains` list with chain names and TVL values
  - `_top3` already computed: top-3 protocol names
  - `total_protocol_tvl` and `total_chain_tvl` available in `build_post_content` scope (can be
    passed up or recomputed from `protocols`/`chains` lists)
- **Proposed fix:** Replace with the leading chain's TVL or the delta vs previous day:
  ```python
  _top_chain = chains[0].get("name", "") if chains else ""
  _top_chain_tvl = _format_tvl(chains[0].get("tvl", 0)) if chains else ""
  if _top_chain:
      _desc_ko += f"선두 체인: {_top_chain} TVL {_top_chain_tvl}."
  ```
  Fallback: omit the suffix (preceding sentence with top-3 names is already unique).
- **Priority:** HIGH

---

### scripts/collect_blockchain.py:338

- **Current:** `_desc_ko += "온체인 데이터 기반 네트워크 건전성 및 활동 지표를 분석합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 328–338):**
  - `btc` dict with `hashrate`, `difficulty`, `mempool_size`
  - `eth` dict with `gas_price` or similar
  - `l2_projects` list with names and TVL
  - `_desc_parts_bc` already lists which networks are covered
- **Proposed fix:** Append a live metric instead of the static sentence:
  ```python
  if btc and btc.get("hashrate"):
      _desc_ko += f"BTC 해시레이트: {btc['hashrate']}."
  elif eth and eth.get("gas_price"):
      _desc_ko += f"ETH 가스: {eth['gas_price']} Gwei."
  ```
  Fallback: omit the suffix.
- **Priority:** HIGH

---

### scripts/collect_political_trades.py:510

- **Current:** `_desc_ko += "의회·SEC 내부자 거래 및 정책 이벤트를 모니터링합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 507–510):**
  - `congress_count`, `sec_count`, `trump_count`, `korea_count`, `cb_count`
  - `unique_items` — list of trade records with `ticker`, `politician` fields
  - Top traded ticker can be derived: `Counter(i.get("ticker","") for i in unique_items).most_common(1)`
- **Proposed fix:** Replace with the most-mentioned ticker or politician name:
  ```python
  _top_ticker = Counter(i.get("ticker", "") for i in unique_items if i.get("ticker")).most_common(1)
  if _top_ticker:
      _desc_ko += f"최다 거래 종목: {_top_ticker[0][0]}."
  ```
  Fallback: omit suffix.
- **Priority:** HIGH

---

### scripts/collect_market_indicators.py:1290

- **Current:** `_desc_ko += "공포탐욕지수·VIX·국채금리 등 핵심 시장 센티먼트 지표를 분석합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 1279–1290):**
  - `self._cnn_fg` dict with `score` and `rating` already used in `_desc_parts_mi`
  - `self._market_data["VIX"]["price_fmt"]` already used
  - `self._market_data.get("US10Y")` for 10-year yield
  - `self._market_data.get("DXY")` already used
- **Proposed fix:** If `_desc_parts_mi` already contains live values, omit the static suffix entirely — the preceding dynamic sentence is already specific. Or append the 10Y yield:
  ```python
  _10y = self._market_data.get("US10Y", {}).get("price_fmt", "")
  if _10y:
      _desc_ko += f"미국 10년물 {_10y}."
  ```
  Fallback: drop suffix (first sentence with actual numbers is unique enough).
- **Priority:** HIGH

---

### scripts/collect_geopolitical.py:918

- **Current:** `_desc_ko += f"Polymarket·GDELT·뉴스 {source_count}개 소스에서 분쟁·제재·무역 리스크를 분석합니다."`
- **Type:** description_ko suffix — partially dynamic (`source_count` variable) but the rest of
  the phrase (`분쟁·제재·무역 리스크를 분석합니다`) is **always identical text** — HIGH SEO impact
- **Available data (in scope at line 907–918):**
  - `_top_geo_themes` already computed (top-3 themes from `theme_counter.most_common(3)`)
  - `markets` (Polymarket prediction market titles)
  - `gdelt_articles` with tones/scores
- **Proposed fix:** The static tail phrase after the source count is redundant because `_top_geo_themes` is already injected above it. Replace the fixed tail with the top Polymarket market title:
  ```python
  _top_market = markets[0].get("question", "")[:40] if markets else ""
  if _top_market:
      _desc_ko += f"주목 시장: {_top_market}."
  else:
      _desc_ko += f"{source_count}개 소스 기반 분석."
  ```
- **Priority:** HIGH

---

### scripts/collect_defi_yields.py:384

- **Current:** `"스테이블코인·ETH·BTC 카테고리별 최고 수익률 프로토콜을 분석합니다."`
- **Type:** description_ko static suffix — HIGH SEO impact
- **Available data (in scope at line 376–384):**
  - `top_stable_project` (name of #1 stablecoin pool)
  - `top_stable_apy` (APY value of #1 stablecoin pool)
  - `avg_apy` (overall average APY)
  - ETH and BTC top pools also available via `categories["eth"]`, `categories["btc"]`
- **Proposed fix:** The prefix of this description already has specific APY numbers. Drop the
  static suffix entirely — the `top_stable_apy` + `avg_apy` sentence above it is already unique:
  ```python
  _top_eth = categories["eth"][0].get("project", "") if categories.get("eth") else ""
  if _top_eth:
      _desc_ko = _desc_ko.rstrip(".") + f", ETH TOP: {_top_eth}."
  # else: omit — existing numbers are sufficient
  ```
- **Priority:** HIGH

---

### scripts/collect_coinmarketcap.py:1243 (fallback path)

- **Current:** `_desc_ko = "크립토 시장 리포트"` (fallback when `_btc` is None)
- **Type:** description_ko — fully static with zero dynamic content — HIGH SEO impact
- **Available data (in scope at line 1230–1249):**
  - `top_coins` list — coin names always available even when BTC lookup fails
  - `global_data` dict — `market_cap_percentage`, `total_market_cap`, `active_cryptocurrencies`
  - `_fg_val` / `_fg_label` — Fear & Greed index values
- **Proposed fix:** Build a fallback from `global_data` or `top_coins`:
  ```python
  if not _btc:
      _total_mc = global_data.get("total_market_cap", {}).get("usd", 0) if global_data else 0
      if _total_mc:
          _desc_ko = f"크립토 총 시가총액 ${_total_mc/1e12:.2f}T, 상위 {len(top_coins)}개 코인 분석."
      else:
          _desc_ko = f"크립토 시장 상위 {len(top_coins)}개 코인 분석."
  ```
- **Priority:** HIGH

---

### scripts/collect_worldmonitor_news.py:1054 (static tail)

- **Current:** `_desc_ko += f"GDELT·Polymarket 등 {len(source_counter)}개 소스 기반 지정학·에너지·금융 동향."`
- **Type:** description_ko suffix — `len(source_counter)` varies but `지정학·에너지·금융 동향` is
  **always identical** — MEDIUM-HIGH SEO impact
- **Available data (in scope at line 1040–1054):**
  - `_headline_titles` — up to 2 headline fragments already assembled
  - `_top_themes` — top 2 theme labels already in the first part of `_desc_ko`
  - `source_counter.most_common(1)` — dominant source name
- **Proposed fix:** Replace fixed tail with the top source name:
  ```python
  _top_src = source_counter.most_common(1)[0][0] if source_counter else ""
  if _top_src:
      _desc_ko += f"주요 출처: {_top_src} 등 {len(source_counter)}개 소스."
  ```
- **Priority:** HIGH (description_ko daily digest)

---

## Medium Priority — body openings with static phrases

These strings appear as the **first content paragraph** of the post body. They differ from day
to day only in count numbers, but the surrounding phrase is word-for-word identical every day.

---

### scripts/collect_political_trades.py:580

- **Current:** `content_parts.append("미국 정치인 거래 동향과 주요 정책 변동을 분석한 일일 리포트입니다.")`
- **Type:** body opening — static sentence with zero dynamic data — MEDIUM SEO impact
- **Available data (in scope at line 578–580):**
  - `sources_str` already computed — lists source categories with counts
  - `total_count` — total item count
  - `self.today` — date string
- **Proposed fix:** Replace with a sentence that includes live counts:
  ```python
  content_parts.append(
      f"**{self.today}** 미국 의회·SEC·행정부 정치인 거래 및 정책 이벤트 "
      f"총 **{total_count}건** — {sources_str}."
  )
  ```
- **Priority:** MEDIUM

---

### scripts/collect_defi_yields.py:181

- **Current:** `f"**{today}** DeFi Llama Yields API 기준 주요 DeFi 수익률(APY) 현황을 정리합니다. "`
  followed by `f"TVL $1M 이상, APY 0.1% 이상 풀 **{total_pools}개** 기준이며, "` (same append)
- **Type:** body opening first sentence — the phrase `DeFi Llama Yields API 기준 주요 DeFi 수익률(APY) 현황을 정리합니다` is identical every day — MEDIUM SEO impact
- **Available data (in scope at line 174–184):**
  - `total_pools`, `avg_apy`, `max_apy_project`, `max_apy_val` all computed above
- **Proposed fix:** Front-load the highest-APY protocol name so the opening sentence is unique:
  ```python
  f"**{today}** 기준 TVL $1M↑·APY 0.1%↑ 풀 **{total_pools}개**. "
  f"최고 APY 프로토콜: **{max_apy_project}** ({max_apy_val:.1f}%). "
  f"스테이블코인·ETH·BTC 카테고리별 수익률 분석.\n"
  ```
- **Priority:** MEDIUM

---

### scripts/collect_defi_llama.py:643

- **Current:** `f"**{today}** DeFi Llama 기준 DeFi 생태계 TVL(Total Value Locked, 총 예치 자산) 현황을 정리합니다. "`
- **Type:** body opening — the phrase `DeFi Llama 기준 DeFi 생태계 TVL(Total Value Locked, 총 예치 자산) 현황을 정리합니다` is fully static — MEDIUM SEO impact
- **Available data (in scope at line 638–645):**
  - `total_protocol_tvl`, `total_chain_tvl` already computed
  - `protocols[:1]` for the #1 protocol name
- **Proposed fix:**
  ```python
  _top_proto = protocols[0].get("name", "") if protocols else ""
  f"**{today}** DeFi 생태계 TVL: 상위 {len(protocols)}개 프로토콜 {_format_tvl(total_protocol_tvl)}, "
  f"상위 {len(chains)}개 체인 {_format_tvl(total_chain_tvl)}. "
  f"{'1위: ' + _top_proto + '.' if _top_proto else ''}\n"
  ```
- **Priority:** MEDIUM

---

### scripts/collect_market_indicators.py:810

- **Current:** `parts.append(f"**{today}** 기준 시장 심리·리스크 지표를 {source_count}개 소스에서 수집했습니다.\n")`
- **Type:** body opening — `시장 심리·리스크 지표를 ... 소스에서 수집했습니다` is word-for-word identical with only `source_count` varying — MEDIUM SEO impact
- **Available data (in scope at `build_post_content` function, line ~800–810):**
  - `cnn_fg["score"]` and `cnn_fg["rating"]` — Fear & Greed score
  - `market_data.get("VIX")["price_fmt"]` — VIX value
- **Proposed fix:**
  ```python
  _fg_str = f" 공포탐욕 {cnn_fg['score']}({_rating_to_korean(cnn_fg.get('rating',''))})" if cnn_fg else ""
  _vix_str = f", VIX {market_data['VIX']['price_fmt']}" if market_data.get("VIX") else ""
  parts.append(
      f"**{today}** 기준 시장 지표{_fg_str}{_vix_str}. {source_count}개 소스 수집.\n"
  )
  ```
- **Priority:** MEDIUM

---

### scripts/collect_crypto_news.py:1377

- **Current:** `content_parts = [f"블록체인 보안 관련 뉴스 {len(all_security_items)}건을 정리합니다.\n"]`
- **Type:** body opening for blockchain security sub-post — the phrase `블록체인 보안 관련 뉴스 ... 건을 정리합니다` appears identical in structure every day — MEDIUM SEO impact
- **Available data (in scope at line 1377–1383):**
  - `rekt_items` list — contains exploit/hack descriptions and fund-loss amounts
  - `google_security_items` — contains news titles
  - Top Rekt item title: `rekt_items[0].get("title", "")` if available
- **Proposed fix:**
  ```python
  _top_rekt = rekt_items[0].get("title", "")[:50] if rekt_items else ""
  if _top_rekt:
      content_parts = [
          f"블록체인 보안 {len(all_security_items)}건 분석. 주목 사건: {_top_rekt}.\n"
      ]
  else:
      content_parts = [
          f"블록체인 보안 뉴스 {len(all_security_items)}건 수집 (Rekt {len(rekt_items)}건 포함).\n"
      ]
  ```
- **Priority:** MEDIUM

---

### scripts/collect_worldmonitor_news.py:801 (body section label)

- **Current:** `"- 범위: 글로벌 지정학, 금융시장, 에너지 이슈"` (static bullet in body opening section)
- **Type:** body opening bullet point — always the same three categories regardless of actual
  day's content distribution — LOW-MEDIUM SEO impact
- **Available data (in scope at line 789–802):**
  - `theme_counter` — Counter of actual themes for that day (varies daily)
  - `source_counter` — actual sources used
- **Proposed fix:** Replace with the top 3 actual themes from `theme_counter`:
  ```python
  top3_themes = ", ".join(t for t, _ in theme_counter.most_common(3))
  f"- 범위: {top3_themes if top3_themes else '글로벌 지정학, 금융시장, 에너지'}"
  ```
- **Priority:** MEDIUM

---

## Low Priority — section headers / explanatory boilerplate

These are static explanatory labels inside section bodies. They don't appear in Google's 160-char
excerpt window but contribute to overall content duplication signals.

---

### scripts/collect_geopolitical.py:1021

- **Current:** `"감성 분석 점수를 제공합니다. 음수 톤은 부정적 보도를 의미합니다.\n"`
- **Type:** section intro for GDELT block — identical in every post — LOW SEO impact
- **Available data:** `gdelt_articles` list with tone scores
- **Proposed fix:** Prepend the average tone score to make it day-specific:
  ```python
  _avg_tone = sum(a.get("avg_tone", 0) for a in gdelt_articles) / len(gdelt_articles) if gdelt_articles else 0
  f"감성 분석 점수 포함 (평균 톤: {_avg_tone:.1f}). 음수 톤은 부정적 보도를 의미합니다.\n"
  ```
- **Priority:** LOW

---

### scripts/collect_defi_yields.py:209–210

- **Current:**
  ```
  "USDC, USDT, DAI 등 스테이블코인 기반 풀을 APY 기준으로 정렬한 결과입니다. "
  "원금 가치 보존을 원하는 투자자에게 적합합니다.\n"
  ```
- **Type:** section label before stablecoin pool table — fully static — LOW SEO impact
- **Available data:** `stablecoin_pools` list, pool count and APY values
- **Proposed fix:**
  ```python
  f"TVL $1M↑ 스테이블코인 풀 {len(stablecoin_pools)}개 (USDC·USDT·DAI 등), APY 기준 정렬. "
  f"최고 수익: {stablecoin_pools[0].get('project','')} {stablecoin_pools[0].get('apy',0):.1f}%.\n"
  ```
- **Priority:** LOW

---

### scripts/collect_stock_news.py:973 (else-branch fallback)

- **Current:** `"주요 동향과 투자 포인트를 정리합니다."` (else-branch when `kr_summary_parts` empty)
- **Type:** description_ko else-branch suffix — partially static — LOW SEO impact (rare path,
  fires only when Korean market data API fails)
- **Available data (in scope at line 971–973):**
  - `len(all_items)` — item count always available
  - `global_rows`, `korean_rows` — at minimum counts are available
- **Proposed fix:** The else-branch already includes item count. The suffix `주요 동향과 투자 포인트를 정리합니다` is the boilerplate. Replace with:
  ```python
  _desc_ko = (
      f"{today} 주식 시장 뉴스 종합 — 글로벌 {len(global_rows)}건·한국 {len(korean_rows)}건, "
      f"총 {len(all_items)}건 분석."
  )
  ```
  (Drop the repeated static suffix entirely.)
- **Priority:** LOW (fallback path only)

---

## Not Flagged — already well-differentiated

These lines were inspected but are either fully dynamic or already flagged as DONE:

| File | Line | Reason not flagged |
|------|------|--------------------|
| `collect_crypto_news.py` | 852–860 | Already fixed per task spec (line 855) |
| `collect_social_media.py` | 655, 1099 | Already fixed per task spec |
| `collect_regulatory.py` | 430, 808 | Already fixed per task spec |
| `collect_coinmarketcap.py` | 1241+1244–1249 | Primary path is fully dynamic (BTC price + F&G + dominance); only fallback at :1243 is flagged |
| `collect_stock_news.py` | 963–968 | Primary branch has live Korean market prices — unique per day |
| `collect_geopolitical.py` | 907–910 | Top-themes sentence is dynamic; only the static tail at :918 is flagged |
| `collect_worldmonitor_news.py` | 789–796 | alert-box items are dynamic (total_items, top theme, top source); only static bullet at :801 flagged |
| `collect_fmp_calendar.py` | 419–425 | Body opening is fully dynamic (live counts per category) |
| `collect_political_trades.py` | 507–509 | `_desc_ko` first sentence is dynamic; only static suffix at :510 flagged |
| `collect_market_indicators.py` | 1287–1289 | `_desc_ko` with F&G + VIX values is dynamic; only static suffix at :1290 flagged |

---

## Implementation Estimate

- Total lines to modify: ~18 lines across 10 files
- Estimated effort: 25–35 agent-minutes for HIGH priority batch; 20 agent-minutes for MEDIUM
- Recommended batch approach:
  - **PR 1 (HIGH, ~9 changes):** `collect_fmp_calendar.py:552`, `collect_defi_llama.py:1084`,
    `collect_blockchain.py:338`, `collect_political_trades.py:510`,
    `collect_market_indicators.py:1290`, `collect_geopolitical.py:918`,
    `collect_defi_yields.py:384`, `collect_coinmarketcap.py:1243`,
    `collect_worldmonitor_news.py:1054`
  - **PR 2 (MEDIUM body openings, ~6 changes):** `collect_political_trades.py:580`,
    `collect_defi_yields.py:181`, `collect_defi_llama.py:643`,
    `collect_market_indicators.py:810`, `collect_crypto_news.py:1377`,
    `collect_worldmonitor_news.py:801`
  - **PR 3 (LOW section labels, ~3 changes):** `collect_geopolitical.py:1021`,
    `collect_defi_yields.py:209–210`, `collect_stock_news.py:973`
- Verification for each PR: `python3 -m ruff check scripts/` + spot-check one generated post
  per modified collector.
